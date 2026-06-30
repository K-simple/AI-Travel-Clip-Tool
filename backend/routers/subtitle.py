import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional, Union

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models.database import Template, get_db
from services.slot_subtitle import (
    ensure_template_segments_json,
    has_cached_whisper_source,
    segments_need_rebuild,
    slot_dict_source_range,
)
from services.subtitle_fusion import template_prefers_visual_subtitles
from services.subtitle_gen import generate_srt, transcribe
from services.subtitle_ocr import probe_visual_subtitle_text
from services.subtitle_pipeline import SlotSpec, recognize_all_slots_capcut, recognize_single_slot_capcut
from services.subtitle_scene_ai import enrich_slot_after_subtitle_recognition, enrich_slots_subtitle_scene
from services.subtitle_status import build_template_subtitle_status, classify_slot_subtitle
from services.processing_config import is_subtitle_quality_mode
from services.subtitle_config import resolve_recognition_mode
from services.vocal_separator import ensure_vocal_and_bgm_tracks, resolve_vocal_source_path
from utils.security import validate_upload_file

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=1)

SubtitleMode = Literal["speech", "burned", "auto", "visual", "audio"]


def _slot_source_range(slot: dict) -> tuple[float, float]:
    """槽位在模板源视频/人声上的起止时间。"""
    if slot.get("clip_start") is not None:
        start = float(slot["clip_start"])
        if slot.get("clip_end") is not None:
            end = float(slot["clip_end"])
        elif slot.get("clip_duration") is not None:
            end = start + float(slot["clip_duration"])
        else:
            end = start + float(slot.get("duration") or slot.get("slot_duration") or 0.1)
        return start, max(start + 0.1, end)

    start = float(slot.get("start", slot.get("start_time", slot.get("slot_start", 0))))
    if "end" in slot:
        end = float(slot["end"])
    elif "end_time" in slot:
        end = float(slot["end_time"])
    else:
        end = start + float(slot.get("duration") or slot.get("slot_duration") or 0.1)
    return start, max(start + 0.1, end)


def _slot_time_match(slot: dict, slot_start: float, slot_end: float, eps: float = 0.05) -> bool:
    start, end = _slot_source_range(slot)
    return abs(start - slot_start) <= eps and abs(end - slot_end) <= eps


def _find_slot_index(
    slots: list,
    slot_start: float,
    slot_end: float,
    slot_id: Optional[Union[str, int]] = None,
) -> Optional[int]:
    if slot_id is not None:
        for i, slot in enumerate(slots):
            sid = slot.get("slot_id") or slot.get("id")
            if sid is not None and str(sid) == str(slot_id):
                return i
    for i, slot in enumerate(slots):
        if _slot_time_match(slot, slot_start, slot_end):
            return i
    return None


def _find_cached_slot_subtitle(template: Template, slot_start: float, slot_end: float) -> Optional[dict]:
    slots = template.slots or []
    for slot in slots:
        if not _slot_time_match(slot, slot_start, slot_end):
            continue
        text = (slot.get("subtitle_text") or "").strip()
        segments = slot.get("subtitle_segments") or []
        if text or segments:
            return {"subtitle_text": text, "subtitle_segments": segments}
    return None


_SCENE_ENRICH_KEYS = (
    "subtitle_style",
    "subtitle_effect_label",
    "subtitle_visual_context",
    "subtitle_scene_match",
    "subtitle_scene_match_reason",
    "ai_description",
    "ai_subject",
    "scene_tags",
    "ai_effect_understanding",
)


def _scene_fields_from_slot(slot: dict | None) -> dict:
    if not isinstance(slot, dict):
        return {}
    out: dict = {}
    for key in _SCENE_ENRICH_KEYS:
        val = slot.get(key)
        if val is not None and val != "":
            out[key] = val
    return out


def _persist_slot_subtitle(
    template: Template,
    slot_start: float,
    slot_end: float,
    subtitle_text: str,
    segments: list,
    db: Session,
    slot_id: Optional[Union[str, int]] = None,
    *,
    commit: bool = True,
    enrich_scene: bool = True,
    source: str | None = None,
) -> None:
    slots = list(template.slots or [])
    if not slots:
        return
    idx = _find_slot_index(slots, slot_start, slot_end, slot_id)
    if idx is None:
        return

    scene_patch: dict = {}
    if enrich_scene and subtitle_text.strip():
        try:
            enriched = enrich_slot_after_subtitle_recognition(
                template.file_path or "",
                slots[idx],
                subtitle_text,
                segments,
                index=idx,
                work_dir=os.path.join(os.path.dirname(template.file_path or ""), "subtitle_scene"),
            )
            subtitle_text = enriched.get("subtitle_text") or subtitle_text
            segments = enriched.get("subtitle_segments") or segments
            scene_patch = {k: enriched[k] for k in _SCENE_ENRICH_KEYS if k in enriched}
        except Exception as exc:
            print(f"字幕场景分析失败 slot#{idx}: {exc}")

    peer_texts = [
        str(s.get("subtitle_text") or "").strip()
        for i, s in enumerate(slots)
        if i != idx and isinstance(s, dict)
    ]
    meta = classify_slot_subtitle(
        {**slots[idx], "subtitle_text": subtitle_text, "subtitle_segments": segments},
        source=source,
        peer_texts=peer_texts,
    )

    slots[idx] = {
        **slots[idx],
        "subtitle_text": subtitle_text,
        "subtitle_segments": segments,
        "subtitle_source": meta.source,
        "subtitle_quality": meta.quality,
        "subtitle_status_reason": meta.reason,
        "subtitle_duplicate": meta.duplicate,
        **scene_patch,
    }
    template.slots = slots
    flag_modified(template, "slots")
    if commit:
        db.commit()
        db.refresh(template)


