"""Unit tests for subtitle golden-set metrics (no video required)."""

from services.subtitle_golden_eval import (
    case_passed,
    duplicate_rate,
    evaluate_case_metrics,
    load_expected,
    nonempty_rate,
    slot_match_rate,
)


def test_nonempty_rate():
    slots = [{"subtitle_text": "a"}, {"subtitle_text": ""}, {"subtitle_text": "b"}]
    assert nonempty_rate(slots) == 2 / 3


def test_duplicate_rate_exact():
    slots = [
        {"subtitle_text": "重复的句子在这里"},
        {"subtitle_text": "重复的句子在这里"},
        {"subtitle_text": "不同内容"},
    ]
    assert duplicate_rate(slots) == 1 / 3


def test_duplicate_rate_fuzzy():
    a = "今天我们去北京旅游很开心"
    b = "今天我们去北京旅游，很开心"
    slots = [
        {"subtitle_text": a},
        {"subtitle_text": b},
        {"subtitle_text": "完全不同的一段字幕内容"},
    ]
    assert duplicate_rate(slots) == 1 / 3


def test_slot_match_rate_partial():
    actual = [{"subtitle_text": "你好世界"}, {"subtitle_text": ""}]
    expected = [{"subtitle_text": "你好世界！"}, {"subtitle_text": ""}]
    assert slot_match_rate(actual, expected) == 1.0


def test_evaluate_case_metrics_with_expected():
    actual = [{"subtitle_text": "A", "subtitle_source": "visual"}]
    expected = [{"subtitle_text": "A"}]
    m = evaluate_case_metrics(actual, expected)
    assert m["nonempty_rate"] == 1.0
    assert m["slot_match_rate"] == 1.0
    assert m["source_distribution"]["visual"] == 1


def test_case_passed_threshold():
    metrics = {"nonempty_rate": 0.9, "duplicate_rate": 0.0, "slot_match_rate": 0.95}
    ok, reasons = case_passed(metrics, {"min_nonempty_rate": 0.85, "max_duplicate_rate": 0.1})
    assert ok
    assert not reasons


def test_load_expected_list_and_object(tmp_path):
    p = tmp_path / "exp.json"
    p.write_text('[{"subtitle_text":"x"}]', encoding="utf-8")
    assert len(load_expected(p)) == 1
