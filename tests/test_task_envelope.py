"""Task envelope and physical-vs-task success tests."""

from __future__ import annotations

import pytest

from g1swarm.boundary import (
    NOMINAL_WALK_ENVELOPE,
    STRICT_WALK_ENVELOPE,
    evaluate_walk_task,
    failure_type_from_violations,
    physical_success,
)
from g1swarm.config import load_yaml


def _metrics(**overrides) -> dict:
    values = {
        "absolute_distance_error_m": 0.05,
        "lateral_drift_m": -0.10,
        "heading_error_deg": -3.0,
        "completion_sim_time_s": 4.6,
    }
    values.update(overrides)
    return values


def test_limits_scale_with_distance() -> None:
    near = NOMINAL_WALK_ENVELOPE.limits(2.0)
    far = NOMINAL_WALK_ENVELOPE.limits(10.0)
    assert near.distance_error_max_m == pytest.approx(0.30)
    assert near.lateral_max_m == pytest.approx(0.35)
    assert far.lateral_max_m == pytest.approx(0.70)
    assert far.distance_error_max_m == pytest.approx(1.00)
    assert STRICT_WALK_ENVELOPE.limits(10.0).heading_max_deg == pytest.approx(8.0)


def test_satisfied_and_violations() -> None:
    assert NOMINAL_WALK_ENVELOPE.evaluate(_metrics(), 2.0).satisfied
    drifted = NOMINAL_WALK_ENVELOPE.evaluate(_metrics(lateral_drift_m=0.9), 2.0)
    assert not drifted.satisfied and "EXCESSIVE_DRIFT" in drifted.violations
    heading = NOMINAL_WALK_ENVELOPE.evaluate(_metrics(heading_error_deg=-20.0), 2.0)
    assert "HEADING_ERROR" in heading.violations
    timeout = NOMINAL_WALK_ENVELOPE.evaluate(_metrics(completion_sim_time_s=99.0), 2.0)
    assert "TIMEOUT" in timeout.violations
    distance = NOMINAL_WALK_ENVELOPE.evaluate(_metrics(absolute_distance_error_m=1.0), 2.0)
    assert "DISTANCE_ERROR" in distance.violations


def test_physical_success_and_task_success_are_separate() -> None:
    result = evaluate_walk_task(_metrics(lateral_drift_m=1.5), 2.0, physical=True)
    assert result["physical_success"] is True
    assert result["task_success"] is False
    assert result["task_violations"] == ["EXCESSIVE_DRIFT"]
    strict_only = evaluate_walk_task(_metrics(lateral_drift_m=0.25), 2.0, physical=True)
    assert strict_only["task_success"] is True
    assert strict_only["strict_violation"] is True


def test_physical_success_predicate() -> None:
    assert physical_success(
        fallen=False, finite=True, skill_status="SUCCESS", simulation_completed=True
    )
    assert not physical_success(
        fallen=True, finite=True, skill_status="SUCCESS", simulation_completed=True
    )
    assert not physical_success(
        fallen=False, finite=False, skill_status="SUCCESS", simulation_completed=True
    )
    assert not physical_success(
        fallen=False, finite=True, skill_status="UNSAFE", simulation_completed=True
    )
    assert not physical_success(
        fallen=False, finite=True, skill_status="SUCCESS", simulation_completed=False
    )


def test_failure_type_mapping() -> None:
    assert failure_type_from_violations(["EXCESSIVE_DRIFT"]) == "EXCESSIVE_DRIFT"
    assert failure_type_from_violations(["HEADING_ERROR"]) == "HEADING_ERROR"
    assert failure_type_from_violations([]) == "TASK_ENVELOPE_VIOLATION"


def test_protocol_envelopes_match_the_frozen_module() -> None:
    protocol = load_yaml("configs/experiments/g1_failure_boundary_001.yaml")
    nominal = protocol["thresholds"]["envelopes"]["nominal"]
    strict = protocol["thresholds"]["envelopes"]["strict"]
    assert nominal["distance_error_floor_m"] == NOMINAL_WALK_ENVELOPE.distance_error_rule[0]
    assert nominal["lateral_relative"] == NOMINAL_WALK_ENVELOPE.lateral_rule[1]
    assert nominal["heading_max_deg"] == NOMINAL_WALK_ENVELOPE.heading_max_deg
    assert strict["heading_max_deg"] == STRICT_WALK_ENVELOPE.heading_max_deg
    assert strict["lateral_relative"] == STRICT_WALK_ENVELOPE.lateral_rule[1]
