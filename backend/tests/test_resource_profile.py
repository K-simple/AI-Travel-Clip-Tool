from services.resource_profile import clamp_workers, cpu_count, is_budget_target, profile_summary


def test_profile_summary_keys():
    s = profile_summary()
    assert "preset" in s
    assert "cpu_count" in s
    assert s["cpu_count"] == cpu_count()


def test_clamp_workers_minimum():
    assert clamp_workers(0, floor=1) >= 1


def test_is_budget_target():
    assert isinstance(is_budget_target(), bool)
