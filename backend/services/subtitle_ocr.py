"""从模板视频画面烧录字幕区域 OCR 识别（供槽位字幕编辑）。"""

import os
import re
import uuid
from typing import Any

import cv2
import numpy as np

from services.scene_detector import extract_frame
from services.subtitle_gen import normalize_chinese_subtitle
from services.subtitle_style_analyzer import _find_subtitle_bbox, analyze_segment_style
from utils.security import resolve_storage_path

_ocr_reader = None


def _work_dir_for_video(video_path: str) -> str:
    template_dir = os.path.dirname(resolve_storage_path(video_path))
    path = os.path.join(template_dir, "subtitle_ocr_frames")
    os.makedirs(path, exist_ok=True)
    return path


def _load_frame(path: str) -> np.ndarray | None:
    if not path or not os.path.isfile(path):
        return None
    img = cv2.imread(path)
    return img if img is not None and img.size > 0 else None


def _extract_frame(video_path: str, time_sec: float, out_dir: str, tag: str) -> str | None:
    os.makedirs(out_dir, exist_ok=True)
    safe_t = max(0.0, float(time_sec))
    out_path = os.path.join(out_dir, f"ocr_{tag}_{uuid.uuid4().hex[:8]}_{int(safe_t * 1000):06d}.jpg")
    try:
        extract_frame(resolve_storage_path(video_path), safe_t, out_path)
        return out_path if os.path.isfile(out_path) else None
    except Exception:
        return None


def _enhance_for_ocr(image: np.ndarray, scale: float = 2.0) -> np.ndarray:
    if image is None or image.size == 0:
        return image
    h, w = image.shape[:2]
    up = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 5, 55, 55)
    norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    return cv2.cvtColor(norm, cv2.COLOR_GRAY2BGR)


def _save_crop(image: np.ndarray, out_dir: str, tag: str) -> str | None:
    if image is None or image.size == 0:
        return None
    path = os.path.join(out_dir, f"crop_{tag}_{uuid.uuid4().hex[:8]}.jpg")
    ok = cv2.imwrite(path, image)
    return path if ok and os.path.isfile(path) else None


def _crop_subtitle_region(during: np.ndarray, before: np.ndarray | None) -> np.ndarray | None:
    if during is None or during.size == 0:
        return None

    bbox = None
    if before is not None and before.size > 0:
        bbox = _find_subtitle_bbox(before, during)

    h, w = during.shape[:2]
    if bbox is not None:
        x, y, bw, bh = bbox
        pad_x = int(bw * 0.08)
        pad_y = int(bh * 0.15)
        x0 = max(0, x - pad_x)
        y0 = max(0, y - pad_y)
        x1 = min(w, x + bw + pad_x)
        y1 = min(h, y + bh + pad_y)
        crop = during[y0:y1, x0:x1]
        if crop.size > 0:
            return crop

    # 竖屏短视频字幕常见在下方 1/3
    band = during[int(h * 0.58) : int(h * 0.92), int(w * 0.05) : int(w * 0.95)]
    return band if band.size > 0 else None


def _get_easyocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr

        use_gpu = os.getenv("OCR_USE_GPU", "0").strip() in ("1", "true", "yes")
        _ocr_reader = easyocr.Reader(["ch_sim", "en"], gpu=use_gpu, verbose=False)
    return _ocr_reader


def _ocr_with_easyocr(image_path: str) -> str:
    reader = _get_easyocr_reader()
    results = reader.readtext(image_path, detail=0, paragraph=True)
    if not results:
        results = reader.readtext(image_path, detail=0)
    parts = [normalize_chinese_subtitle(str(item)) for item in results if str(item).strip()]
    return normalize_chinese_subtitle("".join(parts))


def _ocr_with_vision(image_path: str) -> str:
    try:
        from services.deepseek_client import chat_vision, deepseek_enabled

        if not deepseek_enabled():
            return ""
        prompt = (
            "这是短视频画面截图。请识别画面中「烧录字幕」（叠加在画面上的文字）的完整内容。"
            "只输出字幕文字，不要解释、不要引号。若无可见字幕，只输出空字符串。"
        )
        raw = (chat_vision(prompt, [image_path], max_tokens=160, temperature=0.05) or "").strip()
        raw = re.sub(r"^[\"'「『]|[\"'」』]$", "", raw.strip())
        if raw.lower() in ("none", "null", "无", "无字幕", "没有字幕", "n/a"):
            return ""
        return normalize_chinese_subtitle(raw)
    except Exception:
        return ""


def _run_ocr_on_image(image: np.ndarray, out_dir: str, tag: str) -> str:
    enhanced = _enhance_for_ocr(image)
    crop_path = _save_crop(enhanced, out_dir, tag)
    if not crop_path:
        return ""

    text = ""
    if os.getenv("OCR_PREFER_VISION", "0").strip() in ("1", "true", "yes"):
        text = _ocr_with_vision(crop_path)
    if not text:
        try:
            text = _ocr_with_easyocr(crop_path)
        except Exception as exc:
            print(f"EasyOCR 失败: {exc}")
            text = ""
    if not text:
        text = _ocr_with_vision(crop_path)
    return normalize_chinese_subtitle(text)


def recognize_slot_visual(
    video_path: str,
    slot_start: float,
    slot_end: float,
    work_dir: str | None = None,
) -> list[dict[str, Any]]:
    """识别单个槽位时间范围内画面上的烧录字幕。"""
    resolved = resolve_storage_path(video_path)
    if not resolved or not os.path.isfile(resolved):
        raise RuntimeError("模板视频不存在")

    slot_start = float(slot_start)
    slot_end = float(slot_end)
    if slot_end <= slot_start:
        return []

    out_dir = work_dir or _work_dir_for_video(resolved)
    duration = slot_end - slot_start
    sample_t = slot_start + duration * 0.42
    before_t = max(0.0, slot_start - min(0.2, duration * 0.25))

    during_path = _extract_frame(resolved, sample_t, out_dir, "mid")
    before_path = _extract_frame(resolved, before_t, out_dir, "before")
    during = _load_frame(during_path or "")
    before = _load_frame(before_path or "")

    if during is None:
        return []

    crop = _crop_subtitle_region(during, before)
    text = _run_ocr_on_image(crop, out_dir, "slot") if crop is not None else ""

    if not text and during is not None:
        text = _run_ocr_on_image(during, out_dir, "full")

    if not text:
        return []

    style: dict[str, Any] | None = None
    try:
        seg = {"start": slot_start, "end": slot_end, "text": text}
        style = analyze_segment_style(resolved, seg, out_dir, use_vision=False)
    except Exception:
        style = None

    item: dict[str, Any] = {
        "start": round(slot_start, 3),
        "end": round(slot_end, 3),
        "duration": round(duration, 3),
        "text": text,
        "source": "visual",
    }
    if style:
        item["style"] = style
    return [item]
