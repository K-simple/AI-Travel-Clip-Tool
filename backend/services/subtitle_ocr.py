"""从模板视频画面烧录字幕区域 OCR 识别（供槽位字幕编辑）。"""

from __future__ import annotations

import os
import re
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import cv2
import numpy as np

from services.processing_config import SUBTITLE_OCR_WORKERS
from services.scene_detector import extract_frame
from services.subtitle_gen import normalize_chinese_subtitle
from services.subtitle_style_analyzer import _find_subtitle_bbox
from utils.security import resolve_storage_path

_ocr_reader = None
_paddleocr_reader = None
_ocr_lock = None
OCR_MIN_CONFIDENCE = float(os.getenv("OCR_MIN_CONFIDENCE", "0.32"))
OCR_ENGINE = os.getenv("OCR_ENGINE", "easyocr").strip().lower()


def _ocr_lock_obj():
    global _ocr_lock
    if _ocr_lock is None:
        import threading
        _ocr_lock = threading.Lock()
    return _ocr_lock


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


def _enhance_for_ocr(image: np.ndarray, scale: float = 2.0, *, fast: bool = False) -> np.ndarray:
    if image is None or image.size == 0:
        return image
    h, w = image.shape[:2]
    if fast:
        max_w = int(os.getenv("OCR_FAST_MAX_WIDTH", "360"))
        if w > max_w:
            ratio = max_w / w
            image = cv2.resize(
                image,
                (max_w, max(1, int(h * ratio))),
                interpolation=cv2.INTER_AREA,
            )
            h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        return cv2.cvtColor(norm, cv2.COLOR_GRAY2BGR)

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


def _subtitle_band_crops(during: np.ndarray, before: np.ndarray | None, *, fast: bool = False) -> list[np.ndarray]:
    """提取可能的烧录字幕区域（差分 bbox + 下方条带）。"""
    crops: list[np.ndarray] = []
    if during is None or during.size == 0:
        return crops

    h, w = during.shape[:2]

    if not fast:
        bbox = None
        if before is not None and before.size > 0:
            bbox = _find_subtitle_bbox(before, during)

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
                crops.append(crop)

    y0_ratio, y1_ratio = (0.62, 0.94) if fast else (0.58, 0.92)
    band = during[int(h * y0_ratio) : int(h * y1_ratio), int(w * 0.05) : int(w * 0.95)]
    if band.size > 0:
        crops.append(band)

    if not fast:
        band2 = during[int(h * 0.58) : int(h * 0.92), int(w * 0.05) : int(w * 0.95)]
        if band2.size > 0 and band2 is not band:
            crops.append(band2)

    return crops


def _get_easyocr_reader():
    global _ocr_reader
    with _ocr_lock_obj():
        if _ocr_reader is None:
            import easyocr

            use_gpu = os.getenv("OCR_USE_GPU", "0").strip() in ("1", "true", "yes")
            _ocr_reader = easyocr.Reader(["ch_sim", "en"], gpu=use_gpu, verbose=False)
    return _ocr_reader


def _get_paddleocr_reader():
    global _paddleocr_reader
    with _ocr_lock_obj():
        if _paddleocr_reader is None:
            from paddleocr import PaddleOCR

            use_gpu = os.getenv("OCR_USE_GPU", "0").strip() in ("1", "true", "yes")
            # Paddle 3.x on Windows CPU：MKLDNN 可能触发 NotImplementedError
            enable_mkldnn = os.getenv("PADDLE_ENABLE_MKLDNN", "0").strip() in ("1", "true", "yes")
            if not use_gpu and os.name == "nt":
                enable_mkldnn = False
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            if not enable_mkldnn:
                os.environ.setdefault("FLAGS_use_mkldnn", "0")
            _paddleocr_reader = PaddleOCR(
                lang="ch",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device="gpu:0" if use_gpu else "cpu",
                enable_mkldnn=enable_mkldnn,
            )
    return _paddleocr_reader


