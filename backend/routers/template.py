import os
import time
import uuid
import shutil
from typing import Any, Dict, List

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Body
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models.database import SessionLocal, Template, get_db
from services.audio_processor import extract_template_audio_clean
from services.media_probe import has_audio_stream
from services.proxy_generator import normalize_proxy_paths
from services.subtitle_gen import normalize_chinese_subtitle
from services.subtitle_render import normalize_segments, write_ass, write_srt
from services.slot_subtitle import extract_subtitles_for_slot_range, slot_dict_source_range
from services.task_queue import create_task, run_task
from services.template_processor import (
    mark_template_failed,
    process_template_full as run_template_full,
)
from services.vocal_separator import ensure_vocal_and_bgm_tracks
from utils.security import resolve_storage_path
from utils.upload_stream import save_upload_stream


router = APIRouter()


def _template_tts_payload(template: Template) -> dict[str, Any]:
    from services.tts.tts_pipeline import build_pipeline_debug, get_timeline_timing_mode

    clips = getattr(template, "subtitle_clips_json", []) or []
    tts_segments = getattr(template, "tts_segments_json", []) or []
    slots = getattr(template, "slots", []) or []
    voice_id = getattr(template, "voice_id", "") or ""
    timing_mode = getattr(template, "timeline_timing_mode", "") or get_timeline_timing_mode()
    pipeline_stage = getattr(template, "pipeline_stage", "") or ""
    pipeline_debug = build_pipeline_debug(
        clips=clips,
        tts_segments=tts_segments,
        slots=slots,
        pipeline_stage=pipeline_stage or None,
        voice_id=voice_id or None,
        timing_mode=timing_mode,
    )
    return {
        "tts_segments_json": tts_segments,
        "ttsSegments": tts_segments,
        "voiceId": voice_id,
        "voice_id": voice_id,
        "timelineTimingMode": timing_mode,
        "timeline_timing_mode": timing_mode,
        "pipelineStage": pipeline_debug.get("pipelineStage"),
        "pipelineDebug": pipeline_debug,
    }


class GenerateTtsRequest(BaseModel):
    voice_id: str = Field(default="real_blog_female", alias="voiceId")
    clip_ids: list[str] = Field(default_factory=list, alias="clipIds")
    overwrite: bool = False

    model_config = {"populate_by_name": True}


class AiSplitByCaptionsRequest(BaseModel):
    source: str = "caption_clips"
    overwrite_slots: bool = Field(default=True, alias="overwriteSlots")
    use_tts_aligned_time: bool = Field(default=True, alias="useTtsAlignedTime")
    merge_short_fragments: bool = Field(default=True, alias="mergeShortFragments")
    subtitle_clips: list[dict] | None = Field(default=None, alias="subtitleClips")

    model_config = {"populate_by_name": True}


class AiSplitByVisualRequest(BaseModel):
    overwrite_slots: bool = Field(default=True, alias="overwriteSlots")
    skip_ai_refine: bool = Field(default=False, alias="skipAiRefine")
    subtitle_clips: list[dict] | None = Field(default=None, alias="subtitleClips")

    model_config = {"populate_by_name": True}


