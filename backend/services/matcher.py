from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class MatchWeights:
    """匹配算法权重配置"""

    tags_weight: float = 0.35
    visual_weight: float = 0.35
    duration_tolerance: float = 2.0

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "MatchWeights":
        if not data:
            return cls()
        tags = float(data.get("tags_weight", 0.35))
        visual = float(data.get("visual_weight", 0.35))
        tags, visual = cls._normalize_pair(tags, visual)
        return cls(
            tags_weight=tags,
            visual_weight=visual,
            duration_tolerance=float(data.get("duration_tolerance", 2.0)),
        )

    @staticmethod
    def _normalize_pair(tags: float, visual: float) -> tuple[float, float]:
        tags = max(0.0, min(1.0, tags))
        visual = max(0.0, min(1.0, visual))
        total = tags + visual
        if total > 1.0:
            tags /= total
            visual /= total
        return tags, visual

    def duration_weight(self) -> float:
        return max(0.0, 1.0 - self.tags_weight - self.visual_weight)


def _effective_tags(item: dict) -> list:
    tags = list(item.get("tags") or item.get("scene_tags") or [])
    for t in item.get("ai_tags") or []:
        if t and t not in tags:
            tags.append(t)
    return tags


def calculate_tag_score(slot_tags: list, seg_tags: list) -> float:
    if not slot_tags or not seg_tags:
        return 0.0
    slot_set = set(slot_tags)
    seg_set = set(seg_tags)
    overlap = slot_set & seg_set
    return len(overlap) / len(slot_set)


def calculate_duration_score(
    slot_dur: float, seg_dur: float, tolerance: float = 2.0, strict: bool = False
) -> float:
    if seg_dur < slot_dur:
        return 0.0
    ratio = seg_dur / slot_dur
    tolerance = max(1.0, tolerance)
    if strict and ratio > tolerance:
        return 0.0
    if ratio <= tolerance:
        return 1.0
    if ratio <= tolerance * 2:
        return 0.7
    return 0.3


def calculate_visual_score(slot: dict, seg: dict, prefer_quality: bool = True) -> float:
    shot_score = (
        1.0
        if slot.get("shot_type") and slot.get("shot_type") == seg.get("shot_type")
        else 0.3
    )
    quality = float(seg.get("quality_score", 0.5))
    if prefer_quality:
        quality = min(1.0, quality * 1.15)
    return shot_score * 0.6 + quality * 0.4


def _slot_id(slot: dict, index: int):
    return slot.get("slot_id", slot.get("id", index + 1))


def match_slots(
    slots: list,
    all_segments: list,
    weights: Optional[MatchWeights] = None,
    settings: Optional[Dict[str, Any]] = None,
) -> list:
    cfg = weights or MatchWeights()
    opts = settings or {}
    strict_duration = bool(opts.get("strict_duration", False))
    prefer_quality = bool(opts.get("prefer_quality", True))
    dedup_global = opts.get("dedup_policy", "global") != "none"

    dur_weight = cfg.duration_weight()
    total_weight = cfg.tags_weight + cfg.visual_weight + dur_weight
    if total_weight <= 0:
        total_weight = 1.0

    results = []
    used = set()

    for index, slot in enumerate(slots):
        best = None
        best_score = -1
        best_detail: Optional[dict] = None
        slot_duration = float(slot.get("duration", slot.get("slot_duration", 0)) or 0)
        current_slot_id = _slot_id(slot, index)

        for seg in all_segments:
            seg_key = f"{seg.get('asset_id')}_{seg.get('segment_id')}"

            if dedup_global and seg_key in used:
                continue

            dur_score = calculate_duration_score(
                slot_duration,
                float(seg.get("duration", 0) or 0),
                cfg.duration_tolerance,
                strict=strict_duration,
            )
            if dur_score == 0:
                continue

            tag_score = calculate_tag_score(
                _effective_tags(slot),
                _effective_tags(seg),
            )
            visual_score = calculate_visual_score(slot, seg, prefer_quality=prefer_quality)

            total = (
                tag_score * cfg.tags_weight
                + visual_score * cfg.visual_weight
                + dur_score * dur_weight
            ) / total_weight

            if opts.get("use_vector_match", True):
                try:
                    from services.vector_index import score_with_vector

                    vw = float(opts.get("vector_weight", 0.25))
                    total = score_with_vector(slot, seg, total, vw)
                except Exception:
                    pass

            if total > best_score:
                best_score = total
                best = seg
                best_detail = {
                    "tag": tag_score,
                    "visual": visual_score,
                    "dur": dur_score,
                    "total": total,
                    "seg_tags": (_effective_tags(seg))[:4],
                    "slot_desc": slot.get("ai_description", ""),
                    "seg_desc": seg.get("ai_description", ""),
                    "shot_type": seg.get("shot_type", ""),
                }

        if best:
            seg_key = f"{best.get('asset_id')}_{best.get('segment_id')}"
            if dedup_global:
                used.add(seg_key)

            seg_video = (best.get("segment_file_path") or "").strip()
            use_seg_file = bool(seg_video)
            clip_start = 0.0 if use_seg_file else float(best.get("start", 0))
            clip_src = seg_video or best.get("file_path", "")

            results.append({
                "slot_id": current_slot_id,
                "slot_start": slot.get("start", slot.get("slot_start", 0)),
                "slot_end": slot.get(
                    "end",
                    slot.get("slot_end", slot.get("slot_start", 0) + slot_duration),
                ),
                "slot_duration": slot_duration,
                "match_score": round(best_score, 3),
                "match_reason": _format_match_reason(best_detail),
                "asset_id": best.get("asset_id"),
                "segment_id": best.get("segment_id"),
                "asset_filename": best.get("filename", ""),
                "asset_file_path": clip_src,
                "clip_start": clip_start,
                "clip_end": float(best.get("end", clip_start + slot_duration)),
                "clip_duration": slot_duration,
                "thumbnail": best.get("thumbnail", ""),
                "tags": best.get("scene_tags", []),
                "segment_file_path": seg_video,
            })
        else:
            results.append({
                "slot_id": current_slot_id,
                "slot_duration": slot_duration,
                "match_score": 0,
                "asset_id": None,
                "error": "没有找到合适的素材",
            })

    return results


def _format_match_reason(detail: Optional[dict]) -> str:
    if not detail:
        return "自动匹配"
    parts = [
        f"标签 {detail['tag']:.0%}",
        f"景别 {detail['visual']:.0%}",
        f"时长 {detail['dur']:.0%}",
    ]
    tags = detail.get("seg_tags") or []
    if tags:
        parts.append(f"标签 {' · '.join(str(t) for t in tags[:3])}")
    slot_desc = detail.get("slot_desc") or ""
    seg_desc = detail.get("seg_desc") or ""
    if slot_desc and seg_desc:
        parts.append(f"画面 {slot_desc}→{seg_desc}")
    elif seg_desc:
        parts.append(f"画面 {seg_desc}")
    shot = detail.get("shot_type")
    if shot:
        parts.append(f"镜头 {shot}")
    return " · ".join(parts)
