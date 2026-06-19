"""判断人声转写字幕质量是否可接受，用于 auto 模式回退到画面 OCR。"""

import re
from typing import Iterable


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
    if duplicate_peers >= 2 and chars >= 12:
        return False, "duplicate_across_slots"

    # 明显乱码/非中文占比过高
    cjk = len(re.findall(r"[\u4e00-\u9fff]", cleaned))
    if chars >= 6 and cjk / max(chars, 1) < 0.35:
        return False, "low_chinese_ratio"

    return True, "ok"


def count_duplicate_peers(text: str, peer_texts: Iterable[str]) -> int:
    target = (text or "").strip()
    if not target or _char_count(target) < 8:
        return 0
    return sum(1 for peer in peer_texts if (peer or "").strip() == target)
