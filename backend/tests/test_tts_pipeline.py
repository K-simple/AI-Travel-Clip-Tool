"""TTS 流水线测试。"""

from __future__ import annotations

import os
import tempfile

from services.caption_slot_builder import apply_caption_slots_from_clips, build_slots_from_sentence_clips
from services.tts.tts_pipeline import (
    align_timeline_to_tts,
    ensure_clip_timeline_fields,
    generate_tts_for_clips,
)


def _eleven_clips():
    return [
        {
            "id": f"cap_{i:03d}",
            "index": i + 1,
            "start": float(i * 3),
            "end": float(i * 3 + 2.5),
            "text": f"第{i + 1}句字幕内容",
            "displayText": f"第{i + 1}句字幕内容",
            "source": "asr",
        }
        for i in range(11)
    ]


def test_eleven_clips_generate_eleven_tts_segments():
    clips = ensure_clip_timeline_fields(_eleven_clips())
    with tempfile.TemporaryDirectory() as tmp:
        template_id = os.path.basename(tmp)
        tts_dir = os.path.join("storage", "templates", template_id, "tts")
        os.makedirs(tts_dir, exist_ok=True)
        result = generate_tts_for_clips(
            template_id,
            clips,
            voice_id="real_blog_female",
            overwrite=True,
        )
    segments = result["tts_segments"]
    assert len(segments) == 11
    assert result["summary"]["generatedCount"] == 11
    assert result["summary"]["failedCount"] == 0
    for seg in segments:
        assert seg["status"] == "generated"
        assert seg["audioPath"]
        assert float(seg["duration"]) > 0


def test_tts_failure_does_not_block_others(monkeypatch):
    clips = ensure_clip_timeline_fields(_eleven_clips())
    clips[5]["text"] = ""  # 触发单条失败

    with tempfile.TemporaryDirectory() as tmp:
        template_id = os.path.basename(tmp)
        os.makedirs(os.path.join("storage", "templates", template_id, "tts"), exist_ok=True)
        result = generate_tts_for_clips(
            template_id,
            clips,
            voice_id="real_blog_female",
            overwrite=True,
        )
    assert result["summary"]["generatedCount"] == 10
    assert result["summary"]["failedCount"] == 1
    assert len(result["tts_segments"]) == 11


def test_align_timeline_to_tts_syncs_start_end():
    clips = ensure_clip_timeline_fields(_eleven_clips())
    with tempfile.TemporaryDirectory() as tmp:
        template_id = os.path.basename(tmp)
        os.makedirs(os.path.join("storage", "templates", template_id, "tts"), exist_ok=True)
        gen = generate_tts_for_clips(template_id, clips, voice_id="real_blog_female", overwrite=True)
    aligned_clips, aligned_segments, total = align_timeline_to_tts(clips, gen["tts_segments"])
    assert len(aligned_clips) == 11
    assert len(aligned_segments) == 11
    assert total > 0
    cursor = 0.0
    for clip, seg in zip(aligned_clips, aligned_segments):
        assert abs(float(clip["start"]) - cursor) < 0.02
        assert abs(float(seg["start"]) - float(clip["start"])) < 0.02
        assert abs(float(seg["end"]) - float(clip["end"])) < 0.02
        cursor = float(clip["end"])
    assert clip.get("originalStart") is not None


def test_apply_caption_slots_count_and_links():
    clips = ensure_clip_timeline_fields(_eleven_clips())
    with tempfile.TemporaryDirectory() as tmp:
        template_id = os.path.basename(tmp)
        os.makedirs(os.path.join("storage", "templates", template_id, "tts"), exist_ok=True)
        gen = generate_tts_for_clips(template_id, clips, voice_id="real_blog_female", overwrite=True)
    aligned_clips, aligned_segments, _ = align_timeline_to_tts(clips, gen["tts_segments"])
    applied = apply_caption_slots_from_clips(
        "tpl-test",
        "",
        aligned_clips,
        duration=60.0,
        tts_segments=aligned_segments,
        timing_mode="tts_driven",
    )
    slots = applied["slots"]
    assert len(slots) == 11
    for i, slot in enumerate(slots):
        clip_id = f"cap_{i + 1:03d}"
        assert slot["linked_subtitle_clip_id"] == clip_id
        assert slot.get("linked_tts_segment_id") == f"tts_{i + 1:03d}"
        assert slot["source"] == "caption_tts_driven"
        assert slot["cut_reason"] == "caption_audio_aligned"


def test_generate_tts_uses_edited_text():
    clips = ensure_clip_timeline_fields(_eleven_clips())
    clips[0]["text"] = "修改后的第一句"
    clips[0]["displayText"] = "修改后的第一句"
    with tempfile.TemporaryDirectory() as tmp:
        template_id = os.path.basename(tmp)
        os.makedirs(os.path.join("storage", "templates", template_id, "tts"), exist_ok=True)
        result = generate_tts_for_clips(template_id, clips, voice_id="real_blog_female", overwrite=True)
    assert result["tts_segments"][0]["text"] == "修改后的第一句"


def test_apply_without_tts_fallback_and_warning():
    clips = ensure_clip_timeline_fields(_eleven_clips())
    applied = apply_caption_slots_from_clips("tpl", "", clips, duration=60.0, tts_segments=[], timing_mode="tts_driven")
    assert applied.get("tts_warning")
    assert len(applied["slots"]) == 11
    assert applied["slots"][0]["cut_reason"] == "caption_sentence"


def test_build_slots_tts_driven_fields():
    clips = ensure_clip_timeline_fields(_eleven_clips())
    tts = [
        {
            "id": "tts_001",
            "captionClipId": "cap_001",
            "index": 1,
            "status": "generated",
            "duration": 2.0,
            "start": 0,
            "end": 2.0,
        }
    ]
    slots, _ = build_slots_from_sentence_clips(clips[:1], tts_segments=tts, timing_mode="tts_driven")
    assert slots[0]["linked_tts_segment_id"] == "tts_001"
    assert slots[0]["source"] == "caption_tts_driven"
