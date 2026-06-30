"""槽位字幕状态：来源、质量、失败原因（PM 方案用户可见层）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from services.subtitle_quality import (
    count_duplicate_peers,
    is_subtitle_quality_acceptable,
    subtitle_text_from_segments,
)

SOURCE_LABELS: dict[str, str] = {
    "none": "无",
    "whisper": "人声（ASR）",
    "whisper_low_quality": "人声（低质量）",
    "visual": "画面",
    "visual_primary": "画面（主）",
    "visual_audio_fallback": "画面（人声不可用）",
    "visual_fallback": "画面（回退）",
    "visual_timeline": "画面（时间轴）",
    "hybrid_visual": "融合（偏画面）",
    "hybrid_whisper": "融合（偏人声）",
}

LOW_QUALITY_SOURCES = frozenset({"whisper_low_quality", "none"})


@dataclass(frozen=True)
class SlotSubtitleStatus:
    slot_id: str | int | None
    quality: str  # ok | low | empty
    source: str
    source_label: str
    reason: str
    subtitle_text: str
    duplicate: bool = False


def source_label(source: str | None) -> str:
    key = str(source or "none").strip() or "none"
    return SOURCE_LABELS.get(key, key)


def failure_reason_for_empty(
    source: str | None,
    *,
    has_video: bool = True,
    has_audio_hint: bool = True,
) -> str:
    src = str(source or "none")
    if src in ("visual", "visual_primary", "hybrid_visual", "visual_fallback"):
        return "画面未检测到字幕，请手填或精识别"
    if not has_audio_hint:
        return "模板无人声轨道，请手填字幕"
    if not has_video:
        return "模板视频不可用"
    return "未识别到文字（可尝试精识别或手填）"


def classify_slot_subtitle(
    slot: dict[str, Any],
    *,
    source: str | None = None,
    peer_texts: Iterable[str] | None = None,
) -> SlotSubtitleStatus:
    text = str(slot.get("subtitle_text") or "").strip()
    if not text:
        segments = slot.get("subtitle_segments") or []
        text = subtitle_text_from_segments(segments)

    src = str(source or slot.get("subtitle_source") or "none")
    slot_id = slot.get("slot_id") or slot.get("id")
    start = float(slot.get("clip_start") or slot.get("start") or 0)
    end = float(
        slot.get("clip_end")
        or slot.get("end")
        or start + float(slot.get("duration") or slot.get("slot_duration") or 0.1)
    )
    duration = max(0.1, end - start)
    peers = list(peer_texts or [])
    dup = count_duplicate_peers(text, peers) >= 1 if text else False

    if not text:
        return SlotSubtitleStatus(
            slot_id=slot_id,
            quality="empty",
            source=src,
            source_label=source_label(src),
            reason=failure_reason_for_empty(src),
            subtitle_text="",
            duplicate=False,
        )

    if src in LOW_QUALITY_SOURCES or src == "whisper_low_quality":
        return SlotSubtitleStatus(
            slot_id=slot_id,
            quality="low",
            source=src,
            source_label=source_label(src),
            reason="人声质量过低，建议精识别或手改",
            subtitle_text=text,
            duplicate=dup,
        )

    if dup:
        return SlotSubtitleStatus(
            slot_id=slot_id,
            quality="low",
            source=src,
            source_label=source_label(src),
            reason="与其他槽位字幕重复，请核对切分或手改",
            subtitle_text=text,
            duplicate=True,
        )

    ok, reason = is_subtitle_quality_acceptable(text, duration)
    if not ok:
        return SlotSubtitleStatus(
            slot_id=slot_id,
            quality="low",
            source=src,
            source_label=source_label(src),
            reason=_quality_reason_zh(reason),
            subtitle_text=text,
            duplicate=False,
        )

    return SlotSubtitleStatus(
        slot_id=slot_id,
        quality="ok",
        source=src,
        source_label=source_label(src),
        reason="",
        subtitle_text=text,
        duplicate=False,
    )


def _quality_reason_zh(code: str) -> str:
    mapping = {
        "too_long_for_slot": "字幕相对槽位过长，可能切分不准",
        "speech_rate_implausible": "语速异常，可能切分不准",
        "paragraph_in_short_slot": "短槽位出现长段文字",
        "duplicate_across_slots": "与其他槽位重复",
        "low_chinese_ratio": "非中文占比过高",
        "garbled": "识别结果疑似乱码",
    }
    return mapping.get(code, "质量偏低，建议精识别或手改")


def build_template_subtitle_status(template) -> dict[str, Any]:
    slots = [s for s in (template.slots or []) if isinstance(s, dict)]
    peer_texts: list[str] = []
    slot_rows: list[dict[str, Any]] = []
    duplicate_count = 0
    empty_count = 0
    low_count = 0
    ready_count = 0

    for slot in slots:
        st = classify_slot_subtitle(slot, peer_texts=peer_texts)
        if st.subtitle_text:
            peer_texts.append(st.subtitle_text)
        if st.quality == "ok":
            ready_count += 1
        elif st.quality == "empty":
            empty_count += 1
        else:
            low_count += 1
        if st.duplicate:
            duplicate_count += 1
        slot_rows.append({
            "slot_id": st.slot_id,
            "quality": st.quality,
            "source": st.source,
            "source_label": st.source_label,
            "reason": st.reason,
            "subtitle_text": st.subtitle_text,
            "duplicate": st.duplicate,
        })

    from services.processing_config import SUBTITLE_RECOGNITION_MODE
    from services.template_subtitle_auto import is_subtitle_batch_running

    total = len(slots)
    return {
        "template_id": getattr(template, "id", None),
        "slot_count": total,
        "ready_count": ready_count,
        "empty_count": empty_count,
        "low_count": low_count,
        "duplicate_count": duplicate_count,
        "failed_count": empty_count + low_count,
        "recognition_mode": SUBTITLE_RECOGNITION_MODE,
        "batch_running": is_subtitle_batch_running(getattr(template, "id", "") or ""),
        "progress_label": f"{ready_count}/{total} 槽位字幕就绪",
        "slots": slot_rows,
    }
