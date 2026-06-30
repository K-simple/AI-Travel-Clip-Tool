"""时间轴导轨缩略帧：按固定间隔 ffmpeg 抽帧，磁盘缓存供前端 filmstrip 渲染。"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Literal

TimelineThumbQuality = Literal["low", "standard", "high"]

QUALITY_PRESETS: dict[TimelineThumbQuality, dict[str, int | float]] = {
    "low": {"interval_sec": 1.0, "width": 80, "max_frames": 120},
    "standard": {"interval_sec": 0.5, "width": 120, "max_frames": 240},
    "high": {"interval_sec": 0.25, "width": 160, "max_frames": 480},
}


def get_video_duration(video_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return 0.0
    try:
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0.0


def _thumb_rel_url(template_id: str, quality: str, filename: str) -> str:
    return f"/storage/thumbnails/{template_id}/timeline_thumbs/{quality}/{filename}"


def _thumb_dir(template_id: str, quality: str) -> str:
    return os.path.join("storage", "thumbnails", template_id, "timeline_thumbs", quality).replace(
        "\\", "/"
    )


def _manifest_path(out_dir: str) -> str:
    return os.path.join(out_dir, "manifest.json").replace("\\", "/")


def _time_to_filename(time_sec: float) -> str:
    ms = int(round(max(0.0, time_sec) * 1000))
    return f"t_{ms:06d}.jpg"


def _probe_video_size(video_path: str) -> tuple[int, int]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return 720, 1280
    try:
        info = json.loads(result.stdout)
        stream = (info.get("streams") or [{}])[0]
        w = int(stream.get("width") or 720)
        h = int(stream.get("height") or 1280)
        return max(1, w), max(1, h)
    except (TypeError, ValueError, json.JSONDecodeError):
        return 720, 1280


def _scaled_height(target_width: int, video_w: int, video_h: int) -> int:
    return max(1, int(round(target_width * video_h / video_w)))


def _compute_sampling(duration: float, interval_sec: float, max_frames: int) -> tuple[float, int]:
    if duration <= 0:
        return interval_sec, 0
    raw_count = int(duration / interval_sec) + 1
    if raw_count <= max_frames:
        return interval_sec, raw_count
    if max_frames <= 1:
        return duration, 1
    effective = duration / (max_frames - 1)
    return effective, max_frames


def _frame_times(duration: float, interval_sec: float, frame_count: int) -> list[float]:
    if frame_count <= 0:
        return []
    if frame_count == 1:
        return [0.0]
    times: list[float] = []
    for i in range(frame_count):
        t = min(duration, i * interval_sec)
        times.append(round(t, 3))
    return times


def _load_manifest(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _manifest_valid(
    manifest: dict[str, Any] | None,
    *,
    video_mtime: float,
    duration: float,
    interval_sec: float,
    width: int,
    quality: str,
) -> bool:
    if not manifest:
        return False
    if manifest.get("quality") != quality:
        return False
    if abs(float(manifest.get("video_mtime", -1)) - video_mtime) > 0.5:
        return False
    if abs(float(manifest.get("duration", -1)) - duration) > 0.05:
        return False
    if abs(float(manifest.get("interval_sec", -1)) - interval_sec) > 0.001:
        return False
    if int(manifest.get("width", -1)) != width:
        return False
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        return False
    return True


def _build_frame_entries(
    template_id: str,
    quality: str,
    times: list[float],
    width: int,
    height: int,
    out_dir: str,
) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for t in times:
        filename = _time_to_filename(t)
        rel_url = _thumb_rel_url(template_id, quality, filename)
        abs_path = os.path.join(out_dir, filename).replace("\\", "/")
        if not os.path.isfile(abs_path):
            continue
        frames.append(
            {
                "time": t,
                "url": rel_url,
                "width": width,
                "height": height,
            }
        )
    return frames


def _extract_frames_batch(
    video_path: str,
    out_dir: str,
    times: list[float],
    width: int,
) -> tuple[int, int]:
    """批量抽帧；返回 (generated, cached)。"""
    generated = 0
    cached = 0
    missing: list[tuple[float, str]] = []

    for t in times:
        filename = _time_to_filename(t)
        abs_path = os.path.join(out_dir, filename).replace("\\", "/")
        if os.path.isfile(abs_path):
            cached += 1
        else:
            missing.append((t, abs_path))

    if not missing:
        return generated, cached

    for t, abs_path in missing:
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{t:.3f}",
            "-i",
            video_path,
            "-vframes",
            "1",
            "-q:v",
            "5",
            "-vf",
            f"scale={width}:-2",
            abs_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and os.path.isfile(abs_path):
            generated += 1
        else:
            print(
                f"[timeline_thumbs] extract failed t={t:.3f} "
                f"{result.stderr[-200:] if result.stderr else ''}"
            )

    return generated, cached


def generate_timeline_thumbnails(
    video_path: str,
    template_id: str,
    *,
    quality: TimelineThumbQuality = "standard",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    生成或读取缓存的时间轴缩略帧列表。

    返回:
      {
        "frames": [{time, url, width, height}, ...],
        "duration": float,
        "interval_sec": float,
        "quality": str,
        "generated": int,
        "cached": int,
      }
    """
    opts = options or {}
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["standard"])
    interval_sec = float(opts.get("interval_sec", preset["interval_sec"]))
    width = int(opts.get("width", preset["width"]))
    max_frames = int(opts.get("max_frames", preset["max_frames"]))

    empty: dict[str, Any] = {
        "frames": [],
        "duration": 0.0,
        "interval_sec": interval_sec,
        "quality": quality,
        "generated": 0,
        "cached": 0,
    }

    if not video_path or not os.path.isfile(video_path):
        return empty

    duration = get_video_duration(video_path)
    if duration <= 0:
        return empty

    video_mtime = os.path.getmtime(video_path)
    effective_interval, frame_count = _compute_sampling(duration, interval_sec, max_frames)
    times = _frame_times(duration, effective_interval, frame_count)
    if not times:
        return {**empty, "duration": duration}

    out_dir = _thumb_dir(template_id, quality)
    os.makedirs(out_dir, exist_ok=True)
    manifest_file = _manifest_path(out_dir)

    manifest = _load_manifest(manifest_file)
    if _manifest_valid(
        manifest,
        video_mtime=video_mtime,
        duration=duration,
        interval_sec=effective_interval,
        width=width,
        quality=quality,
    ):
        frames = manifest.get("frames") if manifest else []
        if isinstance(frames, list) and frames:
            print(
                f"[timeline_thumbs] template={template_id} duration={duration:.1f} "
                f"interval={effective_interval} width={width}"
            )
            print(f"[timeline_thumbs] generated=0 cached={len(frames)}")
            return {
                "frames": frames,
                "duration": duration,
                "interval_sec": effective_interval,
                "quality": quality,
                "generated": 0,
                "cached": len(frames),
            }

    print(
        f"[timeline_thumbs] template={template_id} duration={duration:.1f} "
        f"interval={effective_interval} width={width}"
    )

    video_w, video_h = _probe_video_size(video_path)
    height = _scaled_height(width, video_w, video_h)

    generated, cached = _extract_frames_batch(video_path, out_dir, times, width)
    frames = _build_frame_entries(template_id, quality, times, width, height, out_dir)

    manifest_payload = {
        "template_id": template_id,
        "quality": quality,
        "video_mtime": video_mtime,
        "duration": duration,
        "interval_sec": effective_interval,
        "width": width,
        "height": height,
        "frames": frames,
    }
    try:
        with open(manifest_file, "w", encoding="utf-8") as fh:
            json.dump(manifest_payload, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"[timeline_thumbs] manifest write failed: {exc}")

    print(f"[timeline_thumbs] generated={generated} cached={cached}")

    return {
        "frames": frames,
        "duration": duration,
        "interval_sec": effective_interval,
        "quality": quality,
        "generated": generated,
        "cached": cached,
    }


