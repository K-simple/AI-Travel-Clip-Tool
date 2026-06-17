"""将时间轴片段切为独立视频文件（非图片）。"""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from services.processing_config import SEGMENT_CUT_WORKERS
from services.video_exporter import file_ok, run_cmd


def extract_segment_video(
    source_path: str,
    start_sec: float,
    end_sec: float,
    output_path: str,
) -> bool:
    """从原片切出 [start, end) 视频片段。"""
    if not source_path or not os.path.exists(source_path):
        return False

    duration = max(0.1, float(end_sec) - float(start_sec))
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 先尝试流复制（快），失败则重编码
    for mode in ("copy", "encode"):
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(max(0, start_sec)),
            "-i", source_path,
            "-t", str(duration),
        ]
        if mode == "copy":
            cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        else:
            cmd += [
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
            ]
        cmd += ["-movflags", "+faststart", output_path]

        try:
            run_cmd(cmd)
            if file_ok(output_path):
                return True
        except Exception as exc:
            print(f"片段切割失败 ({mode}): {exc}")

    return False


def attach_segment_videos(
    video_path: str,
    asset_id: str,
    segments: list,
) -> list:
    """为每个分段生成独立 mp4，并写入 segment_file_path。"""
    seg_dir = os.path.join("storage", "assets", asset_id, "segments")
    os.makedirs(seg_dir, exist_ok=True)

    def _cut_one(item: tuple[int, dict]) -> dict:
        i, seg = item
        start = float(seg.get("start", 0))
        end = float(seg.get("end", start + float(seg.get("duration", 0))))
        seg_id = seg.get("segment_id") or f"seg_{i + 1}"
        out_path = os.path.join(seg_dir, f"{seg_id}.mp4")
        ok = extract_segment_video(video_path, start, end, out_path)
        return {
            **seg,
            "segment_id": seg_id,
            "type": "video",
            "asset_id": asset_id,
            "file_path": video_path,
            "segment_file_path": out_path if ok else "",
            "clip_start": 0.0 if ok else start,
            "clip_end": end - start if ok else end,
        }

    enriched: list[dict] = [None] * len(segments)  # type: ignore
    workers = min(SEGMENT_CUT_WORKERS, max(1, len(segments)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_cut_one, (i, seg)): i for i, seg in enumerate(segments)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            enriched[idx] = fut.result()

    ok_count = sum(1 for s in enriched if s.get("segment_file_path"))
    print(f"视频片段导出: {asset_id} -> {ok_count}/{len(enriched)}")
    return enriched
