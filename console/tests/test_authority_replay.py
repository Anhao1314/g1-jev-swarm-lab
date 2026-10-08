"""Offline observer tests; no simulator, evaluator, provider or experiment run."""
from __future__ import annotations

import ast
import gzip
import importlib.util
import json
import math
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("authority_replay_builder", ROOT / "console/build_authority_replay.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def json_at(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def independent_lateral(position, origin, heading):
    dx, dy = position[0] - origin[0], position[1] - origin[1]
    return -math.sin(heading) * dx + math.cos(heading) * dy


@pytest.mark.parametrize("arm", BUILDER.ARMS)
def test_formal_metrics_are_source_bound_and_no_science_changes(arm, tmp_path):
    source_id = arm[1]
    paths = BUILDER.source_paths(source_id)
    before = {name: BUILDER.digest(ROOT / path) for name, path in paths.items()}
    run = BUILDER.build_run(*arm, data=tmp_path)
    source, baseline = BUILDER.load_source(source_id), BUILDER.load_source(BUILDER.ARMS[0][1])
    result, audit, summary = source["result"], source["audit"], source["summary_row"]
    expected_window = audit["first_walk_window_state"]["local_lateral_m"] - baseline["audit"]["first_walk_window_state"]["local_lateral_m"]
    expected_end = result["nodes"][1]["lateral_drift_m"] - baseline["result"]["nodes"][1]["lateral_drift_m"]
    limit = result["nodes"][1]["envelope"]["strict_envelope"]["limits"]["lateral_drift_max_m"]
    authority = run["authority"]
    assert authority["local_effect_at_window_end_m"] == expected_window
    assert authority["local_effect_at_walk_end_m"] == expected_end
    assert authority["strict_gap_m"] == abs(result["nodes"][1]["lateral_drift_m"]) - limit
    assert authority["local_strict_limit_m"] == limit
    assert authority["evidence_metrics"] == summary
    assert authority["joint_qualifier"] is summary["joint_qualifier"] is False
    assert run["summary"]["strict_status"] == "FAIL"
    assert run["run_id"] == result["run_id"] and run["probe_id"] == result["probe_id"]
    assert authority["walk_end_s"] == result["nodes"][1]["end_state"]["simulation_time"]
    assert authority["window_end_s"] == authority["walk_start_s"] + source["protocol"]["authority"]["window_s"]
    assert authority["source_locators"]["walk_endpoint"].endswith("#pointer=/nodes/1/lateral_drift_m")
    assert run["provenance"]["source_result_sha"] == before["result"]["sha256"]
    assert run["visual_source"] == "state_playback"
    assert run["provenance"]["mj_step_calls"] == run["provenance"]["simulation_reexecutions"] == 0
    assert before == {name: BUILDER.digest(ROOT / path) for name, path in paths.items()}


def test_fixed_walk_anchors_survive_start_and_cross_node_endpoint_frames(tmp_path):
    arm = BUILDER.ARMS[1]
    run = BUILDER.build_run(*arm, data=tmp_path)
    source = BUILDER.load_source(arm[1])
    reference = source["result"]["nodes"][1]["walking_reference"]
    start = min(run["samples"], key=lambda sample: abs(sample["time_s"] - run["authority"]["walk_start_s"]))
    end = min(run["samples"], key=lambda sample: abs(sample["time_s"] - run["authority"]["walk_end_s"]))
    assert start["node_index"] == 0  # Acquisition boundary ownership is retained.
    assert end["node_index"] != 1  # Closest visual endpoint has already entered Turn.
    for sample in (start, end):
        expected = independent_lateral([sample["x"], sample["y"]], reference["measurement_origin"], reference["measurement_heading_rad"])
        expected_reference = independent_lateral([sample["x"], sample["y"]], reference["control_origin"], reference["control_heading_rad"])
        target = source["summary_row"]["world_metrics"]["nodes"][1]["commanded_terminal_xy_m"]
        assert sample["first_walk_local_lateral_m"] == pytest.approx(expected, abs=1e-13)
        assert sample["first_walk_reference_lateral_m"] == pytest.approx(expected_reference, abs=1e-13)
        assert sample["first_walk_global_endpoint_error_m"] == math.hypot(sample["x"] - target[0], sample["y"] - target[1])
    assert abs(start["first_walk_local_lateral_m"]) < 1e-12
    assert end["local_lateral_m"] != end["first_walk_local_lateral_m"]
    assert run["authority"]["local_lateral_at_walk_end_m"] == source["result"]["nodes"][1]["lateral_drift_m"]
    assert run["authority"]["local_lateral_at_walk_end_m"] != end["first_walk_local_lateral_m"]


@pytest.mark.parametrize("arm", BUILDER.ARMS)
def test_command_exposure_uses_retained_trace_and_window_state(arm, tmp_path):
    run = BUILDER.build_run(*arm, data=tmp_path)
    paths = BUILDER.source_paths(arm[1])
    with gzip.open(ROOT / paths["trace"], "rt", encoding="utf-8") as stream:
        trace = [json.loads(line) for line in stream]
    boundary = run["authority"]["window_end_s"]
    before = max((s for s in run["samples"] if s["time_s"] < boundary - 1e-8), key=lambda s: s["time_s"])
    at = min(run["samples"], key=lambda s: abs(s["time_s"] - boundary))
    for sample in (before, at):
        last = next(row for row in reversed(trace) if row["time_s"] <= sample["time_s"] + 1e-10)
        assert sample["residual_action"] == last["action"]
        assert sample["applied_residual"] == last["residual"]
        assert sample["authority_active"] == last["active"]
    assert at["applied_residual"] == [0.0, 0.0, 0.0]
    assert at["first_walk_authority_active"] is False
    if arm[2] != "off":
        assert before["first_walk_authority_active"] is True
        assert before["residual_nonzero"] is True
    assert "#decoded-line=" in run["authority"]["source_locators"]["window_trace"]


def test_changed_source_result_is_refused_before_derivation(tmp_path):
    paths = BUILDER.source_paths(BUILDER.ARMS[1][1])
    for key in ("manifest", "result"):
        target = tmp_path / paths[key]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / paths[key], target)
    result = json.loads((tmp_path / paths["result"]).read_text())
    result["nodes"][1]["lateral_drift_m"] = 0.0
    (tmp_path / paths["result"]).write_text(json.dumps(result))
    with pytest.raises(ValueError, match="Retained source identity changed"):
        BUILDER.load_source(BUILDER.ARMS[1][1], tmp_path)


def test_changed_acquisition_producer_cannot_be_rebound_as_original(monkeypatch):
    result = json_at(BUILDER.source_paths(BUILDER.ARMS[0][1])["result"])
    relative = next(iter(result["provenance"]["source_hashes"]))
    original_digest = BUILDER.digest
    def changed_digest(path):
        actual = original_digest(path)
        return {**actual, "sha256": "0" * 64} if Path(path) == ROOT / relative else actual
    monkeypatch.setattr(BUILDER, "digest", changed_digest)
    with pytest.raises(ValueError, match="Source acquisition producer changed"):
        BUILDER.load_source(BUILDER.ARMS[0][1])


def test_previous_console_is_copied_without_changing_bytes(tmp_path):
    catalog, manifest = BUILDER.copy_previous(tmp_path)
    assert [row["id"] for row in catalog["runs"]] == ["alpha0-off", "alpha05-off"]
    for path, pin in manifest["files"].items():
        if path.startswith("runs/"):
            assert BUILDER.digest(tmp_path / path) == pin
    # A second idempotent copy does not reinterpret or rewrite the old run.
    assert BUILDER.copy_previous(tmp_path)[0] == catalog


def test_render_binding_refuses_changed_video_and_nonzero_physics(tmp_path):
    arm = BUILDER.ARMS[0]
    paths = BUILDER.source_paths(arm[1])
    run = BUILDER.build_run(*arm, data=tmp_path)
    directory = tmp_path / "runs" / arm[0]
    video = directory / "rollout.mp4"
    video.write_bytes(b"offline-render-binding-fixture")
    render = {"passed": True, "mj_step_calls": 0, "source_pose_sha256": BUILDER.digest(ROOT / paths["poses"])["sha256"],
              "frame_sim_times_s": run["frame_map"], "frames": len(run["samples"]), "fps": 20,
              "video_sha256": BUILDER.digest(video)["sha256"]}
    BUILDER.write(directory / "render_manifest.json", render)
    finalized = BUILDER.build_run(*arm, data=tmp_path, finalize=True)
    assert finalized["provenance"]["video_sha"] == render["video_sha256"]
    video.write_bytes(b"changed")
    with pytest.raises(ValueError, match="video hash mismatch"):
        BUILDER.build_run(*arm, data=tmp_path, finalize=True)
    video.write_bytes(b"offline-render-binding-fixture")
    render["mj_step_calls"] = 1
    BUILDER.write(directory / "render_manifest.json", render)
    with pytest.raises(ValueError, match="zero physics stepping"):
        BUILDER.build_run(*arm, data=tmp_path, finalize=True)


def test_builder_has_no_scientific_execution_imports():
    tree = ast.parse((ROOT / "console/build_authority_replay.py").read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append((node.module or "").split(".")[0])
    assert not set(imports) & {"mujoco", "torch", "g1swarm", "study"}
    assert [arm[2] for arm in BUILDER.ARMS] == ["off", "combined_inward", "corner_forward_inward"]
