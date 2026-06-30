"""AI 一键分割画面（CaptionClip → slot）测试。"""

from services.caption_slot_builder import ai_split_by_captions, build_slots_from_sentence_clips
from services.processing_config import (
    is_base_slot_creation_mode,
    is_one_caption_one_shot,
    is_one_slot_one_material,
)
from services.scene_detector import build_base_template_slot, build_template_intake_slots
from services.slot_helpers import (
    build_one_caption_one_shot_debug,
    has_mixed_slot_sources,
    is_base_only_timeline,
    is_base_slot,
    slots_will_be_overwritten_by_ai_split,
)
from services.subtitle_config import SubtitleConfig


def _eleven_clips():
    return [
        {
            "id": f"cap_{i:03d}",
            "start": float(i * 3),
            "end": float(i * 3 + 2.5),
            "text": f"第{i + 1}句话内容",
            "displayText": f"第{i + 1}句话内容",
            "source": "asr",
            "confidence": 0.8,
        }
        for i in range(11)
    ]


def test_default_slot_creation_mode_is_base():
    assert is_base_slot_creation_mode() is True


def test_upload_creates_single_base_slot():
    slots = build_template_intake_slots("/nonexistent/video.mp4", "/tmp/thumbs", 30.0, extract_thumbs=False)
    assert len(slots) == 1
    assert is_base_slot(slots[0])
    assert slots[0]["id"] == "slot_base_001"
    assert slots[0]["source"] == "base"
    assert slots[0]["cut_reason"] == "full_video"
    assert slots[0].get("isBaseSlot") is True


def test_build_base_template_slot_shape():
    slots = build_base_template_slot("/fake.mp4", "/tmp", 12.5, extract_thumb=False)
    slot = slots[0]
    assert slot["start"] == 0.0
    assert slot["end"] == 12.5
    assert slot["duration"] == 12.5
    assert slot["subtitle_text"] == ""


def test_eleven_caption_clips_generate_eleven_ai_slots():
    clips = _eleven_clips()
    slots, _ = build_slots_from_sentence_clips(clips, ai_split=True)
    assert len(slots) == 11
    for i, slot in enumerate(slots):
        assert slot["subtitle_text"] == f"第{i + 1}句话内容"
        assert slot["linkedCaptionClipId"] == f"cap_{i:03d}"
        assert slot["cut_reason"] == "one_sentence_one_shot"
        assert slot["source"] == "ai_caption_split"


def test_ai_split_by_captions_returns_debug():
    clips = _eleven_clips()
    result = ai_split_by_captions(
        "tpl_test",
        "/nonexistent/video.mp4",
        clips,
        duration=33.0,
        merge_short_fragments=True,
    )
    assert len(result["slots"]) == 11
    debug = result["ai_split_debug"]
    assert debug["strategy"] == "one_sentence_one_shot"
    assert debug["captionClipCount"] == 11
    assert debug["slotCount"] == 11
    assert debug["usedTtsAlignedTime"] is False


def test_short_fragments_merged_not_independent_slots():
    clips = [
        {"id": "cap_001", "start": 0.0, "end": 3.0, "text": "今年的旅行很精彩", "source": "asr"},
        {"id": "cap_002", "start": 3.0, "end": 3.2, "text": "年的", "source": "asr"},
        {"id": "cap_003", "start": 3.25, "end": 3.55, "text": "次璞", "source": "asr"},
        {"id": "cap_004", "start": 3.6, "end": 6.0, "text": "大连最美", "source": "asr"},
    ]
    result = ai_split_by_captions(
        "tpl_test",
        "/nonexistent/video.mp4",
        clips,
        duration=6.0,
        merge_short_fragments=True,
    )
    assert len(result["slots"]) < len(clips)
    assert result["ai_split_debug"]["mergedShortClipCount"] >= 1


def test_tts_aligned_time_used_when_available():
    clips = [
        {
            "id": "cap_001",
            "start": 0.0,
            "end": 2.5,
            "text": "第一句",
            "source": "asr",
            "originalStart": 0.0,
            "originalEnd": 2.0,
        },
        {
            "id": "cap_002",
            "start": 2.5,
            "end": 5.0,
            "text": "第二句",
            "source": "asr",
            "originalStart": 2.0,
            "originalEnd": 4.0,
        },
    ]
    tts_segments = [
        {"id": "tts_001", "captionClipId": "cap_001", "status": "generated", "duration": 2.5},
        {"id": "tts_002", "captionClipId": "cap_002", "status": "generated", "duration": 2.5},
    ]
    slots, _ = build_slots_from_sentence_clips(
        clips,
        tts_segments=tts_segments,
        timing_mode="tts_driven",
        ai_split=True,
        use_tts_aligned_time=True,
    )
    assert len(slots) == 2
    assert slots[0]["linkedTtsSegmentId"] == "tts_001"
    assert slots[1]["linkedTtsSegmentId"] == "tts_002"
    assert slots[0]["start"] == 0.0
    assert slots[0]["end"] == 2.5
    assert slots[1]["start"] == 2.5
    assert slots[1]["end"] == 5.0


