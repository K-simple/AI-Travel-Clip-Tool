"""从烧录字幕画面提取样式与动画特征（OpenCV + 可选 DeepSeek 视觉）。"""

import json
import os
import re
from typing import Any

import cv2
import numpy as np

from services.processing_config import ENABLE_SUBTITLE_STYLE_ANALYSIS, SUBTITLE_STYLE_MAX_SEGMENTS
from services.scene_detector import extract_frame

# 剪映 transform_y 近似映射（竖屏 1080x1920）
_POSITION_TRANSFORM_Y = {
    "top": 720,
    "center": 0,
    "bottom": -400,
}

_ANIMATION_LABELS = {
    "fade": "淡入",
    "fade_up": "上滑",
    "fade_down": "下滑",
    "bounce": "弹跳",
    "scale": "缩放",
    "none": "无",
}


def _hex_color(bgr: tuple[int, int, int]) -> str:
    b, g, r = (int(bgr[0]), int(bgr[1]), int(bgr[2]))
    return f"#{r:02x}{g:02x}{b:02x}"


def _load_frame(path: str) -> np.ndarray | None:
    if not path or not os.path.isfile(path):
        return None
    img = cv2.imread(path)
    return img if img is not None and img.size > 0 else None


def _extract_frame_to_dir(video_path: str, time_sec: float, out_dir: str, tag: str) -> str | None:
    os.makedirs(out_dir, exist_ok=True)
    safe_t = max(0.0, time_sec)
    out_path = os.path.join(out_dir, f"style_{tag}_{int(safe_t * 1000):06d}.jpg").replace("\\", "/")
    if os.path.isfile(out_path):
        return out_path
    try:
        extract_frame(video_path, safe_t, out_path)
        return out_path if os.path.isfile(out_path) else None
    except Exception:
        return None


def _find_subtitle_bbox(before: np.ndarray, during: np.ndarray) -> tuple[int, int, int, int] | None:
    """对比前后帧差异，定位字幕区域 bbox (x, y, w, h)。"""
    h, w = during.shape[:2]
    bands = [
        (int(h * 0.55), h),
        (int(h * 0.35), int(h * 0.65)),
        (0, int(h * 0.35)),
    ]

    best: tuple[int, int, int, int, float] | None = None
    min_area = w * h * 0.0008

    for y0, y1 in bands:
        rb = before[y0:y1, :]
        rd = during[y0:y1, :]
        if rb.size == 0 or rd.size == 0:
            continue

        diff = cv2.absdiff(rb, rd)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, 18, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 3))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(cnt)
            if bw < w * 0.08 or bh < h * 0.012:
                continue
            score = area * (1.2 if y0 >= int(h * 0.55) else 1.0)
            if best is None or score > best[4]:
                best = (x, y + y0, bw, bh, score)

    if best is None:
        return None
    return best[0], best[1], best[2], best[3]


def _pick_fill_and_outline(centers: np.ndarray, counts: np.ndarray) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """从字幕 ROI 聚类中选取填充色与描边色（优先高饱和/高亮文字色）。"""
    order = np.argsort(-counts)
    scored: list[tuple[float, tuple[int, int, int]]] = []
    for idx in order:
        b, g, r = (int(centers[idx][0]), int(centers[idx][1]), int(centers[idx][2]))
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        max_c = max(r, g, b)
        min_c = min(r, g, b)
        sat = (max_c - min_c) / max(max_c, 1)
        score = sat * 2.2 + lum / 255.0 + float(counts[idx]) * 1e-5
        if lum < 70:
            score *= 0.25
        if r > 170 and g > 130 and b < 120:
            score += 1.2
        if lum > 210 and sat < 0.12:
            score += 0.35
        scored.append((score, (b, g, r)))

    scored.sort(key=lambda x: -x[0])
    primary = scored[0][1]
    secondary = scored[1][1] if len(scored) > 1 else scored[0][1]

    lum_p = 0.299 * primary[2] + 0.587 * primary[1] + 0.114 * primary[0]
    lum_s = 0.299 * secondary[2] + 0.587 * secondary[1] + 0.114 * secondary[0]
    if lum_p >= lum_s:
        fill, outline = primary, secondary
    else:
        fill, outline = secondary, primary

    if lum_p > 200 and lum_s > 200:
        outline = (0, 0, 0)
    elif lum_p < lum_s and lum_s - lum_p > 40:
        fill, outline = secondary, primary

    return fill, outline


