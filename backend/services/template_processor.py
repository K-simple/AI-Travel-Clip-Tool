"""模板后台处理：快速可编辑 + 后台增强（AI 镜头修正 / 代理 / 音频）。"""

import os
import time
from typing import Any, Dict, List, Optional

from models.database import SessionLocal, Template
from services.beat_detector import estimate_beat_markers
from services.processing_config import (
    DEFER_TEMPLATE_PROXIES,
    DEFER_WHISPER,
    TEMPLATE_EXTRACT_AUDIO_EARLY,
    TEMPLATE_FAST_EDIT_READY,
    TEMPLATE_FAST_SKIP_AUTO_TUNE,
    TEMPLATE_SCENE_INTERVAL_FALLBACK,
)
from services.scene_detector import (
    _attach_thumbnails,
    build_template_shot_slots,
    extract_frame,
    get_video_duration,
)
from services.proxy_generator import generate_preview_proxies, normalize_proxy_paths
from services.slot_analyzer import enrich_template_slots


def mark_template_failed(template_id: str, error: str = "") -> None:
    _update_template(
        template_id,
        processing_status="failed",
        processing_progress=100,
        enhance_status="failed",
        enhance_progress=100,
    )
    if error:
        print(f"模板处理失败 [{template_id}]: {error}")


def mark_template_ready(template_id: str, progress: int = 100) -> None:
    _update_template(
        template_id,
        processing_status="ready",
        processing_progress=progress,
        enhance_status="ready",
        enhance_progress=100,
    )


def mark_template_editable(
    template_id: str,
    *,
    slots: list,
    duration: float,
    beat_markers: list | None = None,
    proxy_paths: dict | None = None,
) -> None:
    """场景切分完成，用户可开始编辑；后台增强继续。"""
    _update_template(
        template_id,
        duration=duration,
        slots=slots,
        slot_count=len(slots),
        beat_markers=beat_markers or [],
        proxy_paths=normalize_proxy_paths(proxy_paths or {}),
        processing_status="ready",
        processing_progress=100,
        enhance_status="processing",
        enhance_progress=5,
    )
    print(f"模板可编辑: {template_id} -> {len(slots)} 个画面槽位")


def _update_template(template_id: str, **fields: Any) -> Optional[Template]:
    db = SessionLocal()
    try:
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            return None
        for key, value in fields.items():
            setattr(template, key, value)
        if hasattr(template, "updated_at"):
            template.updated_at = time.time()
        db.commit()
        db.refresh(template)
        return template
    finally:
        db.close()


def _bump_enhance(template_id: str, progress: int) -> None:
    _update_template(template_id, enhance_progress=progress, enhance_status="processing")


def process_template_edit_ready(template_id: str, file_path: str) -> list:
    """
    第一阶段：约 10 秒内可编辑。
    - 时长 + 封面
    - PySceneDetect 按画面切槽（跳过 AI 修正、跳过代理、跳过缩略图批量抽取）
    """
    _update_template(
        template_id,
        processing_progress=15,
        processing_status="processing",
        enhance_status="processing",
        enhance_progress=0,
    )

    duration = get_video_duration(file_path)
    if duration <= 0:
        raise RuntimeError("无法读取模板视频时长")

    thumb_dir = os.path.join("storage", "thumbnails", template_id)
    os.makedirs(thumb_dir, exist_ok=True)
    main_thumb = os.path.join(thumb_dir, "main.jpg").replace("\\", "/")
    extract_frame(file_path, max(duration / 2, 0.5), main_thumb)

    _update_template(template_id, processing_progress=35, processing_status="processing")

    fast = TEMPLATE_FAST_EDIT_READY
    slots = build_template_shot_slots(
        file_path,
        thumb_dir,
        duration,
        skip_auto_tune=fast and TEMPLATE_FAST_SKIP_AUTO_TUNE,
        skip_ai_refine=True,
        extract_thumbs=False,
        allow_interval_fallback=TEMPLATE_SCENE_INTERVAL_FALLBACK,
        on_progress=lambda p: _update_template(
            template_id, processing_progress=min(95, p), processing_status="processing"
        ),
    )

    if not slots:
        raise RuntimeError("镜头切分未产生槽位，请检查视频格式或场景检测配置")

    mark_template_editable(
        template_id,
        slots=slots,
        duration=duration,
        beat_markers=[],
        proxy_paths={},
    )
    return slots