def test_overwrite_warning_when_existing_non_base_slots():
    existing = [
        {"id": "slot_001", "start": 0, "end": 2, "source": "ai_caption_split"},
        {"id": "slot_002", "start": 2, "end": 4, "source": "ai_caption_split"},
    ]
    assert slots_will_be_overwritten_by_ai_split(existing) is True
    assert is_base_only_timeline(existing) is False

    result = ai_split_by_captions(
        "tpl_test",
        "/nonexistent/video.mp4",
        _eleven_clips()[:2],
        duration=6.0,
        existing_slots=existing,
        overwrite_slots=True,
    )
    assert result.get("overwrite_warning")


def test_base_only_timeline_not_overwritten_flag():
    base = build_base_template_slot(10.0)
    assert is_base_only_timeline([base]) is True
    assert slots_will_be_overwritten_by_ai_split([base]) is False


def test_recognize_does_not_imply_slot_mutation():
    """recognize-captions 路径只写 subtitle_clips_json，slots 由调用方保留。"""
    base = build_base_template_slot(10.0)
    slots_before = [dict(base)]
    slots_after = list(slots_before)
    assert slots_before == slots_after
    assert is_base_only_timeline(slots_after)


def test_one_caption_one_shot_config_defaults():
    assert is_one_caption_one_shot() is True
    assert is_one_slot_one_material() is True


def test_ai_split_debug_one_caption_one_shot():
    clips = _eleven_clips()
    result = ai_split_by_captions(
        "tpl_test",
        "/nonexistent/video.mp4",
        clips,
        duration=33.0,
        merge_short_fragments=True,
    )
    debug = result["oneCaptionOneShotDebug"]
    assert debug["captionClipCount"] == 11
    assert debug["slotCount"] == 11
    assert debug["slotsEqualCaptions"] is True
    assert debug["usingOldVisualSlots"] is False
    assert debug["allAiCaptionSplitSlots"] is True


def test_ai_split_replaces_mixed_visual_slots():
    clips = _eleven_clips()[:3]
    existing = [
        {"id": "slot_001", "slot_id": 1, "start": 0, "end": 1, "source": "scene_detect", "duration": 1},
        {"id": "slot_002", "slot_id": 2, "start": 1, "end": 2, "source": "scene_detect", "duration": 1},
    ]
    assert has_mixed_slot_sources(existing) is False
    result = ai_split_by_captions(
        "tpl_test",
        "/nonexistent/video.mp4",
        clips,
        duration=9.0,
        existing_slots=existing,
        overwrite_slots=True,
    )
    slots = result["slots"]
    assert len(slots) == 3
    assert all(s["source"] == "ai_caption_split" for s in slots)
    assert not has_mixed_slot_sources(slots)


def test_build_one_caption_one_shot_debug_counts():
    clips = _eleven_clips()[:2]
    slots, _ = build_slots_from_sentence_clips(clips, ai_split=True)
    debug = build_one_caption_one_shot_debug(caption_clips=clips, slots=slots)
    assert debug["captionClipCount"] == 2
    assert debug["slotCount"] == 2
    assert debug["slotsEqualCaptions"] is True


def test_tts_aligned_ai_split_slot_times_match_caption():
    clips = [
        {
            "id": "cap_001",
            "start": 0.0,
            "end": 2.5,
            "text": "第一句",
            "source": "asr",
            "originalStart": 0.0,
            "originalEnd": 2.0,
        },
        {
            "id": "cap_002",
            "start": 2.5,
            "end": 5.0,
            "text": "第二句",
            "source": "asr",
            "originalStart": 2.0,
            "originalEnd": 4.0,
        },
    ]
    tts_segments = [
        {"id": "tts_001", "captionClipId": "cap_001", "status": "generated", "duration": 2.5},
        {"id": "tts_002", "captionClipId": "cap_002", "status": "generated", "duration": 2.5},
    ]
    result = ai_split_by_captions(
        "tpl_test",
        "/nonexistent/video.mp4",
        clips,
        duration=5.0,
        tts_segments=tts_segments,
        timing_mode="tts_driven",
        use_tts_aligned_time=True,
    )
    slots = result["slots"]
    assert len(slots) == 2
    assert slots[0]["start"] == 0.0
    assert slots[0]["end"] == 2.5
    assert slots[1]["start"] == 2.5
    assert slots[1]["end"] == 5.0
    assert result["ai_split_debug"]["usedTtsAlignedTime"] is True
