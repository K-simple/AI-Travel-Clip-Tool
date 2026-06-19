"""将项目时间轴导出为 CapCut Mate 剪映草稿。"""

import json
import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Literal, Optional

from services.processing_config import SEGMENT_CUT_WORKERS

from services.capcut_mate_client import (
    ADD_VIDEOS_BATCH_SIZE,
    add_audios,
    add_captions,
    add_videos,
    create_draft,
    extract_draft_id,
    get_draft_files,
    normalize_draft_url,
    require_capcut_mate,
    save_draft,
)
from services.slot_subtitle import get_whisper_source_path
from services.subtitle_style_analyzer import style_to_capcut_params, style_signature
from services.segment_extractor import extract_segment_audio, extract_segment_video
from services.video_exporter import cut_asset_clip, ensure_ffmpeg, file_ok
from utils.export_controls import resolve_export_mix
from utils.public_media import (
    build_capcut_clip_url,
    build_public_media_url,
    ensure_http_video_url,
    is_local_capcut_url,
    resolve_public_media_base,
    verify_media_url,
)
from utils.security import ensure_storage_subpath, resolve_storage_path

US_PER_SEC = 1_000_000

_CAPCUT_TRANSITION_MAP = {
    "fade": "fade",
    "fadeblack": "fade",
    "fadewhite": "fade",
    "fadegrays": "fade",
    "dissolve": "dissolve",
    "wipeleft": "wipe",
    "wiperight": "wipe",
    "slideleft": "slide",
    "slideright": "slide",
}


def _us(seconds: float) -> int:
    return max(1, int(round(float(seconds) * US_PER_SEC)))


def _parse_resolution(resolution: str) -> tuple[int, int]:
    parts = str(resolution or "1080x1920").lower().split("x")
    if len(parts) != 2:
        return 1080, 1920
    return int(parts[0]), int(parts[1])


def _probe_video_size(video_path: str) -> tuple[int, int] | None:
    import json
    import subprocess

    if not video_path or not os.path.isfile(video_path):
        return None
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        video_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            return None
        width = int(streams[0].get("width") or 0)
        height = int(streams[0].get("height") or 0)
        if width > 0 and height > 0:
            return width, height
    except Exception:
        return None
    return None


def _storage_relative(abs_path: str) -> str:
    norm = os.path.abspath(str(abs_path or "")).replace("\\", "/")
    idx = norm.find("/storage/")
    if idx >= 0:
        return norm[idx:]
    if norm.startswith("storage/"):
        return f"/{norm}"
    return norm


def _slot_duration(slot: dict[str, Any]) -> float:
    return float(
        slot.get("clip_duration")
        or slot.get("slot_duration")
        or slot.get("duration")
        or 2
    )


def _template_clip_start(slot: dict[str, Any]) -> float:
    if slot.get("clip_start") is not None:
        return float(slot.get("clip_start"))
    return float(slot.get("slot_start") or slot.get("start") or 0)


def _resolve_slot_source(
    slot: dict[str, Any],
    *,
    template_video_path: str,
    template_only: bool = False,
) -> tuple[str, float, float] | None:
    """返回 (file_path, clip_start, clip_duration)。"""
    duration = _slot_duration(slot)
    if duration <= 0:
        return None

    if template_only:
        if template_video_path and os.path.isfile(template_video_path):
            return template_video_path, _template_clip_start(slot), duration
        return None

    raw_path = (
        slot.get("segment_file_path")
        or slot.get("asset_file_path")
        or slot.get("file_path")
        or ""
    )
    if raw_path:
        try:
            file_path = resolve_storage_path(str(raw_path))
        except ValueError:
            return None
        if not os.path.isfile(file_path):
            return None
        clip_start = 0.0 if str(slot.get("segment_file_path") or "").strip() else float(
            slot.get("clip_start") or slot.get("asset_start") or 0
        )
        return file_path, clip_start, duration

    if template_video_path and os.path.isfile(template_video_path):
        return template_video_path, _template_clip_start(slot), duration
    return None


def _can_reuse_segment_file(
    slot: dict[str, Any],
    file_path: str,
    clip_start: float,
    keep_audio: bool,
) -> bool:
    """已切好的 segment mp4 可直接复制，避免重复 ffmpeg 编码。"""
    if keep_audio:
        return False
    seg = str(slot.get("segment_file_path") or "").strip()
    if not seg:
        return False
    try:
        resolved = resolve_storage_path(seg)
    except ValueError:
        return False
    if resolved != file_path or clip_start > 0.01:
        return False
    return os.path.isfile(resolved)


