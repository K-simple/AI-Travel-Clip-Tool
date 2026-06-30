import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from models.database import Asset, Project, Template, get_db
from services.match_strategy import MatchStrategy
from services.matcher import MatchWeights, match_slots
from services.smart_matcher import enrich_timeline_for_matching, slots_missing_understanding
from utils.edl_timeline import slots_timeline_to_edl

router = APIRouter()


def expand_segments_for_matching(assets: list, all_segments: list) -> list:
    """素材仅有一个长镜头时，按时间窗虚拟切分，避免所有槽位匹配同一段。"""
    expanded = list(all_segments)
    seen = {f"{s.get('asset_id')}_{s.get('segment_id')}" for s in all_segments}

    for asset in assets:
        asset_segs = [s for s in all_segments if s.get("asset_id") == asset.id]
        if len(asset_segs) > 1:
            continue

        duration = float(asset.duration or 0)
        if duration < 5 or not asset.file_path:
            continue

        base = asset_segs[0] if asset_segs else {}
        base_thumb = base.get("thumbnail") or asset.thumbnail_path
        step = 4.0
        t = 0.0
        vidx = 1

        while t < duration - 0.8 and len(expanded) < 80:
            end = min(t + step, duration)
            seg_dur = end - t
            if seg_dur < 0.8:
                break
            seg_id = f"vslice_{vidx}"
            key = f"{asset.id}_{seg_id}"
            if key not in seen:
                expanded.append({
                    **base,
                    "segment_id": seg_id,
                    "asset_id": asset.id,
                    "file_path": asset.file_path,
                    "filename": asset.filename,
                    "start": round(t, 3),
                    "end": round(end, 3),
                    "duration": round(seg_dur, 3),
                    "thumbnail": base_thumb,
                    "segment_file_path": "",
                    "scene_tags": base.get("scene_tags", []),
                    "shot_type": base.get("shot_type", "wide"),
                })
                seen.add(key)
            t += step
            vidx += 1

    return expanded


class MatchWeightsConfig(BaseModel):
    tags_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    visual_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    duration_tolerance: float = Field(default=2.0, ge=1.0, le=10.0)

    @model_validator(mode="after")
    def normalize_weights(self):
        total = self.tags_weight + self.visual_weight
        if total > 1.0:
            self.tags_weight /= total
            self.visual_weight /= total
        return self


class MatchRunRequest(BaseModel):
    project_id: str
    template_id: str
    asset_ids: Optional[List[str]] = None
    overwrite: bool = False
    settings: Optional[Dict[str, Any]] = None
    weights: Optional[MatchWeightsConfig] = None
    strategy: Optional[Dict[str, Any]] = None


