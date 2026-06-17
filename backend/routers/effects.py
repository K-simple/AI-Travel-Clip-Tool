"""特效 / 转场 API。"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body

from services.effects_engine import compile_clip_filters
from services.transitions import get_all_transitions, resolve_transition

router = APIRouter()


@router.get("/transitions")
def list_transitions():
    presets = get_all_transitions()
    return {"count": len(presets), "presets": presets}


@router.post("/preview-filter")
def preview_filter(
    clip: Dict[str, Any] = Body(...),
    width: int = 1080,
    height: int = 1920,
):
    vf = compile_clip_filters(clip, width, height)
    return {"vf": vf, "transition": resolve_transition(clip.get("transition_out"))}