def _load_cached_profile(
    video_path: str,
    template_id: str,
    quality: TimelineThumbQuality,
) -> dict[str, Any] | None:
    """仅读磁盘缓存，不触发 ffmpeg。"""
    if not video_path or not os.path.isfile(video_path):
        return None

    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["standard"])
    interval_sec = float(preset["interval_sec"])
    width = int(preset["width"])
    max_frames = int(preset["max_frames"])

    duration = get_video_duration(video_path)
    if duration <= 0:
        return None

    video_mtime = os.path.getmtime(video_path)
    effective_interval, _frame_count = _compute_sampling(duration, interval_sec, max_frames)
    out_dir = _thumb_dir(template_id, quality)
    manifest = _load_manifest(_manifest_path(out_dir))
    if not _manifest_valid(
        manifest,
        video_mtime=video_mtime,
        duration=duration,
        interval_sec=effective_interval,
        width=width,
        quality=quality,
    ):
        return None

    frames = manifest.get("frames") if manifest else []
    if not isinstance(frames, list) or not frames:
        return None

    return {
        "intervalSec": effective_interval,
        "thumbnails": frames,
    }


def pregenerate_timeline_thumbnails_for_intake(video_path: str, template_id: str) -> None:
    """模板 intake 完成后预生成 low/standard 预览帧（不参与切槽）。"""
    for quality in ("low", "standard"):
        try:
            generate_timeline_thumbnails(video_path, template_id, quality=quality)
        except Exception as exc:
            print(f"[timeline_thumbs] intake pregenerate {quality} failed: {exc}")


