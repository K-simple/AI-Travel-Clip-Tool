"""模板媒体增强：字幕样式 + 音效点位。"""

from typing import Any

from services.processing_config import ENABLE_SFX_DETECTION, ENABLE_SUBTITLE_STYLE_ANALYSIS
from services.sfx_detector import analyze_template_audio
from services.subtitle_style_analyzer import analyze_subtitle_styles, merge_styles_into_slots


def enrich_template_media_analysis(
    *,
    video_path: str,
    template_dir: str,
    segments_json: list[dict[str, Any]] | None,
    audio_path: str,
    duration: float,
    slots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    模板分析增强入口。
    返回 beat_markers、sfx_markers、segments_json、slots（带样式）。
    """
    result: dict[str, Any] = {
        "beat_markers": [],
        "sfx_markers": [],
        "segments_json": segments_json or [],
        "slots": slots or [],
    }

    if ENABLE_SFX_DETECTION and audio_path:
        try:
            audio_result = analyze_template_audio(audio_path, duration, template_dir)
            result["beat_markers"] = audio_result.get("beat_markers") or []
            result["sfx_markers"] = audio_result.get("sfx_markers") or []
        except Exception as exc:
            print(f"音效/节拍分析失败: {exc}")

    if ENABLE_SUBTITLE_STYLE_ANALYSIS and video_path and segments_json:
        try:
            enriched_segments = analyze_subtitle_styles(video_path, segments_json, template_dir)
            result["segments_json"] = enriched_segments
            if slots:
                result["slots"] = merge_styles_into_slots(slots, enriched_segments)
        except Exception as exc:
            print(f"字幕样式分析失败: {exc}")

    return result
