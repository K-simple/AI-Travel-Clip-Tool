"""基于模板画面理解的智能素材匹配（非随机）。"""

from __future__ import annotations

import re
from typing import Any

_CN_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,}")


def _slot_key(slot: dict[str, Any]) -> str:
    sid = slot.get("slot_id") or slot.get("id")
    return str(sid) if sid is not None else ""


def build_match_text_profile(item: dict[str, Any]) -> str:
    """汇总槽位/片段的可匹配语义文本。"""
    parts: list[str] = []
    for key in (
        "ai_description",
        "subtitle_visual_context",
        "ai_replace_hint",
        "ai_subject",
        "subtitle_text",
        "shot_type_cn",
        "shot_type",
    ):
        val = str(item.get(key) or "").strip()
        if val:
            parts.append(val)

    tags = list(item.get("scene_tags") or item.get("tags") or [])
    for tag in item.get("ai_tags") or []:
        if tag and tag not in tags:
            tags.append(tag)
    if tags:
        parts.append(" ".join(str(t) for t in tags[:12]))

    return " ".join(parts)


def _cn_tokens(text: str) -> set[str]:
    if not text:
        return set()
    return set(_CN_TOKEN.findall(text))


def calculate_semantic_score(slot: dict[str, Any], seg: dict[str, Any]) -> float:
    """模板画面理解 vs 素材片段描述的语义相似度。"""
    slot_text = build_match_text_profile(slot)
    seg_text = build_match_text_profile(seg)
    slot_tokens = _cn_tokens(slot_text)
    seg_tokens = _cn_tokens(seg_text)
    if not slot_tokens or not seg_tokens:
        return 0.0

    overlap = len(slot_tokens & seg_tokens)
    union = len(slot_tokens | seg_tokens)
    jaccard = overlap / union if union else 0.0

    hint = str(slot.get("ai_replace_hint") or "").strip()
    hint_tokens = _cn_tokens(hint)
    hint_hit = len(hint_tokens & seg_tokens) / max(1, len(hint_tokens)) if hint_tokens else 0.0

    subject = str(slot.get("ai_subject") or "").strip()
    subject_hit = 1.0 if subject and subject in seg_text else 0.0

    subtitle = str(slot.get("subtitle_text") or "").strip()
    sub_tokens = _cn_tokens(subtitle)
    sub_hit = len(sub_tokens & seg_tokens) / max(1, len(sub_tokens)) if sub_tokens else 0.0

    desc_slot = str(slot.get("ai_description") or slot.get("subtitle_visual_context") or "")
    desc_seg = str(seg.get("ai_description") or "")
    desc_hit = 0.0
    if desc_slot and desc_seg:
        ds = _cn_tokens(desc_slot)
        de = _cn_tokens(desc_seg)
        if ds and de:
            desc_hit = len(ds & de) / max(1, len(ds))

    score = jaccard * 0.45 + hint_hit * 0.25 + desc_hit * 0.15 + subject_hit * 0.1 + sub_hit * 0.05
    return min(1.0, max(0.0, score))


def merge_template_understanding_into_timeline(
    timeline: list[dict[str, Any]],
    template_slots: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """将模板槽位 AI 画面理解合并进项目时间线（匹配前必做）。"""
    if not timeline or not template_slots:
        return timeline

    by_id: dict[str, dict[str, Any]] = {}
    for slot in template_slots:
        if isinstance(slot, dict):
            key = _slot_key(slot)
            if key:
                by_id[key] = slot

    merged: list[dict[str, Any]] = []
    for index, entry in enumerate(timeline):
        if not isinstance(entry, dict):
            merged.append(entry)
            continue
        item = dict(entry)
        tpl = by_id.get(_slot_key(item))
        if not tpl:
            merged.append(item)
            continue

        for field in (
            "ai_description",
            "ai_tags",
            "ai_subject",
            "ai_replace_hint",
            "subtitle_visual_context",
            "subtitle_scene_match",
            "subtitle_scene_match_reason",
            "subtitle_text",
            "subtitle_segments",
            "shot_type",
            "shot_type_cn",
            "template_thumbnail",
        ):
            if not item.get(field) and tpl.get(field):
                item[field] = tpl[field]

        tags = list(item.get("scene_tags") or item.get("tags") or [])
        for tag in tpl.get("scene_tags") or tpl.get("tags") or []:
            if tag and tag not in tags:
                tags.append(tag)
        for tag in tpl.get("ai_tags") or []:
            if tag and tag not in tags:
                tags.append(tag)
        if tags:
            item["scene_tags"] = tags
            item["tags"] = tags

        if not item.get("template_thumbnail") and tpl.get("thumbnail"):
            item["template_thumbnail"] = tpl.get("thumbnail")

        merged.append(item)

    return merged


def enrich_timeline_for_matching(
    timeline: list[dict[str, Any]],
    template_slots: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """匹配前：确保时间线槽位携带模板画面理解字段。"""
    return merge_template_understanding_into_timeline(timeline, template_slots)


def slots_missing_understanding(timeline: list[dict[str, Any]], ratio: float = 0.5) -> bool:
    """超过一半槽位缺少画面描述时视为未理解模板。"""
    if not timeline:
        return True
    missing = 0
    for slot in timeline:
        if not isinstance(slot, dict):
            continue
        if not str(slot.get("ai_description") or slot.get("subtitle_visual_context") or "").strip():
            missing += 1
    return missing / max(1, len(timeline)) >= ratio
