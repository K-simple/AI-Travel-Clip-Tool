import os
import json
import uuid
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from utils.security import resolve_storage_path
from services.media_probe import has_audio_stream
from services.subtitle_render import (
    ass_escape,
    build_ass_from_timeline_slots,
    format_ass_time,
    make_template_subtitle_if_needed,
    normalize_segments,
    write_ass,
)


def run_cmd(cmd, cwd=None):
    print("执行命令:", " ".join(map(str, cmd)))

    result = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )

    if result.returncode != 0:
        raise RuntimeError(
            "命令执行失败:\n"
            + " ".join(map(str, cmd))
            + "\n\nSTDOUT:\n"
            + result.stdout
            + "\n\nSTDERR:\n"
            + result.stderr
        )

    return result


def ensure_ffmpeg():
    if not shutil.which("ffmpeg"):
        raise RuntimeError("未检测到 ffmpeg，请先安装 FFmpeg 并加入系统 PATH")

    if not shutil.which("ffprobe"):
        raise RuntimeError("未检测到 ffprobe，请先安装 FFmpeg 并加入系统 PATH")


def file_ok(path: str) -> bool:
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0


def to_bool(value) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        return value.lower() in ["1", "true", "yes", "y", "on", "开启", "是"]

    return False


def extract_audio_for_subtitle(video_path: str, wav_path: str):
    """
    从模板视频中提取给 Whisper 用的音频。
    """
    from services.media_probe import extract_whisper_wav

    extract_whisper_wav(video_path, wav_path)


def compile_slot_post_effects_vf(slot: dict[str, Any], width: int, height: int) -> str:
    """已裁好尺寸的片段上叠加调色/蒙版/变速等（不含 scale/pad）。"""
    from services.effects_engine import (
        _interp_keyframes,
        build_color_filter,
        build_mask_filter,
        build_speed_filter,
    )

    parts: list[str] = []
    speed = float(slot.get("speed") or 1.0)
    optical = bool(slot.get("optical_flow") or slot.get("opticalFlow"))
    sf = build_speed_filter(speed, use_optical_flow=optical)
    if sf:
        parts.append(sf)

    keyframes = slot.get("keyframes") or []
    if keyframes:
        scale = _interp_keyframes(keyframes, "scale", 0.0, 1.0)
        opacity = _interp_keyframes(keyframes, "opacity", 0.0, 1.0)
        if abs(scale - 1.0) > 0.01:
            parts.append(f"scale=iw*{scale}:ih*{scale}")
        if opacity < 0.99:
            parts.append(f"colorchannelmixer=aa={opacity}")

    color_grade = slot.get("color_grade") or slot.get("colorGrade")
    cf = build_color_filter(color_grade)
    if cf:
        parts.append(cf)

    mask = slot.get("mask")
    mf = build_mask_filter(mask, width, height)
    if mf:
        parts.append(mf)

    return ",".join(parts)


def slot_has_post_effects(slot: dict[str, Any]) -> bool:
    if abs(float(slot.get("speed") or 1.0) - 1.0) > 0.01:
        return True
    if slot.get("keyframes"):
        return True
    color = slot.get("color_grade") or slot.get("colorGrade") or {}
    if any(
        abs(float(color.get(k, d)) - d) > 0.01
        for k, d in (("brightness", 0), ("contrast", 1), ("saturation", 1), ("gamma", 1))
    ):
        return True
    if abs(float(color.get("hue") or 0)) > 0.01:
        return True
    mask = slot.get("mask") or {}
    if mask.get("enabled"):
        return True
    return False


def legacy_subtitle_mask_vf(height: int) -> str:
    """遮盖模板成片底部旧烧录字幕区域，避免与新字幕叠影。"""
    y = int(height * 0.72)
    bar_h = max(1, height - y)
    return f"drawbox=x=0:y={y}:w=iw:h={bar_h}:color=black@0.78:t=fill"


