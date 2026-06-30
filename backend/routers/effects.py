"""特效 / 转场 / 特效库 API。"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from services.effects_catalog import (
    apply_preset_to_slot,
    build_ai_effect_understanding,
    enrich_slot_catalog_understanding,
    find_preset,
    list_catalog_categories,
    load_effects_catalog,
)
from services.effects_engine import compile_clip_filters
from services.transitions import get_all_transitions, resolve_transition

router = APIRouter()


class ApplyEffectPresetRequest(BaseModel):
    slot: Dict[str, Any]
    preset_id: str = Field(min_length=1)


class ApplyEffectBatchRequest(BaseModel):
    slots: List[Dict[str, Any]]
    preset_id: str = Field(min_length=1)
    slot_indices: Optional[List[int]] = None


class UnderstandSlotEffectsRequest(BaseModel):
    slot: Dict[str, Any]
    ai_preset_ids: Optional[List[str]] = None
    apply_suggested_presets: bool = False


@router.get("/transitions")
def list_transitions():
    presets = get_all_transitions()
    return {"count": len(presets), "presets": presets}


@router.get("/library")
def list_effects_library():
    catalog = load_effects_catalog()
    categories = list_catalog_categories()
    preset_count = sum(len(c.get("presets") or []) for c in categories)
    return {
        "version": catalog.get("version", 1),
        "category_count": len(categories),
        "preset_count": preset_count,
        "categories": categories,
    }


@router.get("/library/{preset_id}")
def get_effect_preset(preset_id: str):
    preset = find_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="特效预设不存在")
    return preset


@router.post("/apply-preset")
def apply_effect_preset(body: ApplyEffectPresetRequest):
    try:
        updated = apply_preset_to_slot(body.slot, body.preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "slot": updated, "preset_id": body.preset_id}


@router.post("/apply-preset-batch")
def apply_effect_preset_batch(body: ApplyEffectBatchRequest):
    if not body.slots:
        raise HTTPException(status_code=400, detail="slots 不能为空")
    try:
        indices = body.slot_indices if body.slot_indices is not None else list(range(len(body.slots)))
        updated_slots = list(body.slots)
        for idx in indices:
            if idx < 0 or idx >= len(updated_slots):
                continue
            if isinstance(updated_slots[idx], dict):
                updated_slots[idx] = apply_preset_to_slot(updated_slots[idx], body.preset_id)
        return {
            "success": True,
            "slots": updated_slots,
            "preset_id": body.preset_id,
            "applied_count": len(indices),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/understand-slot")
def understand_slot_effects(body: UnderstandSlotEffectsRequest):
    """将槽位 AI 识别结果映射到特效库 preset，生成 ai_effect_understanding。"""
    updated = enrich_slot_catalog_understanding(
        body.slot,
        ai_preset_ids=body.ai_preset_ids,
        apply_suggested_presets=body.apply_suggested_presets,
    )
    understanding = updated.get("ai_effect_understanding") or build_ai_effect_understanding(updated)
    return {
        "success": True,
        "slot": updated,
        "understanding": understanding,
    }


@router.post("/preview-filter")
def preview_filter(
    clip: Dict[str, Any] = Body(...),
    width: int = 1080,
    height: int = 1920,
):
    vf = compile_clip_filters(clip, width, height)
    return {"vf": vf, "transition": resolve_transition(clip.get("transition_out"))}
