"""AI 分析模板视频每槽位的画面特效与字幕动画风格。"""

import json
import os
import re
from typing import Any

from services.deepseek_client import chat_vision, deepseek_enabled
from services.effects_catalog import build_catalog_ai_reference, enrich_slot_catalog_understanding, validate_catalog_preset_ids
from services.processing_config import (
    ENABLE_TEMPLATE_EFFECTS_ANALYSIS,
    TEMPLATE_EFFECTS_MAX_SLOTS,
)
from services.scene_detector import extract_frame

_SLOT_EFFECT_PROMPT = (
    "你是短视频剪辑特效分析师。根据这一镜头截图，识别该镜头的剪辑特效特征。"
    "输出严格 JSON（无 markdown）："
    '{"motion":"static|zoom_in|zoom_out|pan_left|pan_right","color_mood":"warm|cool|vivid|cinematic|neutral",'
    '"contrast":1.0,"saturation":1.0,"brightness":0.0,"transition_hint":"fade|dissolve|cut|wipe",'
    '"subtitle_animation_in":"fade|fade_up|fade_down|scale|bounce|typewriter|none",'
    '"subtitle_animation_out":"fade|fade_up|fade_down|scale_out|none",'
    '"subtitle_animation_loop":"none|pulse|shake|glow|wave",'
    '"effect_label":"10字内特效描述",'
    '"catalog_preset_ids":["sub_in_fade","vid_zoom_in_slow","grade_warm"]'
    "}"
)


def _parse_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if m:
            raw = m.group(1).strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _color_mood_to_grade(mood: str) -> dict[str, float]:
    mood = str(mood or "neutral").lower()
    if mood == "warm":
        return {"contrast": 1.02, "saturation": 1.08, "brightness": 0.03, "hue": 8}
    if mood == "cool":
        return {"contrast": 1.04, "saturation": 0.95, "brightness": 0.01, "hue": -12}
    if mood == "vivid":
        return {"contrast": 1.05, "saturation": 1.22, "brightness": 0.02}
    if mood == "cinematic":
        return {"contrast": 1.12, "saturation": 0.9, "brightness": -0.03}
    return {"contrast": 1.0, "saturation": 1.0, "brightness": 0.0}


def _motion_to_keyframes(motion: str) -> list[dict[str, Any]] | None:
    motion = str(motion or "static").lower()
    if motion == "zoom_in":
        return [
            {"time": 0, "props": {"scale": 1.0, "opacity": 1.0}},
            {"time": 1, "props": {"scale": 1.1, "opacity": 1.0}},
        ]
    if motion == "zoom_out":
        return [
            {"time": 0, "props": {"scale": 1.1, "opacity": 1.0}},
            {"time": 1, "props": {"scale": 1.0, "opacity": 1.0}},
        ]
    if motion in ("pan_left", "pan_right"):
        return [
            {"time": 0, "props": {"scale": 1.05, "opacity": 1.0}},
            {"time": 1, "props": {"scale": 1.08, "opacity": 1.0}},
        ]
    return None


def _transition_hint_to_out(hint: str) -> dict[str, Any]:
    hint = str(hint or "fade").lower()
    mapping = {
        "fade": {"type": "fade", "duration": 0.35},
        "dissolve": {"type": "dissolve", "duration": 0.4},
        "wipe": {"type": "wipeleft", "duration": 0.35},
        "cut": {"type": "fade", "duration": 0.12},
    }
    return mapping.get(hint, mapping["fade"])


def _slot_frame_path(slot: dict[str, Any], video_path: str, work_dir: str, index: int) -> str:
    thumb = str(slot.get("thumbnail") or "").strip()
    if thumb and os.path.isfile(thumb):
        return thumb

    start = float(slot.get("start", slot.get("clip_start", 0)))
    duration = float(slot.get("duration", slot.get("clip_duration", 1)))
    t = start + duration * 0.45
    os.makedirs(work_dir, exist_ok=True)
    out = os.path.join(work_dir, f"effect_frame_{index:03d}.jpg")
    if not os.path.isfile(out):
        extract_frame(video_path, t, out)
    return out if os.path.isfile(out) else ""