def burn_clip_with_vf_and_subtitles(
    video_path: str,
    output_path: str,
    *,
    ass_path: Optional[str] = None,
    extra_vf: str = "",
    mask_legacy_subtitles: bool = False,
    height: int = 1920,
) -> str:
    """对单段 MP4 重编码：可选遮罩旧字幕区 + 特效滤镜 + ASS 烧录。"""
    video_path = os.path.abspath(video_path)
    output_path = os.path.abspath(output_path)
    workdir = os.path.dirname(video_path)

    ass_name: Optional[str] = None
    if ass_path and os.path.isfile(ass_path):
        ass_name = "clip_subtitle_burn.ass"
        shutil.copy2(ass_path, os.path.join(workdir, ass_name))

    vf_parts: list[str] = []
    if mask_legacy_subtitles:
        vf_parts.append(legacy_subtitle_mask_vf(height))
    if extra_vf:
        vf_parts.append(extra_vf)
    if ass_name:
        vf_parts.append(f"subtitles={ass_name}")

    if not vf_parts:
        if video_path != output_path:
            shutil.copy2(video_path, output_path)
        return output_path

    vf = ",".join(vf_parts)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]

    try:
        run_cmd(cmd, cwd=workdir)
    finally:
        if ass_name:
            try:
                os.remove(os.path.join(workdir, ass_name))
            except OSError:
                pass

    if not file_ok(output_path):
        raise RuntimeError("片段字幕/特效烧录失败")
    return output_path


def cut_asset_clip(
    file_path: str,
    clip_start: float,
    clip_duration: float,
    output_path: str,
    width: int,
    height: int,
    keep_audio: bool = False,
    output_audio_stream: bool = False,
):
    """
    裁剪用户素材片段。

    keep_audio:
        当前片段是否保留素材原声。

    output_audio_stream:
        本次导出是否需要素材音频轨。
        如果有任意片段开启素材原声，则所有片段都补齐音频轨，避免 concat 出问题。
    """
    if clip_duration <= 0:
        raise RuntimeError(f"片段时长不合法: {clip_duration}")

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1,"
        f"fps=30"
    )

    if not output_audio_stream:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(clip_start),
            "-t", str(clip_duration),
            "-i", str(file_path),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-an",
            "-movflags", "+faststart",
            str(output_path)
        ]

        run_cmd(cmd)

        if not file_ok(output_path):
            raise RuntimeError(f"素材片段裁剪失败: {output_path}")

        return

    if keep_audio and has_audio_stream(file_path):
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(clip_start),
            "-t", str(clip_duration),
            "-i", str(file_path),
            "-filter_complex",
            (
                f"[0:v]{vf}[v];"
                f"[0:a:0]"
                f"aresample=async=1:first_pts=0,"
                f"apad,"
                f"atrim=0:{clip_duration},"
                f"asetpts=N/SR/TB,"
                f"aformat=sample_rates=44100:channel_layouts=stereo[a]"
            ),
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-ac", "2",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path)
        ]

        run_cmd(cmd)

        if not file_ok(output_path):
            raise RuntimeError(f"保留素材原声裁剪失败: {output_path}")

        return

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(clip_start),
        "-t", str(clip_duration),
        "-i", str(file_path),
        "-f", "lavfi",
        "-t", str(clip_duration),
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-filter_complex", f"[0:v]{vf}[v]",
        "-map", "[v]",
        "-map", "1:a:0",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-ac", "2",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path)
    ]

    run_cmd(cmd)

    if not file_ok(output_path):
        raise RuntimeError(f"静音素材片段裁剪失败: {output_path}")


