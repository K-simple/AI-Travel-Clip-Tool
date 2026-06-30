import os

from services.subtitle_render import (
    ass_escape,
    build_ass_from_timeline_slots,
    format_ass_time,
    format_srt_time,
    make_template_subtitle_if_needed,
    normalize_segments,
    write_ass,
    write_ass_styled_for_clip,
    write_srt,
)


def test_make_template_subtitle_prefers_ass(tmp_path):
    ass = tmp_path / "template.ass"
    ass.write_text("[Script Info]", encoding="utf-8")
    result = make_template_subtitle_if_needed(
        None,
        None,
        str(ass),
        None,
        str(tmp_path),
        1080,
        1920,
    )
    assert result == str(ass)


def test_make_template_subtitle_from_segments_json(tmp_path):
    segments = [{"start": 0, "end": 1.2, "text": "模板字幕"}]
    result = make_template_subtitle_if_needed(
        None,
        None,
        None,
        segments,
        str(tmp_path),
        1080,
        1920,
    )
    assert result and os.path.isfile(result)
    assert "模板字幕" in open(result, encoding="utf-8").read()


def test_format_ass_time_zero():
    assert format_ass_time(0) == "0:00:00.00"


def test_write_ass_creates_file(tmp_path):
    out = tmp_path / "test.ass"
    write_ass([{"start": 0, "end": 1.5, "text": "hello"}], str(out))
    text = out.read_text(encoding="utf-8")
    assert "Dialogue:" in text
    assert "hello" in text


def test_build_ass_from_timeline_slots(tmp_path):
    timeline = [
        {
            "slot_duration": 3.0,
            "subtitle_text": "开场",
        },
        {
            "slot_duration": 2.0,
            "subtitle_segments": [{"start": 3.1, "end": 4.5, "text": "第二镜"}],
        },
    ]
    out = build_ass_from_timeline_slots(timeline, str(tmp_path), 1080, 1920)
    assert out and os.path.isfile(out)
    assert "开场" in open(out, encoding="utf-8").read()


def test_build_ass_maps_source_relative_segments(tmp_path):
    timeline = [
        {
            "slot_start": 5.0,
            "slot_duration": 2.0,
            "clip_start": 12.0,
            "template_source_start": 12.0,
            "subtitle_segments": [{"start": 12.2, "end": 13.8, "text": "源时间字幕"}],
        },
    ]
    out = build_ass_from_timeline_slots(timeline, str(tmp_path), 1080, 1920)
    body = open(out, encoding="utf-8").read()
    assert "源时间字幕" in body
    assert "0:00:05." in body


def test_write_ass_styled_for_clip(tmp_path):
    out = tmp_path / "styled.ass"
    write_ass_styled_for_clip(
        [
            {
                "start": 0,
                "end": 2,
                "text": "花字",
                "style": {
                    "text_color": "#ff0000",
                    "animation_in": "scale",
                    "font_size": 48,
                },
            }
        ],
        str(out),
    )
    text = out.read_text(encoding="utf-8")
    assert "花字" in text
    assert "\\fscx" in text


def test_ass_escape():
    assert ass_escape("a\\b{c}") == "a\\\\b\\{c\\}"


def test_normalize_segments_filters_empty():
    raw = [{"start": 0, "end": 1, "text": " ok "}, {"start": 2, "end": 2, "text": "x"}]
    out = normalize_segments(raw)
    assert len(out) == 1
    assert out[0]["text"] == "ok"


def test_write_srt(tmp_path):
    out = tmp_path / "sub.srt"
    write_srt([{"start": 0, "end": 1.25, "text": "你好"}], str(out))
    text = out.read_text(encoding="utf-8")
    assert "1\n" in text
    assert "你好" in text
    assert format_srt_time(1.25).endswith(",250")