class RecognizeSlotRequest(BaseModel):
    template_id: str
    slot_start: float = Field(ge=0)
    slot_end: float = Field(gt=0)
    slot_id: Optional[Union[str, int]] = None
    force: bool = False
    mode: SubtitleMode = "speech"
    quality: bool = False


class BatchRecognizeSlotRequest(BaseModel):
    template_id: str
    slots: list
    force: bool = False
    mode: SubtitleMode = "speech"
    quality: bool = False


class RecognizeCaptionsRequest(BaseModel):
    template_id: str
    force: bool = False
    mode: SubtitleMode = "speech"
    quality: bool = False


class ApplyCaptionSlotsRequest(BaseModel):
    template_id: str
    subtitle_clips: list[dict] | None = None
    source: str = "caption_clips"
    overwrite_slots: bool = Field(default=True, alias="overwriteSlots")
    use_tts_aligned_time: bool = Field(default=True, alias="useTtsAlignedTime")
    merge_short_fragments: bool = Field(default=True, alias="mergeShortFragments")

    model_config = {"populate_by_name": True}


class UpdateSubtitleClipsRequest(BaseModel):
    template_id: str
    subtitle_clips: list[dict]


def _resolve_batch_slot_range(template: Template, item: dict) -> tuple[float, float] | None:
    """优先用模板槽位上的源时间（clip_start），避免与前端时间轴坐标混淆。"""
    slot_id = item.get("slot_id")
    for slot in template.slots or []:
        if not isinstance(slot, dict):
            continue
        sid = slot.get("slot_id") or slot.get("id")
        if slot_id is not None and sid is not None and str(sid) == str(slot_id):
            return slot_dict_source_range(slot)
    try:
        slot_start = float(item.get("slot_start", 0))
        slot_end = float(item.get("slot_end", 0))
    except (TypeError, ValueError):
        return None
    if slot_end <= slot_start:
        return None
    return slot_start, slot_end


def _resolve_subtitle_flow(
    mode: SubtitleMode,
    template: Template,
    specs: list[SlotSpec],
) -> tuple[str, bool, bool]:
    """返回 (recognition_mode, prefer_visual, skip_whisper)。auto 默认 speech，不探测 OCR。"""
    rec = resolve_recognition_mode(mode)
    if rec == "speech":
        print(f"[subtitle] 口播模式 speech：跳过 OCR 探测，ASR 主导")
        return rec, False, False
    if rec == "burned":
        print(f"[subtitle] 烧录字幕模式 burned：仅 OCR")
        return rec, True, True
    # legacy auto 已废弃：未识别的 mode 一律 speech
    print(f"[subtitle] mode={mode} 未识别，回退 speech")
    return "speech", False, False


def _should_run_asr(mode: SubtitleMode, skip_whisper: bool) -> bool:
    if skip_whisper:
        return False
    rec = resolve_recognition_mode(mode)
    return rec == "speech"


def _template_speech_payload(template: Template, segments_json: list | None) -> dict:
    """批量/单槽 speech 响应：完整 spoken_caption 主轨 + 可选 debug。"""
    pool = segments_json or getattr(template, "segments_json", None) or []
    spoken: list = []
    for seg in pool:
        if not isinstance(seg, dict):
            continue
        seg_type = str(seg.get("type") or "spoken_caption")
        if seg_type in ("screen_text", "burned_subtitle_candidate", "uncertain"):
            continue
        spoken.append(seg)
    payload: dict = {
        "spoken_captions": spoken,
        "spokenCaptionSegments": spoken,
        "segments": spoken,
    }
    profile = getattr(template, "_last_effect_profile", None)
    if profile:
        payload["effect_profile"] = profile
    debug = getattr(template, "_last_speech_debug", None)
    if debug:
        payload["debug"] = debug
    split_debug = getattr(template, "_last_subtitle_split_debug", None)
    if not split_debug:
        from services.spoken_caption_split import get_last_split_debug

        split_debug = get_last_split_debug()
    if split_debug:
        payload["subtitleSplitDebug"] = split_debug
    clips = getattr(template, "subtitle_clips_json", None) or []
    clip_debug = getattr(template, "_last_subtitle_clip_debug", None)
    if not clip_debug:
        from services.subtitle_clip_planner import get_last_subtitle_clip_debug

        clip_debug = get_last_subtitle_clip_debug()
    if not clips and spoken:
        from services.subtitle_clip_planner import build_subtitle_clips_from_asr

        clips, clip_debug = build_subtitle_clips_from_asr(spoken)
    if clips:
        payload["subtitleClips"] = clips
        payload["subtitle_clips"] = clips
    if clip_debug:
        payload["subtitleClipDebug"] = clip_debug
    return payload


