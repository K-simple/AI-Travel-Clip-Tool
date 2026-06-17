"""代理工作流 — 多档预览代理（清晰 / 流畅 / 低清）。"""

import json
import os
import subprocess
from typing import Callable, Dict, Optional

from services.video_exporter import file_ok, run_cmd

PREVIEW_TIER_ORDER = ("low", "smooth", "clear")
PREVIEW_TIER_SPECS: Dict[str, tuple[int, int, bool]] = {
    # tier -> (max_height, crf, force_reencode)
    "clear": (1080, 24, False),
    "smooth": (720, 28, True),
    "low": (480, 32, True),
}


def _source_height(source_path: str) -> int:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=height",
        "-of",
        "json",
        source_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        if streams:
            return int(streams[0].get("height") or 0)
    except Exception:
        pass
    return 0


def detect_nvenc_available() -> bool:
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "h264_nvenc" in r.stdout
    except Exception:
        return False


def pick_video_codec(prefer_nvenc: bool = True, resolution: str = "1080x1920") -> str:
    if prefer_nvenc and detect_nvenc_available():
        return "h264_nvenc"
    return "libx264"


def generate_proxy(
    source_path: str,
    output_path: str,
    height: int = 720,
    crf: int = 28,
    *,
    force_reencode: bool = False,
    min_source_height: int = 0,
) -> Optional[str]:
    """
    生成单档代理。
    - min_source_height>0 且源片更矮时跳过（清晰档仅对 >1080 源生成）
    - force_reencode=True 时即使同分辨率也重编码以减小体积（流畅/低清档）
    """
    if not source_path or not os.path.exists(source_path):
        return None

    src_h = _source_height(source_path)
    if src_h <= 0:
        return None
    if min_source_height > 0 and src_h <= min_source_height:
        return None

    if not force_reencode and src_h <= height:
        return source_path

    target_h = min(height, src_h)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    use_nvenc = detect_nvenc_available()
    cmd = ["ffmpeg", "-y", "-i", source_path, "-vf", f"scale=-2:{target_h}"]
    if use_nvenc:
        cmd += ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", str(crf)]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]
    cmd += [
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        output_path,
    ]
    try:
        run_cmd(cmd)
        return output_path if file_ok(output_path) else None
    except Exception as exc:
        print(f"代理生成失败: {exc}")
        return None


def generate_preview_proxies(
    source_path: str,
    output_dir: str,
    base_name: str,
    on_tier_ready: Optional[Callable[[str, str], None]] = None,
    *,
    tiers: tuple[str, ...] | None = None,
) -> Dict[str, str]:
    """按 low → smooth → clear 顺序生成预览代理，便于尽快可播低清档。"""
    result: Dict[str, str] = {"clear": "", "smooth": "", "low": ""}
    if not source_path or not os.path.exists(source_path):
        return result

    os.makedirs(output_dir, exist_ok=True)
    src_h = _source_height(source_path)
    tier_order = tiers or PREVIEW_TIER_ORDER

    for tier in tier_order:
        max_h, crf, force = PREVIEW_TIER_SPECS[tier]
        min_src = 1080 if tier == "clear" else 0
        if tier == "clear" and src_h > 0 and src_h <= 1080:
            continue

        out_path = os.path.join(output_dir, f"{base_name}_{tier}.mp4")
        path = generate_proxy(
            source_path,
            out_path,
            height=max_h,
            crf=crf,
            force_reencode=force,
            min_source_height=min_src,
        )
        if path and path != source_path and os.path.isfile(path):
            normalized = path.replace("\\", "/")
            result[tier] = normalized
            if on_tier_ready:
                on_tier_ready(tier, normalized)

    return result


def normalize_proxy_paths(raw: Optional[dict]) -> Dict[str, str]:
    if not raw or not isinstance(raw, dict):
        return {"clear": "", "smooth": "", "low": ""}
    return {
        "clear": str(raw.get("clear") or ""),
        "smooth": str(raw.get("smooth") or ""),
        "low": str(raw.get("low") or ""),
    }
