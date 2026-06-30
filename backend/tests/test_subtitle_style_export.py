"""字幕样式解析与剪映动画导出映射测试。"""

import pytest

cv2 = pytest.importorskip("cv2")

from services.subtitle_style_analyzer import (
    resolve_subtitle_style_for_export,
    style_needs_template_video_analysis,
    style_to_capcut_caption_item,
    to_capcut_font_size,
)


def test_to_capcut_font_size_maps_analyzer_scale():
    assert to_capcut_font_size({"font_size": 54}) == 15
    assert 9 <= to_capcut_font_size({"font_size": 72}) <= 22
    assert to_capcut_font_size({"capcut_font_size": 18}) == 18


def test_style_needs_analysis_for_default_white():
    assert style_needs_template_video_analysis({"text_color": "#ffffff", "confidence": 0.35})
    assert not style_needs_template_video_analysis(
        {"text_color": "#face15", "confidence": 0.72, "style_label": "上滑·#face15"}
    )


def test_resolve_subtitle_style_prefers_template_segment():
    slot = {"subtitle_style": {"text_color": "#ffffff", "animation_in": "fade"}}
    template_seg = {"style": {"text_color": "#face15", "animation_in": "fade_up", "confidence": 0.8}}
    style = resolve_subtitle_style_for_export(slot, template_segment=template_seg)
    assert style["text_color"] == "#face15"
    assert style["animation_in"] == "fade_up"


def test_style_to_capcut_caption_item_maps_animations():
    cap = {"start": 0, "end": 2_000_000, "text": "测试字幕"}
    style = {
        "text_color": "#face15",
        "animation_in": "fade_up",
        "animation_out": "scale_out",
        "animation_loop": "pulse",
        "font_size": 54,
        "capcut_font_size": 15,
        "outline_color": "#000000",
    }
    item = style_to_capcut_caption_item(cap, style, clip_duration_us=2_000_000)
    assert item["in_animation"] == "向上滑动"
    assert item["out_animation"] == "缩小"
    assert item["loop_animation"] == "脉冲"
    assert item["font_size"] == 15
    assert item["text_color"] == "#face15"
