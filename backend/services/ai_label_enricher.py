"""DeepSeek V4 中文画面描述与关键词标签。"""

import json
import os
import re
from typing import Any

from services.deepseek_client import chat_vision, deepseek_enabled
from services.processing_config import AI_LABEL_MAX_ITEMS, ENABLE_AI_LABELS


_LABEL_PROMPT = (
    "你是旅游混剪视频分析助手。根据截图判断画面内容，输出严格 JSON（不要 markdown）："
    '{"description":"6-12字中文画面描述，如三亚海滩航拍","tags":["关键词1","关键词2"]} '
    "要求：description 简洁可读；tags 3-6 个，含地点/场景/景别/主体（中文）。"
)

_TEMPLATE_SLOT_PROMPT = (
    "你是旅游混剪模板镜头分析师。这张截图来自「模板成片」的某一镜头槽位，"
    "用户将来会用自己的旅行素材替换它。"
    '输出严格 JSON（不要 markdown）：{"description":"6-12字中文画面描述",'
    '"tags":["关键词"],"shot_type_cn":"景别如航拍/全景/中景/特写/跟拍",'
    '"subject":"主体如人物/风景/美食/地标","replace_hint":"建议用户上传什么画面来替换"}'
)

_SHOT_TYPE_MAP = {
    "航拍": "aerial",
    "远景": "wide",
    "全景": "wide",
    "中景": "medium",
    "近景": "medium",
    "特写": "close",
    "跟拍": "tracking",
    "空镜": "wide",
}


def _parse_label_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}

    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if m:
            raw = m.group(1).strip()

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    desc_m = re.search(r'"description"\s*:\s*"([^"]+)"', raw)
    tags_m = re.search(r'"tags"\s*:\s*\[(.*?)\]', raw, re.S)
    tags: list[str] = []
    if tags_m:
        tags = re.findall(r'"([^"]+)"', tags_m.group(1))
    if desc_m:
        return {"description": desc_m.group(1).strip(), "tags": tags}
    if len(raw) <= 24 and not raw.startswith("{"):
        return {"description": raw.strip("。， "), "tags": []}
    return {}


def describe_frame_image(image_path: str, *, duration_sec: float | None = None) -> dict[str, str | list[str]]:
    """
    为单帧生成中文描述与标签。
    返回 {"description": "...", "tags": [...]}，失败时返回空 dict。
    """
    if not image_path or not os.path.isfile(image_path):
        return {}

    hint = ""
    if duration_sec is not None and duration_sec > 0:
        hint = f"该镜头时长约 {duration_sec:.1f} 秒。"

    try:
        reply = chat_vision(
            _LABEL_PROMPT + hint,
            [image_path],
            max_tokens=128,
            temperature=0.2,
        )
        parsed = _parse_label_json(reply)
        desc = str(parsed.get("description") or "").strip()
        tags_raw = parsed.get("tags") or []
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
        if not desc and tags:
            desc = " · ".join(tags[:3])
        if not desc:
            return {}
        return {"description": desc[:32], "tags": tags[:8]}
    except Exception as exc:
        print(f"DeepSeek 画面描述失败 [{image_path}]: {exc}")
        return {}


def describe_template_slot_image(
    image_path: str,
    *,
    duration_sec: float | None = None,
) -> dict[str, str | list[str]]:
    """为模板槽位截图生成描述、景别与替换建议。"""
    if not image_path or not os.path.isfile(image_path):
        return {}

    hint = ""
    if duration_sec is not None and duration_sec > 0:
        hint = f"该槽位时长约 {duration_sec:.1f} 秒。"

    try:
        reply = chat_vision(
            _TEMPLATE_SLOT_PROMPT + hint,
            [image_path],
            max_tokens=192,
            temperature=0.2,
        )
        parsed = _parse_label_json(reply)
        desc = str(parsed.get("description") or "").strip()
        tags_raw = parsed.get("tags") or []
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
        shot_type_cn = str(parsed.get("shot_type_cn") or "").strip()
        subject = str(parsed.get("subject") or "").strip()
        replace_hint = str(parsed.get("replace_hint") or "").strip()
        if not desc and tags:
            desc = " · ".join(tags[:3])
        if not desc:
            return {}
        result: dict[str, str | list[str]] = {
            "description": desc[:32],
            "tags": tags[:8],
        }
        if shot_type_cn:
            result["shot_type_cn"] = shot_type_cn[:12]
        if subject:
            result["subject"] = subject[:24]
        if replace_hint:
            result["replace_hint"] = replace_hint[:48]
        return result
    except Exception as exc:
        print(f"DeepSeek 模板槽位描述失败 [{image_path}]: {exc}")
        return {}