def _parse_paddleocr_result(result: Any) -> str:
    if not result:
        return ""
    parts: list[str] = []
    for item in result:
        if hasattr(item, "json"):
            payload = item.json if isinstance(item.json, dict) else {}
            res = payload.get("res") if isinstance(payload.get("res"), dict) else payload
            texts = list(res.get("rec_texts") or [])
            scores = list(res.get("rec_scores") or [])
            for i, text in enumerate(texts):
                conf = float(scores[i]) if i < len(scores) else 1.0
                token = normalize_chinese_subtitle(str(text).strip())
                if token and conf >= OCR_MIN_CONFIDENCE:
                    parts.append(token)
            continue
        if not isinstance(item, (list, tuple)):
            continue
        for line in item:
            if not line or len(line) < 2:
                continue
            text_conf = line[1]
            if isinstance(text_conf, (list, tuple)) and len(text_conf) >= 2:
                text, conf = str(text_conf[0]), float(text_conf[1])
            else:
                text, conf = str(text_conf), 1.0
            token = normalize_chinese_subtitle(text.strip())
            if token and conf >= OCR_MIN_CONFIDENCE:
                parts.append(token)
    return normalize_chinese_subtitle("".join(parts))


def _ocr_with_paddleocr(image_path: str) -> str:
    reader = _get_paddleocr_reader()
    with _ocr_lock_obj():
        try:
            result = reader.predict(image_path)
            return _parse_paddleocr_result(result)
        except Exception as exc:
            print(f"PaddleOCR 失败: {exc}")
            return ""


def _ocr_with_paddleocr_image(image: np.ndarray) -> str:
    reader = _get_paddleocr_reader()
    with _ocr_lock_obj():
        try:
            result = reader.predict(image)
            return _parse_paddleocr_result(result)
        except Exception as exc:
            print(f"PaddleOCR 内存 OCR 失败: {exc}")
            return ""


def _ocr_with_local_engine(image_path: str) -> str:
    if OCR_ENGINE == "paddle":
        text = _ocr_with_paddleocr(image_path)
        if text:
            return text
        try:
            return _ocr_with_easyocr(image_path)
        except Exception:
            return ""
    return _ocr_with_easyocr(image_path)


def _ocr_with_local_engine_image(image: np.ndarray) -> str:
    if OCR_ENGINE == "paddle":
        text = _ocr_with_paddleocr_image(image)
        if text:
            return text
        return _ocr_with_easyocr_image(image)
    return _ocr_with_easyocr_image(image)


def _ocr_with_easyocr(image_path: str) -> str:
    reader = _get_easyocr_reader()
    try:
        detailed = reader.readtext(image_path, detail=1, paragraph=False)
        parts: list[str] = []
        for item in detailed:
            if len(item) < 3:
                continue
            _bbox, text, conf = item[0], item[1], float(item[2])
            token = normalize_chinese_subtitle(str(text).strip())
            if token and conf >= OCR_MIN_CONFIDENCE:
                parts.append(token)
        if parts:
            return normalize_chinese_subtitle("".join(parts))
    except Exception:
        pass

    results = reader.readtext(image_path, detail=0, paragraph=True)
    if not results:
        results = reader.readtext(image_path, detail=0)
    parts = [normalize_chinese_subtitle(str(item)) for item in results if str(item).strip()]
    return normalize_chinese_subtitle("".join(parts))


def preload_ocr_reader() -> None:
    """启动时或首次批量前预加载 OCR 引擎（OCR_ENGINE=paddle|easyocr）。"""
    if OCR_ENGINE == "paddle":
        try:
            _get_paddleocr_reader()
            return
        except Exception as exc:
            print(f"PaddleOCR 预加载失败，回退 EasyOCR: {exc}")
    _get_easyocr_reader()


def _ocr_with_easyocr_image(image: np.ndarray) -> str:
    """内存 OCR，批量路径免磁盘读写。"""
    reader = _get_easyocr_reader()
    with _ocr_lock_obj():
        try:
            detailed = reader.readtext(image, detail=1, paragraph=False)
            parts: list[str] = []
            for item in detailed:
                if len(item) < 3:
                    continue
                _bbox, text, conf = item[0], item[1], float(item[2])
                token = normalize_chinese_subtitle(str(text).strip())
                if token and conf >= OCR_MIN_CONFIDENCE:
                    parts.append(token)
            if parts:
                return normalize_chinese_subtitle("".join(parts))
        except Exception:
            pass
    return ""


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


def _run_ocr_on_image(image: np.ndarray, out_dir: str, tag: str, *, fast: bool = False) -> str:
    enhanced = _enhance_for_ocr(image, fast=fast)
    if fast:
        text = _ocr_with_local_engine_image(enhanced)
        return normalize_chinese_subtitle(text)

    crop_path = _save_crop(enhanced, out_dir, tag)
    if not crop_path:
        return ""

    text = ""
    if os.getenv("OCR_PREFER_VISION", "0").strip() in ("1", "true", "yes"):
        text = _ocr_with_vision(crop_path)
    if not text:
        try:
            text = _ocr_with_local_engine(crop_path)
        except Exception as exc:
            print(f"OCR 失败 ({OCR_ENGINE}): {exc}")
            text = ""
    if not text:
        text = _ocr_with_vision(crop_path)
    return normalize_chinese_subtitle(text)


