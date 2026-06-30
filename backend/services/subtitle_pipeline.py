"""剪映式字幕：双路识别 + AI 判断；烧录字幕优先画面 OCR 准确度。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal, Optional, Union

from services.processing_config import ENABLE_SUBTITLE_TIMELINE_SCAN, SUBTITLE_BATCH_WORKERS
from services.slot_subtitle import recognize_slots_audio_batch
from services.subtitle_audio_judge import AsrReliability, assess_asr_reliability
from services.subtitle_config import get_subtitle_config, resolve_recognition_mode
from services.subtitle_fusion import (
    collect_screen_text_segments,
    fuse_slot_subtitles,
    maybe_ocr_assist_spoken,
    text_similarity,
)
from services.subtitle_ocr import recognize_slots_visual_batch
from services.subtitle_quality import postprocess_slot_segments, subtitle_text_from_segments
from services.speech_subtitle_pipeline import (
    SLOT_STATUS_ERROR,
    SLOT_STATUS_MATCHED,
    SLOT_STATUS_NO_SPEECH,
)
from services.vocal_separator import resolve_vocal_source_path

SubtitleMode = Literal["speech", "burned", "auto", "visual", "audio"]

_batch_pool = ThreadPoolExecutor(max_workers=SUBTITLE_BATCH_WORKERS)


@dataclass(frozen=True)
class SlotSpec:
    slot_id: Optional[Union[str, int]]
    slot_start: float
    slot_end: float


@dataclass
class SlotRecognizeOutcome:
    slot_id: Optional[Union[str, int]]
    segments: list
    source: str
    error: Optional[str] = None
    status: str = SLOT_STATUS_MATCHED
    reason: str = ""
    linked_subtitle_segment_ids: list[str] = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0

    @property
    def success(self) -> bool:
        return self.status != SLOT_STATUS_ERROR

    @property
    def subtitle_text(self) -> str:
        return subtitle_text_from_segments(self.segments)


def _error_outcomes(specs: list[SlotSpec], error_msg: str) -> list[SlotRecognizeOutcome]:
    return [
        SlotRecognizeOutcome(
            slot_id=s.slot_id,
            segments=[],
            source="none",
            error=error_msg,
            status=SLOT_STATUS_ERROR,
            reason=error_msg,
            start=s.slot_start,
            end=s.slot_end,
        )
        for s in specs
    ]


_VISUAL_CACHE_SOURCES = frozenset({
    "visual",
    "visual_primary",
    "visual_timeline",
    "visual_fallback",
    "hybrid_visual",
    "visual_audio_fallback",
})


def _find_slot_dict(slots: list, spec: SlotSpec) -> dict | None:
    from services.slot_subtitle import slot_dict_source_range

    if spec.slot_id is not None:
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            sid = slot.get("slot_id") or slot.get("id")
            if sid is not None and str(sid) == str(spec.slot_id):
                return slot
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        start, end = slot_dict_source_range(slot)
        if abs(start - spec.slot_start) < 0.06 and abs(end - spec.slot_end) < 0.06:
            return slot
    return None


def _load_cached_slot_visuals(
    template,
    specs: list[SlotSpec],
) -> tuple[list[list], list[int]]:
    """复用 intake 已写入槽位的字幕，返回 (visual_batch, 仍需 OCR 的槽索引)。"""
    slots = list(getattr(template, "slots", None) or [])
    visual_batch: list[list] = []
    need_ocr: list[int] = []

    for i, spec in enumerate(specs):
        slot = _find_slot_dict(slots, spec)
        if not slot:
            visual_batch.append([])
            need_ocr.append(i)
            continue

        text = str(slot.get("subtitle_text") or "").strip()
        segments = list(slot.get("subtitle_segments") or [])
        if not text and segments:
            text = subtitle_text_from_segments(segments)
        source = str(slot.get("subtitle_source") or "none")

        if text and (segments or source in _VISUAL_CACHE_SOURCES):
            if segments:
                visual_batch.append([dict(s) for s in segments if isinstance(s, dict)])
            else:
                visual_batch.append([
                    {
                        "start": spec.slot_start,
                        "end": spec.slot_end,
                        "duration": round(spec.slot_end - spec.slot_start, 3),
                        "text": text,
                        "source": source if source != "none" else "visual",
                    }
                ])
        else:
            visual_batch.append([])
            need_ocr.append(i)

    return visual_batch, need_ocr


def _fill_visual_gaps(
    video_path: str,
    ranges: list[tuple[float, float]],
    visual_batch: list[list],
    need_ocr: list[int],
    *,
    quality: bool,
) -> None:
    if not video_path or not need_ocr:
        return
    from services.subtitle_timeline_scan import ocr_burned_slots_batch

    gap_ranges = [ranges[i] for i in need_ocr]
    try:
        gap_batch = ocr_burned_slots_batch(video_path, gap_ranges, quality=quality)
        for j, slot_i in enumerate(need_ocr):
            if j < len(gap_batch) and gap_batch[j]:
                visual_batch[slot_i] = gap_batch[j]
    except Exception as exc:
        print(f"空槽字幕带 OCR 失败: {exc}")


def _collect_hq_indices(
    specs: list[SlotSpec],
    visual_batch: list[list],
    audio_batch: list[list],
    segments_json: list | None,
    prefer_visual: bool,
) -> tuple[list[AsrReliability], list[int]]:
    """收集需高质量 OCR 的槽：fast 为空、ASR 不可靠、或与 ASR 差异大。"""
    peer_texts: list[str] = []
    reliabilities: list[AsrReliability] = []
    hq_indices: list[int] = []

    for i, spec in enumerate(specs):
        audio_segments = audio_batch[i] if i < len(audio_batch) else []
        visual_segments = visual_batch[i] if i < len(visual_batch) else []
        audio_text = subtitle_text_from_segments(audio_segments)
        visual_text = subtitle_text_from_segments(visual_segments)

        reliability = assess_asr_reliability(
            audio_segments,
            spec.slot_start,
            spec.slot_end,
            peer_texts,
            segments_json=segments_json,
            check_audio_noise=False,
        )
        reliabilities.append(reliability)

        # 已有可靠画面字幕时不因 prefer_visual 整批 HQ 升级（否则 25 槽极慢）
        need_hq = False
        if not visual_text:
            need_hq = prefer_visual or not reliability.reliable
        elif visual_text and audio_text:
            if text_similarity(visual_text, audio_text) < 0.55:
                need_hq = True
        elif not reliability.reliable:
            need_hq = True

        if need_hq:
            hq_indices.append(i)

        if visual_text:
            peer_texts.append(visual_text)
        elif audio_text and reliability.reliable:
            peer_texts.append(audio_text)

    return reliabilities, hq_indices


def _upgrade_visual_hq(
    video_path: str,
    ranges: list[tuple[float, float]],
    visual_batch: list[list],
    indices: list[int],
) -> None:
    if not video_path or not indices:
        return
    hq_ranges = [ranges[i] for i in indices]
    try:
        hq_batch = recognize_slots_visual_batch(
            video_path, hq_ranges, quality=True, parallel=True
        )
        for j, slot_i in enumerate(indices):
            if j < len(hq_batch) and hq_batch[j]:
                visual_batch[slot_i] = hq_batch[j]
    except Exception as exc:
        print(f"HQ OCR 升级失败: {exc}")


def _fill_empty_slots_with_clip_asr(
    specs: list[SlotSpec],
    visual_batch: list[list],
    audio_batch: list[list],
    source_path: str,
) -> None:
    """精识别：空槽仅对该槽做 clip ASR，避免整段 Whisper 重跑。"""
    from services.slot_subtitle import _transcribe_slot_clip

    if not source_path:
        return
    for i, spec in enumerate(specs):
        if subtitle_text_from_segments(visual_batch[i]) or subtitle_text_from_segments(audio_batch[i]):
            continue
        try:
            clip = _transcribe_slot_clip(source_path, spec.slot_start, spec.slot_end)
            if clip:
                audio_batch[i] = clip
        except Exception as exc:
            print(f"槽位 clip ASR 失败 #{spec.slot_id}: {exc}")


def _map_api_mode_to_pipeline(mode: SubtitleMode) -> tuple[str, SubtitleMode]:
    """(recognition_mode, legacy pipeline mode)"""
    raw = str(mode or "speech").lower()
    if raw in ("speech", "audio"):
        return "speech", "audio"
    if raw in ("burned", "visual"):
        return "burned", "visual"
    if raw == "auto":
        resolved = resolve_recognition_mode("auto")
        if resolved == "speech":
            return "speech", "audio"
        if resolved == "burned":
            return "burned", "visual"
        return "legacy_auto", "auto"
    return "legacy_auto", "auto"


def _recognize_all_speech_mode(
    template,
    specs: list[SlotSpec],
    segments_json: list | None,
    *,
    dropped_segments: list | None = None,
) -> list[SlotRecognizeOutcome]:
    """口播模式：整段 ASR 主轨 → split_spoken_caption_by_slots（批量，禁止重复）。"""
    from services.spoken_caption_split import split_spoken_caption_by_slots

    cfg = get_subtitle_config()
    spoken_pool = segments_json or []
    dropped = dropped_segments or []
    debug = getattr(template, "_last_speech_debug", None) or {}
    asr_meta = debug.get("asr") if isinstance(debug, dict) else {}
    if not isinstance(asr_meta, dict):
        asr_meta = {}
    raw_count = int(asr_meta.get("rawSegmentCount") or len(spoken_pool))
    final_count = int(asr_meta.get("finalSegmentCount") or len(spoken_pool))
    dropped_count = int(asr_meta.get("droppedSegmentCount") or len(dropped))

    print(
        f"[speech] raw_asr_segments={raw_count} final_asr_segments={final_count} "
        f"dropped_segments={dropped_count}"
    )

    pseudo_slots = [
        {
            "slot_id": spec.slot_id,
            "clip_start": spec.slot_start,
            "clip_end": spec.slot_end,
            "start": spec.slot_start,
            "end": spec.slot_end,
        }
        for spec in specs
    ]
    split_slots, split_debug = split_spoken_caption_by_slots(spoken_pool, pseudo_slots, config=cfg)
    template._last_subtitle_split_debug = split_debug

    matched = empty = errors = 0
    outcomes: list[SlotRecognizeOutcome] = []

    for spec, slot in zip(specs, split_slots):
        text = str(slot.get("subtitle_text") or "").strip()
        segments = postprocess_slot_segments(list(slot.get("subtitle_segments") or []))
        status = str(
            slot.get("subtitle_status")
            or (SLOT_STATUS_MATCHED if text else SLOT_STATUS_NO_SPEECH)
        )
        reason = str(slot.get("subtitle_status_reason") or ("word_split" if text else "no_asr_in_slot_window"))
        linked = list(
            slot.get("linkedSubtitleSegmentIds")
            or slot.get("linked_subtitle_segment_ids")
            or []
        )
        source = "whisper" if status == SLOT_STATUS_MATCHED else "none"

        if status == SLOT_STATUS_MATCHED:
            matched += 1
        elif status == SLOT_STATUS_ERROR:
            errors += 1
        else:
            empty += 1

        print(
            f"[speech][slot] id={spec.slot_id} start={spec.slot_start:.2f} end={spec.slot_end:.2f} "
            f"status={status} reason={reason} linked_segments={linked}"
        )

        outcomes.append(
            SlotRecognizeOutcome(
                slot_id=spec.slot_id,
                segments=segments,
                source=source,
                error=reason if status == SLOT_STATUS_ERROR else None,
                status=status,
                reason=reason,
                linked_subtitle_segment_ids=linked,
                start=spec.slot_start,
                end=spec.slot_end,
            )
        )

    print(
        f"[speech] slots_total={len(specs)} matched={matched} empty={empty} error={errors}"
    )
    return outcomes


def _legacy_tuple_to_outcome(
    spec: SlotSpec,
    slot_id,
    segments: list,
    source: str,
    error: Optional[str],
) -> SlotRecognizeOutcome:
    if error:
        return SlotRecognizeOutcome(
            slot_id=slot_id,
            segments=segments,
            source=source,
            error=error,
            status=SLOT_STATUS_ERROR,
            reason=error,
            start=spec.slot_start,
            end=spec.slot_end,
        )
    text = subtitle_text_from_segments(segments)
    if text:
        status = SLOT_STATUS_MATCHED
        reason = "legacy_matched"
    else:
        status = SLOT_STATUS_NO_SPEECH
        reason = "legacy_empty"
    return SlotRecognizeOutcome(
        slot_id=slot_id,
        segments=segments,
        source=source,
        status=status,
        reason=reason,
        start=spec.slot_start,
        end=spec.slot_end,
    )


def recognize_all_slots_capcut(
    template,
    specs: list[SlotSpec],
    mode: SubtitleMode,
    segments_json: list | None,
    prefer_visual: bool,
    skip_whisper: bool = False,
    quality_mode: bool = False,
) -> list[SlotRecognizeOutcome]:
    if not specs:
        return []

    recognition_mode, pipeline_mode = _map_api_mode_to_pipeline(mode)
    print(f"[subtitle] mode={mode} → recognition={recognition_mode}, pipeline={pipeline_mode}")

    if recognition_mode == "speech":
        prefer_visual = False
        skip_whisper = False
        if not segments_json:
            print("[speech] 警告：缺少 segments_json，槽位切分可能为空")
        dropped = []
        debug = getattr(template, "_last_speech_debug", None) or {}
        if isinstance(debug, dict):
            dropped = list(debug.get("droppedSegments") or [])
        return _recognize_all_speech_mode(
            template,
            specs,
            segments_json,
            dropped_segments=dropped,
        )

    if recognition_mode == "burned":
        prefer_visual = True
        skip_whisper = True
        pipeline_mode = "visual"

    video_path = template.file_path or ""
    ranges = [(s.slot_start, s.slot_end) for s in specs]
    source_path = resolve_vocal_source_path(video_path, force=False) or video_path

    # 仅纯画面模式或用户精识别时使用 HQ OCR 路径；烧录字幕快速识别仍走 fast + 按需升级
    ocr_quality = pipeline_mode == "visual" or quality_mode

    visual_batch: list[list] = [[] for _ in specs]
    audio_batch: list[list] = [[] for _ in specs]

    def _run_visual(quality: bool) -> list[list]:
        if not video_path:
            return [[] for _ in specs]
        return recognize_slots_visual_batch(
            video_path, ranges, quality=quality, parallel=quality
        )

    def _run_audio() -> list[list]:
        if skip_whisper or not segments_json or not source_path:
            return [[] for _ in specs]
        return recognize_slots_audio_batch(source_path, ranges, segments_json)

    run_visual = pipeline_mode in ("visual", "auto") and bool(video_path)
    run_audio = pipeline_mode in ("audio", "auto") and not skip_whisper

    timeline_visual: list[list] | None = None
    cached_visual, need_ocr = _load_cached_slot_visuals(template, specs)

    # intake 已写入字幕：跳过重扫时间轴，仅补空槽
    if (
        not quality_mode
        and prefer_visual
        and run_visual
        and len(need_ocr) < len(specs)
    ):
        visual_batch = cached_visual
        if need_ocr:
            _fill_visual_gaps(video_path, ranges, visual_batch, need_ocr, quality=False)
        timeline_visual = visual_batch
        print(
            f"字幕复用 intake 缓存: {len(specs) - len(need_ocr)}/{len(specs)} 槽，"
            f"补 OCR {len(need_ocr)} 槽"
        )

    # 精识别：逐槽 HQ OCR，勿整片重扫时间轴（否则极慢且与 intake 结果相同）
    use_timeline_batch = (
        timeline_visual is None
        and prefer_visual
        and run_visual
        and ENABLE_SUBTITLE_TIMELINE_SCAN
        and video_path
        and not quality_mode
    )
    if use_timeline_batch:
        try:
            from services.processing_config import SUBTITLE_SCAN_FPS
            from services.scene_detector import get_video_duration
            from services.subtitle_timeline_scan import (
                apply_subtitle_timeline_to_slots,
                probe_timeline_viable,
                scan_and_ocr_burned_timeline,
                segments_overlapping_range,
            )

            duration = float(getattr(template, "duration", 0) or 0)
            if duration <= 0:
                duration = get_video_duration(video_path)
            timeline = scan_and_ocr_burned_timeline(
                video_path,
                duration,
                quality=quality_mode,
                sample_fps=SUBTITLE_SCAN_FPS,
            )
            if probe_timeline_viable(timeline, min_segments=1):
                pseudo_slots = [
                    {"clip_start": s.slot_start, "clip_end": s.slot_end}
                    for s in specs
                ]
                aligned = apply_subtitle_timeline_to_slots(pseudo_slots, timeline)
                timeline_visual = []
                for slot, al in zip(specs, aligned):
                    segs = al.get("subtitle_segments") or []
                    if not segs:
                        segs = segments_overlapping_range(
                            timeline, slot.slot_start, slot.slot_end
                        )
                    timeline_visual.append(segs)
                print(f"字幕时间轴识别: {len(timeline)} 句 → {len(specs)} 槽")
        except Exception as exc:
            print(f"字幕时间轴 batch 跳过: {exc}")
            timeline_visual = None

    if timeline_visual is not None:
        visual_batch = timeline_visual
        if run_audio and not skip_whisper:
            audio_batch = _run_audio()
        elif run_visual and not run_audio:
            pass
    elif quality_mode and run_visual and prefer_visual:
        try:
            from services.subtitle_timeline_scan import ocr_burned_slots_batch

            visual_batch = ocr_burned_slots_batch(video_path, ranges, quality=True)
            print(f"烧录字幕精识别 HQ OCR: {len(ranges)} 槽")
        except Exception as exc:
            print(f"烧录 HQ OCR 失败，回退整帧 OCR: {exc}")
            visual_batch = _run_visual(False)
            _upgrade_visual_hq(video_path, ranges, visual_batch, list(range(len(specs))))
    elif quality_mode and run_visual and run_audio:
        # 非烧录：fast OCR + ASR 并行 → 按需 HQ 升级
        fv = _batch_pool.submit(_run_visual, False)
        fa = _batch_pool.submit(_run_audio)
        visual_batch = fv.result()
        audio_batch = fa.result()
        _upgrade_visual_hq(video_path, ranges, visual_batch, list(range(len(specs))))
        _fill_empty_slots_with_clip_asr(specs, visual_batch, audio_batch, source_path)
    elif quality_mode and run_visual:
        visual_batch = _run_visual(False)
        _upgrade_visual_hq(video_path, ranges, visual_batch, list(range(len(specs))))
    elif run_visual and run_audio and ocr_quality:
        fa = _batch_pool.submit(_run_audio)
        visual_batch = _run_visual(True)
        audio_batch = fa.result()
    elif run_visual:
        try:
            visual_batch = _run_visual(ocr_quality)
        except Exception as exc:
            if mode == "visual":
                return _error_outcomes(specs, str(exc))
            print(f"OCR 失败: {exc}")
    elif run_audio:
        if not source_path and mode == "audio":
            return _error_outcomes(specs, "模板缺少音频源")
        if not segments_json and mode == "audio":
            return _error_outcomes(specs, "缺少整段转写结果")
        audio_batch = _run_audio()

    if mode == "auto" and video_path and not quality_mode and not ocr_quality:
        reliabilities, hq_indices = _collect_hq_indices(
            specs, visual_batch, audio_batch, segments_json, prefer_visual
        )
        if hq_indices:
            _upgrade_visual_hq(video_path, ranges, visual_batch, hq_indices)
    else:
        reliabilities, _ = _collect_hq_indices(
            specs, visual_batch, audio_batch, segments_json, prefer_visual
        ) if mode == "auto" else ([], [])

    peer_texts: list[str] = []
    legacy_results: list[tuple[Optional[Union[str, int]], list, str, Optional[str]]] = []

    cfg = get_subtitle_config()
    fusion_mode = recognition_mode if recognition_mode in ("speech", "burned") else "legacy_auto"

    for i, spec in enumerate(specs):
        audio_segments = audio_batch[i] if i < len(audio_batch) else []
        visual_segments = visual_batch[i] if i < len(visual_batch) else []

        if fusion_mode == "speech":
            audio_segments = maybe_ocr_assist_spoken(
                audio_segments,
                visual_segments,
                enabled=cfg.enable_ocr_assist,
            )
            fused, source = fuse_slot_subtitles(
                audio_segments,
                visual_segments,
                spec.slot_start,
                spec.slot_end,
                peer_texts,
                recognition_mode="speech",
            )
            segments = postprocess_slot_segments(fused)
        elif fusion_mode == "burned":
            fused, source = fuse_slot_subtitles(
                audio_segments,
                visual_segments,
                spec.slot_start,
                spec.slot_end,
                peer_texts,
                recognition_mode="burned",
            )
            segments = postprocess_slot_segments(fused)
        elif pipeline_mode == "auto":
            reliability = reliabilities[i] if i < len(reliabilities) else assess_asr_reliability(
                audio_segments,
                spec.slot_start,
                spec.slot_end,
                peer_texts,
                segments_json=segments_json,
                check_audio_noise=False,
            )
            audio_bad = timeline_visual is not None and bool(visual_segments)
            fused, source = fuse_slot_subtitles(
                audio_segments,
                visual_segments,
                spec.slot_start,
                spec.slot_end,
                peer_texts,
                prefer_visual=prefer_visual or audio_bad,
                audio_unreliable=audio_bad or not reliability.reliable,
                recognition_mode="legacy_auto",
            )
            if timeline_visual is not None and visual_segments:
                source = "visual_timeline"
            segments = postprocess_slot_segments(fused)
        elif pipeline_mode == "visual":
            segments = postprocess_slot_segments(collect_screen_text_segments(visual_segments) if cfg.enable_screen_text else visual_segments)
            source = "visual" if segments else "none"
        else:
            segments = postprocess_slot_segments(audio_segments)
            source = "whisper" if segments else "none"

        text = subtitle_text_from_segments(segments)
        if text:
            peer_texts.append(text)
        legacy_results.append((spec.slot_id, segments, source, None))

    return [
        _legacy_tuple_to_outcome(spec, slot_id, segments, source, error)
        for spec, (slot_id, segments, source, error) in zip(specs, legacy_results)
    ]


def recognize_single_slot_capcut(
    template,
    slot_start: float,
    slot_end: float,
    mode: SubtitleMode,
    segments_json: list | None,
    peer_texts: list[str] | None,
    prefer_visual: bool,
    skip_whisper: bool = False,
    quality_mode: bool = False,
) -> SlotRecognizeOutcome:
    spec = SlotSpec(None, slot_start, slot_end)
    out = recognize_all_slots_capcut(
        template,
        [spec],
        mode,
        segments_json,
        prefer_visual,
        skip_whisper=skip_whisper,
        quality_mode=quality_mode,
    )
    if not out:
        return SlotRecognizeOutcome(
            slot_id=None,
            segments=[],
            source="none",
            status=SLOT_STATUS_NO_SPEECH,
            reason="empty_result",
            start=slot_start,
            end=slot_end,
        )
    outcome = out[0]
    if outcome.error and outcome.status == SLOT_STATUS_ERROR:
        raise RuntimeError(outcome.error)
    return outcome
