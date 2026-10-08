"""Synthetic tests only: case separation and offline paired analysis."""
from __future__ import annotations

from collections import Counter
import copy
import json

import pytest

from g1swarm.transition_learning.cases import TRAIN_CASES, EVAL_CASES, PRIMITIVE_CASES, SEQUENCE_CASES
from g1swarm.transition_learning.analysis import summarize_results, compare_results


def _fingerprint(case):
    return json.dumps({key: case[key] for key in ("nodes", "initial_yaw_deg")}, sort_keys=True)


def test_counts_and_parameter_disjoint_splits():
    assert len(TRAIN_CASES) == 12 and len(EVAL_CASES) == 16
    assert len(PRIMITIVE_CASES) == 8 and len(SEQUENCE_CASES) == 2
    for cases, count in ((TRAIN_CASES, 3), (EVAL_CASES, 4)):
        assert Counter(case["transition"] for case in cases) == {
            "walk_to_turn": count, "turn_to_walk": count,
            "walk_to_stop": count, "stand_to_walk": count,
        }
        assert len({_fingerprint(case) for case in cases}) == len(cases)
    assert not {_fingerprint(case) for case in TRAIN_CASES} & {_fingerprint(case) for case in EVAL_CASES}
    all_cases = TRAIN_CASES + EVAL_CASES + PRIMITIVE_CASES + SEQUENCE_CASES
    assert len({case["id"] for case in all_cases}) == len(all_cases)


def test_original_thresholds_and_skill_lifecycle():
    for case in TRAIN_CASES + EVAL_CASES + PRIMITIVE_CASES + SEQUENCE_CASES:
        for node in case["nodes"]:
            p = node["parameters"]
            if node["skill"] == "walk_forward":
                distance = p["target_distance_m"]
                assert p["tolerance_m"] == max(0.2, 0.1 * distance)
                assert p["max_duration_s"] == max(15, 6 * distance)
                assert p["speed_mps"] == 0.5 and p["reset_memory"] is True
            elif node["skill"] == "turn":
                assert p["yaw_rate_radps"] == 0.5 and p["tolerance_deg"] == 15
                assert p["max_duration_s"] == 10 and p["settle_s"] == 0.5
            elif node["skill"] == "stop":
                assert p == {"window_s": 1.0, "speed_threshold_mps": 0.10, "max_duration_s": 4.0}
            else:
                assert node["skill"] == "stand" and 0 < p["duration_s"] <= 20


def test_primitive_and_unseen_sequences_are_separate():
    assert all(len(case["nodes"]) == 1 for case in PRIMITIVE_CASES)
    for case in SEQUENCE_CASES:
        assert {node["skill"] for node in case["nodes"]} == {"stand", "walk_forward", "turn", "stop"}
        assert sum(node["parameters"]["target_distance_m"] for node in case["nodes"]
                   if node["skill"] == "walk_forward") >= 12
    assert any(node["parameters"].get("duration_s") == 10
               for case in SEQUENCE_CASES for node in case["nodes"])


def _record(treatment, label=None, case_id="case-1", task=True, drift=0.1):
    record = {"treatment": treatment, "case_id": case_id, "group": "transition",
              "transition": "walk_to_turn", "evaluation_set": "heldout_transition",
              "task_success": task, "physical_success": True, "total_sim_time_s": 4.0,
              "failure_taxonomy": ["SUCCESS"] if task else ["HEADING_ERROR"],
              "nodes": [{"skill": "turn", "parameters": {"target_angle_deg": 45},
                         "heading_error_deg": 2.0, "lateral_drift_m": drift,
                         "ideal_path_heading_error_deg": 3.0, "ideal_path_lateral_error_m": drift,
                         "fallen": False, "max_tilt_deg": 4.0, "min_height_m": 0.7,
                         "transition_metrics": {"eligible": True, "duration_s": 2.0,
                             "completion_duration_s": 4.0, "heading_change_deg": 47.0,
                             "lateral_change_m": drift, "speed_rms_mps": 0.2,
                             "final_speed_mps": 0.1, "max_tilt_deg": 4.0, "min_height_m": 0.7}}]}
    if label is not None:
        record["treatment_label"] = label
    return record


def test_summary_keeps_seeds_and_rotation_separate():
    result = summarize_results([_record("learned", "train-seed11"),
                                _record("learned", "train-seed29", task=False)])
    assert set(result["by_treatment"]) == {"train-seed11", "train-seed29"}
    metrics = result["by_treatment"]["train-seed11"]["overall"]["metrics"]
    assert metrics["turn_mean_abs_heading_error_deg"]["mean"] == 2
    assert metrics["transition_mean_heading_change_deg"]["mean"] == 47
    assert metrics["transition_mean_window_duration_s"]["mean"] == 2
    assert metrics["transition_mean_completion_duration_s"]["mean"] == 4
    assert "not heading error" in result["metric_interpretation"]["transition_mean_heading_change_deg"]
    assert result["by_treatment"]["train-seed29"]["overall"]["physical_success_task_failure"] == 1