def _sample_times(slot_start: float, slot_end: float, *, fast: bool = False) -> list[float]:
    duration = max(0.12, float(slot_end) - float(slot_start))
    if fast or duration <= 1.2:
        return [slot_start + duration * 0.5]
    if duration <= 2.0:
        return [slot_start + duration * 0.38, slot_start + duration * 0.72]
    return [
        slot_start + duration * 0.32,
        slot_start + duration * 0.52,
        slot_start + duration * 0.72,
    ]


def _ocr_text_at_time(
    video_path: str,
    time_sec: float,
    out_dir: str,
    *,
    fast: bool = False,
    band_y0: float | None = None,
    band_y1: float | None = None,
) -> str:
    during_path = _extract_frame(video_path, time_sec, out_dir, "mid")
    during = _load_frame(during_path or "")
    if during is None:
        return ""

    if band_y0 is not None and band_y1 is not None:
        h, w = during.shape[:2]
        crop = during[int(h * band_y0) : int(h * band_y1), int(w * 0.05) : int(w * 0.95)]
        if crop is not None and crop.size > 0:
            text = _run_ocr_on_image(
                crop,
                out_dir,
                f"band_{int(time_sec * 1000)}",
                fast=fast,
            )
            if text and len(re.sub(r"\s+", "", text)) >= 2:
                return text

    before = None
    if not fast:
        before_t = max(0.0, float(time_sec) - 0.18)
        before_path = _extract_frame(video_path, before_t, out_dir, "before")
        before = _load_frame(before_path or "")

    texts: list[str] = []
    crops = _subtitle_band_crops(during, before, fast=fast)
    for idx, crop in enumerate(crops[:1] if fast else crops):
        text = _run_ocr_on_image(crop, out_dir, f"t{int(time_sec*1000)}_{idx}", fast=fast)
        if text and len(re.sub(r"\s+", "", text)) >= 2:
            texts.append(text)
            if fast:
                break

    if not texts and not fast and during is not None:
        fallback = _run_ocr_on_image(during, out_dir, f"full_{int(time_sec*1000)}")
        if fallback:
            texts.append(fallback)

    return _consensus_ocr_texts(texts)


def _consensus_ocr_texts(texts: list[str]) -> str:
    cleaned = [normalize_chinese_subtitle(t) for t in texts if t and t.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]

    # 完全相同
    counter = Counter(cleaned)
    best_text, best_count = counter.most_common(1)[0]
    if best_count >= 2:
        return best_text

    # 取出现频率最高；并列时取 CJK 字数最多且较短的（更像单行字幕）
    def rank(text: str) -> tuple[int, int, int]:
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        return (counter[text], cjk, -len(text))

    return max(cleaned, key=rank)


def probe_visual_subtitle_text(
    video_path: str,
    slot_start: float,
    slot_end: float,
    work_dir: str | None = None,
) -> str:
    """轻量探测：OpenCV 单帧 + 内存 OCR。"""
    resolved = resolve_storage_path(video_path)
    if not resolved or not os.path.isfile(resolved):
        return ""
    slot_start = float(slot_start)
    slot_end = float(slot_end)
    if slot_end <= slot_start:
        return ""
    duration = slot_end - slot_start
    sample_t = slot_start + duration * 0.5
    cap = cv2.VideoCapture(resolved)
    if not cap.isOpened():
        return ""
    try:
        during = _read_frame_cv2(cap, sample_t)
        if during is None:
            return ""
        for crop in _subtitle_band_crops(during, None, fast=True)[:1]:
            text = _run_ocr_on_image(crop, "", "probe", fast=True)
            if text:
                return text
        return ""
    finally:
        cap.release()


def _read_frame_cv2(cap: cv2.VideoCapture, time_sec: float) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(time_sec)) * 1000.0)
    ok, frame = cap.read()
    if not ok or frame is None or frame.size == 0:
        return None
    return frame


