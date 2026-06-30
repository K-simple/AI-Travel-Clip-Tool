"""EDL 多轨合成导出 — 支持 V1/V2/V3 叠层、转场、特效、多音频轨。"""

import json
import os
import subprocess
import uuid
from typing import Any, Dict, List, Optional, Tuple

from services.effects_engine import compile_clip_filters
from services.transitions import resolve_transition
from services.subtitle_render import build_ass_from_timeline_slots, make_template_subtitle_if_needed, write_ass
from services.video_exporter import (
    add_template_audio,
    burn_subtitles,
    cut_asset_clip,
    ensure_ffmpeg,
    file_ok,
    has_audio_stream,
    run_cmd,
    select_template_audio_source,
)
from utils.security import resolve_storage_path


def _clip_asset_path(clip: Dict[str, Any]) -> str:
    return (
        clip.get("asset_file_path")
        or clip.get("file_path")
        or clip.get("source_path")
        or ""
    )


def _render_clip_file(
    clip: Dict[str, Any],
    output_path: str,
    width: int,
    height: int,
    keep_audio: bool,
) -> bool:
    raw = _clip_asset_path(clip)
    if not raw:
        return False
    try:
        path = resolve_storage_path(raw)
    except ValueError:
        return False
    if not os.path.exists(path):
        return False

    src_in = float(clip.get("src_in", clip.get("clip_start", 0)))
    src_out = float(clip.get("src_out", src_in + float(clip.get("duration", 2))))
    duration = max(0.1, src_out - src_in)
    vf = compile_clip_filters(clip, width, height)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(src_in),
        "-i", path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
    ]
    if keep_audio and has_audio_stream(path):
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]
    cmd.append(output_path)
    try:
        run_cmd(cmd)
        return file_ok(output_path)
    except Exception as exc:
        print(f"渲染片段失败: {exc}")
        return False


def _concat_with_xfade(
    clip_paths: List[str],
    transitions: List[Optional[Dict]],
    output_path: str,
    width: int,
    height: int,
) -> str:
    if not clip_paths:
        raise RuntimeError("无视频片段")
    if len(clip_paths) == 1:
        import shutil
        shutil.copy2(clip_paths[0], output_path)
        return output_path

    # 构建 xfade filter_complex
    inputs = []
    for p in clip_paths:
        inputs.extend(["-i", p])

    filters = []
    prev = "[0:v]"
    offset = 0.0
    # 获取各段时长
    durations = []
    for p in clip_paths:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", p,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        try:
            durations.append(float(r.stdout.strip()))
        except ValueError:
            durations.append(2.0)

    for i in range(1, len(clip_paths)):
        tr = resolve_transition(transitions[i - 1] if i - 1 < len(transitions) else None)
        tdur = tr["duration"]
        offset += durations[i - 1] - tdur
        out = f"[v{i}]" if i < len(clip_paths) - 1 else "[vout]"
        filters.append(
            f"{prev}[{i}:v]xfade=transition={tr['ffmpeg']}:duration={tdur}:offset={max(0, offset)}{out}"
        )
        prev = out

    filter_str = ";".join(filters)
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", filter_str, "-map", "[vout]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", output_path]
    try:
        run_cmd(cmd)
    except Exception as exc:
        print(f"xfade 失败，回退 concat: {exc}")
        from services.video_exporter import concat_clips
        concat_clips(clip_paths, output_path)
    return output_path


def _overlay_tracks(
    base_path: str,
    overlay_clips: List[Tuple[str, float, float]],
    output_path: str,
    width: int,
    height: int,
) -> str:
    if not overlay_clips:
        import shutil
        shutil.copy2(base_path, output_path)
        return output_path

    inputs = ["-i", base_path]
    for path, _, _ in overlay_clips:
        inputs.extend(["-i", path])

    chain = "[0:v]"
    for idx, (_, start, end) in enumerate(overlay_clips):
        inp = idx + 1
        out = f"[ov{idx}]"
        enable = f"between(t,{start},{end})"
        chain = f"{chain}[{inp}:v]overlay=0:0:enable='{enable}'{out}"
    filter_str = chain

    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", filter_str, "-map", f"[ov{len(overlay_clips)-1}]", "-c:v", "libx264", "-preset", "veryfast", output_path]
    try:
        run_cmd(cmd)
        return output_path
    except Exception as exc:
        print(f"叠层失败: {exc}")
        import shutil
        shutil.copy2(base_path, output_path)
        return output_path


def _build_ass_from_edl(edl: Dict[str, Any], temp_dir: str, width: int, height: int) -> Optional[str]:
    tracks = edl.get("tracks", {})
    sub_tracks = tracks.get("subtitle") or []
    segments = []
    for track in sub_tracks:
        for clip in track.get("clips") or []:
            text = (clip.get("text") or "").strip()
            if not text:
                continue
            segments.append({
                "start": float(clip.get("dst_in", 0)),
                "end": float(clip.get("dst_out", 0)),
                "text": text,
            })
    if not segments:
        return None
    out = os.path.join(temp_dir, "edl_subtitle.ass")
    write_ass(segments, out, width=width, height=height)
    return out


