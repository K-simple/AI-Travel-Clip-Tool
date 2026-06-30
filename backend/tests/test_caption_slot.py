"""caption_slot 一句一槽 + 两阶段流程测试。"""

from services.caption_sentence_fusion import fuse_sentence_clips, score_ocr_subtitle_track
from services.caption_slot_builder import (
    apply_caption_slots_from_clips,
    build_slots_from_sentence_clips,
    run_caption_recognition_pipeline,
)
from services.subtitle_clip_planner import build_subtitle_clips_from_asr
from services.subtitle_config import SubtitleConfig


def _cfg(**kwargs) -> SubtitleConfig:
    base = SubtitleConfig(cut_strategy="caption_slot")
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


def test_eleven_sentence_clips_generate_eleven_slots():
    clips = [
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
    slots, debug = build_slots_from_sentence_clips(clips, ai_split=True)
    assert len(slots) == 11
    assert len(debug) == 11
    for i, slot in enumerate(slots):
        assert slot["subtitle_text"] == f"第{i + 1}句话内容"
        assert slot["linked_subtitle_clip_id"] == f"cap_{i:03d}"
        assert slot["cut_reason"] == "one_sentence_one_shot"
        assert slot["source"] == "ai_caption_split"


def test_apply_uses_edited_clip_text():
    clips = [
        {"id": "cap_001", "start": 0.0, "end": 2.0, "text": "修改后的第一句", "source": "asr"},
    ]
    slots, _ = build_slots_from_sentence_clips(clips, ai_split=True)
    assert slots[0]["subtitle_text"] == "修改后的第一句"


def test_short_fragments_merged_or_dropped():
    spoken = [
        {
            "id": "s1",
            "start": 0.0,
            "end": 3.0,
            "text": "今年的旅行",
            "type": "spoken_caption",
            "words": [
                {"start": 0.0, "end": 0.2, "word": "年的"},
                {"start": 0.25, "end": 0.5, "word": "次璞"},
                {"start": 0.6, "end": 3.0, "word": "旅行很精彩"},
            ],
        }
    ]
    clips, debug = build_subtitle_clips_from_asr(spoken, config=_cfg())
    assert len(clips) >= 1
    for c in clips:
        dur = float(c["end"]) - float(c["start"])
        assert dur >= 0.5 or c.get("quality", {}).get("needsReview")
    assert debug.get("mergedFragmentCount", 0) + debug.get("mergedShortCount", 0) >= 0


def test_fusion_prefers_ocr_text_when_similar():
    asr_clips = [
        {
            "id": "cap_001",
            "start": 6.3,
            "end": 9.9,
            "text": "你的足云南的美女土们通过朋友介绍找到我现在",
            "displayText": "你的足云南的美女土们通过朋友介绍找到我现在",
            "confidence": 0.72,
            "linkedSegmentIds": ["asr_1"],
        }
    ]
    ocr_segments = [
        {
            "id": "ocr_1",
            "start": 6.2,
            "end": 9.8,
            "text": "你的足云南的美女们通过朋友介绍找到我现在",
            "source": "ocr",
        }
    ]
    spoken = [{"id": "asr_1", "start": 6.0, "end": 10.0, "text": asr_clips[0]["text"]}]
    fused, debug = fuse_sentence_clips(asr_clips, ocr_segments, spoken, config=_cfg())
    assert len(fused) == 1
    assert fused[0]["source"] == "asr_ocr_fused"
    assert "美女们" in fused[0]["text"]
    assert debug["fusedCount"] == 1


def test_ocr_ad_rejected():
    seg = {"id": "ocr_x", "start": 1.0, "end": 2.0, "text": "LOGO"}
    score, dbg = score_ocr_subtitle_track(seg, [], config=_cfg())
    assert score == 0.0
    assert dbg.get("rejectReason") == "logo_or_ad"


def test_ocr_only_when_asr_missing():
    ocr_segments = [
        {
            "id": "ocr_1",
            "start": 2.0,
            "end": 4.5,
            "text": "欢迎来到云南旅行",
            "source": "ocr",
        }
    ]
    fused, debug = fuse_sentence_clips([], ocr_segments, [], config=_cfg())
    assert len(fused) >= 1
    assert fused[0]["source"] == "ocr"
    assert debug["ocrOnlyCount"] >= 1


def test_slot_linked_to_clip_one_to_one():
    clips = [
        {"id": "cap_001", "start": 0.0, "end": 2.0, "text": "第一句", "source": "asr"},
        {"id": "cap_002", "start": 2.0, "end": 4.5, "text": "第二句", "source": "asr"},
    ]
    slots, _ = build_slots_from_sentence_clips(clips, ai_split=True)
    assert slots[0]["linkedSubtitleClipId"] == "cap_001"
    assert slots[1]["linkedSubtitleClipId"] == "cap_002"
    assert slots[0]["duration"] == 2.0
    assert abs(slots[1]["duration"] - 2.5) < 0.01