def _prepare_slot_clip(
    *,
    file_path: str,
    clip_start: float,
    clip_duration: float,
    output_path: str,
    width: int,
    height: int,
    keep_audio: bool,
    reuse_segment: bool,
    template_cut: bool = False,
) -> None:
    if reuse_segment:
        shutil.copy2(file_path, output_path)
        if not file_ok(output_path):
            raise RuntimeError(f"片段复制失败: {output_path}")
        return

    if template_cut:
        ok = extract_segment_video(
            file_path,
            clip_start,
            clip_start + clip_duration,
            output_path,
            allow_stream_copy=False,
            include_audio=False,
        )
        if not ok:
            raise RuntimeError(f"模板片段切割失败: {output_path}")
        return

    cut_asset_clip(
        file_path=file_path,
        clip_start=clip_start,
        clip_duration=clip_duration,
        output_path=output_path,
        width=width,
        height=height,
        keep_audio=keep_audio,
        output_audio_stream=keep_audio,
    )
    if not file_ok(output_path):
        raise RuntimeError(f"素材片段裁剪失败: {output_path}")


def _capcut_transition(slot: dict[str, Any]) -> tuple[str | None, int]:
    transition = slot.get("transition_out") or slot.get("transitionOut")
    if not transition:
        return None, 500_000
    resolved = resolve_transition(transition if isinstance(transition, dict) else {"type": transition})
    ffmpeg_name = str(resolved.get("ffmpeg") or "fade")
    duration_us = _us(float(resolved.get("duration") or 0.3))
    duration_us = min(max(duration_us, 100_000), 2_500_000)
    return _CAPCUT_TRANSITION_MAP.get(ffmpeg_name, "fade"), duration_us


def _slot_template_range(slot: dict[str, Any]) -> tuple[float, float]:
    """槽位在模板原片上的起止秒（用于挂载 subtitle_segments）。"""
    if slot.get("start") is not None:
        start = float(slot["start"])
        if slot.get("end") is not None:
            return start, float(slot["end"])
        if slot.get("end_time") is not None:
            return start, float(slot["end_time"])
        return start, start + _slot_duration(slot)

    clip_start = _template_clip_start(slot)
    duration = _slot_duration(slot)
    return clip_start, clip_start + duration


