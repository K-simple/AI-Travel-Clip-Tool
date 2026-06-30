"""ffprobe / ffmpeg 轻量封装（避免 subtitle ↔ video_exporter 循环依赖）。"""

from __future__ import annotations

import os
import subprocess


def has_audio_stream(media_path: str) -> bool:
    if not media_path or not os.path.exists(media_path):
        return False

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(media_path),
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )

    return bool(result.stdout.strip())


def extract_whisper_wav(video_path: str, wav_path: str) -> None:
    """从视频提取 16k 单声道 PCM，供 Whisper 识别。"""
    if not has_audio_stream(video_path):
        raise RuntimeError(f"没有音频轨，无法识别字幕: {video_path}")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(wav_path),
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )

    if result.returncode != 0:
        raise RuntimeError(
            "音频提取失败:\n" + result.stderr.strip() or result.stdout.strip()
        )

    if not os.path.exists(wav_path) or os.path.getsize(wav_path) <= 0:
        raise RuntimeError(f"音频提取失败: {wav_path}")
