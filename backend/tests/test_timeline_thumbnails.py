from services.timeline_thumbnails import (
    QUALITY_PRESETS,
    _compute_sampling,
    _frame_times,
    _scaled_height,
    _time_to_filename,
    _thumb_rel_url,
)


def test_time_to_filename():
    assert _time_to_filename(0.0) == "t_000000.jpg"
    assert _time_to_filename(0.5) == "t_000500.jpg"
    assert _time_to_filename(1.25) == "t_001250.jpg"


def test_thumb_rel_url():
    url = _thumb_rel_url("tpl-1", "standard", "t_000500.jpg")
    assert url == "/storage/thumbnails/tpl-1/timeline_thumbs/standard/t_000500.jpg"


def test_compute_sampling_caps_long_video():
    interval, count = _compute_sampling(600.0, 0.5, 240)
    assert count == 240
    assert interval > 0.5


def test_compute_sampling_short_video():
    interval, count = _compute_sampling(10.0, 0.5, 240)
    assert interval == 0.5
    assert count == 21


def test_frame_times():
    times = _frame_times(2.0, 0.5, 5)
    assert times == [0.0, 0.5, 1.0, 1.5, 2.0]


def test_scaled_height():
    assert _scaled_height(120, 720, 1280) == 213


def test_quality_presets():
    assert QUALITY_PRESETS["low"]["interval_sec"] == 1.0
    assert QUALITY_PRESETS["standard"]["width"] == 120
    assert QUALITY_PRESETS["high"]["interval_sec"] == 0.25


def test_get_timeline_thumbnail_profiles_empty_video():
    from services.timeline_thumbnails import get_timeline_thumbnail_profiles

    payload = get_timeline_thumbnail_profiles("", "tpl-x", generate_missing=False)
    assert payload["status"] == "processing"
    assert payload["templateId"] == "tpl-x"
    assert payload["profiles"] == {}