def process_template_enhancement(
    template_id: str,
    file_path: str,
    template_dir: str,
    *,
    extract_audio_fn,
    has_audio_fn,
    file_ok_fn,
) -> None:
    """
    第二阶段：后台增强（不阻塞编辑）。
    AI 镜头修正 → 槽位缩略图 → 预览代理 → 节拍 → CLIP 标签 → 音频
    """
    db = SessionLocal()
    try:
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            return
        slots = list(template.slots or [])
        duration = float(template.duration or 0)
    finally:
        db.close()

    if not slots or duration <= 0:
        _update_template(template_id, enhance_status="ready", enhance_progress=100)
        return

    thumb_dir = os.path.join("storage", "thumbnails", template_id)
    os.makedirs(thumb_dir, exist_ok=True)

    try:
        # 1) AI 镜头修正（合并误切 / 拆分漏切）
        _bump_enhance(template_id, 10)
        from services.ai_shot_refiner import refine_shots_with_ai
        from services.template_scene_tuning import resolve_tuning_for_template

        tuning = resolve_tuning_for_template(file_path)
        refined = refine_shots_with_ai(slots, file_path, thumb_dir, tuning=tuning)
        if refined:
            slots = refined
            print(f"AI 镜头修正完成: {template_id} -> {len(slots)} 段")

        _bump_enhance(template_id, 35)

        # 2) 槽位缩略图
        slots = _attach_thumbnails(file_path, thumb_dir, slots)
        _update_template(template_id, slots=slots, slot_count=len(slots))
        _bump_enhance(template_id, 50)

        # 3) 预览代理（后台生成，不阻塞编辑）
        proxy_paths: Dict[str, str] = {"clear": "", "smooth": "", "low": ""}

        def _on_tier(tier: str, path: str) -> None:
            proxy_paths[tier] = path
            _update_template(
                template_id,
                proxy_paths=normalize_proxy_paths(proxy_paths),
            )

        generate_preview_proxies(file_path, template_dir, "template", on_tier_ready=_on_tier)

        _bump_enhance(template_id, 70)

        # 4) 节拍
        beat_markers = estimate_beat_markers(duration)
        _update_template(template_id, beat_markers=beat_markers)

        # 5) CLIP / 标签 enrich
        try:
            process_template_slot_enrich(template_id, file_path)
        except Exception as exc:
            print(f"模板槽位 enrich 跳过: {exc}")

        _bump_enhance(template_id, 85)

        # 6) 音频
        process_template_audio_only(
            template_id,
            file_path,
            template_dir,
            extract_audio_fn,
            has_audio_fn,
            file_ok_fn,
        )

        _update_template(
            template_id,
            enhance_status="ready",
            enhance_progress=100,
            proxy_paths=normalize_proxy_paths(proxy_paths),
        )
        print(f"模板后台增强完成: {template_id}")
    except Exception as exc:
        print(f"模板后台增强失败（保留已可编辑槽位）: {template_id} -> {exc}")
        _update_template(template_id, enhance_status="ready", enhance_progress=100)


def process_template_fast_intake(template_id: str, file_path: str) -> None:
    """兼容旧调用：完整 intake（非快速模式）。"""
    template_dir = os.path.dirname(file_path)
    thumb_dir = os.path.join("storage", "thumbnails", template_id)
    os.makedirs(thumb_dir, exist_ok=True)

    _update_template(template_id, processing_progress=12)
    duration = get_video_duration(file_path)
    if duration <= 0:
        raise RuntimeError("无法读取模板视频时长")

    extract_frame(file_path, max(duration / 2, 0.5), os.path.join(thumb_dir, "main.jpg"))

    proxy_paths: Dict[str, str] = {"clear": "", "smooth": "", "low": ""}

    def _on_tier(tier: str, path: str) -> None:
        proxy_paths[tier] = path
        _update_template(
            template_id,
            proxy_paths=normalize_proxy_paths(proxy_paths),
            processing_progress={"low": 22, "smooth": 28, "clear": 34}.get(tier, 34),
        )

    if not DEFER_TEMPLATE_PROXIES:
        generate_preview_proxies(file_path, template_dir, "template", on_tier_ready=_on_tier)

    _update_template(template_id, processing_progress=38, processing_status="processing")
    slots = build_template_shot_slots(
        file_path,
        thumb_dir,
        duration,
        on_progress=lambda p: _update_template(
            template_id, processing_progress=p, processing_status="processing"
        ),
    )
    beat_markers = estimate_beat_markers(duration)

    _update_template(
        template_id,
        duration=duration,
        slots=slots,
        slot_count=len(slots),
        beat_markers=beat_markers,
        proxy_paths=normalize_proxy_paths(proxy_paths),
        processing_status="processing",
        processing_progress=70,
    )


def process_template_slot_enrich(template_id: str, file_path: str) -> None:
    """为快速槽位补充 CLIP 标签（基于缩略图，与素材分析对称）。"""
    db = SessionLocal()
    try:
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template or not template.slots:
            return
        slots = enrich_template_slots(list(template.slots), file_path)
        template.slots = slots
        template.slot_count = len(slots)
        if hasattr(template, "updated_at"):
            template.updated_at = time.time()
        db.commit()
        print(f"模板槽位 CLIP 分析完成: {template_id} -> {len(slots)} 段")
    except Exception as exc:
        print(f"模板槽位 CLIP 分析失败（保留原槽位）: {exc}")
    finally:
        db.close()


