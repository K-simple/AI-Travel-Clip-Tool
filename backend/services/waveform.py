"""从音频文件提取波形峰值，供时间轴真实波形渲染。"""

import os
import struct
import subprocess
from typing import List

from services.video_exporter import file_ok


def extract_waveform_peaks(audio_path: str, bars: int = 300) -> List[float]:
    """返回 0~1 归一化峰值列表。失败时返回空列表。"""
    if not audio_path or not file_ok(audio_path) or bars < 8:
        return []

    bars = min(int(bars), 2000)
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        audio_path,
        "-ac",
        "1",
        "-ar",
        "8000",
        "-f",
        "f32le",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return []

    if proc.returncode != 0 or not proc.stdout:
        return []

    samples = struct.unpack(f"{len(proc.stdout) // 4}f", proc.stdout)
    if not samples:
        return []

    chunk = max(1, len(samples) // bars)
    peaks: List[float] = []
    for i in range(bars):
        start = i * chunk
        end = min(len(samples), start + chunk)
        if start >= len(samples):
            peaks.append(0.0)
            continue
        block = samples[start:end]
        peak = max(abs(v) for v in block)
        peaks.append(float(peak))

    max_peak = max(peaks) if peaks else 0.0
    if max_peak <= 1e-9:
        return [0.15] * len(peaks)

    return [max(0.08, min(1.0, p / max_peak)) for p in peaks]
