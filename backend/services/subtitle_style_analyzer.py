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


def _sample_text_colors(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> tuple[str, str]:
    x, y, w, h = bbox
    roi = frame[y : y + h, x : x + w]
    if roi.size == 0:
        return "#ffffff", "#000000"

    pixels = roi.reshape(-1, 3).astype(np.float32)
    if len(pixels) > 800:
        idx = np.linspace(0, len(pixels) - 1, 800, dtype=int)
        pixels = pixels[idx]

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    _, labels, centers = cv2.kmeans(pixels, 3, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=3)
    order = np.argsort(-counts)

    primary = tuple(int(c) for c in centers[order[0]])
    secondary = tuple(int(c) for c in centers[order[1] if len(order) > 1 else order[0]])

    lum_p = 0.299 * primary[2] + 0.587 * primary[1] + 0.114 * primary[0]
    lum_s = 0.299 * secondary[2] + 0.587 * secondary[1] + 0.114 * secondary[0]

    if lum_p >= lum_s:
        fill, outline = primary, secondary
    else:
        fill, outline = secondary, primary

    if lum_p > 200 and lum_s > 200:
        outline = (0, 0, 0)

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
        "transform_y": _POSITION_TRANSFORM_Y["bottom"],
        "confidence": 0.35,
        "style_label": "默认白字黑边",
    }


def style_to_capcut_params(style: dict[str, Any]) -> dict[str, Any]:
    return {
        "text_color": style.get("text_color") or "#ffffff",
        "font_size": int(style.get("font_size") or 18),
        "alignment": 1,
        "transform_y": int(style.get("transform_y") or _POSITION_TRANSFORM_Y["bottom"]),
    }


def style_signature(style: dict[str, Any]) -> str:
    return "|".join(
        str(style.get(k, ""))
        for k in ("text_color", "outline_color", "font_size", "transform_y", "animation_in")
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
