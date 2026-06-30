"""剪映式字幕轨：从 ASR spoken_caption 主轨切句生成独立 subtitleClips（不依赖画面 slot）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from services.subtitle_config import SubtitleConfig, get_subtitle_config

STRONG_PUNCT = "。！？"
WEAK_PUNCT = "；，、"
ALL_PUNCT = STRONG_PUNCT + WEAK_PUNCT

SEMANTIC_STARTERS = (
    "首先",
    "然后",
    "接下来",
    "但是",
    "所以",
    "因为",
    "如果",
    "另外",
    "最后",
    "重点是",
    "千万别",
    "一定要",
    "第二",
    "第三",
    "第四",
    "第五",
    "第一",
    "接下来",
)

_LAST_CLIP_DEBUG: dict[str, Any] = {}


def get_last_subtitle_clip_debug() -> dict[str, Any]:
    return dict(_LAST_CLIP_DEBUG)


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = str(text).strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    return text.strip()


def _char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _is_spoken_segment(seg: dict[str, Any]) -> bool:
    seg_type = str(seg.get("type") or "spoken_caption")
    return seg_type not in ("screen_text", "burned_subtitle_candidate", "uncertain", "slot_derived_caption")


@dataclass
class _WordUnit:
    token: str
    start: float
    end: float
    segment_id: str
    word_index: int
    confidence: float | None = None


@dataclass
class _ClipDraft:
    words: list[_WordUnit] = field(default_factory=list)
    split_reason: str = "asr_segment"

    @property
    def text(self) -> str:
        return _normalize("".join(w.token for w in self.words))

    @property
    def start(self) -> float:
        return self.words[0].start if self.words else 0.0

    @property
    def end(self) -> float:
        return self.words[-1].end if self.words else 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def char_count(self) -> int:
        return _char_count(self.text)


def _ends_with_punct(token: str) -> tuple[bool, str | None]:
    t = _normalize(token)
    if not t:
        return False, None
    for ch in reversed(t):
        if ch in STRONG_PUNCT:
            return True, "punctuation"
        if ch in WEAK_PUNCT:
            return True, "punctuation"
    return False, None


def _starts_semantic(token: str) -> bool:
    t = _normalize(token)
    return any(t.startswith(s) for s in SEMANTIC_STARTERS)


def _collect_words(spoken_segments: list[dict[str, Any]], use_words: bool, cfg: SubtitleConfig) -> list[_WordUnit]:
    units: list[_WordUnit] = []
    for seg in spoken_segments:
        if not isinstance(seg, dict) or not _is_spoken_segment(seg):
            continue
        seg_id = str(seg.get("id") or "")
        conf = float(seg["confidence"]) if seg.get("confidence") is not None else None
        words = seg.get("words")
        ss = float(seg.get("start", 0))
        se = float(seg.get("end", ss))
        if use_words and isinstance(words, list) and words:
            for wi, w in enumerate(words):
                if not isinstance(w, dict):
                    continue
                token = _normalize(str(w.get("word") or ""))
                if not token:
                    continue
                ws = float(w.get("start", ss))
                we = float(w.get("end", ws))
                units.append(
                    _WordUnit(
                        token=token,
                        start=ws,
                        end=max(ws + 0.02, we),
                        segment_id=seg_id,
                        word_index=wi,
                        confidence=conf,
                    )
                )
        else:
            text = _normalize(str(seg.get("text") or ""))
            if not text:
                continue
            chars = list(text)
            n = max(1, len(chars))
            dur = max(0.05, se - ss)
            for ci, ch in enumerate(chars):
                t0 = ss + dur * ci / n
                t1 = ss + dur * (ci + 1) / n
                units.append(
                    _WordUnit(
                        token=ch,
                        start=t0,
                        end=max(t0 + 0.02, t1),
                        segment_id=seg_id,
                        word_index=ci,
                        confidence=conf,
                    )
                )
    units.sort(key=lambda w: (w.start, w.word_index))
    return units


def _gap_after(words: list[_WordUnit], idx: int) -> float:
    if idx >= len(words) - 1:
        return 0.0
    return max(0.0, words[idx + 1].start - words[idx].end)


def _score_cut_point(words: list[_WordUnit], cut_after: int, cfg: SubtitleConfig) -> float:
    """Higher = better place to cut after word index cut_after."""
    if cut_after < 0 or cut_after >= len(words):
        return -1.0
    w = words[cut_after]
    score = 0.0
    has_punct, _ = _ends_with_punct(w.token)
    if has_punct:
        score += 10.0
        if any(ch in STRONG_PUNCT for ch in w.token):
            score += 5.0
    gap = _gap_after(words, cut_after)
    if gap >= cfg.clip_pause_threshold_sec:
        score += 6.0 + min(gap, 1.0)
    if cut_after + 1 < len(words) and _starts_semantic(words[cut_after + 1].token):
        score += 4.0
    draft = _ClipDraft(words=words[: cut_after + 1])
    dur_diff = abs(draft.duration - cfg.clip_target_duration)
    score += max(0.0, 3.0 - dur_diff)
    return score


def _find_forced_cut(words: list[_WordUnit], start_idx: int, cfg: SubtitleConfig) -> int:
    """Return word index to cut after (inclusive), within words[start_idx:]."""
    if start_idx >= len(words):
        return start_idx
    best_idx = start_idx
    best_score = -1.0
    accum_start = words[start_idx].start
    for i in range(start_idx, len(words)):
        dur = words[i].end - accum_start
        chars = _char_count("".join(w.token for w in words[start_idx : i + 1]))
        if dur > cfg.clip_max_duration or chars > cfg.clip_max_chars:
            break
        sc = _score_cut_point(words, i, cfg)
        if sc > best_score:
            best_score = sc
            best_idx = i
        if dur >= cfg.clip_target_duration * 0.85 and sc >= 4.0:
            return i
    if best_idx == start_idx and start_idx + 1 < len(words):
        return start_idx
    return best_idx


def _split_words_into_drafts(words: list[_WordUnit], cfg: SubtitleConfig) -> tuple[list[_ClipDraft], dict[str, int]]:
    stats = {
        "punctuationSplitCount": 0,
        "pauseSplitCount": 0,
        "semanticSplitCount": 0,
        "splitLongCount": 0,
    }
    if not words:
        return [], stats

    drafts: list[_ClipDraft] = []
    i = 0
    while i < len(words):
        chunk_start = i
        cut_reason = "asr_segment"
        j = i
        while j < len(words):
            w = words[j]
            dur = w.end - words[chunk_start].start
            chars = _char_count("".join(x.token for x in words[chunk_start : j + 1]))
            has_punct, _ = _ends_with_punct(w.token)
            gap = _gap_after(words, j)

            force_long = dur > cfg.clip_max_duration or chars > cfg.clip_max_chars
            if force_long and j > chunk_start:
                cut_at = _find_forced_cut(words, chunk_start, cfg)
                drafts.append(_ClipDraft(words=words[chunk_start : cut_at + 1], split_reason="max_duration"))
                stats["splitLongCount"] += 1
                i = cut_at + 1
                break

            should_cut = False
            if has_punct:
                should_cut = True
                cut_reason = "punctuation"
                stats["punctuationSplitCount"] += 1
            elif gap >= cfg.clip_pause_threshold_sec and j > chunk_start:
                should_cut = True
                cut_reason = "pause"
                stats["pauseSplitCount"] += 1
            elif j + 1 < len(words) and _starts_semantic(words[j + 1].token) and j > chunk_start:
                should_cut = True
                cut_reason = "semantic"
                stats["semanticSplitCount"] += 1
            elif dur >= cfg.clip_target_duration * 1.6 and j > chunk_start:
                should_cut = True
                cut_reason = "max_duration"
                stats["splitLongCount"] += 1

            if should_cut or j == len(words) - 1:
                drafts.append(_ClipDraft(words=words[chunk_start : j + 1], split_reason=cut_reason))
                i = j + 1
                break
            j += 1
        else:
            i = j + 1

    return drafts, stats


def _merge_short_clips(drafts: list[_ClipDraft], cfg: SubtitleConfig) -> tuple[list[_ClipDraft], int]:
    if len(drafts) <= 1:
        return drafts, 0
    merged_count = 0
    out: list[_ClipDraft] = []
    i = 0
    while i < len(drafts):
        cur = drafts[i]
        if (
            (cur.duration < cfg.clip_min_duration or cur.char_count < cfg.clip_min_chars)
            and i + 1 < len(drafts)
        ):
            nxt = drafts[i + 1]
            gap = nxt.start - cur.end
            combined_dur = nxt.end - cur.start
            combined_chars = _char_count(cur.text + nxt.text)
            cur_strong = any(ch in STRONG_PUNCT for ch in cur.text)
            if (
                gap <= cfg.clip_merge_gap_sec
                and combined_dur <= cfg.clip_max_duration
                and combined_chars <= cfg.clip_max_chars
                and not (cur_strong and cur.char_count >= cfg.clip_min_chars)
            ):
                out.append(
                    _ClipDraft(
                        words=cur.words + nxt.words,
                        split_reason="merged_short",
                    )
                )
                merged_count += 1
                i += 2
                continue
        out.append(cur)
        i += 1
    return out, merged_count


def _clip_dict_from_merged(a: dict[str, Any], b: dict[str, Any], reason: str) -> dict[str, Any]:
    start = min(float(a.get("start", 0)), float(b.get("start", 0)))
    end = max(float(a.get("end", start)), float(b.get("end", start)))
    text = _normalize(str(a.get("text") or "") + str(b.get("text") or ""))
    confs = [float(x) for x in (a.get("confidence"), b.get("confidence")) if x is not None]
    merged = dict(a)
    merged.update(
        {
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "text": text,
            "displayText": text,
            "confidence": round(min(confs), 3) if confs else 0.5,
            "splitReason": reason,
            "linkedSegmentIds": list(
                dict.fromkeys(
                    list(a.get("linkedSegmentIds") or []) + list(b.get("linkedSegmentIds") or [])
                )
            ),
        }
    )
    return merged


def _postprocess_fragment_clips(
    clips: list[dict[str, Any]],
    cfg: SubtitleConfig,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """合并/丢弃过短碎片（年的、次璞等）。"""
    stats = {
        "mergedTooShort": 0,
        "mergedFragment": 0,
        "droppedTooShortLowConfidence": 0,
    }
    out = [dict(c) for c in clips if isinstance(c, dict) and str(c.get("text") or "").strip()]
    if len(out) <= 1:
        return out, stats

    min_dur = 0.6
    min_chars = 3

    for _ in range(max(3, len(out))):
        merged_pass = False
        i = 0
        nxt: list[dict[str, Any]] = []
        while i < len(out):
            cur = out[i]
            dur = float(cur.get("duration") or (float(cur.get("end", 0)) - float(cur.get("start", 0))))
            chars = _char_count(str(cur.get("text") or ""))
            conf = float(cur.get("confidence") or 0.5)
            is_fragment = dur < min_dur or chars < min_chars

            if not is_fragment:
                nxt.append(cur)
                i += 1
                continue

            if dur >= 0.55 and chars >= 2 and conf >= 0.75 and str(cur.get("text") or "") in (
                "嗯",
                "啊",
                "哦",
                "呢",
                "吧",
            ):
                nxt.append(cur)
                i += 1
                continue

            prev = nxt[-1] if nxt else None
            nxt_item = out[i + 1] if i + 1 < len(out) else None
            gap_prev = float(cur.get("start", 0)) - float(prev.get("end", 0)) if prev else 999.0
            gap_next = float(nxt_item.get("start", 0)) - float(cur.get("end", 0)) if nxt_item else 999.0

            def _can_merge(left: dict[str, Any], right: dict[str, Any], gap: float) -> bool:
                if gap > cfg.clip_merge_gap_sec:
                    return False
                combined = _clip_dict_from_merged(left, right, "merged_fragment")
                comb_dur = float(combined.get("duration") or 0)
                comb_chars = _char_count(str(combined.get("text") or ""))
                return comb_dur <= cfg.clip_max_duration and comb_chars <= cfg.clip_max_chars

            pick: str | None = None
            if prev and nxt_item:
                if _can_merge(prev, cur, gap_prev) and _can_merge(cur, nxt_item, gap_next):
                    pick = "prev" if gap_prev <= gap_next else "next"
                elif _can_merge(prev, cur, gap_prev):
                    pick = "prev"
                elif _can_merge(cur, nxt_item, gap_next):
                    pick = "next"
            elif prev and _can_merge(prev, cur, gap_prev):
                pick = "prev"
            elif nxt_item and _can_merge(cur, nxt_item, gap_next):
                pick = "next"

            if pick == "prev" and prev is not None:
                nxt[-1] = _clip_dict_from_merged(
                    prev, cur, "merged_too_short" if dur < min_dur else "merged_fragment"
                )
                stats["mergedTooShort" if dur < min_dur else "mergedFragment"] += 1
                merged_pass = True
                i += 1
                continue
            if pick == "next" and nxt_item is not None:
                nxt.append(_clip_dict_from_merged(cur, nxt_item, "merged_fragment"))
                stats["mergedFragment"] += 1
                merged_pass = True
                i += 2
                continue

            if conf < 0.42 and (dur < 0.45 or chars <= 2):
                stats["droppedTooShortLowConfidence"] += 1
                i += 1
                continue

            nxt.append(cur)
            i += 1

        out = nxt
        if not merged_pass:
            break

    for idx, clip in enumerate(out, start=1):
        clip["id"] = f"cap_{idx:03d}"
    return out, stats


def _compute_line_breaks(text: str, cfg: SubtitleConfig) -> tuple[str, list[int]]:
    t = _normalize(text)
    if not t:
        return "", []
    max_line = cfg.clip_max_chars_per_line
    max_lines = cfg.clip_max_lines
    if _char_count(t) <= max_line or max_lines <= 1:
        return t, []

    # Prefer break at punctuation near middle
    mid = len(t) // 2
    best = -1
    for idx, ch in enumerate(t):
        if ch in ALL_PUNCT and abs(idx - mid) <= max_line:
            best = idx + 1
    if best <= 0 or best >= len(t):
        best = min(max_line, len(t))
    display = t[:best].rstrip("，、；") + "\n" + t[best:].lstrip("，、；")
    return display, [best]


def _draft_to_clip(draft: _ClipDraft, index: int, seg_map: dict[str, dict]) -> dict[str, Any]:
    text = draft.text
    if not text:
        return {}
    linked_seg_ids = sorted({w.segment_id for w in draft.words if w.segment_id})
    linked_word_ids = [f"{w.segment_id}:{w.word_index}" for w in draft.words]
    confs = [w.confidence for w in draft.words if w.confidence is not None]
    confidence = round(min(confs), 3) if confs else 0.5

    profile_id = None
    render_hints: dict[str, Any] = {}
    for sid in linked_seg_ids:
        seg = seg_map.get(sid) or {}
        if profile_id is None and seg.get("effectProfileId"):
            profile_id = seg.get("effectProfileId")
        if seg.get("renderHints"):
            render_hints = dict(seg.get("renderHints") or {})

    display_text, line_breaks = _compute_line_breaks(text, get_subtitle_config())
    clip_words = [
        {
            "word": w.token,
            "start": round(w.start, 3),
            "end": round(w.end, 3),
        }
        for w in draft.words
    ]

    return {
        "id": f"cap_{index:03d}",
        "start": round(draft.start, 3),
        "end": round(draft.end, 3),
        "duration": round(draft.duration, 3),
        "text": text,
        "displayText": display_text or text,
        "source": "asr",
        "type": "spoken_caption",
        "clipType": "subtitle_clip",
        "confidence": confidence,
        "linkedSegmentIds": linked_seg_ids,
        "linkedWordIds": linked_word_ids,
        "words": clip_words,
        "lineBreaks": line_breaks,
        "effectProfileId": profile_id,
        "renderHints": render_hints or {
            "emphasis": False,
            "keywords": [],
            "animationIntensity": "normal",
        },
        "splitReason": draft.split_reason,
    }


def build_subtitle_clips_from_asr(
    spoken_segments: list[dict[str, Any]],
    *,
    config: SubtitleConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    从 spoken_caption 主轨生成剪映式 subtitleClips。
    不依赖 visual slots；每个 word 只属于一个 clip。
    """
    global _LAST_CLIP_DEBUG
    cfg = config or get_subtitle_config()
    pool = [s for s in (spoken_segments or []) if isinstance(s, dict) and _is_spoken_segment(s)]
    use_words = cfg.clip_use_word_timestamps
    words = _collect_words(pool, use_words, cfg)
    word_count = len(words)

    print(f"[subtitle_clip] build start segments={len(pool)} words={word_count}")

    if not pool:
        debug = {
            "strategy": "capcut_like_sentence_split",
            "rawSegmentCount": 0,
            "wordCount": 0,
            "subtitleClipCount": 0,
            "splitLongCount": 0,
            "mergedShortCount": 0,
            "pauseSplitCount": 0,
            "punctuationSplitCount": 0,
        }
        _LAST_CLIP_DEBUG = debug
        return [], debug

    if not words:
        # fallback: one clip per segment
        clips = []
        seg_map = {str(s.get("id") or ""): s for s in pool}
        for i, seg in enumerate(pool):
            text = _normalize(str(seg.get("text") or ""))
            if not text:
                continue
            ss = float(seg.get("start", 0))
            se = float(seg.get("end", ss))
            draft = _ClipDraft(
                words=[
                    _WordUnit(
                        token=text,
                        start=ss,
                        end=max(ss + 0.05, se),
                        segment_id=str(seg.get("id") or ""),
                        word_index=0,
                        confidence=float(seg.get("confidence")) if seg.get("confidence") is not None else None,
                    )
                ],
                split_reason="asr_segment",
            )
            clip = _draft_to_clip(draft, i + 1, seg_map)
            if clip:
                clips.append(clip)
        debug = {
            "strategy": "capcut_like_sentence_split",
            "rawSegmentCount": len(pool),
            "wordCount": 0,
            "subtitleClipCount": len(clips),
            "splitLongCount": 0,
            "mergedShortCount": 0,
            "pauseSplitCount": 0,
            "punctuationSplitCount": 0,
        }
        _LAST_CLIP_DEBUG = debug
        return clips, debug

    drafts, split_stats = _split_words_into_drafts(words, cfg)
    drafts, merged_short = _merge_short_clips(drafts, cfg)

    seg_map = {str(s.get("id") or ""): s for s in pool}
    clips: list[dict[str, Any]] = []
    for i, draft in enumerate(drafts, start=1):
        if not draft.text:
            continue
        clip = _draft_to_clip(draft, i, seg_map)
        if clip:
            clips.append(clip)
            print(
                f"[subtitle_clip] clip start={clip['start']:.2f} end={clip['end']:.2f} "
                f"text={clip['text'][:24]}{'...' if len(clip['text']) > 24 else ''} "
                f"reason={clip.get('splitReason')}"
            )

    clips, frag_stats = _postprocess_fragment_clips(clips, cfg)
    from services.caption_clip_quality import attach_quality_to_clips

    clips = attach_quality_to_clips(clips, config=cfg)

    debug = {
        "strategy": "capcut_like_sentence_split",
        "rawSegmentCount": len(pool),
        "wordCount": word_count,
        "subtitleClipCount": len(clips),
        "splitLongCount": split_stats.get("splitLongCount", 0),
        "mergedShortCount": merged_short + frag_stats.get("mergedTooShort", 0),
        "pauseSplitCount": split_stats.get("pauseSplitCount", 0),
        "punctuationSplitCount": split_stats.get("punctuationSplitCount", 0),
        "semanticSplitCount": split_stats.get("semanticSplitCount", 0),
        "mergedFragmentCount": frag_stats.get("mergedFragment", 0),
        "droppedTooShortLowConfidence": frag_stats.get("droppedTooShortLowConfidence", 0),
    }
    _LAST_CLIP_DEBUG = debug
    print(
        f"[subtitle_clip] split punctuation count={debug['punctuationSplitCount']} "
        f"pause count={debug['pauseSplitCount']} long count={debug['splitLongCount']} "
        f"merged short count={merged_short} output clips={len(clips)}"
    )
    return clips, debug


def postprocess_caption_clips_for_ai_split(
    clips: list[dict[str, Any]],
    config: SubtitleConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """AI 分割画面前：合并/丢弃过短 CaptionClip 碎片。"""
    cfg = config or get_subtitle_config()
    return _postprocess_fragment_clips(clips, cfg)


def persist_template_subtitle_clips(
    template,
    spoken_segments: list[dict[str, Any]] | None = None,
    *,
    db=None,
    config: SubtitleConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """从 segments 构建并写入 template.subtitle_clips_json。"""
    from sqlalchemy.orm.attributes import flag_modified

    pool = spoken_segments
    if pool is None:
        pool = getattr(template, "segments_json", None) or []
    clips, debug = build_subtitle_clips_from_asr(pool, config=config)
    template.subtitle_clips_json = clips
    template._last_subtitle_clip_debug = debug
    flag_modified(template, "subtitle_clips_json")
    if db is not None:
        db.commit()
        db.refresh(template)
    return clips, debug
