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
import subprocess
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


@pytest.fixture(scope="module")
def acquired_records():
    """Requires complete retained evidence; a missing campaign is a failure."""
    return _rows(DIRECTORY / "evidence/results.jsonl.gz")


def _yaw(quaternion):
    # Compute independently, without the new analysis module or simulator.
    w, x, y, z = quaternion
    return math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))


def _wrapped(value):
    return math.atan2(math.sin(value), math.cos(value))


def _project(position, origin, heading):
    dx, dy = position[0]-origin[0], position[1]-origin[1]
    return math.cos(heading)*dx+math.sin(heading)*dy, -math.sin(heading)*dx+math.cos(heading)*dy


def _source_science(value):
    # Keep all actual scientific diagnostics. Strip only documented publication
    # annotations and actual clock names, never an arbitrary key substring.
    annotation = {"alpha", "heading_alignment_alpha", "run_id", "phase", "repetition", "provenance",
        "evaluation_set", "checkpoint", "recorded_at", "treatment_label", "observer_audit",
        "policy_decision_calls", "learned_policy_configured", "wall_time_s", "elapsed_wall_time_s"}
    if isinstance(value, dict):
        return {k: _source_science(v) for k, v in value.items() if k not in annotation}
    if isinstance(value, list):
        return [_source_science(v) for v in value]
    return value


def _cross_frame_science(value):
    """Cross-alpha comparisons omit only the differing reference-mode label.

    Actual reference coordinates, gains, command diagnostics and outcomes remain
    present; the intervention's label is not an independent physical variable.
    """
    value = _source_science(value)
    if isinstance(value, dict):
        return {k: _cross_frame_science(v) for k, v in value.items() if k != "reference_mode"}
    if isinstance(value, list):
        return [_cross_frame_science(v) for v in value]
    return value


def test_complete_acquisition_preserves_schedule_and_prospective_git_provenance(acquired_records):
    protocol = _json(DIRECTORY / "protocol.json")
    assert len(acquired_records) == 16
    for record, expected in zip(acquired_records, protocol["schedule"]):
        for key in ("case_id", "alpha", "phase", "repetition"):
            assert record[key] == expected[key]
    manifest = _json(DIRECTORY / "evidence/manifest.json")
    completion = _json(DIRECTORY / "evidence/completion.json")
    assert completion["status"] == "COMPLETE"
    assert completion["runs"] == 16
    assert manifest["protocol"] == protocol
    common = manifest["provenance"]
    assert all(record["provenance"] == common for record in acquired_records)
    assert common["PPO_training"] is False
    assert common["residual_enabled"] is False
    assert common["Console_UI_modified"] is False
    assert common["no_independent_seed_claim"] is True
    assert common["protocol_sha256"] == _sha(DIRECTORY / "protocol.json")
    assert common["case_manifest_sha256"] == _sha(DIRECTORY / "case_manifest.json")
    assert common["history_manifest_sha256"] == _sha(DIRECTORY / "history_freeze.json")
    assert common["base_policy_sha256"] == _sha(ROOT / "third_party/unitree_rl_gym/deploy/pre_train/g1/motion.pt")
    commit = common["code_commit"]
    assert len(commit) == 40
    for path, expected in common["source_hashes"].items():
        assert _sha(ROOT / path) == expected
        committed = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)
        assert hashlib.sha256(committed).hexdigest() == expected
    committed_protocol = subprocess.check_output([
        "git", "show", f"{commit}:experiments/phase3a/correction_tradeoff_isolation_001/protocol.json"
    ], cwd=ROOT)
    assert hashlib.sha256(committed_protocol).hexdigest() == common["protocol_sha256"]
    assert not (DIRECTORY / "evidence/stopped.json").exists()


def test_exported_evidence_retains_every_raw_artifact_and_both_hashes():
    inventory = _json(DIRECTORY / "evidence_manifest.json")
    assert inventory["protocol_sha256"] == _sha(DIRECTORY / "protocol.json")
    assert inventory["all_negative_results_retained"] is True
    assert inventory["retry"] is False
    raw_paths = set()
    for name, pin in inventory["files"].items():
        exported = (ROOT / name).read_bytes()
        assert len(exported) == pin["bytes"], name
        assert hashlib.sha256(exported).hexdigest() == pin["sha256"], name
        decoded = gzip.decompress(exported) if pin["encoding"] == "gzip" else exported
        assert hashlib.sha256(decoded).hexdigest() == pin["raw_sha256"], name
        raw = ROOT / pin["raw_path"]
        raw_paths.add(raw)
        if raw.exists():
            assert raw.read_bytes() == decoded, pin["raw_path"]
    raw_root = ROOT / "artifacts/correction_tradeoff_isolation_001"
    if raw_root.is_dir():
        assert {p for p in raw_root.rglob("*") if p.is_file()} == raw_paths
    assert len([n for n in inventory["files"] if n.endswith(".npz")]) == 16
    assert len([n for n in inventory["files"] if "/traces/" in n]) == 16


