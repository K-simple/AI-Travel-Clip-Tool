"""素材后台分析（场景切分、CLIP、代理）。"""

import os
import time
from typing import Optional

from models.database import SessionLocal
from services.asset_analyzer import analyze_asset_fast, enrich_segments
from services.processing_config import (
    ASSET_FAST_EDIT_READY,
    ASSET_QUICK_SEGMENTS,
    DEFER_ASSET_AI_LABELS,
    DEFER_ASSET_PROXIES,
    SKIP_CLIP,
    SKIP_PROXY,
    SKIP_SEGMENT_MP4,
    TEMPLATE_SLOT_INTERVAL,
)
from services.proxy_generator import generate_preview_proxies, normalize_proxy_paths
from services.scene_detector import build_interval_segments, extract_frame, get_video_duration
from services.segment_extractor import attach_segment_videos
from services.task_queue import update_task


def build_quick_segments(
    duration: float,
    file_path: str,
    thumb_path: str,
    asset_id: str,
    filename: str,
    thumb_dir: str = "",
) -> list:
    """上传后按时间间隔快速切分多镜头，保证素材库与时间轴可区分各段。"""
    raw = build_interval_segments(
        duration,
        TEMPLATE_SLOT_INTERVAL,
        video_path="" if ASSET_QUICK_SEGMENTS else file_path,
        thumb_dir="" if ASSET_QUICK_SEGMENTS else (thumb_dir or os.path.dirname(thumb_path)),
    )
    if not raw:
        return [
            {
                "segment_id": "seg_1",
                "slot_id": 1,
                "start": 0.0,
                "end": round(duration, 3),
                "duration": round(duration, 3),
                "thumbnail": thumb_path,
                "scene_tags": [],
                "shot_type": "wide",
                "has_person": False,
                "quality_score": 0.5,
                "type": "video",
                "file_path": file_path,
                "segment_file_path": "",
                "clip_start": 0.0,
                "clip_end": round(duration, 3),
                "filename": filename,
                "asset_id": asset_id,
            }
        ]

    segments = []
    for i, seg in enumerate(raw):
        thumb = seg.get("thumbnail") or thumb_path
        if ASSET_QUICK_SEGMENTS and thumb_path:
            thumb = thumb_path
        segments.append({
            **seg,
            "segment_id": seg.get("segment_id") or f"seg_{i + 1}",
            "thumbnail": thumb,
            "file_path": file_path,
            "segment_file_path": "",
            "clip_start": float(seg.get("start", 0)),
            "clip_end": float(seg.get("end", duration)),
            "filename": filename,
            "asset_id": asset_id,
        })
    return segments


def _apply_proxy_paths(asset, proxy_map: dict) -> None:
    normalized = normalize_proxy_paths(proxy_map)
    asset.proxy_paths = normalized
    asset.proxy_path = normalized.get("smooth") or normalized.get("low") or normalized.get("clear") or ""


def _mark_asset_ready(asset, db, *, progress: int = 100) -> None:
    asset.processing_status = "ready"
    asset.processing_progress = progress
    asset.updated_at = time.time()
    db.commit()


