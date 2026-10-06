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


def test_summarize_ignores_string_task_robustness_records(tmp_path, monkeypatch) -> None:
    """Regression: robustness task keys must not break nominal aggregation."""

    monkeypatch.setenv("G1SWARM_ARTIFACTS_DIR", str(tmp_path))
    runner = CharacterizationRunner(
        "configs/experiments/g1_skill_characterization_001.yaml", campaign="final"
    )
    runner.results = [
        {
            "run_id": "a1-walk-2m-rep0-seed000",
            "skill": "walk_forward",
            "task": 2.0,
            "condition": "nominal",
            "seed": 0,
            "success": True,
            "failure_type": "SUCCESS",
            "failure_reason": None,
            "metrics": {
                "forward_displacement_m": 2.0,
                "absolute_distance_error_m": 0.0,
                "lateral_drift_m": -0.3,
                "heading_error_deg": -1.0,
                "completion_sim_time_s": 4.0,
                "mean_speed_mps": 0.5,
                "residual_speed_mps": 0.4,
            },
        },
        {
            "run_id": "c-walk_forward_2m-nominal-seed001",
            "skill": "walk_forward",
            "task": "walk_forward_2m",
            "condition": "nominal",
            "seed": 1,
            "success": True,
            "failure_type": "SUCCESS",
            "failure_reason": None,
            "metrics": {
                "task_key": "walk_forward_2m",
                "forward_displacement_m": 2.1,
                "absolute_distance_error_m": 0.1,
                "lateral_drift_m": -0.2,
                "heading_error_deg": -1.1,
                "completion_sim_time_s": 4.1,
            },
        },
    ]
    summary = runner.summarize()
    assert summary["nominal"]["walk_forward"]["2"]["n"] == 1
    assert summary["robustness"]["walk_forward_2m"]["nominal"]["n"] == 1
