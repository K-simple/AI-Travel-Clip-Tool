"""按原视频画面镜头切分槽位（PySceneDetect + 可选 AI 边界修正），并关联字幕。"""

from __future__ import annotations

from typing import Any

from services.scene_detector import _attach_thumbnails, get_video_duration


def _overlap_sec(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _captions_overlapping_shot(
    shot_start: float,
    shot_end: float,
    clips: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    hits: list[tuple[float, dict[str, Any]]] = []
    for cap in clips:
        if not isinstance(cap, dict):
            continue
        cs = float(cap.get("start", 0))
        ce = float(cap.get("end", cs))
        ov = _overlap_sec(shot_start, shot_end, cs, ce)
        if ov >= 0.05:
            hits.append((ov, cap))
    hits.sort(key=lambda item: -item[0])
    return [cap for _, cap in hits]


def build_slots_from_visual_shots(
    shots: list[dict[str, Any]],
    caption_clips: list[dict[str, Any]] | None = None,
    *,
    video_path: str | None = None,
    thumb_dir: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """将 PySceneDetect 镜头列表转为槽位，并按时间重叠关联 CaptionClip。"""
    clips = [c for c in (caption_clips or []) if isinstance(c, dict)]
    slots: list[dict[str, Any]] = []
    slot_debug: list[dict[str, Any]] = []

    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue
        start = float(shot.get("start", 0))
        end = float(shot.get("end", start + float(shot.get("duration") or 0.1)))
        if end <= start:
            end = start + max(0.35, float(shot.get("duration") or 0.35))
        duration = max(0.08, end - start)

        overlapping = _captions_overlapping_shot(start, end, clips)
        primary = overlapping[0] if overlapping else None

        subtitle_segments: list[dict[str, Any]] = []
        for cap in overlapping:
            cs = float(cap.get("start", 0))
            ce = float(cap.get("end", cs))
            seg_start = max(start, cs)
            seg_end = min(end, ce)
            if seg_end <= seg_start:
                continue
            cap_style = cap.get("subtitle_style") if isinstance(cap.get("subtitle_style"), dict) else {}
            if not cap_style and isinstance(cap.get("style"), dict):
                cap_style = cap["style"]
            seg_item: dict[str, Any] = {
                "start": round(seg_start, 3),
                "end": round(seg_end, 3),
                "text": str(cap.get("text") or cap.get("displayText") or "").strip(),
                "type": "spoken_caption",
                "source": str(cap.get("source") or "asr"),
            }
            if cap_style:
                seg_item["style"] = dict(cap_style)
            subtitle_segments.append(seg_item)

        primary_text = ""
        if primary:
            primary_text = str(primary.get("text") or primary.get("displayText") or "").strip()
        if not primary_text and subtitle_segments:
            primary_text = str(subtitle_segments[0].get("text") or "")

        slot_id_num = index + 1
        slot: dict[str, Any] = {
            "id": f"slot_{slot_id_num:03d}",
            "slot_id": slot_id_num,
            "segment_id": f"seg_{slot_id_num}",
            "type": "video",
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(duration, 3),
            "clip_start": round(start, 3),
            "clip_end": round(end, 3),
            "template_source_start": round(start, 3),
            "subtitle_text": primary_text,
            "subtitle_segments": subtitle_segments,
            "subtitle_source": "visual_scene" if overlapping else "",
            "source": "visual_scene_split",
            "cut_reason": "pyscenedetect",
            "isBaseSlot": False,
            "thumbnail": shot.get("thumbnail") or "",
            "tags": list(shot.get("tags") or []),
            "scene_tags": list(shot.get("scene_tags") or []),
            "shot_type": shot.get("shot_type") or "wide",
            "has_person": bool(shot.get("has_person")),
            "quality_score": shot.get("quality_score"),
            "mood": shot.get("mood") or "",
        }
        if primary:
            clip_id = str(primary.get("id") or f"cap_{slot_id_num:03d}")
            slot["linked_subtitle_clip_id"] = clip_id
            slot["linkedSubtitleClipId"] = clip_id
            slot["linkedCaptionClipId"] = clip_id
            if isinstance(primary.get("subtitle_style"), dict):
                slot["subtitle_style"] = dict(primary["subtitle_style"])

        slots.append(slot)
        slot_debug.append(
            {
                "slotId": slot_id_num,
                "shotStart": round(start, 3),
                "shotEnd": round(end, 3),
                "linkedCaptionCount": len(overlapping),
                "linkedCaptionClipId": slot.get("linkedCaptionClipId"),
                "subtitleText": primary_text[:64],
            }
        )

    if video_path and thumb_dir and slots:
        missing = [s for s in slots if not str(s.get("thumbnail") or "").strip()]
        if missing:
            slots = _attach_thumbnails(video_path, thumb_dir, slots)

    return slots, slot_debug


def detect_visual_shots(
    video_path: str,
    thumb_dir: str,
    duration: float | None = None,
    *,
    skip_ai_refine: bool = False,
    skip_auto_tune: bool = False,
) -> list[dict[str, Any]]:
    """PySceneDetect 检测原视频镜头切点，可选 AI 边界修正。"""
    from services.scene_detector import build_template_shot_slots

    dur = duration if duration and duration > 0 else get_video_duration(video_path)
    shots = build_template_shot_slots(
        video_path,
        thumb_dir,
        dur,
        skip_auto_tune=skip_auto_tune,
        skip_ai_refine=skip_ai_refine,
        extract_thumbs=True,
        allow_interval_fallback=True,
    )
    return shots or []
