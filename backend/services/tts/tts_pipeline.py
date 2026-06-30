"""TTS 生成与时间线对齐流水线。"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Any

from services.tts.tts_provider import get_tts_provider
from services.tts.tts_utils import estimate_duration_from_text, get_timeline_timing_mode
from services.tts.voice_profiles import get_voice_profile

__all__ = [
    "align_timeline_to_tts",
    "build_pipeline_debug",
    "concat_tts_for_timeline",
    "ensure_clip_timeline_fields",
    "generate_tts_for_clips",
    "get_timeline_timing_mode",
    "index_tts_by_caption_id",
    "sort_clips_by_index",
]


def sort_clips_by_index(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = list(clips or [])
    indexed.sort(
        key=lambda c: (
            int(c.get("index") or 0),
            float(c.get("start") or 0),
            str(c.get("id") or ""),
        )
    )
    return indexed


def ensure_clip_timeline_fields(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(clips or []):
        if not isinstance(raw, dict):
            continue
        clip = dict(raw)
        start = round(float(clip.get("start") or 0), 3)
        end = round(float(clip.get("end") or start), 3)
        if end <= start:
            end = round(start + max(0.35, float(clip.get("duration") or 0.35)), 3)
        clip["start"] = start
        clip["end"] = end
        clip["duration"] = round(end - start, 3)
        clip.setdefault("index", i + 1)
        if clip.get("originalStart") is None:
            clip["originalStart"] = start
        if clip.get("originalEnd") is None:
            clip["originalEnd"] = end
        tts = clip.get("tts")
        if not isinstance(tts, dict):
            tts = {}
        tts.setdefault("status", "pending")
        tts.setdefault("voiceId", "")
        tts.setdefault("voiceName", "")
        tts.setdefault("audioPath", "")
        tts.setdefault("duration", 0)
        tts.setdefault("provider", "")
        clip["tts"] = tts
        out.append(clip)
    return out


def index_tts_by_caption_id(tts_segments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for seg in tts_segments or []:
        if not isinstance(seg, dict):
            continue
        cid = str(seg.get("captionClipId") or seg.get("caption_clip_id") or "")
        if cid:
            out[cid] = seg
    return out


def _tts_segment_id(index: int) -> str:
    return f"tts_{index:03d}"


def _resolve_tts_dir(template_id: str) -> str:
    rel = os.path.join("storage", "templates", template_id, "tts").replace("\\", "/")
    os.makedirs(rel, exist_ok=True)
    return rel


def generate_tts_for_clips(
    template_id: str,
    clips: list[dict[str, Any]],
    *,
    voice_id: str,
    clip_ids: list[str] | None = None,
    overwrite: bool = False,
    existing_segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    profile = get_voice_profile(voice_id)
    if not profile:
        raise ValueError(f"未知音色 voiceId={voice_id}")

    prepared = ensure_clip_timeline_fields(clips)
    prepared = sort_clips_by_index(prepared)
    if not prepared:
        raise ValueError("没有可用的 CaptionClip")

    target_ids = {str(x).strip() for x in (clip_ids or []) if str(x).strip()}
    if target_ids:
        _ = [c for c in prepared if str(c.get("id") or "") in target_ids]
    else:
        _ = prepared

    seg_map: dict[str, dict[str, Any]] = index_tts_by_caption_id(existing_segments or [])
    tts_dir = _resolve_tts_dir(template_id)
    provider = get_tts_provider(profile.get("provider"))
    voice_name = str(profile.get("displayName") or voice_id)

    generated = 0
    failed = 0
    debug_items: list[dict[str, Any]] = []

    for clip in prepared:
        clip_id = str(clip.get("id") or "")
        idx = int(clip.get("index") or 0)
        if target_ids and clip_id not in target_ids:
            continue

        text = str(clip.get("text") or clip.get("displayText") or "").strip()
        seg_id = _tts_segment_id(idx)
        prev = seg_map.get(clip_id)
        tts_state = dict(clip.get("tts") or {})

        if (
            not overwrite
            and prev
            and str(prev.get("status") or "") == "generated"
            and prev.get("audioPath")
        ):
            seg_map[clip_id] = dict(prev)
            clip["tts"] = {
                "status": "generated",
                "voiceId": voice_id,
                "voiceName": voice_name,
                "audioPath": prev.get("audioPath") or "",
                "duration": float(prev.get("duration") or 0),
                "provider": prev.get("provider") or profile.get("provider") or "mock",
            }
            generated += 1
            continue

        if not text:
            seg = {
                "id": seg_id,
                "captionClipId": clip_id,
                "index": idx,
                "text": "",
                "voiceId": voice_id,
                "voiceName": voice_name,
                "audioPath": "",
                "duration": 0,
                "start": float(clip.get("start") or 0),
                "end": float(clip.get("end") or 0),
                "status": "failed",
                "error": "空文本",
                "provider": profile.get("provider") or "mock",
            }
            seg_map[clip_id] = seg
            clip["tts"] = {
                "status": "failed",
                "voiceId": voice_id,
                "voiceName": voice_name,
                "audioPath": "",
                "duration": 0,
                "provider": profile.get("provider") or "mock",
            }
            failed += 1
            debug_items.append({"clipId": clip_id, "status": "failed", "error": "空文本"})
            continue

        out_path = os.path.join(tts_dir, f"{seg_id}.wav").replace("\\", "/")
        try:
            result = provider.synthesize(
                text,
                voice_id=voice_id,
                output_path=out_path,
                language=str(profile.get("language") or "zh-CN"),
            )
            duration = float(result.get("duration") or estimate_duration_from_text(text))
            audio_path = str(result.get("audioPath") or out_path)
            seg = {
                "id": seg_id,
                "captionClipId": clip_id,
                "index": idx,
                "text": text,
                "voiceId": voice_id,
                "voiceName": voice_name,
                "audioPath": audio_path,
                "duration": round(duration, 3),
                "start": float(clip.get("start") or 0),
                "end": round(float(clip.get("start") or 0) + duration, 3),
                "status": "generated",
                "error": None,
                "provider": result.get("provider") or profile.get("provider") or "mock",
            }
            seg_map[clip_id] = seg
            clip["tts"] = {
                "status": "generated",
                "voiceId": voice_id,
                "voiceName": voice_name,
                "audioPath": audio_path,
                "duration": round(duration, 3),
                "provider": seg["provider"],
            }
            generated += 1
            debug_items.append({"clipId": clip_id, "status": "generated", "duration": duration})
        except Exception as exc:
            seg = {
                "id": seg_id,
                "captionClipId": clip_id,
                "index": idx,
                "text": text,
                "voiceId": voice_id,
                "voiceName": voice_name,
                "audioPath": "",
                "duration": 0,
                "start": float(clip.get("start") or 0),
                "end": float(clip.get("end") or 0),
                "status": "failed",
                "error": str(exc),
                "provider": profile.get("provider") or "mock",
            }
            seg_map[clip_id] = seg
            clip["tts"] = {
                "status": "failed",
                "voiceId": voice_id,
                "voiceName": voice_name,
                "audioPath": "",
                "duration": 0,
                "provider": profile.get("provider") or "mock",
            }
            failed += 1
            debug_items.append({"clipId": clip_id, "status": "failed", "error": str(exc)})

    segments: list[dict[str, Any]] = []
    for clip in prepared:
        clip_id = str(clip.get("id") or "")
        seg = seg_map.get(clip_id)
        if seg:
            segments.append(dict(seg))
        else:
            idx = int(clip.get("index") or len(segments) + 1)
            segments.append(
                {
                    "id": _tts_segment_id(idx),
                    "captionClipId": clip_id,
                    "index": idx,
                    "text": str(clip.get("text") or ""),
                    "voiceId": voice_id,
                    "voiceName": voice_name,
                    "audioPath": "",
                    "duration": 0,
                    "start": float(clip.get("start") or 0),
                    "end": float(clip.get("end") or 0),
                    "status": "pending",
                    "error": None,
                    "provider": "",
                }
            )
    return {
        "clips": prepared,
        "tts_segments": segments,
        "summary": {
            "captionClipCount": len(prepared),
            "generatedCount": generated,
            "failedCount": failed,
            "voiceId": voice_id,
        },
        "debug": {"items": debug_items, "provider": profile.get("provider")},
    }


def align_timeline_to_tts(
    clips: list[dict[str, Any]],
    tts_segments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    prepared = ensure_clip_timeline_fields(clips)
    prepared = sort_clips_by_index(prepared)
    seg_map = index_tts_by_caption_id(tts_segments)

    cursor = 0.0
    aligned_clips: list[dict[str, Any]] = []
    aligned_segments: list[dict[str, Any]] = []

    for clip in prepared:
        clip_id = str(clip.get("id") or "")
        seg = seg_map.get(clip_id)
        if seg and str(seg.get("status") or "") == "generated":
            dur = float(seg.get("duration") or 0)
        else:
            dur = float(clip.get("duration") or max(0.35, float(clip.get("end", 0)) - float(clip.get("start", 0))))

        dur = max(0.08, dur)
        start = round(cursor, 3)
        end = round(cursor + dur, 3)
        cursor = end

        next_clip = dict(clip)
        if next_clip.get("originalStart") is None:
            next_clip["originalStart"] = float(clip.get("start") or 0)
        if next_clip.get("originalEnd") is None:
            next_clip["originalEnd"] = float(clip.get("end") or 0)
        next_clip["start"] = start
        next_clip["end"] = end
        next_clip["duration"] = round(end - start, 3)
        aligned_clips.append(next_clip)

        if seg:
            next_seg = dict(seg)
            next_seg["start"] = start
            next_seg["end"] = end
            next_seg["duration"] = round(end - start, 3)
            aligned_segments.append(next_seg)
        else:
            aligned_segments.append(
                {
                    "id": _tts_segment_id(int(clip.get("index") or len(aligned_segments) + 1)),
                    "captionClipId": clip_id,
                    "index": int(clip.get("index") or len(aligned_segments) + 1),
                    "text": str(clip.get("text") or ""),
                    "voiceId": "",
                    "voiceName": "",
                    "audioPath": "",
                    "duration": round(end - start, 3),
                    "start": start,
                    "end": end,
                    "status": "pending",
                    "error": None,
                    "provider": "",
                }
            )

    return aligned_clips, aligned_segments, round(cursor, 3)


def build_pipeline_debug(
    *,
    clips: list[dict[str, Any]] | None = None,
    tts_segments: list[dict[str, Any]] | None = None,
    slots: list[dict[str, Any]] | None = None,
    pipeline_stage: str | None = None,
    voice_id: str | None = None,
    timing_mode: str | None = None,
) -> dict[str, Any]:
    clip_list = clips or []
    tts_list = tts_segments or []
    slot_list = slots or []
    needs_review = sum(
        1
        for c in clip_list
        if isinstance(c.get("quality"), dict) and c["quality"].get("needsReview")
    )
    total_duration = 0.0
    if clip_list:
        total_duration = max(float(c.get("end") or 0) for c in clip_list if isinstance(c, dict))
    elif tts_list:
        total_duration = max(float(s.get("end") or 0) for s in tts_list if isinstance(s, dict))

    stage = pipeline_stage or "captions_recognized"
    if tts_list and any(str(s.get("status") or "") == "generated" for s in tts_list):
        stage = "tts_generated"
    if timing_mode == "tts_driven" and clip_list and tts_list:
        if all(
            abs(float(c.get("start") or 0) - float(seg.get("start") or -1)) < 0.02
            for c, seg in zip(sort_clips_by_index(clip_list), sorted(tts_list, key=lambda x: x.get("index", 0)))
            if isinstance(c, dict) and isinstance(seg, dict)
        ):
            stage = "timeline_aligned"
    if slot_list:
        stage = "slots_applied"

    from services.slot_helpers import build_one_caption_one_shot_debug

    one_caption_one_shot_debug = build_one_caption_one_shot_debug(
        caption_clips=clip_list,
        slots=slot_list,
    )

    return {
        "pipelineStage": stage,
        "captionClipCount": len(clip_list),
        "ttsSegmentCount": len(tts_list),
        "slotCount": len(slot_list),
        "needsReviewCount": needs_review,
        "totalDuration": round(total_duration, 3),
        "timingMode": timing_mode or get_timeline_timing_mode(),
        "voiceId": voice_id or "",
        "oneCaptionOneShotDebug": one_caption_one_shot_debug,
    }


def concat_tts_for_timeline(
    timeline: list[dict[str, Any]],
    tts_segments: list[dict[str, Any]],
    output_path: str,
) -> str | None:
    """按时间线槽位顺序拼接 TTS wav，用于 MP4 导出。"""
    seg_map = index_tts_by_caption_id(tts_segments)
    ordered_paths: list[str] = []

    for slot in timeline or []:
        if not isinstance(slot, dict):
            continue
        tts_id = str(
            slot.get("linked_tts_segment_id")
            or slot.get("linkedTtsSegmentId")
            or ""
        )
        clip_id = str(
            slot.get("linked_subtitle_clip_id")
            or slot.get("linkedSubtitleClipId")
            or slot.get("linkedCaptionClipId")
            or ""
        )
        seg = None
        if tts_id:
            seg = next((s for s in tts_segments if str(s.get("id") or "") == tts_id), None)
        if not seg and clip_id:
            seg = seg_map.get(clip_id)
        if not seg or str(seg.get("status") or "") != "generated":
            continue
        ap = str(seg.get("audioPath") or "").strip()
        if not ap or not os.path.isfile(ap):
            from utils.security import resolve_storage_path

            ap = resolve_storage_path(ap) or ap
        if ap and os.path.isfile(ap):
            ordered_paths.append(ap)

    if not ordered_paths:
        return None

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if len(ordered_paths) == 1:
        import shutil

        shutil.copy2(ordered_paths[0], output_path)
        return output_path

    list_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    try:
        for p in ordered_paths:
            safe = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
            list_file.write(f"file '{safe}'\n")
        list_file.close()
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_file.name,
                "-c",
                "copy",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
        return output_path
    except Exception as exc:
        print(f"[tts] concat failed: {exc}")
        return None
    finally:
        try:
            os.unlink(list_file.name)
        except Exception:
            pass
