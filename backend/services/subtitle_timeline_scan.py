"""烧录字幕时间轴：逐帧（采样）扫描字幕带变化 → 按句切分 → OCR（剪映式）。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable

import cv2
import numpy as np

from services.subtitle_gen import normalize_chinese_subtitle
from utils.security import resolve_storage_path

# 竖屏旅游片常见烧录字幕带（全片校准后可覆盖）
_DEFAULT_Y0 = 0.58
_DEFAULT_Y1 = 0.92


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


SUBTITLE_SCAN_FPS = _env_float("SUBTITLE_SCAN_FPS", 4.0)
SUBTITLE_SCAN_MIN_SEGMENT_SEC = _env_float("SUBTITLE_SCAN_MIN_SEGMENT_SEC", 0.35)
SUBTITLE_SCAN_HASH_THRESHOLD = int(os.getenv("SUBTITLE_SCAN_HASH_THRESHOLD", "10"))
SUBTITLE_SPLIT_MIN_SLOT_SEC = _env_float("SUBTITLE_SPLIT_MIN_SLOT_SEC", 0.28)


def _slot_source_range(slot: dict[str, Any]) -> tuple[float, float]:
    start = float(slot.get("clip_start") if slot.get("clip_start") is not None else slot.get("start") or 0)
    end = float(
        slot.get("clip_end")
        if slot.get("clip_end") is not None
        else slot.get("end")
        if slot.get("end") is not None
        else start + float(slot.get("duration") or slot.get("slot_duration") or 0.1)
    )
    return start, max(start + 0.08, end)


@dataclass(frozen=True)
class SubtitleBand:
    y0_ratio: float = _DEFAULT_Y0
    y1_ratio: float = _DEFAULT_Y1


def extract_subtitle_band(frame: np.ndarray, band: SubtitleBand | None = None) -> np.ndarray | None:
    if frame is None or frame.size == 0:
        return None
    b = band or SubtitleBand()
    h, w = frame.shape[:2]
    y0 = int(h * b.y0_ratio)
    y1 = int(h * b.y1_ratio)
    x0 = int(w * 0.05)
    x1 = int(w * 0.95)
    crop = frame[y0:y1, x0:x1]
    return crop if crop.size > 0 else None


def band_dhash(band: np.ndarray, *, hash_size: int = 8) -> int:
    """差异哈希，用于判断字幕带像素是否变化。"""
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    diff = resized[:, 1:] > resized[:, :-1]
    bits = diff.flatten()
    value = 0
    for i, bit in enumerate(bits):
        if bit:
            value |= 1 << i
    return value


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def band_has_content(band: np.ndarray, *, min_variance: float = 180.0) -> bool:
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    return float(np.var(gray)) >= min_variance


def calibrate_subtitle_band(
    video_path: str,
    duration: float,
    *,
    sample_count: int = 8,
) -> SubtitleBand:
    """在整片均匀采样，选字幕带方差最大的纵向区间。"""
    resolved = resolve_storage_path(video_path)
    if not resolved or duration <= 0:
        return SubtitleBand()

    candidates = [
        SubtitleBand(0.55, 0.94),
        SubtitleBand(0.58, 0.92),
        SubtitleBand(0.62, 0.90),
        SubtitleBand(0.50, 0.88),
    ]
    scores = [0.0] * len(candidates)
    times = [
        duration * (i + 0.5) / max(sample_count, 1)
        for i in range(sample_count)
    ]

    cap = cv2.VideoCapture(resolved)
    if not cap.isOpened():
        return SubtitleBand()
    try:
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            for i, band_def in enumerate(candidates):
                band = extract_subtitle_band(frame, band_def)
                if band is None:
                    continue
                gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
                scores[i] += float(np.var(gray))
    finally:
        cap.release()

    best_i = max(range(len(candidates)), key=lambda i: scores[i])
    if scores[best_i] <= 0:
        return SubtitleBand()
    return candidates[best_i]


def scan_subtitle_boundaries(
    video_path: str,
    duration: float,
    *,
    band: SubtitleBand | None = None,
    sample_fps: float | None = None,
    hash_threshold: int | None = None,
) -> list[float]:
    """
    按固定帧率采样字幕带，哈希突变处即为字幕换句边界。
    返回边界时间列表（不含 0 与 duration，由调用方补全）。
    """
    resolved = resolve_storage_path(video_path)
    if not resolved or duration <= 0.1:
        return []

    fps = sample_fps if sample_fps is not None else SUBTITLE_SCAN_FPS
    threshold = hash_threshold if hash_threshold is not None else SUBTITLE_SCAN_HASH_THRESHOLD
    step = 1.0 / max(fps, 0.5)
    band = band or calibrate_subtitle_band(video_path, duration)

    cap = cv2.VideoCapture(resolved)
    if not cap.isOpened():
        return []

    boundaries: list[float] = []
    prev_hash: int | None = None
    prev_content = False
    t = step * 0.5

    try:
        while t < duration - step * 0.25:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                t += step
                continue

            crop = extract_subtitle_band(frame, band)
            if crop is None:
                t += step
                continue

            has_content = band_has_content(crop)
            dh = band_dhash(crop)

            if prev_hash is not None:
                changed = False
                if has_content != prev_content:
                    changed = True
                elif has_content and hamming_distance(dh, prev_hash) >= threshold:
                    changed = True
                if changed:
                    boundaries.append(round(t - step * 0.5, 3))

            prev_hash = dh
            prev_content = has_content
            t += step
    finally:
        cap.release()

    # 去抖：合并过近边界
    min_gap = SUBTITLE_SCAN_MIN_SEGMENT_SEC * 0.6
    merged: list[float] = []
    for b in sorted(boundaries):
        if merged and b - merged[-1] < min_gap:
            continue
        merged.append(b)
    return merged


def segments_from_boundaries(
    boundaries: list[float],
    duration: float,
    *,
    min_segment_sec: float | None = None,
) -> list[tuple[float, float]]:
    min_seg = min_segment_sec if min_segment_sec is not None else SUBTITLE_SCAN_MIN_SEGMENT_SEC
    edges = [0.0] + sorted(b for b in boundaries if 0 < b < duration) + [duration]
    segments: list[tuple[float, float]] = []
    for i in range(len(edges) - 1):
        start, end = edges[i], edges[i + 1]
        if end - start < min_seg:
            if segments:
                ps, pe = segments[-1]
                segments[-1] = (ps, end)
            continue
        segments.append((round(start, 3), round(end, 3)))
    return segments


def _ocr_segment_text(
    video_path: str,
    start: float,
    end: float,
    *,
    quality: bool,
    band: SubtitleBand,
) -> str:
    from services.subtitle_ocr import _consensus_ocr_texts, _ocr_text_at_time, _work_dir_for_video

    resolved = resolve_storage_path(video_path) or video_path
    out_dir = _work_dir_for_video(resolved)
    duration = max(0.12, end - start)
    if duration <= 1.5:
        times = [start + duration * 0.5]
    else:
        times = [
            start + duration * 0.28,
            start + duration * 0.52,
            start + duration * 0.76,
        ]
    texts: list[str] = []
    for t in times:
        text = _ocr_text_at_time(
            resolved,
            t,
            out_dir,
            fast=not quality,
            band_y0=band.y0_ratio,
            band_y1=band.y1_ratio,
        )
        if text:
            texts.append(text)
    return _consensus_ocr_texts(texts)


def _ocr_range_segment(
    video_path: str,
    start: float,
    end: float,
    *,
    quality: bool,
    band: SubtitleBand,
) -> dict[str, Any] | None:
    text = _ocr_segment_text(video_path, start, end, quality=quality, band=band)
    text = normalize_chinese_subtitle(text)
    if not text or len(re.sub(r"\s+", "", text)) < 2:
        return None
    return {
        "start": start,
        "end": end,
        "duration": round(end - start, 3),
        "text": text,
        "source": "visual_timeline" if quality is False else "visual",
    }


def _parallel_ocr_ranges(
    video_path: str,
    ranges: list[tuple[float, float]],
    *,
    quality: bool,
    band: SubtitleBand,
    on_done: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any] | None]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from services.processing_config import SUBTITLE_OCR_WORKERS
    from services.subtitle_ocr import preload_ocr_reader

    if not ranges:
        return []
    preload_ocr_reader()
    workers = max(1, min(SUBTITLE_OCR_WORKERS, len(ranges)))
    results: list[dict[str, Any] | None] = [None] * len(ranges)
    done = 0
    total = len(ranges)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _ocr_range_segment,
                video_path,
                float(start),
                float(end),
                quality=quality,
                band=band,
            ): idx
            for idx, (start, end) in enumerate(ranges)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception as exc:
                print(f"并行 OCR 失败 #{idx + 1}: {exc}")
                results[idx] = None
            done += 1
            if on_done:
                on_done(done, total)
    return results


def ocr_burned_slots_batch(
    video_path: str,
    ranges: list[tuple[float, float]],
    *,
    quality: bool = True,
) -> list[list[dict[str, Any]]]:
    """
    烧录字幕逐槽 OCR（校准 band + 多时刻采样），并行处理各槽。
    """
    from services.scene_detector import get_video_duration

    if not video_path or not ranges:
        return [[] for _ in ranges]

    duration = float(get_video_duration(video_path) or 0)
    if duration <= 0:
        duration = max(float(end) for _, end in ranges)

    band = calibrate_subtitle_band(video_path, duration)
    valid_ranges = [
        (float(s), float(e)) for s, e in ranges if float(e) > float(s)
    ]
    if not valid_ranges:
        return [[] for _ in ranges]

    def _progress(done: int, total: int) -> None:
        if done == 1 or done == total or done % 5 == 0:
            print(f"烧录 OCR 进度 {done}/{total}")

    ocr_rows = _parallel_ocr_ranges(
        video_path,
        valid_ranges,
        quality=quality,
        band=band,
        on_done=_progress,
    )

    out: list[list[dict[str, Any]]] = []
    row_i = 0
    for slot_start, slot_end in ranges:
        slot_start = float(slot_start)
        slot_end = float(slot_end)
        if slot_end <= slot_start:
            out.append([])
            continue
        row = ocr_rows[row_i] if row_i < len(ocr_rows) else None
        row_i += 1
        if not row:
            out.append([])
            continue
        seg = dict(row)
        seg["start"] = round(slot_start, 3)
        seg["end"] = round(slot_end, 3)
        seg["duration"] = round(slot_end - slot_start, 3)
        seg["source"] = "visual"
        out.append([seg])
    return out


def scan_and_ocr_burned_timeline(
    video_path: str,
    duration: float,
    *,
    quality: bool = False,
    sample_fps: float | None = None,
    on_segment_done: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """
    剪映式：扫描字幕换句点 → 每段多时刻 OCR → 带真实起止时间的 subtitle segments。
    """
    band = calibrate_subtitle_band(video_path, duration)
    boundaries = scan_subtitle_boundaries(
        video_path, duration, band=band, sample_fps=sample_fps
    )
    ranges = segments_from_boundaries(boundaries, duration)
    if not ranges:
        return []

    ocr_rows = _parallel_ocr_ranges(
        video_path,
        ranges,
        quality=quality,
        band=band,
        on_done=on_segment_done,
    )
    segments: list[dict[str, Any]] = []
    for row in ocr_rows:
        if row:
            segments.append({**row, "source": "visual_timeline"})
    return segments


def segments_overlapping_range(
    timeline: list[dict[str, Any]],
    range_start: float,
    range_end: float,
    *,
    min_overlap_ratio: float = 0.25,
) -> list[dict[str, Any]]:
    """取与槽位时间重叠的字幕段（剪映：槽位内显示对应句）。"""
    if range_end <= range_start:
        return []
    slot_dur = range_end - range_start
    hits: list[dict[str, Any]] = []
    for seg in timeline:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        ss = float(seg.get("start", 0))
        se = float(seg.get("end", ss))
        overlap = min(range_end, se) - max(range_start, ss)
        if overlap <= 0:
            continue
        ratio = overlap / max(slot_dur, 0.1)
        seg_overlap = overlap / max(se - ss, 0.1)
        if ratio >= min_overlap_ratio or seg_overlap >= 0.45:
            hits.append(dict(seg))
    return hits


def _subtitle_piece_for_range(
    seg: dict[str, Any],
    piece_start: float,
    piece_end: float,
) -> dict[str, Any]:
    text = str(seg.get("text") or "").strip()
    dur = piece_end - piece_start
    return {
        "start": round(piece_start, 3),
        "end": round(piece_end, 3),
        "duration": round(dur, 3),
        "text": text,
        "source": "visual_timeline",
    }


def _ensure_slot_clip_bounds(item: dict[str, Any]) -> None:
    start = float(item.get("clip_start") if item.get("clip_start") is not None else item.get("start") or 0)
    end = float(
        item.get("clip_end")
        if item.get("clip_end") is not None
        else item.get("end")
        if item.get("end") is not None
        else start + float(item.get("duration") or 0.1)
    )
    item["start"] = round(start, 3)
    item["end"] = round(end, 3)
    item["clip_start"] = round(start, 3)
    item["clip_end"] = round(end, 3)
    item["duration"] = round(max(0.08, end - start), 3)


def merge_timeline_segments(
    timeline: list[dict[str, Any]],
    *,
    similarity_threshold: float = 0.88,
    max_gap_sec: float = 0.4,
) -> list[dict[str, Any]]:
    """
    合并扫描/OCR 产生的同句碎片（哈希边界抖动），避免一句拆成多槽。
    """
    from services.subtitle_gen import normalize_chinese_subtitle
    from services.subtitle_quality import text_similarity

    ordered = sorted(
        (dict(seg) for seg in timeline if isinstance(seg, dict)),
        key=lambda s: float(s.get("start", 0)),
    )
    if not ordered:
        return []

    merged: list[dict[str, Any]] = []
    for seg in ordered:
        text = normalize_chinese_subtitle(str(seg.get("text") or "").strip())
        if not text:
            continue
        ss = float(seg.get("start", 0))
        se = float(seg.get("end", ss))
        if se <= ss:
            continue
        item = {
            "start": round(ss, 3),
            "end": round(se, 3),
            "duration": round(se - ss, 3),
            "text": text,
            "source": seg.get("source") or "visual_timeline",
        }
        if not merged:
            merged.append(item)
            continue
        prev = merged[-1]
        prev_text = str(prev.get("text") or "")
        gap = ss - float(prev["end"])
        same = text == prev_text or (
            gap <= max_gap_sec and text_similarity(text, prev_text) >= similarity_threshold
        )
        if same:
            prev["end"] = round(max(float(prev["end"]), se), 3)
            prev["duration"] = round(float(prev["end"]) - float(prev["start"]), 3)
            if len(text) > len(prev_text):
                prev["text"] = text
            continue
        merged.append(item)
    return merged


def _distinct_timeline_pieces_in_slot(
    matched: list[dict[str, Any]],
    slot_start: float,
    slot_end: float,
    *,
    min_dur: float,
) -> list[tuple[float, float, dict[str, Any]]]:
    """每个合并后的字幕句在槽内最多保留一段（去重同句）。"""
    pieces: list[tuple[float, float, dict[str, Any]]] = []
    seen_texts: set[str] = set()
    for seg in matched:
        text = str(seg.get("text") or "").strip()
        if not text or text in seen_texts:
            continue
        ss = max(slot_start, float(seg.get("start", slot_start)))
        se = min(slot_end, float(seg.get("end", slot_end)))
        if se - ss < min_dur:
            continue
        seen_texts.add(text)
        pieces.append((ss, se, seg))
    return pieces


def split_slots_by_subtitle_timeline(
    slots: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    min_slot_duration: float | None = None,
    video_path: str = "",
    thumb_dir: str = "",
) -> list[dict[str, Any]]:
    """
    一镜多句时按字幕边界拆槽：仅当同一镜头内命中 **2 句不同字幕** 才拆。
    同句 OCR 碎片会先 merge，避免 25 句字幕被拆成 37 槽。
    """
    if not timeline or not slots:
        return slots

    timeline = merge_timeline_segments(timeline)
    min_dur = min_slot_duration if min_slot_duration is not None else SUBTITLE_SPLIT_MIN_SLOT_SEC
    out: list[dict[str, Any]] = []

    for slot in slots:
        start, end = _slot_source_range(slot)
        matched = segments_overlapping_range(timeline, start, end)
        if not matched:
            out.append(dict(slot))
            continue

        matched.sort(key=lambda s: float(s.get("start", 0)))
        pieces = _distinct_timeline_pieces_in_slot(matched, start, end, min_dur=min_dur)

        if len(pieces) <= 1:
            item = dict(slot)
            if pieces:
                ss, se, seg = pieces[0]
                text = str(seg.get("text") or "").strip()
                item["subtitle_text"] = text
                item["subtitle_segments"] = [_subtitle_piece_for_range(seg, ss, se)]
                item["subtitle_source"] = "visual_timeline"
                item["subtitle_timeline_aligned"] = True
            out.append(item)
            continue

        parent_id = slot.get("slot_id")
        for ss, se, seg in pieces:
            dur = se - ss
            item = dict(slot)
            item["start"] = round(ss, 3)
            item["end"] = round(se, 3)
            item["clip_start"] = round(ss, 3)
            item["clip_end"] = round(se, 3)
            item["duration"] = round(dur, 3)
            text = str(seg.get("text") or "").strip()
            item["subtitle_text"] = text
            item["subtitle_segments"] = [_subtitle_piece_for_range(seg, ss, se)]
            item["subtitle_source"] = "visual_timeline"
            item["subtitle_timeline_aligned"] = True
            item["subtitle_split_from"] = parent_id
            item["thumbnail"] = ""
            out.append(item)

    for i, item in enumerate(out):
        item["slot_id"] = i + 1
        item["segment_id"] = f"seg_{i + 1}"
        _ensure_slot_clip_bounds(item)

    if video_path and thumb_dir:
        try:
            from services.scene_detector import _attach_thumbnails

            indices_needing = [
                i for i, s in enumerate(out) if not str(s.get("thumbnail") or "").strip()
            ]
            if indices_needing:
                subset = [out[i] for i in indices_needing]
                updated = _attach_thumbnails(video_path, thumb_dir, subset)
                for idx, upd in zip(indices_needing, updated):
                    out[idx]["thumbnail"] = upd.get("thumbnail", "")

        except Exception as exc:
            print(f"拆槽后缩略图提取跳过: {exc}")

    return out


def apply_subtitle_timeline_to_slots(
    slots: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """用字幕时间轴覆盖各槽位文本（解决「镜头切分与字幕句不同步」）。"""
    if not timeline:
        return slots

    timeline = merge_timeline_segments(timeline)

    out: list[dict[str, Any]] = []
    for slot in slots:
        item = dict(slot)
        start, end = _slot_source_range(item)
        matched = segments_overlapping_range(timeline, start, end)
        if not matched:
            out.append(item)
            continue

        # 取重叠最大的单句作为槽位主字幕（避免一槽多句拼接成乱码）
        best = max(
            matched,
            key=lambda s: min(end, float(s["end"])) - max(start, float(s["start"])),
        )
        text = str(best.get("text") or "").strip()
        rel_segments = []
        for seg in matched:
            ss = max(start, float(seg.get("start", start)))
            se = min(end, float(seg.get("end", end)))
            if se <= ss:
                continue
            rel_segments.append({
                "start": round(ss, 3),
                "end": round(se, 3),
                "duration": round(se - ss, 3),
                "text": str(seg.get("text") or "").strip(),
                "source": "visual_timeline",
            })

        item["subtitle_text"] = text
        item["subtitle_segments"] = rel_segments or [{
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "text": text,
            "source": "visual_timeline",
        }]
        item["subtitle_source"] = "visual_timeline"
        item["subtitle_timeline_aligned"] = True
        out.append(item)
    return out


def probe_timeline_viable(timeline: list[dict[str, Any]], *, min_segments: int = 2) -> bool:
    if len(timeline) < min_segments:
        return False
    texts = [str(s.get("text") or "").strip() for s in timeline]
    unique = {t for t in texts if t}
    return len(unique) >= min(2, min_segments)
