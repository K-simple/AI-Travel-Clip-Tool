import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from services.subtitle_timeline_scan import (
    apply_subtitle_timeline_to_slots,
    band_dhash,
    hamming_distance,
    merge_timeline_segments,
    segments_from_boundaries,
    segments_overlapping_range,
    split_slots_by_subtitle_timeline,
)


def test_hamming_distance():
    assert hamming_distance(0b1010, 0b1010) == 0
    assert hamming_distance(0b1010, 0b0101) == 4


def test_band_dhash_stable():
    band = np.zeros((32, 120, 3), dtype=np.uint8)
    h1 = band_dhash(band)
    h2 = band_dhash(band)
    assert h1 == h2


def test_segments_from_boundaries_merge_short():
    segs = segments_from_boundaries([1.0, 1.2, 3.0], 4.0, min_segment_sec=0.35)
    assert segs[0][0] == 0.0
    assert segs[-1][1] == 4.0


def test_apply_subtitle_timeline_picks_best_overlap():
    timeline = [
        {"start": 0.0, "end": 2.0, "text": "第一句字幕"},
        {"start": 2.0, "end": 4.0, "text": "第二句字幕"},
    ]
    slots = [{"clip_start": 0.0, "clip_end": 2.0, "start": 0.0, "end": 2.0}]
    out = apply_subtitle_timeline_to_slots(slots, timeline)
    assert "第一句" in out[0]["subtitle_text"]


def test_segments_overlapping_range():
    timeline = [{"start": 1.0, "end": 3.0, "text": "中间句"}]
    hits = segments_overlapping_range(timeline, 0.5, 2.5)
    assert len(hits) == 1


def test_split_slots_by_subtitle_timeline():
    timeline = [
        {"start": 0.0, "end": 2.0, "text": "第一句字幕"},
        {"start": 2.0, "end": 4.5, "text": "第二句字幕"},
    ]
    slots = [
        {
            "slot_id": 1,
            "start": 0.0,
            "end": 4.5,
            "clip_start": 0.0,
            "clip_end": 4.5,
            "duration": 4.5,
        }
    ]
    out = split_slots_by_subtitle_timeline(slots, timeline)
    assert len(out) == 2
    assert out[0]["subtitle_text"] == "第一句字幕"
    assert out[1]["subtitle_text"] == "第二句字幕"
    assert out[0]["clip_end"] == 2.0
    assert out[1]["clip_start"] == 2.0
    assert out[0]["slot_id"] == 1
    assert out[1]["slot_id"] == 2


def test_split_slots_keeps_single_sentence_slot():
    timeline = [{"start": 0.0, "end": 2.0, "text": "单句"}]
    slots = [{"slot_id": 1, "start": 0.0, "end": 2.0, "clip_start": 0.0, "clip_end": 2.0, "duration": 2.0}]
    out = split_slots_by_subtitle_timeline(slots, timeline)
    assert len(out) == 1
    assert out[0]["subtitle_text"] == "单句"


def test_merge_timeline_duplicate_fragments():
    timeline = [
        {"start": 0.25, "end": 1.0, "text": "同一句字幕"},
        {"start": 1.0, "end": 1.75, "text": "同一句字幕"},
        {"start": 1.75, "end": 2.5, "text": "第二句字幕"},
    ]
    merged = merge_timeline_segments(timeline)
    assert len(merged) == 2
    assert merged[0]["text"] == "同一句字幕"
    assert merged[0]["end"] == 1.75


def test_split_does_not_split_same_text_fragments():
    timeline = [
        {"start": 0.25, "end": 1.0, "text": "同一句字幕"},
        {"start": 1.0, "end": 1.75, "text": "同一句字幕"},
    ]
    slots = [
        {
            "slot_id": 1,
            "start": 0.0,
            "end": 1.75,
            "clip_start": 0.0,
            "clip_end": 1.75,
            "duration": 1.75,
        }
    ]
    out = split_slots_by_subtitle_timeline(slots, timeline)
    assert len(out) == 1
    assert "同一句" in out[0]["subtitle_text"]