def _build_speech_summary(
    results: list[dict],
    template: Template,
    rec_mode: str,
) -> dict:
    debug = getattr(template, "_last_speech_debug", None) or {}
    asr = debug.get("asr") if isinstance(debug, dict) else {}
    if not isinstance(asr, dict):
        asr = {}
    matched = sum(1 for r in results if r.get("status") == "matched")
    errors = sum(1 for r in results if r.get("status") == "error")
    empty = sum(
        1
        for r in results
        if r.get("status") in ("no_speech", "no_overlap", "filtered")
    )
    return {
        "mode": rec_mode,
        "slotCount": len(results),
        "matchedSlotCount": matched,
        "emptySlotCount": empty,
        "errorSlotCount": errors,
        "rawAsrSegmentCount": int(asr.get("rawSegmentCount") or 0),
        "finalAsrSegmentCount": int(asr.get("finalSegmentCount") or 0),
        "droppedSegmentCount": int(asr.get("droppedSegmentCount") or 0),
    }


def _slot_row_from_outcome(outcome, *, include_scene: bool = False) -> dict:
    """将 SlotRecognizeOutcome 转为 API 槽位结果。"""
    subtitle_text = outcome.subtitle_text
    row: dict = {
        "slot_id": outcome.slot_id,
        "slotId": outcome.slot_id,
        "start": round(float(outcome.start), 3),
        "end": round(float(outcome.end), 3),
        "subtitle_text": subtitle_text,
        "subtitle_segments": outcome.segments,
        "segment_count": len(outcome.segments),
        "success": outcome.success,
        "status": outcome.status,
        "reason": outcome.reason,
        "linkedSubtitleSegmentIds": list(outcome.linked_subtitle_segment_ids or []),
        "source": outcome.source,
        "_slot_start": outcome.start,
        "_slot_end": outcome.end,
    }
    if outcome.status == "error":
        row["error"] = outcome.error or outcome.reason
    elif outcome.status != "matched":
        row["subtitle_quality"] = "empty"
        row["subtitle_status_reason"] = outcome.reason
    if include_scene:
        row["_include_scene"] = True
    return row


def _invalid_slot_row(
    slot_id,
    *,
    start: float = 0.0,
    end: float = 0.0,
    reason: str,
) -> dict:
    return {
        "slot_id": slot_id,
        "slotId": slot_id,
        "start": start,
        "end": end,
        "subtitle_text": "",
        "subtitle_segments": [],
        "success": False,
        "status": "error",
        "reason": reason,
        "linkedSubtitleSegmentIds": [],
        "error": reason,
    }


def _probe_prefer_visual(video_path: str, specs: list[SlotSpec]) -> bool:
    """探测模板是否含烧录字幕（影响融合时 OCR 权重）。"""
    probe_samples: list[str] = []
    for spec in specs[:5]:
        try:
            hit = probe_visual_subtitle_text(video_path, spec.slot_start, spec.slot_end)
            if hit:
                probe_samples.append(hit)
        except Exception:
            pass
        if len(probe_samples) >= 2:
            break
    if template_prefers_visual_subtitles(probe_samples, min_hits=1 if probe_samples else 2):
        return True
    # 任一探针读出 ≥6 字中文 → 视为烧录字幕
    return any(len(re.findall(r"[\u4e00-\u9fff]", t)) >= 6 for t in probe_samples)


def _template_slot_meta(template: Template) -> tuple[int, float]:
    return len(template.slots or []), float(getattr(template, "duration", 0) or 0)


def _should_force_vocal_sep(template: Template, req_force: bool) -> bool:
    """剪映式：已有分离音频时不因精识别重复跑 Demucs。"""
    if not req_force:
        return False
    return not has_cached_whisper_source(template.file_path or "")


def _should_rebuild_whisper(template: Template) -> bool:
    """仅当无缓存或缓存异常时才整段 Whisper；精识别复用 fast 结果。"""
    existing = getattr(template, "segments_json", None) or []
    slot_count, media_duration = _template_slot_meta(template)
    if not existing:
        return True
    return segments_need_rebuild(existing, media_duration, slot_count)


