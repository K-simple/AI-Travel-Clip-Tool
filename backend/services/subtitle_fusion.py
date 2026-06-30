"""槽位字幕：画面 OCR 与人声 ASR 融合择优。"""

from __future__ import annotations

import re
from typing import Iterable, Literal

from services.subtitle_quality import (
    count_near_duplicate_peers,
    is_subtitle_quality_acceptable,
    subtitle_text_from_segments,
    text_similarity,
)

SubtitleSource = Literal[
    "visual",
    "visual_primary",
    "visual_audio_fallback",
    "whisper",
    "whisper_low_quality",
    "hybrid_visual",
    "hybrid_whisper",
    "none",
]


def _tag_segments(segments: list, seg_type: str, source: str) -> list:
    out: list = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        item = dict(seg)
        item.setdefault("type", seg_type)
        item.setdefault("source", source)
        out.append(item)
    return out


def collect_screen_text_segments(visual_segments: list) -> list:
    """OCR 结果标记为 screen_text，不进入 spoken_caption。"""
    return _tag_segments(visual_segments, "screen_text", "ocr")


def maybe_ocr_assist_spoken(
    audio_segments: list,
    visual_segments: list,
    *,
    enabled: bool,
) -> list:
    """可选：OCR 与 ASR 高度相似时保留 ASR，不替换为 OCR。"""
    if not enabled or not audio_segments or not visual_segments:
        return audio_segments
    from services.subtitle_quality import subtitle_text_from_segments, text_similarity

    a = subtitle_text_from_segments(audio_segments)
    v = subtitle_text_from_segments(visual_segments)
    if not a or not v:
        return audio_segments
    if text_similarity(a, v) >= 0.82:
        return audio_segments
    return audio_segments


def _char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def score_subtitle_text(
    text: str,
    slot_duration: float,
    peer_texts: Iterable[str],
    *,
    source_kind: str,
    visual_boost: float = 0.0,
) -> float:
    cleaned = (text or "").strip()
    if not cleaned:
        return -100.0

    peers = list(peer_texts)
    dup = count_near_duplicate_peers(cleaned, peers)
    ok, reason = is_subtitle_quality_acceptable(
        cleaned, slot_duration, duplicate_peers=dup
    )
    score = 0.0
    chars = _char_count(cleaned)

    if ok:
        score += 45.0
    else:
        score -= 35.0
        if reason == "duplicate_across_slots":
            score -= 25.0
        elif reason == "too_long_for_slot":
            score -= 20.0

    score -= dup * 30.0

    if source_kind == "visual":
        score += 18.0 + visual_boost
        # 烧录字幕通常更短、更贴槽位
        if slot_duration <= 3.0 and chars <= max(18, slot_duration * 9):
            score += 8.0
    elif source_kind in ("clip", "slice", "slice_loose"):
        score += 6.0
    else:
        score += 4.0

    cjk = len(re.findall(r"[\u4e00-\u9fff]", cleaned))
    if chars >= 4:
        score += min(12.0, cjk / max(chars, 1) * 12.0)

    # 合理长度奖励
    ideal = max(4.0, slot_duration * 5.5)
    if chars <= ideal * 1.35:
        score += 6.0
    elif chars > ideal * 2.2:
        score -= 12.0

    return score


def fuse_slot_subtitles(
    audio_segments: list,
    visual_segments: list,
    slot_start: float,
    slot_end: float,
    peer_texts: list[str] | None = None,
    *,
    prefer_visual: bool = False,
    audio_unreliable: bool = False,
    recognition_mode: str = "legacy_auto",
    enable_ocr_assist: bool = False,
) -> tuple[list, SubtitleSource]:
    """综合画面 OCR 与人声 ASR，返回最佳槽位字幕。

    recognition_mode:
      - speech: 仅 ASR → spoken_caption
      - burned: 仅 OCR → burned_subtitle
      - legacy_auto: 原有融合逻辑
    """
    mode = str(recognition_mode or "legacy_auto").lower()

    if mode == "speech":
        if not audio_segments:
            return [], "none"
        return _tag_segments(audio_segments, "spoken_caption", "whisper"), "whisper"

    if mode == "burned":
        if not visual_segments:
            return [], "none"
        return _tag_segments(visual_segments, "burned_subtitle", "visual"), "visual_primary"

    peers = peer_texts or []
    slot_duration = max(0.1, float(slot_end) - float(slot_start))
    audio_text = subtitle_text_from_segments(audio_segments)
    visual_text = subtitle_text_from_segments(visual_segments)
    visual_boost = 12.0 if prefer_visual else 0.0

    if not audio_text and not visual_text:
        return [], "none"
    if visual_text and not audio_text:
        return visual_segments, "visual_primary"

    # 烧录字幕模板：两路都有字时默认信画面（与 ASR 不一致时尤其如此）
    if prefer_visual and visual_text:
        if not audio_text:
            return visual_segments, "visual_primary"
        sim = text_similarity(audio_text, visual_text)
        if sim < 0.72 or audio_unreliable:
            return visual_segments, "visual_primary" if sim < 0.45 else "hybrid_visual"

    visual_ok, _ = is_subtitle_quality_acceptable(
        visual_text, slot_duration, duplicate_peers=0
    ) if visual_text else (False, "empty")

    # 音频不可靠（杂音/乱码/低置信）→ 优先画面烧录字幕
    if audio_unreliable and visual_text:
        return visual_segments, "visual_audio_fallback"

    if audio_text and not visual_text:
        ok, _ = is_subtitle_quality_acceptable(
            audio_text,
            slot_duration,
            duplicate_peers=count_near_duplicate_peers(audio_text, peers),
        )
        return audio_segments, "whisper" if ok else "whisper_low_quality"

    audio_dup = count_near_duplicate_peers(audio_text, peers)
    visual_dup = count_near_duplicate_peers(visual_text, peers)
    audio_ok, audio_reason = is_subtitle_quality_acceptable(
        audio_text, slot_duration, duplicate_peers=audio_dup
    )
    if not visual_ok and visual_text:
        visual_ok = True
    sim = text_similarity(audio_text, visual_text)

    audio_score = score_subtitle_text(
        audio_text, slot_duration, peers, source_kind="clip"
    )
    visual_score = score_subtitle_text(
        visual_text, slot_duration, peers, source_kind="visual", visual_boost=visual_boost
    )

    if visual_ok and (not audio_ok or audio_dup >= 1 or audio_reason == "duplicate_across_slots"):
        return visual_segments, "visual_primary"

    if visual_ok and audio_ok and sim >= 0.62:
        return visual_segments, "hybrid_visual"

    if visual_ok and visual_score >= audio_score - 4.0:
        return visual_segments, "hybrid_visual"
    if audio_ok:
        return audio_segments, "hybrid_whisper"

    if visual_text:
        return visual_segments, "visual_primary"
    return audio_segments, "whisper_low_quality"


def template_prefers_visual_subtitles(
    sample_texts: list[str],
    *,
    min_hits: int = 2,
) -> bool:
    """批量识别前探测：若多槽能 OCR 出中文，则后续优先画面字幕。"""
    hits = [
        t
        for t in sample_texts
        if t and _char_count(t) >= 4 and len(re.findall(r"[\u4e00-\u9fff]", t)) >= 2
    ]
    return len(hits) >= max(1, min_hits)
