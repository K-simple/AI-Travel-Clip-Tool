"""对比字幕时间轴：拆槽前（镜头+对齐） vs 拆槽后（一句一槽）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _slot_row(slot: dict) -> dict:
    cs = slot.get("clip_start", slot.get("start"))
    ce = slot.get("clip_end", slot.get("end"))
    return {
        "slot_id": slot.get("slot_id"),
        "clip": f"{cs:.2f}-{ce:.2f}" if cs is not None and ce is not None else "?",
        "dur": round(float(slot.get("duration") or 0), 2),
        "text": (slot.get("subtitle_text") or "")[:48],
        "source": slot.get("subtitle_source"),
        "split_from": slot.get("subtitle_split_from"),
    }


def _print_table(title: str, slots: list[dict]) -> None:
    print(f"\n=== {title} ({len(slots)} 槽) ===")
    for row in [_slot_row(s) for s in slots]:
        extra = f" ←#{row['split_from']}" if row.get("split_from") else ""
        print(
            f"  #{row['slot_id']:>2} [{row['clip']:>13}] {row['dur']:>4.2f}s "
            f"| {row['text']}{extra}"
        )


def run_compare(video_path: Path, *, ocr_engine: str, quality: bool) -> dict:
    from services.processing_config import SUBTITLE_SCAN_FPS
    from services.scene_detector import build_template_shot_slots, get_video_duration
    from services.subtitle_timeline_scan import (
        apply_subtitle_timeline_to_slots,
        probe_timeline_viable,
        scan_and_ocr_burned_timeline,
        split_slots_by_subtitle_timeline,
    )

    os.environ["OCR_ENGINE"] = ocr_engine
    resolved = video_path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)

    duration = get_video_duration(str(resolved))
    if duration <= 0:
        raise RuntimeError(f"无法读取时长: {resolved}")

    print(f"视频: {resolved.name} ({duration:.1f}s)  OCR={ocr_engine}  quality={quality}")

    t0 = time.monotonic()
    shot_slots = build_template_shot_slots(
        str(resolved),
        str(_BACKEND / "storage" / "temp" / "split_compare_thumbs"),
        duration,
        skip_auto_tune=True,
        skip_ai_refine=True,
        extract_thumbs=False,
        allow_interval_fallback=True,
    )
    t_shot = time.monotonic() - t0
    print(f"镜头切分: {len(shot_slots)} 槽 ({t_shot:.1f}s)")

    t1 = time.monotonic()
    timeline = scan_and_ocr_burned_timeline(
        str(resolved),
        duration,
        quality=quality,
        sample_fps=SUBTITLE_SCAN_FPS,
    )
    t_scan = time.monotonic() - t1
    print(f"字幕时间轴: {len(timeline)} 句 ({t_scan:.1f}s)")
    for seg in timeline:
        print(
            f"  {seg.get('start', 0):.2f}-{seg.get('end', 0):.2f}s "
            f"| {(seg.get('text') or '')[:56]}"
        )

    if not probe_timeline_viable(timeline, min_segments=1):
        print("WARN: 时间轴不可用，跳过对比")
        return {"shot_count": len(shot_slots), "timeline_count": len(timeline)}

    aligned = apply_subtitle_timeline_to_slots(
        [dict(s) for s in shot_slots],
        timeline,
    )
    split = split_slots_by_subtitle_timeline(
        [dict(s) for s in shot_slots],
        timeline,
        video_path=str(resolved),
        thumb_dir=str(_BACKEND / "storage" / "temp" / "split_compare_thumbs"),
    )

    _print_table("拆槽前（镜头切分 + 时间轴对齐，一槽可能多句）", aligned)
    _print_table("拆槽后（一句一槽）", split)

    multi = sum(
        1
        for s in aligned
        if len(s.get("subtitle_segments") or []) > 1
        or (
            s.get("subtitle_text")
            and len(
                [
                    x
                    for x in (s.get("subtitle_segments") or [])
                    if str(x.get("text") or "").strip()
                ]
            )
            > 1
        )
    )
    print(
        f"\n汇总: 镜头 {len(shot_slots)} → 对齐 {len(aligned)} (多句槽 {multi}) "
        f"→ 拆槽 {len(split)}"
    )
    return {
        "duration_sec": duration,
        "ocr_engine": ocr_engine,
        "shot_count": len(shot_slots),
        "timeline_count": len(timeline),
        "aligned_count": len(aligned),
        "split_count": len(split),
        "multi_subtitle_slots": multi,
        "timeline": timeline,
        "aligned": [_slot_row(s) for s in aligned],
        "split": [_slot_row(s) for s in split],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="字幕驱动拆槽前后对比")
    parser.add_argument(
        "--video",
        required=True,
        help="模板 mp4 路径",
    )
    parser.add_argument(
        "--ocr-engine",
        default=os.getenv("OCR_ENGINE", "easyocr"),
        choices=("easyocr", "paddle"),
    )
    parser.add_argument(
        "--quality",
        action="store_true",
        help="HQ OCR（较慢）",
    )
    parser.add_argument(
        "--out",
        default="",
        help="JSON 输出路径",
    )
    args = parser.parse_args()

    result = run_compare(Path(args.video), ocr_engine=args.ocr_engine, quality=args.quality)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