def analyze_slot_effects(
    video_path: str,
    slot: dict[str, Any],
    *,
    frame_path: str = "",
    index: int = 0,
    work_dir: str = "",
) -> dict[str, Any]:
    """单槽位 AI 特效理解，返回 auto_effects 结构。"""
    if not ENABLE_TEMPLATE_EFFECTS_ANALYSIS or not deepseek_enabled():
        return {}

    frame = frame_path or _slot_frame_path(slot, video_path, work_dir, index)
    if not frame:
        return {}

    try:
        subtitle_hint = str(slot.get("subtitle_text") or "").strip()
        catalog_ref = build_catalog_ai_reference()
        prompt = catalog_ref + "\n" + _SLOT_EFFECT_PROMPT
        if subtitle_hint:
            prompt = f"该镜头字幕为「{subtitle_hint[:48]}」。请结合字幕含义与特效库 preset id 判断画面特效。" + prompt
        reply = chat_vision(prompt, [frame], max_tokens=280, temperature=0.15)
        parsed = _parse_json(reply)
        if not parsed:
            return {}

        motion = str(parsed.get("motion") or "static")
        color_grade = _color_mood_to_grade(parsed.get("color_mood"))
        for key in ("contrast", "saturation", "brightness"):
            if parsed.get(key) is not None:
                try:
                    color_grade[key] = float(parsed[key])
                except (TypeError, ValueError):
                    pass

        subtitle_style = {
            "animation_in": str(parsed.get("subtitle_animation_in") or "fade"),
            "animation_out": str(parsed.get("subtitle_animation_out") or "fade"),
            "animation_loop": str(parsed.get("subtitle_animation_loop") or "none"),
        }

        catalog_ids = validate_catalog_preset_ids(parsed.get("catalog_preset_ids"))

        auto_effects: dict[str, Any] = {
            "effect_label": str(parsed.get("effect_label") or "").strip()[:24],
            "motion": motion,
            "color_mood": str(parsed.get("color_mood") or "neutral"),
            "color_grade": color_grade,
            "transition_out": _transition_hint_to_out(parsed.get("transition_hint")),
            "subtitle_style": subtitle_style,
            "catalog_preset_ids": catalog_ids,
            "source": "ai",
        }
        keyframes = _motion_to_keyframes(motion)
        if keyframes:
            auto_effects["keyframes"] = keyframes
        return auto_effects
    except Exception as exc:
        print(f"槽位特效 AI 分析失败 #{index}: {exc}")
        return {}


def enrich_slots_with_ai_effects(
    video_path: str,
    slots: list[dict[str, Any]],
    work_dir: str,
) -> list[dict[str, Any]]:
    """为模板槽位批量补充 auto_effects，并写入 subtitle_segments.style。"""
    if not slots or not ENABLE_TEMPLATE_EFFECTS_ANALYSIS:
        return slots

    limit = max(1, TEMPLATE_EFFECTS_MAX_SLOTS)
    result: list[dict[str, Any]] = []
    analyzed = 0

    for index, slot in enumerate(slots):
        item = dict(slot) if isinstance(slot, dict) else {}
        if analyzed < limit:
            auto = analyze_slot_effects(
                video_path,
                item,
                index=index,
                work_dir=os.path.join(work_dir, "effect_frames"),
            )
            if auto:
                item["auto_effects"] = auto
                if auto.get("effect_label"):
                    item["template_effect_label"] = auto["effect_label"]
                sub_style = auto.get("subtitle_style") if isinstance(auto.get("subtitle_style"), dict) else {}
                sub_segs = list(item.get("subtitle_segments") or [])
                if sub_segs and sub_style:
                    merged = []
                    for seg in sub_segs:
                        if not isinstance(seg, dict):
                            continue
                        style = dict(seg.get("style") or {})
                        for k, v in sub_style.items():
                            if v and v != "none" and k not in style:
                                style[k] = v
                        merged.append({**seg, "style": style})
                    item["subtitle_segments"] = merged
                item = enrich_slot_catalog_understanding(
                    item,
                    ai_preset_ids=auto.get("catalog_preset_ids"),
                )
                analyzed += 1
        result.append(item)

    print(f"模板槽位特效 AI 分析完成: {analyzed}/{len(slots)} 段")
    return result
