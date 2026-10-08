"""Publish captured M2.1 halt evidence as read-only state playback.

This builder renders saved qpos/qvel/ctrl using mj_forward; it never runs a
mission, controller, policy, or physics step. M2.0 artifacts are untouched.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from build_m2_replay import ROOT, render, yaw, angle_deg, record, write_new, load

SOURCE = ROOT / "experiments/m2/post_failure_halt_integration_001"
OUTPUT = ROOT / "experiments/research_console/m2_post_failure_halt_001"
RUNS = ("failure_opt_in", "safe_opt_in")
FROZEN_SOURCE_COMMIT = "4ace485cacae7de1dbfa866a94960b37abb81ef0"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_run(name: str) -> tuple[Path, dict, dict | None]:
    source = SOURCE / "artifacts" / name
    receipt = load(source / "receipt.json")
    if receipt["result_sha256"] != sha(source / "result.json"):
        raise ValueError(f"Result receipt mismatch: {name}")
    if receipt["pose_sha256"] != sha(source / "poses.npz"):
        raise ValueError(f"Pose receipt mismatch: {name}")
    result = load(source / "result.json")
    halt = result.get("physical_halt")
    if receipt["physical_halt_status"] != (halt or {}).get("status"):
        raise ValueError(f"Halt status receipt mismatch: {name}")
    return source, result, halt


def build_run(name: str) -> dict:
    source, result, halt = verify_run(name)
    output = OUTPUT / "runs" / name
    output.mkdir(parents=True, exist_ok=False)
    protocol = load(SOURCE / "protocol.json")
    mission = load(ROOT / protocol["mission_source"])[protocol["failure_case"] if halt else protocol["safe_control"]]
    ledger = source / "ledger" / result["mission_id"] / "events.jsonl"
    with np.load(source / "poses.npz", allow_pickle=False) as poses:
        times, qpos, qvel = poses["time_s"], poses["qpos"], poses["qvel"]
        if not len(times) or not np.all(np.diff(times) > 0):
            raise ValueError("Invalid pose times")
        block_time = float(result["total_simulation_time_s"])
        if halt and not (times[0] <= block_time <= times[-1]):
            raise ValueError("Halt request must coincide with the task block or precede post-block capture")
        if halt and "pre_halt_state" in halt and abs(float(halt["pre_halt_state"]["simulation_time"]) - block_time) > .003:
            raise ValueError("Halt and mission times disagree")
        durations = [float(n["metrics"]["simulation_time_s"]) for n in result["nodes"]]
        ends = np.cumsum(durations).tolist()
        starts = [0.0] + ends[:-1]
        nodes, decisions, events, samples = [], [], [], []
        heading = yaw(qpos[0]); origin = np.array(qpos[0, :2], copy=True)
        route = [origin.tolist()]
        for i, node in enumerate(result["nodes"]):
            skill, metric = node["skill"], node["metrics"]
            step = mission["steps"][i]
            strict = None
            if skill == "walk_forward":
                from g1swarm.boundary.envelope import STRICT_WALK_ENVELOPE
                strict = STRICT_WALK_ENVELOPE.evaluate(metric, float(step["parameters"]["distance_m"]))
                origin = origin + float(step["parameters"]["distance_m"]) * np.array([math.cos(heading), math.sin(heading)])
                route.append(origin.tolist())
            if skill == "turn":
                heading += math.radians(float(step["parameters"]["angle_deg"]))
            decision = node.get("feedback_decision")
            action = decision["action"] if decision else "CONTINUE"
            locator = source.relative_to(ROOT).as_posix() + f"/result.json#/nodes/{i}"
            decisions.append({"time_s": ends[i], "node_index": i, "observation": decision.get("observed_metrics", {}) if decision else {},
                              "evaluation": decision.get("evaluation", "Task completed") if decision else "Task completed",
                              "decision": action, "action": "Block task descendants" if action == "STOP_DEPENDENTS" else "Dispatch next READY node",
                              "continuation": action, "source_locator": locator})
            events.append({"id": f"node-{i}-decision", "time_s": ends[i], "node_index": i,
                           "label": f"{step['id']} {skill}: {action}", "metric": "task_decision", "value": action,
                           "failure": action == "STOP_DEPENDENTS", "source_locator": locator})
            nodes.append({"index": i, "skill": skill, "start_s": starts[i], "end_s": ends[i],
                          "task_status": "PASS" if metric["task_success"] else "FAIL",
                          "strict_status": "PASS" if strict and strict.satisfied else "FAIL" if strict else "Unavailable",
                          "physical_status": "PASS" if metric["physical_success"] else "FAIL",
                          "strict_lateral_limit_m": strict.limits.lateral_max_m if strict else None,
                          "strict_violations": strict.violations if strict else [], "source_locator": locator})
        if halt:
            halt_locator = source.relative_to(ROOT).as_posix() + "/result.json#/physical_halt"
            status = halt["status"]
            decisions.extend((
                {"time_s": block_time, "node_index": 0, "observation": {}, "evaluation": "Task graph already blocked",
                 "decision": "PHYSICAL_HALT_REQUESTED", "action": "Independent explicit Stop skill; no task node dispatch",
                 "continuation": "TASK_BLOCKED", "source_locator": halt_locator + "/request"},
                {"time_s": float(times[-1]), "node_index": 0, "observation": halt.get("final_state", {}),
                 "evaluation": halt.get("checks", {}), "decision": status, "action": "End physical halt attempt",
                 "continuation": "TASK_BLOCKED", "source_locator": halt_locator + "/status"},
            ))
            events.extend((
                {"id": "halt-request", "time_s": block_time, "node_index": 0, "label": "Independent physical halt requested",
                 "metric": "halt_request", "value": halt["request"], "failure": True,
                 "source_locator": halt_locator + "/request"},
                {"id": "halt-completion", "time_s": float(times[-1]), "node_index": 0,
                 "label": f"Physical halt: {status}", "metric": "halt_status", "value": status,
                 "failure": status != "HALT_SUCCEEDED", "source_locator": halt_locator + "/status"},
            ))
        for frame, t in enumerate(times):
            index = min(int(np.searchsorted(ends, t, side="left")), len(ends) - 1)
            start_frame = int(np.searchsorted(times, starts[index], side="left"))
            local_origin = qpos[start_frame, :2]; local_heading = yaw(qpos[start_frame]); offset = qpos[frame, :2] - local_origin
            samples.append({"time_s": float(t), "frame_index": frame, "node_index": index,
                            "skill": "independent_physical_halt" if halt and t > block_time + 1e-8 else result["nodes"][index]["skill"],
                            "x": float(qpos[frame, 0]), "y": float(qpos[frame, 1]),
                            "actual_heading_deg": angle_deg(yaw(qpos[frame])), "commanded_heading_deg": None,
                            "reference_heading_deg": None,
                            "local_lateral_m": float(-math.sin(local_heading)*offset[0]+math.cos(local_heading)*offset[1]),
                            "global_lateral_m": None, "heading_error_deg": None,
                            "speed_mps": float(np.linalg.norm(qvel[frame, :2])),
                            "source_locator": source.relative_to(ROOT).as_posix()+f"/poses.npz#frame={frame}"})
    video = output / "rollout.mp4"
    rendering = render(source, video)
    write_new(output / "render_manifest.json", rendering)
    provenance = {"source_result_path": (source / "result.json").relative_to(ROOT).as_posix(),
                  "source_poses_path": (source / "poses.npz").relative_to(ROOT).as_posix(),
                  "source_protocol_path": (SOURCE / "protocol.json").relative_to(ROOT).as_posix(),
                  "source_runtime_ledger_path": ledger.relative_to(ROOT).as_posix(),
                  "source_result_format": "json", "source_result_locator": (source / "result.json").relative_to(ROOT).as_posix(),
                  "protocol_sha": sha(SOURCE / "protocol.json"),
                  "source_commit": FROZEN_SOURCE_COMMIT,
                  "producer_code_sha": sha(Path(__file__))}
    summary = {"task_status": "PASS" if result["mission_success"] else "FAIL",
               "strict_status": "PASS" if all(n["strict_status"] != "FAIL" for n in nodes) else "FAIL",
               "physical_status": "PASS" if result["physical_success"] else "FAIL",
               "halt_status": halt["status"] if halt else "NOT_REQUESTED"}
    run = {"schema_version": 1, "runtime_kind": "closed_loop_mission", "id": name,
           "label": "Failure · integrated physical halt" if halt else "Safe task · no halt control",
           "experiment_id": "post_failure_halt_integration_001", "case_id": result["mission_id"],
           "treatment": name, "duration_s": float(times[-1]), "visual_source": "state_playback",
           "media_caption": "Captured MuJoCo states · render only", "video_url": f"/media/{name}/rollout.mp4",
           "frame_fps": 20, "frame_map": times.tolist(), "ideal_route": route, "samples": samples,
           "nodes": nodes, "runtime_decisions": decisions, "events": events,
           "summary": summary, "provenance": provenance, "evidence_url": f"/api/evidence/{name}"}
    write_new(output / "run.json", run)
    return run


def build() -> None:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    OUTPUT.mkdir(parents=True)
    runs = [build_run(name) for name in RUNS]
    write_new(OUTPUT / "catalog.json", {"schema_version": 1, "title": "M2.1 post-failure physical halt integration",
              "runs": [{"id": r["id"]} for r in runs],
              "experiments": [{"id": "post_failure_halt", "title": "M2.1 · task block and independent halt",
                               "description": "Integrated opt-in Stop and unchanged safe control; not a hardware safety claim",
                               "case_id": runs[0]["case_id"],
                               "arms": [{"id": r["id"], "label": r["label"], "run_url": f"/api/runs/{r['id']}"} for r in runs]}]})
    derived = {p.relative_to(OUTPUT).as_posix(): record(p) for p in OUTPUT.rglob("*") if p.is_file()}
    source_files = {SOURCE / "protocol.json", SOURCE / "source_manifest.json", Path(__file__)}
    for name in RUNS:
        source, result, halt = verify_run(name)
        source_files.update((source / "result.json", source / "poses.npz", source / "receipt.json",
                             source / "ledger" / result["mission_id"] / "events.jsonl"))
    write_new(OUTPUT / "manifest.json", {"schema_version": 1, "visual_source": "state_playback",
              "scientific_evidence_modified": False, "files": derived,
              "sources": {p.relative_to(ROOT).as_posix(): record(p) for p in sorted(source_files)}})


if __name__ == "__main__":
    build()