def _parse_srt_time(raw: str) -> float:
    text = str(raw or "").strip().replace(",", ".")
    parts = text.split(":")
    if len(parts) != 3:
        return 0.0
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def _parse_srt_file(path: str) -> list[dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
    except Exception:
        return []

    import re

    blocks = re.split(r"\n\s*\n", content.strip())
    segments: list[dict[str, Any]] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        time_line = lines[1] if "-->" in lines[1] else lines[0]
        text_lines = lines[2:] if "-->" in lines[1] else lines[1:]
        if "-->" not in time_line:
            continue
        start_raw, end_raw = [part.strip() for part in time_line.split("-->", 1)]
        text = " ".join(text_lines).strip()
        if not text:
            continue
        start = _parse_srt_time(start_raw)
        end = _parse_srt_time(end_raw)
        if end <= start:
            continue
        segments.append(
            {
                "start": start,
                "end": end,
                "duration": end - start,
                "text": text,
            }
        )
    return segments


def _load_template_subtitle_segments(template) -> list[dict[str, Any]]:
    segments = getattr(template, "segments_json", None) or []
    if segments:
        return [dict(seg) for seg in segments if isinstance(seg, dict)]

    srt_path = str(getattr(template, "subtitle_srt_path", "") or "").strip()
    if srt_path:
        try:
            abs_path = (
                srt_path
                if os.path.isabs(srt_path)
                else ensure_storage_subpath(srt_path.lstrip("/"))
            )
            parsed = _parse_srt_file(abs_path)
            if parsed:
                return parsed
        except Exception:
            pass
    return []


def _attach_template_subtitles_to_timeline(
    timeline: list,
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not timeline:
        return []
    if not segments:
        return [dict(s) if isinstance(s, dict) else s for s in timeline]

    result: list[dict[str, Any]] = []
    for slot in timeline:
        if not isinstance(slot, dict):
            continue
        item = dict(slot)
        range_start, range_end = _slot_template_range(item)
        texts: list[str] = []
        related: list[dict[str, Any]] = []
        for seg in segments:
            seg_start = float(seg.get("start", 0))
            seg_end = float(seg.get("end", seg_start))
            if max(range_start, seg_start) >= min(range_end, seg_end):
                continue
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            texts.append(text)
            related.append(dict(seg))
        item["subtitle_text"] = " ".join(texts).strip()
        item["subtitle_segments"] = related
        result.append(item)
    return result


def _collect_captions_for_slot(
    slot: dict[str, Any],
    *,
    timeline_start_us: int,
    clip_duration_sec: float,
    source_range_start: float,
) -> list[dict[str, Any]]:
    captions: list[dict[str, Any]] = []
    clip_duration_us = _us(clip_duration_sec)
    sub_segs = slot.get("subtitle_segments") or []

    if sub_segs:
        for seg in sub_segs:
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            seg_start = float(seg.get("start", source_range_start))
            seg_end = float(seg.get("end", seg_start + 0.5))
            rel_start = max(0.0, seg_start - source_range_start)
            rel_end = min(
                clip_duration_sec,
                max(rel_start + 0.08, seg_end - source_range_start),
            )
            captions.append(
                {
                    "start": timeline_start_us + _us(rel_start),
                    "end": timeline_start_us + _us(rel_end),
                    "text": text,
                    "style": seg.get("style") or {},
                }
            )
        return captions

    subtitle_text = str(slot.get("subtitle_text") or "").strip()
    if subtitle_text:
        captions.append(
            {
                "start": timeline_start_us + _us(0.05),
                "end": timeline_start_us + max(_us(0.2), clip_duration_us - _us(0.05)),
                "text": subtitle_text,
                "style": slot.get("subtitle_style") or {},
            }
        )
    return captions


def _add_styled_captions_to_draft(
    draft_url: str,
    captions: list[dict[str, Any]],
    warnings: list[str],
) -> str:
    if not captions:
        return draft_url

    groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for cap in captions:
        style = cap.get("style") if isinstance(cap.get("style"), dict) else {}
        key = style_signature(style) if style else "default"
        groups.setdefault(key, []).append((cap, style))

    for items in groups.values():
        style = items[0][1] if items else {}
        params = style_to_capcut_params(style)
        payload = [
            {"start": c["start"], "end": c["end"], "text": c["text"]}
            for c, _ in items
        ]
        try:
            cap_resp = add_captions(draft_url, payload, **params)
            draft_url = cap_resp.get("draft_url") or draft_url
        except Exception as exc:
            warnings.append(f"字幕添加失败：{exc}")

    return draft_url


def _add_sfx_to_draft(
    draft_url: str,
    template,
    media_base: str,
    warnings: list[str],
) -> str:
    sfx_markers = getattr(template, "sfx_markers", None) or []
    if not sfx_markers:
        return draft_url

    audio_infos: list[dict[str, Any]] = []
    for sfx in sfx_markers:
        if not isinstance(sfx, dict):
            continue
        clip_path = str(sfx.get("clip_path") or "").strip()
        if not clip_path:
            continue
        try:
            audio_abs = (
                clip_path
                if os.path.isabs(clip_path)
                else ensure_storage_subpath(clip_path.lstrip("/"))
            )
        except Exception:
            audio_abs = clip_path.replace("/", os.sep)
        if not os.path.isfile(audio_abs):
            continue

        media_url = build_public_media_url(_storage_relative(audio_abs), media_base)
        ok, reason = verify_media_url(media_url)
        if not ok:
            warnings.append(f"音效「{sfx.get('type', 'sfx')}」URL 不可访问：{reason}")
            continue

        start_us = _us(float(sfx.get("time", 0)))
        dur_us = _us(float(sfx.get("clip_duration") or sfx.get("duration") or 0.2))
        audio_infos.append(
            {
                "audio_url": media_url,
                "start": start_us,
                "end": start_us + max(_us(0.08), dur_us),
                "volume": float(sfx.get("volume") or 0.85),
            }
        )

    if not audio_infos:
        return draft_url

    try:
        audio_resp = add_audios(draft_url, audio_infos)
        draft_url = audio_resp.get("draft_url") or draft_url
    except Exception as exc:
        warnings.append(f"音效轨添加失败：{exc}")

    return draft_url


def _enrich_timeline_subtitles(timeline: list, template) -> list[dict[str, Any]]:
    """可替换模板导出：用模板全局字幕补全槽位 subtitle_segments。"""
    if not timeline:
        return []

    segments = _load_template_subtitle_segments(template)
    return _attach_template_subtitles_to_timeline(timeline, segments)


def _clear_draft_cover(draft_id: str) -> None:
    """导出草稿不写封面帧，避免剪映成片自动带封面。"""
    if not draft_id:
        return
    mate_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "capcut-mate", "output", "draft")
    )
    for name in ("draft_content.json", "draft_info.json"):
        path = os.path.join(mate_root, draft_id, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                continue
            data["cover"] = None
            data["retouch_cover"] = None
            data["static_cover_image_path"] = ""
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=4)
        except Exception:
            pass


