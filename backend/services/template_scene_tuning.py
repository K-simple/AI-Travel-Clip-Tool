"""旅游混剪模板镜头切分：预设档位 + 样片自动校准。"""

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from scenedetect import ContentDetector, detect


TEMPLATE_SCENE_PROFILES: dict[str, dict[str, Any]] = {
    # 卡点极快、0.5–1.5s 一镜（抖音爆款混剪）
    "travel_ultra": {
        "label": "极快卡点",
        "description": "0.5–1.5 秒/镜，适合高密度卡点旅拍",
        "threshold": 20.0,
        "min_shot_duration": 0.12,
        "max_segments": 120,
        "target_avg_shot_sec": 1.0,
        "min_avg_shot_sec": 0.35,
        "max_avg_shot_sec": 2.2,
        "ai_split_min_duration": 0.9,
        "ai_max_boundary_checks": 100,
        "calibration_candidates": [14, 18, 22, 26, 30],
    },
    # 快切旅拍，1–2.5s 一镜（最常见混剪）
    "travel_fast": {
        "label": "快切混剪",
        "description": "1–2.5 秒/镜，旅游 Vlog 快剪默认推荐",
        "threshold": 24.0,
        "min_shot_duration": 0.18,
        "max_segments": 100,
        "target_avg_shot_sec": 1.6,
        "min_avg_shot_sec": 0.5,
        "max_avg_shot_sec": 3.5,
        "ai_split_min_duration": 1.4,
        "ai_max_boundary_checks": 80,
        "calibration_candidates": [18, 22, 26, 30, 34],
    },
    # 均衡：兼顾闪白转场与真实切镜
    "travel_normal": {
        "label": "标准混剪",
        "description": "1.5–3 秒/镜，默认档位，误切较少",
        "threshold": 27.0,
        "min_shot_duration": 0.25,
        "max_segments": 80,
        "target_avg_shot_sec": 2.0,
        "min_avg_shot_sec": 0.7,
        "max_avg_shot_sec": 4.5,
        "ai_split_min_duration": 2.0,
        "ai_max_boundary_checks": 60,
        "calibration_candidates": [22, 26, 30, 34, 38],
    },
    # 慢节奏、风景长镜头
    "travel_slow": {
        "label": "慢镜氛围",
        "description": "3–6 秒/镜，适合风光/治愈系",
        "threshold": 32.0,
        "min_shot_duration": 0.45,
        "max_segments": 50,
        "target_avg_shot_sec": 3.5,
        "min_avg_shot_sec": 1.5,
        "max_avg_shot_sec": 8.0,
        "ai_split_min_duration": 3.0,
        "ai_max_boundary_checks": 40,
        "calibration_candidates": [28, 32, 36, 40, 44],
    },
}


@dataclass
class TemplateSceneTuning:
    profile: str = "travel_normal"
    threshold: float = 27.0
    min_shot_duration: float = 0.25
    max_segments: int = 80
    target_avg_shot_sec: float = 2.0
    min_avg_shot_sec: float = 0.7
    max_avg_shot_sec: float = 4.5
    ai_split_min_duration: float = 2.0
    ai_max_boundary_checks: int = 60
    auto_tune: bool = True
    calibration_candidates: list[float] = field(default_factory=lambda: [22.0, 26.0, 30.0, 34.0, 38.0])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_scene_profiles() -> list[dict[str, Any]]:
    items = []
    for key, cfg in TEMPLATE_SCENE_PROFILES.items():
        items.append(
            {
                "id": key,
                "label": cfg["label"],
                "description": cfg["description"],
                "threshold": cfg["threshold"],
                "min_shot_duration": cfg["min_shot_duration"],
                "ai_split_min_duration": cfg["ai_split_min_duration"],
            }
        )
    return items


def _profile(name: str) -> dict[str, Any]:
    return TEMPLATE_SCENE_PROFILES.get(name, TEMPLATE_SCENE_PROFILES["travel_normal"])


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return float(raw)


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return int(raw)


def get_template_tuning(override: dict[str, Any] | None = None) -> TemplateSceneTuning:
    """读取环境变量 + 档位预设，可被 override / scene_tuning.json 覆盖。"""
    profile_name = os.getenv("TEMPLATE_SCENE_PROFILE", "travel_fast")
    if override and override.get("profile"):
        profile_name = str(override["profile"])
    base = _profile(profile_name)

    tuning = TemplateSceneTuning(
        profile=profile_name,
        threshold=_env_float("TEMPLATE_SCENE_THRESHOLD", float(base["threshold"])),
        min_shot_duration=_env_float("MIN_TEMPLATE_SHOT_DURATION", float(base["min_shot_duration"])),
        max_segments=_env_int("MAX_TEMPLATE_SEGMENTS", int(base["max_segments"])),
        target_avg_shot_sec=float(base["target_avg_shot_sec"]),
        min_avg_shot_sec=float(base["min_avg_shot_sec"]),
        max_avg_shot_sec=float(base["max_avg_shot_sec"]),
        ai_split_min_duration=_env_float("AI_SHOT_SPLIT_MIN_DURATION", float(base["ai_split_min_duration"])),
        ai_max_boundary_checks=_env_int("AI_SHOT_MAX_BOUNDARY_CHECKS", int(base["ai_max_boundary_checks"])),
        auto_tune=_env_bool("TEMPLATE_SCENE_AUTO_TUNE", True),
        calibration_candidates=[float(x) for x in base.get("calibration_candidates", [])],
    )

    if override:
        for key in (
            "threshold",
            "min_shot_duration",
            "max_segments",
            "target_avg_shot_sec",
            "ai_split_min_duration",
            "ai_max_boundary_checks",
            "auto_tune",
        ):
            if key in override and override[key] is not None:
                setattr(tuning, key, override[key])

    return tuning


