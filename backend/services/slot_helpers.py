"""画面槽创建与判定辅助。"""

from __future__ import annotations

from typing import Any


def is_base_slot(slot: dict[str, Any]) -> bool:
    if not isinstance(slot, dict):
        return False
    if slot.get("isBaseSlot"):
        return True
    src = str(slot.get("source") or "")
    reason = str(slot.get("cut_reason") or "")
    slot_id = str(slot.get("id") or slot.get("slot_id") or "")
    if src in ("base", "full_video"):
        return True
    if reason in ("full_video", "template_import_whole"):
        return True
    if slot_id.startswith("slot_base"):
        return True
    return False


def is_base_only_timeline(slots: list[dict[str, Any]] | None) -> bool:
    items = [s for s in (slots or []) if isinstance(s, dict)]
    if not items:
        return True
    return len(items) == 1 and is_base_slot(items[0])


def has_ai_caption_split_slots(slots: list[dict[str, Any]] | None) -> bool:
    return any(
        str(s.get("source") or "") == "ai_caption_split"
        for s in (slots or [])
        if isinstance(s, dict)
    )


def slots_will_be_overwritten_by_ai_split(slots: list[dict[str, Any]] | None) -> bool:
    """非 base 单槽时，AI 分割会覆盖现有画面槽。"""
    items = [s for s in (slots or []) if isinstance(s, dict)]
    if not items:
        return False
    return not is_base_only_timeline(items)


def is_ai_caption_split_slot(slot: dict[str, Any]) -> bool:
    if not isinstance(slot, dict):
        return False
    if str(slot.get("source") or "") == "ai_caption_split":
        return True
    return str(slot.get("cut_reason") or "") == "one_sentence_one_shot"


def is_visual_scene_slot(slot: dict[str, Any]) -> bool:
    if not isinstance(slot, dict):
        return False
    src = str(slot.get("source") or "")
    if src in ("ai_caption_split", "base", "full_video"):
        return False
    if is_base_slot(slot):
        return False
    reason = str(slot.get("cut_reason") or "")
    if reason in ("one_sentence_one_shot", "full_video", "template_import_whole"):
        return False
    return bool(src) or reason not in ("", "one_sentence_one_shot")


def has_mixed_slot_sources(slots: list[dict[str, Any]] | None) -> bool:
    """ai_caption_split 与 PySceneDetect / 旧 visual 槽不可混用。"""
    items = [s for s in (slots or []) if isinstance(s, dict)]
    if not items:
        return False
    has_ai = any(is_ai_caption_split_slot(s) for s in items)
    has_visual = any(is_visual_scene_slot(s) for s in items)
    return has_ai and has_visual


def count_material_clips(timeline: list[dict[str, Any]] | None) -> int:
    return sum(
        1
        for s in (timeline or [])
        if isinstance(s, dict) and (s.get("asset_id") or s.get("segment_file_path"))
    )


def build_one_caption_one_shot_debug(
    *,
    caption_clips: list[dict[str, Any]] | None = None,
    slots: list[dict[str, Any]] | None = None,
    timeline: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from services.processing_config import (
        ENABLE_SECONDARY_CUTS,
        is_one_caption_one_shot,
        is_one_slot_one_material,
    )

    clip_list = [c for c in (caption_clips or []) if isinstance(c, dict)]
    slot_list = [s for s in (slots or []) if isinstance(s, dict)]
    timeline_list = timeline if timeline is not None else slot_list

    caption_count = len(clip_list)
    slot_count = len(slot_list)
    material_count = count_material_clips(timeline_list)
    using_old_visual = any(is_visual_scene_slot(s) for s in slot_list) and not all(
        is_ai_caption_split_slot(s) for s in slot_list
    )
    mixed = has_mixed_slot_sources(slot_list)
    all_ai = slot_count > 0 and all(is_ai_caption_split_slot(s) for s in slot_list)

    return {
        "captionClipCount": caption_count,
        "slotCount": slot_count,
        "materialClipCount": material_count,
        "timelineRenderedVideoBlockCount": slot_count,
        "slotsEqualCaptions": slot_count == caption_count if caption_count else slot_count <= 1,
        "materialsEqualSlots": material_count <= slot_count,
        "timelineBlocksEqualSlots": slot_count == len(timeline_list),
        "usingOldVisualSlots": using_old_visual and not all_ai,
        "usingFixedIntervalMaterialCuts": False,
        "secondaryCutsEnabled": bool(ENABLE_SECONDARY_CUTS),
        "renderingMaterialSegmentsAsMainTrack": False,
        "mixedSlotSources": mixed,
        "oneCaptionOneShotEnabled": is_one_caption_one_shot(),
        "oneSlotOneMaterialEnabled": is_one_slot_one_material(),
        "allAiCaptionSplitSlots": all_ai,
    }
