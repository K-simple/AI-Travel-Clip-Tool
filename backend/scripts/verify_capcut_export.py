"""重启后完整验证：剪映草稿导出 + 字幕动画字段。"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

API = "http://127.0.0.1:8000"


def _get(path: str, timeout: float = 5.0) -> dict:
    req = urllib.request.Request(f"{API}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(path: str, body: dict, timeout: float = 600.0) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_for_services(max_wait_sec: int = 90) -> None:
    deadline = time.time() + max_wait_sec
    last_err = ""
    while time.time() < deadline:
        try:
            capcut = _get("/api/export/capcut-status", timeout=3)
            if capcut.get("enabled") and capcut.get("reachable"):
                print(f"OK backend + CapCut Mate: {capcut}")
                return
            last_err = f"capcut-status: {capcut}"
        except Exception as exc:
            last_err = str(exc)
        time.sleep(2)
    raise RuntimeError(f"服务未就绪（{max_wait_sec}s）: {last_err}")


def pick_export_project() -> tuple[str, str, list]:
    from models.database import Project, SessionLocal, Template

    db = SessionLocal()
    try:
        projects = db.query(Project).order_by(Project.updated_at.desc()).all()
        best = None
        best_score = -1
        for project in projects:
            template = db.query(Template).filter(Template.id == project.template_id).first()
            if not template:
                continue
            timeline = list(project.timeline or [])
            if not timeline:
                continue
            clips = list(template.subtitle_clips_json or [])
            score = 0
            score += sum(
                1
                for s in timeline
                if isinstance(s, dict)
                and (s.get("asset_id") or s.get("asset_file_path") or s.get("segment_file_path"))
            )
            score += sum(
                1
                for c in clips
                if isinstance(c, dict) and isinstance(c.get("subtitle_style"), dict)
            )
            score += sum(
                1
                for s in timeline
                if isinstance(s, dict)
                and (
                    isinstance(s.get("subtitle_style"), dict)
                    or (
                        isinstance(s.get("subtitle_segments"), list)
                        and s["subtitle_segments"]
                        and isinstance(s["subtitle_segments"][0], dict)
                        and s["subtitle_segments"][0].get("style")
                    )
                )
            )
            if score > best_score:
                best_score = score
                best = (project.id, template.id, timeline, len(clips), score)
        if not best:
            raise RuntimeError("数据库中没有可导出的项目（timeline 为空）")
        project_id, template_id, timeline, clip_count, score = best
        print(
            f"选用项目 project_id={project_id} template_id={template_id} "
            f"slots={len(timeline)} caption_clips={clip_count} score={score}"
        )
        return project_id, template_id, timeline
    finally:
        db.close()


def verify_caption_payloads(project_id: str) -> dict:
    from models.database import Project, SessionLocal, Template
    from services.capcut_draft_exporter import (
        _collect_captions_for_slot,
        _merge_timeline_subtitles,
        _probe_video_size,
    )
    from services.effects_catalog import merge_auto_effects_into_slot
    from services.subtitle_style_analyzer import (
        ensure_timeline_styles_from_template_video,
        style_to_capcut_caption_item,
    )
    from utils.security import ensure_storage_subpath

    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        template = db.query(Template).filter(Template.id == project.template_id).first()
        export_timeline = _merge_timeline_subtitles(list(project.timeline or []), template)
        template_video = ""
        if template.file_path:
            try:
                template_video = ensure_storage_subpath(template.file_path)
            except Exception:
                template_video = template.file_path or ""
        height = 1920
        if template_video and os.path.isfile(template_video):
            native = _probe_video_size(template_video)
            if native:
                height = native[1]
            export_timeline = ensure_timeline_styles_from_template_video(
                export_timeline,
                template_video,
                os.path.join("storage", "temp", "verify_subtitle_styles"),
                frame_height=height,
            )
        captions = []
        cursor = 0.0
        for slot in export_timeline:
            if not isinstance(slot, dict):
                continue
            dur = float(slot.get("duration") or max(0.1, float(slot.get("end", 0)) - float(slot.get("start", 0))))
            caption_slot = merge_auto_effects_into_slot(slot)
            caps = _collect_captions_for_slot(
                caption_slot,
                timeline_start_us=int(cursor * 1_000_000),
                clip_duration_sec=dur,
                source_range_start=float(slot.get("clip_start") or slot.get("start") or 0),
            )
            captions.extend(caps)
            cursor += dur

        with_anim_in = 0
        with_anim_out = 0
        with_color = 0
        capcut_items = []
        for cap in captions:
            style = cap.get("style") if isinstance(cap.get("style"), dict) else {}
            if style.get("animation_in"):
                with_anim_in += 1
            if style.get("animation_out"):
                with_anim_out += 1
            color = str(style.get("text_color") or "").lower()
            if color and color not in ("#ffffff", "#fff", "white"):
                with_color += 1
            clip_dur = max(1, int(cap["end"]) - int(cap["start"]))
            item = style_to_capcut_caption_item(cap, style, clip_duration_us=clip_dur)
            capcut_items.append(item)

        with_jy_in = sum(1 for item in capcut_items if item.get("in_animation"))
        return {
            "caption_count": len(captions),
            "with_animation_in": with_anim_in,
            "with_animation_out": with_anim_out,
            "with_non_white_color": with_color,
            "with_jianying_in_animation": with_jy_in,
            "sample": capcut_items[:2],
        }
    finally:
        db.close()


def main() -> int:
    print("=== 等待服务就绪 ===")
    wait_for_services()

    print("\n=== 选择导出项目 ===")
    project_id, template_id, _timeline = pick_export_project()

    print("\n=== 预检字幕动画 payload ===")
    preview = verify_caption_payloads(project_id)
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    if preview["caption_count"] == 0:
        print("WARN: 无字幕条目，导出可能缺少文本轨")
    if preview["with_jianying_in_animation"] == 0:
        print("WARN: 预检未发现剪映 in_animation，将仍尝试导出")

    print("\n=== 调用 POST /api/export/capcut-draft ===")
    result = _post(
        "/api/export/capcut-draft",
        {
            "project_id": project_id,
            "template_id": template_id,
            "add_subtitles": True,
            "capcut_export_mode": "filled",
            "include_template_slots": True,
        },
        timeout=900,
    )
    print(json.dumps(
        {
            "success": result.get("success"),
            "clips_count": result.get("clips_count"),
            "draft_url": result.get("draft_url"),
            "draft_id": result.get("draft_id"),
            "warnings": result.get("warnings"),
            "message": result.get("message"),
        },
        ensure_ascii=False,
        indent=2,
    ))

    if not result.get("success"):
        return 1
    if result.get("warnings"):
        print(f"导出完成但有 {len(result['warnings'])} 条警告")
    draft_id = result.get("draft_id") or ""
    if draft_id:
        print(f"\n草稿 ID: {draft_id}")
        print(f"打开链接: {result.get('draft_url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
