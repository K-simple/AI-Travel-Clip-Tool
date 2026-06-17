import os
import shutil
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from models.database import Asset, get_db
from services.asset_processor import build_quick_segments, process_asset_full
from services.proxy_generator import normalize_proxy_paths
from services.task_queue import create_task, get_task, run_task
from utils.upload_stream import save_upload_stream

router = APIRouter()


def _cleanup_asset_files(asset: Asset):
    paths = [asset.file_path, asset.thumbnail_path, getattr(asset, "proxy_path", "")]
    if asset.file_path:
        thumb_dir = os.path.join("storage", "thumbnails", "assets", asset.id)
        seg_dir = os.path.join("storage", "assets", asset.id, "segments")
        for path in (thumb_dir, seg_dir):
            if path and os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
    for path in paths:
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _asset_to_dict(asset: Asset, *, include_segments: bool = False) -> dict:
    proxy_paths = normalize_proxy_paths(getattr(asset, "proxy_paths", None))
    data = {
        "asset_id": asset.id,
        "filename": asset.filename,
        "duration": asset.duration,
        "thumbnail": asset.thumbnail_path,
        "file_path": asset.file_path,
        "segment_count": len(asset.segments) if asset.segments else 0,
        "proxy_path": getattr(asset, "proxy_path", "") or proxy_paths.get("smooth") or "",
        "proxy_paths": proxy_paths,
        "processing_status": getattr(asset, "processing_status", "ready") or "ready",
        "processing_progress": getattr(asset, "processing_progress", 100) or 100,
    }
    if include_segments:
        data["segments"] = asset.segments or []
    return data


@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """快速入库：流式落盘后立即返回，元数据/切分/AI 在后台进行。"""
    asset_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename or "")[1].lower() or ".mp4"
    safe_filename = f"{asset_id}{ext}"
    file_path = f"storage/assets/{safe_filename}"
    thumb_dir = f"storage/thumbnails/assets/{asset_id}"
    os.makedirs(thumb_dir, exist_ok=True)

    try:
        await save_upload_stream(file, file_path)

        quick_segments = build_quick_segments(
            0, file_path, "", asset_id, file.filename or safe_filename
        )

        now = time.time()
        asset = Asset(
            id=asset_id,
            filename=file.filename,
            duration=0,
            file_path=file_path,
            thumbnail_path="",
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

        payload = _asset_to_dict(asset, include_segments=False)
        payload["segments"] = quick_segments
        payload["processing"] = True
        payload["task_id"] = task_id
        return payload
    except HTTPException:
        if os.path.exists(file_path):
            os.remove(file_path)
        shutil.rmtree(thumb_dir, ignore_errors=True)
        raise
    except Exception as exc:
        if os.path.exists(file_path):
            os.remove(file_path)
        shutil.rmtree(thumb_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="素材上传失败") from exc


@router.get("/tasks/{task_id}")
def get_asset_task(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/list")
def list_assets(db: Session = Depends(get_db)):
    assets = db.query(Asset).all()
    return [_asset_to_dict(a, include_segments=True) for a in assets]


@router.get("/{asset_id}/status")
def get_asset_status(asset_id: str, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    return {
        "success": True,
        **_asset_to_dict(asset, include_segments=True),
    }


@router.get("/{asset_id}")
def get_asset(asset_id: str, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    return {"success": True, **_asset_to_dict(asset, include_segments=True)}


@router.post("/{asset_id}/reprocess")
def reprocess_asset(asset_id: str, db: Session = Depends(get_db)):
    """重新切分镜头并导出片段视频（修复旧素材仅单镜头的问题）。"""
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")
    if not asset.file_path or not os.path.isfile(asset.file_path):
        raise HTTPException(status_code=400, detail="素材文件不存在")

    asset.processing_status = "processing"
    asset.processing_progress = 5
    asset.updated_at = time.time()
    db.commit()

    task_id = create_task("asset_analyze", {"asset_id": asset_id})
    run_task(task_id, lambda: process_asset_full(asset_id, task_id))
    return {"success": True, "task_id": task_id, "asset_id": asset_id}


@router.delete("/{asset_id}")
def delete_asset(asset_id: str, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="素材不存在")

    _cleanup_asset_files(asset)
    db.delete(asset)
    db.commit()
    return {"success": True}
