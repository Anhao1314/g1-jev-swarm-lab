"""Offline preregistration checks only; these tests never run physics."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("phase3b0a_preregistered_study", HERE / "study.py")
study = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(study)


def test_frozen_preflight_and_exact_state_membership():
    checked = study.preflight()
    assert checked["pinned_sources"] >= 25
    assert checked["states"] == [
        "sequence-mixed-16m:first-walk-entry:alpha0.5:seed0",
        "phase3b0a-stand5-16m:first-walk-entry:alpha0.5:seed0",
        "phase3b0a-push-y60-16m:first-walk-entry:alpha0.5:seed0",
    ]
    assert checked["mode_order"] == list(study.MODES)
    assert "ops/state.json" in checked["retained_chain_pointer_exception"]


def test_case_derivation_changes_only_declared_membership_and_stand_duration():
    _, specs = study.declarations()
    source = json.loads((study.ROOT / specs["source_case"]).read_text())
    nominal, shorter, pushed = [study.derive_case(source, s) for s in specs["states"]]
    assert nominal == source
    assert shorter["nodes"][0]["parameters"]["duration_s"] == 5.0
    assert pushed["nodes"] == source["nodes"]
    assert shorter["nodes"][1:] == pushed["nodes"][1:] == source["nodes"][1:]
    assert shorter["id"] != pushed["id"] != nominal["id"]


@pytest.mark.parametrize("mode,expected", [
    ("CONTINUE", [0, 0, 0]), ("LATERAL_RECOVERY", [0, -1, 0]),
    ("YAW_RECOVERY", [0, 0, -1]), ("COMBINED_RECOVERY", [0, -1, -1])])
def test_four_fixed_actions_only_first_walk_14_seconds(mode, expected):
    assert study.action(mode, 1, "walk_forward", 0, 14.).tolist() == expected
    assert study.action(mode, 1, "walk_forward", 139, 14.).tolist() == expected
    assert study.action(mode, 1, "walk_forward", 140, 14.).tolist() == [0., 0., 0.]
    assert study.action(mode, 3, "walk_forward", 0, 14.).tolist() == [0., 0., 0.]
    assert study.action(mode, 0, "stand", 0, 14.).tolist() == [0., 0., 0.]
    with pytest.raises(ValueError):
        study.action(mode, 1, "walk_forward", 0, 15.)


def test_no_undeclared_profile_or_window():
    with pytest.raises(ValueError):
        study.action("NEW_PROFILE", 1, "walk_forward", 0, 14.)


def test_observed_terminal_failure_is_not_censored():
    row = {"nodes": [{"strict_success": False, "ideal_path_lateral_error_m": 1.0,
                       "ideal_path_heading_error_deg": 20.0}],
           "task_success": False, "physical_success": False,
           "final_state": {"base_position": [1.0, 2.0, 0.7]},
           "ideal_endpoint_reference_xy": [8.0, 4.0], "ideal_endpoint_error_m": 7.3}
    observed = study.outcome(row, "observed-result")
    assert observed["nominal"] is False and observed["physical"] is False
    assert observed["all_strict"] is False
    assert "INCOMPLETE_ROUTE_NONCOMPARABLE_ENDPOINT" in observed["evidence_source"]


def test_predecision_exactness_and_diagnostic_scales():
    clean = {"push_active": False, "applied_force_clear": True, "qpos": [1., 2.], "qvel": [0.]}
    assert study.same_predecision(clean, dict(clean))
    altered = dict(clean, qvel=[.1])
    assert not study.same_predecision(clean, altered)
    state = {"observables": {key: 0.0 for key in study.ORACLE.OBSERVABLE_FIELDS}}
    state["observables"]["previous_recovery"] = None
    other = json.loads(json.dumps(state))
    other["observables"]["route_y_error_m"] = .011
    other["observables"]["reference_heading_deg"] = 1.1
    diagnostic = study.observed_differences(state, other)
    assert diagnostic["descriptive_scale_flags"]["route_xy_at_least_0p01m"]
    assert diagnostic["descriptive_scale_flags"]["reference_heading_at_least_1deg"]
    assert diagnostic["raw_right_minus_left"]["previous_recovery"] is None


def test_historical_four_arm_sources_and_receipts_are_pinned():
    pins = json.loads((HERE / "source_manifest.json").read_text())["files"]
    assert "ops/state.json" in pins
    historical = json.loads(study.HISTORICAL.read_text())["evidence_sources"]
    for arm in ("off", "lateral", "yaw", "combined"):
        result = historical[arm]["result"]["path"]
        assert result in pins
        assert result.replace("result.json", "audit.json") in pins
        assert result.replace("result.json", "poses.npz") in pins
        assert historical[arm]["trace"]["path"] in pins


def test_any_other_pinned_source_drift_fails(monkeypatch):
    original = study.digest
    target = study.ROOT / "src/g1swarm/transition_learning/env.py"
    monkeypatch.setattr(study, "digest", lambda path: "0"*64 if path == target else original(path))
    with pytest.raises(RuntimeError, match="Pinned source drift"):
        study.preflight()


def test_confirmation_rejects_censor_and_non_boolean_truthy_checks():
    checks = {mode: {key: True for key in study.CONFIRMATION_KEYS} for mode in study.MODES}
    assert study.confirmation_passed(checks)
    checks["YAW_RECOVERY"] = {"censored": "network or execution failure"}
    assert not study.confirmation_passed(checks)
    checks["YAW_RECOVERY"] = {key: True for key in study.CONFIRMATION_KEYS}
    checks["YAW_RECOVERY"]["full_step_physics"] = "True"
    assert not study.confirmation_passed(checks)


def test_attempt02_resumes_sha_verified_nominal_and_corrects_only_policy_state_check():
    verified = study.verify_attempt01()
    assert verified["verified_exported_files"] == 38
    _, specs = study.declarations()
    case = study.derive_case(json.loads((study.ROOT / specs["source_case"]).read_text()), specs["states"][0])
    historical = json.loads(study.HISTORICAL.read_text())["evidence_sources"]
    initial_digests, predecision_digests = set(), set()
    for mode in study.MODES:
        data, snapshot, events = study.inherited_nominal(mode)
        record, traces, decisions, _, receipt = data
        initial_digests.add(receipt["initial_tensors_sha256"])
        predecision_digests.add(snapshot["policy_tensors_sha256"])
        assert receipt["initial_tensors_sha256"] != receipt["final_tensors_sha256"]
        audit = study.audit_cell(record, traces, decisions, receipt, case, mode, snapshot, events, None)
        assert audit["passed"]
        assert study.nominal_equivalence(mode, record, traces, receipt, snapshot, historical)["passed"]
    assert len(initial_digests) == 1
    assert len(predecision_digests) == 1


def test_inherited_oracle_evidence_sources_resolve_to_committed_attempt01():
    for mode in study.MODES:
        locator = study.evidence_source(0, "sequence-mixed-16m", mode,
                                        study.ROOT / "artifacts/decision_benchmark_acquisition_001_attempt02")
        rel, checksum = locator.split("#sha256=")
        assert rel.startswith("experiments/phase3b/decision_benchmark_acquisition_001/evidence/runs/")
        path = study.ROOT / rel
        assert path.is_file()
        assert study.digest(path) == checksum
