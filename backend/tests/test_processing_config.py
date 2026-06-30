import pytest

from services.processing_config import PROCESSING_PRESET, _PRESET_ENV
from services.resource_profile import clamp_workers, cpu_count


def test_processing_presets_defined():
    assert PROCESSING_PRESET in _PRESET_ENV or PROCESSING_PRESET == "budget"
    assert "budget" in _PRESET_ENV
    assert "standard" in _PRESET_ENV
    assert "dev" in _PRESET_ENV
    assert "quality" in _PRESET_ENV


def test_budget_preset_has_lightweight_defaults():
    budget = _PRESET_ENV["budget"]
    assert budget["WHISPER_MODEL"] == "small"
    assert budget["VOCAL_SEPARATION"] == "ffmpeg"
    assert budget["SUBTITLE_PRELOAD"] == "0"
    assert budget["ENABLE_SUBTITLE_SCENE_AI"] == "0"


def test_clamp_workers_respects_cpu():
    capped = clamp_workers(99, reserve_cores=1)
    assert 1 <= capped <= cpu_count()


def test_intake_rich_ratio_logic():
    slots = [{"ai_description": "a"}, {"ai_description": ""}, {"ai_description": "b"}]
    labeled = sum(1 for s in slots if str(s.get("ai_description") or "").strip())
    assert labeled / len(slots) >= 0.5
    assert labeled / len(slots) < 0.9