def test_comparison_pairs_each_seed_and_reports_regression():
    records = [_record("deterministic_correction"),
               _record("learned", "train-seed11", drift=0.05),
               _record("learned", "train-seed29", task=False, drift=0.2)]
    result = compare_results(records)
    assert result["baseline_cases"] == 1 and result["improvement_threshold"] is None
    good = result["by_treatment"]["train-seed11"]
    bad = result["by_treatment"]["train-seed29"]
    assert good["pair_coverage_complete"] and good["overall"]["paired_cases"] == 1
    assert good["pairs"][0]["metrics"]["ideal_path_mean_abs_lateral_error_m"]["candidate_minus_baseline"] == pytest.approx(-0.05)
    assert bad["overall"]["task_pass_to_fail"] == 1
    assert bad["overall"]["physical_pass_to_fail"] == 0


def test_missing_metrics_and_pair_coverage_are_not_imputed():
    baseline, candidate = _record("deterministic_correction"), _record("learned", "train-seed11")
    candidate["nodes"][0]["ideal_path_lateral_error_m"] = None
    candidate["nodes"][0]["transition_metrics"]["eligible"] = False
    extra = _record("learned", "train-seed11", case_id="extra")
    result = compare_results([baseline, candidate, extra])
    comparison = result["by_treatment"]["train-seed11"]
    assert comparison["candidate_only_ids"] == ["extra"] and not comparison["pair_coverage_complete"]
    assert comparison["pairs"][0]["metrics"]["ideal_path_mean_abs_lateral_error_m"]["candidate_minus_baseline"] is None
    assert comparison["pairs"][0]["metrics"]["transition_mean_heading_change_deg"]["candidate"] is None
    summary = summarize_results([candidate])["by_treatment"]["train-seed11"]["overall"]["metrics"]
    assert summary["ideal_path_mean_abs_lateral_error_m"]["n"] == 0
    assert summary["ideal_path_mean_abs_lateral_error_m"]["missing_or_non_finite"] == 1


def test_pair_duplicates_and_mismatched_metadata_raise():
    baseline, candidate = _record("deterministic_correction"), _record("learned", "train-seed11")
    with pytest.raises(ValueError, match="duplicate treatment/case"):
        compare_results([baseline, candidate, copy.deepcopy(candidate)])
    candidate["transition"] = "turn_to_walk"
    with pytest.raises(ValueError, match="metadata mismatch"):
        compare_results([baseline, candidate])


def test_empty_and_missing_baseline_are_explicit():
    assert summarize_results([])["record_count"] == 0
    empty = compare_results([])
    assert not empty["baseline_available"] and empty["baseline_cases"] == 0
    result = compare_results([_record("learned", "train-seed11")])
    assert result["by_treatment"]["train-seed11"]["overall"]["paired_cases"] == 0


def test_tracking_diagnostics_keep_nulls_distinct_from_zero_and_window_end():
    baseline = _record("deterministic_correction")
    candidate = _record("learned", "train-seed11")
    baseline["nodes"][0]["transition_metrics"].update(
        angular_speed_rms_radps=0.5, standing_fraction=0.9,
        sustained_tracking_recovery_s=None, final_speed_mps=0.3,
        next_skill_final_speed_mps=0.1,
    )
    candidate["nodes"][0]["transition_metrics"].update(
        angular_speed_rms_radps=0.2, standing_fraction=1.0,
        sustained_tracking_recovery_s=0.0, final_speed_mps=0.2,
        next_skill_final_speed_mps=0.05,
    )
    pair = compare_results([baseline, candidate])["by_treatment"]["train-seed11"]["pairs"][0]
    metrics = pair["metrics"]
    assert metrics["transition_mean_angular_speed_rms_radps"]["candidate_minus_baseline"] == pytest.approx(-0.3)
    assert metrics["transition_mean_standing_fraction"]["candidate_minus_baseline"] == pytest.approx(0.1)
    recovery = metrics["transition_mean_sustained_tracking_recovery_s"]
    assert recovery["baseline"] is None and recovery["candidate"] == 0
    assert recovery["candidate_minus_baseline"] is None
    assert metrics["transition_mean_final_speed_mps"]["candidate"] == 0.2
    assert metrics["transition_mean_next_skill_final_speed_mps"]["candidate"] == 0.05
    coverage = pair["transition_diagnostic_coverage"]
    assert coverage["baseline"]["sustained_tracking_recovery_s"]["null_or_non_finite_windows"] == 1
    assert coverage["candidate"]["sustained_tracking_recovery_s"]["observed_windows"] == 1


def test_sequence_partial_recovery_coverage_remains_explicit():
    record = _record("learned", "train-seed11")
    first = record["nodes"][0]
    first["transition_metrics"]["sustained_tracking_recovery_s"] = None
    second = copy.deepcopy(first)
    second["transition_metrics"]["sustained_tracking_recovery_s"] = 1.2
    record["nodes"].append(second)
    summary = summarize_results([record])["by_treatment"]["train-seed11"]["overall"]
    assert summary["metrics"]["transition_mean_sustained_tracking_recovery_s"]["mean"] == 1.2
    assert summary["transition_diagnostic_coverage"]["sustained_tracking_recovery_s"] == {
        "eligible_windows": 2, "observed_windows": 1, "null_or_non_finite_windows": 1,
    }
