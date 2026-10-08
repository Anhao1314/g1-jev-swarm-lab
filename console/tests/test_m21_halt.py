"""Read-only checks that the M2.1 visual follows integrated halt evidence."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from console.server import ConsoleData


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "experiments/m2/post_failure_halt_integration_001/artifacts"
VISUAL = ROOT / "experiments/research_console/m2_post_failure_halt_001"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_integrated_halt_is_distinct_from_task_block_and_uses_real_pose_times():
    data = ConsoleData(VISUAL, ROOT)
    assert data.verification["status"] == "VERIFIED"
    run = data.runs["failure_opt_in"]
    result = load(SOURCE / "failure_opt_in/result.json")
    halt = result["physical_halt"]
    with np.load(SOURCE / "failure_opt_in/poses.npz", allow_pickle=False) as poses:
        assert run["frame_map"] == poses["time_s"].tolist()
        assert len(run["samples"]) == len(poses["time_s"])
        assert run["samples"][-1]["x"] == float(poses["qpos"][-1, 0])
    decisions = [item["decision"] for item in run["runtime_decisions"]]
    assert decisions == ["STOP_DEPENDENTS", "PHYSICAL_HALT_REQUESTED", halt["status"]]
    assert run["runtime_decisions"][0]["time_s"] == result["total_simulation_time_s"]
    assert run["runtime_decisions"][1]["time_s"] == result["total_simulation_time_s"]
    assert run["runtime_decisions"][2]["time_s"] == halt["final_state"]["simulation_time"]
    assert run["summary"]["task_status"] == "FAIL"
    assert run["summary"]["halt_status"] == "HALT_SUCCEEDED"
    assert run["duration_s"] > result["total_simulation_time_s"]


def test_safe_control_has_no_halt_event_or_task_regression():
    data = ConsoleData(VISUAL, ROOT)
    run = data.runs["safe_opt_in"]
    result = load(SOURCE / "safe_opt_in/result.json")
    assert "physical_halt" not in result
    assert len(result["nodes"]) == 3
    assert len(run["nodes"]) == 3
    assert run["summary"]["halt_status"] == "NOT_REQUESTED"
    assert not any("halt" in event["id"] for event in run["events"])