def concat_clips(temp_clips: List[str], output_path: str):
    temp_dir = os.path.dirname(output_path)
    concat_file = os.path.join(temp_dir, "concat_list.txt")

    with open(concat_file, "w", encoding="utf-8") as f:
        for clip in temp_clips:
            abs_path = os.path.abspath(clip).replace("\\", "/")
            abs_path = abs_path.replace("'", "'\\''")
            f.write(f"file '{abs_path}'\n")

    cmd_copy = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path)
    ]

    try:
        run_cmd(cmd_copy)
    except Exception as e:
        print(f"快速合并失败，改用重新编码合并。原因: {e}")

        has_any_audio = any(has_audio_stream(clip) for clip in temp_clips)
        cmd_reencode = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path)
        ]
        if has_any_audio:
            cmd_reencode.extend([
                "-c:a", "aac",
                "-b:a", "128k",
                "-ar", "44100",
                "-ac", "2",
            ])
        else:
            cmd_reencode.append("-an")

        run_cmd(cmd_reencode)

    if not file_ok(output_path):
        raise RuntimeError(f"合并视频失败: {output_path}")


def select_template_audio_source(
    template_audio_path: Optional[str],
    template_video_path: Optional[str]
) -> Optional[str]:
    """
    优先使用模板上传时提取好的 template_audio.m4a。
    如果不存在，则退回使用模板原视频。
    """
    if template_audio_path and os.path.exists(template_audio_path) and has_audio_stream(template_audio_path):
        return template_audio_path

    if template_video_path and os.path.exists(template_video_path) and has_audio_stream(template_video_path):
        return template_video_path

    return None


def add_template_audio(
    video_path: str,
    template_audio_source: str,
    output_path: str,
    use_asset_audio: bool = False,
    asset_audio_volume: float = 0.3,
    template_audio_volume: float = 1.0,
):
    """
    添加模板音频。

    use_asset_audio=False:
        最终音频 = 模板音频。

    use_asset_audio=True:
        最终音频 = 模板音频 + 素材原声。
    """
    if not template_audio_source or not os.path.exists(template_audio_source):
        raise RuntimeError("模板音频不存在，无法添加模板音频")

    if not has_audio_stream(template_audio_source):
        raise RuntimeError("模板音频源没有音频轨")

    if not use_asset_audio or not has_audio_stream(video_path):
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(template_audio_source),
            "-filter_complex",
            (
                f"[1:a:0]volume={min(template_audio_volume, 1.0)},"
                f"aformat=sample_rates=48000:channel_layouts=stereo,alimiter=limit=0.92[a]"
            ),
            "-map", "0:v:0",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-ac", "2",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path)
        ]

        run_cmd(cmd)

        if not file_ok(output_path):
            raise RuntimeError("添加模板音频失败")

        return

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(template_audio_source),
        "-filter_complex",
        (
            f"[0:a:0]volume={min(asset_audio_volume, 1.0)},"
            f"aformat=sample_rates=48000:channel_layouts=stereo,alimiter=limit=0.92[a0];"
            f"[1:a:0]volume={min(template_audio_volume, 1.0)},"
            f"aformat=sample_rates=48000:channel_layouts=stereo,alimiter=limit=0.92[a1];"
            f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[a]"
        ),
        "-map", "0:v:0",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path)
    ]

    run_cmd(cmd)

    if not file_ok(output_path):
        raise RuntimeError("模板音频和素材原声混音失败")


def burn_subtitles(video_path: str, subtitle_path: str, output_path: str) -> str:
    """
    支持 ASS / SRT 字幕烧录。
    Windows 下使用相对路径避免冒号、反斜杠问题。
    """
    if not subtitle_path or not os.path.exists(subtitle_path):
        raise RuntimeError(f"字幕文件不存在: {subtitle_path}")

    video_path = os.path.abspath(video_path)
    output_path = os.path.abspath(output_path)

    workdir = os.path.dirname(video_path)

    ext = os.path.splitext(subtitle_path)[1].lower()
    if ext not in [".ass", ".srt"]:
        ext = ".srt"

    temp_subtitle_name = f"template_subtitle{ext}"
    temp_subtitle = os.path.join(workdir, temp_subtitle_name)

    shutil.copy2(subtitle_path, temp_subtitle)

    if ext == ".ass":
        vf = f"subtitles={temp_subtitle_name}"
    else:
        vf = (
            f"subtitles={temp_subtitle_name}:"
            "force_style='"
            "FontName=Microsoft YaHei,"
            "FontSize=54,"
            "PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,"
            "BorderStyle=1,"
            "Outline=3,"
            "Shadow=0,"
            "Alignment=2,"
            "MarginV=120"
            "'"
        )

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path
    ]

    try:
        run_cmd(cmd, cwd=workdir)
    finally:
        try:
            os.remove(temp_subtitle)
        except Exception:
            pass

    if not file_ok(output_path):
        raise RuntimeError("字幕烧录失败")

    return output_path


