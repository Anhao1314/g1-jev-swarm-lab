"""Stage A regression tests for the Phase 1.2b evaluator-input bug.

The audit found that segmentation missions stored ``final_lateral_drift_m`` /
``final_heading_error_deg`` while the shared walk-envelope evaluator reads
``lateral_drift_m`` / ``heading_error_deg``; the missing keys defaulted to
``+inf`` and produced spurious EXCESSIVE_DRIFT / HEADING_ERROR verdicts.

These tests pin (a) the historical bug shape, (b) the corrected behaviour and
(c) the nominal-vs-strict semantics that the audit had to verify.
"""

from __future__ import annotations

from g1swarm.boundary.envelope import evaluate_walk_task, failure_type_from_violations
from g1swarm.segmentation.runner import SegmentationRunner, build_segmentation_comparison

# Raw values from artifacts/g1_distance_segmentation_001/final/direct_long-4m-final-seed000
CASE1_TARGET_M = 4.0
CASE1_DRIFT_M = -0.28142439922706486
CASE1_HEADING_DEG = -6.719698642668926
CASE1_DISTANCE_ERROR_M = 6.476481383899113e-05
CASE1_TIME_S = 8.705999999999577


def _canonical_metrics() -> dict:
    return {
        "absolute_distance_error_m": CASE1_DISTANCE_ERROR_M,
        "completion_sim_time_s": CASE1_TIME_S,
        "lateral_drift_m": CASE1_DRIFT_M,
        "heading_error_deg": CASE1_HEADING_DEG,
    }


def test_four_meter_case_satisfies_nominal_envelope() -> None:
    evaluation = evaluate_walk_task(_canonical_metrics(), CASE1_TARGET_M, physical=True)
    assert evaluation["task_success"] is True
    assert evaluation["task_violations"] == []
    assert evaluation["strict_violation"] is True  # drift exceeds the strict limit


def test_final_star_keys_alone_reproduce_the_original_bug() -> None:
    broken = {
        "final_forward_progress_m": CASE1_TARGET_M,
        "final_lateral_drift_m": CASE1_DRIFT_M,
        "final_heading_error_deg": CASE1_HEADING_DEG,
        "absolute_distance_error_m": CASE1_DISTANCE_ERROR_M,
        "completion_sim_time_s": CASE1_TIME_S,
    }
    evaluation = evaluate_walk_task(broken, CASE1_TARGET_M, physical=True)
    assert evaluation["task_success"] is False
    assert "EXCESSIVE_DRIFT" in evaluation["task_violations"]
    assert "HEADING_ERROR" in evaluation["task_violations"]
    assert evaluation["nominal_envelope"]["lateral_drift_m"] == float("inf")


def test_task_success_uses_the_nominal_envelope() -> None:
    strict_only = dict(_canonical_metrics(), lateral_drift_m=0.25)
    evaluation = evaluate_walk_task(strict_only, CASE1_TARGET_M, physical=True)
    assert evaluation["task_success"] is True
    assert evaluation["strict_violation"] is True
    failing = dict(_canonical_metrics(), lateral_drift_m=0.45)
    evaluation = evaluate_walk_task(failing, CASE1_TARGET_M, physical=True)
    assert evaluation["task_success"] is False
    assert evaluation["task_violations"] == ["EXCESSIVE_DRIFT"]


def test_failure_type_comes_from_the_nominal_violation_set() -> None:
    passing = evaluate_walk_task(dict(_canonical_metrics(), lateral_drift_m=0.34), 4.0, physical=True)
    assert failure_type_from_violations(passing["task_violations"]) == "TASK_ENVELOPE_VIOLATION"
    failing = evaluate_walk_task(dict(_canonical_metrics(), lateral_drift_m=0.355), 4.0, physical=True)
    assert failure_type_from_violations(failing["task_violations"]) == "EXCESSIVE_DRIFT"


def test_boundary_and_mission_shapes_evaluate_identically() -> None:
    boundary_shape = _canonical_metrics()  # exactly what BoundaryRunner stores
    mission_shape = dict(
        boundary_shape,
        final_forward_progress_m=CASE1_TARGET_M,
        final_lateral_drift_m=CASE1_DRIFT_M,
        final_heading_error_deg=CASE1_HEADING_DEG,
        total_simulation_time_s=CASE1_TIME_S,
    )
    for shape in (boundary_shape, mission_shape):
        evaluation = evaluate_walk_task(shape, CASE1_TARGET_M, physical=True)
        assert evaluation["task_success"] is True
        assert evaluation["task_violations"] == []
        assert evaluation["nominal_envelope"]["lateral_drift_m"] == abs(CASE1_DRIFT_M)


def test_mission_metrics_and_comparison_use_canonical_values(
    tmp_path, monkeypatch, locomotion_robot: dict
) -> None:
    monkeypatch.setenv("G1SWARM_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    runner = SegmentationRunner(
        "configs/experiments/g1_distance_segmentation_001.yaml", campaign="pilot"
    )
    record = runner.run_mission("direct_long", 4.0, phase="pilot", seed=0)
    metrics = record["metrics"]
    assert metrics["lateral_drift_m"] == metrics["final_lateral_drift_m"]
    assert metrics["heading_error_deg"] == metrics["final_heading_error_deg"]
    assert metrics["forward_displacement_m"] == metrics["final_forward_progress_m"]
    assert metrics["task_success"] is True, metrics["failure_reason"]
    comparison = build_segmentation_comparison(runner.protocol, runner.records)
    entry = comparison["distances"]["4"]["treatments"]["direct_long"]
    assert entry["lateral_drift_m"] == metrics["lateral_drift_m"]
    assert entry["heading_error_deg"] == metrics["heading_error_deg"]
