"""判断人声转写字幕质量是否可接受，用于 auto 模式回退到画面 OCR。"""

import os
import re
from difflib import SequenceMatcher
from typing import Iterable

SUBTITLE_DUPLICATE_MIN_CHARS = int(os.getenv("SUBTITLE_DUPLICATE_MIN_CHARS", "8"))
SUBTITLE_DUPLICATE_SIMILARITY = float(os.getenv("SUBTITLE_DUPLICATE_SIMILARITY", "0.88"))


def subtitle_text_from_segments(segments: list) -> str:
    parts = [str(seg.get("text", "")).strip() for seg in segments if isinstance(seg, dict)]
    return " ".join(p for p in parts if p).strip()


def _char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def is_subtitle_quality_acceptable(
    text: str,
    slot_duration: float,
    *,
    duplicate_peers: int = 0,
) -> tuple[bool, str]:
    """
    评估人声转写结果是否可用。
    返回 (是否接受, 原因简述)。
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return False, "empty"

    chars = _char_count(cleaned)
    duration = max(0.12, float(slot_duration))
    cps = chars / duration

    # 短槽位塞入过长文本 — 常见于整段旁白误匹配
    if duration <= 2.5 and chars > max(22, duration * 11):
        return False, "too_long_for_slot"
    if duration <= 4.5 and cps > 13:
        return False, "speech_rate_implausible"
    if chars > 55 and duration <= 3.5:
        return False, "paragraph_in_short_slot"

    # 批量时多槽位出现相同长文本
    if duplicate_peers >= 1 and chars >= SUBTITLE_DUPLICATE_MIN_CHARS:
        return False, "duplicate_across_slots"

    # 明显乱码/非中文占比过高
    cjk = len(re.findall(r"[\u4e00-\u9fff]", cleaned))
    if chars >= 6 and cjk / max(chars, 1) < 0.35:
        return False, "low_chinese_ratio"

    from services.subtitle_audio_judge import is_asr_garbled

    garbled, g_reason = is_asr_garbled(cleaned)
    if garbled:
        return False, g_reason

    return True, "ok"


def text_similarity(a: str, b: str) -> float:
    """0~1，越高表示两路识别越接近（与 fusion 评分一致）。"""
    ta = re.sub(r"\s+", "", (a or "").strip())
    tb = re.sub(r"\s+", "", (b or "").strip())
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()


def count_near_duplicate_peers(text: str, peer_texts: Iterable[str]) -> int:
    """统计已有 peer 中与 text 精确或模糊重复的数量（统一 fusion/status/评测阈值）。"""
    target = (text or "").strip()
    if not target or _char_count(target) < SUBTITLE_DUPLICATE_MIN_CHARS:
        return 0
    count = 0
    for peer in peer_texts:
        peer_text = (peer or "").strip()
        if not peer_text:
            continue
        if peer_text == target:
            count += 1
        elif text_similarity(target, peer_text) >= SUBTITLE_DUPLICATE_SIMILARITY:
            count += 1
    return count


def count_duplicate_peers(text: str, peer_texts: Iterable[str]) -> int:
    """兼容旧名：与 count_near_duplicate_peers 相同（精确 + fuzzy）。"""
    return count_near_duplicate_peers(text, peer_texts)


def postprocess_subtitle_text(text: str) -> str:
    """剪映式轻量后处理：标点规整、去多余空白。"""
    from services.subtitle_gen import normalize_chinese_subtitle

    cleaned = normalize_chinese_subtitle(text or "")
    if not cleaned:
        return ""
    cleaned = re.sub(r"[，,]{2,}", "，", cleaned)
    cleaned = re.sub(r"[。\.]{2,}", "。", cleaned)
    cleaned = re.sub(r"[\[\]【】]+$", "", cleaned)
    cleaned = re.sub(r"^[\[\]【】]+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def postprocess_slot_segments(segments: list) -> list:
    """对槽位字幕段落做统一后处理。"""
    out: list = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        text = postprocess_subtitle_text(str(seg.get("text", "")))
        if not text:
            continue
        item = dict(seg)
        item["text"] = text
        out.append(item)
    return out