def _run_ai_split_template(template: Template, req: AiSplitByCaptionsRequest, db: Session) -> dict:
    from services.caption_clip_quality import attach_quality_to_clips
    from services.caption_slot_builder import ai_split_by_captions
    from services.slot_helpers import slots_will_be_overwritten_by_ai_split
    from services.tts.tts_pipeline import build_pipeline_debug, get_timeline_timing_mode

    clips = req.subtitle_clips if req.subtitle_clips is not None else (template.subtitle_clips_json or [])
    clips = attach_quality_to_clips(list(clips or []))
    if not clips:
        raise HTTPException(status_code=400, detail="请先识别字幕")

    resolved_path = resolve_storage_path(template.file_path or "") or template.file_path or ""
    if not resolved_path or not os.path.isfile(resolved_path):
        raise HTTPException(status_code=400, detail="模板视频不存在")

    existing_slots = list(template.slots or [])
    if slots_will_be_overwritten_by_ai_split(existing_slots) and not req.overwrite_slots:
        raise HTTPException(status_code=409, detail="AI 一键分割画面会覆盖当前画面槽，请确认后重试")

    vision = getattr(template, "ai_vision_json", None) or {}
    visual_suggestions = vision.get("visualCutSuggestions") if isinstance(vision, dict) else None

    tts_segments = getattr(template, "tts_segments_json", []) or []
    timing_mode = getattr(template, "timeline_timing_mode", "") or None

    try:
        applied = ai_split_by_captions(
            template.id,
            resolved_path,
            clips,
            duration=float(getattr(template, "duration", 0) or 0),
            tts_segments=tts_segments,
            timing_mode=timing_mode,
            merge_short_fragments=req.merge_short_fragments,
            use_tts_aligned_time=req.use_tts_aligned_time,
            existing_slots=existing_slots,
            overwrite_slots=req.overwrite_slots,
            visual_suggestions=visual_suggestions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    slots = applied.get("slots") or []
    template.slots = slots
    template.slot_count = len(slots)
    template.subtitle_clips_json = applied.get("sentence_clips") or clips
    template.pipeline_stage = "slots_applied"
    flag_modified(template, "slots")
    flag_modified(template, "subtitle_clips_json")
    db.commit()
    db.refresh(template)

    pipeline_debug = build_pipeline_debug(
        clips=template.subtitle_clips_json,
        tts_segments=tts_segments,
        slots=slots,
        pipeline_stage="slots_applied",
        voice_id=getattr(template, "voice_id", "") or "",
        timing_mode=timing_mode or get_timeline_timing_mode(),
    )

    return {
        "success": True,
        "slotCount": len(slots),
        "subtitleClipCount": len(clips),
        "slots": slots,
        "subtitleClips": template.subtitle_clips_json,
        "aiSplitDebug": applied.get("ai_split_debug") or {},
        "oneCaptionOneShotDebug": applied.get("oneCaptionOneShotDebug") or {},
        "overwriteWarning": applied.get("overwrite_warning"),
        "reviewWarning": applied.get("review_warning"),
        "ttsWarning": applied.get("tts_warning"),
        "pipelineDebug": pipeline_debug,
        "summary": applied.get("summary") or {},
    }


def _run_visual_split_template(template: Template, req: AiSplitByVisualRequest, db: Session) -> dict:
    from services.caption_clip_quality import attach_quality_to_clips
    from services.caption_slot_builder import ai_split_by_visual_scenes
    from services.slot_helpers import slots_will_be_overwritten_by_ai_split
    from services.tts.tts_pipeline import build_pipeline_debug, get_timeline_timing_mode

    clips = req.subtitle_clips if req.subtitle_clips is not None else (template.subtitle_clips_json or [])
    clips = attach_quality_to_clips(list(clips or []))

    resolved_path = resolve_storage_path(template.file_path or "") or template.file_path or ""
    if not resolved_path or not os.path.isfile(resolved_path):
        raise HTTPException(status_code=400, detail="模板视频不存在")

    existing_slots = list(template.slots or [])
    if slots_will_be_overwritten_by_ai_split(existing_slots) and not req.overwrite_slots:
        raise HTTPException(status_code=409, detail="按画面切分会覆盖当前画面槽，请确认后重试")

    tts_segments = getattr(template, "tts_segments_json", []) or []
    timing_mode = getattr(template, "timeline_timing_mode", "") or None

    try:
        applied = ai_split_by_visual_scenes(
            template.id,
            resolved_path,
            clips,
            duration=float(getattr(template, "duration", 0) or 0),
            existing_slots=existing_slots,
            overwrite_slots=req.overwrite_slots,
            skip_ai_refine=req.skip_ai_refine,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    slots = applied.get("slots") or []
    template.slots = slots
    template.slot_count = len(slots)
    if applied.get("sentence_clips"):
        template.subtitle_clips_json = applied["sentence_clips"]
    template.pipeline_stage = "slots_applied"
    flag_modified(template, "slots")
    flag_modified(template, "subtitle_clips_json")
    db.commit()
    db.refresh(template)

    pipeline_debug = build_pipeline_debug(
        clips=template.subtitle_clips_json,
        tts_segments=tts_segments,
        slots=slots,
        pipeline_stage="slots_applied",
        voice_id=getattr(template, "voice_id", "") or "",
        timing_mode=timing_mode or get_timeline_timing_mode(),
    )

    return {
        "success": True,
        "slotCount": len(slots),
        "subtitleClipCount": len(clips),
        "slots": slots,
        "subtitleClips": template.subtitle_clips_json,
        "aiSplitDebug": applied.get("ai_split_debug") or {},
        "visualSplitDebug": applied.get("ai_split_debug") or {},
        "overwriteWarning": applied.get("overwrite_warning"),
        "pipelineDebug": pipeline_debug,
        "summary": applied.get("summary") or {},
        "splitStrategy": "visual_scene_split",
    }


def build_quick_template_slots(duration: float = 0) -> List[Dict[str, Any]]:
    slot_duration = round(duration, 3) if duration > 0 else 3.0
    return [
        {
            "id": "slot_base_001",
            "slot_id": 1,
            "start": 0.0,
            "end": slot_duration,
            "duration": slot_duration,
            "clip_start": 0.0,
            "clip_end": slot_duration,
            "source": "base",
            "cut_reason": "full_video",
            "isBaseSlot": True,
            "subtitle_text": "",
            "thumbnail": "",
            "tags": [],
            "scene_tags": [],
            "shot_type": "wide",
            "has_person": False,
            "quality_score": 0.5,
        }
    ]


def _template_pipeline_helpers() -> dict:
    from services.subtitle_gen import transcribe

    return {
        "extract_audio_fn": extract_template_audio,
        "extract_whisper_audio_fn": extract_audio_for_whisper,
        "transcribe_fn": transcribe,
        "normalize_segments_fn": lambda raw: normalize_segments(
            raw, normalize_text=normalize_chinese_subtitle
        ),
        "write_srt_fn": write_srt,
        "write_ass_fn": write_ass,
        "attach_subtitles_fn": attach_subtitles_to_slots,
        "has_audio_fn": has_audio_stream,
        "file_ok_fn": file_ok,
    }


def _run_template_pipeline_safe(
    template_id: str,
    file_path: str,
    template_dir: str,
    subtitle_style: str,
):
    try:
        run_template_full(
            template_id,
            file_path,
            template_dir,
            subtitle_style,
            **_template_pipeline_helpers(),
        )
    except Exception as exc:
        print(f"模板后台处理失败: {template_id} -> {exc}")
        mark_template_failed(template_id, str(exc))


def enqueue_template_processing(
    template_id: str,
    file_path: str,
    template_dir: str,
    subtitle_style: str,
) -> str:
    task_id = create_task("template_process", {"template_id": template_id})
    run_task(
        task_id,
        lambda: _run_template_pipeline_safe(
            template_id, file_path, template_dir, subtitle_style
        ),
    )
    return task_id


def file_ok(path: str) -> bool:
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0


def extract_template_audio(video_path: str, output_path: str):
    """提取模板音频（高质量 / 流复制，带轻度限幅）。"""
    if not has_audio_stream(video_path):
        raise RuntimeError("模板视频没有音频轨")
    extract_template_audio_clean(video_path, output_path)


def extract_audio_for_whisper(video_path: str, output_path: str):
    """
    提取给 Whisper 使用的音频：先分离人声与 BGM，再输出 16k 人声音轨。
    """
    if not has_audio_stream(video_path):
        raise RuntimeError("模板视频没有音频轨，无法识别字幕")

    template_dir = os.path.dirname(resolve_storage_path(video_path))
    tracks = ensure_vocal_and_bgm_tracks(video_path, template_dir)
    whisper_src = tracks.get("whisper") or tracks.get("vocals")
    if not whisper_src or not file_ok(whisper_src):
        raise RuntimeError("人声轨生成失败")

    if os.path.abspath(whisper_src) != os.path.abspath(output_path):
        shutil.copy2(whisper_src, output_path)

    if not file_ok(output_path):
        raise RuntimeError("Whisper 音频提取失败")


def attach_subtitles_to_slots(
    slots: List[Dict[str, Any]],
    subtitle_segments: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    把模板字幕挂到对应分段 slot 上，方便前端显示。
    """
    result = []

    for slot in slots:
        item = dict(slot)
        slot_start, slot_end = slot_dict_source_range(item)
        related_segments = extract_subtitles_for_slot_range(subtitle_segments, slot_start, slot_end)
        item["subtitle_text"] = " ".join(seg["text"] for seg in related_segments).strip()
        item["subtitle_segments"] = related_segments
        result.append(item)

    return result


@router.post("/upload")
async def upload_template(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    上传模板视频：
    1. 流式保存视频并立即返回占位时间线
    2. 后台完成镜头切分、CLIP、音频与字幕
    """
    template_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename or "")[1].lower() or ".mp4"
    safe_filename = f"{template_id}{ext}"

    template_dir = os.path.join("storage", "templates", template_id)
    os.makedirs(template_dir, exist_ok=True)
    file_path = os.path.join(template_dir, safe_filename)

    await save_upload_stream(file, file_path)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=500, detail="模板视频保存失败")

    # 不在上传请求中阻塞 ffprobe，时长与槽位由后台 fast_intake 补齐
    duration = 0.0
    slots = build_quick_template_slots(0)
    beat_markers = []

    subtitle_style = (
        "FontName=Microsoft YaHei;"
        "FontSize=54;"
        "PrimaryColour=&H00FFFFFF;"
        "OutlineColour=&H00000000;"
        "BorderStyle=1;"
        "Outline=3;"
        "Shadow=0;"
        "Alignment=2;"
        "MarginV=120"
    )

    template = Template(
        id=template_id,
        filename=file.filename,
        duration=duration,
        slot_count=len(slots),
        file_path=file_path,
        slots=slots,
        audio_path="",
        subtitle_srt_path="",
        subtitle_ass_path="",
        subtitle_style=subtitle_style,
        segments_json=[],
        processing_status="processing",
        processing_progress=5,
        enhance_status="processing",
        enhance_progress=0,
        beat_markers=beat_markers,
        created_at=time.time()
    )

    db.add(template)
    db.commit()

    task_id = enqueue_template_processing(
        template_id,
        file_path,
        template_dir,
        subtitle_style,
    )

    return {
        "template_id": template_id,
        "filename": file.filename,
        "duration": duration,
        "slot_count": len(slots),
        "file_path": file_path,
        "slots": slots,
        "audio_path": "",
        "subtitle_srt_path": "",
        "subtitle_ass_path": "",
        "subtitle_style": subtitle_style,
        "segments_json": [],
        "processing": True,
        "processing_progress": 5,
        "processing_status": "processing",
        "task_id": task_id,
        "beat_markers": beat_markers,
    }


@router.get("/list")
def list_templates(db: Session = Depends(get_db)):
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
                "created_at": t.created_at,
            }
            for t in templates
        ],
    }


