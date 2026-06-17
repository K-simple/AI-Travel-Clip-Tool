from typing import Any, Dict, List

PRESERVE_IF_EMPTY = (
    "slot_start",
    "slot_end",
    "slot_index",
    "template_thumbnail",
    "shot_type",
    "scene_tags",
    "ai_description",
    "ai_tags",
    "subtitle_segments",
    "clip_duration",
    "asset_audio_volume",
)


def slot_key(slot: Dict[str, Any], index: int) -> str:
    return str(slot.get("slot_id", slot.get("id", index)))


def merge_timeline(existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并 timeline 更新，保留模板元数据字段。"""
    existing_map = {slot_key(slot, i): dict(slot) for i, slot in enumerate(existing or [])}
    merged: List[Dict[str, Any]] = []

    for index, inc in enumerate(incoming or []):
        key = slot_key(inc, index)
        base = dict(existing_map.get(key, {}))
        result = {**base, **inc}

        for field in PRESERVE_IF_EMPTY:
            incoming_value = inc.get(field)
            if (incoming_value is None or incoming_value == "" or incoming_value == []) and base.get(field):
                result[field] = base[field]

        if not result.get("clip_duration"):
            result["clip_duration"] = result.get("slot_duration", result.get("duration", 0))

        merged.append(result)

    return merged
