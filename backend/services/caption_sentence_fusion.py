"""ASR + OCR 融合为 sentenceClips（一句一槽依据）。"""

from __future__ import annotations

import re
from typing import Any

from services.subtitle_config import SubtitleConfig, get_subtitle_config
from services.subtitle_gen import normalize_chinese_subtitle
from services.subtitle_quality import text_similarity

_LAST_FUSION_DEBUG: dict[str, Any] = {}


def get_last_caption_fusion_debug() -> dict[str, Any]:
    return dict(_LAST_FUSION_DEBUG)


def _char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _normalize_ocr_segments(ocr_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, seg in enumerate(ocr_segments or []):
        if not isinstance(seg, dict):
            continue
        text = normalize_chinese_subtitle(str(seg.get("text") or "").strip())
        if not text:
            continue
        start = float(seg.get("start", 0))
        end = float(seg.get("end", start))
        if end <= start:
            end = start + max(0.35, float(seg.get("duration") or 0.35))
        item = dict(seg)
        item.setdefault("id", seg.get("id") or f"ocr_{i + 1:03d}")
        item["start"] = round(start, 3)
        item["end"] = round(end, 3)
        item["duration"] = round(end - start, 3)
        item.setdefault("type", "burned_subtitle")
        item.setdefault("source", "ocr")
        out.append(item)
    return out


def _is_logo_or_ad(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if len(t) <= 2:
        return True
    # 纯英文/数字短水印
    if re.fullmatch(r"[A-Za-z0-9\s\.\-_]{1,12}", t):
        return True
    ad_kw = ("扫码", "关注", "加盟", "热线", "版权", "LOGO", "logo", "www.", "http")
    if any(k in t for k in ad_kw) and _char_count(t) <= 10:
        return True
    return False


def score_ocr_subtitle_track(
    ocr_seg: dict[str, Any],
    asr_segments: list[dict[str, Any]],
    *,
    config: SubtitleConfig | None = None,
) -> tuple[float, dict[str, Any]]:
    """OCR 轨字幕区域可信度评分。"""
    cfg = config or get_subtitle_config()
    text = str(ocr_seg.get("text") or "").strip()
    start = float(ocr_seg.get("start", 0))
    end = float(ocr_seg.get("end", start))
    dur = max(0.05, end - start)

    debug: dict[str, Any] = {"text": text[:48]}
    if _is_logo_or_ad(text):
        debug["rejectReason"] = "logo_or_ad"
        return 0.0, debug

    score = 0.0
    # 时间轴扫描已限定字幕带 → 位置/区域分
    score += 0.28
    debug["regionScore"] = 0.28

    # 横向居中（timeline scan 默认取中间 90% 宽）
    score += 0.12
    debug["centerScore"] = 0.12

    # 持续时间
    if cfg.caption_slot_min_duration <= dur <= cfg.caption_slot_max_duration:
        score += 0.18
        debug["durationScore"] = 0.18
    elif dur >= 0.35:
        score += 0.08
        debug["durationScore"] = 0.08
    else:
        debug["durationScore"] = 0.0

    chars = _char_count(text)
    if chars >= cfg.caption_slot_min_chars:
        score += min(0.12, chars / max(cfg.caption_slot_max_chars, 1) * 0.12)
    debug["charScore"] = round(score, 3)

    # 与 ASR 时间重叠
    best_asr_sim = 0.0
    best_overlap = 0.0
    for asr in asr_segments or []:
        if not isinstance(asr, dict):
            continue
        a_text = str(asr.get("text") or "").strip()
        if not a_text:
            continue
        a0 = float(asr.get("start", 0))
        a1 = float(asr.get("end", a0))
        ov = _overlap(start, end, a0, a1)
        if ov <= 0:
            continue
        ratio = ov / max(dur, 0.1)
        sim = text_similarity(text, a_text)
        best_overlap = max(best_overlap, ratio)
        best_asr_sim = max(best_asr_sim, sim)

    if best_overlap >= 0.25:
        score += 0.15 * min(1.0, best_overlap)
        debug["asrOverlapScore"] = round(0.15 * min(1.0, best_overlap), 3)
    if best_asr_sim >= 0.45:
        score += 0.15 * best_asr_sim
        debug["asrTextSimScore"] = round(0.15 * best_asr_sim, 3)

    debug["asrSimilarity"] = round(best_asr_sim, 3)
    debug["subtitleScore"] = round(score, 3)
    return score, debug


def _blend_time(
    asr_start: float,
    asr_end: float,
    ocr_start: float,
    ocr_end: float,
    *,
    prefer_asr: bool,
) -> tuple[float, float]:
    if prefer_asr:
        # ASR 时间更连续：以 ASR 为主，OCR 微调
        if abs(asr_start - ocr_start) < 0.35 and abs(asr_end - ocr_end) < 0.45:
            start = (asr_start + ocr_start) / 2
            end = (asr_end + ocr_end) / 2
            return round(start, 3), round(max(start + 0.08, end), 3)
        return round(asr_start, 3), round(asr_end, 3)
    start = min(asr_start, ocr_start)
    end = max(asr_end, ocr_end)
    return round(start, 3), round(max(start + 0.08, end), 3)


def _clip_from_parts(
    *,
    clip_id: str,
    start: float,
    end: float,
    text: str,
    display_text: str,
    source: str,
    confidence: float,
    linked_seg_ids: list[str],
    linked_ocr_ids: list[str],
    fusion_debug: dict[str, Any] | None,
    split_reason: str = "caption_sentence",
) -> dict[str, Any]:
    dur = max(0.08, end - start)
    return {
        "id": clip_id,
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(dur, 3),
        "text": text,
        "displayText": display_text or text,
        "source": source,
        "type": "spoken_caption",
        "clipType": "subtitle_clip",
        "confidence": round(confidence, 3),
        "linkedSegmentIds": linked_seg_ids,
        "linkedOcrSegmentIds": linked_ocr_ids,
        "splitReason": split_reason,
        "fusionDebug": fusion_debug or {},
    }


def _score_ocr_pool(
    ocr_segments: list[dict[str, Any]],
    spoken_segments: list[dict[str, Any]],
    *,
    config: SubtitleConfig | None = None,
    asr_clips: list[dict[str, Any]] | None = None,
) -> tuple[list[tuple[dict[str, Any], float, dict[str, Any]]], int]:
    cfg = config or get_subtitle_config()
    ocr_pool = _normalize_ocr_segments(ocr_segments)
    scored: list[tuple[dict[str, Any], float, dict[str, Any]]] = []
    rejected = 0
    threshold = cfg.caption_slot_ocr_subtitle_score_threshold
    if not asr_clips:
        threshold = max(0.45, threshold - 0.12)
    for seg in ocr_pool:
        score, sdebug = score_ocr_subtitle_track(seg, spoken_segments, config=cfg)
        if score < threshold:
            rejected += 1
            continue
        scored.append((seg, score, sdebug))
    return scored, rejected


def _ocr_matches_for_clip(
    clip: dict[str, Any],
    scored_ocr: list[tuple[dict[str, Any], float, dict[str, Any]]],
    *,
    min_ratio: float,
) -> list[tuple[dict[str, Any], float, dict[str, Any], float]]:
    a0 = float(clip.get("start", 0))
    a1 = float(clip.get("end", a0))
    matches: list[tuple[dict[str, Any], float, dict[str, Any], float]] = []
    for ocr, score, sdebug in scored_ocr:
        o0 = float(ocr.get("start", 0))
        o1 = float(ocr.get("end", o0))
        ov = _overlap(a0, a1, o0, o1)
        if ov <= 0.05:
            continue
        ocr_dur = max(0.1, o1 - o0)
        clip_dur = max(0.1, a1 - a0)
        ratio = max(ov / ocr_dur, ov / clip_dur)
        if ratio >= min_ratio:
            matches.append((ocr, score, sdebug, ratio))
    matches.sort(key=lambda x: float(x[0].get("start", 0)))
    return matches


def _words_overlapping_range(
    words: list[dict[str, Any]], t0: float, t1: float
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in words or []:
        if not isinstance(w, dict):
            continue
        ws = float(w.get("start", 0))
        we = float(w.get("end", ws))
        if we > t0 + 0.01 and ws < t1 - 0.01:
            out.append(w)
    return out


def _split_asr_clip_by_ocr(
    clip: dict[str, Any],
    ocr_matches: list[tuple[dict[str, Any], float, dict[str, Any], float]],
    *,
    clip_index: int,
) -> list[dict[str, Any]]:
    """一条 ASR 对应多个画面字幕 → 按 OCR 边界拆分（文本仍来自 ASR 词级时间）。"""
    a_text = str(clip.get("text") or "").strip()
    words = list(clip.get("words") or [])
    linked_seg = list(clip.get("linkedSegmentIds") or [])
    base_conf = float(clip.get("confidence") or 0.5)
    out: list[dict[str, Any]] = []

    for part_i, (ocr, score, sdebug, ratio) in enumerate(ocr_matches):
        o0 = float(ocr.get("start", 0))
        o1 = float(ocr.get("end", o0))
        o_text = str(ocr.get("text") or "").strip()
        part_words = _words_overlapping_range(words, o0, o1)
        if part_words:
            text = normalize_chinese_subtitle("".join(str(w.get("word") or "") for w in part_words))
            start = float(part_words[0].get("start", o0))
            end = float(part_words[-1].get("end", o1))
        else:
            # 无词级时间：按 OCR 窗口截取 ASR 文本比例
            total_chars = max(1, _char_count(a_text))
            clip_dur = max(0.1, float(clip.get("end", 0)) - float(clip.get("start", 0)))
            rel0 = max(0.0, (o0 - float(clip.get("start", 0))) / clip_dur)
            rel1 = min(1.0, (o1 - float(clip.get("start", 0))) / clip_dur)
            c0 = int(rel0 * total_chars)
            c1 = max(c0 + 1, int(rel1 * total_chars))
            text = normalize_chinese_subtitle(a_text[c0:c1]) or a_text
            start, end = o0, o1

        if not text.strip():
            continue
        clip_id = f"cap_{clip_index:03d}_{part_i + 1}"
        out.append(
            _clip_from_parts(
                clip_id=clip_id,
                start=start,
                end=end,
                text=text,
                display_text=str(clip.get("displayText") or text),
                source="asr",
                confidence=base_conf,
                linked_seg_ids=linked_seg,
                linked_ocr_ids=[str(ocr.get("id") or "")],
                fusion_debug={
                    "asrText": a_text,
                    "ocrText": o_text,
                    "similarity": round(text_similarity(text, o_text), 3),
                    "textSource": "asr",
                    "timeSource": "ocr_assisted",
                    "validationAction": "ocr_split",
                    "ocrOverlapRatio": round(ratio, 3),
                    **sdebug,
                },
                split_reason="ocr_boundary_split",
            )
        )
    return out


def _merge_asr_clips(
    clips: list[dict[str, Any]],
    ocr: dict[str, Any],
    *,
    clip_index: int,
    ocr_score: float,
    sdebug: dict[str, Any],
) -> dict[str, Any]:
    texts = [str(c.get("text") or "").strip() for c in clips if str(c.get("text") or "").strip()]
    merged_text = normalize_chinese_subtitle("".join(texts))
    start = min(float(c.get("start", 0)) for c in clips)
    end = max(float(c.get("end", start)) for c in clips)
    linked_seg: list[str] = []
    linked_ocr = [str(ocr.get("id") or "")]
    confs = [float(c.get("confidence") or 0.5) for c in clips]
    o_text = str(ocr.get("text") or "").strip()
    words: list[dict[str, Any]] = []
    for c in clips:
        linked_seg.extend(list(c.get("linkedSegmentIds") or []))
        words.extend(list(c.get("words") or []))
    linked_seg = sorted(set(linked_seg))
    return _clip_from_parts(
        clip_id=f"cap_{clip_index:03d}",
        start=start,
        end=end,
        text=merged_text,
        display_text=merged_text,
        source="asr",
        confidence=round(sum(confs) / max(len(confs), 1), 3),
        linked_seg_ids=linked_seg,
        linked_ocr_ids=linked_ocr,
        fusion_debug={
            "asrText": merged_text,
            "ocrText": o_text,
            "similarity": round(text_similarity(merged_text, o_text), 3),
            "textSource": "asr",
            "timeSource": "ocr_assisted",
            "validationAction": "ocr_merge",
            "mergedAsrClipCount": len(clips),
            **sdebug,
        },
        split_reason="ocr_boundary_merge",
    )


def _finalize_validated_clip(
    clip: dict[str, Any],
    ocr_match: tuple[dict[str, Any], float, dict[str, Any], float] | None,
    *,
    config: SubtitleConfig,
) -> dict[str, Any]:
    """ASR 文本为主；OCR 校验边界/时间/明显错字。"""
    item = dict(clip)
    a_text = str(item.get("text") or "").strip()
    a0 = float(item.get("start", 0))
    a1 = float(item.get("end", a0))
    fusion = dict(item.get("fusionDebug") or {})
    validation: dict[str, Any] = {
        "textSource": "asr",
        "asrText": a_text,
    }
    action = str(fusion.get("validationAction") or "keep")

    if ocr_match:
        ocr, score, sdebug, ratio = ocr_match
        o_text = str(ocr.get("text") or "").strip()
        o0 = float(ocr.get("start", a0))
        o1 = float(ocr.get("end", a1))
        sim = text_similarity(a_text, o_text)
        validation.update(
            {
                "ocrText": o_text,
                "similarity": round(sim, 3),
                "ocrScore": round(score, 3),
                "ocrOverlapRatio": round(ratio, 3),
                **sdebug,
            }
        )
        item["linkedOcrSegmentIds"] = [str(ocr.get("id") or "")]
        # 1:1 校验通过时，用 OCR 硬字幕显示时间微调
        if action in ("keep", "ocr_split", "ocr_merge"):
            start, end = _blend_time(a0, a1, o0, o1, prefer_asr=config.caption_slot_use_asr_time)
            item["start"] = start
            item["end"] = end
            item["duration"] = round(max(0.08, end - start), 3)
            validation["timeSource"] = "ocr_assisted" if not config.caption_slot_use_asr_time else "asr_with_ocr_hint"

        # 高相似度 OCR 辅助修正明显错字（仍标记 asr 主来源）
        if sim >= config.caption_ocr_text_correct_threshold and o_text:
            item["text"] = o_text
            item["displayText"] = str(item.get("displayText") or o_text)
            validation["textCorrectedByOcr"] = True
            validation["textSource"] = "asr_ocr_corrected"
            item["source"] = "asr_ocr_validated"
        elif sim < config.caption_ocr_mismatch_review_threshold:
            validation["validationAction"] = "mismatch"
            validation["needsLocalReAsr"] = True
        else:
            validation["validationAction"] = action or "validated"
            item["source"] = "asr_ocr_validated"
    else:
        validation["validationAction"] = "asr_only"
        item["source"] = "asr"

    item["fusionDebug"] = {**fusion, **validation}
    item["validationDebug"] = validation
    item["validated"] = validation.get("validationAction") != "mismatch" and bool(a_text)
    item["validationStatus"] = "needs_review" if validation.get("validationAction") == "mismatch" else "validated"
    return item


def validate_caption_clips_with_ocr(
    asr_clips: list[dict[str, Any]],
    ocr_segments: list[dict[str, Any]],
    spoken_segments: list[dict[str, Any]] | None = None,
    *,
    config: SubtitleConfig | None = None,
    ocr_raw: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    ASR 主、OCR 校验：
    - OCR 验证 ASR 切句是否对应一个画面字幕片段
    - 1 ASR → 多 OCR：拆分（切句过长）
    - 多 ASR → 1 OCR：合并（切句过碎）
    - 文本不一致：needsReview / 高相似度 OCR 辅助改字
    不生成 OCR-only 字幕轨。
    """
    global _LAST_FUSION_DEBUG
    cfg = config or get_subtitle_config()
    spoken = [s for s in (spoken_segments or []) if isinstance(s, dict)]
    scored_ocr, rejected_ocr = _score_ocr_pool(
        ocr_segments, spoken, config=cfg, asr_clips=asr_clips
    )
    min_ratio = cfg.caption_ocr_overlap_min_ratio

    resegmented: list[dict[str, Any]] = []
    ocr_split_count = 0
    ocr_merge_count = 0
    kept_count = 0

    # --- 阶段 1：按 OCR 边界拆分过长的 ASR 句 ---
    for i, clip in enumerate(asr_clips or []):
        if not isinstance(clip, dict):
            continue
        a_text = str(clip.get("text") or "").strip()
        if not a_text:
            continue
        matches = _ocr_matches_for_clip(clip, scored_ocr, min_ratio=min_ratio)
        if cfg.caption_ocr_validate_split and len(matches) >= 2:
            parts = _split_asr_clip_by_ocr(clip, matches, clip_index=i + 1)
            if len(parts) >= 2:
                resegmented.extend(parts)
                ocr_split_count += 1
                continue
        resegmented.append(dict(clip))

    # --- 阶段 2：同一 OCR 画面字幕对应多条 ASR → 合并 ---
    merged_pass: list[dict[str, Any]] = []
    if cfg.caption_ocr_validate_merge and scored_ocr:
        used: set[int] = set()
        clip_list = resegmented
        for idx, clip in enumerate(clip_list):
            if idx in used:
                continue
            matches = _ocr_matches_for_clip(clip, scored_ocr, min_ratio=min_ratio)
            if not matches:
                merged_pass.append(clip)
                used.add(idx)
                continue
            primary_ocr_id = str(matches[0][0].get("id") or "")
            group = [clip]
            used.add(idx)
            for j in range(idx + 1, len(clip_list)):
                if j in used:
                    continue
                other = clip_list[j]
                other_matches = _ocr_matches_for_clip(other, scored_ocr, min_ratio=min_ratio)
                if not other_matches:
                    continue
                if str(other_matches[0][0].get("id") or "") == primary_ocr_id:
                    group.append(other)
                    used.add(j)
            if len(group) >= 2:
                merged_pass.append(
                    _merge_asr_clips(
                        group,
                        matches[0][0],
                        clip_index=len(merged_pass) + 1,
                        ocr_score=matches[0][1],
                        sdebug=matches[0][2],
                    )
                )
                ocr_merge_count += 1
            else:
                merged_pass.append(clip)
                kept_count += 1
    else:
        merged_pass = resegmented
        kept_count = len(resegmented)

    # --- 阶段 3：逐句 OCR 文本校验 ---
    validated: list[dict[str, Any]] = []
    mismatch_count = 0
    ocr_corrected_count = 0
    for i, clip in enumerate(merged_pass):
        matches = _ocr_matches_for_clip(clip, scored_ocr, min_ratio=min_ratio)
        primary = matches[0] if matches else None
        item = _finalize_validated_clip(clip, primary, config=cfg)
        item["id"] = str(item.get("id") or f"cap_{i + 1:03d}")
        vdebug = item.get("validationDebug") if isinstance(item.get("validationDebug"), dict) else {}
        if vdebug.get("validationAction") == "mismatch":
            mismatch_count += 1
        if vdebug.get("textCorrectedByOcr"):
            ocr_corrected_count += 1
        validated.append(item)

    validated.sort(key=lambda c: float(c.get("start") or 0))

    from services.caption_clip_quality import attach_quality_to_clips

    validated = attach_quality_to_clips(validated, config=cfg)
    for item in validated:
        vdebug = item.get("validationDebug") if isinstance(item.get("validationDebug"), dict) else {}
        quality = dict(item.get("quality") or {})
        if vdebug.get("validationAction") == "mismatch":
            quality["needsReview"] = True
            reasons = list(quality.get("reasons") or [])
            if "asr_ocr_mismatch" not in reasons:
                reasons.append("asr_ocr_mismatch")
            quality["reasons"] = reasons
        elif vdebug.get("validationAction") == "asr_only" and scored_ocr:
            quality["needsReview"] = True
            reasons = list(quality.get("reasons") or [])
            if "no_ocr_match" not in reasons:
                reasons.append("no_ocr_match")
            quality["reasons"] = reasons
        item["quality"] = quality
        item["validationStatus"] = "needs_review" if quality.get("needsReview") else "validated"
        item["validated"] = item["validationStatus"] == "validated"

    debug = {
        "strategy": "asr_primary_ocr_validate",
        "asrClipCount": len(asr_clips or []),
        "validatedCaptionClipCount": len(validated),
        "ocrTrackCount": len(_normalize_ocr_segments(ocr_segments)),
        "ocrRawCount": len(ocr_raw or ocr_segments or []),
        "acceptedOcrCount": len(scored_ocr),
        "rejectedOcrCount": rejected_ocr,
        "ocrSplitCount": ocr_split_count,
        "ocrMergeCount": ocr_merge_count,
        "keptAsrClipCount": kept_count,
        "mismatchCount": mismatch_count,
        "ocrTextCorrectedCount": ocr_corrected_count,
        "ocrOnlyCount": 0,
    }
    _LAST_FUSION_DEBUG = debug
    print(
        f"[caption_validate] asr={len(asr_clips or [])} validated={len(validated)} "
        f"split={ocr_split_count} merge={ocr_merge_count} mismatch={mismatch_count}"
    )
    return validated, debug


def fuse_sentence_clips(
    asr_clips: list[dict[str, Any]],
    ocr_segments: list[dict[str, Any]],
    spoken_segments: list[dict[str, Any]] | None = None,
    *,
    config: SubtitleConfig | None = None,
    ocr_raw: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """兼容旧路径：默认走 ASR 主 + OCR 校验。"""
    cfg = config or get_subtitle_config()
    if cfg.caption_ocr_validate and asr_clips:
        return validate_caption_clips_with_ocr(
            asr_clips,
            ocr_segments,
            spoken_segments,
            config=cfg,
            ocr_raw=ocr_raw,
        )

    global _LAST_FUSION_DEBUG
    spoken = [s for s in (spoken_segments or []) if isinstance(s, dict)]
    ocr_pool = _normalize_ocr_segments(ocr_segments)

    scored_ocr, rejected_ocr = _score_ocr_pool(
        ocr_segments, spoken, config=cfg, asr_clips=asr_clips
    )

    fused: list[dict[str, Any]] = []
    used_ocr_ids: set[str] = set()
    asr_only = 0
    fused_count = 0

    for i, clip in enumerate(asr_clips or []):
        if not isinstance(clip, dict):
            continue
        a_text = str(clip.get("text") or "").strip()
        if not a_text:
            continue
        a0 = float(clip.get("start", 0))
        a1 = float(clip.get("end", a0))
        best_ocr: dict[str, Any] | None = None
        best_sim = 0.0
        best_score = 0.0
        best_sdebug: dict[str, Any] = {}
        for ocr, score, sdebug in scored_ocr:
            o0 = float(ocr.get("start", 0))
            o1 = float(ocr.get("end", o0))
            if _overlap(a0, a1, o0, o1) <= 0.05:
                continue
            sim = text_similarity(a_text, str(ocr.get("text") or ""))
            if sim > best_sim:
                best_sim = sim
                best_ocr = ocr
                best_score = score
                best_sdebug = sdebug

        clip_id = str(clip.get("id") or f"cap_{i + 1:03d}")
        linked_seg = list(clip.get("linkedSegmentIds") or [])
        if (
            best_ocr
            and best_sim >= cfg.caption_slot_ocr_asr_sim_threshold
            and cfg.caption_slot_use_ocr_text
        ):
            o_text = str(best_ocr.get("text") or "").strip()
            o0 = float(best_ocr.get("start", a0))
            o1 = float(best_ocr.get("end", a1))
            start, end = _blend_time(
                a0, a1, o0, o1, prefer_asr=cfg.caption_slot_use_asr_time
            )
            fused.append(
                _clip_from_parts(
                    clip_id=clip_id,
                    start=start,
                    end=end,
                    text=o_text or a_text,
                    display_text=str(clip.get("displayText") or o_text or a_text),
                    source="asr_ocr_fused",
                    confidence=float(clip.get("confidence") or 0.5) * 0.6 + best_score * 0.4,
                    linked_seg_ids=linked_seg,
                    linked_ocr_ids=[str(best_ocr.get("id") or "")],
                    fusion_debug={
                        "asrText": a_text,
                        "ocrText": o_text,
                        "similarity": round(best_sim, 3),
                        "textSource": "ocr",
                        "timeSource": "asr" if cfg.caption_slot_use_asr_time else "blend",
                        **best_sdebug,
                    },
                )
            )
            used_ocr_ids.add(str(best_ocr.get("id") or ""))
            fused_count += 1
        else:
            fused.append(
                _clip_from_parts(
                    clip_id=clip_id,
                    start=a0,
                    end=a1,
                    text=a_text,
                    display_text=str(clip.get("displayText") or a_text),
                    source="asr",
                    confidence=float(clip.get("confidence") or 0.5),
                    linked_seg_ids=linked_seg,
                    linked_ocr_ids=[],
                    fusion_debug={"asrText": a_text, "textSource": "asr", "timeSource": "asr"},
                )
            )
            asr_only += 1

    fused.sort(key=lambda c: float(c.get("start") or 0))

    from services.caption_clip_quality import attach_quality_to_clips

    fused = attach_quality_to_clips(fused, config=cfg)

    debug = {
        "strategy": "caption_slot_fusion",
        "asrClipCount": len(asr_clips or []),
        "ocrTrackCount": len(ocr_pool),
        "ocrRawCount": len(ocr_raw or ocr_segments or []),
        "acceptedOcrCount": len(scored_ocr),
        "rejectedOcrCount": rejected_ocr,
        "fusedSentenceCount": len(fused),
        "asrOnlyCount": asr_only,
        "ocrOnlyCount": 0,
        "fusedCount": fused_count,
    }
    _LAST_FUSION_DEBUG = debug
    return fused, debug


def build_caption_recognition_debug(
    spoken_segments: list[dict[str, Any]],
    asr_clips: list[dict[str, Any]],
    ocr_raw: list[dict[str, Any]],
    ocr_normalized: list[dict[str, Any]],
    sentence_clips: list[dict[str, Any]],
    fusion_debug: dict[str, Any],
    clip_debug: dict[str, Any],
    config: SubtitleConfig | None = None,
) -> dict[str, Any]:
    """识别阶段 debug（含 OCR 样本）。"""
    from services.caption_clip_quality import is_garbled_text

    cfg = config or get_subtitle_config()
    ocr_threshold = cfg.caption_slot_ocr_subtitle_score_threshold
    if not asr_clips:
        ocr_threshold = max(0.45, ocr_threshold - 0.12)

    ocr_samples: list[dict[str, Any]] = []
    accepted = 0
    for i, seg in enumerate(ocr_raw or []):
        if not isinstance(seg, dict):
            continue
        raw_text = str(seg.get("text") or "")
        norm = normalize_chinese_subtitle(raw_text)
        score, sdebug = score_ocr_subtitle_track(
            {**seg, "text": norm}, spoken_segments, config=cfg
        )
        reject = sdebug.get("rejectReason")
        if is_garbled_text(norm):
            reject = reject or "garbled_text"
            score = min(score, 0.2)
        if score < ocr_threshold:
            reject = reject or "low_score"
        else:
            accepted += 1
        ocr_samples.append(
            {
                "text": norm[:80],
                "rawText": raw_text[:80],
                "start": float(seg.get("start", 0)),
                "end": float(seg.get("end", seg.get("start", 0))),
                "box": seg.get("box") or seg.get("bbox") or [],
                "subtitleScore": round(score, 3),
                "rejectReason": reject or (None if score >= ocr_threshold else "low_score"),
            }
        )

    needs_review = sum(
        1
        for c in sentence_clips
        if isinstance(c.get("quality"), dict) and c["quality"].get("needsReview")
    )
    validated_count = sum(
        1 for c in sentence_clips if isinstance(c, dict) and c.get("validationStatus") == "validated"
    )

    return {
        "strategy": fusion_debug.get("strategy", "caption_recognition"),
        "asrSegmentCount": len(spoken_segments or []),
        "asrClipCount": len(asr_clips or []),
        "rawAsrClipCount": len(asr_clips or []),
        "validatedCaptionClipCount": len(sentence_clips or []),
        "validatedClipCount": validated_count,
        "ocrRawCount": len(ocr_raw or []),
        "ocrTrackCount": len(ocr_normalized or []),
        "ocrSubtitleCandidateCount": accepted,
        "ocrRejectedCount": fusion_debug.get("rejectedOcrCount", max(0, len(ocr_raw or []) - accepted)),
        "ocrSplitCount": fusion_debug.get("ocrSplitCount", 0),
        "ocrMergeCount": fusion_debug.get("ocrMergeCount", 0),
        "mismatchCount": fusion_debug.get("mismatchCount", 0),
        "ocrTextCorrectedCount": fusion_debug.get("ocrTextCorrectedCount", 0),
        "fusedCount": fusion_debug.get("fusedCount", 0),
        "asrOnlyCount": fusion_debug.get("asrOnlyCount", 0),
        "ocrOnlyCount": fusion_debug.get("ocrOnlyCount", 0),
        "sentenceClipCount": len(sentence_clips or []),
        "needsReviewCount": needs_review,
        "ocrSamples": ocr_samples[:40],
        "subtitleClipDebug": clip_debug,
        "fusionDebug": fusion_debug,
        "validationDebug": fusion_debug,
    }
