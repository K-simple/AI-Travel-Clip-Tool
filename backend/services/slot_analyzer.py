"""模板槽位 CLIP + DeepSeek 语义分析。"""

import os
from typing import Any, Dict, List

from services.ai_label_enricher import enrich_items_with_ai_labels
from services.asset_analyzer import analyze_frame, analyze_quality, get_frame_embedding


def enrich_template_slots(slots: List[Dict[str, Any]], video_path: str = "") -> List[Dict[str, Any]]:
    """为模板槽位补充 scene_tags / shot_type / has_person / clip_embedding / ai_description。"""
    enriched: List[Dict[str, Any]] = []

    for slot in slots:
        item = dict(slot)
        thumb = item.get("thumbnail", "")

        if thumb and os.path.exists(thumb):
            frame_info = analyze_frame(thumb)
            item["scene_tags"] = frame_info.get("scene_tags", [])
            item["tags"] = item["scene_tags"]
            item["shot_type"] = frame_info.get("shot_type", "wide")
            item["has_person"] = frame_info.get("has_person", False)

            emb = get_frame_embedding(thumb)
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

    return enrich_items_with_ai_labels(enriched, label="模板槽位")
