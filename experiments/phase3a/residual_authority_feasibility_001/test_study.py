"""Offline tests for the frozen authority gate; no simulation or actor loading."""
from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROFILES = (
    "lateral_inward", "yaw_inward", "combined_inward", "corner_forward_inward",
    "late_combined_inward", "yaw_return_lateral_inward",
)
EXPECTED = {
    "lateral_inward": [0.0, -1.0, 0.0],
    "yaw_inward": [0.0, 0.0, -1.0],
    "combined_inward": [0.0, -1.0, -1.0],
    "corner_forward_inward": [1.0, -1.0, -1.0],
    "late_combined_inward": [0.0, -1.0, -1.0],
    "yaw_return_lateral_inward": [0.0, -1.0, -1.0],
}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def study():
    # Importing declarations is permitted; no FrameRunner is constructed here.
    sys.path.insert(0, str(ROOT))
    return load_module("authority_gate_study_offline_test", HERE / "study.py")


@pytest.fixture(scope="module")
def protocol():
    return json.loads((HERE / "protocol.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def auditor():
    return load_module("authority_gate_auditor_offline_test", HERE / "audit.py")


@pytest.fixture(scope="module")
def retained_baseline():
    path = ROOT / "experiments/phase3a/correction_tradeoff_isolation_001/evidence/results.jsonl.gz"
    rows = [json.loads(line) for line in gzip.decompress(path.read_bytes()).decode("utf-8").splitlines()]
    return next(row for row in rows if row["case_id"] == "sequence-mixed-16m"
                and row["alpha"] == 0.5 and row["phase"] == "primary")


def synthetic_gate_candidate(retained_baseline):
    """Logical classifier fixture only, never a simulated/scored robot result."""
    candidate = copy.deepcopy(retained_baseline)
    candidate.update(run_id="synthetic-primary", probe_id="combined_inward", repetition=0,
                     residual_enabled=True, PPO_training=False)
    for node in candidate["nodes"]:
        node["strict_success"] = True
    # The retained fixed-world final y error is negative; +0.1m reduces its
    # magnitude and endpoint norm without changing heading. This is synthetic.
    candidate["final_state"]["base_position"][1] += 0.1
    candidate["nodes"][-1]["end_state"]["base_position"][1] += 0.1
    return candidate


def synthetic_confirmation(candidate):
    confirmation = copy.deepcopy(candidate)
    confirmation.update(run_id="synthetic-confirmation", repetition=1)
    return confirmation


@pytest.mark.parametrize("probe_id", PROFILES)
@pytest.mark.parametrize("node_index,skill,tick", [
    (0, "walk_forward", 0), (2, "walk_forward", 0), (3, "walk_forward", 0),
    (5, "walk_forward", 0), (1, "stand", 0), (1, "turn", 0),
    (1, "stop", 0), (1, "walk_forward", -1), (1, "walk_forward", 20),
    (1, "walk_forward", 21), (1, "walk_forward", 170),
])
def test_profiles_have_no_authority_outside_declared_node_skill_or_window(
    study, probe_id, node_index, skill, tick,
):
    actual = study.profile_action(probe_id, node_index, skill, tick)
    np.testing.assert_array_equal(actual, np.zeros(3))


@pytest.mark.parametrize("probe_id", ["off", "zero"])
@pytest.mark.parametrize("tick", [0, 9, 10, 19, 20])
def test_control_callbacks_are_exact_zero(study, probe_id, tick):
    np.testing.assert_array_equal(study.profile_action(probe_id, 1, "walk_forward", tick), np.zeros(3))


@pytest.mark.parametrize("probe_id", PROFILES)
@pytest.mark.parametrize("tick", [0, 9, 10, 19])
def test_frozen_profile_actions_and_switches(study, probe_id, tick):
    expected = EXPECTED[probe_id]
    if probe_id == "late_combined_inward" and tick < 10:
        expected = [0.0, 0.0, 0.0]
    if probe_id == "yaw_return_lateral_inward" and tick >= 10:
        expected = [0.0, -1.0, 1.0]
    actual = study.profile_action(probe_id, 1, "walk_forward", tick)
    assert isinstance(actual, np.ndarray)
    assert actual.shape == (3,) and np.isfinite(actual).all()
    np.testing.assert_array_equal(actual, expected)
    assert np.all(np.abs(actual) <= 1.0)
    assert np.all(np.abs(actual * np.array([0.1, 0.06, 0.12])) <= np.array([0.1, 0.06, 0.12]))


@pytest.mark.parametrize("probe_id", PROFILES)
def test_callback_does_not_return_shared_mutable_action_template(study, probe_id):
    before = study.profile_action(probe_id, 1, "walk_forward", 10).copy()
    candidate = study.profile_action(probe_id, 1, "walk_forward", 10)
    candidate[:] = 7.0
    np.testing.assert_array_equal(study.profile_action(probe_id, 1, "walk_forward", 10), before)


def test_unknown_profile_fails_closed(study):
    with pytest.raises((ValueError, KeyError)):
        study.profile_action("not_a_frozen_probe", 1, "walk_forward", 0)


def test_scientific_comparer_discards_only_execution_annotations(study):
    science = {
        "task_success": True, "physical_success": True,
        "nodes": [{"strict_success": False, "lateral_drift_m": 0.372292,
                   "envelope": {"strict_envelope": {"limits": {"lateral_drift_max_m": 0.28}}},
                   "skill_metrics": {"elapsed_wall_time_s": 4.0, "elapsed_sim_time_s": 17.08}}],
        "trace": [{"active": False, "applied_command": [0.5, 0.0, 0.01]}],
    }
    annotated = copy.deepcopy(science)
    annotated["wall_time_s"] = 8.0
    annotated["nodes"][0]["skill_metrics"]["elapsed_wall_time_s"] = 9.0
    annotated["trace"][0]["active"] = True
    original = copy.deepcopy(science)
    assert study.scientific(science) == study.scientific(annotated)
    assert science == original


@pytest.mark.parametrize("field,changed", [
    ("task_success", False), ("physical_success", False),
    ("strict_success", False), ("fallen", True), ("status", "TIMEOUT"),
    ("simulation_steps", 8510), ("total_sim_time_s", 49.0),
    ("lateral_drift_m", 0.281), ("heading_error_deg", 8.01),
    ("ideal_endpoint_error_m", 1.21), ("applied_command", [0.5, 0.0, 0.12]),
    ("residual", [0.0, -0.06, 0.0]), ("action", [0.0, -1.0, 0.0]),
    ("walking_reference", {"measurement_heading_rad": 0.1, "control_heading_rad": 0.05}),
    ("envelope", {"strict_envelope": {"limits": {"lateral_drift_max_m": 0.3}}}),
    ("start_state", {"base_position": [0.0, 0.01, 0.78]}),
    ("end_state", {"base_position": [8.0, 0.29, 0.78]}),
    ("memory_reset_count", 2),
])
def test_scientific_comparer_preserves_every_critical_difference(study, field, changed):
    original = {field: None}
    altered = {field: changed}
    assert study.scientific(original) != study.scientific(altered)


def test_predeclared_contract_and_budget_cannot_be_nominalized_after_probe(protocol):
    assert protocol["class"] == "Experimental" and protocol["frozen"] is True
    assert protocol["reference_alpha"] == 0.5
    assert protocol["local_claim"].startswith("STRICT endpoint eligibility on all original nodes")
    assert "nominal independent secondary" in protocol["local_claim"]
    assert "complete physical success" in protocol["physical_claim"]
    assert protocol["authority"]["window_s"] == 2.0
    assert protocol["authority"]["decision_period_s"] == 0.1
    assert protocol["authority"]["physical_bounds"] == [0.1, 0.06, 0.12]
    assert protocol["authority"]["total_yaw_limit_radps"] == 0.6
    assert [p["id"] for p in protocol["probes_in_order"]] == list(PROFILES)
    assert protocol["budget"]["maximum_complete_case_executions"] == 9
    assert protocol["budget"]["training_steps"] == protocol["budget"]["provider_calls"] == 0
    assert protocol["budget"]["checkpoint_writes"] == 0
    assert protocol["budget"]["alpha_scan"] is False
    assert "command integrals are not such proof" in protocol["verdict_rules"]["NOT_FEASIBLE"]
    assert "no full-space certificate" in protocol["verdict_rules"]["INCONCLUSIVE"]


def test_case_and_semantics_source_hashes_are_bound_before_physics(protocol):
    assert hashlib.sha256((HERE / "case.json").read_bytes()).hexdigest() == protocol["case_sha256"]
    contract = ROOT / "experiments/phase3a/spatial_contract_semantics_001/contract.json"
    assert hashlib.sha256(contract.read_bytes()).hexdigest() == protocol["contract_sha256"]
    manifest = HERE / "source_manifest.json"
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == protocol["source_manifest_sha256"]
    case = json.loads((HERE / "case.json").read_text(encoding="utf-8"))
    assert case["id"] == "sequence-mixed-16m"
    assert [n["skill"] for n in case["nodes"]] == [
        "stand", "walk_forward", "turn", "walk_forward", "turn", "walk_forward", "stop",
    ]
    assert case["nodes"][0]["parameters"]["duration_s"] == 10.0
    assert case["nodes"][1]["parameters"]["target_distance_m"] == 8.0
    assert [n["parameters"]["target_distance_m"] for n in case["nodes"] if n["skill"] == "walk_forward"] == [8.0, 4.0, 4.0]


def test_failed_finite_profiles_do_not_prove_authority_impossibility(auditor, retained_baseline, protocol):
    primary = copy.deepcopy(retained_baseline)
    primary.update(run_id="synthetic-negative", probe_id="combined_inward", repetition=0)
    result = auditor.summarize([primary, synthetic_confirmation(primary)], retained_baseline, protocol)
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["full_space_infeasibility_certificate"] is False
    assert not any(row["joint_qualifier"] for row in result["runs"])


def test_joint_witness_requires_exact_confirmation(auditor, retained_baseline, protocol):
    primary = synthetic_gate_candidate(retained_baseline)
    single = auditor.summarize([primary], retained_baseline, protocol)
    assert single["runs"][0]["joint_qualifier"] is True
    assert single["verdict"] == "INCONCLUSIVE"
    confirmed = auditor.summarize([primary, synthetic_confirmation(primary)], retained_baseline, protocol)
    assert confirmed["verdict"] == "FEASIBLE"
    assert confirmed["repeated_joint_witnesses"][0]["exact_scientific_record"] is True


@pytest.mark.parametrize("defect", ["strict", "physical", "incomplete", "status", "heading", "roundoff"])
def test_joint_gate_rejects_failed_independent_contract_or_unresolved_gain(
    auditor, retained_baseline, protocol, defect,
):
    candidate = synthetic_gate_candidate(retained_baseline)
    if defect == "strict":
        candidate["nodes"][1]["strict_success"] = False
    elif defect == "physical":
        candidate["physical_success"] = False
    elif defect == "incomplete":
        candidate["nodes"].pop()
    elif defect == "status":
        candidate["nodes"][1]["status"] = "TIMEOUT"
    elif defect == "heading":
        candidate["final_state"]["base_orientation"] = [math.cos(0.1), 0.0, 0.0, math.sin(0.1)]
    elif defect == "roundoff":
        candidate["final_state"] = copy.deepcopy(retained_baseline["final_state"])
        candidate["final_state"]["base_position"][1] += protocol["roundoff_audit_tolerance"] / 10
    result = auditor.summarize([candidate, synthetic_confirmation(candidate)], retained_baseline, protocol)
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["full_space_infeasibility_certificate"] is False
    assert not any(row["joint_qualifier"] for row in result["runs"])


def test_confirmation_cannot_ignore_scientific_geometry_change(auditor, retained_baseline, protocol):
    primary = synthetic_gate_candidate(retained_baseline)
    confirmation = synthetic_confirmation(primary)
    confirmation["nodes"][1]["max_tilt_deg"] += 0.001
    result = auditor.summarize([primary, confirmation], retained_baseline, protocol)
    assert all(row["joint_qualifier"] for row in result["runs"])
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["repeated_joint_witnesses"][0]["exact_scientific_record"] is False


def test_missing_required_world_evidence_does_not_default_to_pass(auditor, retained_baseline, protocol):
    candidate = synthetic_gate_candidate(retained_baseline)
    del candidate["final_state"]
    with pytest.raises(KeyError):
        auditor.summarize([candidate], retained_baseline, protocol)