def export_video(
    timeline: list,
    output_path: str,
    resolution: str = "1080x1920",

    template_video_path: str = None,
    template_audio_path: str = None,
    template_subtitle_srt_path: str = None,
    template_subtitle_ass_path: str = None,
    template_segments_json=None,

    add_subtitles: bool = True,
    use_slot_subtitles: bool = True,
    use_asset_audio: bool = False,
    asset_audio_volume: float = 0.3,
    template_audio_volume: float = 1.0,
    tts_segments: list | None = None,
) -> str:
    """
    正确产品逻辑：

    画面 = 用户素材
    音频 = 模板音频
    字幕 = 模板字幕
    素材原声 = 用户决定是否开启
    """
    ensure_ffmpeg()

    if isinstance(timeline, str):
        timeline = json.loads(timeline)

    if not timeline:
        raise RuntimeError("项目时间线为空，无法导出")

    width, height = resolution.split("x")
    width = int(width)
    height = int(height)

    output_path = os.path.abspath(output_path)
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    base_temp_dir = os.path.abspath(os.path.join("storage", "temp"))
    os.makedirs(base_temp_dir, exist_ok=True)

    temp_dir = os.path.join(base_temp_dir, f"export_{uuid.uuid4().hex}")
    os.makedirs(temp_dir, exist_ok=True)

    temp_clips = []

    try:
        any_asset_audio_enabled = to_bool(use_asset_audio)

        for slot in timeline:
            if "use_original_audio" in slot and to_bool(slot.get("use_original_audio")):
                any_asset_audio_enabled = True
                break

        print("正在裁剪用户素材片段...")

        skipped_slots = []

        for i, slot in enumerate(timeline):
            if not slot.get("asset_id"):
                skipped_slots.append(f"槽位 {slot.get('slot_id', i)} 未匹配素材")
                continue

            raw_path = (
                slot.get("asset_file_path")
                or slot.get("file_path")
                or slot.get("path")
                or ""
            )

            if not raw_path:
                skipped_slots.append(f"槽位 {slot.get('slot_id', i)} 缺少文件路径")
                continue

            try:
                file_path = resolve_storage_path(raw_path)
            except ValueError:
                skipped_slots.append(f"槽位 {slot.get('slot_id', i)} 文件路径非法")
                continue

            if not os.path.exists(file_path):
                skipped_slots.append(f"槽位 {slot.get('slot_id', i)} 文件不存在")
                continue

            clip_start = float(
                slot.get("clip_start")
                or slot.get("asset_start")
                or 0
            )

            clip_duration = (
                slot.get("clip_duration")
                or slot.get("slot_duration")
                or slot.get("duration")
                or 2
            )
            clip_duration = float(clip_duration)

            if clip_duration <= 0:
                print(f"片段 {i} 时长无效，跳过: {clip_duration}")
                continue

            slot_override_audio = slot.get("use_original_audio", None)

            if slot_override_audio is None:
                keep_audio = to_bool(use_asset_audio)
            else:
                keep_audio = to_bool(slot_override_audio)

            temp_clip = os.path.join(temp_dir, f"clip_{i:03d}.mp4")

            cut_asset_clip(
                file_path=file_path,
                clip_start=clip_start,
                clip_duration=clip_duration,
                output_path=temp_clip,
                width=width,
                height=height,
                keep_audio=keep_audio,
                output_audio_stream=any_asset_audio_enabled,
            )

            temp_clips.append(temp_clip)
            print(f"片段 {i} 裁剪成功: {temp_clip}")

        if skipped_slots:
            print("导出跳过的槽位:", "; ".join(skipped_slots))

        if not temp_clips:
            detail = "没有可用的视频片段，请检查素材匹配结果"
            if skipped_slots:
                detail += "：" + "；".join(skipped_slots[:5])
            raise RuntimeError(detail)

        if len(skipped_slots) > len(temp_clips):
            raise RuntimeError(
                f"过多槽位无法导出（{len(skipped_slots)}/{len(timeline)}），请补全素材后重试"
            )

        print("正在合并素材片段...")

        merged = os.path.join(temp_dir, "merged.mp4")
        concat_clips(temp_clips, merged)

        print("正在添加模板音频...")

        template_audio_source = None
        tts_audio_path = os.path.join(temp_dir, "tts_concat.m4a")
        if tts_segments:
            from services.tts.tts_pipeline import concat_tts_for_timeline

            concat_path = concat_tts_for_timeline(timeline, tts_segments, tts_audio_path.replace(".m4a", ".wav"))
            if concat_path and os.path.isfile(concat_path):
                if concat_path.lower().endswith(".wav"):
                    ensure_ffmpeg()
                    import subprocess

                    subprocess.run(
                        ["ffmpeg", "-y", "-i", concat_path, "-c:a", "aac", "-b:a", "192k", tts_audio_path],
                        check=True,
                        capture_output=True,
                    )
                    if file_ok(tts_audio_path):
                        template_audio_source = tts_audio_path
                else:
                    template_audio_source = concat_path

        if not template_audio_source:
            template_audio_source = select_template_audio_source(
                template_audio_path=template_audio_path,
                template_video_path=template_video_path,
            )

        if not template_audio_source:
            if any_asset_audio_enabled and has_audio_stream(merged):
                print("没有模板音频，使用素材原声")
                with_audio = os.path.join(temp_dir, "with_audio.mp4")
                shutil.copy2(merged, with_audio)
            else:
                raise RuntimeError("模板没有可用音频，无法导出带音频视频")
        else:
            with_audio = os.path.join(temp_dir, "with_template_audio.mp4")

            add_template_audio(
                video_path=merged,
                template_audio_source=template_audio_source,
                output_path=with_audio,
                use_asset_audio=any_asset_audio_enabled,
                asset_audio_volume=asset_audio_volume,
                template_audio_volume=template_audio_volume,
            )

        if not file_ok(with_audio):
            raise RuntimeError("生成带音频视频失败")

        if add_subtitles:
            print("正在添加字幕...")

            subtitle_path = None
            if use_slot_subtitles:
                subtitle_path = build_ass_from_timeline_slots(
                    timeline, temp_dir, width=width, height=height
                )
                if subtitle_path:
                    print("使用槽位 timeline 字幕")

            if not subtitle_path:
                subtitle_path = make_template_subtitle_if_needed(
                    template_video_path=template_video_path,
                    template_subtitle_srt_path=template_subtitle_srt_path,
                    template_subtitle_ass_path=template_subtitle_ass_path,
                    template_segments_json=template_segments_json,
                    temp_dir=temp_dir,
                    width=width,
                    height=height,
                )

            if not subtitle_path:
                raise RuntimeError("没有可用的模板字幕，无法烧录字幕")

            print(f"使用模板字幕文件: {subtitle_path}")

            burn_subtitles(
                video_path=with_audio,
                subtitle_path=subtitle_path,
                output_path=output_path
            )
        else:
            shutil.copy2(with_audio, output_path)

        if not file_ok(output_path):
            raise RuntimeError("导出失败，输出文件不存在或为空")

        print(f"导出成功: {output_path}")
        return output_path

    finally:
        print("正在清理临时文件...")
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass