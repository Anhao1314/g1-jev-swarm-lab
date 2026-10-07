"""Independent integrity checks for the historical visual explanation slice.

These checks read immutable evidence; they do not execute a new experiment,
score a sample again, or import the renderer/physics into the HTTP server.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path

import pytest
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SCIENCE = ROOT / "experiments/phase3a/frame_residual_learning_001"
SOURCE_RESULTS = SCIENCE / "evidence/evaluation/results.jsonl.gz"
ARMS = ("alpha0-residual-off", "alpha0.5-residual-off")
RESULT_LINES = {ARMS[0]: 26, ARMS[1]: 52}
VISUAL = ROOT / "experiments/research_console/vertical_slice_001"
RUN_IDS = {ARMS[0]: "alpha0-off", ARMS[1]: "alpha05-off"}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _decoded(path: Path) -> bytes:
    raw = path.read_bytes()
    return gzip.decompress(raw) if path.suffix == ".gz" else raw


def _source_rows():
    rows = [json.loads(x) for x in _decoded(SOURCE_RESULTS).decode().splitlines()]
    return {arm: rows[line - 1] for arm, line in RESULT_LINES.items()}


def _yaw(quat):
    w, x, y, z = quat
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def _wrapped(value):
    return math.atan2(math.sin(value), math.cos(value))


def _lateral(position, origin, heading):
    dx, dy = position[0] - origin[0], position[1] - origin[1]
    return -math.sin(heading) * dx + math.cos(heading) * dy


def test_all_original_scientific_files_remain_byte_identical():
    """Preserve all tracked source/config/tests and historical study evidence."""
    snapshot = _json(ROOT / "console/audit/scientific_snapshot_before.json")
    assert snapshot["source_commit"] == "86d1883db84a53de57eacfab061234f2a118c94c"
    assert snapshot["tracked_file_count"] == len(snapshot["files"]) == 1348
    for relative, expected in snapshot["files"].items():
        path = ROOT / relative
        assert path.is_file(), f"Original scientific file missing: {relative}"
        data = path.read_bytes()
        assert len(data) == expected["bytes"], relative
        assert hashlib.sha256(data).hexdigest() == expected["sha256"], relative


@pytest.mark.parametrize("arm", ARMS)
def test_source_result_and_trace_keep_export_and_raw_identity(arm):
    """The displayed source is the frozen inventory entry, not a copied score."""
    inventory = _json(SCIENCE / "evidence_manifest.json")["inventory"]
    trace = SCIENCE / f"evidence/evaluation/traces/primary--{arm}--sequence-mixed-16m.jsonl.gz"
    for path in (SOURCE_RESULTS, trace):
        pin = inventory[path.relative_to(ROOT).as_posix()]
        exported = path.read_bytes()
        decoded = _decoded(path)
        for key, data in (("exported", exported), ("raw", decoded)):
            assert len(data) == pin[key]["bytes"]
            assert hashlib.sha256(data).hexdigest() == pin[key]["sha256"]
        # Raw acquisition may be absent on a fresh clone. The exported decoding
        # always has its raw hash verified; if raw is retained, verify it too.
        raw_path = ROOT / pin["raw_path"]
        if raw_path.is_file():
            assert raw_path.read_bytes() == decoded
    record = _source_rows()[arm]
    assert record["case_id"] == "sequence-mixed-16m"
    assert record["phase"] == "primary"
    assert record["treatment_label"] == arm
    assert record["checkpoint"] is None
    assert record["residual_enabled"] is False
    assert record["provenance"]["code_commit"] == "a4926973e01b65f98fc7c598d48ac982b47d6516"


@pytest.mark.parametrize("arm", ARMS)
def test_frozen_source_node_metric_frames_are_unambiguous(arm):
    """Independent frame arithmetic distinguishes local contract/global path."""
    record = _source_rows()[arm]
    origin = list(record["nodes"][0]["start_state"]["base_position"][:2])
    planned_heading = _yaw(record["nodes"][0]["start_state"]["base_orientation"])
    for node in record["nodes"]:
        position = node["end_state"]["base_position"]
        heading = _yaw(node["end_state"]["base_orientation"])
        local_origin = node["start_state"]["base_position"]
        local_heading = _yaw(node["start_state"]["base_orientation"])
        assert node["lateral_drift_m"] == pytest.approx(
            _lateral(position, local_origin, local_heading), abs=1e-12
        )
        assert node["ideal_path_lateral_error_m"] == pytest.approx(
            _lateral(position, origin, planned_heading), abs=1e-12
        )
        target_heading = planned_heading
        if node["skill"] == "turn":
            target_heading += math.radians(node["parameters"]["target_angle_deg"])
        assert node["ideal_path_heading_error_deg"] == pytest.approx(
            math.degrees(_wrapped(heading - target_heading)), abs=1e-12
        )
        if node["skill"] == "walk_forward":
            distance = node["parameters"]["target_distance_m"]
            origin[0] += distance * math.cos(planned_heading)
            origin[1] += distance * math.sin(planned_heading)
        elif node["skill"] == "turn":
            planned_heading = _wrapped(target_heading)
    endpoint = record["final_state"]["base_position"]
    assert record["ideal_endpoint_error_m"] == pytest.approx(
        math.hypot(endpoint[0] - origin[0], endpoint[1] - origin[1]), abs=1e-12
    )


def test_midpoint_negative_strict_result_is_preserved():
    records = _source_rows()
    first_walk = records[ARMS[1]]["nodes"][1]
    assert first_walk["skill"] == "walk_forward"
    assert first_walk["lateral_drift_m"] == pytest.approx(0.37229234402137323)
    assert first_walk["task_success"] is True
    assert first_walk["strict_success"] is False
    strict = first_walk["envelope"]["strict_envelope"]
    nominal = first_walk["envelope"]["nominal_envelope"]
    assert strict["violations"] == ["EXCESSIVE_DRIFT"]
    assert strict["limits"]["lateral_drift_max_m"] == 0.28
    assert nominal["limits"]["lateral_drift_max_m"] == 0.56
    assert abs(records[ARMS[1]]["nodes"][-1]["ideal_path_lateral_error_m"]) < abs(
        records[ARMS[0]]["nodes"][-1]["ideal_path_lateral_error_m"]
    )


def test_historical_joint_pose_gap_is_not_hidden():
    """Historical command evidence is insufficient for original-state replay."""
    for arm in ARMS:
        trace = SCIENCE / f"evidence/evaluation/traces/primary--{arm}--sequence-mixed-16m.jsonl.gz"
        rows = [json.loads(x) for x in _decoded(trace).decode().splitlines()]
        assert all(row["state_before_command"]["joint_positions"] is None for row in rows)
        assert all(row["state_before_command"]["joint_velocities"] is None for row in rows)
        assert all(row["active"] is False for row in rows)
        assert all(row["residual"] == [0.0, 0.0, 0.0] for row in rows)


def _scientific_record(record):
    # Only explicit publication annotations and actual wall-time names may be
    # removed. Keep all reference diagnostics, correction stats, node results,
    # transition geometry, ideal endpoints, task gates, and simulation times.
    annotation = {"checkpoint", "recorded_at", "evaluation_set", "provenance", "phase", "treatment_label"}

    def strip_wall(value):
        if isinstance(value, dict):
            return {k: strip_wall(v) for k, v in value.items()
                    if k not in {"wall_time_s", "elapsed_wall_time_s"}}
        if isinstance(value, list):
            return [strip_wall(v) for v in value]
        return value

    return strip_wall({k: v for k, v in record.items() if k not in annotation})


@pytest.mark.parametrize("arm", ARMS)
def test_derived_replay_has_exact_original_scientific_record_and_commands(arm):
    directory = VISUAL / "runs" / RUN_IDS[arm]
    original = _source_rows()[arm]
    observed = _json(directory / "derived_result.json")
    unobserved = _json(directory / "unobserved_result.json")
    assert _scientific_record(observed) == _scientific_record(original)
    assert _scientific_record(unobserved) == _scientific_record(original)
    source_trace = SCIENCE / f"evidence/evaluation/traces/primary--{arm}--sequence-mixed-16m.jsonl.gz"
    original_rows = [json.loads(x) for x in _decoded(source_trace).decode().splitlines()]
    derived_rows = [json.loads(x) for x in _decoded(directory / "derived_trace.jsonl.gz").decode().splitlines()]
    assert derived_rows == original_rows


@pytest.mark.parametrize("arm", ARMS)
def test_pose_capture_off_on_stream_parity_is_complete_and_scoped(arm):
    directory = VISUAL / "runs" / RUN_IDS[arm]
    certificate = _json(directory / "parity.json")
    assert certificate["capture_off_on_equal"] is True
    assert certificate["historical_record_exact"] is True
    assert certificate["historical_command_trace_exact"] is True
    assert certificate["historical_joint_states_available"] is False
    assert "NOT a live PPO training observer" in certificate["scope"]
    assert certificate["capture_off"] == certificate["capture_on"]
    receipt = certificate["capture_on"]
    source = _source_rows()[arm]
    assert receipt["physics_steps"] == sum(n["simulation_steps"] for n in source["nodes"])
    for stream in ("commands", "torques", "base_actions"):
        assert receipt["streams"][stream]["count"] == receipt["physics_steps"]
    assert receipt["streams"]["base_observations"]["count"] > 0
    assert receipt["streams"]["residual_observations"]["count"] > 0
    assert receipt["streams"]["rewards"]["count"] == certificate["reward_calls"] == 0
    assert certificate["optimizer_updates"] == 0
    assert certificate["checkpoint_written"] is False
    assert certificate["no_renderer_encoder_browser_in_physics_process"] is True
    # Full TorchScript state includes evolving LSTM hidden/cell buffers.
    # Equality is required across off/on executions, not before/after rollout.
    assert receipt["initial_policy_tensors_sha256"] != receipt["final_policy_tensors_sha256"]
    provenance = _json(directory / "capture_manifest.json")["provenance"]
    assert provenance["visual_source"] == "derived_visualization_replay"
    assert provenance["original_video_available"] is False
    assert provenance["checkpoint_sha"] is None
    policy = ROOT / "third_party/unitree_rl_gym/deploy/pre_train/g1/motion.pt"
    assert hashlib.sha256(policy.read_bytes()).hexdigest() == provenance["policy_sha"]
    assert hashlib.sha256((directory / "poses.npz").read_bytes()).hexdigest() == provenance["pose_sha"]


@pytest.mark.parametrize("arm", ARMS)
def test_rendering_is_bound_to_exact_captured_states_and_original_final_pose(arm):
    directory = VISUAL / "runs" / RUN_IDS[arm]
    render = _json(directory / "render_manifest.json")
    assert render["visual_source"] == "derived_visualization_replay"
    assert render["passed"] is True
    assert render["original_model_modified"] is False
    assert render["physics_execution_finished_before_rendering"] is True
    assert "zero mj_step" in render["render_mechanism"]
    assert render["pose_unchanged"] is True
    assert hashlib.sha256((directory / "rollout.mp4").read_bytes()).hexdigest() == render["video_sha256"]
    assert hashlib.sha256((directory / "poses.npz").read_bytes()).hexdigest() == render["pose_sha256"]
    with np.load(directory / "poses.npz", allow_pickle=False) as poses:
        assert poses["qpos"].shape == (render["frames"], 19)
        assert poses["qvel"].shape == (render["frames"], 18)
        assert poses["ctrl"].shape == (render["frames"], 12)
        assert np.isfinite(poses["qpos"]).all()
        assert np.isfinite(poses["qvel"]).all()
        assert np.array_equal(poses["time_s"], render["frame_sim_times_s"])
        assert poses["time_s"][0] == 0.0
        assert np.all(np.diff(poses["time_s"]) > 0)
        original = _source_rows()[arm]
        assert poses["time_s"][-1] == original["total_sim_time_s"]
        assert np.array_equal(poses["qpos"][-1, :3], original["final_state"]["base_position"])
        assert np.array_equal(poses["qpos"][-1, 3:7], original["final_state"]["base_orientation"])


def test_initial_negative_comparison_receipt_is_retained_without_new_physics():
    directory = VISUAL / "runs" / RUN_IDS[ARMS[0]]
    initial = _json(directory / "initial_certificate_bug.json")
    corrected = _json(directory / "parity.json")
    assert initial["capture_off_on_equal"] is False
    assert initial["historical_record_exact"] is False
    assert initial["historical_command_trace_exact"] is True
    # Correction changes comparison interpretation only: the same already
    # acquired stream receipts persist, including every physics-step digest.
    assert initial["capture_off"] == corrected["capture_off"]
    assert initial["capture_on"] == corrected["capture_on"]
    assert "no scientific replay retried" in corrected["initial_certificate_correction"]


@pytest.mark.parametrize("arm", ARMS)
def test_synchronized_metrics_use_source_contract_frames_at_each_native_pose(arm):
    """Cross-check every UI sample independently against source node frames."""
    directory = VISUAL / "runs" / RUN_IDS[arm]
    run = _json(directory / "run.json")
    source = _source_rows()[arm]
    assert run["visual_source"] == "derived_visualization_replay"
    assert run["duration_s"] == source["total_sim_time_s"]
    planned = []
    origin = source["nodes"][0]["start_state"]["base_position"][:2].copy()
    heading = _yaw(source["nodes"][0]["start_state"]["base_orientation"])
    for node in source["nodes"]:
        planned.append((origin.copy(), heading))
        if node["skill"] == "walk_forward":
            distance = node["parameters"]["target_distance_m"]
            origin[0] += distance * math.cos(heading)
            origin[1] += distance * math.sin(heading)
        elif node["skill"] == "turn":
            heading = _wrapped(heading + math.radians(node["parameters"]["target_angle_deg"]))
    with np.load(directory / "poses.npz", allow_pickle=False) as poses:
        assert run["frame_map"] == poses["time_s"].tolist()
        assert len(run["samples"]) == len(run["frame_map"])
        for frame, sample in enumerate(run["samples"]):
            assert sample["frame_index"] == frame
            assert sample["time_s"] == poses["time_s"][frame]
            node_index = sample["node_index"]
            assert node_index == poses["node_index"][frame]
            node = source["nodes"][node_index]
            assert sample["skill"] == node["skill"]
            state = poses["qpos"][frame]
            assert [sample["x"], sample["y"]] == state[:2].tolist()
            actual = _yaw(state[3:7])
            local_origin = node["start_state"]["base_position"]
            local_heading = _yaw(node["start_state"]["base_orientation"])
            planned_origin, planned_heading = planned[node_index]
            commanded = planned_heading
            if node["skill"] == "turn":
                commanded += math.radians(node["parameters"]["target_angle_deg"])
            assert sample["actual_heading_deg"] == pytest.approx(math.degrees(actual), abs=1e-12)
            assert sample["commanded_heading_deg"] == pytest.approx(math.degrees(_wrapped(commanded)), abs=1e-12)
            assert sample["local_lateral_m"] == pytest.approx(_lateral(state, local_origin, local_heading), abs=1e-12)
            assert sample["global_lateral_m"] == pytest.approx(_lateral(state, planned_origin, planned_heading), abs=1e-12)
            assert sample["heading_error_deg"] == pytest.approx(math.degrees(_wrapped(actual - commanded)), abs=1e-12)
            if node["skill"] == "walk_forward":
                # Expected reference comes directly from the frozen node's
                # annotation, not the capture metadata or index implementation.
                reference = node["walking_reference"]["control_heading_rad"]
                assert sample["reference_heading_deg"] == pytest.approx(math.degrees(reference), abs=1e-12)
            else:
                assert sample["reference_heading_deg"] is None
            assert sample["source_locator"] == f"runs/{RUN_IDS[arm]}/poses.npz#frame={frame}"
    for index, node in enumerate(run["nodes"]):
        original = source["nodes"][index]
        assert node["task_status"] == ("PASS" if original["task_success"] else "FAIL")
        assert node["physical_status"] == ("PASS" if original["physical_success"] else "FAIL")
        assert node["strict_status"] == ("PASS" if original["strict_success"] else "FAIL")
        assert node["source_metric"] == original["lateral_drift_m"]
    for event in run["events"]:
        original = source["nodes"][event["node_index"]]
        assert event["time_s"] == original["end_state"]["simulation_time"]
        assert event["value"] == original[event["metric"]]
        assert event["source_locator"] == (
            f"{SOURCE_RESULTS.relative_to(ROOT).as_posix()}#decoded-line={RESULT_LINES[arm]}"
            f"&pointer=/nodes/{event['node_index']}/{event['metric']}"
        )
    assert run["summary"]["global_lateral_m"] == source["nodes"][-1]["ideal_path_lateral_error_m"]
    assert run["summary"]["heading_error_deg"] == source["nodes"][-1]["ideal_path_heading_error_deg"]
    assert run["summary"]["endpoint_error_m"] == source["ideal_endpoint_error_m"]
    assert run["summary"]["strict_status"] == ("PASS" if all(n["strict_success"] for n in source["nodes"]) else "FAIL")