def get_timeline_thumbnail_profiles(
    video_path: str,
    template_id: str,
    *,
    generate_missing: bool = True,
    include_high: bool = False,
) -> dict[str, Any]:
    """
    返回多档位时间轴缩略图；缺失时同步生成 low/standard。
    """
    empty: dict[str, Any] = {
        "templateId": template_id,
        "duration": 0.0,
        "status": "processing",
        "profiles": {},
    }

    if not video_path or not os.path.isfile(video_path):
        return empty

    duration = get_video_duration(video_path)
    if duration <= 0:
        return {**empty, "duration": 0.0}

    profiles: dict[str, dict[str, Any]] = {}
    sync_qualities: tuple[TimelineThumbQuality, ...] = ("low", "standard")
    if include_high:
        sync_qualities = ("low", "standard", "high")

    for quality in sync_qualities:
        if generate_missing:
            result = generate_timeline_thumbnails(video_path, template_id, quality=quality)
            if result["frames"]:
                profiles[quality] = {
                    "intervalSec": result["interval_sec"],
                    "thumbnails": result["frames"],
                }
        else:
            cached = _load_cached_profile(video_path, template_id, quality)
            if cached:
                profiles[quality] = cached

    # 若 low 仍缺失，尝试强制同步生成
    if "low" not in profiles and generate_missing:
        result = generate_timeline_thumbnails(video_path, template_id, quality="low")
        if result["frames"]:
            profiles["low"] = {
                "intervalSec": result["interval_sec"],
                "thumbnails": result["frames"],
            }

    # high 仅返回已缓存（按需生成）
    if include_high and "high" not in profiles:
        cached_high = _load_cached_profile(video_path, template_id, "high")
        if cached_high:
            profiles["high"] = cached_high
        elif generate_missing:
            result = generate_timeline_thumbnails(video_path, template_id, quality="high")
            if result["frames"]:
                profiles["high"] = {
                    "intervalSec": result["interval_sec"],
                    "thumbnails": result["frames"],
                }
    elif not include_high:
        cached_high = _load_cached_profile(video_path, template_id, "high")
        if cached_high:
            profiles["high"] = cached_high

    has_low = bool(profiles.get("low", {}).get("thumbnails"))
    status = "ready" if has_low else "processing"

    return {
        "templateId": template_id,
        "duration": duration,
        "status": status,
        "profiles": profiles,
    }
