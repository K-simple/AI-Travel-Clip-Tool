import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models.database import Template, get_db
from services.slot_subtitle import recognize_slot_from_template
from services.subtitle_gen import generate_srt, transcribe
from utils.security import validate_upload_file

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=1)


def _slot_time_match(slot: dict, slot_start: float, slot_end: float, eps: float = 0.05) -> bool:
    start = float(slot.get("start", slot.get("slot_start", -1)))
    end = float(slot.get("end", slot.get("slot_end", -1)))
    return abs(start - slot_start) <= eps and abs(end - slot_end) <= eps


def _find_cached_slot_subtitle(template: Template, slot_start: float, slot_end: float) -> Optional[dict]:
    slots = template.slots or []
    for slot in slots:
        if not _slot_time_match(slot, slot_start, slot_end):
            continue
        text = (slot.get("subtitle_text") or "").strip()
        segments = slot.get("subtitle_segments") or []
        if text or segments:
            return {"subtitle_text": text, "subtitle_segments": segments}
    return None


def _persist_slot_subtitle(
    template: Template,
    slot_start: float,
    slot_end: float,
    subtitle_text: str,
    segments: list,
    db: Session,
) -> None:
    slots = list(template.slots or [])
    if not slots:
        return
    changed = False
    for i, slot in enumerate(slots):
        if _slot_time_match(slot, slot_start, slot_end):
            slots[i] = {
                **slot,
                "subtitle_text": subtitle_text,
                "subtitle_segments": segments,
            }
            changed = True
            break
    if changed:
        template.slots = slots
        db.commit()


class RecognizeSlotRequest(BaseModel):
    template_id: str
    slot_start: float = Field(ge=0)
    slot_end: float = Field(gt=0)
    slot_id: Optional[str] = None
    force: bool = False


class BatchRecognizeSlotRequest(BaseModel):
    template_id: str
    slots: list


@router.post("/recognize")
async def recognize_subtitle(file: UploadFile = File(...)):
    import os
    import uuid

    content = await file.read()
    ext = validate_upload_file(file.filename, len(content))

    safe_filename = f"{uuid.uuid4()}{ext}"
    temp_path = f"storage/temp/{safe_filename}"
    srt_path = temp_path.replace(ext, ".srt")

    try:
        with open(temp_path, "wb") as f:
            f.write(content)

        loop = asyncio.get_event_loop()
        segments = await loop.run_in_executor(_executor, transcribe, temp_path)
        generate_srt(segments, srt_path)

        return {
            "success": True,
            "segments": segments,
            "srt_path": srt_path,
            "total_count": len(segments),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail="语音识别失败") from exc
    finally:
        import os

        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@router.post("/recognize-slot")
async def recognize_slot_subtitle(req: RecognizeSlotRequest, db: Session = Depends(get_db)):
    """根据模板人声，识别指定槽位时间范围内的字幕。"""
    if req.slot_end <= req.slot_start:
        raise HTTPException(status_code=400, detail="槽位时间范围无效")

    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    status = getattr(template, "processing_status", "ready")
    if status == "processing":
        raise HTTPException(status_code=400, detail="模板仍在分析中，请稍后再试")

    cached = _find_cached_slot_subtitle(template, req.slot_start, req.slot_end)
    if cached and not req.force:
        return {
            "success": True,
            "slot_id": req.slot_id,
            "subtitle_text": cached["subtitle_text"],
            "subtitle_segments": cached["subtitle_segments"],
            "segment_count": len(cached["subtitle_segments"]),
            "cached": True,
        }

    try:
        loop = asyncio.get_event_loop()
        segments = await loop.run_in_executor(
            _executor,
            recognize_slot_from_template,
            template,
            req.slot_start,
            req.slot_end,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="人声识别失败") from exc

    subtitle_text = " ".join(seg["text"] for seg in segments).strip()
    _persist_slot_subtitle(template, req.slot_start, req.slot_end, subtitle_text, segments, db)

    return {
        "success": True,
        "slot_id": req.slot_id,
        "subtitle_text": subtitle_text,
        "subtitle_segments": segments,
        "segment_count": len(segments),
        "cached": False,
    }


@router.post("/recognize-slot-batch")
async def recognize_slot_subtitle_batch(req: BatchRecognizeSlotRequest, db: Session = Depends(get_db)):
    """批量识别多个槽位的字幕。"""
    if not req.slots:
        raise HTTPException(status_code=400, detail="slots 不能为空")

    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    status = getattr(template, "processing_status", "ready")
    if status == "processing":
        raise HTTPException(status_code=400, detail="模板仍在分析中，请稍后再试")

    results = []
    loop = asyncio.get_event_loop()

    for item in req.slots:
        slot_id = item.get("slot_id")
        slot_start = float(item.get("slot_start", 0))
        slot_end = float(item.get("slot_end", 0))
        if slot_end <= slot_start:
            results.append({
                "slot_id": slot_id,
                "success": False,
                "error": "时间范围无效",
            })
            continue
        try:
            segments = await loop.run_in_executor(
                _executor,
                recognize_slot_from_template,
                template,
                slot_start,
                slot_end,
            )
            subtitle_text = " ".join(seg["text"] for seg in segments).strip()
            results.append({
                "slot_id": slot_id,
                "success": True,
                "subtitle_text": subtitle_text,
                "subtitle_segments": segments,
                "segment_count": len(segments),
            })
        except Exception as exc:
            results.append({
                "slot_id": slot_id,
                "success": False,
                "error": str(exc),
            })

    ok_count = sum(1 for r in results if r.get("success"))
    return {
        "success": True,
        "results": results,
        "recognized_count": ok_count,
        "total_count": len(results),
    }
