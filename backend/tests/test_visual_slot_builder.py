"""按原视频画面镜头切分槽位测试。"""

from services.visual_slot_builder import build_slots_from_visual_shots


def test_build_slots_from_visual_shots_links_captions_by_overlap():
    shots = [
        {"start": 0.0, "end": 3.0, "duration": 3.0, "shot_type": "wide"},
        {"start": 3.0, "end": 6.5, "duration": 3.5, "shot_type": "medium"},
    ]
    clips = [
        {"id": "cap_1", "start": 0.2, "end": 2.8, "text": "第一句"},
        {"id": "cap_2", "start": 3.1, "end": 5.0, "text": "第二句"},
        {"id": "cap_3", "start": 5.0, "end": 6.2, "text": "第三句"},
    ]
    slots, debug = build_slots_from_visual_shots(shots, clips)
    assert len(slots) == 2
    assert slots[0]["source"] == "visual_scene_split"
    assert slots[0]["cut_reason"] == "pyscenedetect"
    assert slots[0]["linkedCaptionClipId"] == "cap_1"
    assert slots[0]["subtitle_text"] == "第一句"
    assert slots[1]["linkedCaptionClipId"] == "cap_2"
    assert len(slots[1]["subtitle_segments"]) == 2
    assert debug[1]["linkedCaptionCount"] == 2
