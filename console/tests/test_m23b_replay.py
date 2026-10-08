"""M2.3b source-bound Console checks; no simulator execution or rescoring."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from console.server import ConsoleData
from scripts import build_m23b_replay as builder


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "experiments/m2/trusted_handoff_qualification_001/artifacts"
VISUAL = ROOT / "experiments/research_console/m23b_trusted_handoff_001"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_authorized_capture_retains_failed_parent_and_distinct_real_new_mission():
    data = ConsoleData(VISUAL, ROOT)
    assert data.verification["status"] == "VERIFIED"
    run = data.runs["trusted_authorized"]
    raw = SOURCE / run["id"]
    original, new = load(raw / "parent_result.json"), load(raw / "new_result.json")
    continuity = load(raw / "continuity.json")
    with np.load(raw / "poses.npz", allow_pickle=False) as poses:
        assert run["frame_map"] == poses["time_s"].tolist()
        assert [sample["x"] for sample in run["samples"]] == poses["qpos"][:, 0].tolist()
        assert [sample["speed_mps"] for sample in run["samples"]] == np.linalg.norm(poses["qvel"][:, :2], axis=1).tolist()
    assert run["summary"]["original_mission_status"] == original["state"]
    assert run["summary"]["new_mission_status"] == new["state"]
    assert original["mission_id"] != new["mission_id"]
    new_nodes = [node for node in run["nodes"] if node["mission_role"] == "new_mission"]
    assert new_nodes[0]["start_s"] == continuity["before_new_mission"]["time_s"]
    assert {node["mission_id"] for node in new_nodes} == {new["mission_id"]}
    assert run["duration_s"] > original["physical_halt"]["final_state"]["simulation_time"]


def test_plan_identity_and_zero_dispatch_refusals_are_bound_to_original_qualification():
    data = ConsoleData(VISUAL, ROOT)
    for name in builder.RUNS:
        run = data.runs[name]
        qualification = load(SOURCE / name / "qualification.json")
        assert run["qualification"] == qualification
        recorded = next(item for item in run["runtime_decisions"] if item["decision"] == "QUALIFICATION_RECORDED")
        assert recorded["evaluation"] == qualification
        assert recorded["time_s"] == run["duration_s"]
        assert recorded["source_locator"].endswith("/qualification.json")
        source_events = load(SOURCE / name / "lifecycle_events.json")
        derived = [item for item in run["runtime_decisions"] if "/lifecycle_events.json#/" in item["source_locator"]]
        assert len(derived) == len(source_events)
        for item in derived:
            event = source_events[int(item["source_locator"].rsplit("/", 1)[1])]
            assert item["time_s"] == event["simulation_time_s"]
            assert item["decision"] == event["event"]
            for key in ("handoff_plan_sha256", "lifecycle_mission_sha256", "permission", "reason", "parent_preserved"):
                if key in event:
                    assert item["evaluation"][key] == event[key]
        links = data.raw[name]
        for kind in ("authorization", "assessment", "continuity", "lifecycle", "qualification"):
            assert f"source-{kind}" in links
        assert links["source-qualification"] == (SOURCE / name / "qualification.json").resolve()


def test_invalid_handoff_has_no_new_mission_visual_and_no_unsupported_safety_claim():
    data = ConsoleData(VISUAL, ROOT)
    run = data.runs["halt_only_invalid"]
    assert run["summary"]["new_mission_status"] == "NOT_EXECUTED"
    assert run["summary"]["lifecycle_status"] == "ESCALATE"
    assert not any(node["mission_role"] == "new_mission" for node in run["nodes"])
    refused = [item for item in run["runtime_decisions"] if item["decision"] == "trusted_handoff_rejected"]
    assert refused
    assert all("not an ongoing physical safety" in item["action"] for item in refused)
    qualification = load(SOURCE / "halt_only_invalid/qualification.json")
    assert qualification["actual_dispatch_plan_sha256"] is None
    assert qualification["ledger_plan_sha256"] is None
    assert all(control["physics_steps_delta"] == 0 and control["node_calls_delta"] == 0
               and control["reset_calls_delta"] == 0 for control in qualification["controls"])


def test_source_receipt_mismatch_rejects_before_output_or_render(tmp_path, monkeypatch):
    source = tmp_path / "source"
    arm = source / "artifacts/trusted_authorized"
    arm.mkdir(parents=True)
    (source / "source_manifest.json").write_text("{}", encoding="utf-8")
    (arm / "parent_result.json").write_text("{}", encoding="utf-8")
    (arm / "receipt.json").write_text(json.dumps({"artifact_files": {"parent_result.json": "0" * 64},
        "source_manifest_sha256": builder.sha(source / "source_manifest.json")}), encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setattr(builder, "SOURCE", source)
    monkeypatch.setattr(builder, "OUTPUT", output)
    with pytest.raises(ValueError, match="Acquisition receipt mismatch"):
        builder.build_run("trusted_authorized")
    assert not output.exists()


def test_native_pose_render_is_zero_step_and_exact_source_identity():
    for name in builder.RUNS:
        manifest = load(VISUAL / "runs" / name / "render_manifest.json")
        assert manifest["passed"] is True
        assert manifest["mj_step_calls"] == 0
        assert manifest["source_pose_sha256"] == builder.sha(SOURCE / name / "poses.npz")
        assert manifest["video_sha256"] == builder.sha(VISUAL / "runs" / name / "rollout.mp4")
        run = load(VISUAL / "runs" / name / "run.json")
        assert manifest["frame_sim_times_s"] == run["frame_map"]