@router.get("/scene-tuning/profiles")
def list_template_scene_profiles():
    """列出旅游混剪镜头切分档位与当前生效参数。"""
    from services.processing_config import TEMPLATE_SCENE_AUTO_TUNE, TEMPLATE_SCENE_PROFILE
    from services.template_scene_tuning import get_template_tuning, list_scene_profiles

    return {
        "success": True,
        "profiles": list_scene_profiles(),
        "active_profile": TEMPLATE_SCENE_PROFILE,
        "auto_tune": TEMPLATE_SCENE_AUTO_TUNE,
        "current": get_template_tuning().to_dict(),
        "hint": "切分过多 → 换 travel_slow 或提高 TEMPLATE_SCENE_THRESHOLD；漏切 → travel_ultra/travel_fast 或降低 threshold",
    }


@router.post("/{template_id}/calibrate-scenes")
def calibrate_template_scenes_endpoint(
    template_id: str,
    profile: str = "travel_fast",
    apply: bool = False,
    db: Session = Depends(get_db),
):
    """
    对模板样片探测最优 TEMPLATE_SCENE_THRESHOLD（不重新跑全流水线，除非 apply=true）。
    apply=true 时写入 scene_tuning.json 并触发 reprocess。
    """
    from services.scene_detector import get_video_duration
    from services.template_scene_tuning import (
        calibrate_template_scenes,
        get_template_tuning,
        save_persisted_tuning,
    )

    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    if not template.file_path or not os.path.isfile(template.file_path):
        raise HTTPException(status_code=400, detail="模板视频不存在")

    duration = float(template.duration or 0) or get_video_duration(template.file_path)
    tuning = get_template_tuning({"profile": profile})
    calibration = calibrate_template_scenes(template.file_path, duration, tuning)
    tuning.threshold = float(calibration["threshold"])

    saved_path = ""
    task_id = None
    if apply:
        saved_path = save_persisted_tuning(template.file_path, tuning, calibration=calibration)
        template.processing_status = "processing"
        template.processing_progress = 5
        db.commit()
        task_id = enqueue_template_processing(
            template_id,
            template.file_path,
            os.path.dirname(template.file_path),
            template.subtitle_style or "",
        )

    return {
        "success": True,
        "template_id": template_id,
        "profile": profile,
        "calibration": calibration,
        "recommended_threshold": calibration["threshold"],
        "applied": apply,
        "saved_path": saved_path,
        "task_id": task_id,
    }