def process_asset_intake(asset_id: str, task_id: Optional[str] = None) -> dict:
    """快速补齐时长、封面与可拖拽镜头（不等代理/精分）。"""
    db = SessionLocal()
    try:
        from models.database import Asset

        asset = db.query(Asset).filter(Asset.id == asset_id).first()
        if not asset:
            raise RuntimeError("素材不存在")

        file_path = asset.file_path
        thumb_dir = os.path.join("storage", "thumbnails", "assets", asset_id)
        os.makedirs(thumb_dir, exist_ok=True)

        if task_id:
            update_task(task_id, progress=8, message="读取视频信息…")
        asset.processing_progress = 8
        db.commit()

        duration = get_video_duration(file_path)
        if duration <= 0:
            raise RuntimeError("无法读取视频时长")

        main_thumb = f"{thumb_dir}/main.jpg"
        extract_frame(file_path, max(duration / 2, 0.5), main_thumb)

        asset.duration = duration
        asset.thumbnail_path = main_thumb
        asset.segments = build_quick_segments(
            duration, file_path, main_thumb, asset_id, asset.filename, thumb_dir
        )
        asset.processing_progress = 42 if ASSET_FAST_EDIT_READY else 15
        asset.updated_at = time.time()
        db.commit()

        if task_id:
            update_task(
                task_id,
                progress=asset.processing_progress,
                message="基础镜头已就绪，可拖拽使用…" if ASSET_FAST_EDIT_READY else "读取完成，继续分析…",
            )

        proxy_result: dict = {"clear": "", "smooth": "", "low": ""}
        if not SKIP_PROXY and not DEFER_ASSET_PROXIES:
            if task_id:
                update_task(task_id, progress=18, message="生成预览代理（低清→流畅→清晰）…")
            asset.processing_progress = 18
            db.commit()
            proxy_dir = os.path.dirname(file_path)

            def _on_tier(tier: str, path: str) -> None:
                proxy_result[tier] = path
                _apply_proxy_paths(asset, proxy_result)
                step = {"low": 24, "smooth": 30, "clear": 35}.get(tier, 35)
                asset.processing_progress = step
                asset.updated_at = time.time()
                db.commit()
                if task_id:
                    update_task(task_id, progress=step, message=f"预览代理 {tier} 已就绪…")

            generate_preview_proxies(
                file_path,
                proxy_dir,
                f"proxy_{asset_id}",
                on_tier_ready=_on_tier,
            )
            _apply_proxy_paths(asset, proxy_result)
            asset.processing_progress = 35
            asset.updated_at = time.time()
            db.commit()
            if task_id:
                update_task(task_id, progress=35, message="预览代理已就绪，继续分析…")

        if ASSET_FAST_EDIT_READY:
            _mark_asset_ready(asset, db, progress=45)

        return {"asset_id": asset_id, "duration": duration, "proxy_paths": proxy_result}
    finally:
        db.close()


def process_asset_analysis(asset_id: str, task_id: Optional[str] = None) -> dict:
    db = SessionLocal()
    try:
        from models.database import Asset

        asset = db.query(Asset).filter(Asset.id == asset_id).first()
        if not asset:
            raise RuntimeError("素材不存在")

        file_path = asset.file_path
        thumb_dir = os.path.join("storage", "thumbnails", "assets", asset_id)
        os.makedirs(thumb_dir, exist_ok=True)

        if task_id:
            update_task(task_id, progress=52, message="镜头精分…")
        asset.processing_progress = max(asset.processing_progress or 0, 52)
        db.commit()

        segments = analyze_asset_fast(file_path, asset_id, thumb_dir)
        for seg in segments:
            seg["file_path"] = file_path
            seg["filename"] = asset.filename

        if not SKIP_SEGMENT_MP4:
            if task_id:
                update_task(task_id, progress=68, message="导出镜头视频…")
            asset.processing_progress = 68
            db.commit()
            segments = attach_segment_videos(file_path, asset_id, segments)

        asset.segments = segments
        asset.processing_progress = 82
        asset.updated_at = time.time()
        db.commit()

        if task_id:
            update_task(task_id, progress=82, message="镜头精分完成…")

        if not SKIP_CLIP:
            if task_id:
                update_task(task_id, progress=90, message="AI 语义打标…")
            asset.processing_progress = 90
            db.commit()
            segments = enrich_segments(
                segments,
                file_path,
                asset_id,
                skip_ai_labels=DEFER_ASSET_AI_LABELS,
            )

        for seg in segments:
            seg["file_path"] = file_path
            seg["filename"] = asset.filename

        asset.segments = segments
        asset.updated_at = time.time()
        db.commit()

        proxy_paths = normalize_proxy_paths(getattr(asset, "proxy_paths", None))

        return {
            "asset_id": asset_id,
            "segment_count": len(segments),
            "proxy_path": asset.proxy_path or "",
            "proxy_paths": proxy_paths,
        }
    except Exception as exc:
        if db:
            try:
                from models.database import Asset

                asset = db.query(Asset).filter(Asset.id == asset_id).first()
                if asset and not ASSET_FAST_EDIT_READY:
                    asset.processing_status = "failed"
                    asset.processing_progress = 100
                    db.commit()
            except Exception:
                pass
        raise exc
    finally:
        db.close()


