from services.subtitle_quality import (
    count_near_duplicate_peers,
    text_similarity,
)


def test_text_similarity_identical():
    assert text_similarity("你好世界", "你好世界") == 1.0


def test_count_near_duplicate_exact():
    peers = ["重复的句子在这里"]
    assert count_near_duplicate_peers("重复的句子在这里", peers) == 1


def test_count_near_duplicate_fuzzy():
    a = "今天我们去北京旅游很开心"
    b = "今天我们去北京旅游，很开心"
    assert text_similarity(a, b) >= 0.88
    assert count_near_duplicate_peers(a, [b]) == 1


def test_count_near_duplicate_short_text_ignored():
    assert count_near_duplicate_peers("短句", ["短句"]) == 0