@router.post("/{template_id}/reprocess")
def reprocess_template(
    template_id: str,
    profile: str | None = None,
    auto_tune: bool | None = None,
    db: Session = Depends(get_db),
):
    """重新触发模板后台处理；可选 profile / auto_tune 写入 scene_tuning.json。"""
    from services.template_scene_tuning import get_template_tuning, save_persisted_tuning

    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    if not template.file_path or not os.path.isfile(template.file_path):
        raise HTTPException(status_code=400, detail="模板视频文件不存在")

    if profile is not None or auto_tune is not None:
        override: dict = {}
        if profile is not None:
            override["profile"] = profile
        tuning = get_template_tuning(override if override else None)
        if auto_tune is not None:
            tuning.auto_tune = auto_tune
        save_persisted_tuning(template.file_path, tuning)

    template_dir = os.path.dirname(template.file_path)
    subtitle_style = template.subtitle_style or ""
    template.processing_status = "processing"
    template.processing_progress = 5
    if hasattr(template, "enhance_status"):
        template.enhance_status = "processing"
        template.enhance_progress = 0
    db.commit()

    task_id = enqueue_template_processing(
        template_id,
        template.file_path,
        template_dir,
        subtitle_style,
    )
    return {
        "success": True,
        "template_id": template_id,
        "task_id": task_id,
        "processing_status": "processing",
        "processing_progress": 5,
        "profile": profile,
        "auto_tune": auto_tune,
    }


