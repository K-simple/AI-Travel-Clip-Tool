import os
import uuid
from functools import partial
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.database import Project, Template, get_db
from services.capcut_draft_exporter import export_timeline_to_capcut_draft
from services.capcut_mate_client import CAPCUT_MATE_BASE_URL, capcut_mate_enabled, ping as capcut_ping
from services.edl_exporter import export_from_edl
from services.proxy_generator import pick_video_codec
from services.task_queue import create_task, get_task, run_task
from services.video_exporter import export_video
from utils.edl_timeline import enrich_edl_asset_paths
from utils.export_controls import resolve_export_mix
from utils.security import ensure_storage_subpath

router = APIRouter()


class CapCutDraftRequest(BaseModel):
    project_id: Optional[str] = None
    template_id: Optional[str] = None
    timeline: Optional[list] = None
    resolution: str = "1080x1920"
    media_base_url: Optional[str] = None
    add_subtitles: bool = True
    use_asset_audio: bool = False
    asset_audio_volume: float = 0.3
    template_audio_volume: float = 1.0
    template_music_enabled: bool = True
    track_controls: Optional[Dict[str, Any]] = None
    include_template_slots: bool = True
    capcut_export_mode: str = "filled"  # filled | replaceable_template


class AsyncRenderRequest(BaseModel):
    project_id: Optional[str] = None
    template_id: Optional[str] = None
    timeline: Optional[list] = None
    resolution: str = "1080x1920"
    add_subtitles: bool = True
    use_slot_subtitles: bool = True
    use_asset_audio: bool = False
    asset_audio_volume: float = 0.3
    template_audio_volume: float = 1.0
    template_music_enabled: bool = True
    track_controls: Optional[Dict[str, Any]] = None
    use_edl: bool = True
    use_nvenc: bool = True
    codec: Optional[str] = None


