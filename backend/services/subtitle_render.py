"""ASS/SRT 字幕渲染公共层（模板 ASS、导出烧录共用）。"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional


def format_ass_time(seconds: float) -> str:
    total_cs = int(round(seconds * 100))
    h = total_cs // 360000
    total_cs %= 360000
    m = total_cs // 6000
    total_cs %= 6000
    s = total_cs // 100
    cs = total_cs % 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def write_ass(
    segments: List[Dict[str, Any]],
    output_path: str,
    width: int = 1080,
    height: int = 1920,
) -> None:
    """生成统一样式 ASS（非模板原始花字特效）。"""
    header = f"""[Script Info]
Title: AI Travel Cut Template Subtitle
ScriptType: v4.00+
Collisions: Normal
PlayResX: {width}
PlayResY: {height}
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,54,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,0,2,60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        for seg in segments:
            start = format_ass_time(float(seg["start"]))
            end = format_ass_time(float(seg["end"]))
            text = ass_escape(str(seg.get("text", "")))
            f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")


def hex_to_ass_color(hex_color: str, alpha_byte: int = 0) -> str:
    raw = str(hex_color or "#ffffff").strip().lstrip("#")
    if len(raw) != 6:
        return "&H00FFFFFF"
    r = int(raw[0:2], 16)
    g = int(raw[2:4], 16)
    b = int(raw[4:6], 16)
    return f"&H{alpha_byte:02X}{b:02X}{g:02X}{r:02X}"


def normalize_segments(
    raw_segments: Any,
    *,
    normalize_text: Callable[[str], str] | None = None,
) -> List[Dict[str, Any]]:
    """把 transcribe 返回的数据统一转成 JSON 可存储格式。"""
    if raw_segments is None:
        return []

    if isinstance(raw_segments, tuple) and len(raw_segments) >= 1:
        raw_segments = raw_segments[0]

    normalized: List[Dict[str, Any]] = []
    norm = normalize_text or (lambda text: text.strip())

    for seg in list(raw_segments):
        if isinstance(seg, dict):
            start = float(seg.get("start", 0))
            end = float(seg.get("end", 0))
            text = norm(str(seg.get("text", "")))
        else:
            start = float(getattr(seg, "start", 0))
            end = float(getattr(seg, "end", 0))
            text = norm(str(getattr(seg, "text", "")))

        if not text or end <= start:
            continue

        normalized.append({
            "start": start,
            "end": end,
            "duration": end - start,
            "text": text,
        })

    return normalized


