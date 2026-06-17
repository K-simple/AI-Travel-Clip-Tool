"""云素材库 — 本地 catalog + 导入到本地素材库。"""

import json
import os
import shutil
import time
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from models.database import Asset, get_db
from services.asset_processor import build_quick_segments, process_asset_full
from services.task_queue import create_task, run_task
from utils.storage_backend import get_storage_backend

router = APIRouter()

_CATALOG = os.path.join("storage", "cloud", "catalog.json")


def _load_catalog() -> List[Dict[str, Any]]:
    if not os.path.exists(_CATALOG):
        return []
    try:
        with open(_CATALOG, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", [])
    except Exception:
        return []


def _save_catalog(items: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(_CATALOG), exist_ok=True)
    with open(_CATALOG, "w", encoding="utf-8") as f:
        json.dump({"items": items, "updated_at": time.time()}, f, ensure_ascii=False, indent=2)


@router.get("/list")
def list_cloud_assets(tag: Optional[str] = None, keyword: Optional[str] = None):
    items = _load_catalog()
    if tag:
        items = [i for i in items if tag in (i.get("tags") or [])]
    if keyword:
        kw = keyword.lower()
        items = [
            i
            for i in items
            if kw in (i.get("title") or "").lower() or kw in (i.get("description") or "").lower()
        ]
    return {"items": items, "count": len(items), "backend": get_storage_backend()}


@router.post("/register")
def register_cloud_asset(body: Dict[str, Any] = Body(...)):
    title = (body.get("title") or "").strip()
    url = (body.get("url") or body.get("file_path") or "").strip()
    if not title or not url:
        raise HTTPException(status_code=400, detail="需要 title 与 url/file_path")

    items = _load_catalog()
    item = {
        "id": str(uuid.uuid4()),
        "title": title,
        "url": url,
        "thumbnail": body.get("thumbnail", ""),
        "duration": float(body.get("duration", 0)),
        "tags": body.get("tags") or [],
        "description": body.get("description", ""),
        "created_at": time.time(),
    }
    items.insert(0, item)
    _save_catalog(items)
    return {"success": True, "item": item}


def _resolve_source_path(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("空 URL")
    if url.startswith("/storage/"):
        path = os.path.join("storage", url[len("/storage/"):])
        if os.path.isfile(path):
            return path
    if url.startswith("storage/") and os.path.isfile(url):
        return url
    if os.path.isfile(url):
        return url
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        ext = os.path.splitext(parsed.path)[1].lower() or ".mp4"
        temp_name = f"cloud_{uuid.uuid4().hex}{ext}"
        dest = os.path.join("storage", "temp", temp_name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with urlopen(url, timeout=120) as resp, open(dest, "wb") as out:
            shutil.copyfileobj(resp, out)
        return dest
    raise ValueError(f"无法解析素材路径: {url}")


@router.post("/import/{item_id}")
def import_to_local(item_id: str, db: Session = Depends(get_db)):
    items = _load_catalog()
    item = next((i for i in items if i["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="云素材不存在")

    try:
        src_path = _resolve_source_path(item.get("url", ""))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    asset_id = str(uuid.uuid4())
    ext = os.path.splitext(src_path)[1].lower() or ".mp4"
    dest_path = f"storage/assets/{asset_id}{ext}"
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    if src_path.startswith(os.path.join("storage", "temp")):
        shutil.move(src_path, dest_path)
    else:
        shutil.copy2(src_path, dest_path)

    thumb_dir = f"storage/thumbnails/assets/{asset_id}"
    os.makedirs(thumb_dir, exist_ok=True)
    quick_segments = build_quick_segments(0, dest_path, "", asset_id, item.get("title") or "cloud")

    now = time.time()
    asset = Asset(
        id=asset_id,
        filename=item.get("title") or os.path.basename(dest_path),
        duration=float(item.get("duration", 0)),
        file_path=dest_path,
        thumbnail_path=item.get("thumbnail", ""),
        segments=quick_segments,
        proxy_path="",
        processing_status="processing",
        processing_progress=5,
        created_at=now,
        updated_at=now,
    )
    db.add(asset)
    db.commit()

    task_id = create_task("asset_analyze", {"asset_id": asset_id})
    run_task(task_id, lambda: process_asset_full(asset_id, task_id))

    return {
        "success": True,
        "asset_id": asset_id,
        "filename": asset.filename,
        "file_path": dest_path,
        "task_id": task_id,
        "message": "已导入本地素材库，后台分析中",
    }
