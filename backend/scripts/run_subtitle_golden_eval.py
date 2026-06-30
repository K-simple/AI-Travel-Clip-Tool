"""Evaluate subtitle recognition against a golden-set manifest."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# scripts/ -> backend/
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.subtitle_golden_eval import (  # noqa: E402
    case_passed,
    evaluate_case_metrics,
    load_expected,
    resolve_manifest_path,
    slot_text,
)

_DEFAULT_BASELINE = _BACKEND / "storage" / "golden-baseline.json"
_TEMPLATES_ROOT = _BACKEND / "storage" / "templates"


def _load_manifest(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _slot_snapshot(slots: list) -> list[dict]:
    rows: list[dict] = []
    for slot in slots or []:
        if not isinstance(slot, dict):
            continue
        rows.append({
            "slot_id": slot.get("slot_id") or slot.get("id"),
            "subtitle_text": slot_text(slot),
            "subtitle_source": slot.get("subtitle_source"),
            "subtitle_quality": slot.get("subtitle_quality"),
            "clip_start": slot.get("clip_start") or slot.get("start"),
            "clip_end": slot.get("clip_end") or slot.get("end"),
        })
    return rows


def _case_from_video(path: Path) -> dict:
    resolved = path.resolve()
    return {
        "id": resolved.stem,
        "category": "ad_hoc",
        "description": f"Ad-hoc baseline: {resolved.name}",
        "template_video": str(resolved),
        "expected_file": "",
        "min_nonempty_rate": 0.0,
        "record_baseline": True,
    }


def _discover_template_videos() -> list[Path]:
    if not _TEMPLATES_ROOT.is_dir():
        return []
    seen: set[str] = set()
    videos: list[Path] = []
    for path in sorted(_TEMPLATES_ROOT.glob("**/*.mp4")):
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        videos.append(path.resolve())
    return videos


def _collect_ad_hoc_cases(args: argparse.Namespace) -> list[dict]:
    cases: list[dict] = []
    for raw in args.video or []:
        path = Path(raw).expanduser()
        if not path.is_file():
            print(f"WARN: --video not found, skipped: {path}")
            continue
        cases.append(_case_from_video(path))
    if args.discover:
        for path in _discover_template_videos():
            cases.append(_case_from_video(path))
    return cases


def _run_offline_video(video_path: Path, template_id: str | None = None) -> dict:
    """不依赖 HTTP：intake OCR + 后台 fast 字幕批次。"""
    import shutil

    from models.database import SessionLocal, Template
    from services.template_intake import process_template_intake
    from services.template_subtitle_auto import run_auto_subtitle_batch

    if not video_path.is_file():
        return {"skipped": True, "reason": f"video missing: {video_path}"}

    tid = template_id or f"golden-{uuid.uuid4().hex[:12]}"
    template_dir = _BACKEND / "storage" / "templates" / tid
    template_dir.mkdir(parents=True, exist_ok=True)
    dest = template_dir / video_path.name
    if not dest.exists():
        shutil.copy2(video_path, dest)

    rel_path = str(dest.relative_to(_BACKEND)).replace("\\", "/")

    db = SessionLocal()
    try:
        template = Template(
            id=tid,
            filename=video_path.name,
            duration=0,
            slot_count=0,
            file_path=rel_path,
            slots=[],
            audio_path="",
            subtitle_srt_path="",
            subtitle_ass_path="",
            subtitle_style="",
            segments_json=[],
            processing_status="processing",
            processing_progress=5,
            enhance_status="processing",
            enhance_progress=0,
            beat_markers=[],
            created_at=time.time(),
        )
        db.add(template)
        db.commit()

        slots = process_template_intake(tid, rel_path, str(template_dir))
        template = db.query(Template).filter(Template.id == tid).first()
        if template:
            template.slots = slots
            template.slot_count = len(slots)
            db.commit()

        batch = run_auto_subtitle_batch(tid)
        template = db.query(Template).filter(Template.id == tid).first()
        actual = list(template.slots or []) if template else slots
        return {
            "skipped": False,
            "template_id": tid,
            "video_path": str(video_path.resolve()),
            "batch": batch,
            "slots": actual,
        }
    finally:
        db.close()


def _run_offline_case(case: dict, manifest_dir: Path) -> dict:
    video_path = resolve_manifest_path(manifest_dir, str(case.get("template_video", "")))
    return _run_offline_video(video_path)


def _run_api_case(case: dict, manifest_dir: Path, api_base: str, timeout_sec: int) -> dict:
    import urllib.error
    import urllib.request

    video_path = resolve_manifest_path(manifest_dir, str(case.get("template_video", "")))
    if not video_path.is_file():
        return {"skipped": True, "reason": f"video missing: {video_path}"}

    base = api_base.rstrip("/")

    def _post_json(path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"{base}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _get_json(path: str) -> dict:
        with urllib.request.urlopen(f"{base}{path}", timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # multipart upload
    boundary = f"----GoldenEval{uuid.uuid4().hex}"
    body_prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{video_path.name}"\r\n'
        f"Content-Type: video/mp4\r\n\r\n"
    ).encode("utf-8")
    body_suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
    file_bytes = video_path.read_bytes()
    body = body_prefix + file_bytes + body_suffix

    upload_req = urllib.request.Request(
        f"{base}/api/template/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(upload_req, timeout=timeout_sec) as resp:
            upload_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"skipped": True, "reason": f"upload failed: {exc.read().decode()[:200]}"}

    template_id = upload_data.get("template_id")
    if not template_id:
        return {"skipped": True, "reason": "upload missing template_id"}

    deadline = time.time() + timeout_sec
    slots: list = []
    while time.time() < deadline:
        status = _get_json(f"/api/template/{template_id}/status")
        if status.get("processing_status") == "ready" and status.get("slot_count", 0) > 0:
            slots = status.get("segments_json")  # noqa: not slots
            break
        time.sleep(2)

    status = _get_json(f"/api/template/{template_id}/status")
    # fetch full template slots via project or template detail
    detail = _get_json(f"/api/template/{template_id}")
    slots = detail.get("slots") or []

    if not slots:
        return {"skipped": True, "reason": "template not ready or no slots"}

    payload_slots = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        start = float(slot.get("clip_start") or slot.get("start") or 0)
        end = float(slot.get("clip_end") or slot.get("end") or start + float(slot.get("duration", 1)))
        payload_slots.append({
            "slot_id": slot.get("slot_id") or slot.get("id"),
            "slot_start": start,
            "slot_end": end,
        })

    if payload_slots:
        _post_json(
            "/api/subtitle/recognize-slot-batch",
            {
                "template_id": template_id,
                "slots": payload_slots,
                "mode": "auto",
                "force": False,
                "quality": False,
            },
        )
        detail = _get_json(f"/api/template/{template_id}")
        slots = detail.get("slots") or slots

    return {"skipped": False, "template_id": template_id, "slots": slots}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run subtitle golden-set evaluation")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=_BACKEND.parent / "docs/subtitle-golden-set/manifest.json",
    )
    parser.add_argument(
        "--mode",
        choices=("check", "offline", "api"),
        default="check",
        help="check=结构检查; offline=本地 intake+auto; api=HTTP 上传+批量识别",
    )
    parser.add_argument(
        "--video",
        action="append",
        default=[],
        metavar="PATH",
        help="额外样片 mp4（offline 模式可单独建立 baseline，可多次指定）",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="扫描 backend/storage/templates/**/*.mp4 作为 ad-hoc 用例",
    )
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--json-out", type=Path, default=None, help="评测报告 JSON")
    parser.add_argument(
        "--baseline-out",
        type=Path,
        default=_DEFAULT_BASELINE,
        help="offline 跑完写入 baseline（含 slots 快照，便于生成 expected）",
    )
    parser.add_argument(
        "--record-baseline",
        action="store_true",
        help="仅记录指标与 slots，不因阈值未达标而失败（--video/--discover 时默认开启）",
    )
    args = parser.parse_args()

    ad_hoc_cases = _collect_ad_hoc_cases(args)
    record_baseline = args.record_baseline or bool(ad_hoc_cases)

    manifest: dict = {"cases": []}
    manifest_dir = args.manifest.parent.resolve()
    if args.manifest.is_file():
        manifest = _load_manifest(args.manifest)
    elif not ad_hoc_cases:
        print(f"Manifest not found: {args.manifest}")
        print("Copy manifest.example.json to manifest.json and add sample videos.")
        print("Or pass --video path/to/sample.mp4 for ad-hoc offline baseline.")
        return 1

    cases = list(manifest.get("cases") or [])
    if ad_hoc_cases:
        cases.extend(ad_hoc_cases)

    if not cases:
        print("No cases in manifest or from --video/--discover.")
        return 1

    if args.mode == "check" and ad_hoc_cases:
        print("Note: --video/--discover ignored in check mode.")

    report: dict = {
        "mode": args.mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "record_baseline": record_baseline,
        "cases": [],
        "passed": 0,
        "failed": 0,
        "skipped": 0,
    }
    baseline_rows: list[dict] = []

    print(f"Golden set: {len(cases)} cases [{args.mode}]")
    if ad_hoc_cases:
        print(f"  ad-hoc: {len(ad_hoc_cases)} from --video/--discover")

    for case in cases:
        cid = case.get("id", "?")
        video = resolve_manifest_path(manifest_dir, str(case.get("template_video", "")))
        expected_path = resolve_manifest_path(manifest_dir, str(case.get("expected_file", "")))
        expected_slots = load_expected(expected_path) if expected_path.is_file() else None
        case_record_baseline = record_baseline or bool(case.get("record_baseline"))

        row: dict = {"id": cid, "category": case.get("category")}

        if args.mode == "check":
            row.update({
                "video_ok": video.is_file(),
                "expected_ok": expected_path.is_file(),
                "min_nonempty_rate": case.get("min_nonempty_rate"),
            })
            ok = video.is_file() or expected_path.is_file()
            row["status"] = "ok" if ok else "missing_assets"
            if not ok:
                report["skipped"] += 1
            else:
                report["passed"] += 1
            print(
                f"  [{cid}] video={'OK' if video.is_file() else 'MISSING'} "
                f"expected={'OK' if expected_path.is_file() else 'MISSING'}"
            )
            report["cases"].append(row)
            continue

        if args.mode == "offline":
            run = _run_offline_case(case, manifest_dir)
        else:
            run = _run_api_case(case, manifest_dir, args.api_base, args.timeout)

        if run.get("skipped"):
            row["status"] = "skipped"
            row["reason"] = run.get("reason")
            report["skipped"] += 1
            print(f"  [{cid}] SKIP — {row['reason']}")
            report["cases"].append(row)
            continue

        actual_slots = run.get("slots") or []
        metrics = evaluate_case_metrics(actual_slots, expected_slots)
        passed, reasons = case_passed(metrics, case)
        row["metrics"] = metrics
        row["template_id"] = run.get("template_id")
        row["video_path"] = run.get("video_path") or str(video.resolve())
        if case_record_baseline:
            row["slots"] = _slot_snapshot(actual_slots)
            baseline_rows.append({
                "id": cid,
                "video_path": row["video_path"],
                "template_id": row.get("template_id"),
                "metrics": metrics,
                "slots": row["slots"],
            })

        if case_record_baseline:
            row["status"] = "recorded"
            report["passed"] += 1
            print(
                f"  [{cid}] RECORD nonempty={metrics['nonempty_rate']:.0%} "
                f"dup={metrics['duplicate_rate']:.0%} sources={metrics['source_distribution']}"
            )
        elif passed:
            row["status"] = "pass"
            report["passed"] += 1
            print(
                f"  [{cid}] PASS nonempty={metrics['nonempty_rate']:.0%} "
                f"dup={metrics['duplicate_rate']:.0%} sources={metrics['source_distribution']}"
            )
        else:
            row["status"] = "fail"
            row["reasons"] = reasons
            report["failed"] += 1
            print(f"  [{cid}] FAIL — {'; '.join(reasons)}")

        report["cases"].append(row)

    print(f"\nSummary: pass={report['passed']} fail={report['failed']} skip={report['skipped']}")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report written: {args.json_out}")

    if baseline_rows and args.mode == "offline":
        baseline_doc = {
            "version": 1,
            "generated_at": report["generated_at"],
            "mode": args.mode,
            "cases": baseline_rows,
        }
        args.baseline_out.parent.mkdir(parents=True, exist_ok=True)
        args.baseline_out.write_text(
            json.dumps(baseline_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Baseline written: {args.baseline_out}")

    if report["failed"]:
        return 2
    if report["passed"] == 0 and report["skipped"] == len(cases):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
