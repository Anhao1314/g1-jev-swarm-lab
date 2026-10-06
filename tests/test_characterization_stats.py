"""Statistics helpers and summary aggregation tests."""

from __future__ import annotations

import pytest

from g1swarm.characterization import bootstrap_ci, is_deterministic, summarize
from g1swarm.characterization.runner import CharacterizationRunner


def test_summarize_basic() -> None:
    stats = summarize([1.0, 2.0, 3.0])
    assert stats["n"] == 3
    assert stats["mean"] == pytest.approx(2.0)
    assert stats["median"] == pytest.approx(2.0)
    assert stats["std"] == pytest.approx(1.0)
    assert stats["min"] == pytest.approx(1.0)
    assert stats["max"] == pytest.approx(3.0)


def test_summarize_empty() -> None:
    stats = summarize([])
    assert stats["n"] == 0
    assert all(stats[key] is None for key in ("mean", "median", "std", "min", "max"))


def test_is_deterministic() -> None:
    assert is_deterministic([1.0, 1.0, 1.0])
    assert not is_deterministic([1.0, 1.0, 1.0001])
    assert is_deterministic([{"a": 1}, {"a": 1}])
    assert is_deterministic([0.5])


def test_bootstrap_interval_brackets_the_mean() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    interval = bootstrap_ci(values, samples=500, seed=0)
    assert interval is not None
    low, high = interval
    assert low <= sum(values) / len(values) <= high
    assert bootstrap_ci([1.0]) is None


def test_group_marks_deterministic_repetitions() -> None:
    record = {
        "success": True,
        "failure_type": "SUCCESS",
        "metrics": {"forward_displacement_m": 2.0, "lateral_drift_m": -0.3},
    }
    grouped = CharacterizationRunner._group([record, dict(record)], ("forward_displacement_m", "lateral_drift_m"))
    assert grouped["n"] == 2
    assert grouped["success_rate"] == 1.0
    assert grouped["deterministic_repetition"] is True
    varied = dict(record)
    varied["metrics"] = {"forward_displacement_m": 2.2, "lateral_drift_m": -0.3}
    grouped = CharacterizationRunner._group([record, varied], ("forward_displacement_m", "lateral_drift_m"))
    assert grouped["deterministic_repetition"] is False


def test_group_counts_failure_types() -> None:
    records = [
        {"success": False, "failure_type": "FALL", "metrics": {}},
        {"success": False, "failure_type": "FALL", "metrics": {}},
        {"success": False, "failure_type": "TIMEOUT", "metrics": {}},
    ]
    grouped = CharacterizationRunner._group(records, ("forward_displacement_m",))
    assert grouped["failure_counts"] == {"FALL": 2, "TIMEOUT": 1}
    assert grouped["success_rate"] == 0.0