def _slot_label(slot: dict[str, Any], index: int) -> str:
    parts = [f"【槽位{index + 1}】"]
    desc = str(slot.get("ai_description") or slot.get("shot_type") or slot.get("name") or "").strip()
    if desc:
        parts.append(desc[:20])
    tags = slot.get("scene_tags") or slot.get("tags") or []
    if tags:
        tag_text = ",".join(str(tag) for tag in tags[:2])
        if tag_text:
            parts.append(tag_text[:12])
    return " ".join(parts)[:40]


def _slot_use_asset_audio(slot: dict[str, Any], mix: dict[str, Any]) -> bool:
    if not mix.get("use_asset_audio"):
        return False
    if slot.get("use_original_audio") is False:
        return False
    if slot.get("use_original_audio") is True:
        return True
    return bool(mix.get("use_asset_audio"))


def _report_progress(
    task_id: str | None,
    progress: int,
    message: str,
    *,
    reporter: Callable[[int, str], None] | None = None,
) -> None:
    progress = max(0, min(100, int(progress)))
    if reporter:
        reporter(progress, message)
    if task_id:
        from services.task_queue import update_task

        update_task(task_id, status="running", progress=progress, message=message)


def export_timeline_to_capcut_draft(
    *,
    timeline: list,
    template,
    resolution: str = "1080x1920",
    media_base_url: str = "",
    template_music_enabled: bool = True,
    use_asset_audio: bool = False,
    asset_audio_volume: float = 0.3,
    template_audio_volume: float = 1.0,
    add_subtitles: bool = True,
    track_controls: Optional[dict[str, Any]] = None,
    include_template_slots: bool = True,
    capcut_export_mode: Literal["filled", "replaceable_template"] | str = "filled",
    task_id: str | None = None,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """
    裁剪片段 → 调用 CapCut Mate 创建草稿。
    media_base_url: CapCut Mate 能访问到的本服务地址，如 http://192.168.1.10:8000
    """
    if not timeline:
        raise RuntimeError("时间线为空，无法导出剪映草稿")

    def progress(p: int, msg: str) -> None:
        _report_progress(task_id, p, msg, reporter=on_progress)

    progress(3, "准备导出剪映草稿")

    require_capcut_mate()
    ensure_ffmpeg()
    width, height = _parse_resolution(resolution)
    media_base = resolve_public_media_base(media_base_url)

    mix = resolve_export_mix(
        track_controls,
        template_music_enabled=template_music_enabled,
        use_asset_audio=use_asset_audio,
        asset_audio_volume=asset_audio_volume,
        template_audio_volume=template_audio_volume,
        add_subtitles=add_subtitles,
    )

    template_video_path = ""
    if getattr(template, "file_path", ""):
        try:
            template_video_path = ensure_storage_subpath(template.file_path)
        except Exception:
            template_video_path = ""

    replaceable_mode = capcut_export_mode == "replaceable_template"
    if replaceable_mode and not template_video_path:
        raise RuntimeError("可替换模板模式需要模板原视频，请确认模板已上传并处理完成")

    if replaceable_mode and template_video_path:
        native = _probe_video_size(template_video_path)
        if native:
            width, height = native

    export_timeline = (
        _enrich_timeline_subtitles(timeline, template) if replaceable_mode else timeline
    )
    template_voice_source = ""
    if replaceable_mode:
        voice_raw = get_whisper_source_path(template) or template_video_path
        try:
            template_voice_source = (
                voice_raw
                if os.path.isabs(voice_raw)
                else ensure_storage_subpath(str(voice_raw).lstrip("/"))
            )
        except Exception:
            template_voice_source = template_video_path
        if not os.path.isfile(template_voice_source):
            template_voice_source = template_video_path

    job_id = uuid.uuid4().hex[:12]
    work_dir = os.path.join("storage", "temp", "capcut_drafts", job_id)
    os.makedirs(work_dir, exist_ok=True)

    video_infos: list[dict[str, Any]] = []
    scene_timelines: list[dict[str, int]] = []
    captions: list[dict[str, Any]] = []
    slot_audio_infos: list[dict[str, Any]] = []
    slot_manifest_entries: list[dict[str, Any]] = []
    skipped: list[str] = []
    warnings: list[str] = []
    cursor_sec = 0.0

    planned: list[dict[str, Any]] = []
    for index, slot in enumerate(export_timeline):
        if not isinstance(slot, dict):
            continue

        has_asset = bool(slot.get("asset_id") or slot.get("asset_file_path") or slot.get("segment_file_path"))
        if not replaceable_mode and not has_asset and not include_template_slots:
            skipped.append(f"槽位 {slot.get('slot_id', index + 1)} 未匹配素材")
            continue

        source = _resolve_slot_source(
            slot,
            template_video_path=template_video_path,
            template_only=replaceable_mode,
        )
        if not source:
            skipped.append(f"槽位 {slot.get('slot_id', index + 1)} 无可用视频源")
            continue

        file_path, clip_start, clip_duration = source
        slot_abs_start = float(slot.get("slot_start") if slot.get("slot_start") is not None else cursor_sec)
        out_name = f"clip_{index:03d}.mp4"
        out_abs = os.path.join(work_dir, out_name)
        keep_audio = False if replaceable_mode else _slot_use_asset_audio(slot, mix)
        reuse_segment = _can_reuse_segment_file(slot, file_path, clip_start, keep_audio)
        audio_abs = os.path.join(work_dir, f"audio_{index:03d}.m4a")

        planned.append(
            {
                "index": index,
                "slot": slot,
                "file_path": file_path,
                "clip_start": clip_start,
                "clip_duration": clip_duration,
                "slot_abs_start": slot_abs_start,
                "out_name": out_name,
                "out_abs": out_abs,
                "audio_abs": audio_abs,
                "cursor_sec": cursor_sec,
                "keep_audio": keep_audio,
                "reuse_segment": reuse_segment,
                "template_cut": replaceable_mode and not reuse_segment,
            }
        )
        cursor_sec += clip_duration

    progress(8, f"计划导出 {len(planned)} 个片段")

    cut_done = 0
    total_planned = max(1, len(planned))

    def _cut_planned(item: dict[str, Any]) -> dict[str, Any]:
        _prepare_slot_clip(
            file_path=item["file_path"],
            clip_start=item["clip_start"],
            clip_duration=item["clip_duration"],
            output_path=item["out_abs"],
            width=width,
            height=height,
            keep_audio=item["keep_audio"],
            reuse_segment=item["reuse_segment"],
            template_cut=item.get("template_cut", False),
        )
        if replaceable_mode and template_voice_source:
            extract_segment_audio(
                template_voice_source,
                item["clip_start"],
                item["clip_duration"],
                item["audio_abs"],
            )
        return item

    cut_failures: list[str] = []
    workers = min(SEGMENT_CUT_WORKERS, max(1, len(planned)))
    if planned:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_cut_planned, item): item for item in planned}
            for fut in as_completed(futures):
                item = futures[fut]
                slot = item["slot"]
                index = item["index"]
                try:
                    fut.result()
                    cut_done += 1
                    progress(
                        8 + int(32 * cut_done / total_planned),
                        f"裁剪片段 {cut_done}/{total_planned}",
                    )
                except Exception as exc:
                    cut_failures.append(
                        f"槽位 {slot.get('slot_id', index + 1)} 裁剪失败：{exc}"
                    )

    if cut_failures:
        skipped.extend(cut_failures)

    media_access_verified = False
    for item in sorted(planned, key=lambda x: x["index"]):
        slot = item["slot"]
        index = item["index"]
        out_abs = item["out_abs"]
        if not file_ok(out_abs):
            continue

        clip_duration = item["clip_duration"]
        clip_start = item["clip_start"]
        cursor_sec = item["cursor_sec"]
        slot_abs_start = item["slot_abs_start"]
        keep_audio = item["keep_audio"]
        out_name = item["out_name"]

        media_url = build_capcut_clip_url(out_abs, media_base)
        media_url = ensure_http_video_url(media_url, media_base)
        if not media_access_verified:
            if is_local_capcut_url(media_url):
                media_access_verified = True
            else:
                ok, reason = verify_media_url(media_url)
                if not ok:
                    raise RuntimeError(
                        f"CapCut Mate 无法访问素材 URL（{media_url}）：{reason}。"
                        f"请将 PUBLIC_MEDIA_BASE_URL 设为 {media_base} 并确保后端可从本机访问。"
                    )
                media_access_verified = True

        start_us = _us(cursor_sec)
        end_us = _us(cursor_sec + clip_duration)
        speed = float(slot.get("speed") or 1.0)
        if speed <= 0:
            speed = 1.0

        video_item: dict[str, Any] = {
            "video_url": media_url,
            "width": width,
            "height": height,
            "start": start_us,
            "end": end_us,
            "duration": end_us - start_us,
            "volume": float(slot.get("asset_audio_volume") or mix.get("asset_audio_volume") or 0.3)
            if keep_audio
            else 0.0,
        }
        if not replaceable_mode and index < len(export_timeline) - 1:
            trans_name, trans_dur = _capcut_transition(slot)
            if trans_name:
                video_item["transition"] = trans_name
                video_item["transition_duration"] = trans_dur
        video_infos.append(video_item)

        if abs(speed - 1.0) > 0.01:
            scene_timelines.append(
                {
                    "start": start_us,
                    "end": start_us + max(1, int((end_us - start_us) / speed)),
                }
            )
        else:
            scene_timelines.append({"start": start_us, "end": end_us})

        if replaceable_mode:
            label = _slot_label(slot, index)
            slot_manifest_entries.append(
                {
                    "slot_id": slot.get("slot_id") or f"slot_{index + 1}",
                    "index": index,
                    "label": label,
                    "duration_sec": round(clip_duration, 3),
                    "clip_file": out_name,
                    "clip_url": media_url,
                    "timeline_start_sec": round(cursor_sec, 3),
                    "template_start_sec": round(clip_start, 3),
                    "description": slot.get("ai_description") or slot.get("shot_type"),
                    "tags": slot.get("scene_tags") or slot.get("tags") or [],
                }
            )
            captions.extend(
                _collect_captions_for_slot(
                    slot,
                    timeline_start_us=start_us,
                    clip_duration_sec=clip_duration,
                    source_range_start=clip_start,
                )
            )
            audio_abs = item.get("audio_abs") or ""
            if audio_abs and file_ok(audio_abs):
                audio_url = ensure_http_video_url(
                    build_public_media_url(_storage_relative(audio_abs), media_base),
                    media_base,
                )
                slot_audio_infos.append(
                    {
                        "audio_url": audio_url,
                        "start": start_us,
                        "end": end_us,
                        "volume": float(mix.get("template_audio_volume") or 1.0),
                    }
                )
        elif mix.get("add_subtitles"):
            captions.extend(
                _collect_captions_for_slot(
                    slot,
                    timeline_start_us=start_us,
                    clip_duration_sec=clip_duration,
                    source_range_start=clip_start,
                )
            )

    if not video_infos:
        detail = "没有可导出的视频片段"
        if skipped:
            detail += "：" + "；".join(skipped[:5])
        raise RuntimeError(detail)

    if replaceable_mode and not captions:
        seg_count = len(_load_template_subtitle_segments(template))
        if seg_count == 0:
            warnings.append("模板尚无字幕数据，请等待模板处理完成或重新上传模板")
        else:
            warnings.append("字幕未能匹配到槽位，请检查槽位 clip_start 是否与模板时间轴一致")

    progress(42, "创建剪映草稿")
    require_capcut_mate()
    draft_resp = create_draft(width, height)
    draft_url = draft_resp.get("draft_url") or ""
    if not draft_url:
        raise RuntimeError("剪映小助手未返回 draft_url，请查看 CapCut Mate 日志")

    batch_size = max(1, ADD_VIDEOS_BATCH_SIZE)

    def _on_video_batch(done_batches: int, total_batches: int) -> None:
        span_start = 45
        span_end = 82
        ratio = done_batches / max(1, total_batches)
        pct = span_start + int((span_end - span_start) * ratio)
        progress(pct, f"写入剪映草稿 {done_batches}/{total_batches} 批")

    video_resp = add_videos(
        draft_url,
        video_infos,
        scene_timelines=scene_timelines if len(scene_timelines) == len(video_infos) else None,
        on_batch=lambda done, total: _on_video_batch(done, total),
    )
    draft_url = video_resp.get("draft_url") or draft_url

    if replaceable_mode and slot_audio_infos:
        progress(84, "添加原视频人声")
        try:
            audio_resp = add_audios(draft_url, slot_audio_infos)
            draft_url = audio_resp.get("draft_url") or draft_url
        except Exception as exc:
            warnings.append(f"原视频人声添加失败：{exc}")
    elif not replaceable_mode:
        template_audio_path = getattr(template, "audio_path", "") or ""
        if mix.get("template_audio_volume", 0) > 0 and template_audio_path:
            try:
                audio_abs = ensure_storage_subpath(template_audio_path)
                if os.path.isfile(audio_abs):
                    audio_url = build_public_media_url(_storage_relative(audio_abs), media_base)
                    ok, reason = verify_media_url(audio_url)
                    if not ok:
                        warnings.append(f"模板 BGM URL 不可访问：{reason}")
                    else:
                        total_us = _us(cursor_sec)
                        audio_resp = add_audios(
                            draft_url,
                            [
                                {
                                    "audio_url": audio_url,
                                    "start": 0,
                                    "end": total_us,
                                    "volume": float(mix.get("template_audio_volume") or 1.0),
                                }
                            ],
                        )
                        draft_url = audio_resp.get("draft_url") or draft_url
            except Exception as exc:
                warnings.append(f"模板 BGM 添加失败：{exc}")

    if not replaceable_mode:
        draft_url = _add_sfx_to_draft(draft_url, template, media_base, warnings)

    if captions:
        progress(86, "添加字幕")
        draft_url = _add_styled_captions_to_draft(draft_url, captions, warnings)

    progress(95, "保存剪映草稿")
    save_resp = save_draft(draft_url, clip_count=len(video_infos))
    draft_url = save_resp.get("draft_url") or draft_url

    draft_id = extract_draft_id(draft_url)
    _clear_draft_cover(draft_id)
    draft_files = get_draft_files(draft_id)

    replace_guide = (
        "在剪映中：选中时间轴上的占位片段 → 右键「替换素材」或点击工具栏替换按钮，"
        "选择你的成片视频即可逐段替换。字幕与人声已按槽位对齐。"
    )
    slot_manifest: dict[str, Any] | None = None
    slot_manifest_url = ""
    if replaceable_mode and slot_manifest_entries:
        slot_manifest = {
            "mode": "replaceable_template",
            "export_version": 1,
            "duration_sec": round(cursor_sec, 3),
            "clips_count": len(slot_manifest_entries),
            "replace_guide": replace_guide,
            "slots": slot_manifest_entries,
        }
        manifest_abs = os.path.join(work_dir, "slot_manifest.json")
        with open(manifest_abs, "w", encoding="utf-8") as manifest_file:
            json.dump(slot_manifest, manifest_file, ensure_ascii=False, indent=2)
        slot_manifest_url = build_public_media_url(_storage_relative(manifest_abs), media_base)

    open_hint = (
        "导出成功后，请点击 draft_url 链接（需已安装剪映 PC 版与剪映小助手）。"
        "不要手动新建空白草稿；链接会在剪映中打开已排好片段的项目。"
    )
    if replaceable_mode:
        open_hint += " 打开后逐段「替换素材」即可套用你的成片，字幕与人声已按槽位分割对齐。"

    progress(100, "剪映草稿生成完成")
    draft_url = normalize_draft_url(draft_url)
    return {
        "draft_url": draft_url,
        "draft_id": draft_id,
        "clips_count": len(video_infos),
        "captions_count": len(captions),
        "duration_sec": round(cursor_sec, 3),
        "skipped_slots": skipped,
        "warnings": warnings,
        "media_base_url": media_base,
        "work_dir": work_dir.replace("\\", "/"),
        "tip_url": draft_resp.get("tip_url", ""),
        "draft_files_count": len(draft_files),
        "capcut_export_mode": "replaceable_template" if replaceable_mode else "filled",
        "slot_manifest": slot_manifest,
        "slot_manifest_url": slot_manifest_url,
        "replace_guide": replace_guide if replaceable_mode else "",
        "open_hint": open_hint,
    }
