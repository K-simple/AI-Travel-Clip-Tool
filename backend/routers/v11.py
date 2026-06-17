from fastapi import APIRouter

from services.effects_stub import CAPABILITIES

router = APIRouter()


@router.get("/status")
def v11_status():
    return {"version": "1.1-stub", "capabilities": CAPABILITIES}
