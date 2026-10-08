"""Publish M2.3b native capture as read-only, source-bound Console playback.

No mission, controller, or physics step runs here. Video generation restores
saved poses through the existing zero-mj_step M2 renderer.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from console.build_m2_replay import angle_deg, load, record, render, write_new, yaw
from g1swarm.config import load_yaml

SOURCE = ROOT / "experiments/m2/trusted_handoff_qualification_001"
OUTPUT = ROOT / "experiments/research_console/m23b_trusted_handoff_001"
RUNS = ("trusted_authorized", "halt_only_invalid")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_run(name: str) -> tuple[Path, dict]:
    source = SOURCE / "artifacts" / name
    receipt = load(source / "receipt.json")
    for file, expected in receipt["artifact_files"].items():
        if sha(source / file) != expected:
            raise ValueError(f"Acquisition receipt mismatch: {name}/{file}")
    if receipt["source_manifest_sha256"] != sha(SOURCE / "source_manifest.json"):
        raise ValueError("Frozen source manifest mismatch")
    return source, receipt


def build_run(name: str, *, render_video: bool = True) -> dict:
    source, receipt = verify_run(name)
    parent = load(source / "parent_result.json")
    new = load(source / "new_result.json") if (source / "new_result.json").exists() else None
    lifecycle = load(source / "lifecycle_events.json")
    continuity = load(source / "continuity.json")
    qualification = load(source / "qualification.json")
    spec = load(SOURCE / "protocol.json")
    frozen = load(SOURCE / "source_manifest.json")["files"]
    robot_path = "configs/robot/g1_locomotion_12dof.yaml"
    if sha(ROOT / robot_path) != frozen[robot_path]:
        raise ValueError("Frozen policy configuration mismatch")
    policy = load_yaml(ROOT / robot_path)["controller"]
    relative = source.relative_to(ROOT).as_posix()
    output = OUTPUT / "runs" / name
    output.mkdir(parents=True, exist_ok=False)
    nodes, decisions, events = [], [], []

    def decision(time, mission_id, stage, value, evaluation, action, locator, node_index=None):
        item = {"time_s": float(time), "mission_id": mission_id, "lifecycle_stage": stage,
                "node_index": node_index, "decision": value, "evaluation": evaluation,
                "action": action, "continuation": stage, "source_locator": locator}
        decisions.append(item)
        events.append({"id": f"decision-{len(events)}", "time_s": float(time),
                       "node_index": node_index, "label": f"{stage}: {value}",
                       "metric": "runtime_decision", "value": value,
                       "failure": value in {"STOP_DEPENDENTS", "HALT_FAILED", "ESCALATE",
                                             "new_mission_rejected", "trusted_handoff_rejected"},
                       "source_locator": locator})

    def mission_nodes(result, role, start, filename):
        cursor = start
        for index, original in enumerate(result["nodes"]):
            metrics = original["metrics"]
            end = cursor + float(metrics["simulation_time_s"])
            feedback = original.get("feedback_decision") or {}
            evaluation = feedback.get("evaluation") or {}
            node_index = len(nodes)
            locator = relative + f"/{filename}#/nodes/{index}"
            nodes.append({"index": node_index, "node_id": original["node_id"],
                          "mission_id": result["mission_id"], "mission_role": role,
                          "skill": original["skill"], "start_s": cursor, "end_s": end,
                          "task_status": "PASS" if metrics["task_success"] else "FAIL",
                          "strict_status": "PASS" if evaluation.get("satisfied") is True else
                                           "FAIL" if evaluation.get("satisfied") is False else "Unavailable",
                          "physical_status": "PASS" if metrics["physical_success"] else "FAIL",
                          "strict_lateral_limit_m": evaluation.get("limits", {}).get("lateral_drift_max_m"),
                          "strict_violations": evaluation.get("violations", []), "source_locator": locator})
            action = feedback.get("action", "CONTINUE")
            decision(end, result["mission_id"], role, action, evaluation or "Task completed",
                     "Block descendants" if action == "STOP_DEPENDENTS" else "Dispatch next READY node",
                     locator, node_index)
            cursor = end

    mission_nodes(parent, "original_mission", 0.0, "parent_result.json")
    halt = parent.get("physical_halt")
    if halt:
        start = halt["pre_halt_state"]["simulation_time"]
        end = halt["final_state"]["simulation_time"]
        locator = relative + "/parent_result.json#/physical_halt"
        node_index = len(nodes)
        nodes.append({"index": node_index, "mission_id": parent["mission_id"], "mission_role": "physical_halt",
                      "skill": "independent_physical_halt", "start_s": start, "end_s": end,
                      "task_status": "Unavailable", "strict_status": "Unavailable",
                      "physical_status": "PASS" if halt["status"] == "HALT_SUCCEEDED" else "FAIL",
                      "source_locator": locator})
        decision(start, parent["mission_id"], "physical_halt", "PHYSICAL_HALT_REQUESTED", "Task already blocked",
                 "Experiment-configured StopSkill; blocked task nodes remain blocked", locator + "/request", node_index)
        decision(end, parent["mission_id"], "physical_halt", halt["status"], halt["checks"],
                 "Finish bounded halt attempt; no hardware safety claim", locator + "/status", node_index)

    for index, entry in enumerate(lifecycle):
        value = entry["event"]
        evaluation = {key: entry[key] for key in (
            "scope", "assurance", "production_authority", "eligible", "reasons", "reason",
            "status", "handoff_consumption", "handoff_plan_sha256", "lifecycle_mission_sha256",
            "integration_epoch", "permission", "principal_id", "parent_preserved",
        ) if key in entry}
        if value == "post_halt_assessment":
            action = "Read current same-session state and frozen new Mission"
        elif value in {"trusted_handoff_rejected", "new_mission_rejected"}:
            action = "Refuse new dispatch; ESCALATE is not an ongoing physical safety controller"
        elif value == "trusted_handoff_verified":
            action = "TEST_ONLY registered fixture identity and host permission; execute issuer-owned canonical bytes"
        elif value == "trusted_handoff_prepared":
            action = "Bind complete canonical Mission, request context and current lifecycle state"
        elif value in {"test_only_authorization_issued", "new_mission_authorized"}:
            action = "Trusted serial TEST_ONLY experiment entry; no production identity or concurrent atomicity"
        else:
            action = "Record separate lifecycle result; retain original failed mission"
        decision(entry["simulation_time_s"], entry.get("new_mission_id", parent["mission_id"]),
                 "trusted_handoff" if value.startswith("trusted_handoff") else "lifecycle", value,
                 evaluation, action, relative + f"/lifecycle_events.json#/{index}")
    if new:
        mission_nodes(new, "new_mission", continuity["before_new_mission"]["time_s"], "new_result.json")

    with np.load(source / "poses.npz", allow_pickle=False) as poses:
        times, qpos, qvel = poses["time_s"], poses["qpos"], poses["qvel"]
        if not len(times) or not np.all(np.diff(times) > 0):
            raise ValueError("Invalid native capture times")
        samples = []
        for frame, time in enumerate(times):
            node = next((n for n in nodes if n["start_s"] <= time <= n["end_s"]), nodes[-1])
            begin = min(int(np.searchsorted(times, node["start_s"], side="left")), len(times) - 1)
            heading = yaw(qpos[begin]); offset = qpos[frame, :2] - qpos[begin, :2]
            samples.append({"time_s": float(time), "frame_index": frame, "node_index": node["index"],
                            "skill": node["skill"], "mission_id": node["mission_id"], "mission_role": node["mission_role"],
                            "x": float(qpos[frame, 0]), "y": float(qpos[frame, 1]),
                            "speed_mps": float(np.linalg.norm(qvel[frame, :2])),
                            "actual_heading_deg": angle_deg(yaw(qpos[frame])),
                            "local_lateral_m": float(-math.sin(heading)*offset[0] + math.cos(heading)*offset[1]),
                            "source_locator": relative + f"/poses.npz#frame={frame}"})
        frame_map = times.tolist()
    decision(frame_map[-1], new["mission_id"] if new else parent["mission_id"], "qualification",
             "QUALIFICATION_RECORDED", qualification,
             "Inspect measured plan identity, parent preservation, physics steps and reset continuity",
             relative + "/qualification.json")
    decisions.sort(key=lambda item: item["time_s"])
    events.sort(key=lambda item: item["time_s"])
    if render_video:
        write_new(output / "render_manifest.json", render(source, output / "rollout.mp4"))
    provenance = {"source_result_path": relative + "/parent_result.json", "source_result_format": "json",
                  "source_protocol_path": (SOURCE / "protocol.json").relative_to(ROOT).as_posix(),
                  "source_runtime_ledger_path": relative + f"/ledger/{parent['mission_id']}/events.jsonl",
                  "source_trace_path": relative + "/state_trace.jsonl.gz", "source_poses_path": relative + "/poses.npz",
                  "source_continuity_path": relative + "/continuity.json", "source_authorization_path": relative + "/requests.json",
                  "source_assessment_path": relative + "/assessment.json", "source_lifecycle_path": relative + "/lifecycle_events.json",
                  "source_qualification_path": relative + "/qualification.json", "protocol_sha": sha(SOURCE / "protocol.json"),
                  "source_commit": receipt["source_commit"], "seed": spec["seed"], "policy_sha": frozen[policy["policy_path"]],
                  "policy_identity": f"{policy['kind']} · {policy['policy_path']} · {policy['source_repository']}@{policy['source_commit']}",
                  "producer_execution_base_commit": receipt["source_commit"], "producer_code_sha": sha(Path(__file__))}
    if (source / "handoff_events.json").exists():
        provenance["source_handoff_path"] = relative + "/handoff_events.json"
    if new:
        provenance.update(source_new_result_path=relative + "/new_result.json",
                          source_new_ledger_path=relative + f"/ledger/{new['mission_id']}/events.jsonl")
    terminal = "NEW_MISSION_COMPLETED" if new and new["mission_success"] else "ESCALATE"
    run = {"schema_version": 1, "runtime_kind": "closed_loop_mission", "id": name,
           "label": {"trusted_authorized": "TEST_ONLY trusted canonical handoff",
                     "halt_only_invalid": "Invalid handoff control"}[name],
           "experiment_id": "trusted_handoff_qualification_001", "case_id": parent["mission_id"], "treatment": name,
           "seed": spec["seed"], "visual_source": "state_playback",
           "media_caption": "Native same-session MuJoCo capture · trusted serial TEST_ONLY · render only",
           "duration_s": frame_map[-1], "frame_fps": 20, "frame_map": frame_map,
           "video_url": f"/media/{name}/rollout.mp4", "nodes": nodes, "samples": samples,
           "runtime_decisions": decisions, "events": events, "ideal_route": [], "qualification": qualification,
           "summary": {"task_status": "PASS" if parent["mission_success"] else "FAIL",
                       "original_mission_status": parent["state"],
                       "strict_status": "FAIL" if any(n["strict_status"] == "FAIL" for n in nodes if n["mission_role"] == "original_mission") else "PASS",
                       "physical_status": "PASS" if parent["physical_success"] else "FAIL",
                       "halt_status": halt["status"] if halt else "NOT_REQUESTED",
                       "new_mission_status": new["state"] if new else "NOT_EXECUTED", "lifecycle_status": terminal},
           "provenance": provenance, "evidence_url": f"/api/evidence/{name}"}
    write_new(output / "run.json", run)
    return run


def build(*, render_video: bool = True) -> None:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    OUTPUT.mkdir(parents=True)
    runs = [build_run(name, render_video=render_video) for name in RUNS]
    write_new(OUTPUT / "catalog.json", {"schema_version": 1, "title": "M2.3b trusted Mission handoff qualification",
              "runs": [{"id": run["id"]} for run in runs], "experiments": [{"id": "trusted_handoff",
              "title": "M2.3b · Failure → Halt → Trusted canonical handoff → New Mission / Refusal",
              "description": "Read-only native capture; TEST_ONLY fixture identity and trusted serial entry. No production permission, concurrency or hardware safety claim.",
              "case_id": runs[0]["case_id"], "arms": [{"id": run["id"], "label": run["label"],
              "run_url": f"/api/runs/{run['id']}"} for run in runs]}]})
    sources = {SOURCE / "protocol.json", SOURCE / "source_manifest.json", Path(__file__)}
    for name in RUNS:
        source, _ = verify_run(name)
        sources.update(path for path in source.rglob("*") if path.is_file())
    write_new(OUTPUT / "manifest.json", {"schema_version": 1, "visual_source": "state_playback",
              "scientific_evidence_modified": False,
              "files": {path.relative_to(OUTPUT).as_posix(): record(path) for path in OUTPUT.rglob("*") if path.is_file()},
              "sources": {path.relative_to(ROOT).as_posix(): record(path) for path in sorted(sources)}})


if __name__ == "__main__":
    if sys.argv[1:] == ["--data-only"]:
        build(render_video=False)
    elif not sys.argv[1:]:
        build()
    else:
        raise SystemExit("usage: build_m23b_replay.py [--data-only]")
