"""`.ctpl` 模板库导入导出（Phase C）。"""

import json
import os
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.database import Template, get_db
from utils.edl_timeline import slots_timeline_to_edl

router = APIRouter()

CTPL_VERSION = "1.0"


class CtplSaveRequest(BaseModel):
    template_id: str
    name: Optional[str] = None


@router.get("/list")
def list_my_templates(db: Session = Depends(get_db)):
    templates = db.query(Template).order_by(Template.created_at.desc()).all()
    return {
        "success": True,
        "templates": [
            {
                "template_id": t.id,
                "filename": t.filename,
                "duration": t.duration,
                "slot_count": t.slot_count,
                "processing_status": getattr(t, "processing_status", "ready"),
            }
            for t in templates
        ],
    }


@router.get("/{template_id}/export-ctpl")
def export_ctpl(template_id: str, db: Session = Depends(get_db)):
    t = db.query(Template).filter(Template.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")

    slots = t.slots or []
    edl = slots_timeline_to_edl(
        [
            {
                "slot_id": s.get("slot_id"),
                "slot_duration": s.get("duration"),
                "slot_start": s.get("start"),
                "slot_end": s.get("end"),
                "subtitle_text": s.get("subtitle_text", ""),
                "scene_tags": s.get("scene_tags") or s.get("tags") or [],
                "shot_type": s.get("shot_type", ""),
            }
            for s in slots
        ],
        beat_markers=getattr(t, "beat_markers", []) or [],
    )

    ctpl: Dict[str, Any] = {
        "version": CTPL_VERSION,
        "meta": {
            "name": t.filename,
            "ratio": "9:16",
            "duration": t.duration,
            "tags": [],
        },
        "slots": [
            {
                "id": f"s{s.get('slot_id')}",
                "start": s.get("start", 0),
                "duration": s.get("duration", 0),
                "spec": {
                    "scene": s.get("scene_tags") or s.get("tags") or [],
                    "shot": s.get("shot_type", "wide"),
                    "motion": "static",
                    "mood": s.get("mood", ""),
                },
                "thumbnail": s.get("thumbnail", ""),
                "subtitle_text": s.get("subtitle_text", ""),
            }
            for s in slots
        ],
        "audio": {
            "bgm": {
                "path": getattr(t, "audio_path", ""),
                "beat_markers": getattr(t, "beat_markers", []) or [],
                "ducking": True,
            }
        },
        "style": {
            "lut": "",
            "intensity": 0.6,
            "transition_preset": "smooth_dip",
        },
        "edl": edl,
    }

    out_dir = os.path.join("storage", "templates", template_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{template_id}.ctpl.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ctpl, f, ensure_ascii=False, indent=2)

    return {"success": True, "ctpl_path": out_path.replace("\\", "/"), "ctpl": ctpl}


@router.post("/import-ctpl")
def import_ctpl(payload: Dict[str, Any], db: Session = Depends(get_db)):
    version = payload.get("version", "1.0")
    if version != CTPL_VERSION:
        raise HTTPException(status_code=400, detail=f"不支持的 ctpl 版本: {version}")

    meta = payload.get("meta") or {}
    slots_raw = payload.get("slots") or []
    template_id = str(uuid.uuid4())

    slots = []
    for i, s in enumerate(slots_raw):
        spec = s.get("spec") or {}
        slots.append({
            "slot_id": i + 1,
            "start": float(s.get("start", 0)),
            "end": float(s.get("start", 0)) + float(s.get("duration", 0)),
            "duration": float(s.get("duration", 0)),
            "scene_tags": spec.get("scene", []),
            "tags": spec.get("scene", []),
            "shot_type": spec.get("shot", "wide"),
            "mood": spec.get("mood", ""),
            "thumbnail": s.get("thumbnail", ""),
            "subtitle_text": s.get("subtitle_text", ""),
        })

    beat_markers = (payload.get("audio") or {}).get("bgm", {}).get("beat_markers", [])

    template = Template(
        id=template_id,
        filename=meta.get("name", "imported.ctpl"),
        duration=float(meta.get("duration", 0)),
        slot_count=len(slots),
        file_path="",
        slots=slots,
        beat_markers=beat_markers,
        processing_status="ready",
        processing_progress=100,
        created_at=time.time(),
    )
    db.add(template)
    db.commit()

    return {"success": True, "template_id": template_id, "slot_count": len(slots)}
