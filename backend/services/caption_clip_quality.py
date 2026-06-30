"""sentenceClip / subtitleClip 质量评分与乱码检测。"""

from __future__ import annotations

import re
from typing import Any

from services.subtitle_config import SubtitleConfig, get_subtitle_config
from services.subtitle_gen import normalize_chinese_subtitle

_REPLACEMENT = "\ufffd"
_GARBLED = re.compile(r"[\ufffd\u0000-\u001f]|(?:\?\?+)")


def _char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def is_garbled_text(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return True
    if _REPLACEMENT in t or _GARBLED.search(t):
        return True
    cjk = len(re.findall(r"[\u4e00-\u9fff]", t))
    if _char_count(t) >= 4 and cjk == 0 and not re.search(r"[a-zA-Z]{3,}", t):
        return True
    return False


def score_clip_quality(
    clip: dict[str, Any],
    *,
    config: SubtitleConfig | None = None,
) -> dict[str, Any]:
    cfg = config or get_subtitle_config()
    text = normalize_chinese_subtitle(str(clip.get("text") or clip.get("displayText") or ""))
    start = float(clip.get("start", 0))
    end = float(clip.get("end", start))
    dur = max(0.05, end - start)
    chars = _char_count(text)
    conf = float(clip.get("confidence") or 0.5)
    source = str(clip.get("source") or "asr")
    fusion = clip.get("fusionDebug") if isinstance(clip.get("fusionDebug"), dict) else {}

    reasons: list[str] = []
    text_conf = min(1.0, conf)
    time_conf = 0.85 if dur >= cfg.clip_min_duration else max(0.2, dur / max(cfg.clip_min_duration, 0.1))

    if is_garbled_text(text):
        reasons.append("garbled_text")
        text_conf = min(text_conf, 0.25)
    if chars < cfg.clip_min_chars:
        reasons.append("too_short_text")
        text_conf = min(text_conf, 0.45)
    if dur < 0.6:
        reasons.append("too_short_duration")
        time_conf = min(time_conf, 0.35)
    if conf < 0.4:
        reasons.append("low_asr_confidence")
        text_conf = min(text_conf, conf)
    if source == "asr" and fusion.get("asrText") and fusion.get("ocrText"):
        sim = float(fusion.get("similarity") or 0)
        if sim < 0.45:
            reasons.append("asr_ocr_mismatch")
            text_conf = min(text_conf, 0.5)
    validation = clip.get("validationDebug") if isinstance(clip.get("validationDebug"), dict) else {}
    if validation.get("validationAction") == "mismatch":
        reasons.append("asr_ocr_mismatch")
        text_conf = min(text_conf, 0.5)
    if validation.get("ocrMatched") is False and validation.get("validationAction") == "asr_only":
        reasons.append("no_ocr_validation")
        text_conf = min(text_conf, 0.65)
    if not text.strip():
        reasons.append("empty_text")
        text_conf = 0.0

    needs_review = bool(reasons) or text_conf < 0.55 or time_conf < 0.5
    return {
        "textConfidence": round(text_conf, 3),
        "timeConfidence": round(time_conf, 3),
        "source": source,
        "needsReview": needs_review,
        "reasons": reasons,
    }


def attach_quality_to_clips(
    clips: list[dict[str, Any]],
    *,
    config: SubtitleConfig | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for clip in clips or []:
        if not isinstance(clip, dict):
            continue
        item = dict(clip)
        text = normalize_chinese_subtitle(str(item.get("text") or ""))
        if text:
            item["text"] = text
            if not item.get("displayText"):
                item["displayText"] = text
        item["quality"] = score_clip_quality(item, config=config)
        out.append(item)
    return out
