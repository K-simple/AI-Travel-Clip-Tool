"""一句一槽：识别（仅字幕）与应用（字幕→slots）两阶段流程。"""

from __future__ import annotations

import os
from typing import Any, Callable

from services.caption_clip_quality import attach_quality_to_clips
from services.caption_sentence_fusion import (
    build_caption_recognition_debug,
    fuse_sentence_clips,
    get_last_caption_fusion_debug,
    score_ocr_subtitle_track,
)
from services.scene_detector import _attach_thumbnails, extract_frame, get_video_duration
from services.subtitle_clip_planner import build_subtitle_clips_from_asr, get_last_subtitle_clip_debug
from services.subtitle_config import SubtitleConfig, caption_slot_clip_config, get_subtitle_config, is_caption_slot_strategy
from services.subtitle_gen import normalize_chinese_subtitle
from services.subtitle_timeline_scan import probe_timeline_viable, scan_and_ocr_burned_timeline

_LAST_CAPTION_SLOT_DEBUG: dict[str, Any] = {}


def get_last_caption_slot_debug() -> dict[str, Any]:
    return dict(_LAST_CAPTION_SLOT_DEBUG)


def build_slots_from_sentence_clips(
    sentence_clips: list[dict[str, Any]],
    *,
    video_path: str | None = None,
    thumb_dir: str | None = None,
    visual_shots: list[dict[str, Any]] | None = None,
    tts_segments: list[dict[str, Any]] | None = None,
    timing_mode: str | None = None,
    ai_split: bool = True,
    use_tts_aligned_time: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """一个 CaptionClip → 一个 slot。AI 分割模式使用 ai_caption_split / one_sentence_one_shot。"""
    from services.tts.tts_pipeline import get_timeline_timing_mode, index_tts_by_caption_id

    tts_map = index_tts_by_caption_id(tts_segments or [])
    mode = (timing_mode or get_timeline_timing_mode() or "tts_driven").strip().lower()
    tts_ready = bool(
        tts_segments
        and any(str(s.get("status") or "") == "generated" for s in tts_segments if isinstance(s, dict))
    )
    use_tts_time = bool(use_tts_aligned_time and tts_ready and mode == "tts_driven")
    use_tts_links = use_tts_time and bool(tts_map)

    slots: list[dict[str, Any]] = []
    slot_debug: list[dict[str, Any]] = []

    for i, clip in enumerate(sentence_clips or []):
        if not isinstance(clip, dict):
            continue
        text = str(clip.get("text") or clip.get("displayText") or "").strip()
        start = float(clip.get("start", 0))
        end = float(clip.get("end", start))
        if end <= start:
            end = start + max(0.35, float(clip.get("duration") or 0.35))
        dur = max(0.08, end - start)
        clip_id = str(clip.get("id") or f"cap_{i + 1:03d}")
        source = str(clip.get("source") or "asr")
        fusion = clip.get("fusionDebug") if isinstance(clip.get("fusionDebug"), dict) else {}
        quality = clip.get("quality") if isinstance(clip.get("quality"), dict) else {}

        tts_seg = tts_map.get(clip_id)
        tts_seg_id = str(tts_seg.get("id") or "") if tts_seg else ""

        if ai_split:
            slot_source = "ai_caption_split"
            cut_reason = "one_sentence_one_shot"
        elif use_tts_links and tts_seg_id:
            slot_source = "caption_tts_driven"
            cut_reason = "caption_audio_aligned"
        else:
            slot_source = "sentence_caption"
            cut_reason = "caption_sentence"

        slot_id_num = i + 1
        slot: dict[str, Any] = {
            "id": f"slot_{slot_id_num:03d}",
            "slot_id": slot_id_num,
            "segment_id": f"seg_{slot_id_num}",
            "type": "video",
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(dur, 3),
            "clip_start": round(start, 3),
            "clip_end": round(end, 3),
            "template_source_start": round(
                float(clip.get("originalStart") if clip.get("originalStart") is not None else start), 3
            ),
            "subtitle_text": text,
            "subtitle_segments": [
                {
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": text,
                    "type": "spoken_caption",
                    "source": source,
                }
            ],
            "subtitle_source": source,
            "subtitle_quality": "ok" if text and not quality.get("needsReview") else "low",
            "source": slot_source,
            "cut_reason": cut_reason,
            "linked_subtitle_clip_id": clip_id,
            "linkedSubtitleClipId": clip_id,
            "linkedCaptionClipId": clip_id,
            "linked_asr_segment_ids": list(clip.get("linkedSegmentIds") or []),
            "linked_ocr_segment_ids": list(clip.get("linkedOcrSegmentIds") or []),
            "confidence": clip.get("confidence"),
            "needs_review": bool(quality.get("needsReview")),
            "isBaseSlot": False,
        }
        if tts_seg_id:
            slot["linked_tts_segment_id"] = tts_seg_id
            slot["linkedTtsSegmentId"] = tts_seg_id

        clip_style = None
        if isinstance(clip.get("subtitle_style"), dict):
            clip_style = dict(clip["subtitle_style"])
        elif isinstance(clip.get("style"), dict):
            clip_style = dict(clip["style"])
        if clip_style:
            slot["subtitle_style"] = clip_style
            slot["subtitle_segments"][0]["style"] = dict(clip_style)

        if visual_shots:
            best = None
            best_ov = 0.0
            for shot in visual_shots:
                if not isinstance(shot, dict):
                    continue
                s0 = float(shot.get("start", shot.get("clip_start", 0)))
                s1 = float(shot.get("end", s0 + float(shot.get("duration", 0.1))))
                ov = min(end, s1) - max(start, s0)
                if ov > best_ov:
                    best_ov = ov
                    best = shot
            if best:
                for key in ("scene_tags", "shot_type", "tags", "mood", "has_person", "quality_score"):
                    if best.get(key) is not None:
                        slot[key] = best[key]
                if best.get("thumbnail"):
                    slot["thumbnail"] = best["thumbnail"]

        slots.append(slot)
        slot_debug.append(
            {
                "slotId": slot["slot_id"],
                "subtitleText": text[:64],
                "source": slot_source,
                "linkedSubtitleClipId": clip_id,
                "linkedCaptionClipId": clip_id,
                "linkedTtsSegmentId": tts_seg_id or None,
                "linkedAsrSegmentIds": slot["linked_asr_segment_ids"],
                "linkedOcrSegmentIds": slot["linked_ocr_segment_ids"],
                "fusionSimilarity": fusion.get("similarity"),
                "needsReview": bool(quality.get("needsReview")),
            }
        )
        print(
            f"[caption_slot] slot start={start:.2f} end={end:.2f} "
            f"text={text[:24]}{'...' if len(text) > 24 else ''} source={source}"
        )

    if video_path and thumb_dir and slots:
        os.makedirs(thumb_dir, exist_ok=True)
        for i, slot in enumerate(slots):
            if str(slot.get("thumbnail") or "").strip():
                continue
            mid = float(slot["start"]) + float(slot["duration"]) / 2
            thumb_path = os.path.join(thumb_dir, f"slot_{i + 1}_thumb.jpg").replace("\\", "/")
            extract_frame(video_path, mid, thumb_path)
            if os.path.isfile(thumb_path):
                slot["thumbnail"] = thumb_path

    return slots, slot_debug


def _collect_visual_reference_shots(
    video_path: str,
    thumb_dir: str,
    duration: float,
    *,
    visual_suggestions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    from services.processing_config import is_base_slot_creation_mode

    if visual_suggestions:
        return list(visual_suggestions)
    if is_base_slot_creation_mode():
        return []
    try:
        from services.scene_detector import build_template_shot_slots

        shots = build_template_shot_slots(
            video_path,
            thumb_dir,
            duration,
            skip_auto_tune=True,
            skip_ai_refine=True,
            extract_thumbs=False,
            allow_interval_fallback=False,
        )
        return shots or []
    except Exception as exc:
        print(f"[caption_slot] visual reference shots skipped: {exc}")
        return []


def normalize_caption_clips_for_ai_split(
    clips: list[dict[str, Any]],
    *,
    merge_short_fragments: bool = True,
    config: SubtitleConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """AI 分割前规范化 CaptionClips（合并短碎片）。"""
    from services.subtitle_clip_planner import postprocess_caption_clips_for_ai_split

    cfg = config or get_subtitle_config()
    raw = attach_quality_to_clips(list(clips or []), config=cfg)
    stats: dict[str, Any] = {
        "captionClipCount": len(raw),
        "normalizedCaptionClipCount": len(raw),
        "mergedShortClipCount": 0,
        "skippedClipCount": 0,
        "needsReviewCount": sum(
            1 for c in raw if isinstance(c.get("quality"), dict) and c["quality"].get("needsReview")
        ),
    }
    if not raw:
        return [], stats
    if not merge_short_fragments:
        return raw, stats

    normalized, frag_stats = postprocess_caption_clips_for_ai_split(raw, cfg)
    stats["mergedShortClipCount"] = int(frag_stats.get("mergedTooShort", 0)) + int(
        frag_stats.get("mergedFragment", 0)
    )
    stats["skippedClipCount"] = int(frag_stats.get("droppedTooShortLowConfidence", 0))
    stats["normalizedCaptionClipCount"] = len(normalized)
    return normalized, stats


def ai_split_by_captions(
    template_id: str,
    file_path: str,
    sentence_clips: list[dict[str, Any]],
    *,
    duration: float | None = None,
    tts_segments: list[dict[str, Any]] | None = None,
    timing_mode: str | None = None,
    merge_short_fragments: bool = True,
    use_tts_aligned_time: bool = True,
    existing_slots: list[dict[str, Any]] | None = None,
    overwrite_slots: bool = True,
    visual_suggestions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """AI 一键分割画面：每个 CaptionClip → 一个 slot。"""
    global _LAST_CAPTION_SLOT_DEBUG
    from services.slot_helpers import slots_will_be_overwritten_by_ai_split
    from services.tts.tts_pipeline import get_timeline_timing_mode

    if not sentence_clips:
        raise ValueError("请先识别字幕")

    # AI 分割仅接受 validatedCaptionClips（ASR 主 + OCR 校验后）
    clip_source = sentence_clips
    invalid = [
        c for c in clip_source
        if isinstance(c, dict) and c.get("validated") is False and c.get("validationStatus") == "invalid"
    ]
    if invalid:
        raise ValueError("存在未通过校验的字幕片段，请先修正或重新识别")

    normalized, norm_stats = normalize_caption_clips_for_ai_split(
        clip_source,
        merge_short_fragments=merge_short_fragments,
    )
    if not normalized:
        raise ValueError("没有可用于分割的字幕片段")

    from services.processing_config import ENABLE_SUBTITLE_STYLE_ANALYSIS
    from services.subtitle_style_analyzer import enrich_caption_clips_with_subtitle_styles

    if ENABLE_SUBTITLE_STYLE_ANALYSIS and file_path and normalized:
        style_dir = os.path.join("storage", "thumbnails", template_id, "caption_split_styles")
        normalized = enrich_caption_clips_with_subtitle_styles(
            file_path,
            normalized,
            style_dir,
        )

    mode = timing_mode or get_timeline_timing_mode()
    tts_ready = bool(
        tts_segments
        and use_tts_aligned_time
        and any(str(s.get("status") or "") == "generated" for s in tts_segments if isinstance(s, dict))
    )
    used_tts_time = tts_ready and mode == "tts_driven"

    overwrite_warning = None
    if existing_slots and slots_will_be_overwritten_by_ai_split(existing_slots):
        if not overwrite_slots:
            raise ValueError("当前已有画面槽，请确认覆盖后再执行 AI 分割")
        overwrite_warning = "AI 一键分割画面已覆盖原有画面槽"

    needs_review = norm_stats.get("needsReviewCount", 0)
    review_warning = None
    if needs_review:
        review_warning = f"有 {needs_review} 句字幕建议检查，已继续分割"

    dur = duration if duration and duration > 0 else get_video_duration(file_path)
    thumb_dir = os.path.join("storage", "thumbnails", template_id)
    visual_shots = _collect_visual_reference_shots(
        file_path, thumb_dir, dur, visual_suggestions=visual_suggestions
    )

    slots, slot_debug = build_slots_from_sentence_clips(
        normalized,
        video_path=file_path,
        thumb_dir=thumb_dir,
        visual_shots=visual_shots,
        tts_segments=tts_segments if used_tts_time else None,
        timing_mode=mode if used_tts_time else "caption_asr",
        ai_split=True,
        use_tts_aligned_time=use_tts_aligned_time,
    )

    from services.processing_config import is_one_caption_one_shot
    from services.slot_helpers import build_one_caption_one_shot_debug, has_mixed_slot_sources

    if has_mixed_slot_sources(slots):
        slots = [s for s in slots if str(s.get("source") or "") == "ai_caption_split"]

    if is_one_caption_one_shot() and len(slots) != len(normalized):
        raise ValueError(
            f"画面槽数量({len(slots)})与字幕句数({len(normalized)})不一致，无法保证一句一画面"
        )

    if slots and any(not str(s.get("thumbnail") or "").strip() for s in slots):
        slots = _attach_thumbnails(file_path, thumb_dir, slots)

    ai_split_debug = {
        "strategy": "one_sentence_one_shot",
        "captionClipCount": norm_stats.get("captionClipCount", len(sentence_clips)),
        "normalizedCaptionClipCount": norm_stats.get("normalizedCaptionClipCount", len(normalized)),
        "slotCount": len(slots),
        "mergedShortClipCount": norm_stats.get("mergedShortClipCount", 0),
        "skippedClipCount": norm_stats.get("skippedClipCount", 0),
        "needsReviewCount": needs_review,
        "usedTtsAlignedTime": used_tts_time,
        "overwriteSlots": bool(overwrite_slots),
        "slotDiagnostics": slot_debug,
    }
    one_caption_one_shot_debug = build_one_caption_one_shot_debug(
        caption_clips=normalized,
        slots=slots,
    )
    ai_split_debug["oneCaptionOneShotDebug"] = one_caption_one_shot_debug
    _LAST_CAPTION_SLOT_DEBUG = {"phase": "ai_split", **ai_split_debug}
    print(
        f"[ai_split] slots={len(slots)} from clips={len(normalized)} "
        f"tts_time={used_tts_time} merged={ai_split_debug['mergedShortClipCount']}"
    )

    tts_warning = None
    if not used_tts_time and mode == "tts_driven":
        tts_warning = "当前使用字幕识别时间切分；生成 AI 人声并对齐后可再次一键分割以更新画面槽"

    return {
        "slots": slots,
        "sentence_clips": normalized,
        "ai_split_debug": ai_split_debug,
        "oneCaptionOneShotDebug": one_caption_one_shot_debug,
        "overwrite_warning": overwrite_warning,
        "review_warning": review_warning,
        "tts_warning": tts_warning,
        "summary": {
            "slotCount": len(slots),
            "captionClipCount": len(sentence_clips),
            "normalizedCaptionClipCount": len(normalized),
            "usedTtsAlignedTime": used_tts_time,
        },
    }


def ai_split_by_visual_scenes(
    template_id: str,
    file_path: str,
    sentence_clips: list[dict[str, Any]] | None = None,
    *,
    duration: float | None = None,
    existing_slots: list[dict[str, Any]] | None = None,
    overwrite_slots: bool = True,
    skip_ai_refine: bool = False,
) -> dict[str, Any]:
    """按原视频画面镜头切分：PySceneDetect + 可选 AI 边界修正，字幕按时间重叠关联。"""
    global _LAST_CAPTION_SLOT_DEBUG
    from services.processing_config import ENABLE_SUBTITLE_STYLE_ANALYSIS
    from services.slot_helpers import slots_will_be_overwritten_by_ai_split
    from services.subtitle_style_analyzer import enrich_caption_clips_with_subtitle_styles
    from services.visual_slot_builder import (
        build_slots_from_visual_shots,
        detect_visual_shots,
    )

    clips = list(sentence_clips or [])
    dur = duration if duration and duration > 0 else get_video_duration(file_path)
    thumb_dir = os.path.join("storage", "thumbnails", template_id)

    overwrite_warning = None
    if existing_slots and slots_will_be_overwritten_by_ai_split(existing_slots):
        if not overwrite_slots:
            raise ValueError("当前已有画面槽，请确认覆盖后再执行画面镜头分割")
        overwrite_warning = "按原视频画面切分已覆盖原有画面槽"

    if ENABLE_SUBTITLE_STYLE_ANALYSIS and file_path and clips:
        style_dir = os.path.join(thumb_dir, "visual_split_styles")
        clips = enrich_caption_clips_with_subtitle_styles(file_path, clips, style_dir)

    shots = detect_visual_shots(
        file_path,
        thumb_dir,
        dur,
        skip_ai_refine=skip_ai_refine,
    )
    if not shots:
        raise ValueError("未能从原视频检测到画面切点，请检查视频或降低场景检测阈值")

    slots, slot_debug = build_slots_from_visual_shots(
        shots,
        clips,
        video_path=file_path,
        thumb_dir=thumb_dir,
    )
    if not slots:
        raise ValueError("画面镜头切分未生成有效槽位")

    linked_slots = sum(1 for s in slots if s.get("linkedCaptionClipId"))
    visual_split_debug = {
        "strategy": "visual_scene_split",
        "visualShotCount": len(shots),
        "slotCount": len(slots),
        "captionClipCount": len(clips),
        "linkedCaptionSlotCount": linked_slots,
        "slotDiagnostics": slot_debug,
        "skipAiRefine": skip_ai_refine,
    }
    _LAST_CAPTION_SLOT_DEBUG = {"phase": "visual_split", **visual_split_debug}
    print(
        f"[visual_split] shots={len(shots)} slots={len(slots)} "
        f"clips={len(clips)} linked={linked_slots}"
    )

    return {
        "slots": slots,
        "sentence_clips": clips,
        "ai_split_debug": visual_split_debug,
        "oneCaptionOneShotDebug": None,
        "overwrite_warning": overwrite_warning,
        "review_warning": None,
        "tts_warning": None,
        "summary": {
            "slotCount": len(slots),
            "captionClipCount": len(clips),
            "strategy": "visual_scene_split",
            "visualShotCount": len(shots),
        },
    }


def _normalize_ocr_raw(ocr_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, seg in enumerate(ocr_segments or []):
        if not isinstance(seg, dict):
            continue
        raw_text = str(seg.get("text") or "")
        text = normalize_chinese_subtitle(raw_text)
        item = dict(seg)
        item["text"] = text
        item.setdefault("id", f"ocr_raw_{i + 1:03d}")
        out.append(item)
    return out


def run_caption_recognition_pipeline(
    template_id: str,
    file_path: str,
    template_dir: str,
    *,
    spoken_segments: list[dict[str, Any]] | None = None,
    duration: float | None = None,
    config: SubtitleConfig | None = None,
    on_progress: Callable[[int], None] | None = None,
    quality_ocr: bool = False,
) -> dict[str, Any]:
    """阶段一：ASR + OCR + 融合 → sentenceClips（不修改 slots）。"""
    global _LAST_CAPTION_SLOT_DEBUG
    cfg = config or get_subtitle_config()
    clip_cfg = caption_slot_clip_config(cfg)

    def bump(p: int) -> None:
        if on_progress:
            on_progress(p)

    print("[caption_slot] recognition start (clips only, no slots)")
    bump(10)

    dur = duration if duration and duration > 0 else get_video_duration(file_path)

    spoken_pool = list(spoken_segments or [])
    if not spoken_pool:
        from services.speech_subtitle_pipeline import SpeechSubtitlePipeline
        from services.slot_subtitle import _normalize_segment_dict

        pipeline = SpeechSubtitlePipeline(cfg)
        result = pipeline.run(file_path, work_dir=os.path.join(template_dir, "speech_asr"))
        spoken_pool = []
        for seg in result.get("spoken_captions") or []:
            item = _normalize_segment_dict(seg)
            if item:
                spoken_pool.append(item)

    bump(35)
    print(f"[caption_slot] asr={len(spoken_pool)}")

    ocr_raw: list[dict[str, Any]] = []
    try:
        from services.processing_config import SUBTITLE_SCAN_FPS

        ocr_raw = scan_and_ocr_burned_timeline(
            file_path,
            dur,
            quality=quality_ocr,
            sample_fps=SUBTITLE_SCAN_FPS,
        )
    except Exception as exc:
        print(f"[caption_slot] OCR timeline skipped: {exc}")

    ocr_segments = _normalize_ocr_raw(ocr_raw)
    bump(55)
    print(f"[caption_slot] ocr raw={len(ocr_raw)} normalized={len(ocr_segments)}")

    asr_clips, clip_debug = build_subtitle_clips_from_asr(spoken_pool, config=clip_cfg)

    validated_clips = asr_clips
    fusion_debug: dict[str, Any] = {"strategy": "asr_only"}
    use_ocr_validate = bool(cfg.caption_ocr_validate and ocr_segments and probe_timeline_viable(ocr_segments, min_segments=1))
    if use_ocr_validate:
        from services.caption_sentence_fusion import validate_caption_clips_with_ocr

        validated_clips, fusion_debug = validate_caption_clips_with_ocr(
            asr_clips, ocr_segments, spoken_pool, config=cfg, ocr_raw=ocr_raw
        )
    elif asr_clips:
        validated_clips = attach_quality_to_clips(asr_clips, config=cfg)
        for clip in validated_clips:
            if isinstance(clip, dict):
                clip["validationStatus"] = "validated"
                clip["validated"] = True
                clip["validationDebug"] = {"validationAction": "asr_only", "textSource": "asr"}

    sentence_clips = validated_clips

    from services.processing_config import ENABLE_SUBTITLE_STYLE_ANALYSIS
    from services.subtitle_style_analyzer import enrich_caption_clips_with_subtitle_styles

    if ENABLE_SUBTITLE_STYLE_ANALYSIS and file_path and sentence_clips:
        style_dir = os.path.join(template_dir, "caption_recognition_styles")
        sentence_clips = enrich_caption_clips_with_subtitle_styles(
            file_path,
            sentence_clips,
            style_dir,
        )
        bump(75)

    needs_review = sum(
        1 for c in sentence_clips if isinstance(c.get("quality"), dict) and c["quality"].get("needsReview")
    )

    recognition_debug = build_caption_recognition_debug(
        spoken_pool,
        asr_clips,
        ocr_raw,
        ocr_segments,
        sentence_clips,
        fusion_debug,
        clip_debug,
        cfg,
    )

    bump(90)
    _LAST_CAPTION_SLOT_DEBUG = {
        "strategy": "caption_recognition",
        "phase": "recognize_only",
        **recognition_debug,
    }

    print(
        f"[caption_slot] recognition done validated={len(sentence_clips)} asr={len(asr_clips)} "
        f"needsReview={needs_review} ocr_split={fusion_debug.get('ocrSplitCount', 0)} "
        f"ocr_merge={fusion_debug.get('ocrMergeCount', 0)}"
    )

    return {
        "asr_clips": asr_clips,
        "validated_caption_clips": sentence_clips,
        "sentence_clips": sentence_clips,
        "spoken_segments": spoken_pool,
        "ocr_segments": ocr_segments,
        "ocr_raw": ocr_raw,
        "caption_recognition_debug": recognition_debug,
        "needs_review_count": needs_review,
    }


def apply_caption_slots_from_clips(
    template_id: str,
    file_path: str,
    sentence_clips: list[dict[str, Any]],
    *,
    duration: float | None = None,
    tts_segments: list[dict[str, Any]] | None = None,
    timing_mode: str | None = None,
    merge_short_fragments: bool = True,
    use_tts_aligned_time: bool = True,
    existing_slots: list[dict[str, Any]] | None = None,
    overwrite_slots: bool = True,
    visual_suggestions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """兼容旧名：等同 ai_split_by_captions。"""
    result = ai_split_by_captions(
        template_id,
        file_path,
        sentence_clips,
        duration=duration,
        tts_segments=tts_segments,
        timing_mode=timing_mode,
        merge_short_fragments=merge_short_fragments,
        use_tts_aligned_time=use_tts_aligned_time,
        existing_slots=existing_slots,
        overwrite_slots=overwrite_slots,
        visual_suggestions=visual_suggestions,
    )
    return {
        **result,
        "caption_slot_debug": result.get("ai_split_debug") or {},
    }


def run_caption_slot_pipeline(
    template_id: str,
    file_path: str,
    template_dir: str,
    *,
    spoken_segments: list[dict[str, Any]] | None = None,
    duration: float | None = None,
    config: SubtitleConfig | None = None,
    on_progress: Callable[[int], None] | None = None,
    quality_ocr: bool = False,
) -> dict[str, Any]:
    """兼容旧调用：识别 + 应用（不推荐，请用两阶段 API）。"""
    rec = run_caption_recognition_pipeline(
        template_id,
        file_path,
        template_dir,
        spoken_segments=spoken_segments,
        duration=duration,
        config=config,
        on_progress=on_progress,
        quality_ocr=quality_ocr,
    )
    applied = apply_caption_slots_from_clips(
        template_id,
        file_path,
        rec.get("sentence_clips") or [],
        duration=duration,
    )
    return {
        **rec,
        **applied,
        "caption_slot_debug": {
            **(rec.get("caption_recognition_debug") or {}),
            **(applied.get("caption_slot_debug") or {}),
        },
    }


def resolve_cut_strategy(strategy: str | None = None) -> str:
    cfg = get_subtitle_config()
    raw = (strategy or cfg.cut_strategy or "caption_slot").strip().lower()
    if raw in ("sentence", "caption_slot"):
        return "caption_slot"
    if raw in ("visual", "speech", "hybrid"):
        return raw
    return "caption_slot"


def should_use_caption_slot_slots(strategy: str | None = None) -> bool:
    return is_caption_slot_strategy(resolve_cut_strategy(strategy))