def process_asset_enhance(asset_id: str, task_id: Optional[str] = None) -> dict:
    """后台增强：预览代理与 DeepSeek 中文标签（不阻塞快速入库）。"""
    db = SessionLocal()
    try:
        from models.database import Asset
        from services.ai_label_enricher import enrich_items_with_ai_labels

        asset = db.query(Asset).filter(Asset.id == asset_id).first()
        if not asset:
            raise RuntimeError("素材不存在")

        file_path = asset.file_path
        proxy_result: dict = normalize_proxy_paths(getattr(asset, "proxy_paths", None))

        if not SKIP_PROXY and DEFER_ASSET_PROXIES:
            if task_id:
                update_task(task_id, progress=88, message="后台生成预览代理…")
            asset.processing_progress = 88
            db.commit()
            proxy_dir = os.path.dirname(file_path)

            def _on_tier(tier: str, path: str) -> None:
                proxy_result[tier] = path
                _apply_proxy_paths(asset, proxy_result)
                asset.updated_at = time.time()
                db.commit()

            generate_preview_proxies(
                file_path,
                proxy_dir,
                f"proxy_{asset_id}",
                on_tier_ready=_on_tier,
                tiers=("low", "smooth") if ASSET_FAST_EDIT_READY else None,
            )
            _apply_proxy_paths(asset, proxy_result)
            db.commit()

        if DEFER_ASSET_AI_LABELS and asset.segments:
            if task_id:
                update_task(task_id, progress=94, message="后台补充 AI 标签…")
            segments = enrich_items_with_ai_labels(list(asset.segments), label="素材片段")
            for seg in segments:
                seg["file_path"] = file_path
                seg["filename"] = asset.filename
            asset.segments = segments
            asset.updated_at = time.time()
            db.commit()

        _mark_asset_ready(asset, db, progress=100)
        if task_id:
            update_task(task_id, progress=100, message="素材增强完成")

        return {
            "asset_id": asset_id,
            "proxy_paths": proxy_result,
            "segment_count": len(asset.segments or []),
        }
    finally:
        db.close()


def process_asset_full(asset_id: str, task_id: Optional[str] = None) -> dict:
    """完整后台流水线：快速入库 → 镜头精分 → 可选后台增强。"""
    try:
        intake = process_asset_intake(asset_id, task_id)
        analysis = process_asset_analysis(asset_id, task_id)
        enhance: dict = {}
        if ASSET_FAST_EDIT_READY and (DEFER_ASSET_PROXIES or DEFER_ASSET_AI_LABELS):
            enhance = process_asset_enhance(asset_id, task_id)
        else:
            db = SessionLocal()
            try:
                from models.database import Asset

                asset = db.query(Asset).filter(Asset.id == asset_id).first()
                if asset:
                    _mark_asset_ready(asset, db, progress=100)
            finally:
                db.close()
            if task_id:
                update_task(task_id, progress=100, message="完成")
        return {**intake, **analysis, **enhance}
    except Exception as exc:
        db = SessionLocal()
        try:
            from models.database import Asset

            asset = db.query(Asset).filter(Asset.id == asset_id).first()
            if asset and not ASSET_FAST_EDIT_READY:
                asset.processing_status = "failed"
                asset.processing_progress = 100
                db.commit()
        finally:
            db.close()
        raise exc
