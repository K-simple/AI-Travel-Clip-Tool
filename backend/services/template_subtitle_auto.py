"""模板 intake 完成后后台批量字幕（默认口播 speech，OCR 仅 burned）。"""

from __future__ import annotations

import threading
from typing import Any

from models.database import SessionLocal, Template
from services.processing_config import AUTO_SUBTITLE_AFTER_INTAKE, is_subtitle_quality_mode
from services.slot_subtitle import (
    ensure_template_segments_json,
    has_cached_whisper_source,
    segments_need_rebuild,
    slot_dict_source_range,
)
from services.subtitle_config import resolve_recognition_mode
from services.subtitle_pipeline import SlotSpec, recognize_all_slots_capcut
from services.vocal_separator import ensure_vocal_and_bgm_tracks, resolve_vocal_source_path

_running: set[str] = set()
_lock = threading.Lock()

_INTAKE_SKIP_RATIO = 0.5


def _intake_subtitles_sufficient(template: Template) -> tuple[bool, int, int]:
    slots = [s for s in (template.slots or []) if isinstance(s, dict)]
    if not slots:
        return False, 0, 0
    ready = sum(1 for s in slots if str(s.get("subtitle_text") or "").strip())
    need = max(1, int(len(slots) * _INTAKE_SKIP_RATIO))
    return ready >= need, ready, len(slots)


def _specs_needing_subtitle(template: Template) -> list[SlotSpec]:
    """仅返回 intake 后仍缺字幕的槽位。"""
    specs: list[SlotSpec] = []
    for slot in template.slots or []:
        if not isinstance(slot, dict):
            continue
        if str(slot.get("subtitle_text") or "").strip():
            continue
        slot_id = slot.get("slot_id") or slot.get("id")
        start, end = slot_dict_source_range(slot)
        if end <= start:
            continue
        specs.append(SlotSpec(slot_id, start, end))
    return specs


def _build_specs(template: Template) -> list[SlotSpec]:
    specs: list[SlotSpec] = []
    for slot in template.slots or []:
        if not isinstance(slot, dict):
            continue
        slot_id = slot.get("slot_id") or slot.get("id")
        start, end = slot_dict_source_range(slot)
        if end <= start:
            continue
        specs.append(SlotSpec(slot_id, start, end))
    return specs


def run_auto_subtitle_batch(template_id: str) -> dict[str, Any]:
    """后台批量字幕：默认 speech，用户未选 burned 时不走 OCR。"""
    from routers.subtitle import _persist_slot_subtitle

    db = SessionLocal()
    try:
        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            return {"success": False, "error": "模板不存在"}

        quality_mode = is_subtitle_quality_mode()
        sufficient, ready, total = _intake_subtitles_sufficient(template)
        if sufficient and not quality_mode:
            print(f"自动字幕跳过 [{template_id}]: intake 已有 {ready}/{total}")
            return {
                "success": True,
                "recognized_count": ready,
                "total_count": total,
                "skipped": True,
            }

        specs = _specs_needing_subtitle(template) if not quality_mode else _build_specs(template)
        if not specs:
            return {"success": True, "recognized_count": ready, "total_count": total}

        rec_mode = resolve_recognition_mode("auto")
        prefer_visual = rec_mode == "burned"
        skip_whisper = rec_mode == "burned"
        api_mode = "burned" if rec_mode == "burned" else "speech"

        segments_json = None
        if not skip_whisper:
            if not has_cached_whisper_source(template.file_path or ""):
                try:
                    ensure_vocal_and_bgm_tracks(template.file_path or "", force=False)
                except Exception as exc:
                    print(f"自动字幕前人声分离失败: {exc}")

            source_path = resolve_vocal_source_path(template.file_path or "", force=False)
            if source_path:
                existing = getattr(template, "segments_json", None) or []
                media_duration = float(getattr(template, "duration", 0) or 0)
                slot_count = len(template.slots or [])
                need_rebuild = segments_need_rebuild(existing, media_duration, slot_count)
                segments_json = ensure_template_segments_json(
                    template,
                    db,
                    force=need_rebuild,
                    fast_batch=not quality_mode,
                    speech_mode=(rec_mode == "speech"),
                )

        print(f"自动字幕 [{template_id}] mode={api_mode} rec={rec_mode}")
        batch_out = recognize_all_slots_capcut(
            template,
            specs,
            api_mode,
            segments_json,
            prefer_visual,
            skip_whisper=skip_whisper,
            quality_mode=quality_mode,
        )

        ok = ready
        pending = 0
        for spec, outcome in zip(specs, batch_out):
            if outcome.status == "error":
                print(f"自动字幕槽位失败 {spec.slot_id}: {outcome.error or outcome.reason}")
                continue
            subtitle_text = outcome.subtitle_text
            if not subtitle_text and outcome.status != "matched":
                _persist_slot_subtitle(
                    template,
                    spec.slot_start,
                    spec.slot_end,
                    "",
                    outcome.segments,
                    db,
                    slot_id=spec.slot_id,
                    commit=False,
                    enrich_scene=False,
                    source=outcome.source,
                )
                pending += 1
                if pending >= 3:
                    db.commit()
                    db.refresh(template)
                    pending = 0
                continue
            if not subtitle_text:
                continue
            _persist_slot_subtitle(
                template,
                spec.slot_start,
                spec.slot_end,
                subtitle_text,
                outcome.segments,
                db,
                slot_id=spec.slot_id,
                commit=False,
                enrich_scene=False,
                source=outcome.source,
            )
            ok += 1
            pending += 1
            if pending >= 3:
                db.commit()
                db.refresh(template)
                pending = 0

        if pending:
            db.commit()
            db.refresh(template)

        print(f"模板自动字幕完成 [{template_id}]: {ok}/{len(specs)}")
        return {"success": True, "recognized_count": ok, "total_count": len(specs)}
    except Exception as exc:
        print(f"模板自动字幕失败 [{template_id}]: {exc}")
        return {"success": False, "error": str(exc)}
    finally:
        db.close()
        with _lock:
            _running.discard(template_id)


def queue_auto_subtitle_batch(template_id: str) -> None:
    if not AUTO_SUBTITLE_AFTER_INTAKE:
        return
    with _lock:
        if template_id in _running:
            return
        _running.add(template_id)

    def _worker() -> None:
        try:
            run_auto_subtitle_batch(template_id)
        except Exception as exc:
            print(f"自动字幕队列失败 [{template_id}]: {exc}")
            with _lock:
                _running.discard(template_id)

    threading.Thread(target=_worker, daemon=True, name=f"subtitle-auto-{template_id[:8]}").start()


def is_subtitle_batch_running(template_id: str) -> bool:
    with _lock:
        return template_id in _running
