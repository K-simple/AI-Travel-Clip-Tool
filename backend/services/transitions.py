"""100+ 转场预设目录与 FFmpeg xfade 映射。"""

import json
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "transitions_catalog.json")

# FFmpeg xfade 支持的转场名（扩展生成变体至 100+）
_XFADE_BASE = [
    "fade", "fadeblack", "fadewhite", "fadegrays", "dissolve",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "slideup", "slidedown",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "circlecrop", "circleopen", "circleclose", "rectcrop",
    "hblur", "pixelize", "diagtl", "diagtr", "diagbl", "diagbr",
    "hlslice", "hrslice", "vuslice", "vdslice", "distance",
    "squeezeh", "squeezev", "zoomin", "horzopen", "horzclose",
    "vertopen", "vertclose",
]


def _expand_presets() -> List[Dict[str, Any]]:
    presets: List[Dict[str, Any]] = []
    if os.path.exists(_CATALOG_PATH):
        with open(_CATALOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            presets.extend(data.get("presets", []))

    durations = [0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
    idx = len(presets)
    for name in _XFADE_BASE:
        for dur in durations:
            if idx >= 120:
                break
            pid = f"{name}_{int(dur * 10)}"
            if any(p["id"] == pid for p in presets):
                continue
            presets.append({
                "id": pid,
                "name": f"{name} {dur}s",
                "ffmpeg": name,
                "duration": dur,
                "category": "扩展",
            })
            idx += 1
    return presets[:120]


@lru_cache(maxsize=1)
def get_all_transitions() -> List[Dict[str, Any]]:
    return _expand_presets()


def resolve_transition(transition: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not transition:
        return {"ffmpeg": "fade", "duration": 0.3}
    tid = transition.get("type") or transition.get("id") or "fade"
    for p in get_all_transitions():
        if p["id"] == tid:
            return {
                "ffmpeg": p["ffmpeg"],
                "duration": float(transition.get("duration", p["duration"])),
            }
    return {
        "ffmpeg": tid if tid in _XFADE_BASE else "fade",
        "duration": float(transition.get("duration", 0.3)),
    }
