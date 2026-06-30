"""特效库：预设加载、应用到槽位/字幕；AI 识别结果映射到预设。"""

import copy
import json
import os
from functools import lru_cache
from typing import Any

_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "effects_catalog.json")

_SUBTITLE_STYLE_KEYS = (
    "animation_in",
    "animation_out",
    "animation_loop",
    "text_color",
    "outline_color",
    "font_size",
    "position",
)

_MOTION_TO_VIDEO_PRESET = {
    "zoom_in": "vid_zoom_in_slow",
    "zoom_out": "vid_zoom_out_slow",
}

_COLOR_MOOD_TO_GRADE_PRESET = {
    "warm": "grade_warm",
    "cool": "grade_cool",
    "vivid": "grade_vivid",
    "cinematic": "grade_cinematic",
    "neutral": "",
}

_TRANSITION_HINT_TO_PRESET = {
    "fade": "trans_fade",
    "dissolve": "trans_dissolve",
    "wipe": "trans_wipe",
    "slide": "trans_slide",
    "cut": "trans_fade",
}

@lru_cache(maxsize=1)
def load_effects_catalog() -> dict[str, Any]:
    path = os.path.abspath(_CATALOG_PATH)
    if not os.path.isfile(path):
        return {"version": 1, "categories": []}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {"version": 1, "categories": []}


def list_catalog_categories() -> list[dict[str, Any]]:
    catalog = load_effects_catalog()
    categories = catalog.get("categories") or []
    return [c for c in categories if isinstance(c, dict)]


def find_preset(preset_id: str) -> dict[str, Any] | None:
    pid = str(preset_id or "").strip()
    if not pid:
        return None
    for category in list_catalog_categories():
        for preset in category.get("presets") or []:
            if isinstance(preset, dict) and str(preset.get("id")) == pid:
                return {
                    **preset,
                    "category_id": category.get("id"),
                    "category_label": category.get("label"),
                }
    return None