@router.post("/recognize")
async def recognize_subtitle(file: UploadFile = File(...)):
    import os
    import uuid

    content = await file.read()
    ext = validate_upload_file(file.filename, len(content))

    safe_filename = f"{uuid.uuid4()}{ext}"
    temp_path = f"storage/temp/{safe_filename}"
    srt_path = temp_path.replace(ext, ".srt")

    try:
        with open(temp_path, "wb") as f:
            f.write(content)

        loop = asyncio.get_event_loop()
        segments = await loop.run_in_executor(_executor, transcribe, temp_path)
        generate_srt(segments, srt_path)

        return {
            "success": True,
            "segments": segments,
            "srt_path": srt_path,
            "total_count": len(segments),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail="语音识别失败") from exc
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@router.post("/recognize-slot")
async def recognize_slot_subtitle(req: RecognizeSlotRequest, db: Session = Depends(get_db)):
    """识别槽位字幕：剪映式整段 ASR + 画面 OCR + 融合。"""
    if req.slot_end <= req.slot_start:
        raise HTTPException(status_code=400, detail="槽位时间范围无效")

    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    resolved_range = _resolve_batch_slot_range(
        template,
        {
            "slot_id": req.slot_id,
            "slot_start": req.slot_start,
            "slot_end": req.slot_end,
        },
    )
    slot_start, slot_end = resolved_range if resolved_range else (req.slot_start, req.slot_end)

    status = getattr(template, "processing_status", "ready")
    if status == "processing":
        raise HTTPException(status_code=400, detail="模板仍在分析中，请稍后再试")

    cached = _find_cached_slot_subtitle(template, slot_start, slot_end)
    quality_mode = req.quality or is_subtitle_quality_mode()
    if cached and not req.force and not quality_mode:
        return {
            "success": True,
            "slot_id": req.slot_id,
            "subtitle_text": cached["subtitle_text"],
            "subtitle_segments": cached["subtitle_segments"],
            "segment_count": len(cached["subtitle_segments"]),
            "cached": True,
        }

    segments_json = None
    slot_count, media_duration = _template_slot_meta(template)

    rec_mode, prefer_visual, skip_whisper = _resolve_subtitle_flow(
        req.mode,
        template,
        [SlotSpec(req.slot_id, slot_start, slot_end)],
    )

    if _should_run_asr(req.mode, skip_whisper):
        try:
            ensure_vocal_and_bgm_tracks(
                template.file_path or "",
                force=_should_force_vocal_sep(template, req.force),
            )
        except Exception as exc:
            print(f"人声分离失败: {exc}")

    if _should_run_asr(req.mode, skip_whisper):
        rebuild = _should_rebuild_whisper(template)
        segments_json = ensure_template_segments_json(
            template,
            db,
            force=rebuild or (quality_mode and req.force),
            fast_batch=not quality_mode or not rebuild,
            speech_mode=(rec_mode == "speech"),
        )

    try:
        loop = asyncio.get_event_loop()
        outcome = await loop.run_in_executor(
            _executor,
            lambda: recognize_single_slot_capcut(
                template,
                slot_start,
                slot_end,
                req.mode,
                segments_json,
                [],
                prefer_visual,
                skip_whisper,
                quality_mode,
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="字幕识别失败") from exc

    segments = outcome.segments
    source = outcome.source
    subtitle_text = outcome.subtitle_text
    slot_idx = _find_slot_index(list(template.slots or []), slot_start, slot_end, req.slot_id)

    if outcome.status == "matched" and subtitle_text:
        _persist_slot_subtitle(
            template,
            slot_start,
            slot_end,
            subtitle_text,
            segments,
            db,
            slot_id=req.slot_id,
            source=source,
        )
        updated_slot = (template.slots or [])[slot_idx] if slot_idx is not None else {}
        if isinstance(updated_slot, dict):
            subtitle_text = str(updated_slot.get("subtitle_text") or subtitle_text)
            segments = updated_slot.get("subtitle_segments") or segments
    elif outcome.status in ("no_speech", "no_overlap", "filtered"):
        _persist_slot_subtitle(
            template,
            slot_start,
            slot_end,
            "",
            segments,
            db,
            slot_id=req.slot_id,
            source=source,
            enrich_scene=False,
        )
        updated_slot = (template.slots or [])[slot_idx] if slot_idx is not None else {}
    else:
        updated_slot = {}

    row = _slot_row_from_outcome(outcome)
    row.pop("_slot_start", None)
    row.pop("_slot_end", None)
    speech_extra = _template_speech_payload(template, segments_json) if rec_mode == "speech" else {}
    summary = _build_speech_summary([row], template, rec_mode) if rec_mode == "speech" else None

    response = {"cached": False, **row}
    if outcome.status == "error":
        response["error"] = outcome.error or outcome.reason
    if isinstance(updated_slot, dict) and outcome.status == "matched":
        response.update({
            "subtitle_quality": updated_slot.get("subtitle_quality"),
            "subtitle_status_reason": updated_slot.get("subtitle_status_reason"),
            "subtitle_duplicate": bool(updated_slot.get("subtitle_duplicate")),
            **_scene_fields_from_slot(updated_slot),
        })
    response.update(speech_extra)
    if summary:
        response["summary"] = summary
    return response


@router.get("/status/{template_id}")
def get_subtitle_status(template_id: str, db: Session = Depends(get_db)):
    """槽位级字幕就绪情况、来源与失败原因。"""
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return build_template_subtitle_status(template)


@router.post("/recognize-captions")
async def recognize_captions(req: RecognizeCaptionsRequest, db: Session = Depends(get_db)):
    """剪映式识别字幕：整段 ASR → subtitleClips（不依赖画面 slot）。"""
    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    status = getattr(template, "processing_status", "ready")
    if status == "processing":
        raise HTTPException(status_code=400, detail="模板仍在分析中，请稍后再试")

    rec_mode = resolve_recognition_mode(req.mode)
    if rec_mode != "speech":
        raise HTTPException(status_code=400, detail="剪映式字幕轨仅支持口播 speech 模式")

    from utils.security import resolve_storage_path

    resolved = resolve_storage_path(template.file_path or "")
    if resolved and os.path.isfile(resolved):
        from services.media_probe import has_audio_stream

        if not has_audio_stream(resolved):
            raise HTTPException(status_code=400, detail="模板视频无音轨，无法进行口播识别")

    if not has_cached_whisper_source(template.file_path or ""):
        try:
            ensure_vocal_and_bgm_tracks(template.file_path or "", force=False)
        except Exception as exc:
            print(f"[subtitle_clip] 人声分离失败: {exc}")

    quality_mode = req.quality or is_subtitle_quality_mode()
    rebuild = _should_rebuild_whisper(template) if req.force else False
    segments_json = ensure_template_segments_json(
        template,
        db,
        force=rebuild or req.force,
        fast_batch=not quality_mode or not rebuild,
        speech_mode=True,
    )
    if not segments_json:
        raise HTTPException(status_code=400, detail="未检测到清晰口播字幕")

    from services.subtitle_clip_planner import persist_template_subtitle_clips
    from services.subtitle_config import get_subtitle_config, is_caption_slot_strategy

    cfg = get_subtitle_config()
    if is_caption_slot_strategy(cfg.cut_strategy):
        from services.caption_slot_builder import run_caption_recognition_pipeline
        from utils.security import resolve_storage_path

        resolved_path = resolve_storage_path(template.file_path or "") or template.file_path or ""
        template_dir = os.path.dirname(resolved_path) if resolved_path else ""
        rec = run_caption_recognition_pipeline(
            req.template_id,
            resolved_path,
            template_dir,
            spoken_segments=segments_json,
            duration=float(getattr(template, "duration", 0) or 0),
            config=cfg,
            quality_ocr=quality_mode,
        )
        clips = rec.get("validated_caption_clips") or rec.get("sentence_clips") or []
        from services.tts.tts_pipeline import ensure_clip_timeline_fields

        clips = ensure_clip_timeline_fields(clips)
        spoken_out = rec.get("spoken_segments") or segments_json
        template.subtitle_clips_json = clips
        template.segments_json = spoken_out
        template.pipeline_stage = "captions_recognized"
        flag_modified(template, "subtitle_clips_json")
        flag_modified(template, "segments_json")
        db.commit()
        db.refresh(template)
        rec_debug = rec.get("caption_recognition_debug") or {}
        needs_review = int(rec.get("needs_review_count") or rec_debug.get("needsReviewCount") or 0)
        from services.tts.tts_pipeline import build_pipeline_debug, get_timeline_timing_mode

        pipeline_debug = build_pipeline_debug(
            clips=clips,
            tts_segments=getattr(template, "tts_segments_json", []) or [],
            slots=getattr(template, "slots", []) or [],
            pipeline_stage="captions_recognized",
            voice_id=getattr(template, "voice_id", "") or "",
            timing_mode=getattr(template, "timeline_timing_mode", "") or get_timeline_timing_mode(),
        )
        asr_clips = rec.get("asr_clips") or []
        response: dict = {
            "success": True,
            "subtitleClipCount": len(clips),
            "validatedCaptionClipCount": len(clips),
            "rawAsrClipCount": len(asr_clips),
            "needsReviewCount": needs_review,
            "cutStrategy": "caption_slot",
            "phase": "recognize_only",
            "summary": {
                "mode": rec_mode,
                "cutStrategy": "caption_slot",
                "subtitleClipCount": len(clips),
                "validatedCaptionClipCount": len(clips),
                "rawAsrClipCount": len(asr_clips),
                "needsReviewCount": needs_review,
                "rawAsrSegmentCount": len(segments_json or []),
                "finalAsrSegmentCount": len(spoken_out or []),
                "ocrSplitCount": rec_debug.get("ocrSplitCount", 0),
                "ocrMergeCount": rec_debug.get("ocrMergeCount", 0),
            },
            "validatedCaptionClips": clips,
            "asrClips": asr_clips,
            "captionRecognitionDebug": rec_debug,
            "pipelineDebug": pipeline_debug,
        }
        response.update(_template_speech_payload(template, spoken_out))
        return response

    clips, clip_debug = persist_template_subtitle_clips(template, segments_json, db=db)

    response: dict = {
        "success": True,
        "subtitleClipCount": len(clips),
        "summary": {
            "mode": rec_mode,
            "subtitleClipCount": len(clips),
            "rawAsrSegmentCount": len(segments_json or []),
            "finalAsrSegmentCount": len(segments_json or []),
        },
    }
    response.update(_template_speech_payload(template, segments_json))
    return response


@router.post("/apply-caption-slots")
async def apply_caption_slots(req: ApplyCaptionSlotsRequest, db: Session = Depends(get_db)):
    """兼容旧路径：等同 AI 一键分割画面（ai-split-by-captions）。"""
    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    from services.caption_clip_quality import attach_quality_to_clips
    from services.caption_slot_builder import ai_split_by_captions
    from services.slot_helpers import slots_will_be_overwritten_by_ai_split
    from services.tts.tts_pipeline import build_pipeline_debug, get_timeline_timing_mode
    from utils.security import resolve_storage_path

    clips = req.subtitle_clips if req.subtitle_clips is not None else (template.subtitle_clips_json or [])
    clips = attach_quality_to_clips(list(clips or []))
    if not clips:
        raise HTTPException(status_code=400, detail="请先识别字幕")

    resolved_path = resolve_storage_path(template.file_path or "") or template.file_path or ""
    if not resolved_path or not os.path.isfile(resolved_path):
        raise HTTPException(status_code=400, detail="模板视频不存在")

    existing_slots = list(template.slots or [])
    if slots_will_be_overwritten_by_ai_split(existing_slots) and not req.overwrite_slots:
        raise HTTPException(status_code=409, detail="AI 一键分割画面会覆盖当前画面槽，请确认后重试")

    vision = getattr(template, "ai_vision_json", None) or {}
    visual_suggestions = vision.get("visualCutSuggestions") if isinstance(vision, dict) else None
    tts_segments = getattr(template, "tts_segments_json", []) or []
    timing_mode = getattr(template, "timeline_timing_mode", "") or None

    try:
        applied = ai_split_by_captions(
            req.template_id,
            resolved_path,
            clips,
            duration=float(getattr(template, "duration", 0) or 0),
            tts_segments=tts_segments,
            timing_mode=timing_mode,
            merge_short_fragments=req.merge_short_fragments,
            use_tts_aligned_time=req.use_tts_aligned_time,
            existing_slots=existing_slots,
            overwrite_slots=req.overwrite_slots,
            visual_suggestions=visual_suggestions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    slots = applied.get("slots") or []
    template.slots = slots
    template.slot_count = len(slots)
    template.subtitle_clips_json = applied.get("sentence_clips") or clips
    template.pipeline_stage = "slots_applied"
    flag_modified(template, "slots")
    flag_modified(template, "subtitle_clips_json")
    db.commit()
    db.refresh(template)

    pipeline_debug = build_pipeline_debug(
        clips=template.subtitle_clips_json,
        tts_segments=tts_segments,
        slots=slots,
        pipeline_stage="slots_applied",
        voice_id=getattr(template, "voice_id", "") or "",
        timing_mode=timing_mode or get_timeline_timing_mode(),
    )

    return {
        "success": True,
        "slotCount": len(slots),
        "subtitleClipCount": len(clips),
        "slots": slots,
        "subtitleClips": template.subtitle_clips_json,
        "cutStrategy": "caption_slot",
        "phase": "apply_slots",
        "aiSplitDebug": applied.get("ai_split_debug") or {},
        "captionSlotDebug": applied.get("ai_split_debug") or {},
        "oneCaptionOneShotDebug": applied.get("oneCaptionOneShotDebug") or {},
        "overwriteWarning": applied.get("overwrite_warning"),
        "reviewWarning": applied.get("review_warning"),
        "ttsWarning": applied.get("tts_warning"),
        "pipelineDebug": pipeline_debug,
        "summary": applied.get("summary") or {},
    }


@router.post("/subtitle-clips")
async def update_subtitle_clips(req: UpdateSubtitleClipsRequest, db: Session = Depends(get_db)):
    """保存用户编辑后的 subtitleClips。"""
    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    from services.caption_clip_quality import attach_quality_to_clips

    clips = attach_quality_to_clips(list(req.subtitle_clips or []))
    if not clips:
        raise HTTPException(status_code=400, detail="subtitle_clips 不能为空")

    template.subtitle_clips_json = clips
    flag_modified(template, "subtitle_clips_json")
    db.commit()
    db.refresh(template)

    needs_review = sum(
        1 for c in clips if isinstance(c.get("quality"), dict) and c["quality"].get("needsReview")
    )
    return {
        "success": True,
        "subtitleClipCount": len(clips),
        "needsReviewCount": needs_review,
        "subtitleClips": clips,
    }


@router.post("/recognize-slot-batch")
async def recognize_slot_subtitle_batch(req: BatchRecognizeSlotRequest, db: Session = Depends(get_db)):
    """批量识别：剪映式整段 ASR + 全槽 OCR + 多模态融合。"""
    if not req.slots:
        raise HTTPException(status_code=400, detail="slots 不能为空")

    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    status = getattr(template, "processing_status", "ready")
    if status == "processing":
        raise HTTPException(status_code=400, detail="模板仍在分析中，请稍后再试")

    slot_count = len(template.slots or [])
    media_duration = float(getattr(template, "duration", 0) or 0)

    from utils.security import resolve_storage_path

    resolved = resolve_storage_path(template.file_path or "")

    specs: list[SlotSpec] = []
    invalid_results: list[dict] = []
    for item in req.slots:
        if not isinstance(item, dict):
            invalid_results.append(_invalid_slot_row(None, reason="槽位参数无效"))
            continue
        slot_id = item.get("slot_id")
        resolved_range = _resolve_batch_slot_range(template, item)
        if not resolved_range:
            invalid_results.append(_invalid_slot_row(slot_id, reason="时间范围无效"))
            continue
        slot_start, slot_end = resolved_range
        if slot_end <= slot_start:
            invalid_results.append(
                _invalid_slot_row(slot_id, start=slot_start, end=slot_end, reason="时间范围无效")
            )
            continue
        specs.append(SlotSpec(slot_id, slot_start, slot_end))

    rec_mode, prefer_visual, skip_whisper = _resolve_subtitle_flow(req.mode, template, specs)
    if rec_mode == "speech":
        print(f"模板 {template.id} 口播模式：ASR 主导，OCR 不参与融合")
    elif prefer_visual:
        print(f"模板 {template.id} 烧录字幕/legacy：OCR 路径")

    quality_mode = req.quality or is_subtitle_quality_mode()
    segments_json = None
    if _should_run_asr(req.mode, skip_whisper):
        if not has_cached_whisper_source(template.file_path or ""):
            try:
                ensure_vocal_and_bgm_tracks(template.file_path or "", force=False)
            except Exception as exc:
                print(f"批量识别前人声分离失败: {exc}")
        elif _should_force_vocal_sep(template, req.force):
            try:
                ensure_vocal_and_bgm_tracks(template.file_path or "", force=True)
            except Exception as exc:
                print(f"批量识别前人声分离失败: {exc}")

        source_path = resolve_vocal_source_path(template.file_path or "", force=False)
        if not source_path and req.mode in ("audio", "speech") and rec_mode != "speech":
            raise HTTPException(status_code=400, detail="模板缺少音频源")

        rebuild = _should_rebuild_whisper(template)
        segments_json = ensure_template_segments_json(
            template,
            db,
            force=rebuild,
            fast_batch=not quality_mode or not rebuild,
            speech_mode=(rec_mode == "speech"),
        )
        if rec_mode == "speech" and segments_json:
            from services.subtitle_clip_planner import persist_template_subtitle_clips

            persist_template_subtitle_clips(template, segments_json, db=db)

    if req.mode in ("visual", "burned", "auto") and (not resolved or not os.path.isfile(resolved)):
        if req.mode in ("visual", "burned"):
            raise HTTPException(status_code=400, detail="模板视频不存在")
    elif rec_mode == "speech":
        from services.media_probe import has_audio_stream

        if resolved and os.path.isfile(resolved) and not has_audio_stream(resolved):
            raise HTTPException(status_code=400, detail="模板视频无音轨，无法进行口播识别")
    elif req.mode in ("audio", "speech"):
        source_path = resolve_vocal_source_path(template.file_path or "", force=False)
        if not source_path:
            raise HTTPException(status_code=400, detail="模板缺少音频源")

    loop = asyncio.get_event_loop()
    batch_out: list = []
    if specs:
        batch_out = await loop.run_in_executor(
            _executor,
            lambda: recognize_all_slots_capcut(
                template,
                specs,
                req.mode,
                segments_json,
                prefer_visual,
                skip_whisper,
                quality_mode,
            ),
        )

    results = list(invalid_results)
    pending_persist: list[tuple[float, float, str, list, Optional[Union[str, int]], str]] = []

    for spec, outcome in zip(specs, batch_out):
        row = _slot_row_from_outcome(outcome)
        results.append(row)

        if outcome.status == "matched" and outcome.subtitle_text:
            pending_persist.append(
                (
                    spec.slot_start,
                    spec.slot_end,
                    outcome.subtitle_text,
                    outcome.segments,
                    spec.slot_id,
                    outcome.source,
                )
            )
        elif outcome.status in ("no_speech", "no_overlap", "filtered"):
            pending_persist.append(
                (spec.slot_start, spec.slot_end, "", outcome.segments, spec.slot_id, outcome.source)
            )

    for slot_start, slot_end, subtitle_text, segments, slot_id, source in pending_persist:
        _persist_slot_subtitle(
            template,
            slot_start,
            slot_end,
            subtitle_text,
            segments,
            db,
            slot_id=slot_id,
            commit=False,
            enrich_scene=bool(subtitle_text.strip()),
            source=source,
        )
    if pending_persist:
        db.commit()
        db.refresh(template)
        slots_after = list(template.slots or [])
        for row in results:
            if row.get("status") != "matched":
                row.pop("_slot_start", None)
                row.pop("_slot_end", None)
                continue
            idx = _find_slot_index(
                slots_after,
                float(row.pop("_slot_start", 0)),
                float(row.pop("_slot_end", 0)),
                row.get("slot_id"),
            )
            if idx is not None and isinstance(slots_after[idx], dict):
                slot = slots_after[idx]
                row["subtitle_text"] = slot.get("subtitle_text") or row.get("subtitle_text")
                row["subtitle_segments"] = slot.get("subtitle_segments") or row.get("subtitle_segments")
                row["subtitle_quality"] = slot.get("subtitle_quality")
                row["subtitle_status_reason"] = slot.get("subtitle_status_reason")
                row["subtitle_duplicate"] = slot.get("subtitle_duplicate")
                row.update(_scene_fields_from_slot(slot))
            else:
                row.pop("_slot_start", None)
                row.pop("_slot_end", None)

    matched_count = sum(1 for r in results if r.get("status") == "matched")
    for row in results:
        row.pop("_slot_start", None)
        row.pop("_slot_end", None)
        row.pop("_include_scene", None)
    response: dict = {
        "success": True,
        "results": results,
        "recognized_count": matched_count,
        "total_count": len(results),
    }
    if rec_mode == "speech":
        response.update(_template_speech_payload(template, segments_json))
        response["summary"] = _build_speech_summary(results, template, rec_mode)
        response["slotDiagnostics"] = [
            {
                "slotId": r.get("slotId"),
                "start": r.get("start"),
                "end": r.get("end"),
                "status": r.get("status"),
                "reason": r.get("reason"),
                "linkedSubtitleSegmentIds": r.get("linkedSubtitleSegmentIds") or [],
            }
            for r in results
        ]
    return response


class AnalyzeSlotSceneRequest(BaseModel):
    template_id: str
    slot_start: float = Field(ge=0)
    slot_end: float = Field(gt=0)
    slot_id: Optional[Union[str, int]] = None


@router.post("/analyze-slot-scene")
async def analyze_slot_subtitle_scene(req: AnalyzeSlotSceneRequest, db: Session = Depends(get_db)):
    """对已识别字幕的槽位重新分析花字特效与字幕-画面对齐。"""
    if req.slot_end <= req.slot_start:
        raise HTTPException(status_code=400, detail="槽位时间范围无效")

    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    if not template.file_path or not os.path.isfile(template.file_path):
        raise HTTPException(status_code=400, detail="模板视频不存在")

    resolved_range = _resolve_batch_slot_range(
        template,
        {"slot_id": req.slot_id, "slot_start": req.slot_start, "slot_end": req.slot_end},
    )
    slot_start, slot_end = resolved_range if resolved_range else (req.slot_start, req.slot_end)

    slots = list(template.slots or [])
    idx = _find_slot_index(slots, slot_start, slot_end, req.slot_id)
    if idx is None:
        raise HTTPException(status_code=404, detail="未找到对应槽位")

    slot = slots[idx]
    subtitle_text = str(slot.get("subtitle_text") or "").strip()
    segments = list(slot.get("subtitle_segments") or [])
    if not subtitle_text and not segments:
        raise HTTPException(status_code=400, detail="该槽位尚无字幕，请先识别字幕")

    if not subtitle_text:
        subtitle_text = " ".join(str(s.get("text", "")) for s in segments if isinstance(s, dict)).strip()

    loop = asyncio.get_event_loop()
    work_dir = os.path.join(os.path.dirname(template.file_path), "subtitle_scene")
    try:
        enriched = await loop.run_in_executor(
            _executor,
            lambda: enrich_slot_after_subtitle_recognition(
                template.file_path,
                slot,
                subtitle_text,
                segments,
                index=idx,
                work_dir=work_dir,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"字幕场景分析失败: {exc}") from exc

    scene_patch = {k: enriched[k] for k in _SCENE_ENRICH_KEYS if k in enriched}
    slots[idx] = {
        **slot,
        "subtitle_text": enriched.get("subtitle_text") or subtitle_text,
        "subtitle_segments": enriched.get("subtitle_segments") or segments,
        **scene_patch,
    }
    template.slots = slots
    flag_modified(template, "slots")
    db.commit()
    db.refresh(template)

    return {
        "success": True,
        "slot_id": req.slot_id,
        "subtitle_text": slots[idx].get("subtitle_text") or subtitle_text,
        "subtitle_segments": slots[idx].get("subtitle_segments") or segments,
        **_scene_fields_from_slot(slots[idx]),
    }


@router.post("/analyze-all-slot-scenes")
async def analyze_all_slot_subtitle_scenes(req: BatchRecognizeSlotRequest, db: Session = Depends(get_db)):
    """批量分析已有字幕槽位的花字特效与画面对齐。"""
    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    if not template.file_path or not os.path.isfile(template.file_path):
        raise HTTPException(status_code=400, detail="模板视频不存在")

    slots = list(template.slots or [])
    if not slots:
        raise HTTPException(status_code=400, detail="模板尚无槽位")

    work_dir = os.path.join(os.path.dirname(template.file_path), "subtitle_scene")
    loop = asyncio.get_event_loop()
    try:
        enriched_slots = await loop.run_in_executor(
            _executor,
            lambda: enrich_slots_subtitle_scene(
                template.file_path,
                slots,
                work_dir=work_dir,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"批量场景分析失败: {exc}") from exc

    template.slots = enriched_slots
    flag_modified(template, "slots")
    db.commit()
    db.refresh(template)

    analyzed = sum(
        1
        for s in enriched_slots
        if isinstance(s, dict) and s.get("subtitle_scene_match") is not None
    )
    return {
        "success": True,
        "template_id": req.template_id,
        "analyzed_count": analyzed,
        "slots": enriched_slots,
    }