def scene_tuning_path_for_template(file_path: str) -> str:
    return os.path.join(os.path.dirname(file_path), "scene_tuning.json")


def load_persisted_tuning(file_path: str) -> dict[str, Any] | None:
    path = scene_tuning_path_for_template(file_path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_persisted_tuning(file_path: str, tuning: TemplateSceneTuning, *, calibration: dict[str, Any] | None = None) -> str:
    path = scene_tuning_path_for_template(file_path)
    payload = tuning.to_dict()
    payload["updated_at"] = time.time()
    if calibration:
        payload["calibration"] = calibration
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def resolve_tuning_for_template(file_path: str, override: dict[str, Any] | None = None) -> TemplateSceneTuning:
    persisted = load_persisted_tuning(file_path)
    merged: dict[str, Any] = {}
    if persisted:
        merged.update(persisted)
    if override:
        merged.update(override)
    return get_template_tuning(merged if merged else None)


def _probe_scene_stats(
    video_path: str,
    threshold: float,
    min_duration: float,
) -> tuple[int, float]:
    """快速探测：给定阈值下的有效镜头数与平均时长。"""
    try:
        scenes = detect(video_path, ContentDetector(threshold=threshold))
    except Exception:
        return 0, 0.0

    if not scenes:
        return 0, 0.0

    total = 0.0
    count = 0
    for start, end in scenes:
        dur = end.get_seconds() - start.get_seconds()
        if dur >= min_duration:
            count += 1
            total += dur

    if count <= 0:
        return 0, 0.0
    return count, total / count


def _calibration_score(count: int, avg_shot: float, tuning: TemplateSceneTuning) -> float:
    if count <= 0 or avg_shot <= 0:
        return 999.0
    score = abs(avg_shot - tuning.target_avg_shot_sec)
    if avg_shot < tuning.min_avg_shot_sec:
        score += (tuning.min_avg_shot_sec - avg_shot) * 2.5
    if avg_shot > tuning.max_avg_shot_sec:
        score += (avg_shot - tuning.max_avg_shot_sec) * 2.5
    if count > tuning.max_segments:
        score += 8.0 + (count - tuning.max_segments) * 0.05
    return score


def calibrate_template_scenes(
    video_path: str,
    duration: float,
    tuning: TemplateSceneTuning | None = None,
) -> dict[str, Any]:
    """
    对样片在多个 threshold 上探测，选出最接近目标镜长的阈值。
    PySceneDetect：threshold 越低 → 切分越多（越敏感）。
    """
    tuning = tuning or get_template_tuning()
    if duration <= 0:
        return {"threshold": tuning.threshold, "segment_count": 0, "avg_shot_sec": 0.0, "candidates": []}

    candidates = tuning.calibration_candidates or [tuning.threshold]
    seen: set[float] = set()
    unique_candidates: list[float] = []
    for th in [tuning.threshold, *candidates]:
        th = round(float(th), 1)
        if th not in seen:
            seen.add(th)
            unique_candidates.append(th)

    results: list[dict[str, Any]] = []
    best_threshold = tuning.threshold
    best_score = 999.0
    best_count = 0
    best_avg = 0.0

    for th in sorted(unique_candidates):
        count, avg = _probe_scene_stats(video_path, th, tuning.min_shot_duration)
        score = _calibration_score(count, avg, tuning)
        item = {
            "threshold": th,
            "segment_count": count,
            "avg_shot_sec": round(avg, 3),
            "score": round(score, 3),
        }
        results.append(item)
        if score < best_score:
            best_score = score
            best_threshold = th
            best_count = count
            best_avg = avg

    return {
        "profile": tuning.profile,
        "threshold": best_threshold,
        "segment_count": best_count,
        "avg_shot_sec": round(best_avg, 3),
        "score": round(best_score, 3),
        "duration_sec": round(duration, 3),
        "candidates": results,
        "applied_params": {
            "min_shot_duration": tuning.min_shot_duration,
            "ai_split_min_duration": tuning.ai_split_min_duration,
            "ai_max_boundary_checks": tuning.ai_max_boundary_checks,
            "max_segments": tuning.max_segments,
        },
    }
