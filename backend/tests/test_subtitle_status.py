import pytest

from services.subtitle_status import (
    classify_slot_subtitle,
    source_label,
)


@pytest.fixture(autouse=True)
def _patch_subtitle_quality_check(monkeypatch):
    """避免测试环境缺少 FastAPI 时 security 模块导入失败。"""

    def _always_ok(text: str, duration: float, **kwargs):
        if not str(text or "").strip():
            return False, "empty"
        return True, "ok"

    monkeypatch.setattr(
        "services.subtitle_status.is_subtitle_quality_acceptable",
        _always_ok,
    )


def test_source_label_known():
    assert source_label("hybrid_visual") == "融合（偏画面）"
    assert source_label("unknown_x") == "unknown_x"


def test_classify_empty_slot():
    st = classify_slot_subtitle({"slot_id": 1}, source="none")
    assert st.quality == "empty"
    assert st.reason


def test_classify_ok_slot():
    st = classify_slot_subtitle(
        {"slot_id": 1, "subtitle_text": "你好世界", "duration": 2.0, "clip_start": 0, "clip_end": 2},
        source="hybrid_visual",
    )
    assert st.quality == "ok"


def test_classify_duplicate():
    st = classify_slot_subtitle(
        {"slot_id": 2, "subtitle_text": "重复的句子在这里", "duration": 2.0, "clip_start": 2, "clip_end": 4},
        source="whisper",
        peer_texts=["重复的句子在这里"],
    )
    assert st.duplicate is True
    assert st.quality == "low"


def test_classify_fuzzy_duplicate():
    a = "今天我们去北京旅游很开心"
    b = "今天我们去北京旅游，很开心"
    st = classify_slot_subtitle(
        {"slot_id": 2, "subtitle_text": b, "duration": 2.0, "clip_start": 2, "clip_end": 4},
        source="whisper",
        peer_texts=[a],
    )
    assert st.duplicate is True
    assert st.quality == "low"
