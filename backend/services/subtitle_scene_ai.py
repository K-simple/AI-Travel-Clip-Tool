"""字幕与画面对齐：AI 理解花字特效 + 字幕是否匹配镜头内容。"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from services.processing_config import (
    ENABLE_SUBTITLE_SCENE_AI,
    SUBTITLE_SCENE_MAX_SLOTS,
)
from services.effects_catalog import build_catalog_ai_reference, enrich_slot_catalog_understanding
from services.scene_detector import extract_frame
from services.subtitle_style_analyzer import analyze_segment_style, _default_style

_POSITION_TRANSFORM_Y = {
    "top": 720,
    "center": 0,
    "bottom": -400,
}

_SCENE_AI_PROMPT = (
    "你是短视频字幕与画面分析师。根据镜头截图和已识别字幕文案，完成："
    "1) 描述画面主体与场景；"
    "2) 识别烧录字幕的花字样式（颜色、入场/出场/循环动画）；"
    "3) 判断字幕内容与画面是否语义一致（如介绍客人时画面应有人/接待场景）。"
    "输出严格 JSON（无 markdown）："
    '{"scene_summary":"20字内画面描述",'
    '"visual_subject":"画面主体",'
    '"scene_tags":["标签1","标签2"],'
    '"subtitle_on_screen":"画面中实际字幕，无则空字符串",'
    '"subtitle_match_score":0.85,'
    '"match_reason":"10字内匹配说明",'
    '"subtitle_effects":{'
    '"text_color":"#RRGGBB","outline_color":"#RRGGBB",'
    '"animation_in":"fade|fade_up|fade_down|bounce|scale|typewriter|none",'
    '"animation_out":"fade|fade_up|fade_down|scale_out|none",'
    '"animation_loop":"none|pulse|shake|glow|wave",'
    '"position":"bottom|center|top",'
    '"style_label":"10字内花字描述"'
    "},"
    '"catalog_preset_ids":["sub_in_fade_up","sub_out_fade"]'
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
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _slot_source_range(slot: dict[str, Any]) -> tuple[float, float]:
    if slot.get("clip_start") is not None:
        start = float(slot["clip_start"])
        if slot.get("clip_end") is not None:
            end = float(slot["clip_end"])
        elif slot.get("clip_duration") is not None:
            end = start + float(slot["clip_duration"])
        else:
            end = start + float(slot.get("duration") or slot.get("slot_duration") or 0.1)
        return start, max(start + 0.1, end)

    start = float(slot.get("start", slot.get("start_time", slot.get("slot_start", 0))))
    if "end" in slot:
        end = float(slot["end"])
    elif "end_time" in slot:
        end = float(slot["end_time"])
    else:
        end = start + float(slot.get("duration") or slot.get("slot_duration") or 0.1)
    return start, max(start + 0.1, end)


def _slot_frame_path(
    video_path: str,
    slot: dict[str, Any],
    work_dir: str,
    index: int,
) -> str:
    thumb = str(slot.get("thumbnail") or slot.get("template_thumbnail") or "").strip()
    if thumb and os.path.isfile(thumb):
        return thumb

    start, end = _slot_source_range(slot)
    t = start + (end - start) * 0.45
    os.makedirs(work_dir, exist_ok=True)
    out = os.path.join(work_dir, f"scene_frame_{index:03d}.jpg")
    if not os.path.isfile(out):
        extract_frame(video_path, t, out)
    return out if os.path.isfile(out) else ""


def _normalize_effects(raw: dict[str, Any] | None, fallback: dict[str, Any]) -> dict[str, Any]:
    style = dict(fallback)
    if not isinstance(raw, dict):
        return style

    for key in ("text_color", "outline_color", "animation_in", "animation_out", "animation_loop", "position", "style_label"):
        val = raw.get(key)
        if val:
            style[key] = str(val)

    if style.get("font_size") is None and fallback.get("font_size"):
        style["font_size"] = fallback["font_size"]

    position = str(style.get("position") or "bottom")
    if position in _POSITION_TRANSFORM_Y:
        style["transform_y"] = _POSITION_TRANSFORM_Y[position]

    style.setdefault("alignment", "center")
    style.setdefault("bold", False)
    style.setdefault("confidence", max(float(fallback.get("confidence", 0.5)), 0.6))
    return style


def _merge_style_into_segments(segments: list, style: dict[str, Any]) -> list:
    if not style or not segments:
        return segments
    merged: list = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        base = dict(seg.get("style") or {})
        for key, val in style.items():
            if val is None or val == "":
                continue
            if key not in base or base.get(key) in (None, "", "none"):
                base[key] = val
        merged.append({**seg, "style": base})
    return merged


def _opencv_style_fallback(
    video_path: str,
    slot: dict[str, Any],
    subtitle_text: str,
    work_dir: str,
) -> dict[str, Any]:
    start, end = _slot_source_range(slot)
    try:
        style = analyze_segment_style(
            video_path,
            {"start": start, "end": end, "text": subtitle_text},
            work_dir,
            use_vision=False,
        )
    except Exception:
        style = _default_style()
    return style


def analyze_slot_subtitle_scene(
    video_path: str,
    slot: dict[str, Any],
    subtitle_text: str,
    subtitle_segments: list | None = None,
    *,
    index: int = 0,
    work_dir: str = "",
    use_vision: bool = True,
) -> dict[str, Any]:
    """分析单槽：花字特效 + 字幕与画面对齐。返回可合并进 slot 的字段。"""
    if not ENABLE_SUBTITLE_SCENE_AI or not video_path or not os.path.isfile(video_path):
        return {}

    text = (subtitle_text or "").strip()
    if not text:
        return {}

    style_dir = work_dir or os.path.join(os.path.dirname(video_path), "subtitle_scene")
    opencv_style = _opencv_style_fallback(video_path, slot, text, os.path.join(style_dir, "opencv"))

    updates: dict[str, Any] = {
        "subtitle_style": opencv_style,
        "subtitle_effect_label": str(opencv_style.get("style_label") or "").strip(),
    }

    parsed: dict[str, Any] = {}
    if use_vision:
        try:
            from services.deepseek_client import chat_vision, deepseek_enabled

            if deepseek_enabled():
                frame = _slot_frame_path(video_path, slot, os.path.join(style_dir, "frames"), index)
                if frame:
                    catalog_ref = build_catalog_ai_reference()
                    prompt = (
                        _SCENE_AI_PROMPT
                        + f"\n已识别字幕：「{text[:80]}」"
                        + f"\n\n{catalog_ref}"
                    )
                    reply = chat_vision(prompt, [frame], max_tokens=380, temperature=0.12)
                    parsed = _parse_json(reply)
        except Exception as exc:
            print(f"字幕场景 AI 分析失败 #{index}: {exc}")

    if parsed:
        scene_summary = str(parsed.get("scene_summary") or "").strip()
        visual_subject = str(parsed.get("visual_subject") or "").strip()
        match_reason = str(parsed.get("match_reason") or "").strip()
        if scene_summary:
            updates["subtitle_visual_context"] = scene_summary
        if visual_subject and not slot.get("ai_subject"):
            updates["ai_subject"] = visual_subject[:48]
        if scene_summary and not slot.get("ai_description"):
            updates["ai_description"] = scene_summary[:120]

        tags = parsed.get("scene_tags")
        if isinstance(tags, list) and tags and not slot.get("scene_tags"):
            updates["scene_tags"] = [str(t).strip() for t in tags if str(t).strip()][:8]

        try:
            score = float(parsed.get("subtitle_match_score", 0))
            updates["subtitle_scene_match"] = round(min(1.0, max(0.0, score)), 3)
        except (TypeError, ValueError):
            pass
        if match_reason:
            updates["subtitle_scene_match_reason"] = match_reason[:80]

        effects = _normalize_effects(parsed.get("subtitle_effects"), opencv_style)
        updates["subtitle_style"] = effects
        label = str(effects.get("style_label") or "").strip()
        if label:
            updates["subtitle_effect_label"] = label

    segments = list(subtitle_segments or slot.get("subtitle_segments") or [])
    style = updates.get("subtitle_style")
    if isinstance(style, dict) and segments:
        updates["subtitle_segments"] = _merge_style_into_segments(segments, style)

    ai_preset_ids = parsed.get("catalog_preset_ids") if isinstance(parsed.get("catalog_preset_ids"), list) else None
    merged_slot = {**slot, **updates}
    enriched = enrich_slot_catalog_understanding(merged_slot, ai_preset_ids=ai_preset_ids)
    updates["ai_effect_understanding"] = enriched.get("ai_effect_understanding")

    return updates


def enrich_slots_subtitle_scene(
    video_path: str,
    slots: list[dict[str, Any]],
    *,
    work_dir: str = "",
    max_slots: int | None = None,
) -> list[dict[str, Any]]:
    """批量为槽位补充字幕特效与画面对齐信息。"""
    if not slots or not ENABLE_SUBTITLE_SCENE_AI:
        return slots

    limit = max_slots if max_slots is not None else SUBTITLE_SCENE_MAX_SLOTS
    base_dir = work_dir or os.path.join(os.path.dirname(video_path), "subtitle_scene")
    result: list[dict[str, Any]] = []
    analyzed = 0

    for index, slot in enumerate(slots):
        item = dict(slot) if isinstance(slot, dict) else {}
        text = str(item.get("subtitle_text") or "").strip()
        if analyzed < limit and text:
            patch = analyze_slot_subtitle_scene(
                video_path,
                item,
                text,
                item.get("subtitle_segments"),
                index=index,
                work_dir=base_dir,
            )
            if patch:
                item = {**item, **patch}
                analyzed += 1
        result.append(item)

    if analyzed:
        print(f"字幕场景 AI 分析完成: {analyzed}/{len(slots)} 槽")
    return result


def enrich_slot_after_subtitle_recognition(
    video_path: str,
    slot: dict[str, Any],
    subtitle_text: str,
    subtitle_segments: list,
    *,
    index: int = 0,
    work_dir: str = "",
) -> dict[str, Any]:
    """识别完成后合并花字 + 画面对齐字段。"""
    patch = analyze_slot_subtitle_scene(
        video_path,
        {**slot, "subtitle_text": subtitle_text, "subtitle_segments": subtitle_segments},
        subtitle_text,
        subtitle_segments,
        index=index,
        work_dir=work_dir,
    )
    if not patch:
        return {
            "subtitle_text": subtitle_text,
            "subtitle_segments": subtitle_segments,
        }
    result = {
        "subtitle_text": subtitle_text,
        "subtitle_segments": patch.get("subtitle_segments") or subtitle_segments,
    }
    for key, val in patch.items():
        if key not in ("subtitle_text", "subtitle_segments"):
            result[key] = val
    return result