def export_from_edl(
    edl: Dict[str, Any],
    output_path: str,
    *,
    template_video_path: str = "",
    template_audio_path: str = "",
    template_subtitle_srt_path: str = "",
    template_subtitle_ass_path: str = "",
    template_segments_json=None,
    timeline_fallback: Optional[list] = None,
    track_controls: Optional[Dict[str, Any]] = None,
    add_subtitles: bool = True,
    template_audio_volume: float = 1.0,
    use_asset_audio: bool = False,
    asset_audio_volume: float = 0.3,
    include_overlay: bool = True,
    include_video2: bool = True,
    video_codec: str = "libx264",
    resolution: str = "1080x1920",
) -> str:
    ensure_ffmpeg()
    width, height = [int(x) for x in resolution.split("x")]
    temp_dir = os.path.join("storage", "temp", f"edl_{uuid.uuid4().hex}")
    os.makedirs(temp_dir, exist_ok=True)

    tracks = edl.get("tracks") or {}
    video_tracks = tracks.get("video") or []
    tc = track_controls or {}

    try:
        # V1 主轨
        main_clips = []
        transitions = []
        if video_tracks:
            v1 = video_tracks[0].get("clips") or []
            for i, clip in enumerate(v1):
                if tc.get("video", {}).get("visible") is False:
                    continue
                out = os.path.join(temp_dir, f"v1_{i:03d}.mp4")
                if _render_clip_file(clip, out, width, height, keep_audio=False):
                    main_clips.append(out)
                    transitions.append(clip.get("transition_out"))

        if not main_clips and timeline_fallback:
            for i, slot in enumerate(timeline_fallback):
                if tc.get("video", {}).get("visible") is False:
                    break
                if not slot.get("asset_id"):
                    continue
                out = os.path.join(temp_dir, f"slot_{i:03d}.mp4")
                cut_asset_clip(
                    file_path=resolve_storage_path(slot.get("asset_file_path", "")),
                    clip_start=float(slot.get("clip_start", 0)),
                    clip_duration=float(slot.get("slot_duration", slot.get("duration", 2))),
                    output_path=out,
                    width=width,
                    height=height,
                    keep_audio=False,
                )
                if file_ok(out):
                    main_clips.append(out)
                    transitions.append(slot.get("transition_out"))

        if not main_clips:
            raise RuntimeError("EDL 无可用视频片段")

        merged = os.path.join(temp_dir, "merged_v1.mp4")
        _concat_with_xfade(main_clips, transitions, merged, width, height)

        # V2/V3 叠层
        overlay_specs: List[Tuple[str, float, float]] = []
        for ti, vtrack in enumerate(video_tracks[1:3], start=2):
            tc_key = "overlay" if ti == 2 else "video2"
            if tc.get(tc_key, {}).get("visible") is False:
                continue
            if ti == 2 and not include_overlay:
                continue
            if ti == 3 and not include_video2:
                continue
            for ci, clip in enumerate(vtrack.get("clips") or []):
                out = os.path.join(temp_dir, f"v{ti}_{ci:03d}.mp4")
                if _render_clip_file(clip, out, width, height, keep_audio=False):
                    overlay_specs.append((
                        out,
                        float(clip.get("dst_in", 0)),
                        float(clip.get("dst_out", clip.get("dst_in", 0) + 2)),
                    ))

        composited = os.path.join(temp_dir, "composited.mp4")
        _overlay_tracks(merged, overlay_specs, composited, width, height)

        # 音频
        template_audio_source = select_template_audio_source(
            template_audio_path=template_audio_path,
            template_video_path=template_video_path,
        )
        with_audio = os.path.join(temp_dir, "with_audio.mp4")
        if template_audio_source and template_audio_volume > 0:
            add_template_audio(
                video_path=composited,
                template_audio_source=template_audio_source,
                output_path=with_audio,
                use_asset_audio=use_asset_audio,
                asset_audio_volume=asset_audio_volume,
                template_audio_volume=template_audio_volume,
            )
        else:
            import shutil
            shutil.copy2(composited, with_audio)

        # 字幕
        final = output_path
        if add_subtitles and tc.get("subtitle", {}).get("visible") is not False:
            sub_path = _build_ass_from_edl(edl, temp_dir, width, height)
            if not sub_path and timeline_fallback:
                sub_path = build_ass_from_timeline_slots(timeline_fallback, temp_dir, width, height)
            if not sub_path:
                sub_path = make_template_subtitle_if_needed(
                    template_video_path=template_video_path,
                    template_subtitle_srt_path=template_subtitle_srt_path,
                    template_subtitle_ass_path=template_subtitle_ass_path,
                    template_segments_json=template_segments_json,
                    temp_dir=temp_dir,
                    width=width,
                    height=height,
                )
            if sub_path:
                burn_subtitles(with_audio, sub_path, final)
            else:
                import shutil
                shutil.copy2(with_audio, final)
        else:
            import shutil
            shutil.copy2(with_audio, final)

        # 重编码（NVENC 可选）
        if video_codec != "libx264" and file_ok(final):
            nvenc_out = os.path.join(temp_dir, "nvenc_out.mp4")
            cmd = [
                "ffmpeg", "-y", "-i", final,
                "-c:v", video_codec, "-preset", "p4", "-b:v", "12M",
                "-c:a", "copy", nvenc_out,
            ]
            try:
                run_cmd(cmd)
                import shutil
                shutil.copy2(nvenc_out, final)
            except Exception as exc:
                print(f"NVENC 重编码跳过: {exc}")

        if not file_ok(final):
            raise RuntimeError("EDL 导出失败")
        return final
    finally:
        pass
