"""低配置设备 worker 上限与硬件探测（目标：千元机浏览 + ~3000 元档 PC）。"""

from __future__ import annotations

import os


def cpu_count() -> int:
    return max(1, os.cpu_count() or 4)


def clamp_workers(requested: int, *, floor: int = 1, reserve_cores: int = 1) -> int:
    """为系统/UI/ffmpeg 主线程保留核心，避免低配机卡死。"""
    try:
        req = int(requested)
    except (TypeError, ValueError):
        req = floor
    cap = max(floor, cpu_count() - max(0, reserve_cores))
    return max(floor, min(req, cap))


def is_budget_target() -> bool:
    preset = os.getenv("PROCESSING_PRESET", "budget").strip().lower()
    return preset in ("budget", "dev")


def profile_summary() -> dict[str, int | str | bool]:
    preset = os.getenv("PROCESSING_PRESET", "budget").strip().lower()
    return {
        "preset": preset,
        "cpu_count": cpu_count(),
        "budget_target": preset in ("budget", "dev"),
    }
