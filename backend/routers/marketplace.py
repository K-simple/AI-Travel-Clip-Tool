"""模板市场 — 上架 / 浏览 / 安装。"""

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from models.database import Template, get_db
from utils.edl_timeline import slots_timeline_to_edl

router = APIRouter()

_LISTINGS = os.path.join("storage", "marketplace", "listings.json")


def _load() -> List[Dict[str, Any]]:
    if not os.path.exists(_LISTINGS):
        return []
    with open(_LISTINGS, "r", encoding="utf-8") as f:
        return json.load(f).get("listings", [])


def _save(listings: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(_LISTINGS), exist_ok=True)
    with open(_LISTINGS, "w", encoding="utf-8") as f:
        json.dump({"listings": listings, "updated_at": time.time()}, f, ensure_ascii=False, indent=2)


@router.get("/list")
def list_templates(category: Optional[str] = None):
    listings = _load()
    if category:
        listings = [l for l in listings if l.get("category") == category]
    return {"listings": listings, "count": len(listings)}


@router.post("/publish")
def publish_template(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
):
    template_id = body.get("template_id")
    if not template_id:
        raise HTTPException(status_code=400, detail="需要 template_id")

    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    listings = _load()
    listing = {
        "id": str(uuid.uuid4()),
        "template_id": template.id,
        "title": body.get("title") or template.filename,
        "description": body.get("description", ""),
        "category": body.get("category", "travel"),
        "price": float(body.get("price", 0)),
        "thumbnail": body.get("thumbnail", ""),
        "slot_count": template.slot_count,
        "duration": template.duration,
        "published_at": time.time(),
        "author": body.get("author", "anonymous"),
    }
    listings.insert(0, listing)
    _save(listings)
    return {"success": True, "listing": listing}


@router.post("/install/{listing_id}")
def install_listing(listing_id: str, db: Session = Depends(get_db)):
    listing = next((l for l in _load() if l["id"] == listing_id), None)
    if not listing:
        raise HTTPException(status_code=404, detail="上架记录不存在")

    src = db.query(Template).filter(Template.id == listing["template_id"]).first()
    if not src:
        raise HTTPException(status_code=404, detail="源模板已删除")

    new_tpl = Template(
        id=str(uuid.uuid4()),
        filename=f"[市场] {listing['title']}",
        duration=src.duration,
        slot_count=src.slot_count,
        file_path=src.file_path,
        slots=src.slots,
        audio_path=src.audio_path,
        subtitle_srt_path=src.subtitle_srt_path,
        subtitle_ass_path=src.subtitle_ass_path,
        segments_json=src.segments_json,
        processing_status="ready",
        created_at=time.time(),
    )
    db.add(new_tpl)
    db.commit()
    return {"success": True, "template_id": new_tpl.id, "listing": listing}