def format_srt_time(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    h = total_ms // 3600000
    total_ms %= 3600000
    m = total_ms // 60000
    total_ms %= 60000
    s = total_ms // 1000
    ms = total_ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: List[Dict[str, Any]], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as handle:
        for index, seg in enumerate(segments, start=1):
            start = format_srt_time(float(seg["start"]))
            end = format_srt_time(float(seg["end"]))
            text = seg["text"]
            handle.write(f"{index}\n")
            handle.write(f"{start} --> {end}\n")
            handle.write(f"{text}\n\n")


def _ass_alignment_from_style(style: dict[str, Any]) -> tuple[int, int]:
    position = str(style.get("position") or "bottom").lower()
    if position == "top":
        return 8, 100
    if position == "center":
        return 5, 40
    return 2, int(style.get("margin_v") or 120)


def _ass_animation_tags(
    style: dict[str, Any], width: int, height: int, duration_sec: float = 2.0
) -> str:
    parts: list[str] = []
    anim_in = str(style.get("animation_in") or "fade").lower()
    anim_out = str(style.get("animation_out") or "fade").lower()
    anim_loop = str(style.get("animation_loop") or "none").lower()
    cx = width // 2

    if anim_in == "fade_up":
        y0, y1 = int(height * 0.92), int(height * 0.82)
        parts.append(f"\\fad(180,120)\\move({cx},{y0},{cx},{y1},0,280)")
    elif anim_in == "fade_down":
        y0, y1 = int(height * 0.78), int(height * 0.88)
        parts.append(f"\\fad(180,120)\\move({cx},{y0},{cx},{y1},0,280)")
    elif anim_in == "scale":
        parts.append("\\fad(200,150)\\fscx115\\fscy115\\t(0,220,\\fscx100\\fscy100)")
    elif anim_in == "bounce":
        parts.append("\\fad(120,120)\\fscx108\\fscy108\\t(0,120,\\fscx100\\fscy100)")
    elif anim_in == "typewriter":
        parts.append("\\fad(80,80)")
    elif anim_in == "blur_in":
        parts.append("\\fad(260,120)")
    else:
        parts.append("\\fad(220,180)")

    fade_out_ms = min(280, max(80, int(duration_sec * 120)))
    if anim_out == "fade_up":
        parts.append(
            f"\\fad(0,{fade_out_ms})\\move({cx},{int(height * 0.82)},{cx},{int(height * 0.72)},0,{fade_out_ms})"
        )
    elif anim_out == "fade_down":
        parts.append(
            f"\\fad(0,{fade_out_ms})\\move({cx},{int(height * 0.88)},{cx},{int(height * 0.96)},0,{fade_out_ms})"
        )
    elif anim_out == "scale_out":
        parts.append(f"\\fad(0,{fade_out_ms})\\t(0,{fade_out_ms},\\fscx85\\fscy85)")
    elif anim_out == "blur_out":
        parts.append(f"\\fad(0,{fade_out_ms})")
    elif anim_out != "none":
        parts.append(f"\\fad(0,{fade_out_ms})")

    if anim_loop == "pulse":
        parts.append("\\t(0,400,\\fscx103\\fscy103)\\t(400,800,\\fscx100\\fscy100)")
    elif anim_loop == "shake":
        parts.append("\\t(0,80,\\frx1)\\t(80,160,\\frx-1)\\t(160,240,\\frx0)")
    elif anim_loop == "glow":
        parts.append("\\3c&H0044AAFF&")
    elif anim_loop == "wave":
        parts.append("\\t(0,300,\\fy-4)\\t(300,600,\\fy4)\\t(600,900,\\fy0)")

    return "".join(parts)


def write_ass_styled_for_clip(
    segments: List[Dict[str, Any]],
    output_path: str,
    width: int = 1080,
    height: int = 1920,
) -> None:
    """为单段视频生成带样式/动画标签的 ASS（时间轴相对本段 0 秒）。"""
    base_style = (
        segments[0].get("style") if segments and isinstance(segments[0].get("style"), dict) else {}
    )
    font_size = int(base_style.get("font_size") or 54)
    primary = hex_to_ass_color(str(base_style.get("text_color") or "#ffffff"))
    outline = hex_to_ass_color(str(base_style.get("outline_color") or "#000000"))
    alignment, margin_v = _ass_alignment_from_style(base_style)
    bold = 1 if base_style.get("bold") else 0

    header = f"""[Script Info]
Title: AI Travel Cut Clip Subtitle
ScriptType: v4.00+
Collisions: Normal
PlayResX: {width}
PlayResY: {height}
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,{font_size},{primary},&H000000FF,{outline},&H64000000,{bold},0,0,0,100,100,0,0,1,3,1,{alignment},60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(header)
        for seg in segments:
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            start = format_ass_time(max(0.0, float(seg.get("start", 0))))
            end = format_ass_time(max(0.08, float(seg.get("end", 0))))
            duration_sec = max(0.08, float(seg.get("end", 0)) - float(seg.get("start", 0)))
            style = seg.get("style") if isinstance(seg.get("style"), dict) else {}
            inner = _ass_animation_tags(style, width, height, duration_sec)
            if style.get("text_color"):
                inner += f"\\1c{hex_to_ass_color(str(style['text_color']))}"
            if style.get("outline_color"):
                inner += f"\\3c{hex_to_ass_color(str(style['outline_color']))}"
            if style.get("font_size"):
                inner += f"\\fs{int(style['font_size'])}"
            prefix = f"{{{inner}}}" if inner else ""
            handle.write(
                f"Dialogue: 0,{start},{end},Default,,0,0,0,,{prefix}{ass_escape(text)}\n"
            )


def build_ass_from_timeline_slots(
    timeline: List[Dict[str, Any]],
    temp_dir: str,
    width: int,
    height: int,
) -> Optional[str]:
    """从槽位 subtitle_text / subtitle_segments 生成 ASS。"""
    segments: List[Dict[str, Any]] = []
    cursor = 0.0

    for slot in timeline:
        dur = float(
            slot.get("slot_duration") or slot.get("clip_duration") or slot.get("duration") or 0
        )
        if dur <= 0:
            continue

        slot_abs_start = float(
            slot.get("slot_start") if slot.get("slot_start") is not None else cursor
        )
        source_start = float(
            slot.get("template_source_start")
            or slot.get("clip_start")
            or slot.get("start")
            or slot_abs_start
        )
        sub_segs = slot.get("subtitle_segments") or []

        if sub_segs:
            for seg in sub_segs:
                text = str(seg.get("text", "")).strip()
                if not text:
                    continue
                seg_start = float(seg.get("start", source_start))
                seg_end = float(seg.get("end", seg_start + 0.5))
                if (
                    seg_start >= source_start - 0.05
                    and seg_end <= source_start + dur + 0.05
                ):
                    rel_start = max(0.0, seg_start - source_start)
                    rel_end = min(dur, max(rel_start + 0.08, seg_end - source_start))
                elif seg_start >= slot_abs_start - 0.05 and seg_end <= slot_abs_start + dur + 0.05:
                    rel_start = max(0.0, seg_start - slot_abs_start)
                    rel_end = min(dur, max(rel_start + 0.08, seg_end - slot_abs_start))
                elif seg_start >= 0 and seg_end <= dur + 0.05:
                    rel_start = seg_start
                    rel_end = min(dur, max(rel_start + 0.08, seg_end))
                else:
                    rel_start = 0.05
                    rel_end = max(0.2, dur - 0.05)
                segments.append({
                    "start": slot_abs_start + rel_start,
                    "end": slot_abs_start + rel_end,
                    "text": text,
                })
        else:
            text = str(slot.get("subtitle_text") or "").strip()
            if text:
                segments.append({
                    "start": cursor + 0.05,
                    "end": cursor + dur - 0.05,
                    "text": text,
                })

        cursor += dur

    if not segments:
        return None

    out_path = os.path.join(temp_dir, "slot_timeline_subtitle.ass")
    write_ass(segments, out_path, width=width, height=height)
    return out_path


def make_template_subtitle_if_needed(
    template_video_path: Optional[str],
    template_subtitle_srt_path: Optional[str],
    template_subtitle_ass_path: Optional[str],
    template_segments_json,
    temp_dir: str,
    width: int,
    height: int,
) -> Optional[str]:
    """
    字幕来源优先级：
    1. 模板 ASS 字幕
    2. 模板 SRT 字幕
    3. 模板 segments_json
    4. 从模板视频实时识别
    """
    if template_subtitle_ass_path and os.path.exists(template_subtitle_ass_path):
        return template_subtitle_ass_path

    if template_subtitle_srt_path and os.path.exists(template_subtitle_srt_path):
        return template_subtitle_srt_path

    if isinstance(template_segments_json, str):
        try:
            template_segments_json = json.loads(template_segments_json)
        except Exception:
            template_segments_json = []

    if template_segments_json:
        fallback_ass_path = os.path.join(temp_dir, "segments_template_subtitle.ass")
        write_ass(template_segments_json, fallback_ass_path, width=width, height=height)
        return fallback_ass_path

    if not template_video_path or not os.path.exists(template_video_path):
        return None

    from services.media_probe import extract_whisper_wav, has_audio_stream

    if not has_audio_stream(template_video_path):
        return None

    print("模板没有预生成字幕文件，开始从模板视频实时识别字幕...")

    try:
        from services.subtitle_gen import transcribe

        whisper_audio_path = os.path.join(temp_dir, "fallback_template_subtitle_audio.wav")
        fallback_ass_path = os.path.join(temp_dir, "fallback_template_subtitle.ass")

        extract_whisper_wav(template_video_path, whisper_audio_path)

        raw_segments = transcribe(whisper_audio_path)
        segments = normalize_segments(raw_segments)

        if not segments:
            return None

        write_ass(segments, fallback_ass_path, width=width, height=height)

        return fallback_ass_path

    except Exception as e:
        print(f"实时识别模板字幕失败: {e}")
        return None
