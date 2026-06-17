import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from scenedetect import ContentDetector, detect

from services.processing_config import (
    FRAME_EXTRACT_WORKERS,
    MAX_SEGMENTS,
    MAX_TEMPLATE_SEGMENTS,
    MIN_TEMPLATE_SHOT_DURATION,
    SCENE_THRESHOLD,
    SKIP_TEMPLATE_SCENE_DETECT,
    TEMPLATE_SCENE_INTERVAL_FALLBACK,
    TEMPLATE_SCENE_THRESHOLD,
    TEMPLATE_SLOT_INTERVAL,
)


def get_video_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-print_format", "json",
        "-show_format",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffprobe 获取时长失败: {video_path}\n{result.stderr}")
        return 0.0
    try:
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"解析视频时长失败: {video_path} ({exc})")
        return 0.0


def extract_frame(video_path: str, time_sec: float, output_path: str) -> str:
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(time_sec),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "4",
        "-vf", "scale=480:-2",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"截帧失败: {video_path} @ {time_sec}s\n{result.stderr}")
    return output_path


def _limit_segments(segments: list, max_count: int, *, merge: bool = True) -> list:
    if len(segments) <= max_count:
        return segments
    if merge:
        return _cap_segments(segments, max_count)
    # 不合并相邻镜头：超限时均匀抽样，尽量保留「一镜一槽」语义
    step = len(segments) / max_count
    picked: list[dict] = []
    for i in range(max_count):
        idx = min(int(round(i * step)), len(segments) - 1)
        seg = dict(segments[idx])
        seg["slot_id"] = i + 1
        seg["segment_id"] = f"seg_{i + 1}"
        picked.append(seg)
    return picked


def _cap_segments(segments: list, max_count: int) -> list:
    if len(segments) <= max_count:
        return segments
    # 合并为等长块，避免片段过多拖慢后续处理
    merged = []
    chunk = max(1, len(segments) // max_count)
    for i in range(0, len(segments), chunk):
        group = segments[i : i + chunk]
        start = float(group[0]["start"])
        end = float(group[-1]["end"])
        merged.append({
            **group[0],
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "segment_id": f"seg_{len(merged) + 1}",
            "slot_id": len(merged) + 1,
        })
    return merged[:max_count]


def _attach_thumbnails(video_path: str, output_dir: str, segments: list) -> list:
    def _one(item: tuple[int, dict]) -> dict:
        i, seg = item
        mid_sec = float(seg["start"]) + float(seg["duration"]) / 2
        thumb_filename = f"slot_{i + 1}_thumb.jpg"
        thumb_path = os.path.join(output_dir, thumb_filename)
        extract_frame(video_path, mid_sec, thumb_path)
        return {
            **seg,
            "thumbnail": thumb_path.replace("\\", "/"),
        }

    workers = min(FRAME_EXTRACT_WORKERS, max(1, len(segments)))
    results: list[dict] = [None] * len(segments)  # type: ignore
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_one, (i, seg)): i for i, seg in enumerate(segments)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            results[idx] = fut.result()
    return results


def detect_scenes(
    video_path: str,
    output_dir: str,
    *,
    extract_thumbs: bool = True,
    max_segments: int | None = None,
    threshold: float | None = None,
    min_duration: float = 0.5,
    merge_when_capped: bool = True,
    allow_interval_fallback: bool | None = None,
) -> list:
    os.makedirs(output_dir, exist_ok=True)

    total_duration = get_video_duration(video_path)
    if total_duration <= 0:
        print(f"无法获取视频时长: {video_path}")
        return []

    detect_threshold = threshold if threshold is not None else SCENE_THRESHOLD
    cap = max_segments if max_segments is not None else MAX_SEGMENTS
    use_interval_fallback = (
        TEMPLATE_SCENE_INTERVAL_FALLBACK if allow_interval_fallback is None else allow_interval_fallback
    )

    def _run_detect(th: float):
        return detect(video_path, ContentDetector(threshold=th))

    try:
        scenes = _run_detect(detect_threshold)
        if len(scenes) == 0 and detect_threshold > 14:
            retry = max(12.0, detect_threshold * 0.72)
            print(f"场景检测无结果，降低 threshold {detect_threshold} -> {retry} 重试")
            scenes = _run_detect(retry)
    except Exception as e:
        print(f"镜头切分失败: {e}")
        scenes = []

    raw: list[dict] = []

    if len(scenes) > 0:
        for i, (start, end) in enumerate(scenes):
            start_sec = start.get_seconds()
            end_sec = end.get_seconds()
            duration = end_sec - start_sec
            if duration < min_duration:
                continue
            raw.append({
                "slot_id": i + 1,
                "segment_id": f"seg_{i + 1}",
                "type": "video",
                "start": round(start_sec, 3),
                "end": round(end_sec, 3),
                "duration": round(duration, 3),
                "thumbnail": "",
                "tags": [],
                "scene_tags": [],
                "shot_type": "wide",
                "has_person": False,
                "quality_score": 0.5,
                "mood": "",
            })
    else:
        if use_interval_fallback:
            interval = 4.0
            slot_id = 1
            current = 0.0
            while current < total_duration:
                end_time = min(current + interval, total_duration)
                duration = end_time - current
                if duration < min_duration:
                    break
                raw.append({
                    "slot_id": slot_id,
                    "segment_id": f"seg_{slot_id}",
                    "type": "video",
                    "start": round(current, 3),
                    "end": round(end_time, 3),
                    "duration": round(duration, 3),
                    "thumbnail": "",
                    "tags": [],
                    "scene_tags": [],
                    "shot_type": "wide",
                    "has_person": False,
                    "quality_score": 0.5,
                    "mood": "",
                })
                current = end_time
                slot_id += 1
        else:
            print(f"场景检测无切点且已禁用等间隔回退: {video_path}")

    # 重新编号，避免过滤短镜头后 slot_id 不连续
    for i, seg in enumerate(raw):
        seg["slot_id"] = i + 1
        seg["segment_id"] = f"seg_{i + 1}"

    raw = _limit_segments(raw, cap, merge=merge_when_capped)

    if extract_thumbs and raw:
        raw = _attach_thumbnails(video_path, output_dir, raw)

    print(f"切分完成: {video_path} -> {len(raw)} 个片段 (threshold={detect_threshold})")
    return raw


