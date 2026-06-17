import os
import time
import uuid
import shutil
import subprocess
from typing import Any, Dict, List

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from models.database import SessionLocal, Template, get_db
from services.audio_processor import extract_template_audio_clean
from services.proxy_generator import normalize_proxy_paths
from services.task_queue import create_task, run_task
from services.template_processor import (
    mark_template_failed,
    process_template_full as run_template_full,
)
from utils.upload_stream import save_upload_stream


router = APIRouter()


def build_quick_template_slots(duration: float = 0) -> List[Dict[str, Any]]:
    slot_duration = round(duration, 3) if duration > 0 else 3.0
    return [
        {
            "slot_id": 1,
            "start": 0.0,
            "end": slot_duration,
            "duration": slot_duration,
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
        "normalize_segments_fn": normalize_segments,
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


def run_cmd(cmd, cwd=None):
    print("执行命令:", " ".join(map(str, cmd)))

    result = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )

    if result.returncode != 0:
        raise RuntimeError(
            "命令执行失败:\n"
            + " ".join(map(str, cmd))
            + "\n\nSTDOUT:\n"
            + result.stdout
            + "\n\nSTDERR:\n"
            + result.stderr
        )

    return result


def file_ok(path: str) -> bool:
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0


def has_audio_stream(video_path: str) -> bool:
    if not video_path or not os.path.exists(video_path):
        return False

    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        str(video_path)
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )

    return bool(result.stdout.strip())


def extract_template_audio(video_path: str, output_path: str):
    """提取模板音频（高质量 / 流复制，带轻度限幅）。"""
    if not has_audio_stream(video_path):
        raise RuntimeError("模板视频没有音频轨")
    extract_template_audio_clean(video_path, output_path)


def extract_audio_for_whisper(video_path: str, output_path: str):
    """
    提取给 Whisper 使用的音频，只用于字幕识别。
    """
    if not has_audio_stream(video_path):
        raise RuntimeError("模板视频没有音频轨，无法识别字幕")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        output_path
    ]

    run_cmd(cmd)

    if not file_ok(output_path):
        raise RuntimeError("Whisper 音频提取失败")


def normalize_segments(raw_segments: Any) -> List[Dict[str, Any]]:
    """
    把 subtitle_gen.transcribe 返回的数据统一转成 JSON 可存储格式。
    """
    if raw_segments is None:
        return []

    if isinstance(raw_segments, tuple) and len(raw_segments) >= 1:
        raw_segments = raw_segments[0]

    normalized = []

    for seg in list(raw_segments):
        if isinstance(seg, dict):
            start = float(seg.get("start", 0))
            end = float(seg.get("end", 0))
            text = str(seg.get("text", "")).strip()
        else:
            start = float(getattr(seg, "start", 0))
            end = float(getattr(seg, "end", 0))
            text = str(getattr(seg, "text", "")).strip()

        if not text:
            continue

        if end <= start:
            continue

        normalized.append({
            "start": start,
            "end": end,
            "duration": end - start,
            "text": text
        })

    return normalized


def format_srt_time(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))

    h = total_ms // 3600000
    total_ms %= 3600000

    m = total_ms // 60000
    total_ms %= 60000

    s = total_ms // 1000
    ms = total_ms % 1000

    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_ass_time(seconds: float) -> str:
    total_cs = int(round(seconds * 100))

    h = total_cs // 360000
    total_cs %= 360000

    m = total_cs // 6000
    total_cs %= 6000

    s = total_cs // 100
    cs = total_cs % 100

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_srt(segments: List[Dict[str, Any]], output_path: str):
    """
    生成 SRT 字幕。
    """
    with open(output_path, "w", encoding="utf-8") as f:
        for index, seg in enumerate(segments, start=1):
            start = format_srt_time(float(seg["start"]))
            end = format_srt_time(float(seg["end"]))
            text = seg["text"]

            f.write(f"{index}\n")
            f.write(f"{start} --> {end}\n")
            f.write(f"{text}\n\n")


def ass_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def write_ass(
    segments: List[Dict[str, Any]],
    output_path: str,
    width: int = 1080,
    height: int = 1920
):
    """
    生成 ASS 字幕。
    这里不是提取模板原始花字特效，而是生成统一样式字幕。
    """
    header = f"""[Script Info]
Title: AI Travel Cut Template Subtitle
ScriptType: v4.00+
Collisions: Normal
PlayResX: {width}
PlayResY: {height}
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,54,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,0,2,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)

        for seg in segments:
            start = format_ass_time(float(seg["start"]))
            end = format_ass_time(float(seg["end"]))
            text = ass_escape(seg["text"])

            f.write(
                f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n"
            )


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

        slot_start = float(item.get("start", item.get("start_time", 0)))

        if "end" in item:
            slot_end = float(item["end"])
        elif "end_time" in item:
            slot_end = float(item["end_time"])
        else:
            slot_end = slot_start + float(item.get("duration", 0))

        texts = []
        related_segments = []

        for seg in subtitle_segments:
            seg_start = float(seg["start"])
            seg_end = float(seg["end"])

            overlap = max(slot_start, seg_start) < min(slot_end, seg_end)

            if overlap:
                texts.append(seg["text"])
                related_segments.append(seg)

        item["subtitle_text"] = " ".join(texts).strip()
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


@router.get("/{template_id}/status")
def get_template_status(template_id: str, db: Session = Depends(get_db)):
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    return {
        "template_id": template.id,
        "processing_status": getattr(template, "processing_status", "ready"),
        "processing_progress": getattr(template, "processing_progress", 100),
        "enhance_status": getattr(template, "enhance_status", "ready") or "ready",
        "enhance_progress": getattr(template, "enhance_progress", 100) or 100,
        "audio_ready": bool(getattr(template, "audio_path", "")),
        "subtitle_ready": bool(getattr(template, "subtitle_srt_path", "")),
        "beat_markers": getattr(template, "beat_markers", []) or [],
        "slot_count": getattr(template, "slot_count", 0) or len(template.slots or []),
        "duration": template.duration,
        "proxy_paths": normalize_proxy_paths(getattr(template, "proxy_paths", None)),
        "editable": getattr(template, "processing_status", "ready") == "ready"
        and (getattr(template, "slot_count", 0) or len(template.slots or [])) > 0,
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
        "proxy_paths": normalize_proxy_paths(getattr(t, "proxy_paths", None)),
    }