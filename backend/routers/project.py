import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.database import Project, Template, get_db
from services.proxy_generator import normalize_proxy_paths
from utils.edl_timeline import slots_timeline_to_edl
from utils.timeline import merge_timeline

router = APIRouter()


class CreateProjectRequest(BaseModel):
    template_id: str
    timeline: Optional[Any] = None
    name: Optional[str] = None


class CreateProjectFromTemplateRequest(BaseModel):
    template_id: str
    name: Optional[str] = None


class SaveTimelineRequest(BaseModel):
    timeline: Any
    track_controls: Optional[Any] = None
    match_strategy: Optional[Any] = None
    overlay_tracks: Optional[Any] = None
    cover_thumbnail: Optional[str] = None


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    cover_thumbnail: Optional[str] = None


def normalize_slot(slot: Dict[str, Any], index: int, timeline_cursor: float = 0.0) -> Dict[str, Any]:
    """槽位在模板源视频中的起止（用于 clip_start / 缩略图 seek）。"""
    source_start = float(slot.get("start", slot.get("start_time", 0)))

    if "end" in slot:
        source_end = float(slot["end"])
    elif "end_time" in slot:
        source_end = float(slot["end_time"])
    else:
        source_end = source_start + float(slot.get("duration", slot.get("slot_duration", 2)))

    duration = max(0.1, source_end - source_start)
    timeline_start = float(timeline_cursor)
    timeline_end = timeline_start + duration

    slot_id = slot.get("slot_id") or slot.get("id") or f"slot_{index + 1:03d}"
    clip_start = slot.get("clip_start")
    if clip_start is None:
        clip_start = source_start

    return {
        "slot_id": slot_id,
        "slot_index": index,
        "slot_start": timeline_start,
        "slot_end": timeline_end,
        "slot_duration": duration,
        "template_thumbnail": slot.get("thumbnail", slot.get("thumb", slot.get("template_thumbnail", ""))),
        "shot_type": slot.get("shot_type", ""),
        "scene_tags": slot.get("tags", slot.get("scene_tags", [])),
        "ai_description": slot.get("ai_description", ""),
        "ai_tags": slot.get("ai_tags", []),
        "ai_replace_hint": slot.get("ai_replace_hint", ""),
        "ai_subject": slot.get("ai_subject", ""),
        "subtitle_text": slot.get("subtitle_text", ""),
        "subtitle_segments": slot.get("subtitle_segments", []),
        "asset_id": slot.get("asset_id"),
        "asset_file_path": slot.get("asset_file_path", ""),
        "asset_thumbnail": slot.get("asset_thumbnail", ""),
        "asset_filename": slot.get("asset_filename", ""),
        "clip_start": float(clip_start),
        "clip_duration": slot.get("clip_duration", duration),
        "use_original_audio": slot.get("use_original_audio", False),
        "asset_audio_volume": slot.get("asset_audio_volume", 0.3),
        "match_score": slot.get("match_score"),
        "match_reason": slot.get("match_reason", ""),
        "locked": slot.get("locked", False),
        "selected": slot.get("selected", False),
    }


def build_initial_timeline_from_template(template: Template):
    slots = template.slots or []
    timeline = []
    cursor = 0.0

    for index, slot in enumerate(slots):
        if isinstance(slot, dict):
            entry = normalize_slot(slot, index, timeline_cursor=cursor)
            timeline.append(entry)
            cursor = float(entry["slot_end"])

    return timeline


def merge_template_timeline(existing: list, template: Template) -> list:
    """用最新模板槽位刷新时间线，保留仍存在的槽位上的素材匹配。"""
    fresh = build_initial_timeline_from_template(template)
    if not fresh:
        return existing or []

    old_by_slot = {}
    for slot in existing or []:
        if isinstance(slot, dict):
            sid = slot.get("slot_id")
            if sid is not None:
                old_by_slot[str(sid)] = slot

    merged = []
    for slot in fresh:
        sid = str(slot.get("slot_id"))
        old = old_by_slot.get(sid)
        if not old:
            merged.append(slot)
            continue
        preserved = {
            "asset_id": old.get("asset_id"),
            "segment_id": old.get("segment_id"),
            "segment_file_path": old.get("segment_file_path"),
            "asset_file_path": old.get("asset_file_path"),
            "asset_filename": old.get("asset_filename"),
            "asset_thumbnail": old.get("asset_thumbnail"),
            "clip_start": old.get("clip_start"),
            "clip_duration": old.get("clip_duration"),
            "clip_end": old.get("clip_end"),
            "match_score": old.get("match_score"),
            "match_reason": old.get("match_reason"),
            "locked": old.get("locked", False),
        }
        merged.append({**slot, **{k: v for k, v in preserved.items() if v is not None}})
    return merged


def project_to_dict(project: Project):
    return {
        "project_id": project.id,
        "template_id": project.template_id,
        "name": getattr(project, "name", "") or "",
        "cover_thumbnail": getattr(project, "cover_thumbnail", "") or "",
        "timeline": project.timeline,
        "created_at": project.created_at,
        "updated_at": getattr(project, "updated_at", None),
    }


