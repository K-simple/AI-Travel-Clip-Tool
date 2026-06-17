import os
import subprocess
import uuid
from typing import Any, Dict, List

from services.subtitle_gen import transcribe
from utils.security import resolve_storage_path


def _run_ffmpeg(cmd: List[str]) -> None:
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "ffmpeg 执行失败")


def extract_audio_segment(source_path: str, start: float, end: float, output_path: str) -> None:
    """从模板音频/视频中截取一段，供 Whisper 识别。"""
    resolved = resolve_storage_path(source_path)
    duration = max(0.15, float(end) - float(start))
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(max(0.0, start)),
        "-t",
        str(duration),
        "-i",
        resolved,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        output_path,
    ]
    _run_ffmpeg(cmd)

    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("人声片段截取失败")


def get_whisper_source_path(template) -> str:
    """优先使用模板预处理的人声 wav，否则回退到原视频。"""
    template_dir = os.path.dirname(template.file_path or "")
    whisper_path = os.path.join(template_dir, "template_subtitle_audio.wav")
    if whisper_path and os.path.isfile(whisper_path) and os.path.getsize(whisper_path) > 0:
        return whisper_path
    return template.file_path


def recognize_slot_from_template(template, slot_start: float, slot_end: float) -> List[Dict[str, Any]]:
    """识别指定时间范围内的人声，返回绝对时间轴字幕分段。"""
    source = get_whisper_source_path(template)
    if not source:
        raise RuntimeError("模板缺少音频源")

    temp_path = os.path.join("storage", "temp", f"slot_asr_{uuid.uuid4().hex}.wav")
    try:
        extract_audio_segment(source, slot_start, slot_end, temp_path)
        raw_segments = transcribe(temp_path)

        segments: List[Dict[str, Any]] = []
        for seg in raw_segments:
            start = round(float(seg["start"]) + float(slot_start), 3)
            end = round(float(seg["end"]) + float(slot_start), 3)
            text = str(seg.get("text", "")).strip()
            if not text or end <= start:
                continue
            segments.append(
                {
                    "start": start,
                    "end": end,
                    "duration": round(end - start, 3),
                    "text": text,
                }
            )
        return segments
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