@router.post("/{template_id}/analyze-media")
def analyze_template_media(template_id: str, db: Session = Depends(get_db)):
    """对已有模板重新运行字幕花字样式 + 音效点位分析（不重新切分镜头）。"""
    from services.template_processor import _apply_media_enrichment

    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    if not template.file_path or not os.path.isfile(template.file_path):
        raise HTTPException(status_code=400, detail="模板视频文件不存在")

    template_dir = os.path.dirname(template.file_path)
    try:
        _apply_media_enrichment(
            template_id,
            template.file_path,
            template_dir,
            include_subtitle_styles=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"媒体分析失败: {exc}") from exc

    db.refresh(template)
    return {
        "success": True,
        "template_id": template_id,
        "beat_markers": getattr(template, "beat_markers", []) or [],
        "sfx_markers": getattr(template, "sfx_markers", []) or [],
        "segments_json": getattr(template, "segments_json", []) or [],
        "slots": template.slots,
    }


@router.post("/{template_id}/analyze-effects")
def analyze_template_effects(template_id: str, db: Session = Depends(get_db)):
    """对已有模板重新运行 AI 槽位特效分析（调色/动效/字幕动画）。"""
    from services.template_effects_analyzer import enrich_slots_with_ai_effects

    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    if not template.file_path or not os.path.isfile(template.file_path):
        raise HTTPException(status_code=400, detail="模板视频文件不存在")

    template_dir = os.path.dirname(template.file_path)
    slots = list(template.slots or [])
    if not slots:
        raise HTTPException(status_code=400, detail="模板尚无槽位")

    try:
        enriched = enrich_slots_with_ai_effects(template.file_path, slots, template_dir)
        template.slots = enriched
        db.commit()
        db.refresh(template)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"特效分析失败: {exc}") from exc

    return {
        "success": True,
        "template_id": template_id,
        "slots": template.slots,
        "analyzed_count": sum(1 for s in (template.slots or []) if isinstance(s, dict) and s.get("auto_effects")),
    }


