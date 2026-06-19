import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional, Union

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models.database import Template, get_db
from services.slot_subtitle import (
    ensure_template_segments_json,
    extract_subtitles_for_slot_range,
    recognize_slot_from_source,
)
from services.subtitle_gen import generate_srt, transcribe
from services.subtitle_ocr import recognize_slot_visual
from services.subtitle_quality import (
    is_subtitle_quality_acceptable,
    subtitle_text_from_segments,
)
from services.vocal_separator import ensure_vocal_and_bgm_tracks, resolve_vocal_source_path
from utils.security import validate_upload_file

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=1)

SubtitleMode = Literal["visual", "audio", "auto"]


def _slot_source_range(slot: dict) -> tuple[float, float]:
    """槽位在模板源视频/人声上的起止时间。"""
    if slot.get("clip_start") is not None:
        start = float(slot["clip_start"])
        if slot.get("clip_end") is not None:
            end = float(slot["clip_end"])
        elif slot.get("clip_duration") is not None:
            end = start + float(slot["clip_duration"])
        else:
            end = start + float(slot.get("duration") or slot.get("slot_duration") or 0.1)
        return start, max(start + 0.1, end)

    start = float(slot.get("start", slot.get("start_time", slot.get("slot_start", 0))))
    if "end" in slot:
        end = float(slot["end"])
    elif "end_time" in slot:
        end = float(slot["end_time"])
    else:
        end = start + float(slot.get("duration") or slot.get("slot_duration") or 0.1)
    return start, max(start + 0.1, end)


def _slot_time_match(slot: dict, slot_start: float, slot_end: float, eps: float = 0.05) -> bool:
    start, end = _slot_source_range(slot)
    return abs(start - slot_start) <= eps and abs(end - slot_end) <= eps


def _find_slot_index(
    slots: list,
    slot_start: float,
    slot_end: float,
    slot_id: Optional[Union[str, int]] = None,
) -> Optional[int]:
    if slot_id is not None:
        for i, slot in enumerate(slots):
            sid = slot.get("slot_id") or slot.get("id")
            if sid is not None and str(sid) == str(slot_id):
                return i
    for i, slot in enumerate(slots):
        if _slot_time_match(slot, slot_start, slot_end):
            return i
    return None


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
    slot_id: Optional[Union[str, int]] = None,
) -> None:
    slots = list(template.slots or [])
    if not slots:
        return
    idx = _find_slot_index(slots, slot_start, slot_end, slot_id)
    if idx is None:
        return
    slots[idx] = {
        **slots[idx],
        "subtitle_text": subtitle_text,
        "subtitle_segments": segments,
    }
    template.slots = slots
    flag_modified(template, "slots")
    db.commit()
    db.refresh(template)


class RecognizeSlotRequest(BaseModel):
    template_id: str
    slot_start: float = Field(ge=0)
    slot_end: float = Field(gt=0)
    slot_id: Optional[Union[str, int]] = None
    force: bool = False
    mode: SubtitleMode = "auto"


class BatchRecognizeSlotRequest(BaseModel):
    template_id: str
    slots: list
    force: bool = False
    mode: SubtitleMode = "auto"


def _recognize_audio_segments(
    video_path: str,
    slot_start: float,
    slot_end: float,
    segments_json: list | None,
) -> list:
    if segments_json:
        sliced = extract_subtitles_for_slot_range(segments_json, slot_start, slot_end)
        if sliced:
            return sliced

    source_path = resolve_vocal_source_path(video_path, force=False) or video_path
    if not source_path:
        return []
    return recognize_slot_from_source(source_path, slot_start, slot_end, segments_json=None)