def apply_template_slot_vision(item: dict[str, Any]) -> dict[str, Any]:
    """为模板槽位写入 ai_description、ai_tags、ai_replace_hint 等。"""
    thumb = str(item.get("thumbnail") or "").strip()
    if not thumb or not os.path.isfile(thumb):
        return item

    duration = float(item.get("duration") or 0)
    labels = describe_template_slot_image(thumb, duration_sec=duration if duration > 0 else None)
    if not labels:
        return item

    desc = str(labels["description"])
    tags = list(labels.get("tags") or [])
    item["ai_description"] = desc
    item["ai_tags"] = tags

    shot_type_cn = str(labels.get("shot_type_cn") or "").strip()
    if shot_type_cn:
        item["shot_type_cn"] = shot_type_cn
        for key, val in _SHOT_TYPE_MAP.items():
            if key in shot_type_cn:
                item["shot_type"] = val
                break

    subject = str(labels.get("subject") or "").strip()
    if subject:
        item["ai_subject"] = subject

    replace_hint = str(labels.get("replace_hint") or "").strip()
    if replace_hint:
        item["ai_replace_hint"] = replace_hint

    merged = list(item.get("scene_tags") or item.get("tags") or [])
    for tag in tags:
        if tag and tag not in merged:
            merged.append(tag)
    if subject and subject not in merged:
        merged.append(subject)
    item["scene_tags"] = merged
    item["tags"] = merged
    return item


def apply_ai_labels(item: dict[str, Any]) -> dict[str, Any]:
    """为槽位/片段 dict 写入 ai_description、ai_tags，并合并进 scene_tags。"""
    thumb = str(item.get("thumbnail") or "").strip()
    if not thumb or not os.path.isfile(thumb):
        return item

    duration = float(item.get("duration") or 0)
    labels = describe_frame_image(thumb, duration_sec=duration if duration > 0 else None)
    if not labels:
        return item

    desc = labels["description"]
    tags = list(labels.get("tags") or [])

    item["ai_description"] = desc
    item["ai_tags"] = tags

    merged = list(item.get("scene_tags") or item.get("tags") or [])
    for tag in tags:
        if tag and tag not in merged:
            merged.append(tag)
    item["scene_tags"] = merged
    item["tags"] = merged
    return item


def enrich_items_with_ai_labels(
    items: list[dict[str, Any]],
    *,
    label: str = "条目",
    template_slots: bool = False,
    on_item_ready=None,
) -> list[dict[str, Any]]:
    """批量为槽位或素材片段补充 DeepSeek 中文标签。"""
    if not items or not ENABLE_AI_LABELS or not deepseek_enabled():
        return items

    cap = max(1, AI_LABEL_MAX_ITEMS)
    enriched: list[dict[str, Any]] = []
    done = 0

    for i, raw in enumerate(items):
        item = dict(raw)
        if done >= cap:
            enriched.append(item)
            continue
        if item.get("ai_description"):
            enriched.append(item)
            continue
        thumb = str(item.get("thumbnail") or "").strip()
        if not thumb or not os.path.isfile(thumb):
            enriched.append(item)
            continue
        if template_slots:
            apply_template_slot_vision(item)
        else:
            apply_ai_labels(item)
        if item.get("ai_description"):
            done += 1
            print(f"DeepSeek 标签 [{label} {i + 1}/{len(items)}]: {item['ai_description']}")
            if on_item_ready:
                on_item_ready(i, item)
        enriched.append(item)

    if done:
        print(f"DeepSeek 中文标签完成: {label} {done}/{min(len(items), cap)}")
    return enriched