def _save_timeline(
    project: Project,
    incoming: list,
    db: Session,
    track_controls=None,
    match_strategy=None,
    overlay_tracks=None,
    cover_thumbnail=None,
):
    if not isinstance(incoming, list):
        raise HTTPException(status_code=400, detail="timeline 格式错误")

    existing = list(project.timeline or [])
    project.timeline = merge_timeline(existing, incoming)
    template = db.query(Template).filter(Template.id == project.template_id).first()
    beat_markers = getattr(template, "beat_markers", []) if template else []
    project.edl_json = slots_timeline_to_edl(
        project.timeline,
        beat_markers=beat_markers or [],
        overlay_tracks=overlay_tracks,
    )
    if track_controls is not None:
        project.track_controls_json = track_controls
    if match_strategy is not None:
        project.match_strategy_json = match_strategy
    if cover_thumbnail is not None:
        project.cover_thumbnail = cover_thumbnail
    if hasattr(project, "updated_at"):
        project.updated_at = time.time()
    db.commit()
    db.refresh(project)

    return {
        "success": True,
        "project_id": project.id,
        "timeline": project.timeline,
        "edl": project.edl_json,
    }


@router.post("/create")
def create_project(req: CreateProjectRequest, db: Session = Depends(get_db)):
    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    if req.timeline is None or req.timeline == []:
        timeline = build_initial_timeline_from_template(template)
    else:
        timeline = req.timeline

    if not timeline:
        raise HTTPException(status_code=400, detail="无法从模板生成时间线")

    project = Project(
        id=str(uuid.uuid4()),
        template_id=template.id,
        name=req.name or "",
        timeline=timeline,
        created_at=time.time(),
    )

    if hasattr(project, "updated_at"):
        project.updated_at = time.time()

    db.add(project)
    db.commit()
    db.refresh(project)

    return {
        "success": True,
        "project_id": project.id,
        "template_id": project.template_id,
        "name": project.name,
        "timeline": project.timeline,
    }


@router.post("/from-template")
def create_project_from_template(
    req: CreateProjectFromTemplateRequest,
    db: Session = Depends(get_db),
):
    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    timeline = build_initial_timeline_from_template(template)
    if not timeline:
        raise HTTPException(status_code=400, detail="模板未包含可用槽位")

    project = Project(
        id=str(uuid.uuid4()),
        template_id=template.id,
        name=req.name or template.filename,
        timeline=timeline,
        created_at=time.time(),
    )

    if hasattr(project, "updated_at"):
        project.updated_at = time.time()

    db.add(project)
    db.commit()
    db.refresh(project)

    return {
        "success": True,
        "project_id": project.id,
        "template_id": template.id,
        "name": project.name,
        "timeline": project.timeline,
    }


@router.post("/{project_id}/refresh-from-template")
def refresh_project_from_template(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    template = db.query(Template).filter(Template.id == project.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    project.timeline = merge_template_timeline(list(project.timeline or []), template)
    beat_markers = getattr(template, "beat_markers", []) or []
    project.edl_json = slots_timeline_to_edl(project.timeline, beat_markers=beat_markers)
    if hasattr(project, "updated_at"):
        project.updated_at = time.time()
    db.commit()
    db.refresh(project)

    return {
        "success": True,
        "project_id": project.id,
        "timeline": project.timeline,
        "slot_count": len(project.timeline or []),
        "template_processing_progress": getattr(template, "processing_progress", 100),
    }


@router.get("/list")
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()

    return {
        "success": True,
        "projects": [
            {
                "project_id": p.id,
                "template_id": p.template_id,
                "name": getattr(p, "name", "") or "",
                "cover_thumbnail": getattr(p, "cover_thumbnail", "") or "",
                "created_at": p.created_at,
                "updated_at": getattr(p, "updated_at", None),
            }
            for p in projects
        ],
    }


@router.get("/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    template = db.query(Template).filter(Template.id == project.template_id).first()

    response = {
        "success": True,
        "project_id": project.id,
        "template_id": project.template_id,
        "name": getattr(project, "name", "") or "",
        "cover_thumbnail": getattr(project, "cover_thumbnail", "") or "",
        "timeline": project.timeline,
        "edl": getattr(project, "edl_json", {}) or {},
        "track_controls": getattr(project, "track_controls_json", {}) or {},
        "match_strategy": getattr(project, "match_strategy_json", {}) or {},
        "project": project_to_dict(project),
    }

    if template:
        response["template_name"] = template.filename
        response["template"] = {
            "template_id": template.id,
            "filename": template.filename,
            "duration": template.duration,
            "slot_count": template.slot_count,
            "file_path": template.file_path,
            "audio_path": getattr(template, "audio_path", ""),
            "subtitle_srt_path": getattr(template, "subtitle_srt_path", ""),
            "subtitle_ass_path": getattr(template, "subtitle_ass_path", ""),
            "subtitle_style": getattr(template, "subtitle_style", ""),
            "processing_status": getattr(template, "processing_status", "ready"),
            "processing_progress": getattr(template, "processing_progress", 100),
            "beat_markers": getattr(template, "beat_markers", []) or [],
            "sfx_markers": getattr(template, "sfx_markers", []) or [],
            "proxy_paths": normalize_proxy_paths(getattr(template, "proxy_paths", None)),
        }

    return response


@router.put("/{project_id}/timeline")
def save_project_timeline(
    project_id: str,
    req: SaveTimelineRequest,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    return _save_timeline(
        project,
        req.timeline,
        db,
        track_controls=req.track_controls,
        match_strategy=req.match_strategy,
        overlay_tracks=req.overlay_tracks,
        cover_thumbnail=req.cover_thumbnail,
    )


@router.patch("/{project_id}")
def update_project(project_id: str, req: UpdateProjectRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    if req.name is not None:
        project.name = req.name.strip()
    if req.cover_thumbnail is not None:
        project.cover_thumbnail = req.cover_thumbnail
    if hasattr(project, "updated_at"):
        project.updated_at = time.time()
    db.commit()
    db.refresh(project)

    return {"success": True, "project": project_to_dict(project)}


@router.delete("/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    db.delete(project)
    db.commit()
    return {"success": True, "project_id": project_id}
