"""将项目时间轴导出为 CapCut Mate 剪映草稿。"""

import json
import os
import uuid
from typing import Any, Literal, Optional

from services.capcut_mate_client import (
    add_audios,
    add_captions,
    add_videos,
    create_draft,
    extract_draft_id,
    get_draft_files,
    require_capcut_mate,
    save_draft,
)
from services.transitions import resolve_transition
from services.video_exporter import cut_asset_clip, ensure_ffmpeg, file_ok
from utils.export_controls import resolve_export_mix
from utils.public_media import build_public_media_url, resolve_public_media_base, verify_media_url
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


def _storage_relative(abs_path: str) -> str:
    norm = abs_path.replace("\\", "/")
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
            clip_start = float(slot.get("slot_start") or slot.get("start") or 0)
            return template_video_path, clip_start, duration
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
        clip_start = float(slot.get("slot_start") or slot.get("start") or 0)
        return template_video_path, clip_start, duration
    return None


def _capcut_transition(slot: dict[str, Any]) -> tuple[str | None, int]:
    transition = slot.get("transition_out") or slot.get("transitionOut")
    if not transition:
        return None, 500_000
    resolved = resolve_transition(transition if isinstance(transition, dict) else {"type": transition})
    ffmpeg_name = str(resolved.get("ffmpeg") or "fade")
    duration_us = _us(float(resolved.get("duration") or 0.3))
    duration_us = min(max(duration_us, 100_000), 2_500_000)
    return _CAPCUT_TRANSITION_MAP.get(ffmpeg_name, "fade"), duration_us


def _collect_captions_for_slot(
    slot: dict[str, Any],
    *,
    timeline_start_us: int,
    clip_duration_sec: float,
    slot_abs_start: float,
) -> list[dict[str, Any]]:
    captions: list[dict[str, Any]] = []
    clip_duration_us = _us(clip_duration_sec)
    sub_segs = slot.get("subtitle_segments") or []

    if sub_segs:
        for seg in sub_segs:
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            seg_start = float(seg.get("start", slot_abs_start))
            seg_end = float(seg.get("end", seg_start + 0.5))
            rel_start = max(0.0, seg_start - slot_abs_start)
            rel_end = min(clip_duration_sec, max(rel_start + 0.08, seg_end - slot_abs_start))
            captions.append(
                {
                    "start": timeline_start_us + _us(rel_start),
                    "end": timeline_start_us + _us(rel_end),
                    "text": text,
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
            }
        )
    return captions


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
) -> dict[str, Any]:
    """
    裁剪片段 → 调用 CapCut Mate 创建草稿。
    media_base_url: CapCut Mate 能访问到的本服务地址，如 http://192.168.1.10:8000
    """
    if not timeline:
        raise RuntimeError("时间线为空，无法导出剪映草稿")

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

    job_id = uuid.uuid4().hex[:12]
    work_dir = os.path.join("storage", "temp", "capcut_drafts", job_id)
    os.makedirs(work_dir, exist_ok=True)

    video_infos: list[dict[str, Any]] = []
    scene_timelines: list[dict[str, int]] = []
    captions: list[dict[str, Any]] = []
    slot_label_captions: list[dict[str, Any]] = []
    slot_manifest_entries: list[dict[str, Any]] = []
    skipped: list[str] = []
    warnings: list[str] = []
    cursor_sec = 0.0

    for index, slot in enumerate(timeline):
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
        cut_asset_clip(
            file_path=file_path,
            clip_start=clip_start,
            clip_duration=clip_duration,
            output_path=out_abs,
            width=width,
            height=height,
            keep_audio=keep_audio,
            output_audio_stream=keep_audio,
        )
        if not file_ok(out_abs):
            skipped.append(f"槽位 {slot.get('slot_id', index + 1)} 裁剪失败")
            continue

        media_url = build_public_media_url(_storage_relative(out_abs), media_base)
        ok, reason = verify_media_url(media_url)
        if not ok:
            raise RuntimeError(
                f"CapCut Mate 无法访问素材 URL（{media_url}）：{reason}。"
                f"请将 PUBLIC_MEDIA_BASE_URL 设为 {media_base} 并确保后端可从本机访问。"
            )

        start_us = _us(cursor_sec)
        end_us = _us(cursor_sec + clip_duration)
        speed = float(slot.get("speed") or 1.0)
        if speed <= 0:
            speed = 1.0

        item: dict[str, Any] = {
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
        if index < len(timeline) - 1:
            trans_name, trans_dur = _capcut_transition(slot)
            if trans_name:
                item["transition"] = trans_name
                item["transition_duration"] = trans_dur
        video_infos.append(item)

        if abs(speed - 1.0) > 0.01:
            scene_timelines.append(
                {
                    "start": start_us,
                    "end": start_us + max(1, int((end_us - start_us) / speed)),
                }
            )
        else:
            scene_timelines.append({"start": start_us, "end": end_us})

        clip_duration_us = _us(clip_duration)

        if replaceable_mode:
            label = _slot_label(slot, index)
            slot_label_captions.append(
                {
                    "start": start_us + _us(0.08),
                    "end": start_us + max(_us(0.5), clip_duration_us - _us(0.08)),
                    "text": label,
                }
            )
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
            if mix.get("add_subtitles"):
                captions.extend(
                    _collect_captions_for_slot(
                        slot,
                        timeline_start_us=start_us,
                        clip_duration_sec=clip_duration,
                        slot_abs_start=slot_abs_start,
                    )
                )
        elif mix.get("add_subtitles"):
            captions.extend(
                _collect_captions_for_slot(
                    slot,
                    timeline_start_us=start_us,
                    clip_duration_sec=clip_duration,
                    slot_abs_start=slot_abs_start,
                )
            )

        cursor_sec += clip_duration

    if not video_infos:
        detail = "没有可导出的视频片段"
        if skipped:
            detail += "：" + "；".join(skipped[:5])
        raise RuntimeError(detail)

    draft_resp = create_draft(width, height)
    draft_url = draft_resp.get("draft_url") or ""
    if not draft_url:
        raise RuntimeError("剪映小助手未返回 draft_url")

    video_resp = add_videos(
        draft_url,
        video_infos,
        scene_timelines=scene_timelines if len(scene_timelines) == len(video_infos) else None,
    )
    draft_url = video_resp.get("draft_url") or draft_url

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

    if captions:
        try:
            cap_resp = add_captions(draft_url, captions)
            draft_url = cap_resp.get("draft_url") or draft_url
        except Exception as exc:
            warnings.append(f"字幕添加失败：{exc}")

    if slot_label_captions:
        try:
            cap_resp = add_captions(
                draft_url,
                slot_label_captions,
                text_color="#face15",
                font_size=22,
                transform_y=720,
            )
            draft_url = cap_resp.get("draft_url") or draft_url
        except Exception as exc:
            warnings.append(f"槽位标签添加失败：{exc}")

    save_resp = save_draft(draft_url)
    draft_url = save_resp.get("draft_url") or draft_url

    draft_id = extract_draft_id(draft_url)
    draft_files = get_draft_files(draft_id)

    replace_guide = (
        "在剪映中：选中时间轴上的占位片段 → 右键「替换素材」或点击工具栏替换按钮，"
        "选择你的成片视频即可逐段替换。黄色标签标示槽位编号与描述。"
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
        open_hint += " 打开后按黄色槽位标签逐段「替换素材」即可套用你的成片。"

    return {
        "draft_url": draft_url,
        "draft_id": draft_id,
        "clips_count": len(video_infos),
        "captions_count": len(captions) + len(slot_label_captions),
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