def _recognize_slot_segments_sync(
    template: Template,
    slot_start: float,
    slot_end: float,
    mode: SubtitleMode = "auto",
    segments_json: list | None = None,
    peer_texts: list[str] | None = None,
) -> tuple[list, str]:
    video_path = template.file_path or ""
    slot_duration = float(slot_end) - float(slot_start)
    peers = peer_texts or []

    if mode == "visual":
        if not video_path:
            return [], "none"
        segments = recognize_slot_visual(video_path, slot_start, slot_end)
        return segments, "visual" if segments else "none"

    if mode == "audio":
        segments = _recognize_audio_segments(video_path, slot_start, slot_end, segments_json)
        return segments, "whisper" if segments else "none"

    # auto：优先人声，质量不佳则画面 OCR
    audio_segments = _recognize_audio_segments(video_path, slot_start, slot_end, segments_json)
    audio_text = subtitle_text_from_segments(audio_segments)
    dup = sum(1 for p in peers if (p or "").strip() == audio_text and len(audio_text) >= 8)
    ok, reason = is_subtitle_quality_acceptable(
        audio_text,
        slot_duration,
        duplicate_peers=dup,
    )
    if ok and audio_segments:
        return audio_segments, "whisper"

    if video_path:
        try:
            visual_segments = recognize_slot_visual(video_path, slot_start, slot_end)
            visual_text = subtitle_text_from_segments(visual_segments)
            if visual_segments and visual_text:
                print(
                    f"槽位 {slot_start:.2f}-{slot_end:.2f}s 人声不理想({reason})，已回退画面 OCR"
                )
                return visual_segments, "visual_fallback"
        except Exception as exc:
            print(f"画面 OCR 回退失败 @ {slot_start}-{slot_end}: {exc}")

    if audio_segments:
        return audio_segments, "whisper_low_quality"
    return [], "none"


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
    """识别槽位字幕：auto 时先人声转写，不理想则回退画面 OCR。"""
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

    segments_json = None
    if req.mode in ("audio", "auto"):
        try:
            ensure_vocal_and_bgm_tracks(template.file_path or "", force=req.force)
        except Exception as exc:
            print(f"人声分离失败: {exc}")
        segments_json = ensure_template_segments_json(template, db, force=req.force and req.mode == "audio")

    try:
        loop = asyncio.get_event_loop()
        segments, source = await loop.run_in_executor(
            _executor,
            _recognize_slot_segments_sync,
            template,
            req.slot_start,
            req.slot_end,
            req.mode,
            segments_json,
            [],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="字幕识别失败") from exc

    subtitle_text = " ".join(seg["text"] for seg in segments).strip()
    _persist_slot_subtitle(
        template,
        req.slot_start,
        req.slot_end,
        subtitle_text,
        segments,
        db,
        slot_id=req.slot_id,
    )

    return {
        "success": True,
        "slot_id": req.slot_id,
        "subtitle_text": subtitle_text,
        "subtitle_segments": segments,
        "segment_count": len(segments),
        "cached": False,
        "source": source,
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

    if req.mode in ("audio", "auto"):
        try:
            ensure_vocal_and_bgm_tracks(template.file_path or "", force=req.force)
        except Exception as exc:
            print(f"批量识别前人声分离失败: {exc}")
        source_path = resolve_vocal_source_path(template.file_path or "", force=False)
        if not source_path and req.mode == "audio":
            raise HTTPException(status_code=400, detail="模板缺少音频源")

    from utils.security import resolve_storage_path

    resolved = resolve_storage_path(template.file_path or "")
    if req.mode in ("visual", "auto") and (not resolved or not os.path.isfile(resolved)):
        if req.mode == "visual":
            raise HTTPException(status_code=400, detail="模板视频不存在")
    elif req.mode == "audio" and not source_path:
        raise HTTPException(status_code=400, detail="模板缺少音频源")

    segments_json = None
    if req.mode in ("audio", "auto"):
        segments_json = ensure_template_segments_json(template, db, force=req.force and req.mode == "audio")

    results = []
    peer_texts: list[str] = []
    loop = asyncio.get_event_loop()

    for item in req.slots:
        if not isinstance(item, dict):
            results.append({"slot_id": None, "success": False, "error": "槽位参数无效"})
            continue

        slot_id = item.get("slot_id")
        try:
            slot_start = float(item.get("slot_start", 0))
            slot_end = float(item.get("slot_end", 0))
        except (TypeError, ValueError):
            results.append({
                "slot_id": slot_id,
                "success": False,
                "error": "时间范围无效",
            })
            continue

        if slot_end <= slot_start:
            results.append({
                "slot_id": slot_id,
                "success": False,
                "error": "时间范围无效",
            })
            continue
        try:
            segments, source = await loop.run_in_executor(
                _executor,
                _recognize_slot_segments_sync,
                template,
                slot_start,
                slot_end,
                req.mode,
                segments_json,
                list(peer_texts),
            )
            subtitle_text = " ".join(seg["text"] for seg in segments).strip()
            if subtitle_text:
                peer_texts.append(subtitle_text)
            _persist_slot_subtitle(
                template,
                slot_start,
                slot_end,
                subtitle_text,
                segments,
                db,
                slot_id=slot_id,
            )
            results.append({
                "slot_id": slot_id,
                "success": True,
                "subtitle_text": subtitle_text,
                "subtitle_segments": segments,
                "segment_count": len(segments),
                "source": source,
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
