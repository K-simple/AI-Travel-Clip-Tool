"""槽位对齐与 speech 状态分类测试（不依赖 Whisper）。"""

from services.speech_subtitle_pipeline import (
    SLOT_STATUS_MATCHED,
    SLOT_STATUS_NO_OVERLAP,
    SLOT_STATUS_NO_SPEECH,
    align_spoken_to_slot_detailed,
    derive_slot_subtitle,
)
from services.subtitle_config import resolve_recognition_mode
from services.subtitle_fusion import fuse_slot_subtitles


def test_resolve_auto_is_speech():
    assert resolve_recognition_mode("auto") == "speech"


def test_fusion_speech_mode_ignores_ocr():
    ocr = [{"start": 0, "end": 2, "text": "广告牌文字", "type": "screen_text"}]
    asr = [{"start": 0, "end": 2, "text": "大家好", "type": "spoken_caption"}]
    fused, source = fuse_slot_subtitles(
        asr,
        ocr,
        0,
        2,
        [],
        recognition_mode="speech",
    )
    assert source == "whisper"
    assert fused[0]["text"] == "大家好"


def test_empty_slot_is_no_speech_not_error():
    spoken = [
        {
            "id": "subtitle_1",
            "start": 0.0,
            "end": 3.0,
            "text": "口播第一句",
            "type": "spoken_caption",
            "confidence": 0.8,
        }
    ]
    result = align_spoken_to_slot_detailed(spoken, 10.0, 12.0, slot_id="slot-10")
    assert result.status == SLOT_STATUS_NO_SPEECH
    assert result.reason == "no_asr_in_slot_window"
    assert result.success is True
    assert result.segments == []


def test_asr_segment_links_multiple_slots():
    spoken = [
        {
            "id": "subtitle_1",
            "start": 0.0,
            "end": 6.0,
            "text": "这是一句跨多个镜头的口播",
            "type": "spoken_caption",
            "confidence": 0.85,
            "effectProfileId": "defaultSpeechCaption",
        }
    ]
    slot_a = align_spoken_to_slot_detailed(spoken, 0.0, 2.0, slot_id="a")
    slot_b = align_spoken_to_slot_detailed(spoken, 2.0, 4.0, slot_id="b")
    slot_c = align_spoken_to_slot_detailed(spoken, 8.0, 10.0, slot_id="c")

    assert slot_a.status == SLOT_STATUS_MATCHED
    assert slot_b.status == SLOT_STATUS_MATCHED
    assert slot_c.status == SLOT_STATUS_NO_SPEECH
    assert slot_a.linked_subtitle_segment_ids == ["subtitle_1"]
    assert slot_b.linked_subtitle_segment_ids == ["subtitle_1"]
    assert spoken[0]["start"] == 0.0
    assert spoken[0]["end"] == 6.0


def test_no_overlap_when_padding_insufficient():
    spoken = [
        {
            "id": "subtitle_2",
            "start": 5.0,
            "end": 5.08,
            "text": "短",
            "type": "spoken_caption",
        }
    ]
    result = align_spoken_to_slot_detailed(spoken, 0.0, 4.5, slot_id="gap")
    assert result.status in (SLOT_STATUS_NO_SPEECH, SLOT_STATUS_NO_OVERLAP)


def test_derive_slot_subtitle_alias():
    spoken = [
        {
            "id": "subtitle_1",
            "start": 0.0,
            "end": 3.0,
            "text": "欢迎来到大连",
            "type": "spoken_caption",
            "confidence": 0.8,
        }
    ]
    aligned = derive_slot_subtitle(spoken, 0.5, 2.5)
    assert aligned
    assert "大连" in aligned[0]["text"]
