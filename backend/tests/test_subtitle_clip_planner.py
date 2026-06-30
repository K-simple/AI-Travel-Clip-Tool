"""subtitleClips 切句规划测试。"""

from services.subtitle_clip_planner import build_subtitle_clips_from_asr
from services.subtitle_config import SubtitleConfig


def _cfg(**kwargs) -> SubtitleConfig:
    base = SubtitleConfig()
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


def test_long_segment_splits_to_multiple_clips():
    spoken = [
        {
            "id": "s1",
            "start": 10.0,
            "end": 15.0,
            "text": "第二站交通机场火车站站口拉客的标价车千万别上",
            "type": "spoken_caption",
            "words": [
                {"start": 10.0, "end": 10.5, "word": "第二"},
                {"start": 10.5, "end": 10.9, "word": "站"},
                {"start": 10.9, "end": 11.3, "word": "交通"},
                {"start": 11.3, "end": 11.7, "word": "机场"},
                {"start": 11.7, "end": 12.1, "word": "火车"},
                {"start": 12.1, "end": 12.5, "word": "站"},
                {"start": 12.5, "end": 12.9, "word": "站口"},
                {"start": 12.9, "end": 13.3, "word": "拉客"},
                {"start": 13.3, "end": 13.7, "word": "的"},
                {"start": 13.7, "end": 14.1, "word": "标价"},
                {"start": 14.1, "end": 14.5, "word": "车"},
                {"start": 14.5, "end": 15.0, "word": "千万别上"},
            ],
        }
    ]
    clips, debug = build_subtitle_clips_from_asr(
        spoken,
        config=_cfg(clip_max_duration=2.5, clip_max_chars=12, clip_target_duration=1.8),
    )
    assert len(clips) >= 2
    joined = "".join(c["text"] for c in clips)
    assert joined == spoken[0]["text"]
    assert debug["subtitleClipCount"] == len(clips)
    texts = [c["text"] for c in clips]
    assert not any(texts.count(t) > 1 for t in texts if len(t) > 4)


def test_punctuation_split():
    spoken = [
        {
            "id": "s1",
            "start": 0.0,
            "end": 6.0,
            "text": "大家好。欢迎来到成都",
            "type": "spoken_caption",
            "words": [
                {"start": 0.0, "end": 1.0, "word": "大家"},
                {"start": 1.0, "end": 1.5, "word": "好。"},
                {"start": 2.0, "end": 3.0, "word": "欢迎"},
                {"start": 3.0, "end": 4.0, "word": "来到"},
                {"start": 4.0, "end": 5.0, "word": "成都"},
            ],
        }
    ]
    clips, debug = build_subtitle_clips_from_asr(spoken, config=_cfg())
    assert len(clips) >= 2
    assert debug["punctuationSplitCount"] >= 1


def test_pause_split():
    spoken = [
        {
            "id": "s1",
            "start": 0.0,
            "end": 8.0,
            "text": "第一段话第二段话",
            "type": "spoken_caption",
            "words": [
                {"start": 0.0, "end": 1.0, "word": "第一"},
                {"start": 1.0, "end": 2.0, "word": "段话"},
                {"start": 2.8, "end": 3.8, "word": "第二"},
                {"start": 3.8, "end": 4.8, "word": "段话"},
            ],
        }
    ]
    clips, _ = build_subtitle_clips_from_asr(
        spoken,
        config=_cfg(clip_pause_threshold_sec=0.35, clip_max_duration=10, clip_max_chars=30),
    )
    assert len(clips) >= 2


def test_merge_short_clips():
    spoken = [
        {
            "id": "s1",
            "start": 0.0,
            "end": 3.0,
            "text": "好。嗯",
            "type": "spoken_caption",
            "words": [
                {"start": 0.0, "end": 0.4, "word": "好。"},
                {"start": 0.5, "end": 0.7, "word": "嗯"},
            ],
        }
    ]
    clips, debug = build_subtitle_clips_from_asr(
        spoken,
        config=_cfg(clip_min_duration=0.8, clip_min_chars=4, clip_merge_gap_sec=0.25),
    )
    assert len(clips) == 1
    assert debug["mergedShortCount"] >= 0


def test_no_words_no_duplicate_text():
    spoken = [
        {"id": "s1", "start": 0.0, "end": 9.0, "text": "abcdefghi", "type": "spoken_caption"},
    ]
    clips, _ = build_subtitle_clips_from_asr(
        spoken,
        config=_cfg(clip_max_chars=4, clip_max_duration=3, clip_use_word_timestamps=False),
    )
    joined = "".join(c["text"] for c in clips)
    assert joined == "abcdefghi"
    assert len(clips) >= 2


def test_clips_independent_of_slots():
    spoken = [{"id": "s1", "start": 0, "end": 2, "text": "测试", "type": "spoken_caption", "words": [{"start": 0, "end": 2, "word": "测试"}]}]
    clips, _ = build_subtitle_clips_from_asr(spoken)
    assert clips[0]["clipType"] == "subtitle_clip"
    assert clips[0]["text"] == "测试"


def test_master_segments_unchanged():
    spoken = [
        {
            "id": "s1",
            "start": 0.0,
            "end": 5.0,
            "text": "原始主轨不变",
            "type": "spoken_caption",
            "words": [{"start": 0, "end": 5, "word": "原始主轨不变"}],
        }
    ]
    original = spoken[0]["text"]
    build_subtitle_clips_from_asr(spoken)
    assert spoken[0]["text"] == original


def test_each_word_assigned_once():
    spoken = [
        {
            "id": "s1",
            "start": 0.0,
            "end": 6.0,
            "text": "ABCDEF",
            "type": "spoken_caption",
            "words": [
                {"start": 0.0, "end": 1.0, "word": "AB"},
                {"start": 1.0, "end": 2.0, "word": "CD"},
                {"start": 2.0, "end": 3.0, "word": "EF"},
            ],
        }
    ]
    clips, _ = build_subtitle_clips_from_asr(
        spoken,
        config=_cfg(clip_max_chars=3, clip_max_duration=1.5, clip_target_duration=1.0),
    )
    ids = []
    for c in clips:
        ids.extend(c.get("linkedWordIds") or [])
    assert len(ids) == len(set(ids))