def _resolve_export_context(
    db: Session,
    project_id: Optional[str],
    template_id: Optional[str],
    timeline: Optional[list],
):
    project = None
    if timeline is not None:
        if not template_id:
            raise HTTPException(status_code=400, detail="缺少 template_id")
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="模板不存在")
        return template, timeline, project

    if not project_id:
        raise HTTPException(status_code=400, detail="缺少 project_id 或 timeline")

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    template = db.query(Template).filter(Template.id == project.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    return template, project.timeline, project


def _run_export_job(
    *,
    template,
    project_timeline: list,
    project: Optional[Project],
    output_path: str,
    resolution: str,
    add_subtitles: bool,
    use_slot_subtitles: bool,
    use_asset_audio: bool,
    asset_audio_volume: float,
    template_audio_volume: float,
    template_music_enabled: bool = True,
    track_controls_override: Optional[Dict[str, Any]] = None,
    use_edl: bool,
    use_nvenc: bool,
    codec: Optional[str],
):
    template_video_path = ensure_storage_subpath(template.file_path)
    video_codec = codec or pick_video_codec(prefer_nvenc=use_nvenc, resolution=resolution)

    edl = None
    track_controls = track_controls_override
    if project and track_controls is None:
        track_controls = getattr(project, "track_controls_json", None) or {}

    mix = resolve_export_mix(
        track_controls,
        template_music_enabled=template_music_enabled,
        use_asset_audio=use_asset_audio,
        asset_audio_volume=asset_audio_volume,
        template_audio_volume=template_audio_volume,
        add_subtitles=add_subtitles,
    )
    add_subtitles = mix["add_subtitles"]
    use_asset_audio = mix["use_asset_audio"]
    template_audio_volume = mix["template_audio_volume"]
    asset_audio_volume = mix["asset_audio_volume"]

    if project and use_edl:
        edl = getattr(project, "edl_json", None) or {}
        if edl and project_timeline:
            edl = enrich_edl_asset_paths(dict(edl), project_timeline)

    if not mix.get("include_video_track"):
        project_timeline = []

    if edl and edl.get("tracks", {}).get("video"):
        export_from_edl(
            edl,
            output_path,
            template_video_path=template_video_path,
            template_audio_path=getattr(template, "audio_path", ""),
            template_subtitle_srt_path=getattr(template, "subtitle_srt_path", ""),
            template_subtitle_ass_path=getattr(template, "subtitle_ass_path", ""),
            template_segments_json=getattr(template, "segments_json", []),
            timeline_fallback=project_timeline,
            track_controls=track_controls,
            add_subtitles=add_subtitles,
            template_audio_volume=template_audio_volume,
            use_asset_audio=use_asset_audio,
            asset_audio_volume=asset_audio_volume,
            include_overlay=mix.get("include_overlay", True),
            include_video2=mix.get("include_video2", True),
            video_codec=video_codec,
            resolution=resolution,
        )
    else:
        export_video(
            timeline=project_timeline,
            output_path=output_path,
            resolution=resolution,
            template_video_path=template_video_path,
            template_audio_path=getattr(template, "audio_path", ""),
            template_subtitle_srt_path=getattr(template, "subtitle_srt_path", ""),
            template_subtitle_ass_path=getattr(template, "subtitle_ass_path", ""),
            template_segments_json=getattr(template, "segments_json", []),
            add_subtitles=add_subtitles,
            use_slot_subtitles=use_slot_subtitles,
            use_asset_audio=use_asset_audio,
            asset_audio_volume=asset_audio_volume,
            template_audio_volume=template_audio_volume,
            tts_segments=getattr(template, "tts_segments_json", []) or [],
        )
    return {"output_url": f"/storage/exports/{os.path.basename(output_path)}", "filename": os.path.basename(output_path), "codec": video_codec}


@router.post("/render")
async def render_video(
    project_id: str | None = None,
    template_id: str | None = None,
    timeline: list | None = Body(default=None),
    resolution: str = "1080x1920",
    add_subtitles: bool = True,
    use_slot_subtitles: bool = True,
    use_asset_audio: bool = False,
    asset_audio_volume: float = 0.3,
    template_audio_volume: float = 1.0,
    template_music_enabled: bool = True,
    track_controls: dict | None = Body(default=None),
    use_edl: bool = True,
    use_nvenc: bool = True,
    codec: str | None = None,
    db: Session = Depends(get_db),
):
    template, project_timeline, project = _resolve_export_context(db, project_id, template_id, timeline)

    template_video_path = template.file_path
    if not template_video_path:
        raise HTTPException(status_code=404, detail="模板视频文件不存在")

    try:
        template_video_path = ensure_storage_subpath(template_video_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="模板视频路径非法") from exc

    if not os.path.exists(template_video_path):
        raise HTTPException(status_code=404, detail="模板视频文件不存在")

    if template.processing_status == "processing":
        raise HTTPException(status_code=409, detail="模板仍在后台处理中，请稍后再导出")

    output_filename = f"{uuid.uuid4()}.mp4"
    output_path = os.path.join("storage", "exports", output_filename)

    import asyncio

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(
                _run_export_job,
                template=template,
                project_timeline=project_timeline,
                project=project,
                output_path=output_path,
                resolution=resolution,
                add_subtitles=add_subtitles,
                use_slot_subtitles=use_slot_subtitles,
                use_asset_audio=use_asset_audio,
                asset_audio_volume=asset_audio_volume,
                template_audio_volume=template_audio_volume,
                template_music_enabled=template_music_enabled,
                track_controls_override=track_controls,
                use_edl=use_edl,
                use_nvenc=use_nvenc,
                codec=codec,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"视频导出失败: {exc}") from exc

    return {
        "success": True,
        "output_url": result["output_url"],
        "filename": result["filename"],
        "codec": result.get("codec"),
        "add_subtitles": add_subtitles,
        "use_slot_subtitles": use_slot_subtitles,
        "use_asset_audio": use_asset_audio,
        "use_edl": use_edl,
    }


@router.get("/capcut-status")
def capcut_mate_status():
    from utils.public_media import detect_lan_host, resolve_public_media_base

    media_base = resolve_public_media_base()
    reachable = capcut_ping()
    return {
        "enabled": capcut_mate_enabled(),
        "base_url": CAPCUT_MATE_BASE_URL,
        "reachable": reachable,
        "ready": capcut_mate_enabled() and reachable,
        "public_media_base_url": media_base,
        "detected_lan_host": detect_lan_host(),
        "api_key_required_for_storage": bool(os.getenv("API_KEY", "").strip()),
        "hint": (
            "1) 启动剪映小助手 CapCut Mate（默认 http://127.0.0.1:30000）；"
            "2) 安装剪映 PC 版；"
            "3) 导出后点击「在剪映中打开草稿」安装到剪映目录（勿手动新建空白项目）；"
            "4) 若素材拉取失败，在 backend/.env 设置 PUBLIC_MEDIA_BASE_URL"
        ),
    }


class CapCutInstallDraftRequest(BaseModel):
    draft_url: str


@router.post("/capcut-install-draft")
def install_capcut_draft(body: CapCutInstallDraftRequest):
    """将已导出的 CapCut Mate 草稿复制到剪映 PC 草稿目录。"""
    from utils.jianying_draft import install_capcut_draft_to_jianying

    draft_url = (body.draft_url or "").strip()
    if not draft_url:
        raise HTTPException(status_code=400, detail="缺少 draft_url")
    try:
        return install_capcut_draft_to_jianying(draft_url)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/capcut-draft-async")
def export_capcut_draft_async(body: CapCutDraftRequest, db: Session = Depends(get_db)):
    """异步导出剪映草稿，前端轮询 /tasks/{task_id} 获取进度。"""
    if not capcut_mate_enabled():
        raise HTTPException(
            status_code=503,
            detail="未配置 CAPCUT_MATE_BASE_URL，无法导出剪映草稿",
        )
    if not capcut_ping():
        raise HTTPException(
            status_code=503,
            detail=f"无法连接剪映小助手（{CAPCUT_MATE_BASE_URL}），请先启动 CapCut Mate",
        )

    template, project_timeline, project = _resolve_export_context(
        db, body.project_id, body.template_id, body.timeline
    )

    if template.processing_status == "processing":
        raise HTTPException(status_code=409, detail="模板仍在后台处理中")

    from utils.public_media import resolve_public_media_base

    media_base = resolve_public_media_base(body.media_base_url)

    track_controls = body.track_controls
    if track_controls is None and project is not None:
        track_controls = getattr(project, "track_controls_json", None) or {}

    task_id = create_task(
        "capcut_draft",
        {
            "project_id": body.project_id,
            "capcut_export_mode": body.capcut_export_mode,
        },
    )

    def _job():
        result = export_timeline_to_capcut_draft(
            timeline=project_timeline,
            template=template,
            resolution=body.resolution,
            media_base_url=media_base,
            template_music_enabled=body.template_music_enabled,
            use_asset_audio=body.use_asset_audio,
            asset_audio_volume=body.asset_audio_volume,
            template_audio_volume=body.template_audio_volume,
            add_subtitles=body.add_subtitles,
            track_controls=track_controls,
            include_template_slots=body.include_template_slots,
            capcut_export_mode=body.capcut_export_mode,
            task_id=task_id,
        )
        project_name = getattr(project, "name", "") if project else ""
        return {
            "success": True,
            **result,
            "project_name": project_name,
            "message": (
                f"已生成 {result.get('clips_count', 0)} 个片段的剪映草稿"
                + (f"（{project_name}）" if project_name else "")
                + "，请点击 draft_url 在剪映中打开"
            ),
        }

    run_task(task_id, _job)
    return {"success": True, "task_id": task_id}


@router.post("/capcut-draft")
async def export_capcut_draft(body: CapCutDraftRequest, db: Session = Depends(get_db)):
    """将当前项目时间轴导出为剪映草稿（CapCut Mate）。"""
    import asyncio

    if not capcut_mate_enabled():
        raise HTTPException(
            status_code=503,
            detail="未配置 CAPCUT_MATE_BASE_URL，无法导出剪映草稿",
        )
    if not capcut_ping():
        raise HTTPException(
            status_code=503,
            detail=f"无法连接剪映小助手（{CAPCUT_MATE_BASE_URL}），请先启动 CapCut Mate",
        )

    template, project_timeline, project = _resolve_export_context(
        db, body.project_id, body.template_id, body.timeline
    )

    if template.processing_status == "processing":
        raise HTTPException(status_code=409, detail="模板仍在后台处理中")

    from utils.public_media import resolve_public_media_base

    media_base = resolve_public_media_base(body.media_base_url)

    track_controls = body.track_controls
    if track_controls is None and project is not None:
        track_controls = getattr(project, "track_controls_json", None) or {}

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(
                export_timeline_to_capcut_draft,
                timeline=project_timeline,
                template=template,
                resolution=body.resolution,
                media_base_url=media_base,
                template_music_enabled=body.template_music_enabled,
                use_asset_audio=body.use_asset_audio,
                asset_audio_volume=body.asset_audio_volume,
                template_audio_volume=body.template_audio_volume,
                add_subtitles=body.add_subtitles,
                track_controls=track_controls,
                include_template_slots=body.include_template_slots,
                capcut_export_mode=body.capcut_export_mode,
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"剪映草稿导出失败: {exc}") from exc

    project_name = getattr(project, "name", "") if project else ""
    return {
        "success": True,
        **result,
        "project_name": project_name,
        "message": (
            f"已生成 {result.get('clips_count', 0)} 个片段的剪映草稿"
            + (f"（{project_name}）" if project_name else "")
            + "，请点击 draft_url 在剪映中打开"
        ),
    }


@router.post("/render-async")
def render_video_async(body: AsyncRenderRequest, db: Session = Depends(get_db)):
    template, project_timeline, project = _resolve_export_context(
        db, body.project_id, body.template_id, body.timeline
    )

    if template.processing_status == "processing":
        raise HTTPException(status_code=409, detail="模板仍在后台处理中")

    output_filename = f"{uuid.uuid4()}.mp4"
    output_path = os.path.join("storage", "exports", output_filename)

    task_id = create_task("export", {"project_id": body.project_id, "output": output_filename})

    def _job():
        return _run_export_job(
            template=template,
            project_timeline=project_timeline,
            project=project,
            output_path=output_path,
            resolution=body.resolution,
            add_subtitles=body.add_subtitles,
            use_slot_subtitles=body.use_slot_subtitles,
            use_asset_audio=body.use_asset_audio,
            asset_audio_volume=body.asset_audio_volume,
            template_audio_volume=body.template_audio_volume,
            template_music_enabled=body.template_music_enabled,
            track_controls_override=body.track_controls,
            use_edl=body.use_edl,
            use_nvenc=body.use_nvenc,
            codec=body.codec,
        )

    run_task(task_id, _job)
    return {"success": True, "task_id": task_id}


@router.get("/tasks/{task_id}")
def get_export_task(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/codecs")
def list_codecs():
    from services.proxy_generator import detect_nvenc_available

    return {
        "nvenc_available": detect_nvenc_available(),
        "resolutions": ["1080x1920", "1920x1080", "2160x3840", "3840x2160"],
        "codecs": ["libx264", "h264_nvenc"],
    }