def _merge_style(existing: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    base = dict(existing or {})
    for key in ("animation_in", "animation_out", "animation_loop", "text_color", "outline_color", "font_size", "position"):
        if key in patch and patch[key] is not None:
            base[key] = patch[key]
    return base


def apply_preset_to_slot(slot: dict[str, Any], preset_id: str) -> dict[str, Any]:
    """将特效库预设应用到槽位，返回更新后的槽位 dict。"""
    preset = find_preset(preset_id)
    if not preset:
        raise ValueError(f"未找到特效预设: {preset_id}")

    apply = preset.get("apply") if isinstance(preset.get("apply"), dict) else {}
    item = copy.deepcopy(slot)

    if "color_grade" in apply:
        item["color_grade"] = {**(item.get("color_grade") or {}), **apply["color_grade"]}

    if "transition_out" in apply:
        item["transition_out"] = {**(item.get("transition_out") or {}), **apply["transition_out"]}

    if "keyframes" in apply:
        item["keyframes"] = copy.deepcopy(apply["keyframes"])

    if "speed" in apply:
        item["speed"] = apply["speed"]

    subtitle_keys = ("animation_in", "animation_out", "animation_loop", "text_color", "outline_color", "font_size", "position")
    subtitle_patch = {k: apply[k] for k in subtitle_keys if k in apply}
    if subtitle_patch:
        sub_segs = list(item.get("subtitle_segments") or [])
        if sub_segs:
            item["subtitle_segments"] = [
                {**seg, "style": _merge_style(seg.get("style") if isinstance(seg.get("style"), dict) else None, subtitle_patch)}
                for seg in sub_segs
                if isinstance(seg, dict)
            ]
        else:
            item["subtitle_style"] = _merge_style(
                item.get("subtitle_style") if isinstance(item.get("subtitle_style"), dict) else None,
                subtitle_patch,
            )

    applied = list(item.get("applied_effect_presets") or [])
    if preset_id not in applied:
        applied.append(preset_id)
    item["applied_effect_presets"] = applied[-20:]
    return item


def _extract_subtitle_style(slot: dict[str, Any]) -> dict[str, Any]:
    """从槽位或首条字幕分段提取样式。"""
    style = slot.get("subtitle_style")
    if isinstance(style, dict) and style:
        return dict(style)
    for seg in slot.get("subtitle_segments") or []:
        if not isinstance(seg, dict):
            continue
        seg_style = seg.get("style")
        if isinstance(seg_style, dict) and seg_style:
            return dict(seg_style)
    auto = slot.get("auto_effects") if isinstance(slot.get("auto_effects"), dict) else {}
    sub = auto.get("subtitle_style")
    return dict(sub) if isinstance(sub, dict) else {}


def _find_preset_by_apply_field(field: str, value: Any, category_ids: tuple[str, ...] | None = None) -> str | None:
    if value is None or value == "" or value == "none":
        return None
    want = str(value).strip()
    for category in list_catalog_categories():
        if category_ids and str(category.get("id")) not in category_ids:
            continue
        for preset in category.get("presets") or []:
            if not isinstance(preset, dict):
                continue
            apply = preset.get("apply") if isinstance(preset.get("apply"), dict) else {}
            if str(apply.get(field, "")).strip() == want:
                return str(preset.get("id"))
    return None


def validate_catalog_preset_ids(preset_ids: list[Any] | None) -> list[str]:
    out: list[str] = []
    for raw in preset_ids or []:
        pid = str(raw or "").strip()
        if pid and find_preset(pid) and pid not in out:
            out.append(pid)
    return out


def suggest_presets_from_subtitle_style(style: dict[str, Any] | None) -> list[str]:
    if not isinstance(style, dict):
        return []
    ids: list[str] = []
    for field, categories in (
        ("animation_in", ("subtitle_in",)),
        ("animation_out", ("subtitle_out",)),
        ("animation_loop", ("subtitle_loop",)),
    ):
        pid = _find_preset_by_apply_field(field, style.get(field), categories)
        if pid and pid not in ids:
            ids.append(pid)
    return ids


def suggest_presets_from_auto_effects(auto: dict[str, Any] | None) -> list[str]:
    if not isinstance(auto, dict):
        return []
    ids: list[str] = []

    motion = str(auto.get("motion") or "").lower()
    vid = _MOTION_TO_VIDEO_PRESET.get(motion)
    if vid and vid not in ids:
        ids.append(vid)

    sub_style = auto.get("subtitle_style") if isinstance(auto.get("subtitle_style"), dict) else {}
    for pid in suggest_presets_from_subtitle_style(sub_style):
        if pid not in ids:
            ids.append(pid)

    mood = str(auto.get("color_mood") or "").lower()
    grade_pid = _COLOR_MOOD_TO_GRADE_PRESET.get(mood)
    if grade_pid and grade_pid not in ids:
        ids.append(grade_pid)
    elif auto.get("color_grade") and not grade_pid:
        for preset_id in ("grade_cinematic", "grade_vivid", "grade_warm", "grade_cool"):
            preset = find_preset(preset_id)
            if not preset:
                continue
            apply_grade = (preset.get("apply") or {}).get("color_grade") or {}
            slot_grade = auto.get("color_grade") or {}
            if (
                abs(float(apply_grade.get("saturation", 1)) - float(slot_grade.get("saturation", 1))) < 0.08
                and abs(float(apply_grade.get("contrast", 1)) - float(slot_grade.get("contrast", 1))) < 0.08
            ):
                ids.append(preset_id)
                break

    trans = auto.get("transition_out") if isinstance(auto.get("transition_out"), dict) else {}
    trans_type = str(trans.get("type") or "").lower()
    hint = "dissolve" if trans_type == "dissolve" else "wipe" if "wipe" in trans_type else "fade"
    trans_pid = _TRANSITION_HINT_TO_PRESET.get(hint)
    if trans_pid and trans_pid not in ids:
        ids.append(trans_pid)

    for raw in auto.get("catalog_preset_ids") or []:
        pid = str(raw or "").strip()
        if pid and find_preset(pid) and pid not in ids:
            ids.append(pid)

    return ids


def build_catalog_ai_reference(*, max_per_category: int = 12) -> str:
    """供 AI 提示词使用的特效库摘要（preset id + 名称）。"""
    lines = ["系统特效库 preset id（输出 catalog_preset_ids 时请只使用下列 id）："]
    for category in list_catalog_categories():
        presets = category.get("presets") or []
        chunk: list[str] = []
        for preset in presets[:max_per_category]:
            if isinstance(preset, dict) and preset.get("id"):
                chunk.append(f"{preset['id']}={preset.get('name', preset['id'])}")
        if chunk:
            lines.append(f"- {category.get('label', category.get('id'))}: " + ", ".join(chunk))
    return "\n".join(lines)


def build_ai_effect_understanding(slot: dict[str, Any]) -> dict[str, Any]:
    """将槽位上 AI/识别出的样式与 auto_effects 映射为特效库理解结果。"""
    style = _extract_subtitle_style(slot)
    auto = slot.get("auto_effects") if isinstance(slot.get("auto_effects"), dict) else {}

    preset_ids: list[str] = []
    for pid in suggest_presets_from_subtitle_style(style):
        if pid not in preset_ids:
            preset_ids.append(pid)
    for pid in suggest_presets_from_auto_effects(auto):
        if pid not in preset_ids:
            preset_ids.append(pid)

    labels: list[str] = []
    for pid in preset_ids:
        preset = find_preset(pid)
        name = str(preset.get("name") or pid).strip() if preset else pid
        if name and name not in labels:
            labels.append(name)

    summary_parts: list[str] = []
    label = str(slot.get("subtitle_effect_label") or slot.get("template_effect_label") or "").strip()
    if label:
        summary_parts.append(label)
    if labels:
        summary_parts.append(" · ".join(labels[:4]))
    visual = str(slot.get("subtitle_visual_context") or slot.get("ai_description") or "").strip()
    if visual:
        summary_parts.append(visual[:40])

    return {
        "catalog_preset_ids": preset_ids,
        "preset_labels": labels,
        "summary": " · ".join(summary_parts)[:120] if summary_parts else "",
        "subtitle_match": slot.get("subtitle_scene_match"),
        "subtitle_match_reason": slot.get("subtitle_scene_match_reason"),
        "visual_context": slot.get("subtitle_visual_context") or slot.get("ai_description"),
        "source": "effects_catalog",
    }


def enrich_slot_catalog_understanding(
    slot: dict[str, Any],
    *,
    ai_preset_ids: list[Any] | None = None,
    apply_suggested_presets: bool = False,
) -> dict[str, Any]:
    """AI 识别后：理解特效库逻辑，写入 ai_effect_understanding；可选自动套用预设。"""
    item = copy.deepcopy(slot)

    validated_ai = validate_catalog_preset_ids(ai_preset_ids)
    understanding = build_ai_effect_understanding(item)
    merged_ids = list(validated_ai)
    for pid in understanding.get("catalog_preset_ids") or []:
        if pid not in merged_ids:
            merged_ids.append(pid)
    understanding["catalog_preset_ids"] = merged_ids
    understanding["preset_labels"] = [
        str(find_preset(pid).get("name") or pid) for pid in merged_ids if find_preset(pid)
    ]
    item["ai_effect_understanding"] = understanding

    if apply_suggested_presets and merged_ids:
        for pid in merged_ids[:8]:
            try:
                item = apply_preset_to_slot(item, pid)
            except ValueError:
                continue

    return item


def merge_auto_effects_into_slot(slot: dict[str, Any]) -> dict[str, Any]:
    """导出前：将 AI 识别的 auto_effects 合并进槽位（不覆盖用户已手动设置的特效）。"""
    auto = slot.get("auto_effects") if isinstance(slot.get("auto_effects"), dict) else {}
    if not auto:
        return slot

    item = copy.deepcopy(slot)
    from services.video_exporter import slot_has_post_effects

    if not slot_has_post_effects(item):
        if auto.get("color_grade"):
            item["color_grade"] = {**(item.get("color_grade") or {}), **auto["color_grade"]}
        if auto.get("transition_out"):
            item["transition_out"] = {**(item.get("transition_out") or {}), **auto["transition_out"]}
        if auto.get("keyframes") and not item.get("keyframes"):
            item["keyframes"] = copy.deepcopy(auto["keyframes"])
        if auto.get("speed") and abs(float(item.get("speed") or 1) - 1.0) < 0.01:
            item["speed"] = float(auto["speed"])

    sub_style = auto.get("subtitle_style") if isinstance(auto.get("subtitle_style"), dict) else {}
    if sub_style:
        sub_segs = list(item.get("subtitle_segments") or [])
        if sub_segs:
            item["subtitle_segments"] = [
                {
                    **seg,
                    "style": _merge_style(
                        seg.get("style") if isinstance(seg.get("style"), dict) else None,
                        sub_style,
                    ),
                }
                for seg in sub_segs
                if isinstance(seg, dict)
            ]
        elif not item.get("subtitle_style"):
            item["subtitle_style"] = dict(sub_style)

    return item