def test_every_control_anchor_and_repeat_has_exact_historical_evidence(acquired_records):
    checks = _json(DIRECTORY / "evidence/anchor_checks.json")
    assert checks["all_passed"] is True
    assert len(checks["checks"]) == 12
    for record in acquired_records:
        if record["alpha"] not in (0.0, 0.5, 1.0):
            continue
        source, trace, locator = source_anchor(record["case_id"], record["alpha"])
        assert _source_science(record) == _source_science(source)
        retained = _rows(DIRECTORY / "evidence/traces" / (record["run_id"]+".jsonl.gz"))
        assert retained == trace
        certificate = next(c for c in checks["checks"] if c["run_id"] == record["run_id"])
        assert certificate["passed"] is True
        assert all(certificate[key] == value for key, value in locator.items())


def test_repetition_identity_covers_full_streams_rng_tensors_traces_and_saved_poses(acquired_records):
    primary = {(r["case_id"], r["alpha"]): r for r in acquired_records if r["phase"] == "primary"}
    for repeated in acquired_records:
        if repeated["phase"] != "repeatability":
            continue
        first = primary[(repeated["case_id"], repeated["alpha"])]
        assert _source_science(repeated) == _source_science(first)
        assert repeated["observer_audit"] == first["observer_audit"]
        for directory, suffix in (("traces", ".jsonl.gz"), ("poses", ".npz")):
            left = DIRECTORY / "evidence" / directory / (first["run_id"]+suffix)
            right = DIRECTORY / "evidence" / directory / (repeated["run_id"]+suffix)
            if suffix == ".jsonl.gz":
                assert _rows(left) == _rows(right)
            else:
                with np.load(left, allow_pickle=False) as a, np.load(right, allow_pickle=False) as b:
                    assert set(a.files) == set(b.files)
                    assert all(np.array_equal(a[key], b[key], equal_nan=True) for key in a.files)
    primitives = [r for r in acquired_records if r["case_id"] == "primitive-walk-8"]
    assert len(primitives) == 6
    assert all(_cross_frame_science(r) == _cross_frame_science(primitives[0]) for r in primitives)
    assert all(r["observer_audit"] == primitives[0]["observer_audit"] for r in primitives)


def test_read_only_observer_preserves_existing_observation_counts_and_zero_learning(acquired_records):
    for record in acquired_records:
        audit = record["observer_audit"]
        assert audit["physics_steps"] == sum(n["simulation_steps"] for n in record["nodes"])
        for stream in ("commands", "torques", "base_actions"):
            assert audit["streams"][stream]["count"] == audit["physics_steps"]
        assert audit["streams"]["base_observations"]["count"] > 0
        assert audit["reward_calls"] == audit["optimizer_updates"] == audit["checkpoint_writes"] == 0
        assert len(audit["physics_state_sha256"]) == len(audit["rng_after_sha256"]) == 64
        assert len(audit["initial_tensors_sha256"]) == len(audit["final_tensors_sha256"]) == 64
        trace = _rows(DIRECTORY / "evidence/traces" / (record["run_id"]+".jsonl.gz"))
        assert audit["streams"]["residual_observations"]["count"] == sum(r["eligible"] for r in trace)
        assert all(row["active"] is False and row["action"] == [0.0, 0.0, 0.0]
                   and row["residual"] == [0.0, 0.0, 0.0] for row in trace)
        assert all(np.array_equal(row["applied_command"], row["deterministic_command"]) for row in trace)


