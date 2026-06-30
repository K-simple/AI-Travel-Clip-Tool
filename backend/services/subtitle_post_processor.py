"""口播字幕后处理：标点、断句、过滤幻听、合并碎片。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from services.subtitle_config import SubtitleConfig, get_subtitle_config
from services.subtitle_gen import normalize_chinese_subtitle

_HALLUCINATION_PATTERNS = (
    r"^谢谢观看$",
    r"^感谢观看$",
    r"^字幕由",
    r"^subtitle$",
    r"^请订阅",
    r"^点赞关注",
    r"^下期再见$",
    r"^关注我$",
)

_PUNCT_END = re.compile(r"[。！？；…]$")


@dataclass
class PostProcessResult:
    segments: list[dict[str, Any]] = field(default_factory=list)
    dropped_segments: list[dict[str, Any]] = field(default_factory=list)


def _char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _segment_confidence(seg: dict[str, Any]) -> float:
    if seg.get("confidence") is not None:
        return float(seg["confidence"])
    debug = seg.get("debug") if isinstance(seg.get("debug"), dict) else {}
    avg_logprob = seg.get("avg_logprob") or debug.get("avg_logprob")
    no_speech = seg.get("no_speech_prob") or debug.get("no_speech_prob")
    score = 0.55
    if avg_logprob is not None:
        score = max(0.0, min(1.0, 1.0 + float(avg_logprob) * 0.35))
    if no_speech is not None:
        score *= max(0.0, 1.0 - float(no_speech))
    return round(score, 3)


def _drop_record(seg: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "id": seg.get("id"),
        "start": seg.get("start"),
        "end": seg.get("end"),
        "text": str(seg.get("text") or ""),
        "reason": reason,
        "confidence": seg.get("confidence"),
    }


def _is_hallucination(text: str, seg: dict[str, Any], confidence: float) -> tuple[bool, str | None]:
    cleaned = (text or "").strip()
    if not cleaned:
        return True, "empty"

    debug = seg.get("debug") if isinstance(seg.get("debug"), dict) else {}
    no_speech = debug.get("no_speech_prob") or seg.get("no_speech_prob")
    avg_logprob = debug.get("avg_logprob") or seg.get("avg_logprob")
    compression = debug.get("compression_ratio") or seg.get("compression_ratio")

    for pat in _HALLUCINATION_PATTERNS:
        if re.search(pat, cleaned, re.I):
            # 高置信度口播结尾语保留
            if confidence >= 0.72:
                return False, None
            if no_speech is not None and float(no_speech) >= 0.55:
                return True, "no_speech_prob_high"
            if avg_logprob is not None and float(avg_logprob) < -0.8:
                return True, "low_confidence"
            if confidence < 0.45:
                return True, "hallucination_pattern_low_confidence"
            return False, None

    if cleaned.lower() in ("嗯", "啊", "呃", "哦") and confidence < 0.4:
        return True, "filler_low_confidence"

    if compression is not None and float(compression) > 2.4 and confidence < 0.4:
        return True, "compression_ratio"

    return False, None


def _split_lines(text: str, max_chars: int, max_lines: int) -> str:
    cleaned = normalize_chinese_subtitle(text)
    if not cleaned or max_chars <= 0:
        return cleaned
    if _char_count(cleaned) <= max_chars:
        return cleaned
    parts: list[str] = []
    buf = ""
    for ch in cleaned:
        buf += ch
        if len(buf) >= max_chars and len(parts) < max_lines - 1:
            if not _PUNCT_END.search(buf):
                buf += "，"
            parts.append(buf.strip())
            buf = ""
    if buf.strip():
        parts.append(buf.strip())
    return "\\N".join(parts[:max_lines])


class SubtitlePostProcessor:
    def __init__(self, config: SubtitleConfig | None = None):
        self.config = config or get_subtitle_config()

    def process(self, segments: list[dict[str, Any]]) -> PostProcessResult:
        cfg = self.config
        cleaned: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []

        for i, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            text = normalize_chinese_subtitle(str(seg.get("text") or ""))
            if not text:
                dropped.append(_drop_record(seg, "empty"))
                continue
            start = round(float(seg.get("start", 0)), 3)
            end = round(float(seg.get("end", start + 0.1)), 3)
            if end <= start:
                end = round(start + max(cfg.min_segment_duration, 0.08), 3)

            item = dict(seg)
            item["text"] = text
            item["start"] = start
            item["end"] = end
            item["duration"] = round(end - start, 3)
            item.setdefault("source", "asr")
            item.setdefault("type", "spoken_caption")
            item["confidence"] = _segment_confidence(item)

            if cfg.filter_low_confidence and item["confidence"] < cfg.min_confidence:
                dropped.append(_drop_record(item, "low_confidence"))
                continue

            is_hall, hall_reason = _is_hallucination(text, item, item["confidence"])
            if is_hall and hall_reason:
                dropped.append(_drop_record(item, hall_reason))
                continue

            dur = end - start
            chars = _char_count(text)
            if dur < 0.25 and chars > 12:
                dropped.append(_drop_record(item, "too_short"))
                continue
            if dur > cfg.max_segment_duration and chars > dur * 14:
                dropped.append(_drop_record(item, "too_long"))
                continue

            item["text"] = _split_lines(text, cfg.max_chars_per_line, cfg.max_lines)
            if not item.get("id"):
                item["id"] = f"subtitle_{i + 1}"
            cleaned.append(item)

        merged = self._merge_fragments(cleaned)
        normalized = self._normalize_timeline(merged)
        return PostProcessResult(segments=normalized, dropped_segments=dropped)

    def _merge_fragments(self, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(segments) < 2:
            return segments
        out: list[dict[str, Any]] = []
        buf: dict[str, Any] | None = None

        for seg in segments:
            if buf is None:
                buf = dict(seg)
                continue
            gap = float(seg["start"]) - float(buf["end"])
            buf_chars = _char_count(str(buf.get("text") or ""))
            seg_chars = _char_count(str(seg.get("text") or ""))
            if gap <= 0.35 and buf_chars <= 6 and seg_chars <= 8:
                buf["text"] = normalize_chinese_subtitle(f"{buf['text']}{seg['text']}")
                buf["end"] = seg["end"]
                buf["duration"] = round(float(buf["end"]) - float(buf["start"]), 3)
                buf["confidence"] = min(float(buf.get("confidence", 0.5)), float(seg.get("confidence", 0.5)))
            else:
                out.append(buf)
                buf = dict(seg)
        if buf:
            out.append(buf)
        return out

    def _normalize_timeline(self, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cfg = self.config
        if not segments:
            return []
        sorted_segs = sorted(segments, key=lambda s: float(s.get("start", 0)))
        prev_end = 0.0
        out: list[dict[str, Any]] = []
        for seg in sorted_segs:
            start = max(float(seg["start"]), prev_end)
            end = max(float(seg["end"]), start + cfg.min_segment_duration * 0.5)
            if end - start > cfg.max_segment_duration:
                end = start + cfg.max_segment_duration
            item = dict(seg)
            item["start"] = round(start, 3)
            item["end"] = round(end, 3)
            item["duration"] = round(end - start, 3)
            prev_end = end
            out.append(item)
        return out