def process_template_audio_only(
    template_id: str,
    file_path: str,
    template_dir: str,
    extract_audio_fn,
    has_audio_fn,
    file_ok_fn,
) -> None:
    """仅提取模板音频（不做 Whisper）。"""
    if not TEMPLATE_EXTRACT_AUDIO_EARLY or not has_audio_fn(file_path):
        return

    template_audio_path = os.path.join(template_dir, "template_audio.m4a")
    try:
        extract_audio_fn(file_path, template_audio_path)
        audio_path = template_audio_path if file_ok_fn(template_audio_path) else ""
    except Exception as exc:
        print(f"模板音频提取失败: {exc}")
        audio_path = ""

    if audio_path:
        _update_template(template_id, audio_path=audio_path)


def process_template_full(
    template_id: str,
    file_path: str,
    template_dir: str,
    subtitle_style: str,
    *,
    extract_audio_fn,
    extract_whisper_audio_fn,
    transcribe_fn,
    normalize_segments_fn,
    write_srt_fn,
    write_ass_fn,
    attach_subtitles_fn,
    has_audio_fn,
    file_ok_fn,
) -> None:
    if TEMPLATE_FAST_EDIT_READY:
        process_template_edit_ready(template_id, file_path)
        process_template_enhancement(
            template_id,
            file_path,
            template_dir,
            extract_audio_fn=extract_audio_fn,
            has_audio_fn=has_audio_fn,
            file_ok_fn=file_ok_fn,
        )
    else:
        process_template_fast_intake(template_id, file_path)
        try:
            process_template_slot_enrich(template_id, file_path)
        except Exception as exc:
            print(f"模板槽位 enrich 跳过: {exc}")
        process_template_audio_only(
            template_id,
            file_path,
            template_dir,
            extract_audio_fn,
            has_audio_fn,
            file_ok_fn,
        )

    if DEFER_WHISPER:
        mark_template_ready(template_id, 100)
        return

    _run_whisper_pipeline(
        template_id,
        file_path,
        template_dir,
        subtitle_style,
        extract_audio_fn=extract_audio_fn,
        extract_whisper_audio_fn=extract_whisper_audio_fn,
        transcribe_fn=transcribe_fn,
        normalize_segments_fn=normalize_segments_fn,
        write_srt_fn=write_srt_fn,
        write_ass_fn=write_ass_fn,
        attach_subtitles_fn=attach_subtitles_fn,
        has_audio_fn=has_audio_fn,
        file_ok_fn=file_ok_fn,
    )


def _run_whisper_pipeline(
    template_id: str,
    file_path: str,
    template_dir: str,
    subtitle_style: str,
    **helpers,
) -> None:
    db = SessionLocal()
    try:
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            return

        has_audio_fn = helpers["has_audio_fn"]
        file_ok_fn = helpers["file_ok_fn"]

        if not has_audio_fn(file_path):
            template.processing_status = "ready"
            template.processing_progress = 100
            template.enhance_status = "ready"
            template.enhance_progress = 100
            db.commit()
            return

        template_audio_path = template.audio_path or os.path.join(template_dir, "template_audio.m4a")
        whisper_audio_path = os.path.join(template_dir, "template_subtitle_audio.wav")
        subtitle_srt_path = os.path.join(template_dir, "template_subtitle.srt")
        subtitle_ass_path = os.path.join(template_dir, "template_subtitle.ass")
        segments_json: List[Dict[str, Any]] = []

        try:
            if not file_ok_fn(template_audio_path):
                helpers["extract_audio_fn"](file_path, template_audio_path)
            helpers["extract_whisper_audio_fn"](file_path, whisper_audio_path)
            raw_segments = helpers["transcribe_fn"](whisper_audio_path)
            segments_json = helpers["normalize_segments_fn"](raw_segments)

            if segments_json:
                helpers["write_srt_fn"](segments_json, subtitle_srt_path)
                helpers["write_ass_fn"](segments_json, subtitle_ass_path)
            else:
                subtitle_srt_path = ""
                subtitle_ass_path = ""
        except Exception as exc:
            print(f"模板字幕识别失败: {exc}")
            if not file_ok_fn(template_audio_path):
                template_audio_path = ""
            subtitle_srt_path = ""
            subtitle_ass_path = ""
            segments_json = []

        try:
            template.slots = helpers["attach_subtitles_fn"](template.slots or [], segments_json)
        except Exception as exc:
            print(f"字幕挂载失败: {exc}")

        template.audio_path = template_audio_path if file_ok_fn(template_audio_path) else ""
        template.subtitle_srt_path = subtitle_srt_path if file_ok_fn(subtitle_srt_path) else ""
        template.subtitle_ass_path = subtitle_ass_path if file_ok_fn(subtitle_ass_path) else ""
        template.segments_json = segments_json
        template.processing_status = "ready"
        template.processing_progress = 100
        template.enhance_status = "ready"
        template.enhance_progress = 100
        db.commit()
    except Exception as exc:
        print(f"模板 Whisper 流水线失败: {exc}")
        try:
            template = db.query(Template).filter(Template.id == template_id).first()
            if template:
                template.processing_status = "ready"
                template.processing_progress = 100
                template.enhance_status = getattr(template, "enhance_status", "ready") or "ready"
                template.enhance_progress = 100
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
