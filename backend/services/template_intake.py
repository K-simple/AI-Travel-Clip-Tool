"""模板导入：~30s 内完成切分 + AI 画面理解 + 字幕/花字特效分析。"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from services.processing_config import (
    ENABLE_SUBTITLE_DRIVEN_SLOT_SPLIT,
    ENABLE_SUBTITLE_TIMELINE_SCAN,
    SUBTITLE_SCAN_FPS,
    SUBTITLE_SLOT_STRATEGY,
    TEMPLATE_EXTRACT_AUDIO_EARLY,
    TEMPLATE_FAST_SKIP_AUTO_TUNE,
    TEMPLATE_INTAKE_AI_WORKERS,
    TEMPLATE_INTAKE_BUDGET_SEC,
    TEMPLATE_INTAKE_SUBTITLE_OCR,
    TEMPLATE_INTAKE_VISION_LABELS,
    TEMPLATE_SCENE_INTERVAL_FALLBACK,
    is_base_slot_creation_mode,
)
from services.scene_detector import (
    _attach_thumbnails,
    build_template_filmstrip,
    build_template_intake_slots,
    build_visual_cut_suggestions,
    extract_frame,
    get_video_duration,
)
from services.subtitle_config import get_subtitle_config, is_caption_slot_strategy, resolve_recognition_mode
from services.subtitle_quality import subtitle_text_from_segments


def _slot_ranges(slots: list[dict[str, Any]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for slot in slots:
        start = float(slot.get("start", slot.get("clip_start", 0)))
        end = float(slot.get("end", start + float(slot.get("duration", 0.1))))
        out.append((start, max(start + 0.08, end)))
    return out


def _apply_ocr_to_slots(slots: list[dict[str, Any]], ocr_batch: list[list]) -> None:
    for i, slot in enumerate(slots):
        segments = ocr_batch[i] if i < len(ocr_batch) else []
        text = subtitle_text_from_segments(segments)
        slot["subtitle_text"] = text
        slot["subtitle_segments"] = segments
        slot.setdefault("clip_start", float(slot.get("start", 0)))
        slot.setdefault("clip_end", float(slot.get("end", slot.get("clip_start", 0) + float(slot.get("duration", 0.1)))))
        if text:
            slot["subtitle_source"] = "visual"
            slot.setdefault("subtitle_quality", "ok")
        else:
            slot.setdefault("subtitle_source", "none")
            slot.setdefault("subtitle_quality", "empty")


def _full_video_speech_transcribe(
    file_path: str,
    template_dir: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """整段视频 ASR，生成 spoken_caption 主轨（先于画面切槽）。"""
    from services.speech_subtitle_pipeline import SpeechSubtitlePipeline
    from services.subtitle_config import get_subtitle_config
    from services.slot_subtitle import _normalize_segment_dict

    print("[intake][speech] full video ASR first")
    pipeline = SpeechSubtitlePipeline(get_subtitle_config())
    result = pipeline.run(file_path, work_dir=os.path.join(template_dir, "speech_asr"))
    spoken = result.get("spoken_captions") or []
    profile = result.get("effect_profile") or {}
    debug = result.get("debug") or {}

    normalized: list[dict[str, Any]] = []
    for seg in spoken:
        item = _normalize_segment_dict(seg)
        if item:
            normalized.append(item)

    print(f"[intake][speech] 主轨 spoken_caption={len(normalized)} 段")
    return spoken, normalized, profile, debug


def _split_speech_into_visual_slots(
    slots: list[dict[str, Any]],
    spoken_segments: list[dict[str, Any]],
    effect_profile: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """画面槽位生成后，从主轨切分槽位字幕（禁止重复 word）。"""
    from services.spoken_caption_split import split_spoken_caption_by_slots

    print("[intake][scene] visual slots generated after ASR")
    return split_spoken_caption_by_slots(
        spoken_segments,
        slots,
        effect_profile=effect_profile,
    )


def _batch_ocr(file_path: str, ranges: list[tuple[float, float]]) -> list[list]:
    if not ranges or not TEMPLATE_INTAKE_SUBTITLE_OCR:
        return [[] for _ in ranges]

    try:
        from services.subtitle_ocr import recognize_slots_visual_batch

        # intake 阶段固定快速 OCR，与 SUBTITLE_RECOGNITION_MODE（精识别）解耦
        return recognize_slots_visual_batch(file_path, ranges, quality=False)
    except Exception as exc:
        print(f"模板 intake OCR 跳过: {exc}")
        return [[] for _ in ranges]


def _enrich_slot_intake(
    index: int,
    slot: dict[str, Any],
    video_path: str,
    work_dir: str,
) -> tuple[int, dict[str, Any]]:
    item = dict(slot)
    thumb = str(item.get("thumbnail") or "").strip()

    if TEMPLATE_INTAKE_VISION_LABELS and thumb and os.path.isfile(thumb):
        try:
            from services.ai_label_enricher import apply_template_slot_vision

            apply_template_slot_vision(item)
        except Exception as exc:
            print(f"槽位 AI 标签失败 #{index + 1}: {exc}")

    text = str(item.get("subtitle_text") or "").strip()
    segments = list(item.get("subtitle_segments") or [])

    try:
        from services.processing_config import ENABLE_SUBTITLE_SCENE_AI

        if ENABLE_SUBTITLE_SCENE_AI and text:
            from services.subtitle_scene_ai import analyze_slot_subtitle_scene

            patch = analyze_slot_subtitle_scene(
                video_path,
                item,
                text,
                segments,
                index=index,
                work_dir=os.path.join(work_dir, "subtitle_scene"),
                use_vision=False,
            )
            if patch:
                item.update(patch)
        elif text or segments:
            from services.subtitle_style_analyzer import analyze_segment_style

            start = float(item.get("start", item.get("clip_start", 0)))
            end = float(item.get("end", start + float(item.get("duration", 0.1))))
            style = analyze_segment_style(
                video_path,
                {"start": start, "end": end, "text": text},
                os.path.join(work_dir, "subtitle_style"),
                use_vision=False,
            )
            item["subtitle_style"] = style
            if style.get("style_label"):
                item["subtitle_effect_label"] = style["style_label"]
            if segments:
                merged = []
                for seg in segments:
                    if isinstance(seg, dict):
                        merged.append({**seg, "style": {**(seg.get("style") or {}), **style}})
                    else:
                        merged.append(seg)
                item["subtitle_segments"] = merged
    except Exception as exc:
        print(f"槽位花字分析失败 #{index + 1}: {exc}")

    try:
        from services.effects_catalog import enrich_slot_catalog_understanding

        item = enrich_slot_catalog_understanding(item)
    except Exception:
        pass

    return index, item


def _parallel_enrich_slots(
    slots: list[dict[str, Any]],
    video_path: str,
    work_dir: str,
) -> list[dict[str, Any]]:
    if not slots:
        return slots
    workers = max(1, min(TEMPLATE_INTAKE_AI_WORKERS, len(slots)))
    results: list[dict[str, Any] | None] = [None] * len(slots)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_enrich_slot_intake, i, slot, video_path, work_dir)
            for i, slot in enumerate(slots)
        ]
        for fut in as_completed(futures):
            try:
                idx, item = fut.result()
                results[idx] = item
            except Exception as exc:
                print(f"槽位并行 enrich 失败: {exc}")
    return [results[i] if results[i] is not None else dict(slots[i]) for i in range(len(slots))]


def _process_template_intake_base_only(
    template_id: str,
    file_path: str,
    template_dir: str,
    duration: float,
    thumb_dir: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    extract_audio_fn: Callable[[str, str], None] | None = None,
    has_audio_fn: Callable[[str], bool] | None = None,
    t0: float,
    bump: Callable[[int], None],
) -> list[dict[str, Any]]:
    """base 模式：上传后仅 1 个全片槽；不 ASR、不 PySceneDetect 切槽。"""
    _ = on_progress

    def _audio_early() -> None:
        if not TEMPLATE_EXTRACT_AUDIO_EARLY or not extract_audio_fn or not has_audio_fn:
            return
        if not has_audio_fn(file_path):
            return
        out = os.path.join(template_dir, "template_audio.m4a")
        try:
            extract_audio_fn(file_path, out)
        except Exception as exc:
            print(f"模板 intake 音频提取失败: {exc}")

    bump(20)
    with ThreadPoolExecutor(max_workers=2) as pool:
        audio_f = pool.submit(_audio_early)
        slots_f = pool.submit(
            build_template_intake_slots,
            file_path,
            thumb_dir,
            duration,
            skip_auto_tune=True,
            skip_ai_refine=True,
            extract_thumbs=True,
            allow_interval_fallback=False,
        )
        slots = slots_f.result()
        audio_f.result()

    if not slots:
        raise RuntimeError("未能创建 base 画面槽")

    suggestions = build_visual_cut_suggestions(file_path, thumb_dir, duration)
    if suggestions:
        from services.template_processor import _update_template

        _update_template(
            template_id,
            ai_vision_json={"visualCutSuggestions": suggestions},
        )

    bump(55)
    if any(not str(s.get("thumbnail") or "").strip() for s in slots):
        slots = _attach_thumbnails(file_path, thumb_dir, slots)

    slots = _clip_only_enrich(slots, file_path)

    filmstrip_path = os.path.join(thumb_dir, "filmstrip.jpg").replace("\\", "/")
    filmstrip_meta = build_template_filmstrip(file_path, filmstrip_path, duration)
    if filmstrip_meta:
        for slot in slots:
            if isinstance(slot, dict):
                slot["filmstrip"] = filmstrip_meta["path"]
                slot["filmstrip_frames"] = filmstrip_meta["frame_count"]
                slot["filmstrip_tile_width"] = filmstrip_meta["tile_width"]
                slot["filmstrip_fps"] = filmstrip_meta.get("fps")

    from services.timeline_thumbnails import pregenerate_timeline_thumbnails_for_intake

    pregenerate_timeline_thumbnails_for_intake(file_path, template_id)

    bump(92)

    elapsed = time.monotonic() - t0
    print(
        f"模板 intake [base] 完成 [{template_id}]: {elapsed:.1f}s, "
        f"1 全片槽（{duration:.1f}s）；字幕识别与 AI 画面切分请在前端手动触发"
    )
    return slots


def process_template_intake(
    template_id: str,
    file_path: str,
    template_dir: str,
    *,
    on_progress: Callable[[int], None] | None = None,
    extract_audio_fn: Callable[[str, str], None] | None = None,
    has_audio_fn: Callable[[str], bool] | None = None,
    file_ok_fn: Callable[[str], bool] | None = None,
) -> list[dict[str, Any]]:
    """
    模板上传后主流程。
    base 模式：仅全片单槽 + 可选画面建议线；字幕识别与 AI 画面切分由用户按钮触发。
    auto_visual 模式：保留 PySceneDetect + 可选 intake 字幕（旧行为）。
    """
    t0 = time.monotonic()

    def bump(p: int) -> None:
        if on_progress:
            on_progress(p)

    bump(8)
    duration = get_video_duration(file_path)
    if duration <= 0:
        raise RuntimeError("无法读取模板视频时长")

    thumb_dir = os.path.join("storage", "thumbnails", template_id)
    os.makedirs(thumb_dir, exist_ok=True)
    main_thumb = os.path.join(thumb_dir, "main.jpg").replace("\\", "/")
    extract_frame(file_path, max(duration / 2, 0.5), main_thumb)

    bump(12)

    if is_base_slot_creation_mode():
        return _process_template_intake_base_only(
            template_id,
            file_path,
            template_dir,
            duration,
            thumb_dir,
            on_progress=on_progress,
            extract_audio_fn=extract_audio_fn,
            has_audio_fn=has_audio_fn,
            t0=t0,
            bump=bump,
        )

    intake_rec_mode = resolve_recognition_mode("auto")
    subtitle_cfg = get_subtitle_config()
    use_caption_slot = is_caption_slot_strategy(subtitle_cfg.cut_strategy)
    spoken_segments: list[dict[str, Any]] = []
    spoken_normalized: list[dict[str, Any]] = []
    effect_profile: dict[str, Any] = {}
    split_debug: dict[str, Any] = {}
    caption_slot_debug: dict[str, Any] = {}
    subtitle_clips: list[dict[str, Any]] = []
    speech_ok = False
    slots: list[dict[str, Any]] = []

    if use_caption_slot:
        print("[intake][caption_slot] 阶段一：ASR+OCR → sentenceClips（不重建画面槽）")
        try:
            from services.caption_slot_builder import run_caption_recognition_pipeline
            from services.template_processor import _update_template

            rec = run_caption_recognition_pipeline(
                template_id,
                file_path,
                template_dir,
                duration=duration,
                config=subtitle_cfg,
                on_progress=lambda p: bump(min(42, 12 + int(p * 0.3))),
            )
            spoken_normalized = rec.get("spoken_segments") or []
            spoken_segments = spoken_normalized
            speech_ok = bool(spoken_normalized)
            caption_slot_debug = rec.get("caption_recognition_debug") or {}
            subtitle_clips = rec.get("sentence_clips") or []
            if spoken_normalized or subtitle_clips:
                _update_template(
                    template_id,
                    segments_json=spoken_normalized,
                    subtitle_clips_json=subtitle_clips,
                )
            print(f"[intake][caption_slot] clips={len(subtitle_clips)} (slots unchanged at intake)")
            use_caption_slot = False
        except Exception as exc:
            print(f"[intake][caption_slot] 识别失败，回退 visual 切槽: {exc}")
            use_caption_slot = False

    if not use_caption_slot and intake_rec_mode == "speech":
        try:
            spoken_segments, spoken_normalized, effect_profile, _asr_debug = _full_video_speech_transcribe(
                file_path, template_dir
            )
            speech_ok = bool(spoken_normalized)
            if speech_ok:
                from services.subtitle_clip_planner import build_subtitle_clips_from_asr
                from services.template_processor import _update_template

                subtitle_clips, _clip_debug = build_subtitle_clips_from_asr(spoken_normalized)
                print(f"[intake][speech] subtitleClips={len(subtitle_clips)} 条")
                _update_template(
                    template_id,
                    segments_json=spoken_normalized,
                    subtitle_clips_json=subtitle_clips,
                )
        except Exception as exc:
            print(f"[intake][speech] 整段 ASR 失败，将回退 OCR: {exc}")
            intake_rec_mode = "burned"

    bump(28)

    def _audio_early() -> None:
        if not TEMPLATE_EXTRACT_AUDIO_EARLY or not extract_audio_fn or not has_audio_fn:
            return
        if not has_audio_fn(file_path):
            return
        out = os.path.join(template_dir, "template_audio.m4a")
        try:
            extract_audio_fn(file_path, out)
        except Exception as exc:
            print(f"模板 intake 音频提取失败: {exc}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        audio_f = pool.submit(_audio_early)
        slots_f = pool.submit(
            build_template_intake_slots,
            file_path,
            thumb_dir,
            duration,
            skip_auto_tune=TEMPLATE_FAST_SKIP_AUTO_TUNE,
            skip_ai_refine=True,
            extract_thumbs=True,
            allow_interval_fallback=TEMPLATE_SCENE_INTERVAL_FALLBACK,
            on_progress=lambda p: bump(min(42, 12 + int(p * 0.28))),
        )
        slots = slots_f.result()
        audio_f.result()

    if not slots:
        raise RuntimeError("镜头切分未产生槽位")

    if is_base_slot_creation_mode():
        suggestions = build_visual_cut_suggestions(file_path, thumb_dir, duration)
        if suggestions:
            from services.template_processor import _update_template

            _update_template(
                template_id,
                ai_vision_json={"visualCutSuggestions": suggestions},
            )

    bump(45)

    if any(not str(s.get("thumbnail") or "").strip() for s in slots):
        slots = _attach_thumbnails(file_path, thumb_dir, slots)

    bump(48)

    ranges = _slot_ranges(slots)
    timeline_applied = False

    if (
        not is_base_slot_creation_mode()
        and speech_ok
        and spoken_segments
        and not is_caption_slot_strategy(subtitle_cfg.cut_strategy)
    ):
        slots, split_debug = _split_speech_into_visual_slots(slots, spoken_segments, effect_profile)
        timeline_applied = True
        subtitled = sum(1 for s in slots if str(s.get("subtitle_text") or "").strip())
        print(f"[intake][speech] 切槽完成: {subtitled}/{len(slots)} 槽有人声字幕")
    elif speech_ok and is_caption_slot_strategy(subtitle_cfg.cut_strategy):
        timeline_applied = True
        print(
            f"[intake][caption_slot] 已生成 {len(subtitle_clips)} 条字幕草稿，"
            f"画面槽保持{'base 全片槽' if is_base_slot_creation_mode() else 'PySceneDetect'}"
        )

    if (
        not is_base_slot_creation_mode()
        and not timeline_applied
        and intake_rec_mode == "burned"
        and ENABLE_SUBTITLE_TIMELINE_SCAN
        and TEMPLATE_INTAKE_SUBTITLE_OCR
    ):
        try:
            from services.subtitle_timeline_scan import (
                apply_subtitle_timeline_to_slots,
                probe_timeline_viable,
                scan_and_ocr_burned_timeline,
                split_slots_by_subtitle_timeline,
            )

            timeline = scan_and_ocr_burned_timeline(
                file_path,
                duration,
                quality=False,
                sample_fps=SUBTITLE_SCAN_FPS,
                on_segment_done=lambda done, total: bump(
                    48 + int(9 * done / max(1, total))
                ),
            )
            if probe_timeline_viable(timeline):
                before = len(slots)
                use_split = SUBTITLE_SLOT_STRATEGY == "split_distinct" or (
                    SUBTITLE_SLOT_STRATEGY not in ("align", "split_distinct")
                    and ENABLE_SUBTITLE_DRIVEN_SLOT_SPLIT
                )
                if use_split:
                    slots = split_slots_by_subtitle_timeline(
                        slots,
                        timeline,
                        video_path=file_path,
                        thumb_dir=thumb_dir,
                    )
                    mode = "按不同字幕拆槽"
                else:
                    slots = apply_subtitle_timeline_to_slots(slots, timeline)
                    mode = "对齐字幕(保留镜头槽)"
                timeline_applied = True
                print(
                    f"模板 intake 字幕时间轴: {len(timeline)} 句, "
                    f"槽位 {before} → {len(slots)} ({mode})"
                )
        except Exception as exc:
            print(f"字幕时间轴扫描跳过: {exc}")

    if not timeline_applied:
        with ThreadPoolExecutor(max_workers=2) as pool:
            ocr_f = pool.submit(_batch_ocr, file_path, ranges)
            clip_f = pool.submit(_clip_only_enrich, slots, file_path)
            ocr_batch = ocr_f.result()
            slots = clip_f.result()
        _apply_ocr_to_slots(slots, ocr_batch)
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            clip_f = pool.submit(_clip_only_enrich, slots, file_path)
            slots = clip_f.result()
    bump(58)

    elapsed = time.monotonic() - t0
    if elapsed >= TEMPLATE_INTAKE_BUDGET_SEC:
        print(
            f"模板 intake 已达预算 {TEMPLATE_INTAKE_BUDGET_SEC}s ({elapsed:.1f}s)，"
            "跳过花字/场景 enrich（后台 auto 字幕批次继续）"
        )
        bump(92)
        from services.timeline_thumbnails import pregenerate_timeline_thumbnails_for_intake

        pregenerate_timeline_thumbnails_for_intake(file_path, template_id)
        return slots

    slots = _parallel_enrich_slots(
        slots,
        file_path,
        os.path.join(template_dir, "intake"),
    )
    bump(92)

    from services.timeline_thumbnails import pregenerate_timeline_thumbnails_for_intake

    pregenerate_timeline_thumbnails_for_intake(file_path, template_id)

    elapsed = time.monotonic() - t0
    labeled = sum(1 for s in slots if str(s.get("ai_description") or "").strip())
    subtitled = sum(1 for s in slots if str(s.get("subtitle_text") or "").strip())
    print(
        f"模板 intake 完成 [{template_id}]: {elapsed:.1f}s, "
        f"{len(slots)} 槽, AI描述 {labeled}, 字幕 {subtitled}"
    )
    return slots


def _clip_only_enrich(slots: list[dict[str, Any]], video_path: str) -> list[dict[str, Any]]:
    """CLIP/质量分（无 DeepSeek，避免与并行 AI 重复）。"""
    from services.asset_analyzer import analyze_frame, analyze_quality

    out: list[dict[str, Any]] = []
    for slot in slots:
        item = dict(slot)
        thumb = str(item.get("thumbnail") or "").strip()
        if thumb and os.path.isfile(thumb):
            try:
                frame_info = analyze_frame(thumb)
                item["scene_tags"] = frame_info.get("scene_tags", [])
                item["tags"] = item["scene_tags"]
                if not item.get("shot_type"):
                    item["shot_type"] = frame_info.get("shot_type", "wide")
                item["has_person"] = frame_info.get("has_person", False)
                emb = frame_info.get("clip_embedding") or []
                if emb:
                    item["clip_embedding"] = emb
            except Exception:
                pass
        start = float(item.get("start", 0))
        end = float(item.get("end", start + float(item.get("duration", 0.1))))
        if video_path and os.path.isfile(video_path):
            try:
                item["quality_score"] = analyze_quality(video_path, start, end)
            except Exception:
                item.setdefault("quality_score", 0.5)
        out.append(item)
    return out


def intake_already_rich(slots: list[dict[str, Any]], *, min_ratio: float = 0.4) -> bool:
    if not slots:
        return False
    labeled = sum(1 for s in slots if str(s.get("ai_description") or "").strip())
    if labeled / len(slots) >= min_ratio:
        return True
    tagged = sum(
        1
        for s in slots
        if isinstance(s.get("scene_tags"), list) and len(s.get("scene_tags") or []) > 0
    )
    return tagged / len(slots) >= 0.65
