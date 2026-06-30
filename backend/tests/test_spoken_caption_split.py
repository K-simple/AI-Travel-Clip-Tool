"""spoken_caption 切槽与防重复测试。"""

from services.spoken_caption_split import (
    SLOT_STATUS_MATCHED,
    SLOT_STATUS_NO_SPEECH,
    split_spoken_caption_by_slots,
)
from services.subtitle_config import SubtitleConfig, resolve_recognition_mode
from services.subtitle_fusion import fuse_slot_subtitles


def test_resolve_auto_is_speech():
    assert resolve_recognition_mode("auto") == "speech"


def test_fusion_speech_mode_ignores_ocr():
    ocr = [{"start": 0, "end": 2, "text": "广告牌", "type": "screen_text"}]
    asr = [{"start": 0, "end": 2, "text": "大家好", "type": "spoken_caption"}]
    fused, source = fuse_slot_subtitles(asr, ocr, 0, 2, [], recognition_mode="speech")
    assert source == "whisper"
    assert fused[0]["text"] == "大家好"


def test_one_segment_three_slots_no_full_duplicate():
    spoken = [
        {
            "id": "subtitle_1",
            "start": 10.0,
            "end": 15.0,
            "text": "第二站交通机场火车站站口拉客的标价车千万别上",
            "type": "spoken_caption",
            "confidence": 0.77,
            "words": [
                {"start": 10.0, "end": 10.6, "word": "第二"},
                {"start": 10.6, "end": 11.0, "word": "站"},
                {"start": 11.0, "end": 11.4, "word": "交通"},
                {"start": 11.4, "end": 11.8, "word": "机场"},
                {"start": 11.8, "end": 12.2, "word": "火车"},
                {"start": 12.2, "end": 12.6, "word": "站"},
                {"start": 12.6, "end": 13.0, "word": "站口"},
                {"start": 13.0, "end": 13.6, "word": "拉客"},
                {"start": 13.6, "end": 14.0, "word": "的"},
                {"start": 14.0, "end": 14.4, "word": "标价"},
                {"start": 14.4, "end": 14.8, "word": "车"},
                {"start": 14.8, "end": 15.0, "word": "千万别上"},
            ],
        }
    ]
    slots = [
        {"slot_id": 12, "clip_start": 10.0, "clip_end": 11.4},
        {"slot_id": 13, "clip_start": 11.4, "clip_end": 12.0},
        {"slot_id": 14, "clip_start": 12.0, "clip_end": 15.0},
    ]
    out, debug = split_spoken_caption_by_slots(spoken, slots)
    texts = [str(s.get("subtitle_text") or "") for s in out]

    assert texts[0] and texts[2]
    assert texts[0] != texts[2]
    assert texts[0] not in texts[2] or texts[2].endswith("千万别上")
    assert "千万别上" in texts[2]
    assert debug["assignedWordCount"] == 12
    assert all(t != spoken[0]["text"] for t in texts if t)


def test_word_midpoint_assigns_unique_slots():
    spoken = [
        {
            "id": "s1",
            "start": 0.0,
            "end": 6.0,
            "text": "这是一句跨多个镜头的口播",
            "type": "spoken_caption",
            "words": [
                {"start": 0.0, "end": 1.0, "word": "这是"},
                {"start": 1.0, "end": 2.0, "word": "一句"},
                {"start": 2.0, "end": 4.0, "word": "跨多个"},
                {"start": 4.0, "end": 6.0, "word": "镜头的口播"},
            ],
        }
    ]
    slots = [
        {"slot_id": "a", "clip_start": 0.0, "clip_end": 2.0},
        {"slot_id": "b", "clip_start": 2.0, "clip_end": 4.0},
        {"slot_id": "c", "clip_start": 4.0, "clip_end": 6.0},
    ]
    out, _ = split_spoken_caption_by_slots(spoken, slots)
    texts = [s.get("subtitle_text") or "" for s in out]
    joined = "".join(texts)
    assert joined == "这是一句跨多个镜头的口播"
    assert len(set(texts)) >= 2


def test_no_words_segment_proportional_no_duplicate():
    spoken = [
        {
            "id": "s1",
            "start": 0.0,
            "end": 9.0,
            "text": "abcdefghi",
            "type": "spoken_caption",
        }
    ]
    slots = [
        {"slot_id": 1, "clip_start": 0.0, "clip_end": 3.0},
        {"slot_id": 2, "clip_start": 3.0, "clip_end": 6.0},
        {"slot_id": 3, "clip_start": 6.0, "clip_end": 9.0},
    ]
    out, _ = split_spoken_caption_by_slots(spoken, slots, config=SubtitleConfig())
    texts = [s.get("subtitle_text") or "" for s in out]
    assert sum(len(t) for t in texts) <= 9
    assert len(set(texts)) >= 2


def test_empty_slot_is_no_speech_not_error():
    spoken = [{"id": "s1", "start": 0.0, "end": 3.0, "text": "你好", "type": "spoken_caption", "words": [{"start": 0, "end": 1, "word": "你"}, {"start": 1, "end": 2, "word": "好"}]}]
    slots = [{"slot_id": 99, "clip_start": 10.0, "clip_end": 12.0}]
    out, _ = split_spoken_caption_by_slots(spoken, slots)
    assert out[0].get("subtitle_status") == SLOT_STATUS_NO_SPEECH
    assert out[0].get("subtitle_text") == ""


def test_dedupe_strips_substring():
    spoken = [
        {
            "id": "s1",
            "start": 0.0,
            "end": 6.0,
            "text": "ABCDE",
            "type": "spoken_caption",
            "words": [
                {"start": 0.0, "end": 2.0, "word": "AB"},
                {"start": 2.0, "end": 4.0, "word": "CD"},
                {"start": 4.0, "end": 6.0, "word": "E"},
            ],
        }
    ]
    slots = [
        {"slot_id": 1, "clip_start": 0.0, "clip_end": 4.0},
        {"slot_id": 2, "clip_start": 2.0, "clip_end": 4.0},
    ]
    out, debug = split_spoken_caption_by_slots(
        spoken,
        slots,
        config=SubtitleConfig(prevent_duplicate_slot_text=True),
    )
    t0 = out[0].get("subtitle_text") or ""
    t1 = out[1].get("subtitle_text") or ""
    assert t0 == "ABCD"
    assert t1 in ("", "CD")
    assert t0 != t1 or t1 == ""


def test_master_segments_unchanged():
    spoken = [
        {
            "id": "s1",
            "start": 0.0,
            "end": 5.0,
            "text": "主轨不变",
            "type": "spoken_caption",
            "words": [{"start": 0, "end": 5, "word": "主轨不变"}],
        }
    ]
    original_text = spoken[0]["text"]
    slots = [{"slot_id": 1, "clip_start": 0.0, "clip_end": 5.0}]
    split_spoken_caption_by_slots(spoken, slots)
    assert spoken[0]["text"] == original_text
