"""Independent checks of the new correction-frame isolation experiment.

The historical task evaluator remains authoritative. These checks distinguish
coordinate geometry from tracking error; they never rescore old experiments.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from g1swarm.boundary.envelope import evaluate_walk_task
from g1swarm.control.path_correction import CorrectionConfig, PathCorrectionPolicy
from g1swarm.heading_alignment.experiment import HeadingCorrectionPolicy
from g1swarm.segmentation.mission import MissionFrame
from g1swarm.tradeoff_isolation.experiment import (
    FixedAlphaCorrectionPolicy, science_record, source_anchor, verify_experiment,
)
import g1swarm.tradeoff_isolation.experiment as experiment


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "experiments/phase3a/correction_tradeoff_isolation_001"
HISTORICAL = ROOT / "experiments/phase3a/heading_alignment_strength_001"


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rows(path):
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    return [json.loads(line) for line in raw.decode().splitlines()]


def _delegate():
    return PathCorrectionPolicy(CorrectionConfig(
        mode="heading_lateral", k_heading=1.5, k_lateral=1.0,
        max_yaw_rate_radps=0.6, deadband_radps=0.01,
        oscillation_threshold_radps=0.05,
    ))


def _policy(alpha, planned_heading):
    runner = SimpleNamespace(index=1, planned_heading=planned_heading)
    return FixedAlphaCorrectionPolicy(runner, alpha, _delegate())


@pytest.mark.parametrize("alpha", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_new_references_preserve_actual_node_start_origin(alpha):
    local = MissionFrame((3.0, -7.0, 0.775), math.radians(-5.367024720986278))
    selected = _policy(alpha, 0.0).selected_frame(local)
    assert selected.initial_position == local.initial_position
    if alpha == 0:
        assert selected is local
    expected = math.radians(-5.367024720986278) * (1-alpha)
    assert selected.initial_yaw_rad == pytest.approx(expected, abs=1e-15)


@pytest.mark.parametrize("actual_deg,planned_deg", [(179.0, -179.0), (-179.0, 179.0)])
@pytest.mark.parametrize("alpha", [0.25, 0.5, 0.75])
def test_interpolation_takes_shortest_wrapped_heading_arc(actual_deg, planned_deg, alpha):
    actual = math.radians(actual_deg)
    planned = math.radians(planned_deg)
    local = MissionFrame((0.0, 0.0, 0.8), actual)
    selected = _policy(alpha, planned).selected_frame(local)
    delta = math.atan2(math.sin(selected.initial_yaw_rad-actual),
                       math.cos(selected.initial_yaw_rad-actual))
    assert math.degrees(delta) == pytest.approx(
        (2.0 if actual_deg > 0 else -2.0)*alpha, abs=1e-12
    )


@pytest.mark.parametrize("alpha", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("actual_deg,planned_deg", [(-5.367024720986278, 0.0), (179.0, -179.0)])
def test_anchor_frames_and_commands_match_frozen_historical_selector(alpha, actual_deg, planned_deg):
    runner = SimpleNamespace(index=1, planned_heading=math.radians(planned_deg))
    local = MissionFrame((0.11200944697231176, -0.18594415169729253, 0.775),
                         math.radians(actual_deg))
    old = HeadingCorrectionPolicy(runner, alpha, _delegate())
    new = FixedAlphaCorrectionPolicy(runner, alpha, _delegate())
    assert new.selected_frame(local) == old.selected_frame(local)
    yaw = math.radians(actual_deg+1.7)
    state = SimpleNamespace(base_position=(1.3, -0.21, 0.77),
                            base_orientation=(math.cos(yaw/2), 0.0, 0.0, math.sin(yaw/2)))
    nominal = np.array([0.5, 0.0, 0.0])
    old_command, old_sample = old.compute(state, local, nominal, sim_time_s=12.0)
    new_command, new_sample = new.compute(state, local, nominal, sim_time_s=12.0)
    assert np.array_equal(new_command, old_command)
    assert new_sample == old_sample
    assert new.config.to_dict() == old.config.to_dict()


@pytest.mark.parametrize("local_heading,rotation,forward,lateral", [
    (0.0, 0.0, 8.0, -0.002),
    (-0.09367225241714054, 0.04683612620857027, 8.008951062490842, -0.0026817135831306294),
    (-0.09367225241714054, 0.09367225241714054, 8.035285751007425, -0.00832757393727912),
    (math.radians(179), math.radians(2), 4.0, 0.05),
])
def test_frame_rotation_separates_geometric_offset_from_tracking(local_heading, rotation, forward, lateral):
    origin = (0.112, -0.185, 0.775)
    control_heading = local_heading+rotation
    position = (origin[0]+forward*math.cos(control_heading)-lateral*math.sin(control_heading),
                origin[1]+forward*math.sin(control_heading)+lateral*math.cos(control_heading),
                origin[2])
    local = MissionFrame(origin, local_heading)
    control = MissionFrame(origin, control_heading)
    actual_forward, actual_lateral = local.project(position)
    measured_forward, measured_lateral = control.project(position)
    assert measured_forward == pytest.approx(forward, abs=2e-15)
    assert measured_lateral == pytest.approx(lateral, abs=2e-15)
    assert actual_lateral == pytest.approx(
        measured_forward*math.sin(rotation)+measured_lateral*math.cos(rotation), abs=2e-15
    )
    assert actual_forward == pytest.approx(
        measured_forward*math.cos(rotation)-measured_lateral*math.sin(rotation), abs=2e-15
    )


def test_original_midpoint_strict_failure_is_real_and_not_physical_failure():
    historical = next(row for row in _rows(HISTORICAL / "evidence/results.jsonl.gz")
                      if row["case_id"] == "sequence-mixed-16m" and row["phase"] == "primary"
                      and row["heading_alignment_alpha"] == 0.5)
    node = historical["nodes"][1]
    assert node["strict_success"] is False
    assert node["physical_success"] is True
    assert node["task_success"] is True
    assert node["envelope"]["strict_envelope"]["violations"] == ["EXCESSIVE_DRIFT"]
    assert node["envelope"]["strict_envelope"]["limits"]["lateral_drift_max_m"] == 0.28
    assert node["envelope"]["nominal_envelope"]["limits"]["lateral_drift_max_m"] == 0.56
    assert node["transition_metrics"]["standing_fraction"] == 1.0
    reference = node["walking_reference"]
    angle = reference["control_heading_rad"]-reference["measurement_heading_rad"]
    control = node["control_frame_diagnostics"]
    geometric = control["forward_m"]*math.sin(angle)
    tracking = control["lateral_m"]*math.cos(angle)
    assert node["lateral_drift_m"] == pytest.approx(geometric+tracking, abs=1e-15)
    assert abs(tracking) < 0.003
    assert geometric > node["envelope"]["strict_envelope"]["limits"]["lateral_drift_max_m"]


def test_old_gate_reports_contract_violation_separately_from_upright_execution():
    result = evaluate_walk_task({"absolute_distance_error_m": 0.0003,
        "lateral_drift_m": 0.37229234402137323, "heading_error_deg": 2.1020931717701137,
        "completion_sim_time_s": 17.112}, 8.0, physical=True)
    assert result["physical_success"] is True
    assert result["task_success"] is True
    assert result["strict_success"] is False
    assert result["strict_envelope"]["violations"] == ["EXCESSIVE_DRIFT"]


def test_new_experiment_retains_original_console_assets_and_source_pins():
    visual = ROOT / "experiments/research_console/vertical_slice_001"
    manifest_path = visual / "manifest.json"
    assert _sha(manifest_path) == "54f63c9f6a35507a25e0b9cdbf1fdd883fab5db8ef8f27071601d97d699a2e79"
    manifest = _json(manifest_path)
    assert len(manifest["files"]) == 34
    assert len(manifest["sources"]) == 13
    for collection, base in ((manifest["files"], visual), (manifest["sources"], ROOT)):
        for name, pin in collection.items():
            path = base / name
            assert path.stat().st_size == pin["bytes"], name
            assert _sha(path) == pin["sha256"], name


def test_every_preexisting_tracked_file_remains_byte_identical():
    history = _json(DIRECTORY / "history_freeze.json")
    assert history["source_commit"] == "eefe56189c511b9be8c6965fcdaa64fb57a81d77"
    assert len(history["files"]) == 1519
    for name, pin in history["files"].items():
        path = ROOT / name
        assert path.is_file(), name
        assert path.stat().st_size == pin["bytes"], name
        assert _sha(path) == pin["sha256"], name
    checks = verify_experiment()
    assert checks["history_files_verified"] == 1519
    assert checks["prior"]["history"]["baseline"]["baseline_files_verified"] == 219


def test_protocol_freezes_membership_order_and_no_training_before_acquisition():
    protocol = _json(DIRECTORY / "protocol.json")
    assert protocol["frozen"] is True
    assert protocol["fixed_alphas"] == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert protocol["alpha_optimization"] is False
    assert protocol["fine_scan"] is False
    assert protocol["expand_cases"] is False
    assert protocol["PPO_training"] is False
    assert protocol["residual_enabled"] is False
    assert protocol["reward_calls_expected"] == 0
    assert protocol["optimizer_updates"] == protocol["checkpoint_writes"] == 0
    assert protocol["semantic_failure_retry"] is False
    assert protocol["analysis"]["no_new_score_thresholds"] is True
    assert protocol["analysis"]["numerical_audit_tolerance"] == 1e-10
    assert protocol["timestep_s"] == 0.002
    assert protocol["pose_capture_hz"] == 20
    assert _sha(DIRECTORY / "history_freeze.json") == protocol["history_manifest_sha256"]
    assert _sha(DIRECTORY / "case_manifest.json") == protocol["case_manifest_sha256"]
    schedule = protocol["schedule"]
    assert len(schedule) == protocol["runs"] == 16
    assert sum(spec["phase"] == "primary" for spec in schedule) == protocol["primary_runs"] == 8
    assert sum(spec["phase"] == "repeatability" for spec in schedule) == protocol["repeatability_runs"] == 8
    assert len({(s["case_id"], s["alpha"], s["phase"]) for s in schedule}) == 16
    assert all(s["alpha"] in (0.0, 0.5, 1.0) for s in schedule[:12])
    assert all(s["alpha"] in (0.25, 0.75) and s["case_id"] == "sequence-mixed-16m"
               for s in schedule[12:])
    cases = _json(DIRECTORY / "case_manifest.json")
    old_cases = _json(ROOT / cases["source_path"])
    assert _sha(ROOT / cases["source_path"]) == cases["source_sha256"]
    assert cases["seen_mechanism_cases"] is True
    for case in cases["cases"]:
        assert case == next(c for c in old_cases["regression"] if c["id"] == case["id"])
    assert {c["id"] for c in cases["cases"]} == {"sequence-mixed-16m", "primitive-walk-8"}


@pytest.mark.parametrize("case", ["sequence-mixed-16m", "primitive-walk-8"])
@pytest.mark.parametrize("alpha", [0.0, 0.5, 1.0])
def test_historical_anchor_loader_returns_exact_retained_record_trace_and_locator(case, alpha):
    record, trace, locator = source_anchor(case, alpha)
    result_path, line = locator["result_locator"].split("#decoded-line=")
    direct_record = _rows(ROOT / result_path)[int(line)-1]
    assert record == direct_record
    assert trace == _rows(ROOT / locator["trace_path"])
    assert _sha(ROOT / result_path) == locator["result_sha256"]
    assert _sha(ROOT / locator["trace_path"]) == locator["trace_sha256"]
    assert record["case_id"] == case
    assert record["heading_alignment_alpha"] == alpha
    assert record["phase"] == "primary"
    assert record["residual_enabled"] is False
    assert record["PPO_training"] is False
    assert all(row["active"] is False and row["action"] == [0.0, 0.0, 0.0]
               and row["residual"] == [0.0, 0.0, 0.0] for row in trace)
    expected_protocol = _json(DIRECTORY / "protocol.json")
    expected_key = "prior_heading_protocol_sha256" if alpha == 1 else "prior_frame_protocol_sha256"
    assert record["provenance"]["protocol_sha256"] == expected_protocol[expected_key]


@pytest.mark.parametrize("alpha", [0.25, 0.75])
def test_novel_alpha_cannot_be_substituted_for_a_historical_anchor(alpha):
    with pytest.raises(RuntimeError, match="Historical anchor must be unique"):
        source_anchor("sequence-mixed-16m", alpha)


def test_scientific_comparison_retains_frames_thresholds_diagnostics_and_outcomes():
    source, _, _ = source_anchor("sequence-mixed-16m", 0.5)
    normalized = science_record(source)
    assert normalized["nodes"][1]["lateral_drift_m"] == source["nodes"][1]["lateral_drift_m"]
    for key in ("walking_reference", "walking_correction_stats", "control_frame_diagnostics",
                "envelope", "transition_metrics", "max_tilt_deg", "min_height_m",
                "physical_success", "task_success", "strict_success", "simulation_steps"):
        assert normalized["nodes"][1][key] == source["nodes"][1][key]
    assert normalized["ideal_endpoint_error_m"] == source["ideal_endpoint_error_m"]
    assert normalized["total_sim_time_s"] == source["total_sim_time_s"]
    altered = json.loads(json.dumps(source))
    altered["nodes"][1]["strict_success"] = True
    assert science_record(altered) != normalized
    altered = json.loads(json.dumps(source))
    altered["nodes"][1]["walking_reference"]["control_heading_rad"] += 1e-12
    assert science_record(altered) != normalized
    altered = json.loads(json.dumps(source))
    altered["nodes"][1]["envelope"]["strict_envelope"]["limits"]["lateral_drift_max_m"] = 0.56
    assert science_record(altered) != normalized


@pytest.mark.parametrize("changed", ["source", "protocol"])
def test_uncommitted_acquisition_source_or_protocol_stops_before_any_physics(monkeypatch, tmp_path, changed):
    called = []

    def no_physics(*args, **kwargs):
        called.append(True)
        raise AssertionError("The provenance gate must run before physics")

    def simulated_git(command, **kwargs):
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return "prospective-source-commit\n"
        if command[:2] == ["git", "show"]:
            name = command[2].split(":", 1)[1]
            is_protocol = name.endswith("correction_tradeoff_isolation_001/protocol.json")
            if (changed == "source" and not is_protocol) or (changed == "protocol" and is_protocol):
                return b"different committed bytes"
            return (ROOT / name).read_bytes()
        raise AssertionError(f"Unexpected Git operation: {command}")

    monkeypatch.setattr(experiment, "acquire", no_physics)
    monkeypatch.setattr(experiment.subprocess, "check_output", simulated_git)
    output = tmp_path / "uncommitted-evidence"
    message = "Acquisition source must be committed" if changed == "source" else "Protocol must be committed"
    with pytest.raises(RuntimeError, match=message):
        experiment.run_campaign(output)
    assert called == []
    assert not output.exists()
