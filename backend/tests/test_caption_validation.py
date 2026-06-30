"""ASR 主 + OCR 校验 → validatedCaptionClips 测试。"""

import pytest

pytest.importorskip("faster_whisper")

from services.caption_sentence_fusion import validate_caption_clips_with_ocr
from services.subtitle_config import SubtitleConfig


def _cfg(**overrides) -> SubtitleConfig:
    base = SubtitleConfig(
        caption_ocr_validate=True,
        caption_ocr_validate_split=True,
        caption_ocr_validate_merge=True,
        caption_ocr_overlap_min_ratio=0.15,
        caption_slot_ocr_subtitle_score_threshold=0.5,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_one_asr_multiple_ocr_splits():
    asr_clips = [
        {
            "id": "cap_001",
            "start": 0.0,
            "end": 6.0,
            "text": "今天天气很好我们出去散步",
            "source": "asr",
            "confidence": 0.9,
            "words": [
                {"word": "今天天气很好", "start": 0.0, "end": 3.0},
                {"word": "我们出去散步", "start": 3.0, "end": 6.0},
            ],
        }
    ]
    ocr_segments = [
        {"id": "ocr_001", "start": 0.0, "end": 3.0, "text": "今天天气很好"},
        {"id": "ocr_002", "start": 3.0, "end": 6.0, "text": "我们出去散步"},
    ]
    validated, debug = validate_caption_clips_with_ocr(
        asr_clips, ocr_segments, spoken_segments=[], config=_cfg()
    )
    assert debug["ocrSplitCount"] >= 1
    assert len(validated) == 2
    assert all(c.get("source") != "ocr" for c in validated)
    assert validated[0]["text"] == "今天天气很好"
    assert validated[1]["text"] == "我们出去散步"


def test_multiple_asr_one_ocr_merges():
    asr_clips = [
        {"id": "cap_001", "start": 0.0, "end": 1.5, "text": "今天", "source": "asr", "confidence": 0.85},
        {"id": "cap_002", "start": 1.5, "end": 3.0, "text": "天气很好", "source": "asr", "confidence": 0.85},
    ]
    ocr_segments = [
        {"id": "ocr_001", "start": 0.0, "end": 3.0, "text": "今天天气很好"},
    ]
    validated, debug = validate_caption_clips_with_ocr(
        asr_clips, ocr_segments, spoken_segments=[], config=_cfg()
    )
    assert debug["ocrMergeCount"] >= 1
    assert len(validated) == 1
    assert "今天" in validated[0]["text"] and "天气" in validated[0]["text"]


def test_asr_ocr_mismatch_needs_review():
    asr_clips = [
        {"id": "cap_001", "start": 0.0, "end": 2.5, "text": "完全不同的句子", "source": "asr", "confidence": 0.8},
    ]
    ocr_segments = [
        {"id": "ocr_001", "start": 0.0, "end": 2.5, "text": "大连最美海岸线"},
    ]
    validated, debug = validate_caption_clips_with_ocr(
        asr_clips, ocr_segments, spoken_segments=[], config=_cfg()
    )
    assert len(validated) == 1
    assert debug["mismatchCount"] >= 1
    assert validated[0]["quality"]["needsReview"] is True
    assert validated[0]["validationStatus"] == "needs_review"


def test_no_ocr_only_clips():
    asr_clips = [
        {"id": "cap_001", "start": 0.0, "end": 2.0, "text": "只有口播", "source": "asr", "confidence": 0.9},
    ]
    ocr_segments = [
        {"id": "ocr_001", "start": 5.0, "end": 7.0, "text": "画面独有字幕"},
    ]
    validated, debug = validate_caption_clips_with_ocr(
        asr_clips, ocr_segments, spoken_segments=[], config=_cfg()
    )
    assert len(validated) == 1
    assert debug["ocrOnlyCount"] == 0
    assert validated[0]["text"] == "只有口播"
