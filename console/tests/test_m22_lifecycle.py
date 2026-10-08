"""Source-bound lifecycle playback; no simulation or controller execution."""
from pathlib import Path
import json

import numpy as np

from console.server import ConsoleData

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "experiments/m2/adaptive_mission_lifecycle_001/artifacts"
VISUAL = ROOT / "experiments/research_console/m2_adaptive_lifecycle_001"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_continuous_authorized_replay_retains_failed_parent_and_distinct_successful_mission():
    data = ConsoleData(VISUAL, ROOT)
    assert data.verification["status"] == "VERIFIED"
    run = data.runs["adaptive_authorized"]
    original = load(SOURCE / "adaptive_authorized/parent_result.json")
    new = load(SOURCE / "adaptive_authorized/new_result.json")
    continuity = load(SOURCE / "adaptive_authorized/continuity.json")
    with np.load(SOURCE / "adaptive_authorized/poses.npz", allow_pickle=False) as poses:
        assert run["frame_map"] == poses["time_s"].tolist()
        assert [sample["x"] for sample in run["samples"]] == poses["qpos"][:, 0].tolist()
        assert [sample["speed_mps"] for sample in run["samples"]] == np.linalg.norm(poses["qvel"][:, :2], axis=1).tolist()
    assert run["summary"]["original_mission_status"] == original["state"] == "FAILED"
    assert run["summary"]["new_mission_status"] == new["state"] == "SUCCESS"
    new_nodes = [node for node in run["nodes"] if node["mission_role"] == "new_mission"]
    assert new_nodes[0]["start_s"] == continuity["before_new_mission"]["time_s"]
    assert {node["mission_id"] for node in new_nodes} == {new["mission_id"]}
    assert original["mission_id"] != new["mission_id"]
    authorized = [d for d in run["runtime_decisions"] if d["decision"] == "new_mission_authorized"]
    assert len(authorized) == 1
    assert authorized[0]["time_s"] == new_nodes[0]["start_s"]
    assert authorized[0]["evaluation"]["scope"] == "TEST_ONLY"
    assert run["duration_s"] > original["physical_halt"]["final_state"]["simulation_time"]
    links = data.raw[run["id"]]
    for kind in ("assessment", "authorization", "continuity", "lifecycle", "new_result", "new_ledger"):
        assert f"source-{kind}" in links
    assert links["source-result"].name == "parent_result.json"
    assert links["source-new_result"].name == "new_result.json"
    spec = load(ROOT / "experiments/m2/adaptive_mission_lifecycle_001/protocol.json")
    frozen = load(ROOT / "experiments/m2/adaptive_mission_lifecycle_001/source_manifest.json")
    receipt = load(SOURCE / "adaptive_authorized/receipt.json")
    assert run["seed"] == run["provenance"]["seed"] == spec["seed"]
    assert run["provenance"]["policy_sha"] == frozen["files"]["third_party/unitree_rl_gym/deploy/pre_train/g1/motion.pt"]
    assert "official_pretrained_policy" in run["provenance"]["policy_identity"]
    assert run["provenance"]["producer_execution_base_commit"] == receipt["source_commit"]


def test_missing_authorization_is_a_zero_dispatch_refusal_not_recovery_or_safety():
    data = ConsoleData(VISUAL, ROOT)
    run = data.runs["halt_only_no_authorization"]
    assert run["summary"]["original_mission_status"] == "FAILED"
    assert run["summary"]["halt_status"] == "HALT_SUCCEEDED"
    assert run["summary"]["new_mission_status"] == "NOT_EXECUTED"
    assert run["summary"]["lifecycle_status"] == "ESCALATE"
    assert not any(node["mission_role"] == "new_mission" for node in run["nodes"])
    refusal = next(d for d in run["runtime_decisions"] if d["decision"] == "new_mission_rejected")
    assert refusal["evaluation"]["reason"] == "AUTHORIZATION_MISSING"
    assert "zero new physics" in refusal["action"]
    assert "No ongoing physical safety guarantee" in refusal["action"]


def test_normal_control_has_no_lifecycle_or_halt():
    run = ConsoleData(VISUAL, ROOT).runs["normal_control"]
    assert run["summary"]["original_mission_status"] == "SUCCESS"
    assert run["summary"]["new_mission_status"] == "NOT_EXECUTED"
    assert run["summary"]["halt_status"] == "NOT_REQUESTED"
    assert len(run["nodes"]) == 3
    assert {node["mission_role"] for node in run["nodes"]} == {"original_mission"}
    assert all(item["lifecycle_stage"] == "original_mission" for item in run["runtime_decisions"])