@router.get("/{template_id}/status")
def get_template_status(template_id: str, db: Session = Depends(get_db)):
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    slots = template.slots or []
    slots_ai_ready = sum(
        1
        for s in slots
        if isinstance(s, dict)
        and (
            s.get("ai_description")
            or (isinstance(s.get("scene_tags"), list) and len(s.get("scene_tags") or []) > 0)
        )
    )
    slots_subtitle_ready = sum(
        1 for s in slots if isinstance(s, dict) and str(s.get("subtitle_text") or "").strip()
    )
    from services.template_subtitle_auto import is_subtitle_batch_running
    from services.subtitle_status import build_template_subtitle_status
    from services.processing_config import SUBTITLE_RECOGNITION_MODE

    subtitle_status = build_template_subtitle_status(template)

    return {
        "template_id": template.id,
        "processing_status": getattr(template, "processing_status", "ready"),
        "processing_progress": getattr(template, "processing_progress", 100),
        "enhance_status": getattr(template, "enhance_status", "ready") or "ready",
        "enhance_progress": getattr(template, "enhance_progress", 100) or 100,
        "audio_ready": bool(getattr(template, "audio_path", "")),
        "subtitle_ready": bool(getattr(template, "subtitle_srt_path", "")),
        "subtitle_batch_running": is_subtitle_batch_running(template.id),
        "beat_markers": getattr(template, "beat_markers", []) or [],
        "sfx_markers": getattr(template, "sfx_markers", []) or [],
        "segments_json": getattr(template, "segments_json", []) or [],
        "slot_count": getattr(template, "slot_count", 0) or len(slots),
        "slots_ai_ready_count": slots_ai_ready,
        "slots_subtitle_ready_count": slots_subtitle_ready,
        "subtitle_recognition_mode": SUBTITLE_RECOGNITION_MODE,
        "subtitle_empty_count": subtitle_status["empty_count"],
        "subtitle_low_count": subtitle_status["low_count"],
        "subtitle_duplicate_count": subtitle_status["duplicate_count"],
        "subtitle_progress_label": subtitle_status["progress_label"],
        "ai_understanding_ready": slots_ai_ready >= max(1, len(slots) // 2),
        "ai_vision": getattr(template, "ai_vision_json", None) or {},
        "duration": template.duration,
        "proxy_paths": normalize_proxy_paths(getattr(template, "proxy_paths", None)),
        "editable": getattr(template, "processing_status", "ready") == "ready"
        and (getattr(template, "slot_count", 0) or len(slots)) > 0,
    }


@router.delete("/{template_id}")
def delete_template(template_id: str, db: Session = Depends(get_db)):
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    template_dir = os.path.join("storage", "templates", template_id)
    thumb_dir = os.path.join("storage", "thumbnails", template_id)
    for path in (template_dir, thumb_dir):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    if template.file_path and os.path.isfile(template.file_path):
        try:
            os.remove(template.file_path)
        except OSError:
            pass

    db.delete(template)
    db.commit()
    return {"success": True}


@router.get("/{template_id}/waveform")
def get_template_waveform(template_id: str, bars: int = 300, db: Session = Depends(get_db)):
    """提取模板 BGM 波形峰值，供前端时间轴真实波形渲染。"""
    from services.waveform import extract_waveform_peaks
    from utils.security import resolve_storage_path

    t = db.query(Template).filter(Template.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")

    audio_path = getattr(t, "audio_path", "") or ""
    if audio_path:
        audio_path = resolve_storage_path(audio_path) or audio_path
    if not audio_path or not os.path.isfile(audio_path):
        video_path = resolve_storage_path(t.file_path) if t.file_path else ""
        audio_path = video_path if video_path and os.path.isfile(video_path) else ""

    peaks = extract_waveform_peaks(audio_path, bars=bars) if audio_path else []
    return {
        "success": True,
        "template_id": template_id,
        "bars": len(peaks),
        "peaks": peaks,
        "duration": t.duration,
    }


@router.get("/{template_id}/timeline-thumbnails")
def get_template_timeline_thumbnails(
    template_id: str,
    generate: bool = True,
    include_high: bool = False,
    db: Session = Depends(get_db),
):
    """返回模板多档位时间轴缩略图，供导轨 filmstrip 预览。"""
    from services.timeline_thumbnails import get_timeline_thumbnail_profiles

    t = db.query(Template).filter(Template.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")

    video_path = resolve_storage_path(t.file_path) if t.file_path else ""
    if not video_path or not os.path.isfile(video_path):
        raise HTTPException(status_code=404, detail="模板视频不存在")

    payload = get_timeline_thumbnail_profiles(
        video_path,
        template_id,
        generate_missing=generate,
        include_high=include_high,
    )
    return {
        "success": True,
        **payload,
    }


@router.get("/{template_id}")
def get_template(template_id: str, db: Session = Depends(get_db)):
    """
    获取模板信息。
    """
    t = db.query(Template).filter(Template.id == template_id).first()

    if not t:
        raise HTTPException(status_code=404, detail="模板不存在")

    return {
        "template_id": t.id,
        "filename": t.filename,
        "duration": t.duration,
        "slot_count": t.slot_count,
        "file_path": t.file_path,
        "slots": t.slots,
        "audio_path": getattr(t, "audio_path", ""),
        "subtitle_srt_path": getattr(t, "subtitle_srt_path", ""),
        "subtitle_ass_path": getattr(t, "subtitle_ass_path", ""),
        "subtitle_style": getattr(t, "subtitle_style", ""),
        "segments_json": getattr(t, "segments_json", []),
        "subtitle_clips_json": getattr(t, "subtitle_clips_json", []) or [],
        "subtitleClips": getattr(t, "subtitle_clips_json", []) or [],
        "cutStrategy": (
            getattr(t, "cut_strategy", None)
            or os.getenv("CUT_STRATEGY", "caption_slot")
        ),
        "sfx_markers": getattr(t, "sfx_markers", []) or [],
        "proxy_paths": normalize_proxy_paths(getattr(t, "proxy_paths", None)),
        "ai_vision": getattr(t, "ai_vision_json", None) or {},
        **_template_tts_payload(t),
    }


@router.get("/voices/list")
def list_tts_voices():
    from services.tts.voice_profiles import list_voice_profiles

    profiles = list_voice_profiles()
    return {"success": True, "voices": profiles, "voiceProfiles": profiles}


@router.post("/{template_id}/generate-tts")
async def generate_template_tts(
    template_id: str,
    req: GenerateTtsRequest,
    db: Session = Depends(get_db),
):
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    from services.tts.tts_pipeline import build_pipeline_debug, ensure_clip_timeline_fields, generate_tts_for_clips

    clips = ensure_clip_timeline_fields(getattr(template, "subtitle_clips_json", []) or [])
    if not clips:
        raise HTTPException(status_code=400, detail="没有可用的字幕片段，请先识别字幕")

    try:
        result = generate_tts_for_clips(
            template_id,
            clips,
            voice_id=req.voice_id,
            clip_ids=req.clip_ids or None,
            overwrite=req.overwrite,
            existing_segments=getattr(template, "tts_segments_json", []) or [],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    template.subtitle_clips_json = result.get("clips") or clips
    template.tts_segments_json = result.get("tts_segments") or []
    template.voice_id = req.voice_id
    template.pipeline_stage = "tts_generated"
    flag_modified(template, "subtitle_clips_json")
    flag_modified(template, "tts_segments_json")
    db.commit()
    db.refresh(template)

    pipeline_debug = build_pipeline_debug(
        clips=template.subtitle_clips_json,
        tts_segments=template.tts_segments_json,
        slots=getattr(template, "slots", []) or [],
        pipeline_stage="tts_generated",
        voice_id=req.voice_id,
    )
    return {
        "success": True,
        "ttsSegments": template.tts_segments_json,
        "subtitleClips": template.subtitle_clips_json,
        "summary": result.get("summary") or {},
        "debug": result.get("debug") or {},
        "pipelineDebug": pipeline_debug,
    }


@router.post("/{template_id}/align-timeline-to-tts")
async def align_template_timeline_to_tts(
    template_id: str,
    db: Session = Depends(get_db),
):
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    from services.tts.tts_pipeline import (
        align_timeline_to_tts,
        build_pipeline_debug,
        ensure_clip_timeline_fields,
        get_timeline_timing_mode,
    )

    clips = ensure_clip_timeline_fields(getattr(template, "subtitle_clips_json", []) or [])
    tts_segments = getattr(template, "tts_segments_json", []) or []
    if not clips:
        raise HTTPException(status_code=400, detail="没有可用的字幕片段")
    if not tts_segments:
        raise HTTPException(status_code=400, detail="请先生成 AI 人声")

    aligned_clips, aligned_segments, total_duration = align_timeline_to_tts(clips, tts_segments)
    timing_mode = get_timeline_timing_mode()

    template.subtitle_clips_json = aligned_clips
    template.tts_segments_json = aligned_segments
    template.timeline_timing_mode = timing_mode
    template.pipeline_stage = "timeline_aligned"
    if float(getattr(template, "duration", 0) or 0) < total_duration:
        template.duration = total_duration
    flag_modified(template, "subtitle_clips_json")
    flag_modified(template, "tts_segments_json")
    db.commit()
    db.refresh(template)

    pipeline_debug = build_pipeline_debug(
        clips=aligned_clips,
        tts_segments=aligned_segments,
        slots=getattr(template, "slots", []) or [],
        pipeline_stage="timeline_aligned",
        voice_id=getattr(template, "voice_id", "") or "",
        timing_mode=timing_mode,
    )
    return {
        "success": True,
        "alignedCaptionClips": aligned_clips,
        "subtitleClips": aligned_clips,
        "ttsSegments": aligned_segments,
        "totalDuration": total_duration,
        "timingMode": timing_mode,
        "pipelineDebug": pipeline_debug,
    }


@router.post("/{template_id}/ai-split-by-captions")
async def ai_split_template_by_captions(
    template_id: str,
    req: AiSplitByCaptionsRequest,
    db: Session = Depends(get_db),
):
    """AI 一键分割画面：每个 CaptionClip → 一个 slot。"""
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    if str(req.source or "caption_clips") != "caption_clips":
        raise HTTPException(status_code=400, detail="当前仅支持 source=caption_clips")
    return _run_ai_split_template(template, req, db)


@router.post("/{template_id}/ai-split-by-visual")
async def ai_split_template_by_visual(
    template_id: str,
    req: AiSplitByVisualRequest,
    db: Session = Depends(get_db),
):
    """按原视频画面镜头切分：PySceneDetect 检测切点，字幕按时间重叠关联到各镜头。"""
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return _run_visual_split_template(template, req, db)