def _detect_highlight_color_hsv(roi: np.ndarray) -> tuple[str, str] | None:
    """检测 ROI 内高饱和高亮文字色（如黄色口播字幕）。"""
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    masks = [
        cv2.inRange(hsv, (12, 70, 120), (45, 255, 255)),
        cv2.inRange(hsv, (0, 0, 210), (180, 40, 255)),
    ]
    mask = masks[0]
    for extra in masks[1:]:
        mask = cv2.bitwise_or(mask, extra)
    ratio = cv2.countNonZero(mask) / max(roi.shape[0] * roi.shape[1], 1)
    if ratio < 0.025:
        return None
    mean_bgr = cv2.mean(roi, mask=mask)[:3]
    fill = (int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2]))
    return _hex_color(fill), "#000000"


def _sample_text_colors(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> tuple[str, str]:
    x, y, w, h = bbox
    roi = frame[y : y + h, x : x + w]
    if roi.size == 0:
        return "#ffffff", "#000000"

    hsv_hit = _detect_highlight_color_hsv(roi)
    if hsv_hit is not None:
        return hsv_hit

    pixels = roi.reshape(-1, 3).astype(np.float32)
    if len(pixels) > 800:
        idx = np.linspace(0, len(pixels) - 1, 800, dtype=int)
        pixels = pixels[idx]

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    _, labels, centers = cv2.kmeans(pixels, 3, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=3)

    fill, outline = _pick_fill_and_outline(centers, counts)
    return _hex_color(fill), _hex_color(outline)


def _position_from_bbox(bbox: tuple[int, int, int, int], frame_h: int) -> str:
    _, y, _, bh = bbox
    cy = y + bh / 2
    if cy >= frame_h * 0.72:
        return "bottom"
    if cy <= frame_h * 0.32:
        return "top"
    return "center"


def _detect_animation(
    bboxes: list[tuple[int, int, int, int] | None],
) -> tuple[str, str]:
    valid = [b for b in bboxes if b is not None]
    if len(valid) < 2:
        return "fade", "fade"

    heights = [b[3] for b in valid]
    ys = [b[1] for b in valid]
    h0, h_mid, h_last = heights[0], heights[len(heights) // 2], heights[-1]
    y0, y_last = ys[0], ys[-1]

    if h_mid > h0 * 1.12 and h_last >= h_mid * 0.92:
        return "bounce", "fade"
    if h_mid > h0 * 1.18:
        return "scale", "fade"
    if y0 - y_last > max(4, h0 * 0.08):
        return "fade_up", "fade_down"
    if y_last - y0 > max(4, h0 * 0.08):
        return "fade_down", "fade"

    return "fade", "fade"


def _estimate_font_size(bbox: tuple[int, int, int, int], frame_h: int) -> int:
    _, _, _, bh = bbox
    ratio = bh / max(frame_h, 1)
    size = int(round(ratio * frame_h * 0.72))
    return int(min(72, max(28, size)))


def to_capcut_font_size(style: dict[str, Any] | None, *, frame_height: int = 1920) -> int:
    """将 OpenCV 分析的字号映射为剪映 Mate 可用字号（约 9–22）。"""
    if not isinstance(style, dict):
        return 15
    if style.get("capcut_font_size") is not None:
        return max(9, min(22, int(style["capcut_font_size"])))
    raw = int(style.get("font_size") or 54)
    if raw <= 24:
        return max(9, min(22, raw))
    capcut = int(round(raw * 15.0 / 54.0))
    return max(9, min(22, capcut))


def style_needs_template_video_analysis(style: dict[str, Any] | None) -> bool:
    """判断是否仍需从模板原片帧分析样式（颜色/字号/动画）。"""
    if not isinstance(style, dict) or not style:
        return True
    conf = float(style.get("confidence") or 0)
    color = str(style.get("text_color") or "").strip().lower()
    is_default_white = color in ("", "#ffffff", "#fff", "white")
    label = str(style.get("style_label") or "")
    if conf >= 0.68 and not is_default_white and "默认" not in label:
        return False
    anim_in = str(style.get("animation_in") or "fade").lower()
    if (
        conf >= 0.65
        and anim_in not in ("", "none", "fade")
        and not is_default_white
    ):
        return False
    if conf >= 0.65 and style.get("capcut_font_size") and not is_default_white:
        return False
    return True


def segment_from_slot_for_style_analysis(slot: dict[str, Any]) -> dict[str, Any]:
    """从槽位提取模板时间轴上的字幕片段，供样式分析。"""
    start = float(
        slot.get("template_source_start")
        if slot.get("template_source_start") is not None
        else slot.get("clip_start")
        if slot.get("clip_start") is not None
        else slot.get("start")
        or 0
    )
    end = float(
        slot.get("clip_end")
        if slot.get("clip_end") is not None
        else slot.get("end")
        or start + max(0.35, float(slot.get("duration") or 0.35))
    )
    if end <= start:
        end = start + max(0.35, float(slot.get("duration") or 0.35))
    text = str(slot.get("subtitle_text") or "").strip()
    for seg in slot.get("subtitle_segments") or []:
        if not isinstance(seg, dict):
            continue
        seg_text = str(seg.get("text") or "").strip()
        if seg_text:
            text = seg_text
            start = float(seg.get("start", start))
            end = float(seg.get("end", end))
            break
    return {"start": start, "end": end, "text": text}


def _apply_style_to_slot_subtitles(slot: dict[str, Any], style: dict[str, Any]) -> dict[str, Any]:
    item = dict(slot)
    item["subtitle_style"] = dict(style)
    sub_segs = list(item.get("subtitle_segments") or [])
    if sub_segs:
        item["subtitle_segments"] = [
            {**seg, "style": dict(style)} if isinstance(seg, dict) else seg for seg in sub_segs
        ]
    return item


def ensure_timeline_styles_from_template_video(
    timeline: list[dict[str, Any]],
    video_path: str,
    work_dir: str,
    *,
    frame_height: int = 1920,
    max_analyze: int | None = None,
) -> list[dict[str, Any]]:
    """导出前：从模板原片逐段分析烧录字幕的颜色、字号与出入场动画。"""
    if not ENABLE_SUBTITLE_STYLE_ANALYSIS or not video_path or not os.path.isfile(video_path):
        return timeline

    limit = max_analyze if max_analyze is not None else SUBTITLE_STYLE_MAX_SEGMENTS
    style_dir = os.path.join(work_dir, "template_video_subtitle_styles")
    os.makedirs(style_dir, exist_ok=True)

    result: list[dict[str, Any]] = []
    last_style = _default_style()
    analyzed_count = 0

    for index, slot in enumerate(timeline):
        if not isinstance(slot, dict):
            result.append(slot)
            continue

        item = dict(slot)
        existing = item.get("subtitle_style") if isinstance(item.get("subtitle_style"), dict) else {}
        seg_style: dict[str, Any] = {}
        for seg in item.get("subtitle_segments") or []:
            if isinstance(seg, dict) and isinstance(seg.get("style"), dict) and seg["style"]:
                seg_style = dict(seg["style"])
                break
        merged = _merge_style_dict(existing, seg_style)

        if not style_needs_template_video_analysis(merged):
            result.append(_apply_style_to_slot_subtitles(item, merged))
            last_style = merged
            continue

        segment = segment_from_slot_for_style_analysis(item)
        try:
            if analyzed_count < limit:
                analyzed = analyze_segment_style(video_path, segment, style_dir)
                analyzed_count += 1
            else:
                analyzed = dict(last_style)
        except Exception as exc:
            print(f"模板原片字幕样式分析失败 @ {segment.get('start')}: {exc}")
            analyzed = dict(last_style)

        analyzed["capcut_font_size"] = to_capcut_font_size(analyzed, frame_height=frame_height)
        final_style = _merge_style_dict(merged, analyzed)
        final_style["capcut_font_size"] = to_capcut_font_size(final_style, frame_height=frame_height)
        result.append(_apply_style_to_slot_subtitles(item, final_style))
        last_style = final_style

    print(f"模板原片字幕样式分析完成: {analyzed_count}/{len(timeline)} 段")
    return result


def ensure_template_segments_have_styles(
    segments: list[dict[str, Any]],
    video_path: str,
    work_dir: str,
) -> list[dict[str, Any]]:
    """为 segments_json 补全 style（模板 intake 未分析时导出前补跑）。"""
    if not segments or not video_path or not os.path.isfile(video_path):
        return segments
    needs = any(
        style_needs_template_video_analysis(seg.get("style") if isinstance(seg, dict) else None)
        for seg in segments
        if isinstance(seg, dict)
    )
    if not needs and any(isinstance(s, dict) and s.get("style") for s in segments):
        return segments
    return analyze_subtitle_styles(video_path, [dict(s) for s in segments if isinstance(s, dict)], work_dir)


def _default_style() -> dict[str, Any]:
    return {
        "text_color": "#ffffff",
        "outline_color": "#000000",
        "font_size": 54,
        "position": "bottom",
        "alignment": "center",
        "bold": False,
        "animation_in": "fade",
        "animation_out": "fade",
        "animation_loop": "none",
        "transform_y": _POSITION_TRANSFORM_Y["bottom"],
        "confidence": 0.35,
        "capcut_font_size": 15,
        "style_label": "默认白字黑边",
    }


def style_to_capcut_params(style: dict[str, Any], *, frame_height: int = 1920) -> dict[str, Any]:
    outline = style.get("outline_color") or style.get("border_color")
    params: dict[str, Any] = {
        "text_color": style.get("text_color") or "#ffffff",
        "font_size": to_capcut_font_size(style, frame_height=frame_height),
        "alignment": 1,
        "transform_y": int(style.get("transform_y") or _POSITION_TRANSFORM_Y["bottom"]),
        "bold": bool(style.get("bold")),
    }
    if outline:
        params["border_color"] = str(outline)
    text_effect = style.get("text_effect") or style.get("effect_label")
    if text_effect:
        params["text_effect"] = text_effect
    return params


_CAPCUT_TEXT_ANIM_IN: dict[str, str | None] = {
    "fade": "渐显",
    "fade_up": "向上滑动",
    "fade_down": "向下滑动",
    "scale": "放大",
    "bounce": "向上弹入",
    "typewriter": "打字机 I",
    "blur_in": "模糊",
    "none": None,
}

_CAPCUT_TEXT_ANIM_OUT: dict[str, str | None] = {
    "fade": "渐隐",
    "fade_up": "向上滑动",
    "fade_down": "向下滑动",
    "scale_out": "缩小",
    "none": None,
}

_CAPCUT_TEXT_ANIM_LOOP: dict[str, str | None] = {
    "pulse": "脉冲",
    "shake": "抖动",
    "glow": "发光",
    "wave": "波浪",
    "none": None,
}


def _map_capcut_text_animation(raw: str | None, *, direction: str) -> str | None:
    key = str(raw or "fade").strip().lower()
    table = _CAPCUT_TEXT_ANIM_IN if direction == "in" else _CAPCUT_TEXT_ANIM_OUT
    if key in table:
        return table[key]
    if key and key not in ("none", ""):
        return key
    return None


def _map_capcut_loop_animation(raw: str | None) -> str | None:
    key = str(raw or "none").strip().lower()
    if key in _CAPCUT_TEXT_ANIM_LOOP:
        return _CAPCUT_TEXT_ANIM_LOOP[key]
    if key and key not in ("none", ""):
        return key
    return None


def _merge_style_dict(existing: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
    from services.effects_catalog import _merge_style

    return _merge_style(existing, patch or {})


def _style_from_effect_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {}
    out: dict[str, Any] = {}
    anim = profile.get("animation") if isinstance(profile.get("animation"), dict) else {}
    for direction, field in (("in", "animation_in"), ("out", "animation_out")):
        block = anim.get(direction)
        if isinstance(block, dict) and block.get("type"):
            out[field] = str(block["type"])
    base = profile.get("baseStyle") if isinstance(profile.get("baseStyle"), dict) else {}
    if base.get("fontSize"):
        out["font_size"] = int(base["fontSize"])
    if base.get("color"):
        out["text_color"] = str(base["color"])
    if base.get("strokeColor"):
        out["outline_color"] = str(base["strokeColor"])
    return out


def _style_from_render_hints(hints: dict[str, Any] | None, base: dict[str, Any]) -> dict[str, Any]:
    style = dict(base)
    if not isinstance(hints, dict):
        return style
    intensity = str(hints.get("animationIntensity") or "normal").lower()
    current_in = str(style.get("animation_in") or "none").lower()
    if intensity == "strong" and current_in in ("", "none", "fade"):
        style["animation_in"] = "bounce"
    elif intensity == "weak" and current_in in ("", "none"):
        style["animation_in"] = "fade"
    return style


def resolve_subtitle_style_for_export(
    slot: dict[str, Any] | None = None,
    *,
    caption_clip: dict[str, Any] | None = None,
    template_segment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """合并样式：优先模板原片分析结果，再 CaptionClip，最后槽位/AI 特效补充。"""
    from services.effects_catalog import _extract_subtitle_style

    style: dict[str, Any] = {}

    if isinstance(template_segment, dict):
        seg_style = template_segment.get("style") if isinstance(template_segment.get("style"), dict) else {}
        if seg_style:
            style = _merge_style_dict(style, seg_style)

    if isinstance(caption_clip, dict):
        for key in ("subtitle_style", "style"):
            raw = caption_clip.get(key)
            if isinstance(raw, dict):
                style = _merge_style_dict(style, raw)
        profile_style = _style_from_effect_profile(
            caption_clip.get("effectProfile") if isinstance(caption_clip.get("effectProfile"), dict) else None
        )
        if profile_style:
            style = _merge_style_dict(style, profile_style)
        hints = caption_clip.get("renderHints")
        style = _style_from_render_hints(hints if isinstance(hints, dict) else None, style)

    if isinstance(slot, dict):
        slot_style = _extract_subtitle_style(slot)
        for key, value in slot_style.items():
            if value is None or value == "" or value == "none":
                continue
            if key not in style or not style.get(key):
                style[key] = value

    if style:
        style["capcut_font_size"] = to_capcut_font_size(style)
        return style
    default = _default_style()
    default["capcut_font_size"] = to_capcut_font_size(default)
    return default


def enrich_caption_clips_with_subtitle_styles(
    video_path: str,
    clips: list[dict[str, Any]],
    work_dir: str,
    *,
    max_clips: int | None = None,
) -> list[dict[str, Any]]:
    """识别字幕后：OpenCV 分析每条 CaptionClip 的样式与出入场动画。"""
    if not ENABLE_SUBTITLE_STYLE_ANALYSIS or not video_path or not clips:
        return clips

    limit = max_clips if max_clips is not None else SUBTITLE_STYLE_MAX_SEGMENTS
    style_dir = os.path.join(work_dir, "caption_clip_styles")
    os.makedirs(style_dir, exist_ok=True)

    enriched: list[dict[str, Any]] = []
    last_style = _default_style()
    for index, clip in enumerate(clips):
        if not isinstance(clip, dict):
            enriched.append(clip)
            continue

        item = dict(clip)
        existing = item.get("subtitle_style") if isinstance(item.get("subtitle_style"), dict) else {}
        if not style_needs_template_video_analysis(existing):
            existing["capcut_font_size"] = to_capcut_font_size(existing)
            item["subtitle_style"] = existing
            enriched.append(item)
            last_style = existing
            continue

        segment = {
            "start": float(item.get("start", 0)),
            "end": float(item.get("end", item.get("start", 0) + 0.5)),
            "text": str(item.get("text") or item.get("displayText") or ""),
        }
        try:
            if index < limit:
                analyzed = analyze_segment_style(video_path, segment, style_dir)
            else:
                analyzed = dict(last_style)
        except Exception as exc:
            print(f"CaptionClip 样式分析失败 @ {segment.get('start')}: {exc}")
            analyzed = dict(last_style)

        item["subtitle_style"] = _merge_style_dict(existing, analyzed)
        item["subtitle_style"]["capcut_font_size"] = to_capcut_font_size(item["subtitle_style"])
        last_style = item["subtitle_style"]
        enriched.append(item)

    print(f"CaptionClip 字幕动画分析完成: {len(enriched)} 条（详细分析 {min(len(clips), limit)} 条）")
    return enriched


def style_to_capcut_caption_item(
    cap: dict[str, Any],
    style: dict[str, Any],
    *,
    clip_duration_us: int | None = None,
) -> dict[str, Any]:
    """将单条字幕 + 样式转为 CapCut Mate add_captions 条目（含出入场动画）。"""
    item = {
        "start": cap["start"],
        "end": cap["end"],
        "text": cap["text"],
    }
    anim_in = _map_capcut_text_animation(style.get("animation_in"), direction="in")
    anim_out = _map_capcut_text_animation(style.get("animation_out"), direction="out")
    if anim_in:
        item["in_animation"] = anim_in
        item["in_animation_duration"] = min(800_000, max(200_000, int((clip_duration_us or 800_000) // 4)))
    if anim_out:
        item["out_animation"] = anim_out
        item["out_animation_duration"] = min(600_000, max(200_000, int((clip_duration_us or 600_000) // 5)))
    loop_anim = _map_capcut_loop_animation(style.get("animation_loop"))
    if loop_anim:
        item["loop_animation"] = loop_anim
    capcut_font = to_capcut_font_size(style)
    item["font_size"] = capcut_font
    if style.get("text_color"):
        item["text_color"] = str(style["text_color"])
    if style.get("outline_color") or style.get("border_color"):
        item["border_color"] = str(style.get("outline_color") or style.get("border_color"))
    return item


def style_signature(style: dict[str, Any]) -> str:
    return "|".join(
        str(style.get(k, ""))
        for k in (
            "text_color",
            "outline_color",
            "font_size",
            "transform_y",
            "animation_in",
            "animation_out",
            "animation_loop",
        )
    )


def _maybe_refine_with_vision(frame_path: str, text: str, base_style: dict[str, Any]) -> dict[str, Any]:
    try:
        from services.deepseek_client import chat_vision, deepseek_enabled

        if not deepseek_enabled() or not frame_path:
            return base_style

        prompt = (
            f"画面中有烧录字幕「{text[:30]}」。请识别字幕样式，输出严格 JSON（无 markdown）："
            '{"text_color":"#RRGGBB","outline_color":"#RRGGBB","animation_in":"fade|fade_up|bounce|scale",'
            '"position":"bottom|center|top","style_label":"10字内描述"}'
        )
        raw = chat_vision(prompt, [frame_path], max_tokens=128, temperature=0.05)
        m = re.search(r"\{[\s\S]*\}", raw or "")
        if not m:
            return base_style
        data = json.loads(m.group(0))
        if not isinstance(data, dict):
            return base_style

        merged = dict(base_style)
        for key in ("text_color", "outline_color", "animation_in", "position", "style_label"):
            val = data.get(key)
            if val:
                merged[key] = val
        if merged.get("position") in _POSITION_TRANSFORM_Y:
            merged["transform_y"] = _POSITION_TRANSFORM_Y[str(merged["position"])]
        merged["confidence"] = min(0.95, float(base_style.get("confidence", 0.5)) + 0.15)
        return merged
    except Exception:
        return base_style


def analyze_segment_style(
    video_path: str,
    segment: dict[str, Any],
    work_dir: str,
    *,
    use_vision: bool = True,
) -> dict[str, Any]:
    start = float(segment.get("start", 0))
    end = float(segment.get("end", start + 0.5))
    mid = start + (end - start) / 2
    duration = end - start

    t_before = max(0.0, start - 0.25)
    t_start = start + min(0.08, duration * 0.15)
    t_mid = mid
    t_end = max(start, end - min(0.08, duration * 0.15))

    paths = {
        "before": _extract_frame_to_dir(video_path, t_before, work_dir, "before"),
        "start": _extract_frame_to_dir(video_path, t_start, work_dir, "start"),
        "mid": _extract_frame_to_dir(video_path, t_mid, work_dir, "mid"),
        "end": _extract_frame_to_dir(video_path, t_end, work_dir, "end"),
    }

    before = _load_frame(paths["before"] or "")
    during = _load_frame(paths["mid"] or paths["start"] or "")
    if before is None or during is None:
        return _default_style()

    bbox = _find_subtitle_bbox(before, during)
    if bbox is None and paths["start"]:
        start_frame = _load_frame(paths["start"])
        if start_frame is not None:
            bbox = _find_subtitle_bbox(before, start_frame)

    if bbox is None:
        return _default_style()

    frame_h = during.shape[0]
    text_color, outline_color = _sample_text_colors(during, bbox)
    position = _position_from_bbox(bbox, frame_h)
    font_size = _estimate_font_size(bbox, frame_h)

    bboxes: list[tuple[int, int, int, int] | None] = []
    for key in ("start", "mid", "end"):
        frame = _load_frame(paths.get(key) or "")
        if frame is None or before is None:
            bboxes.append(None)
            continue
        bboxes.append(_find_subtitle_bbox(before, frame))

    animation_in, animation_out = _detect_animation(bboxes)

    style = {
        "text_color": text_color,
        "outline_color": outline_color,
        "font_size": font_size,
        "capcut_font_size": to_capcut_font_size({"font_size": font_size}, frame_height=frame_h),
        "position": position,
        "alignment": "center",
        "bold": False,
        "animation_in": animation_in,
        "animation_out": animation_out,
        "transform_y": _POSITION_TRANSFORM_Y.get(position, -400),
        "confidence": 0.72,
        "style_label": f"{_ANIMATION_LABELS.get(animation_in, animation_in)}·{text_color}",
    }

    if use_vision and paths.get("mid"):
        style = _maybe_refine_with_vision(paths["mid"], str(segment.get("text", "")), style)
        style["capcut_font_size"] = to_capcut_font_size(style, frame_height=frame_h)

    return style


def analyze_subtitle_styles(
    video_path: str,
    segments: list[dict[str, Any]],
    work_dir: str,
    *,
    max_segments: int | None = None,
) -> list[dict[str, Any]]:
    """为每条字幕分段补充 style 字段。"""
    if not ENABLE_SUBTITLE_STYLE_ANALYSIS or not video_path or not segments:
        return segments

    limit = max_segments if max_segments is not None else SUBTITLE_STYLE_MAX_SEGMENTS
    style_dir = os.path.join(work_dir, "subtitle_style_frames")
    os.makedirs(style_dir, exist_ok=True)

    enriched: list[dict[str, Any]] = []
    for index, seg in enumerate(segments):
        item = dict(seg)
        if index < limit:
            try:
                item["style"] = analyze_segment_style(video_path, item, style_dir)
            except Exception as exc:
                print(f"字幕样式分析失败 @ {seg.get('start')}: {exc}")
                item["style"] = _default_style()
        else:
            item["style"] = enriched[-1].get("style") if enriched else _default_style()
        enriched.append(item)

    print(f"字幕样式分析完成: {len(enriched)} 段（详细分析 {min(len(segments), limit)} 段）")
    return enriched


def merge_styles_into_slots(slots: list[dict[str, Any]], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将带 style 的全局 segments 合并进槽位 subtitle_segments。"""
    if not segments:
        return slots

    style_by_range: list[tuple[float, float, dict]] = []
    for seg in segments:
        st = seg.get("style")
        if not st:
            continue
        style_by_range.append((float(seg["start"]), float(seg["end"]), st))

    result = []
    for slot in slots:
        item = dict(slot)
        sub_segs = list(item.get("subtitle_segments") or [])
        if not sub_segs:
            result.append(item)
            continue

        merged_segs = []
        for sub in sub_segs:
            sub_item = dict(sub)
            ss = float(sub_item.get("start", 0))
            se = float(sub_item.get("end", ss))
            best_style = None
            best_overlap = 0.0
            for gs, ge, gst in style_by_range:
                overlap = max(0.0, min(se, ge) - max(ss, gs))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_style = gst
            if best_style:
                sub_item["style"] = best_style
            merged_segs.append(sub_item)

        item["subtitle_segments"] = merged_segs
        result.append(item)

    return result