def _visual_segment_from_text(text: str, slot_start: float, slot_end: float) -> list[dict[str, Any]]:
    text = normalize_chinese_subtitle(text)
    if not text:
        return []
    duration = float(slot_end) - float(slot_start)
    return [
        {
            "start": round(slot_start, 3),
            "end": round(slot_end, 3),
            "duration": round(duration, 3),
            "text": text,
            "source": "visual",
        }
    ]


def _read_frames_sequential(
    cap: cv2.VideoCapture,
    times: list[float],
) -> list[np.ndarray | None]:
    """按时间顺序读帧，减少反复 seek。"""
    if not times:
        return []
    indexed = sorted(enumerate(times), key=lambda x: x[1])
    frames: list[np.ndarray | None] = [None] * len(times)
    last_ms = -1.0
    for orig_i, t in indexed:
        target_ms = max(0.0, float(t)) * 1000.0
        if target_ms + 5 < last_ms:
            cap.set(cv2.CAP_PROP_POS_MSEC, target_ms)
        else:
            cap.set(cv2.CAP_PROP_POS_MSEC, target_ms)
        ok, frame = cap.read()
        last_ms = target_ms
        frames[orig_i] = frame if ok and frame is not None and frame.size > 0 else None
    return frames


def _ocr_slot_crops(
    idx: int,
    slot_start: float,
    slot_end: float,
    during,
    before,
    out_dir: str,
    *,
    quality: bool,
) -> list[dict[str, Any]]:
    text = ""
    crops = _subtitle_band_crops(during, before, fast=not quality)
    limit = len(crops) if quality else 1
    for crop_idx, crop in enumerate(crops[:limit]):
        text = _run_ocr_on_image(
            crop,
            out_dir,
            f"batch_{idx}_{crop_idx}",
            fast=not quality,
        )
        if text and len(re.sub(r"\s+", "", text)) >= 2:
            break
    return _visual_segment_from_text(text, slot_start, slot_end)


def recognize_slots_visual_batch(
    video_path: str,
    ranges: list[tuple[float, float]],
    *,
    quality: bool = False,
    parallel: bool | None = None,
) -> list[list[dict[str, Any]]]:
    """
    批量画面 OCR：单次打开视频，内存读帧。
    quality=True：差分定位 + 多区域 OCR（剪映式烧录字幕），可并行 OCR 提速。
    """
    resolved = resolve_storage_path(video_path)
    if not resolved or not os.path.isfile(resolved):
        raise RuntimeError("模板视频不存在")
    if not ranges:
        return []

    preload_ocr_reader()
    out_dir = _work_dir_for_video(resolved) if quality else ""
    cap = cv2.VideoCapture(resolved)
    if not cap.isOpened():
        raise RuntimeError("无法打开模板视频")

    sample_times = [
        float(s) + max(0.12, float(e) - float(s)) * 0.5
        for s, e in ranges
        if float(e) > float(s)
    ]
    frames = _read_frames_sequential(cap, sample_times) if sample_times else []

    prepared: list[tuple[int, float, float, Any, Any]] = []
    fi = 0
    for idx, (slot_start, slot_end) in enumerate(ranges):
        slot_start = float(slot_start)
        slot_end = float(slot_end)
        if slot_end <= slot_start:
            continue
        during = frames[fi] if fi < len(frames) else None
        fi += 1
        if during is None:
            continue
        before = None
        if quality:
            before_t = max(0.0, slot_start + (slot_end - slot_start) * 0.5 - 0.18)
            before = _read_frame_cv2(cap, before_t)
        prepared.append((idx, slot_start, slot_end, during, before))

    cap.release()

    use_parallel = parallel if parallel is not None else (quality and len(prepared) > 1)
    results: list[list[dict[str, Any]]] = [[] for _ in ranges]

    if use_parallel and quality:
        workers = min(SUBTITLE_OCR_WORKERS, max(1, len(prepared)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _ocr_slot_crops,
                    idx,
                    slot_start,
                    slot_end,
                    during,
                    before,
                    out_dir,
                    quality=quality,
                ): idx
                for idx, slot_start, slot_end, during, before in prepared
            }
            for future in futures:
                slot_i = futures[future]
                try:
                    results[slot_i] = future.result()
                except Exception as exc:
                    print(f"并行 OCR 槽位失败 #{slot_i}: {exc}")
        return results

    for idx, slot_start, slot_end, during, before in prepared:
        try:
            results[idx] = _ocr_slot_crops(
                idx, slot_start, slot_end, during, before, out_dir, quality=quality
            )
        except Exception as exc:
            print(f"OCR 槽位失败 #{idx}: {exc}")

    return results
