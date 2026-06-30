import pytest

from services.matcher import (
    MatchWeights,
    calculate_duration_score,
    calculate_tag_score,
    match_slots,
)


def test_calculate_tag_score_overlap():
    assert calculate_tag_score(["beach", "sun"], ["sun", "wave"]) == 0.5
    assert calculate_tag_score([], ["sun"]) == 0.0


def test_calculate_duration_score():
    assert calculate_duration_score(4.0, 3.0) == 0.0
    assert calculate_duration_score(4.0, 4.5) == 1.0


def test_match_slots_respects_min_score_threshold():
    slots = [
        {
            "slot_id": 1,
            "duration": 3.0,
            "scene_tags": ["完全不同"],
            "ai_description": "雪山",
        }
    ]
    segments = [
        {
            "asset_id": "a1",
            "segment_id": "s1",
            "duration": 5.0,
            "scene_tags": ["海滩"],
            "ai_description": "沙滩",
            "shot_type": "wide",
            "quality_score": 0.5,
            "start": 0,
            "end": 5,
            "filename": "beach.mp4",
        }
    ]
    results = match_slots(
        slots,
        segments,
        weights=MatchWeights(),
        settings={"min_match_score": 0.95, "semantic_weight": 0.4},
    )
    assert results[0].get("asset_id") is None
    assert "低于阈值" in results[0].get("error", "")