def test_native_pose_coordinates_and_source_commands_independently_support_mechanism(acquired_records):
    maximum_error = 0.0
    observed_walk_commands = 0
    for record in acquired_records:
        path = DIRECTORY / "evidence/poses" / (record["run_id"]+".npz")
        with np.load(path, allow_pickle=False) as poses:
            assert poses["qpos"].shape == (len(poses["time_s"]), 19)
            assert poses["qvel"].shape == (len(poses["time_s"]), 18)
            assert poses["ctrl"].shape == (len(poses["time_s"]), 12)
            assert np.isfinite(poses["qpos"]).all()
            assert np.isfinite(poses["qvel"]).all()
            assert np.isfinite(poses["ctrl"]).all()
            assert poses["time_s"][0] == 0.0
            assert np.all(np.diff(poses["time_s"]) > 0)
            assert poses["time_s"][-1] == record["total_sim_time_s"]
            assert np.array_equal(poses["qpos"][-1, :3], record["final_state"]["base_position"])
            assert np.array_equal(poses["qpos"][-1, 3:7], record["final_state"]["base_orientation"])
            for frame, node_index in enumerate(poses["node_index"]):
                node = record["nodes"][int(node_index)]
                if node["skill"] != "walk_forward":
                    assert math.isnan(poses["reference_heading"][frame])
                    continue
                ref = node["walking_reference"]
                assert np.array_equal(poses["local_origin"][frame], node["start_state"]["base_position"][:2])
                assert poses["local_heading"][frame] == ref["measurement_heading_rad"]
                if math.isnan(poses["reference_heading"][frame]):
                    # Retain the frozen observer's initialization metadata gap:
                    # the t=0 pose is copied before first Walk node setup. It
                    # is a real pose, not a command-aligned observation. Never
                    # synthesize a reference or alter the evidence to fill it.
                    assert record["case_id"] == "primitive-walk-8"
                    assert frame == 0 and poses["time_s"][frame] == 0.0
                    assert int(node_index) == 0
                    continue
                assert poses["reference_heading"][frame] == ref["control_heading_rad"]
                position = poses["qpos"][frame, :3]
                lf, ll = _project(position, poses["local_origin"][frame], poses["local_heading"][frame])
                cf, cl = _project(position, poses["local_origin"][frame], poses["reference_heading"][frame])
                delta = _wrapped(poses["reference_heading"][frame]-poses["local_heading"][frame])
                reconstructed = cf*math.sin(delta)+cl*math.cos(delta)
                maximum_error = max(maximum_error, abs(ll-reconstructed))
                assert ll == pytest.approx(reconstructed, abs=1e-10)
                assert lf == pytest.approx(cf*math.cos(delta)-cl*math.sin(delta), abs=1e-10)
        trace = _rows(DIRECTORY / "evidence/traces" / (record["run_id"]+".jsonl.gz"))
        for row in trace:
            if row["skill"] != "walk_forward":
                continue
            observed_walk_commands += 1
            ref = row["walking_reference"]
            state = row["state_before_command"]
            _, cl = _project(state["base_position"], ref["control_origin"], ref["control_heading_rad"])
            heading_error = _wrapped(_yaw(state["base_orientation"])-ref["control_heading_rad"])
            yaw_raw = -1.5*heading_error-cl
            yaw_raw = 0.0 if abs(yaw_raw) < 0.01 else yaw_raw
            yaw_command = max(-0.6, min(0.6, yaw_raw))
            expected = [row["nominal_command"][0], row["nominal_command"][1], yaw_command]
            assert row["applied_command"] == pytest.approx(expected, abs=1e-10)
    assert observed_walk_commands > 0
    assert maximum_error < 1e-10


def test_shared_pretreatment_stand_state_and_midpoint_negative_remain_visible(acquired_records):
    sequence = [r for r in acquired_records if r["case_id"] == "sequence-mixed-16m"]
    first_stand = _cross_frame_science(sequence[0]["nodes"][0])
    assert all(_cross_frame_science(r["nodes"][0]) == first_stand for r in sequence)
    midpoint = next(r for r in sequence if r["phase"] == "primary" and r["alpha"] == 0.5)
    first_walk = midpoint["nodes"][1]
    assert first_walk["lateral_drift_m"] == 0.37229234402137323
    assert first_walk["physical_success"] is True
    assert first_walk["task_success"] is True
    assert first_walk["strict_success"] is False
    assert first_walk["envelope"]["strict_envelope"]["violations"] == ["EXCESSIVE_DRIFT"]
    assert first_walk["walking_correction_stats"]["saturation_count"] == 0


@pytest.mark.parametrize("alpha,console_run", [(0.0, "alpha0-off"), (0.5, "alpha05-off")])
def test_current_sequence_probe_matches_frozen_console_capture_off_and_on_streams(acquired_records, alpha, console_run):
    record = next(r for r in acquired_records if r["case_id"] == "sequence-mixed-16m"
                  and r["phase"] == "primary" and r["alpha"] == alpha)
    audit = record["observer_audit"]
    frozen = _json(ROOT / "experiments/research_console/vertical_slice_001/runs" / console_run / "parity.json")
    assert frozen["capture_off_on_equal"] is True
    for observer in ("capture_off", "capture_on"):
        original = frozen[observer]
        assert audit["physics_state_sha256"] == original["physics_state_sha256"]
        assert audit["physics_steps"] == original["physics_steps"]
        for name, stream in audit["streams"].items():
            assert stream == original["streams"][name]
        assert audit["initial_tensors_sha256"] == original["initial_policy_tensors_sha256"]
        assert audit["final_tensors_sha256"] == original["final_policy_tensors_sha256"]
