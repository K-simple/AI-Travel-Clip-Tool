"""从完整 spoken_caption 主轨切分到画面槽位（禁止重复分配 word/字符）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from services.subtitle_config import SubtitleConfig, get_subtitle_config

SLOT_STATUS_MATCHED = "matched"
SLOT_STATUS_NO_SPEECH = "no_speech"
SLOT_STATUS_NO_OVERLAP = "no_overlap"
SLOT_STATUS_FILTERED = "filtered"
SLOT_STATUS_ERROR = "error"

_LAST_SPLIT_DEBUG: dict[str, Any] = {}


def get_last_split_debug() -> dict[str, Any]:
    return dict(_LAST_SPLIT_DEBUG)


def _normalize(text: str) -> str:
    """轻量中文清理，避免依赖 subtitle_gen / faster_whisper。"""
    if not text:
        return ""
    text = str(text).strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+([，。！？；：、])", r"\1", text)
    text = re.sub(r"([，。！？；：、])\s+", r"\1", text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。\.]{2,}", "。", text)
    return text.strip()


def _is_spoken_segment(seg: dict[str, Any]) -> bool:
    seg_type = str(seg.get("type") or "spoken_caption")
    return seg_type not in ("screen_text", "burned_subtitle_candidate", "uncertain")


def _slot_key(slot: dict[str, Any], index: int) -> str:
    sid = slot.get("slot_id") or slot.get("id")
    return str(sid) if sid is not None else f"slot_{index}"


def _slot_time_range(slot: dict[str, Any]) -> tuple[float, float]:
    if slot.get("clip_start") is not None:
        start = float(slot["clip_start"])
        if slot.get("clip_end") is not None:
            end = float(slot["clip_end"])
        else:
            end = start + float(slot.get("clip_duration") or slot.get("duration") or 0.1)
    else:
        start = float(slot.get("start", slot.get("slot_start", 0)))
        if slot.get("end") is not None:
            end = float(slot["end"])
        elif slot.get("end_time") is not None:
            end = float(slot["end_time"])
        else:
            end = start + float(slot.get("duration") or slot.get("slot_duration") or 0.1)
    return start, max(start + 0.05, end)


def _overlap(seg_start: float, seg_end: float, range_start: float, range_end: float) -> float:
    return min(seg_end, range_end) - max(seg_start, range_start)


def _char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _text_similarity(a: str, b: str) -> float:
    ca = _normalize(a)
    cb = _normalize(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    if ca in cb or cb in ca:
        return min(len(ca), len(cb)) / max(len(ca), len(cb))
    common = sum(1 for ch in ca if ch in cb)
    return common / max(len(ca), len(cb))


@dataclass
class _WordItem:
    token: str
    start: float
    end: float
    mid: float
    segment_id: str
    word_index: int
    confidence: float | None = None


@dataclass
class _SlotBucket:
    slot_index: int
    slot_key: str
    start: float
    end: float
    words: list[_WordItem] = field(default_factory=list)
    segment_ids: set[str] = field(default_factory=set)
    linked_word_ids: list[str] = field(default_factory=list)


def _find_slot_for_mid(
    mid: float,
    buckets: list[_SlotBucket],
    padding: float,
) -> int | None:
    hits: list[tuple[int, float]] = []
    for b in buckets:
        if b.start - padding <= mid <= b.end + padding:
            overlap = _overlap(b.start, b.end, mid - 0.01, mid + 0.01)
            hits.append((b.slot_index, overlap if overlap > 0 else 0.01))
    if hits:
        hits.sort(key=lambda x: (-x[1], x[0]))
        return hits[0][0]

    nearest: tuple[int, float] | None = None
    for b in buckets:
        if mid < b.start:
            dist = b.start - mid
        elif mid > b.end:
            dist = mid - b.end
        else:
            dist = 0.0
        if dist <= padding and (nearest is None or dist < nearest[1]):
            nearest = (b.slot_index, dist)
    return nearest[0] if nearest else None


def _collect_words(spoken_segments: list[dict[str, Any]]) -> list[_WordItem]:
    items: list[_WordItem] = []
    for seg in spoken_segments:
        if not isinstance(seg, dict) or not _is_spoken_segment(seg):
            continue
        seg_id = str(seg.get("id") or "")
        words = seg.get("words")
        if not isinstance(words, list):
            continue
        for wi, word in enumerate(words):
            if not isinstance(word, dict):
                continue
            token = _normalize(str(word.get("word") or ""))
            if not token:
                continue
            ws = float(word.get("start", 0))
            we = float(word.get("end", ws))
            items.append(
                _WordItem(
                    token=token,
                    start=ws,
                    end=we,
                    mid=(ws + we) / 2.0,
                    segment_id=seg_id,
                    word_index=wi,
                    confidence=float(seg.get("confidence")) if seg.get("confidence") is not None else None,
                )
            )
    items.sort(key=lambda w: (w.start, w.word_index))
    return items


def _assign_words_to_buckets(
    words: list[_WordItem],
    buckets: list[_SlotBucket],
    cfg: SubtitleConfig,
) -> tuple[int, int]:
    padding = float(cfg.slot_word_padding_sec)
    assigned = 0
    unassigned = 0
    taken: set[tuple[str, int]] = set()

    for word in words:
        key = (word.segment_id, word.word_index)
        if key in taken:
            continue
        slot_idx = _find_slot_for_mid(word.mid, buckets, padding) if cfg.assign_by_word_midpoint else None
        if slot_idx is None:
            unassigned += 1
            continue
        taken.add(key)
        bucket = buckets[slot_idx]
        bucket.words.append(word)
        if word.segment_id:
            bucket.segment_ids.add(word.segment_id)
        bucket.linked_word_ids.append(f"{word.segment_id}:{word.word_index}")
        assigned += 1

    return assigned, unassigned


def _segments_without_words(spoken_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for seg in spoken_segments:
        if not isinstance(seg, dict) or not _is_spoken_segment(seg):
            continue
        words = seg.get("words")
        if isinstance(words, list) and words:
            continue
        text = _normalize(str(seg.get("text") or ""))
        if text:
            out.append(seg)
    return out


def _assign_segment_exclusive(
    seg: dict[str, Any],
    buckets: list[_SlotBucket],
    assigned_segment_slots: dict[str, int],
    cfg: SubtitleConfig,
) -> None:
    """无 words：按 overlap 最大单槽分配，或按时间比例切分文本（每字只出现一次）。"""
    seg_id = str(seg.get("id") or "")
    seg_start = float(seg.get("start", 0))
    seg_end = float(seg.get("end", seg_start))
    if seg_end <= seg_start:
        return
    text = _normalize(str(seg.get("text") or ""))
    if not text:
        return

    overlaps: list[tuple[int, float, float, float]] = []
    for b in buckets:
        ov_start = max(seg_start, b.start)
        ov_end = min(seg_end, b.end)
        ov = ov_end - ov_start
        if ov > 0:
            overlaps.append((b.slot_index, ov, ov_start, ov_end))

    if not overlaps:
        return

    if seg_id and seg_id in assigned_segment_slots:
        return

    chars = list(text)
    n = len(chars)
    seg_dur = max(0.05, seg_end - seg_start)

    if len(overlaps) == 1 or n <= 1:
        slot_idx = max(overlaps, key=lambda x: x[1])[0]
        buckets[slot_idx].words.append(
            _WordItem(
                token=text,
                start=seg_start,
                end=seg_end,
                mid=(seg_start + seg_end) / 2.0,
                segment_id=seg_id,
                word_index=-1,
            )
        )
        if seg_id:
            buckets[slot_idx].segment_ids.add(seg_id)
            assigned_segment_slots[seg_id] = slot_idx
        return

    overlaps.sort(key=lambda x: buckets[x[0]].start)
    total_ov = sum(x[1] for x in overlaps)
    cursor = 0
    for i, (slot_idx, ov, _, _) in enumerate(overlaps):
        if i == len(overlaps) - 1:
            chunk = "".join(chars[cursor:])
        else:
            count = max(0, int(round(n * ov / total_ov)))
            if count == 0 and ov / seg_dur >= 0.08:
                count = 1
            chunk = "".join(chars[cursor : cursor + count])
            cursor += count
        chunk = _normalize(chunk)
        if not chunk:
            continue
        buckets[slot_idx].words.append(
            _WordItem(
                token=chunk,
                start=seg_start,
                end=seg_end,
                mid=(seg_start + seg_end) / 2.0,
                segment_id=seg_id,
                word_index=-100 - i,
            )
        )
        buckets[slot_idx].segment_ids.add(seg_id)
    if seg_id:
        assigned_segment_slots[seg_id] = overlaps[0][0]


def _bucket_to_derived_segment(
    bucket: _SlotBucket,
    spoken_segments: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], float]:
    text = _normalize("".join(w.token for w in bucket.words))
    if not text:
        return "", [], 0.0

    seg_map = {str(s.get("id") or ""): s for s in spoken_segments if isinstance(s, dict)}
    confs: list[float] = []
    profile_id = None
    render_hints = None
    for sid in bucket.segment_ids:
        seg = seg_map.get(sid)
        if seg:
            if seg.get("confidence") is not None:
                confs.append(float(seg["confidence"]))
            if profile_id is None and seg.get("effectProfileId"):
                profile_id = seg.get("effectProfileId")
            if render_hints is None and seg.get("renderHints"):
                render_hints = seg.get("renderHints")

    confidence = round(min(confs), 3) if confs else 0.5
    linked_ids = sorted(bucket.segment_ids)
    source_refs = [
        {
            "id": sid,
            "start": seg_map[sid].get("start"),
            "end": seg_map[sid].get("end"),
            "text": seg_map[sid].get("text"),
            "confidence": seg_map[sid].get("confidence"),
        }
        for sid in linked_ids
        if sid in seg_map
    ]

    derived = [
        {
            "id": f"slot_{bucket.start:.2f}_{bucket.end:.2f}",
            "start": round(bucket.start, 3),
            "end": round(bucket.end, 3),
            "duration": round(bucket.end - bucket.start, 3),
            "text": text,
            "source": "asr",
            "type": "slot_derived_caption",
            "confidence": confidence,
            "effectProfileId": profile_id,
            "renderHints": render_hints or {},
            "linkedSubtitleSegmentIds": linked_ids,
            "linkedWordIds": list(bucket.linked_word_ids),
            "source_segments": source_refs,
        }
    ]
    return text, derived, confidence


def _strip_prefix_overlap(prev_text: str, curr_text: str) -> str:
    """保留 curr 中相对 prev 的新增部分。"""
    if not prev_text or not curr_text:
        return curr_text
    if curr_text == prev_text:
        return ""
    if curr_text in prev_text:
        return ""
    best = 0
    max_k = min(len(prev_text), len(curr_text))
    for k in range(max_k, 0, -1):
        if prev_text.endswith(curr_text[:k]):
            best = k
            break
    remainder = curr_text[best:]
    return _normalize(remainder)


def _dedupe_adjacent_slots(slots: list[dict[str, Any]], cfg: SubtitleConfig) -> int:
    if not cfg.prevent_duplicate_slot_text:
        return 0
    fix_count = 0
    for i in range(1, len(slots)):
        prev = slots[i - 1]
        curr = slots[i]
        prev_text = _normalize(str(prev.get("subtitle_text") or ""))
        curr_text = _normalize(str(curr.get("subtitle_text") or ""))
        if not prev_text or not curr_text:
            continue

        prev_ids = set(prev.get("linked_subtitle_segment_ids") or prev.get("linkedSubtitleSegmentIds") or [])
        curr_ids = set(curr.get("linked_subtitle_segment_ids") or curr.get("linkedSubtitleSegmentIds") or [])
        ids_overlap = prev_ids & curr_ids if prev_ids and curr_ids else False

        should_fix = False
        new_text = curr_text

        if curr_text == prev_text:
            should_fix = True
            new_text = ""
        elif ids_overlap or _text_similarity(prev_text, curr_text) >= 0.55:
            stripped = _strip_prefix_overlap(prev_text, curr_text)
            if stripped != curr_text:
                should_fix = True
                new_text = stripped
            elif curr_text in prev_text or _text_similarity(prev_text, curr_text) >= 0.92:
                should_fix = True
                new_text = ""
        elif _text_similarity(prev_text, curr_text) >= 0.92:
            should_fix = True
            new_text = ""

        if should_fix and new_text != curr_text:
            sid = curr.get("slot_id") or curr.get("id")
            print(
                f"[subtitle][dedupe] removed duplicated slot text slot={sid} "
                f"was='{curr_text[:24]}...'"
            )
            curr["subtitle_text"] = new_text
            if not new_text:
                curr["subtitle_status"] = SLOT_STATUS_NO_SPEECH
                curr["subtitle_status_reason"] = "dedupe_removed_duplicate"
                curr["subtitle_quality"] = "empty"
            fix_count += 1

    return fix_count


def split_spoken_caption_by_slots(
    spoken_segments: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    *,
    config: SubtitleConfig | None = None,
    effect_profile: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    从完整 spoken_caption 主轨切分到画面槽位。
    每个 word/字符时间片只分配给一个 slot。
    """
    global _LAST_SPLIT_DEBUG
    cfg = config or get_subtitle_config()
    spoken_pool = [s for s in (spoken_segments or []) if isinstance(s, dict) and _is_spoken_segment(s)]

    buckets: list[_SlotBucket] = []
    out_slots: list[dict[str, Any]] = []
    for i, slot in enumerate(slots or []):
        if not isinstance(slot, dict):
            out_slots.append(slot)
            continue
        start, end = _slot_time_range(slot)
        key = _slot_key(slot, i)
        buckets.append(_SlotBucket(slot_index=i, slot_key=key, start=start, end=end))
        item = dict(slot)
        item.setdefault("clip_start", round(start, 3))
        item.setdefault("clip_end", round(end, 3))
        out_slots.append(item)

    all_words = _collect_words(spoken_pool)
    strategy = "word_midpoint" if all_words else "segment_proportional"

    print(
        f"[subtitle][split] segments={len(spoken_pool)} words={len(all_words)} slots={len(buckets)}"
    )

    assigned_words = 0
    unassigned_words = 0
    if all_words:
        assigned_words, unassigned_words = _assign_words_to_buckets(all_words, buckets, cfg)

    assigned_segment_slots: dict[str, int] = {}
    for seg in _segments_without_words(spoken_pool):
        _assign_segment_exclusive(seg, buckets, assigned_segment_slots, cfg)

    matched_count = 0
    for i, bucket in enumerate(buckets):
        slot = out_slots[i]
        text, derived, confidence = _bucket_to_derived_segment(bucket, spoken_pool)
        linked_ids = derived[0].get("linkedSubtitleSegmentIds") if derived else []

        if text:
            slot["subtitle_text"] = text
            slot["subtitle_segments"] = derived
            slot["subtitle_source"] = "whisper"
            slot["subtitle_quality"] = "ok"
            slot["subtitle_status"] = SLOT_STATUS_MATCHED
            slot["subtitle_status_reason"] = "word_split" if bucket.linked_word_ids else "segment_split"
            slot["subtitle_confidence"] = confidence
            slot["linked_subtitle_segment_ids"] = linked_ids
            slot["linkedSubtitleSegmentIds"] = linked_ids
            slot["linkedWordIds"] = list(bucket.linked_word_ids)
            if effect_profile:
                slot["subtitle_effect_profile"] = effect_profile
            if derived and derived[0].get("renderHints"):
                slot["subtitle_render_hints"] = derived[0]["renderHints"]
            matched_count += 1
            print(
                f"[subtitle][split] slot={bucket.slot_key} start={bucket.start:.2f} "
                f"end={bucket.end:.2f} text={text[:32]}{'...' if len(text) > 32 else ''}"
            )
        else:
            slot["subtitle_text"] = ""
            slot["subtitle_segments"] = []
            slot.setdefault("subtitle_source", "none")
            slot["subtitle_quality"] = "empty"
            slot["subtitle_status"] = SLOT_STATUS_NO_SPEECH
            slot["subtitle_status_reason"] = "no_words_in_slot_window"

    dedupe_fix = _dedupe_adjacent_slots(out_slots, cfg)

    debug = {
        "strategy": "full_asr_then_split_by_slots",
        "splitStrategy": strategy,
        "segmentCount": len(spoken_pool),
        "wordCount": len(all_words),
        "slotCount": len(buckets),
        "assignedWordCount": assigned_words,
        "unassignedWordCount": unassigned_words,
        "matchedSlotCount": matched_count,
        "duplicatedTextFixCount": dedupe_fix,
    }
    _LAST_SPLIT_DEBUG = debug
    print(
        f"[subtitle][split] assigned_words={assigned_words} unassigned_words={unassigned_words} "
        f"matched_slots={matched_count}/{len(buckets)} dedupe_fixes={dedupe_fix}"
    )
    return out_slots, debug
