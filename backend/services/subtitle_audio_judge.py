"""槽位音频/ASR 可靠性判断：杂音或乱码时回退画面 OCR。"""

from __future__ import annotations

import os
import re
import struct
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from services.subtitle_quality import (
    _char_count,
    is_subtitle_quality_acceptable,
    subtitle_text_from_segments,
)
from utils.security import resolve_storage_path

WHISPER_LOGPROB_BAD = float(os.getenv("SUBTITLE_WHISPER_LOGPROB_BAD", "-0.85"))
NO_SPEECH_BAD = float(os.getenv("SUBTITLE_NO_SPEECH_BAD", "0.42"))
SLOT_SNR_BAD_DB = float(os.getenv("SUBTITLE_SLOT_SNR_BAD_DB", "8.0"))


@dataclass(frozen=True)
class AsrReliability:
    reliable: bool
    score: float
    reason: str


def _overlapping_segments(
    segments_json: list[dict[str, Any]],
    slot_start: float,
    slot_end: float,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for seg in segments_json or []:
        if not isinstance(seg, dict):
            continue
        ss = float(seg.get("start", 0))
        se = float(seg.get("end", ss))
        overlap = min(slot_end, se) - max(slot_start, ss)
        if overlap > 0.02:
            hits.append(seg)
    return hits


def whisper_confidence_for_slot(
    segments_json: list[dict[str, Any]] | None,
    slot_start: float,
    slot_end: float,
) -> tuple[float | None, float | None]:
    """返回槽位重叠段落的 (avg_logprob, no_speech_prob) 均值。"""
    if not segments_json:
        return None, None
    segs = _overlapping_segments(segments_json, slot_start, slot_end)
    if not segs:
        return None, None
    logprobs: list[float] = []
    no_speech: list[float] = []
    for seg in segs:
        if seg.get("avg_logprob") is not None:
            logprobs.append(float(seg["avg_logprob"]))
        if seg.get("no_speech_prob") is not None:
            no_speech.append(float(seg["no_speech_prob"]))
    lp = sum(logprobs) / len(logprobs) if logprobs else None
    nsp = sum(no_speech) / len(no_speech) if no_speech else None
    return lp, nsp


def is_asr_garbled(text: str) -> tuple[bool, str]:
    """检测 ASR 乱码/幻觉（如 2飞7、未闭合括号、怪问句）。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return False, ""

    chars = _char_count(cleaned)
    if chars < 2:
        return False, ""

    if re.search(r"[\[\]【】]$", cleaned) or re.search(r"^[\[\]【】]", cleaned):
        return True, "broken_brackets"

    open_b = cleaned.count("[") + cleaned.count("【")
    close_b = cleaned.count("]") + cleaned.count("】")
    if open_b != close_b:
        return True, "unbalanced_brackets"

    digits = len(re.findall(r"\d", cleaned))
    if digits >= 1 and re.search(r"\d[\u4e00-\u9fff]|\u4e00-\u9fff]\d", cleaned):
        if digits >= 2 or (digits >= 1 and chars <= 12):
            return True, "digit_in_speech"

    cjk = len(re.findall(r"[\u4e00-\u9fff]", cleaned))
    if chars >= 5 and cjk / max(chars, 1) < 0.5:
        return True, "low_chinese"

    if "?" in cleaned or "？" in cleaned:
        if chars <= 14 and not any(w in cleaned for w in ("吗", "呢", "么", "什么", "怎么", "为什么")):
            return True, "odd_question"

    weird = re.findall(r"[^\u4e00-\u9fffA-Za-z0-9，。！？；：、""''（）()\s]", cleaned)
    if len(weird) >= 2:
        return True, "special_chars"

    # Whisper 常见误听 / 缺字
    if re.search(r"努士|杨努", cleaned):
        return True, "phonetic_error"
    if re.search(r"哈尔的|哈尔来", cleaned) and "哈尔滨" not in cleaned:
        return True, "truncated_place"
    if re.search(r"通过视频也是我|也是我$", cleaned):
        return True, "broken_grammar"
    if re.search(r"找到我的", cleaned) is None and "通过视频" in cleaned and len(cleaned) <= 16:
        return True, "incomplete_phrase"

    return False, ""


def _estimate_slot_snr_db(source_path: str, slot_start: float, slot_end: float) -> float | None:
    """轻量 SNR 估计：人声能量 vs 首尾静音底噪（仅对可疑槽调用）。"""
    resolved = resolve_storage_path(source_path)
    if not resolved or not os.path.isfile(resolved):
        return None

    duration = max(0.15, float(slot_end) - float(slot_start))
    temp_path = os.path.join(
        "storage", "temp", f"snr_{uuid.uuid4().hex}.wav"
    )
    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(max(0.0, slot_start)),
            "-t", str(duration),
            "-i", resolved,
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le",
            temp_path,
        ]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
        )
        if result.returncode != 0 or not os.path.isfile(temp_path):
            return None

        with open(temp_path, "rb") as f:
            raw = f.read()
        if len(raw) < 64:
            return None
        samples = struct.unpack(f"<{len(raw)//2}h", raw[: (len(raw) // 2) * 2])
        if not samples:
            return None

        n = len(samples)
        edge = max(1, int(n * 0.12))
        noise = samples[:edge] + samples[-edge:]
        speech = samples[edge:-edge] if n > edge * 2 else samples

        def rms(block: Iterable[int]) -> float:
            blk = list(block)
            if not blk:
                return 0.0
            return (sum(x * x for x in blk) / len(blk)) ** 0.5

        noise_rms = max(rms(noise), 1.0)
        speech_rms = rms(speech)
        if speech_rms <= noise_rms:
            return 0.0
        import math
        return 20.0 * math.log10(speech_rms / noise_rms)
    except (OSError, struct.error, ValueError):
        return None
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def assess_asr_reliability(
    audio_segments: list,
    slot_start: float,
    slot_end: float,
    peer_texts: list[str] | None = None,
    *,
    segments_json: list[dict[str, Any]] | None = None,
    source_path: str | None = None,
    check_audio_noise: bool = False,
) -> AsrReliability:
    """
    判断槽位 ASR 是否可信。
    score 越高越可信；reliable=False 时应优先画面 OCR。
    """
    text = subtitle_text_from_segments(audio_segments)
    slot_duration = max(0.12, float(slot_end) - float(slot_start))
    peers = peer_texts or []

    if not text:
        return AsrReliability(False, 0.0, "empty")

    score = 72.0
    reasons: list[str] = []

    ok, q_reason = is_subtitle_quality_acceptable(
        text, slot_duration, duplicate_peers=0
    )
    if not ok:
        score -= 38.0
        reasons.append(q_reason)

    garbled, g_reason = is_asr_garbled(text)
    if garbled:
        score -= 45.0
        reasons.append(g_reason)

    dup = sum(1 for p in peers if (p or "").strip() == text.strip() and _char_count(text) >= 6)
    if dup >= 1:
        score -= 30.0
        reasons.append("duplicate")

    avg_lp, no_sp = whisper_confidence_for_slot(segments_json or [], slot_start, slot_end)
    if avg_lp is not None and avg_lp < WHISPER_LOGPROB_BAD:
        score -= 28.0
        reasons.append("low_logprob")
    if no_sp is not None and no_sp > NO_SPEECH_BAD:
        score -= 32.0
        reasons.append("no_speech")

    if check_audio_noise and source_path and score < 55.0:
        snr = _estimate_slot_snr_db(source_path, slot_start, slot_end)
        if snr is not None and snr < SLOT_SNR_BAD_DB:
            score -= 25.0
            reasons.append("noisy_audio")

    reliable = score >= 52.0 and not garbled and ok
    reason = reasons[0] if reasons else "ok"
    return AsrReliability(reliable, score, reason)
