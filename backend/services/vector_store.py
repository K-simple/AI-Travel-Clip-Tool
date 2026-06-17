"""向量存储 — Milvus / PGVector / 内存回退。"""

import json
import os
from typing import Any, Dict, List, Optional

_BACKEND = os.getenv("VECTOR_BACKEND", "memory")  # memory | pgvector | milvus
_MILVUS_URI = os.getenv("MILVUS_URI", "")
_PGVECTOR_DSN = os.getenv("PGVECTOR_DSN", os.getenv("DATABASE_URL", ""))

_memory: Dict[str, Dict[str, Any]] = {}


def _load_memory_from_disk() -> None:
    global _memory
    path = os.path.join("storage", "vector_index.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _memory = data.get("segments", {})
        except Exception:
            _memory = {}


_load_memory_from_disk()


def upsert(key: str, embedding: List[float], meta: Optional[Dict] = None) -> None:
    global _memory
    if _BACKEND == "milvus" and _MILVUS_URI:
        try:
            from pymilvus import Collection, connections, utility  # type: ignore
            connections.connect(uri=_MILVUS_URI)
            # 集合需预先创建；失败则回退内存
        except Exception:
            pass
    if _BACKEND == "pgvector" and _PGVECTOR_DSN.startswith("postgresql"):
        try:
            import psycopg2  # type: ignore
            conn = psycopg2.connect(_PGVECTOR_DSN)
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS clip_embeddings (
                  id TEXT PRIMARY KEY,
                  embedding JSONB,
                  meta JSONB
                )
                """
            )
            cur.execute(
                "INSERT INTO clip_embeddings (id, embedding, meta) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET embedding=EXCLUDED.embedding, meta=EXCLUDED.meta",
                (key, json.dumps(embedding), json.dumps(meta or {})),
            )
            conn.commit()
            cur.close()
            conn.close()
            return
        except Exception as exc:
            print(f"PGVector 写入失败，回退内存: {exc}")

    _memory[key] = {"embedding": embedding, "meta": meta or {}}
    # 持久化到文件
    path = os.path.join("storage", "vector_index.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"segments": _memory}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"segments": {}}
    data.setdefault("segments", {})[key] = _memory[key]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

