"""TTS 工具函数。"""

from __future__ import annotations

import os
import re


def get_timeline_timing_mode() -> str:
    return os.getenv("TIMELINE_TIMING_MODE", "tts_driven").strip().lower() or "tts_driven"


def count_speech_chars(text: str) -> int:
    if not text:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(re.findall(r"[a-zA-Z0-9]", text))
    return max(1, cjk + max(1, other // 2) if other else 0)


def estimate_duration_from_text(text: str, chars_per_sec: float | None = None) -> float:
    cps = chars_per_sec
    if cps is None:
        lo = float(os.getenv("TTS_CHARS_PER_SEC_MIN", "4"))
        hi = float(os.getenv("TTS_CHARS_PER_SEC_MAX", "6"))
        cps = (lo + hi) / 2.0
    chars = count_speech_chars(text)
    return round(max(0.35, chars / max(cps, 0.5)), 3)