@router.post("/run")
def run_match(req: MatchRunRequest, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == req.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    template = db.query(Template).filter(Template.id == req.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    if template.id != project.template_id:
        raise HTTPException(status_code=400, detail="project_id 与 template_id 不匹配")

    from services.slot_helpers import has_ai_caption_split_slots, has_mixed_slot_sources, is_base_only_timeline

    template_slots = list(template.slots or [])
    if is_base_only_timeline(template_slots):
        raise HTTPException(status_code=400, detail="请先点击 AI 一键分割画面，再进行素材匹配。")

    if has_mixed_slot_sources(template_slots):
        raise HTTPException(
            status_code=400,
            detail="画面槽数据不一致（旧镜头切分与字幕分割混用），请重新执行 AI 一键分割画面。",
        )

    if has_ai_caption_split_slots(template_slots) and not all(
        str(s.get("source") or "") == "ai_caption_split" for s in template_slots if isinstance(s, dict)
    ):
        raise HTTPException(
            status_code=400,
            detail="画面槽含非字幕分割槽位，请重新执行 AI 一键分割画面。",
        )

    old_timeline = list(project.timeline or [])
    if not old_timeline:
        raise HTTPException(status_code=400, detail="项目时间线为空，请先从模板创建项目")

    old_timeline = enrich_timeline_for_matching(old_timeline, template_slots)
    understanding_warning = None
    if slots_missing_understanding(old_timeline, ratio=0.5):
        understanding_warning = (
            "部分模板槽位尚未完成 AI 画面理解，匹配准确度可能下降；"
            "建议等待模板分析完成或重新上传模板"
        )

    assets = (
        db.query(Asset).all()
        if not req.asset_ids
        else db.query(Asset).filter(Asset.id.in_(req.asset_ids)).all()
    )
    if not assets:
        raise HTTPException(status_code=400, detail="找不到待匹配的素材")

    all_segments = []
    for asset in assets:
        if asset.segments:
            for seg in asset.segments:
                all_segments.append({
                    **seg,
                    "asset_id": asset.id,
                    "filename": asset.filename,
                    "file_path": seg.get("file_path") or asset.file_path,
                    "thumbnail": seg.get("thumbnail") or asset.thumbnail_path,
                })

    if not all_segments:
        raise HTTPException(status_code=400, detail="素材片段为空，请先上传素材并生成片段")

    from services.processing_config import is_one_slot_one_material

    if not is_one_slot_one_material():
        all_segments = expand_segments_for_matching(assets, all_segments)

    weights = MatchWeights.from_dict(req.weights.model_dump() if req.weights else None)
    strategy = MatchStrategy.from_dict(req.strategy)
    merged_settings = strategy.merge_settings(req.settings)

    matched_timeline = match_slots(
        old_timeline,
        all_segments,
        weights=weights,
        settings=merged_settings,
    )

    new_timeline = []
    matched_count = 0
    warnings = []

    for old_slot, match in zip(old_timeline, matched_timeline):
        if old_slot.get("locked"):
            new_timeline.append(old_slot)
            continue

        if not req.overwrite and old_slot.get("asset_id"):
            new_timeline.append(old_slot)
            continue

        if match.get("asset_id"):
            matched_count += 1
            slot_duration = old_slot.get("slot_duration", old_slot.get("duration", 0))
            template_clip_start = old_slot.get("template_clip_start")
            if template_clip_start is None and not old_slot.get("asset_id"):
                template_clip_start = float(old_slot.get("clip_start", 0))
            linked_caption = (
                old_slot.get("linkedCaptionClipId")
                or old_slot.get("linked_subtitle_clip_id")
                or old_slot.get("linkedSubtitleClipId")
            )
            new_slot = {
                **old_slot,
                "asset_id": match["asset_id"],
                "segment_id": match.get("segment_id"),
                "segment_file_path": match.get("segment_file_path", ""),
                "asset_file_path": match.get("asset_file_path", ""),
                "asset_thumbnail": match.get("thumbnail", ""),
                "asset_filename": match.get("asset_filename", match.get("filename", "")),
                "clip_start": match.get("clip_start", 0),
                "clip_end": match.get("clip_end"),
                "clip_duration": slot_duration,
                "match_score": match.get("match_score", 0),
                "match_reason": match.get("match_reason", "自动匹配"),
                "use_original_audio": False,
                "linked_slot_id": old_slot.get("slot_id"),
                "linkedSlotId": old_slot.get("slot_id"),
                "linked_caption_clip_id": linked_caption,
                "linkedCaptionClipId": linked_caption,
            }
            if template_clip_start is not None:
                new_slot["template_clip_start"] = template_clip_start
        else:
            new_slot = {
                **old_slot,
                "match_score": 0,
                "match_reason": match.get("error", "未找到合适素材"),
            }
            warnings.append(f"{old_slot.get('slot_id')} 未匹配到素材")

        new_timeline.append(new_slot)

    project.timeline = new_timeline
    if strategy.transition_inherit:
        for slot in new_timeline:
            slot["transition_out"] = {"type": "dip_to_color", "duration": 0.3, "color": "#000000"}

    beat_markers = getattr(template, "beat_markers", []) or []
    project.edl_json = slots_timeline_to_edl(new_timeline, beat_markers=beat_markers)
    project.match_strategy_json = strategy.to_dict()
    if hasattr(project, "updated_at"):
        project.updated_at = time.time()
    db.commit()
    db.refresh(project)

    unmatched_count = len([slot for slot in new_timeline if not slot.get("asset_id")])

    from services.slot_helpers import build_one_caption_one_shot_debug

    return {
        "success": True,
        "project_id": project.id,
        "timeline": new_timeline,
        "matched_count": matched_count,
        "unmatched_count": unmatched_count,
        "warnings": warnings,
        "understanding_warning": understanding_warning,
        "edl": project.edl_json,
        "strategy": strategy.to_dict(),
        "oneCaptionOneShotDebug": build_one_caption_one_shot_debug(
            caption_clips=getattr(template, "subtitle_clips_json", []) or [],
            slots=template_slots,
            timeline=new_timeline,
        ),
    }
