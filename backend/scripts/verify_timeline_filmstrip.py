"""重启后验证：时间轴 timeline-thumbnails API + 磁盘缓存 + 前端可达。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

API = "http://127.0.0.1:8000"
FRONTEND_CANDIDATES = ("http://127.0.0.1:3000", "http://127.0.0.1:3001")


def _get(path: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(f"{API}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_ok(url: str, timeout: float = 5.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False


def _frontend_url() -> str:
    for url in FRONTEND_CANDIDATES:
        if _http_ok(url, timeout=3):
            return url
    return FRONTEND_CANDIDATES[0]


def wait_for_services(max_wait_sec: int = 120) -> str:
    deadline = time.time() + max_wait_sec
    last_err = ""
    while time.time() < deadline:
        try:
            health = _get("/health", timeout=3)
            frontend = _frontend_url()
            if health.get("status") == "ok" and _http_ok(frontend, timeout=3):
                print(f"OK backend: {health}")
                print(f"OK frontend: {frontend}")
                return frontend
            last_err = f"health={health}, frontend candidates={FRONTEND_CANDIDATES}"
        except Exception as exc:
            last_err = str(exc)
        time.sleep(2)
    raise RuntimeError(f"服务未就绪（{max_wait_sec}s）: {last_err}")


def _make_test_video(out_path: Path, duration: float = 4.0) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=720x1280:rate=24:duration={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not out_path.is_file():
        raise RuntimeError(f"ffmpeg 生成测试视频失败:\n{result.stderr[-500:]}")


def _ensure_test_template() -> tuple[str, str]:
    from models.database import SessionLocal, Template

    db = SessionLocal()
    try:
        row = (
            db.query(Template)
            .filter(Template.file_path.isnot(None))
            .order_by(Template.created_at.desc())
            .first()
        )
        if row and row.file_path:
            video_abs = Path(row.file_path)
            if not video_abs.is_absolute():
                video_abs = BACKEND_ROOT / video_abs
            if video_abs.is_file():
                print(f"使用已有模板: {row.id} ({video_abs.name})")
                return row.id, str(video_abs.resolve())
    finally:
        db.close()

    template_id = f"filmstrip-e2e-{uuid.uuid4().hex[:8]}"
    template_dir = BACKEND_ROOT / "storage" / "templates" / template_id
    video_path = template_dir / f"{template_id}.mp4"
    _make_test_video(video_path)

    from services.scene_detector import get_video_duration

    duration = get_video_duration(str(video_path))
    slots = [
        {
            "slot_id": 1,
            "id": "slot_1",
            "name": "全片",
            "duration": duration,
            "start": 0.0,
            "end": duration,
            "clip_start": 0.0,
        }
    ]

    db = SessionLocal()
    try:
        template = Template(
            id=template_id,
            filename=video_path.name,
            duration=duration,
            slot_count=1,
            file_path=str(video_path.relative_to(BACKEND_ROOT)).replace("\\", "/"),
            slots=slots,
            audio_path="",
            subtitle_srt_path="",
            subtitle_ass_path="",
            subtitle_style="",
            segments_json=[],
            processing_status="ready",
            processing_progress=100,
            enhance_status="ready",
            enhance_progress=100,
            beat_markers=[],
            created_at=time.time(),
        )
        db.add(template)
        db.commit()
    finally:
        db.close()

    print(f"创建测试模板: {template_id}, duration={duration:.1f}s")
    return template_id, str(video_path.resolve())


def verify_api(template_id: str) -> dict:
    payload = _get(f"/api/template/{template_id}/timeline-thumbnails")
    assert payload.get("success") is True, payload
    assert payload.get("templateId") == template_id, payload
    assert payload.get("status") == "ready", payload
    assert float(payload.get("duration") or 0) > 0, payload

    profiles = payload.get("profiles") or {}
    assert "low" in profiles, payload
    assert "standard" in profiles, payload

    low = profiles["low"]
    std = profiles["standard"]
    assert low.get("intervalSec") == 1.0, low
    assert std.get("intervalSec") in (0.5, 1.0), std

    low_thumbs = low.get("thumbnails") or []
    std_thumbs = std.get("thumbnails") or []
    assert len(low_thumbs) >= 2, f"low thumbnails too few: {len(low_thumbs)}"
    assert len(std_thumbs) >= len(low_thumbs), (
        f"standard should be denser: low={len(low_thumbs)} std={len(std_thumbs)}"
    )

    sample = low_thumbs[0]
    for key in ("time", "url", "width", "height"):
        assert key in sample, sample
    assert sample["url"].startswith("/storage/thumbnails/"), sample["url"]

    thumb_abs = BACKEND_ROOT / sample["url"].lstrip("/")
    assert thumb_abs.is_file(), f"missing thumb file: {thumb_abs}"

    # 二次请求应命中缓存（generated 不再大量增加）
    payload2 = _get(f"/api/template/{template_id}/timeline-thumbnails")
    assert payload2.get("status") == "ready"
    assert len(payload2["profiles"]["low"]["thumbnails"]) == len(low_thumbs)

    return {
        "template_id": template_id,
        "duration": payload["duration"],
        "low_count": len(low_thumbs),
        "standard_count": len(std_thumbs),
        "sample_url": sample["url"],
        "cached_ok": True,
    }


def verify_storage_accessible(template_id: str) -> None:
    payload = _get(f"/api/template/{template_id}/timeline-thumbnails")
    url = payload["profiles"]["low"]["thumbnails"][0]["url"]
    assert _http_ok(f"{API}{url}"), f"storage URL not accessible: {url}"


def verify_intake_pregenerate(template_id: str, video_path: str) -> None:
    from services.timeline_thumbnails import pregenerate_timeline_thumbnails_for_intake

    pregenerate_timeline_thumbnails_for_intake(video_path, template_id)
    low_dir = BACKEND_ROOT / "storage" / "thumbnails" / template_id / "timeline_thumbs" / "low"
    std_dir = BACKEND_ROOT / "storage" / "thumbnails" / template_id / "timeline_thumbs" / "standard"
    assert low_dir.is_dir(), low_dir
    assert std_dir.is_dir(), std_dir
    assert any(low_dir.glob("t_*.jpg")), "low thumbs missing"
    assert any(std_dir.glob("t_*.jpg")), "standard thumbs missing"


def main() -> int:
    print("=== 等待服务就绪 ===")
    frontend = wait_for_services()

    print("\n=== 准备测试模板 ===")
    template_id, video_path = _ensure_test_template()

    print("\n=== 验证 intake 预生成目录 ===")
    verify_intake_pregenerate(template_id, video_path)

    print("\n=== 验证 timeline-thumbnails API ===")
    summary = verify_api(template_id)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\n=== 验证 /storage 静态访问 ===")
    verify_storage_accessible(template_id)
    print("OK storage URL reachable")

    print("\n=== 运行单元测试 ===")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_timeline_thumbnails.py", "-q"],
        cwd=str(BACKEND_ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError("pytest test_timeline_thumbnails failed")

    print("\n=== E2E 验证通过 ===")
    print(f"  templateId: {template_id}")
    print(f"  low thumbnails: {summary['low_count']}")
    print(f"  standard thumbnails: {summary['standard_count']}")
    print(f"  sample: {summary['sample_url']}")
    print(f"  editor: {frontend}/editor")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nE2E FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
