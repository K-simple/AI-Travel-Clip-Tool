"""轻量向量索引（内存 + JSON 持久化，Phase C；可换 Milvus/PGVector）。"""

import json
import math
import os
from typing import Any, Dict, List, Optional


INDEX_PATH = os.path.join("storage", "vector_index.json")


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def _load() -> Dict[str, Any]:
    if not os.path.exists(INDEX_PATH):
        return {"segments": {}}
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"segments": {}}


def _save(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)


def upsert_segment_embedding(seg_key: str, embedding: List[float], meta: Optional[Dict[str, Any]] = None) -> None:
    try:
        from services.vector_store import upsert

        upsert(seg_key, embedding, meta)
    except Exception:
        pass
    data = _load()
    data["segments"][seg_key] = {
        "embedding": embedding,
        "meta": meta or {},
    }
    _save(data)


def vector_similarity(slot_emb: List[float], seg_emb: List[float]) -> float:
    return max(0.0, _cosine(slot_emb, seg_emb))


def score_with_vector(
    slot: Dict[str, Any],
    seg: Dict[str, Any],
    base_score: float,
    vector_weight: float = 0.25,
) -> float:
    slot_emb = slot.get("clip_embedding") or slot.get("ref_keyframe_emb")
    seg_emb = seg.get("clip_embedding")
    if not slot_emb or not seg_emb:
        return base_score
    sim = vector_similarity(slot_emb, seg_emb)
    w = max(0.0, min(1.0, vector_weight))
    return base_score * (1 - w) + sim * w
