"""字幕黄金集评测：指标计算与结果对比（供 scripts/run_subtitle_golden_eval.py 使用）。"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from services.subtitle_quality import (
    SUBTITLE_DUPLICATE_MIN_CHARS,
    count_near_duplicate_peers,
    subtitle_text_from_segments,
)


def _char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def slot_text(slot: dict[str, Any]) -> str:
    text = str(slot.get("subtitle_text") or "").strip()
    if text:
        return text
    return subtitle_text_from_segments(slot.get("subtitle_segments") or [])


def nonempty_rate(slots: list[dict[str, Any]]) -> float:
    if not slots:
        return 0.0
    ready = sum(1 for s in slots if slot_text(s))
    return ready / len(slots)


def duplicate_rate(
    slots: list[dict[str, Any]],
    *,
    min_chars: int | None = None,
) -> float:
    if not slots:
        return 0.0
    threshold = SUBTITLE_DUPLICATE_MIN_CHARS if min_chars is None else min_chars
    peer_texts: list[str] = []
    dup_slots = 0
    for slot in slots:
        text = slot_text(slot)
        if text and _char_count(text) >= threshold:
            if count_near_duplicate_peers(text, peer_texts) >= 1:
                dup_slots += 1
            peer_texts.append(text)
    return dup_slots / len(slots)


def source_distribution(slots: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for slot in slots:
        src = str(slot.get("subtitle_source") or "none").strip() or "none"
        counts[src] += 1
    return dict(counts)


def normalize_for_compare(text: str) -> str:
    cleaned = re.sub(r"\s+", "", (text or "").strip())
    cleaned = re.sub(r"[，,。\.！!？?；;：:\"'\[\]【】]", "", cleaned)
    return cleaned.lower()


def slot_match_rate(actual: list[dict[str, Any]], expected: list[dict[str, Any]]) -> float:
    """按槽位顺序比较归一化文本一致率。"""
    if not expected:
        return 1.0 if not actual else 0.0
    n = min(len(actual), len(expected))
    if n == 0:
        return 0.0
    hits = 0
    for i in range(n):
        a = normalize_for_compare(slot_text(actual[i]))
        e = normalize_for_compare(slot_text(expected[i]))
        if not e and not a:
            hits += 1
        elif e and a and (a == e or e in a or a in e):
            hits += 1
    return hits / len(expected)


def optional_cer(actual: str, expected: str) -> float | None:
    try:
        from jiwer import cer
    except ImportError:
        return None
    a = normalize_for_compare(actual)
    e = normalize_for_compare(expected)
    if not e:
        return None
    return float(cer(e, a))


def aggregate_slot_text(slots: list[dict[str, Any]]) -> str:
    return " ".join(slot_text(s) for s in slots if slot_text(s))


def evaluate_case_metrics(
    actual_slots: list[dict[str, Any]],
    expected_slots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "slot_count": len(actual_slots),
        "nonempty_rate": round(nonempty_rate(actual_slots), 4),
        "duplicate_rate": round(duplicate_rate(actual_slots), 4),
        "source_distribution": source_distribution(actual_slots),
    }
    if expected_slots is not None:
        metrics["slot_match_rate"] = round(slot_match_rate(actual_slots, expected_slots), 4)
        cer_val = optional_cer(
            aggregate_slot_text(actual_slots),
            aggregate_slot_text(expected_slots),
        )
        if cer_val is not None:
            metrics["cer"] = round(cer_val, 4)
    return metrics


def load_expected(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("slots") or data.get("timeline") or []
    return []


def resolve_manifest_path(base: Path, raw: str) -> Path:
    p = Path(raw)
    if p.is_file():
        return p
    return (base / raw).resolve()


def case_passed(metrics: dict[str, Any], case: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    min_rate = float(case.get("min_nonempty_rate", 0.8))
    if metrics["nonempty_rate"] < min_rate:
        reasons.append(f"nonempty_rate {metrics['nonempty_rate']:.0%} < {min_rate:.0%}")

    max_dup = case.get("max_duplicate_rate")
    if max_dup is not None and metrics["duplicate_rate"] > float(max_dup):
        reasons.append(
            f"duplicate_rate {metrics['duplicate_rate']:.0%} > {float(max_dup):.0%}"
        )

    min_match = case.get("min_slot_match_rate")
    if min_match is not None and metrics.get("slot_match_rate", 0) < float(min_match):
        reasons.append(
            f"slot_match_rate {metrics.get('slot_match_rate', 0):.0%} < {float(min_match):.0%}"
        )

    max_cer = case.get("max_cer")
    if max_cer is not None and metrics.get("cer") is not None and metrics["cer"] > float(max_cer):
        reasons.append(f"cer {metrics['cer']:.2%} > {float(max_cer):.2%}")

    return len(reasons) == 0, reasons
