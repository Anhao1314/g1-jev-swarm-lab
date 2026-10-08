"""Read-only audit of the frozen M2 mission comparison; never runs physics."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from acquire import HERE, ROOT, digest, verify_sources, write_new


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def node_without_wall(node: dict) -> dict:
    value = json.loads(json.dumps(node))
    value["metrics"].pop("wall_time_s", None)
    value.pop("feedback_decision", None)
    return value


def audit() -> dict:
    verify_sources()
    frozen = read(HERE / "protocol.json")
    checks = {}
    inventory = {}
    records = {}
    for case in ("success_mission", "failure_mission"):
        for mode in ("static_dispatch", "strict_feedback"):
            run_id = f"{case}--{mode}"
            directory = HERE / "artifacts" / run_id
            result_path, pose_path = directory / "result.json", directory / "poses.npz"
            receipt = read(directory / "receipt.json")
            result = read(result_path)
            mission = frozen[case]
            ledger_dir = directory / "ledger" / mission["mission_id"]
            graph = read(ledger_dir / "task_graph.json")
            events_path = ledger_dir / "events.jsonl"
            events = [json.loads(x) for x in events_path.read_text(encoding="utf-8").splitlines()]
            with np.load(pose_path, allow_pickle=False) as poses:
                arrays = {key: poses[key].copy() for key in ("time_s", "qpos", "qvel", "ctrl")}
            assert receipt["result_sha256"] == digest(result_path)
            assert receipt["pose_sha256"] == digest(pose_path)
            assert receipt["source_manifest_sha256"] == digest(HERE / "source_manifest.json")
            assert result["mission_id"] == mission["mission_id"]
            assert result["grounding"]["status"] == "GROUNDED"
            assert result["validation"]["valid"] is True
            assert len(arrays["time_s"]) > 2 and np.all(np.diff(arrays["time_s"]) > 0)
            assert all(np.isfinite(a).all() for a in arrays.values())
            assert arrays["time_s"][0] == 0.0
            assert abs(arrays["time_s"][-1] - result["total_simulation_time_s"]) < 1e-9
            assert len(graph["execution_order"]) == result["skill_invocations"]
            assert sum(e["event"] == "feedback_decision" for e in events) == (
                1 if mode == "strict_feedback" else 0)
            records[run_id] = (result, graph, arrays)
            inventory[run_id] = {
                "result_sha256": digest(result_path), "poses_sha256": digest(pose_path),
                "events_sha256": digest(events_path),
                "task_graph_sha256": digest(ledger_dir / "task_graph.json"),
                "pose_frames": len(arrays["time_s"]),
                "state": result["state"], "failure_type": result["failure_type"],
                "completed_nodes": result["completed_nodes"],
                "skill_invocations": result["skill_invocations"],
                "simulation_steps": result["simulation_steps_executed"],
            }
    for case in ("success_mission", "failure_mission"):
        static, _, sa = records[f"{case}--static_dispatch"]
        feedback, _, fa = records[f"{case}--strict_feedback"]
        assert node_without_wall(static["nodes"][0]) == node_without_wall(feedback["nodes"][0])
        assert len(sa["time_s"]) >= len(fa["time_s"])
        # Feedback appends the exact terminal state. The continuing static run
        # samples at 20 Hz, so its first-node endpoint can fall between frames.
        common_frames = len(fa["time_s"])
        if sa["time_s"][common_frames - 1] != fa["time_s"][-1]:
            common_frames -= 1
        checks[f"{case}_first_skill_exact"] = all(
            np.array_equal(sa[key][:common_frames], fa[key][:common_frames]) for key in sa)
        assert checks[f"{case}_first_skill_exact"]
    safe_static, _, _ = records["success_mission--static_dispatch"]
    safe_feedback, _, _ = records["success_mission--strict_feedback"]
    fail_static, _, _ = records["failure_mission--static_dispatch"]
    fail_feedback, fail_graph, _ = records["failure_mission--strict_feedback"]
    assert safe_static["state"] == safe_feedback["state"] == "SUCCESS"
    assert safe_static["completed_nodes"] == safe_feedback["completed_nodes"] == 3
    checks["bounded_positive_retained"] = True
    assert fail_static["state"] == "SUCCESS" and fail_static["completed_nodes"] == 3
    assert fail_feedback["state"] == "FAILED" and fail_feedback["failure_type"] == "TASK_ENVELOPE_VIOLATION"
    assert fail_feedback["failed_node"] == "s1" and fail_feedback["skill_invocations"] == 1
    assert [n["state"] for n in fail_graph["nodes"]] == ["FAILED", "BLOCKED", "BLOCKED"]
    decision = fail_feedback["nodes"][0]["feedback_decision"]
    assert decision["action"] == "STOP_DEPENDENTS"
    assert decision["evaluation"]["violations"] == ["EXCESSIVE_DRIFT", "HEADING_ERROR"]
    checks["real_feedback_changes_dispatch"] = True
    checks["no_recovery_or_claimed_physical_stop"] = fail_feedback["nodes"][0]["metrics"]["final_speed_mps"] > 0.1
    assert checks["no_recovery_or_claimed_physical_stop"]
    payload = {
        "status": "PASS", "study": frozen["experiment_id"],
        "protocol_sha256": digest(HERE / "protocol.json"),
        "source_manifest_sha256": digest(HERE / "source_manifest.json"),
        "checks": checks, "inventory": inventory,
        "failure_first_walk": {
            "physical_success": fail_feedback["nodes"][0]["metrics"]["physical_success"],
            "skill_status": fail_feedback["nodes"][0]["metrics"]["skill_status"],
            "lateral_drift_m": fail_feedback["nodes"][0]["metrics"]["lateral_drift_m"],
            "heading_error_deg": fail_feedback["nodes"][0]["metrics"]["heading_error_deg"],
            "strict_limits": decision["evaluation"]["limits"],
            "violations": decision["evaluation"]["violations"],
            "final_speed_mps": fail_feedback["nodes"][0]["metrics"]["final_speed_mps"],
        },
    }
    return payload


if __name__ == "__main__":
    result = audit()
    write_new(HERE / "audit.json", result)
    print(json.dumps({"status": result["status"], "checks": result["checks"]}, allow_nan=False))
