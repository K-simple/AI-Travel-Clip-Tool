"""口播视频 ASR 主流程：提取音频 → 预处理 → VAD+Whisper → 后处理 → 特效理解。"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from services.audio_enhancer import AudioEnhancer
from services.media_probe import extract_whisper_wav, has_audio_stream
from services.subtitle_config import SubtitleConfig, get_subtitle_config
from services.subtitle_effect_understanding import (
    attach_effect_to_segments,
    get_default_speech_effect_profile,
)
from utils.security import resolve_storage_path


def _normalize(text: str) -> str:
    from services.subtitle_gen import normalize_chinese_subtitle

    return normalize_chinese_subtitle(text)

ProgressCb = Callable[[str, int, str], None] | None

SLOT_STATUS_MATCHED = "matched"
SLOT_STATUS_NO_SPEECH = "no_speech"
SLOT_STATUS_NO_OVERLAP = "no_overlap"
SLOT_STATUS_FILTERED = "filtered"
SLOT_STATUS_ERROR = "error"


@dataclass
class SlotAlignResult:
    segments: list[dict[str, Any]] = field(default_factory=list)
    status: str = SLOT_STATUS_NO_SPEECH
    reason: str = ""
    linked_subtitle_segment_ids: list[str] = field(default_factory=list)
    slot_start: float = 0.0
    slot_end: float = 0.0
    slot_id: str | int | None = None

    @property
    def subtitle_text(self) -> str:
        return " ".join(str(s.get("text") or "") for s in self.segments).strip()

    @property
    def success(self) -> bool:
        return self.status != SLOT_STATUS_ERROR


def _log(step: str, progress: int, message: str, on_progress: ProgressCb) -> None:
    print(f"[speech][{progress:3d}%] {step}: {message}")
    if on_progress:
        on_progress(step, progress, message)


def build_speech_debug(
    *,
    cfg: SubtitleConfig,
    raw_wav: str,
    enhanced_wav: str,
    enhance_result,
    raw_segments: list,
    final_segments: list,
    dropped_segments: list,
    audio_duration: float = 0.0,
) -> dict[str, Any]:
    return {
        "mode": "speech",
        "asrEngine": cfg.asr_engine,
        "audio": {
            "extractedPath": raw_wav,
            "enhancedPath": enhanced_wav,
            "enhanced": bool(enhance_result.used_loudnorm if enhance_result else cfg.enable_audio_enhance),
            "vocalIsolationUsed": bool(enhance_result.vocal_isolation_used if enhance_result else False),
            "fallbackToOriginal": bool(enhance_result.fallback_to_original if enhance_result else False),
            "duration": round(audio_duration, 3),
            "preprocessMs": int(enhance_result.elapsed_ms if enhance_result else 0),
            "steps": list(enhance_result.steps if enhance_result else []),
        },
        "vad": {
            "enabled": cfg.enable_vad,
            "speechSegments": len(raw_segments),
        },
        "asr": {
            "rawSegmentCount": len(raw_segments),
            "finalSegmentCount": len(final_segments),
            "droppedSegmentCount": len(dropped_segments),
        },
        "droppedSegments": dropped_segments,
    }


class SpeechSubtitlePipeline:
    def __init__(self, config: SubtitleConfig | None = None):
        self.config = config or get_subtitle_config()
        self.enhancer = AudioEnhancer(
            enable_enhance=self.config.enable_audio_enhance,
            enable_vocal_isolation=self.config.enable_vocal_isolation,
        )
        from services.subtitle_post_processor import SubtitlePostProcessor

        self.post_processor = SubtitlePostProcessor(self.config)
        self.last_debug: dict[str, Any] = {}
        self.last_dropped: list[dict[str, Any]] = []

    def run(
        self,
        video_path: str,
        *,
        work_dir: str | None = None,
        on_progress: ProgressCb = None,
    ) -> dict[str, Any]:
        cfg = self.config
        t0 = time.monotonic()
        resolved = resolve_storage_path(video_path)
        if not os.path.isfile(resolved):
            raise RuntimeError("视频文件不存在")

        if not has_audio_stream(resolved):
            raise RuntimeError("视频无音轨，无法进行口播字幕识别")

        base_dir = work_dir or os.path.dirname(resolved)
        os.makedirs(base_dir, exist_ok=True)

        raw_wav = os.path.join(base_dir, "speech_raw_16k.wav")
        enhanced_wav = os.path.join(base_dir, "speech_enhanced_16k.wav")

        _log("extract_audio", 5, "FFmpeg 提取 16kHz mono WAV", on_progress)
        t_extract = time.monotonic()
        extract_whisper_wav(resolved, raw_wav)
        print(f"[speech] 提音频耗时 {int((time.monotonic() - t_extract) * 1000)}ms")

        _log("audio_preprocess", 12, "音量归一化（vocal isolation 默认关）", on_progress)
        enhance_result = self.enhancer.enhance(raw_wav, enhanced_wav)

        _log("vad", 25, "VAD 由 faster-whisper vad_filter 执行", on_progress)
        _log("asr", 35, f"Whisper 识别 language={cfg.language}", on_progress)
        t_asr = time.monotonic()
        from services.subtitle_gen import transcribe_speech

        raw_segments = transcribe_speech(
            enhanced_wav,
            language=cfg.language,
            config=cfg,
        )
        print(f"[speech] ASR 耗时 {int((time.monotonic() - t_asr) * 1000)}ms, raw={len(raw_segments)}")

        _log("postprocess", 75, f"原始 {len(raw_segments)} 段 → 后处理", on_progress)
        post_result = self.post_processor.process(raw_segments)
        processed = post_result.segments
        dropped = post_result.dropped_segments
        self.last_dropped = dropped

        _log("effect", 88, "字幕特效 profile + renderHints", on_progress)
        profile = get_default_speech_effect_profile()
        spoken = attach_effect_to_segments(processed, profile)

        audio_duration = 0.0
        try:
            from services.subtitle_gen import _audio_duration_seconds

            audio_duration = _audio_duration_seconds(enhanced_wav)
        except Exception:
            pass

        debug = build_speech_debug(
            cfg=cfg,
            raw_wav=raw_wav,
            enhanced_wav=enhanced_wav,
            enhance_result=enhance_result,
            raw_segments=raw_segments,
            final_segments=spoken,
            dropped_segments=dropped,
            audio_duration=audio_duration,
        )
        debug["elapsedMs"] = int((time.monotonic() - t0) * 1000)
        self.last_debug = debug

        print(
            f"[speech] raw_asr_segments={len(raw_segments)} "
            f"final_asr_segments={len(spoken)} dropped_segments={len(dropped)}"
        )

        _log("done", 100, f"输出 {len(spoken)} 条 spoken_caption", on_progress)

        return {
            "spoken_captions": spoken,
            "effect_profile": profile,
            "debug": debug,
            "meta": {
                "engine": cfg.asr_engine,
                "language": cfg.language,
                "enhanced_audio_used": enhance_result.used_loudnorm,
                "vocal_isolation_used": enhance_result.vocal_isolation_used,
                "vad_used": cfg.enable_vad,
                "raw_segment_count": len(raw_segments),
                "spoken_segment_count": len(spoken),
                "dropped_segment_count": len(dropped),
            },
        }


def transcribe_video_speech(
    video_path: str,
    *,
    work_dir: str | None = None,
    config: SubtitleConfig | None = None,
    on_progress: ProgressCb = None,
) -> list[dict[str, Any]]:
    pipeline = SpeechSubtitlePipeline(config)
    result = pipeline.run(video_path, work_dir=work_dir, on_progress=on_progress)
    return result["spoken_captions"]


def _is_spoken_segment(seg: dict[str, Any]) -> bool:
    seg_type = str(seg.get("type") or "spoken_caption")
    return seg_type not in ("screen_text", "burned_subtitle_candidate", "uncertain")


def _padded_range(
    slot_start: float,
    slot_end: float,
    cfg: SubtitleConfig,
) -> tuple[float, float, float]:
    pad = float(cfg.slot_padding_sec)
    padded_start = max(0.0, float(slot_start) - pad)
    padded_end = max(padded_start + 0.05, float(slot_end) + pad)
    slot_dur = max(0.05, float(slot_end) - float(slot_start))
    return padded_start, padded_end, slot_dur


def _overlap_amount(seg_start: float, seg_end: float, range_start: float, range_end: float) -> float:
    return min(range_end, seg_end) - max(range_start, seg_start)


def _segment_matches_slot(
    seg: dict[str, Any],
    padded_start: float,
    padded_end: float,
    slot_dur: float,
    cfg: SubtitleConfig,
) -> bool:
    s = float(seg.get("start", 0))
    e = float(seg.get("end", s))
    if e <= s:
        return False
    overlap = _overlap_amount(s, e, padded_start, padded_end)
    if overlap <= 0:
        return False
    seg_dur = max(0.05, e - s)
    if overlap >= float(cfg.min_overlap_sec):
        return True
    if overlap / seg_dur >= float(cfg.min_segment_overlap_ratio):
        return True
    if overlap / slot_dur >= float(cfg.min_slot_overlap_ratio):
        return True
    return False


def _segments_with_any_overlap(
    segments: list[dict[str, Any]],
    range_start: float,
    range_end: float,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict) or not _is_spoken_segment(seg):
            continue
        s = float(seg.get("start", 0))
        e = float(seg.get("end", s))
        if _overlap_amount(s, e, range_start, range_end) > 0:
            hits.append(seg)
    return hits


def _words_text_in_range(
    seg: dict[str, Any],
    slot_start: float,
    slot_end: float,
) -> str:
    words = seg.get("words")
    if not isinstance(words, list) or not words:
        return ""
    picked: list[str] = []
    for word in words:
        if not isinstance(word, dict):
            continue
        ws = float(word.get("start", 0))
        we = float(word.get("end", ws))
        center = (ws + we) / 2.0
        if slot_start <= center <= slot_end or _overlap_amount(ws, we, slot_start, slot_end) > 0:
            token = _normalize(str(word.get("word") or ""))
            if token:
                picked.append(token)
    return _normalize("".join(picked))


def _build_derived_segments(
    hits: list[dict[str, Any]],
    slot_start: float,
    slot_end: float,
) -> list[dict[str, Any]]:
    linked_ids = [str(h.get("id") or "") for h in hits if h.get("id")]
    texts: list[str] = []
    confs: list[float] = []
    for h in hits:
        word_text = _words_text_in_range(h, slot_start, slot_end)
        if word_text:
            texts.append(word_text)
        else:
            texts.append(str(h.get("text") or "").replace("\\N", ""))
        confs.append(float(h.get("confidence") or 0.5))

    profile_id = hits[0].get("effectProfileId")
    render_hints = hits[0].get("renderHints") or {}
    source_refs = [
        {
            "id": h.get("id"),
            "start": h.get("start"),
            "end": h.get("end"),
            "text": h.get("text"),
            "confidence": h.get("confidence"),
        }
        for h in hits
    ]

    return [
        {
            "id": f"slot_{slot_start:.2f}_{slot_end:.2f}",
            "start": round(slot_start, 3),
            "end": round(slot_end, 3),
            "duration": round(slot_end - slot_start, 3),
            "text": "".join(texts),
            "source": "asr",
            "type": "slot_derived_caption",
            "confidence": round(min(confs), 3) if confs else 0.5,
            "effectProfileId": profile_id,
            "renderHints": render_hints,
            "linkedSubtitleSegmentIds": [i for i in linked_ids if i],
            "source_segments": source_refs,
        }
    ]


def align_spoken_to_slot_detailed(
    spoken_segments: list[dict[str, Any]],
    slot_start: float,
    slot_end: float,
    *,
    slot_id: str | int | None = None,
    dropped_segments: list[dict[str, Any]] | None = None,
    config: SubtitleConfig | None = None,
) -> SlotAlignResult:
    """单槽对齐：委托 split_spoken_caption_by_slots，保证与批量逻辑一致。"""
    from services.spoken_caption_split import (
        SLOT_STATUS_ERROR,
        SLOT_STATUS_FILTERED,
        SLOT_STATUS_MATCHED,
        SLOT_STATUS_NO_OVERLAP,
        SLOT_STATUS_NO_SPEECH,
        split_spoken_caption_by_slots,
    )

    cfg = config or get_subtitle_config()
    result = SlotAlignResult(slot_start=slot_start, slot_end=slot_end, slot_id=slot_id)

    if slot_end <= slot_start:
        result.status = SLOT_STATUS_ERROR
        result.reason = "invalid_slot_time"
        return result

    pseudo_slot = {
        "slot_id": slot_id,
        "clip_start": slot_start,
        "clip_end": slot_end,
        "start": slot_start,
        "end": slot_end,
    }
    split_slots, _ = split_spoken_caption_by_slots(spoken_segments, [pseudo_slot], config=cfg)
    slot = split_slots[0] if split_slots else pseudo_slot

    dropped_pool = list(dropped_segments or [])
    if dropped_pool and not str(slot.get("subtitle_text") or "").strip():
        padded_start, padded_end, _ = _padded_range(slot_start, slot_end, cfg)
        if _segments_with_any_overlap(dropped_pool, padded_start, padded_end):
            result.status = SLOT_STATUS_FILTERED
            result.reason = "segments_filtered"
            return result

    text = str(slot.get("subtitle_text") or "").strip()
    segments = list(slot.get("subtitle_segments") or [])
    status = str(slot.get("subtitle_status") or (SLOT_STATUS_MATCHED if text else SLOT_STATUS_NO_SPEECH))
    reason = str(slot.get("subtitle_status_reason") or ("word_split" if text else "no_asr_in_slot_window"))

    if text:
        result.segments = segments
        result.linked_subtitle_segment_ids = list(
            slot.get("linkedSubtitleSegmentIds")
            or slot.get("linked_subtitle_segment_ids")
            or []
        )
        result.status = SLOT_STATUS_MATCHED
        result.reason = reason
        return result

    spoken_pool = [s for s in (spoken_segments or []) if isinstance(s, dict)]
    padded_start, padded_end, _ = _padded_range(slot_start, slot_end, cfg)

    if _segments_with_any_overlap(spoken_pool, padded_start, padded_end):
        result.status = SLOT_STATUS_NO_OVERLAP
        result.reason = "asr_overlap_insufficient"
    else:
        result.status = SLOT_STATUS_NO_SPEECH
        result.reason = "no_asr_in_slot_window"
    return result


def derive_slot_subtitle(
    spoken_segments: list[dict[str, Any]],
    slot_start: float,
    slot_end: float,
    **kwargs,
) -> list[dict[str, Any]]:
    """槽位派生字幕（兼容旧接口）。"""
    align = align_spoken_to_slot_detailed(
        spoken_segments,
        slot_start,
        slot_end,
        **kwargs,
    )
    return align.segments


# 兼容旧名
align_spoken_to_slot = derive_slot_subtitle
