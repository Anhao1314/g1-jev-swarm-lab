"""Canonical metrics schema tests (Phase 1.3 audit-hardening)."""

from __future__ import annotations

import math

import pytest

from g1swarm.boundary.envelope import NOMINAL_WALK_ENVELOPE
from g1swarm.metrics import (
    REQUIRED_METRICS,
    MissingMetricError,
    RunMetrics,
    canonicalize,
    envelope_input,
    require_canonical,
)


def _canonical_metrics(**overrides) -> dict:
    values = {
        "forward_displacement_m": 4.0,
        "distance_error_m": 0.01,
        "lateral_drift_m": -0.28,
        "heading_error_deg": -6.7,
        "simulation_time_s": 8.7,
        "physical_success": True,
        "task_success": True,
        "failure_type": "SUCCESS",
        "failure_reason": None,
    }
    values.update(overrides)
    return values


def test_run_metrics_requires_and_serializes_canonical_fields() -> None:
    metrics = RunMetrics(**_canonical_metrics())
    metrics.validate()
    payload = metrics.to_dict()
    for key in REQUIRED_METRICS:
        assert key in payload
    # Historical aliases are emitted for schema continuity.
    assert payload["final_lateral_drift_m"] == payload["lateral_drift_m"]
    assert payload["final_heading_error_deg"] == payload["heading_error_deg"]
    assert payload["absolute_distance_error_m"] == payload["distance_error_m"]


def test_alias_canonicalization_and_precedence() -> None:
    aliased = canonicalize({"final_lateral_drift_m": -0.2, "final_heading_error_deg": -3.0})
    assert aliased["lateral_drift_m"] == -0.2
    assert aliased["heading_error_deg"] == -3.0
    conflicting = canonicalize({"final_lateral_drift_m": -0.9, "lateral_drift_m": -0.1})
    assert conflicting["lateral_drift_m"] == -0.1  # canonical wins


def test_missing_metric_raises_instead_of_defaulting() -> None:
    with pytest.raises(MissingMetricError) as excinfo:
        require_canonical({"lateral_drift_m": 0.1})
    assert "distance_error_m" in excinfo.value.missing
    assert "heading_error_deg" in excinfo.value.missing


def test_non_finite_metric_counts_as_missing() -> None:
    metrics = _canonical_metrics(lateral_drift_m=float("nan"))
    with pytest.raises(MissingMetricError):
        require_canonical(metrics)
    metrics = _canonical_metrics(heading_error_deg=float("inf"))
    with pytest.raises(MissingMetricError):
        require_canonical(metrics)


def test_envelope_input_maps_aliases_to_internal_names() -> None:
    mapped = envelope_input(
        {
            "absolute_distance_error_m": 0.01,
            "final_lateral_drift_m": 0.28,
            "final_heading_error_deg": -6.7,
            "completion_sim_time_s": 8.7,
        }
    )
    assert mapped == {
        "absolute_distance_error_m": 0.01,
        "lateral_drift_m": 0.28,
        "heading_error_deg": -6.7,
        "completion_sim_time_s": 8.7,
    }


def test_envelope_raises_on_missing_metrics() -> None:
    with pytest.raises(MissingMetricError):
        NOMINAL_WALK_ENVELOPE.evaluate({}, 2.0)
    with pytest.raises(MissingMetricError):
        NOMINAL_WALK_ENVELOPE.evaluate({"lateral_drift_m": 0.1}, 2.0)


def test_run_metrics_validate_rejects_non_finite() -> None:
    metrics = RunMetrics(**_canonical_metrics(lateral_drift_m=math.inf))
    with pytest.raises(MissingMetricError):
        metrics.validate()
