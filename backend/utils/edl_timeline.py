"""PRD 标准 EDL / Timeline JSON 与槽位 timeline 互转。"""

from typing import Any, Dict, List, Optional


def slots_timeline_to_edl(
    timeline: List[Dict[str, Any]],
    *,
    width: int = 1080,
    height: int = 1920,
    fps: float = 30,
    beat_markers: Optional[List[float]] = None,
    transition_type: str = "fade",
    transition_duration: float = 0.3,
    overlay_tracks: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """将槽位 timeline 转为 PRD 多轨 EDL。"""
    video_clips: List[Dict[str, Any]] = []
    subtitle_clips: List[Dict[str, Any]] = []
    audio_clips: List[Dict[str, Any]] = []
    dst_cursor = 0.0

    for i, slot in enumerate(timeline):
        dur = float(slot.get("slot_duration") or slot.get("duration") or 0)
        if dur <= 0:
            continue

        slot_id = slot.get("slot_id", i + 1)
        clip_id = f"c{i + 1}"

        if slot.get("asset_id"):
            video_clips.append({
                "clip_id": clip_id,
                "slot_id": slot_id,
                "asset_seg_id": slot.get("asset_id"),
                "asset_file_path": slot.get("asset_file_path", ""),
                "src_in": float(slot.get("clip_start") or 0),
                "src_out": float(slot.get("clip_start") or 0) + dur,
                "dst_in": dst_cursor,
                "dst_out": dst_cursor + dur,
                "speed": float(slot.get("speed", 1.0)),
                "optical_flow": bool(slot.get("optical_flow", False)),
                "keyframes": slot.get("keyframes") or [],
                "color_grade": slot.get("color_grade"),
                "mask": slot.get("mask"),
                "transition_in": None if i == 0 else {"type": transition_type, "duration": transition_duration},
                "transition_out": slot.get("transition_out")
                or (
                    {
                        "type": transition_type,
                        "duration": transition_duration,
                        "color": "#000000",
                    }
                    if i < len(timeline) - 1
                    else None
                ),
            })

        sub_text = (slot.get("subtitle_text") or "").strip()
        segs = slot.get("subtitle_segments") or []
        if segs:
            for j, seg in enumerate(segs):
                rel_start = float(seg.get("start", 0)) - float(slot.get("slot_start") or 0)
                rel_end = float(seg.get("end", 0)) - float(slot.get("slot_start") or 0)
                subtitle_clips.append({
                    "clip_id": f"sub{i}_{j}",
                    "text": seg.get("text", ""),
                    "dst_in": dst_cursor + max(0, rel_start),
                    "dst_out": dst_cursor + max(rel_start + 0.1, rel_end),
                    "style_id": "style_main",
                    "animation_in": "fade_up",
                    "animation_out": "fade_down",
                })
        elif sub_text:
            subtitle_clips.append({
                "clip_id": f"sub{i}",
                "text": sub_text,
                "dst_in": dst_cursor + 0.05,
                "dst_out": dst_cursor + dur - 0.05,
                "style_id": "style_main",
                "animation_in": "fade_up",
                "animation_out": "fade_down",
            })

        if slot.get("use_original_audio"):
            audio_clips.append({
                "clip_id": f"a{i}",
                "asset_id": slot.get("asset_id"),
                "src_in": float(slot.get("clip_start") or 0),
                "src_out": float(slot.get("clip_start") or 0) + dur,
                "dst_in": dst_cursor,
                "gain": float(slot.get("asset_audio_volume") or 0.3),
                "ducking": True,
            })

        dst_cursor += dur

    return {
        "version": "1.0",
        "project": {
            "width": width,
            "height": height,
            "fps": fps,
            "sample_rate": 48000,
            "duration": dst_cursor,
        },
        "tracks": {
            "video": _build_video_tracks(video_clips, overlay_tracks),
            "subtitle": [{"track_id": "t1", "clips": subtitle_clips}],
            "audio": [
                {"track_id": "a1", "clips": audio_clips},
                {
                    "track_id": "a2",
                    "clips": [{
                        "clip_id": "bgm",
                        "type": "template_bgm",
                        "dst_in": 0,
                        "dst_out": dst_cursor,
                        "gain": -18,
                        "beat_markers": beat_markers or [],
                    }],
                },
            ],
        },
        "styles": {
            "style_main": {
                "font": "Microsoft YaHei",
                "size": 54,
                "color": "#FFFFFF",
                "stroke": 3,
                "stroke_color": "#000000",
                "alignment": "bottom_center",
                "safe_margin": 120,
            }
        },
        "source": "slots_timeline",
    }


def _build_video_tracks(
    v1_clips: List[Dict[str, Any]],
    overlay_tracks: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    tracks = [{"track_id": "v1", "clips": v1_clips}]
    overlays = overlay_tracks or {}
    for tid in ("v2", "v3"):
        clips = overlays.get(tid) or overlays.get(tid.replace("v", "video_")) or []
        if clips:
            tracks.append({"track_id": tid, "clips": clips})
        else:
            tracks.append({"track_id": tid, "clips": []})
    return tracks


def enrich_edl_asset_paths(edl: Dict[str, Any], timeline: List[Dict[str, Any]]) -> Dict[str, Any]:
    """用 timeline 槽位补全 EDL 片段的 asset_file_path。"""
    path_by_asset: Dict[str, str] = {}
    for slot in timeline:
        aid = slot.get("asset_id")
        fp = slot.get("asset_file_path")
        if aid and fp:
            path_by_asset[str(aid)] = fp

    tracks = edl.get("tracks") or {}
    for vtrack in tracks.get("video") or []:
        for clip in vtrack.get("clips") or []:
            if not clip.get("asset_file_path"):
                seg = clip.get("asset_seg_id")
                if seg and str(seg) in path_by_asset:
                    clip["asset_file_path"] = path_by_asset[str(seg)]
    return edl
