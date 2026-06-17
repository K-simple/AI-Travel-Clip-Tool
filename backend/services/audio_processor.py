"""音频提取与降噪处理。"""

import json
import os
import subprocess
from typing import Optional

from services.video_exporter import file_ok, run_cmd


def probe_audio_stream(path: str) -> Optional[dict]:
    if not path or not os.path.exists(path):
        return None
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,channels,sample_rate",
        "-of", "json",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        return streams[0] if streams else None
    except Exception:
        return None


def _try_audio_copy(video_path: str, output_path: str) -> bool:
    info = probe_audio_stream(video_path)
    if not info:
        return False
    codec = (info.get("codec_name") or "").lower()
    if codec not in ("aac", "mp4a"):
        return False

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    try:
        run_cmd(cmd)
        return file_ok(output_path)
    except Exception:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False


def extract_template_audio_clean(video_path: str, output_path: str) -> str:
    """提取模板 BGM：优先流复制，否则高质量 AAC + 轻度滤波。"""
    if not video_path or not os.path.exists(video_path):
        raise RuntimeError("模板视频不存在")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if _try_audio_copy(video_path, output_path):
        return output_path

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-af", "highpass=f=80,lowpass=f=16000,alimiter=limit=0.95",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        "-movflags", "+faststart",
        output_path,
    ]
    run_cmd(cmd)
    if not file_ok(output_path):
        raise RuntimeError("模板音频提取失败")
    return output_path
