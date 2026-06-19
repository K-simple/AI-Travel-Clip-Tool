"""模板槽位 CLIP + DeepSeek 语义分析。"""

import os
from typing import Any, Callable, Dict, List, Optional

from services.ai_label_enricher import enrich_items_with_ai_labels
from services.asset_analyzer import analyze_frame, analyze_quality


def enrich_template_slots(
    slots: List[Dict[str, Any]],
    video_path: str = "",
    *,
    on_slot_ready: Optional[Callable[[int, Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    """为模板槽位补充 scene_tags / shot_type / clip_embedding / ai_description / ai_replace_hint。"""
    enriched: List[Dict[str, Any]] = []

    for slot in slots:
        item = dict(slot)
        thumb = item.get("thumbnail", "")

        if thumb and os.path.exists(thumb):
            frame_info = analyze_frame(thumb)
            item["scene_tags"] = frame_info.get("scene_tags", [])
            item["tags"] = item["scene_tags"]
            if not item.get("shot_type"):
                item["shot_type"] = frame_info.get("shot_type", "wide")
            item["has_person"] = frame_info.get("has_person", False)

            emb = frame_info.get("clip_embedding") or []
            if emb:
                item["clip_embedding"] = emb
        else:
            item.setdefault("scene_tags", [])
            item.setdefault("tags", [])
            item.setdefault("shot_type", "wide")
            item.setdefault("has_person", False)

        if video_path and os.path.exists(video_path):
            start = float(item.get("start", 0))
            end = float(item.get("end", start + float(item.get("duration", 0))))
            item["quality_score"] = analyze_quality(video_path, start, end)
        else:
            item.setdefault("quality_score", 0.5)

        enriched.append(item)

    return enrich_items_with_ai_labels(
        enriched,
        label="模板槽位",
        template_slots=True,
        on_item_ready=on_slot_ready,
    )