def build_interval_segments(
    total_duration: float,
    interval: float = 4.0,
    *,
    video_path: str = "",
    thumb_dir: str = "",
) -> list:
    """按固定间隔快速切分（不做场景检测，适合模板快速就绪）。"""
    if total_duration <= 0:
        return []

    raw: list[dict] = []
    slot_id = 1
    current = 0.0
    step = max(1.0, float(interval))

    while current < total_duration:
        end_time = min(current + step, total_duration)
        duration = end_time - current
        if duration < 0.5:
            break
        raw.append({
            "slot_id": slot_id,
            "segment_id": f"seg_{slot_id}",
            "type": "video",
            "start": round(current, 3),
            "end": round(end_time, 3),
            "duration": round(duration, 3),
            "thumbnail": "",
            "tags": [],
            "scene_tags": [],
            "shot_type": "wide",
            "has_person": False,
            "quality_score": 0.5,
            "mood": "",
        })
        current = end_time
        slot_id += 1

    raw = _limit_segments(raw, MAX_SEGMENTS, merge=True)
    if video_path and thumb_dir and raw:
        raw = _attach_thumbnails(video_path, thumb_dir, raw)
    return raw


def build_template_shot_slots(
    file_path: str,
    thumb_dir: str,
    duration: float,
    *,
    tuning_override: dict | None = None,
    on_progress: Callable[[int], None] | None = None,
    skip_auto_tune: bool = False,
    skip_ai_refine: bool = False,
    extract_thumbs: bool = True,
    allow_interval_fallback: bool | None = None,
) -> list:
    """
    旅游混剪模板槽位：场景检测（一镜一槽）+ 可选自动校准 + AI 修正。
    """
    from services.template_scene_tuning import (
        calibrate_template_scenes,
        resolve_tuning_for_template,
    )

    def bump(progress: int) -> None:
        if on_progress:
            on_progress(progress)

    if duration <= 0:
        return []

    bump(40)
    tuning = resolve_tuning_for_template(file_path, tuning_override)
    threshold = tuning.threshold
    min_duration = tuning.min_shot_duration
    max_segments = tuning.max_segments

    if tuning.auto_tune and not SKIP_TEMPLATE_SCENE_DETECT and not skip_auto_tune:
        cal = calibrate_template_scenes(file_path, duration, tuning)
        threshold = float(cal["threshold"])
        print(
            f"模板镜头校准 [{tuning.profile}]: threshold={threshold} "
            f"≈{cal['segment_count']} 镜, 均长 {cal['avg_shot_sec']}s (score={cal['score']})"
        )

    bump(48)
    if not SKIP_TEMPLATE_SCENE_DETECT:
        slots = detect_scenes(
            file_path,
            thumb_dir,
            max_segments=max_segments,
            threshold=threshold,
            min_duration=min_duration,
            merge_when_capped=False,
            extract_thumbs=extract_thumbs,
            allow_interval_fallback=allow_interval_fallback,
        )
        if slots:
            bump(58)
            if not skip_ai_refine:
                from services.ai_shot_refiner import refine_shots_with_ai

                slots = refine_shots_with_ai(slots, file_path, thumb_dir, tuning=tuning)
                bump(65)
            print(f"模板按镜头切分: {len(slots)} 个画面 (profile={tuning.profile}, threshold={threshold})")
            return slots
        print("模板场景切分无结果，回退等间隔切分")

    if TEMPLATE_SCENE_INTERVAL_FALLBACK if allow_interval_fallback is None else allow_interval_fallback:
        return build_interval_segments(
            duration,
            TEMPLATE_SLOT_INTERVAL,
            video_path=file_path,
            thumb_dir=thumb_dir,
        )
    return []
