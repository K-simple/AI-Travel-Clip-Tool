"""口播字幕特效 profile 与轻量语义 renderHints。"""

from __future__ import annotations

import re
import uuid
from typing import Any

DEFAULT_SPEECH_EFFECT_PROFILE: dict[str, Any] = {
    "effectProfileId": "default_speech_caption",
    "name": "口播默认字幕",
    "baseStyle": {
        "fontFamily": "Microsoft YaHei",
        "fontSize": 54,
        "fontWeight": "normal",
        "color": "#FFFFFF",
        "strokeColor": "#000000",
        "strokeWidth": 3,
        "shadow": {"blur": 0, "offsetX": 0, "offsetY": 0, "color": "#00000080"},
        "background": {},
        "opacity": 1,
    },
    "layout": {
        "x": 0.5,
        "y": 0.82,
        "anchor": "center",
        "maxWidth": 0.86,
        "align": "center",
        "maxLines": 2,
    },
    "animation": {
        "in": {"type": "fade", "duration": 0.15},
        "out": {"type": "fade", "duration": 0.1},
    },
    "highlight": {
        "enabled": False,
        "mode": "none",
        "color": "#FACE15",
        "strategy": "keywords",
    },
    "timingRules": {
        "minDuration": 0.8,
        "maxDuration": 5.5,
        "charsPerSecond": 8,
        "lineBreakMode": "semantic",
    },
}

_EMPHASIS_KEYWORDS = ("重点", "关键", "注意", "必须", "技巧", "方法", "秘诀", "推荐", "最好", "一定")


def normalize_effect_profile_from_slot(slot: dict[str, Any] | None) -> dict[str, Any]:
    """从槽位已有 subtitle_style 归一化为 effectProfile。"""
    profile = dict(DEFAULT_SPEECH_EFFECT_PROFILE)
    profile["effectProfileId"] = f"slot_{slot.get('slot_id') or slot.get('id') or uuid.uuid4().hex[:8]}"
    if not isinstance(slot, dict):
        return profile

    style = slot.get("subtitle_style") if isinstance(slot.get("subtitle_style"), dict) else {}
    if style:
        base = profile["baseStyle"]
        if style.get("font_size"):
            base["fontSize"] = int(style["font_size"])
        if style.get("font_color") or style.get("color"):
            base["color"] = str(style.get("font_color") or style.get("color"))
        if style.get("stroke_color"):
            base["strokeColor"] = str(style["stroke_color"])
        if style.get("stroke_width") is not None:
            base["strokeWidth"] = int(style["stroke_width"])
        pos = str(style.get("position") or "bottom").lower()
        layout = profile["layout"]
        if pos == "top":
            layout["y"] = 0.12
        elif pos == "center":
            layout["y"] = 0.5

    label = str(slot.get("subtitle_effect_label") or "").strip()
    if label:
        profile["name"] = label

    return profile


def get_default_speech_effect_profile() -> dict[str, Any]:
    return dict(DEFAULT_SPEECH_EFFECT_PROFILE)


def analyze_segment_render_hints(text: str, *, confidence: float = 0.5) -> dict[str, Any]:
    """轻量语义分析：不改变 ASR 原文，仅生成 renderHints。"""
    cleaned = (text or "").strip()
    keywords = [w for w in _EMPHASIS_KEYWORDS if w in cleaned]
    is_question = cleaned.endswith("?") or cleaned.endswith("？")
    is_exclaim = cleaned.endswith("!") or cleaned.endswith("！")
    emphasis = bool(keywords) or is_exclaim or (is_question and confidence >= 0.5)

    line_breaks: list[int] = []
    if "\\N" in cleaned:
        acc = 0
        for part in cleaned.split("\\N"):
            acc += len(part)
            line_breaks.append(acc)

    intensity = "normal"
    if emphasis and confidence >= 0.65:
        intensity = "strong"
    elif confidence < 0.45:
        intensity = "weak"

    return {
        "emphasis": emphasis,
        "keywords": keywords[:5],
        "lineBreaks": line_breaks,
        "animationIntensity": intensity,
        "sentenceType": "question" if is_question else ("exclaim" if is_exclaim else "statement"),
    }


def attach_effect_to_segments(
    segments: list[dict[str, Any]],
    effect_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    profile = effect_profile or get_default_speech_effect_profile()
    pid = profile.get("effectProfileId") or "default_speech_caption"
    out: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        item = dict(seg)
        text = str(item.get("text") or "")
        conf = float(item.get("confidence") or 0.5)
        item["effectProfileId"] = pid
        item["renderHints"] = analyze_segment_render_hints(text, confidence=conf)
        item.setdefault("type", "spoken_caption")
        out.append(item)
    return out
