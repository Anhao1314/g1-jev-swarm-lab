"""Publish native M2.2 lifecycle capture; restore poses with zero mj_step."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

from build_m2_replay import ROOT, render, yaw, angle_deg, record, write_new, load
from g1swarm.config import load_yaml

SOURCE = ROOT / "experiments/m2/adaptive_mission_lifecycle_001"
OUTPUT = ROOT / "experiments/research_console/m2_adaptive_lifecycle_001"
RUNS = ("adaptive_authorized", "halt_only_no_authorization", "normal_control")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_run(name: str):
    source = SOURCE / "artifacts" / name
    receipt = load(source / "receipt.json")
    for file, expected in receipt["artifact_files"].items():
        if sha(source / file) != expected:
            raise ValueError(f"Acquisition receipt mismatch: {name}/{file}")
    if receipt["source_manifest_sha256"] != sha(SOURCE / "source_manifest.json"):
        raise ValueError("Frozen source manifest mismatch")
    return source, receipt, load(source / "parent_result.json")


def build_run(name: str, *, render_video=True) -> dict:
    source, receipt, parent = verify_run(name)
    new = load(source / "new_result.json") if (source / "new_result.json").exists() else None
    lifecycle = load(source / "lifecycle_events.json") if (source / "lifecycle_events.json").exists() else []
    continuity = load(source / "continuity.json")
    output = OUTPUT / "runs" / name
    output.mkdir(parents=True, exist_ok=not render_video)
    spec = load(SOURCE / "protocol.json")
    frozen = load(SOURCE / "source_manifest.json")["files"]
    robot_path = "configs/robot/g1_locomotion_12dof.yaml"
    if sha(ROOT / robot_path) != frozen[robot_path]:
        raise ValueError("Frozen policy configuration mismatch")
    policy = load_yaml(ROOT / robot_path)["controller"]
    relative = source.relative_to(ROOT).as_posix()
    nodes, decisions, events = [], [], []

    def decision(time, mission_id, stage, value, evaluation, action, locator, node_index=None):
        item = {"time_s": float(time), "mission_id": mission_id, "lifecycle_stage": stage,
                "node_index": node_index, "decision": value, "evaluation": evaluation,
                "action": action, "continuation": stage, "source_locator": locator}
        decisions.append(item)
        events.append({"id": f"decision-{len(events)}", "time_s": float(time), "node_index": node_index,
                       "label": f"{stage}: {value}", "metric": "runtime_decision", "value": value,
                       "failure": value in {"STOP_DEPENDENTS", "HALT_FAILED", "ESCALATE", "new_mission_rejected"},
                       "source_locator": locator})

    def mission_nodes(result, role, start, filename):
        cursor = start
        for i, original in enumerate(result["nodes"]):
            metrics = original["metrics"]
            end = cursor + float(metrics["simulation_time_s"])
            feedback = original.get("feedback_decision") or {}
            evaluation = feedback.get("evaluation") or {}
            index = len(nodes)
            locator = relative + f"/{filename}#/nodes/{i}"
            nodes.append({"index": index, "node_id": original["node_id"], "mission_id": result["mission_id"],
                          "mission_role": role, "skill": original["skill"], "start_s": cursor, "end_s": end,
                          "task_status": "PASS" if metrics["task_success"] else "FAIL",
                          "strict_status": "PASS" if evaluation.get("satisfied") is True else "FAIL" if evaluation.get("satisfied") is False else "Unavailable",
                          "physical_status": "PASS" if metrics["physical_success"] else "FAIL",
                          "strict_lateral_limit_m": evaluation.get("limits", {}).get("lateral_drift_max_m"),
                          "strict_violations": evaluation.get("violations", []), "source_locator": locator})
            decision(end, result["mission_id"], role, feedback.get("action", "CONTINUE"),
                     evaluation or "Task completed", "Block descendants" if feedback.get("action") == "STOP_DEPENDENTS" else "Dispatch next READY node",
                     locator, index)
            cursor = end
        return cursor

    mission_nodes(parent, "original_mission", 0, "parent_result.json")
    halt = parent.get("physical_halt")
    if halt:
        start = halt["pre_halt_state"]["simulation_time"]
        end = halt["final_state"]["simulation_time"]
        locator = relative + "/parent_result.json#/physical_halt"
        index = len(nodes)
        nodes.append({"index": index, "mission_id": parent["mission_id"], "mission_role": "physical_halt",
                      "skill": "independent_physical_halt", "start_s": start, "end_s": end,
                      "task_status": "Unavailable", "strict_status": "Unavailable",
                      "physical_status": "PASS" if halt["status"] == "HALT_SUCCEEDED" else "FAIL", "source_locator": locator})
        decision(start, parent["mission_id"], "physical_halt", "PHYSICAL_HALT_REQUESTED", "Task already blocked",
                 "Experiment-configured independent StopSkill; no old node dispatch", locator + "/request", index)
        decision(end, parent["mission_id"], "physical_halt", halt["status"], halt["checks"],
                 "Finish halt attempt; this is not a hardware safety claim", locator + "/status", index)
    for i, entry in enumerate(lifecycle):
        value = entry["event"]
        if value == "post_halt_assessment":
            evaluation = {"eligible": entry["eligible"], "reasons": entry["reasons"]}
            action = "Assess exact observed state and grounded new mission"
        elif value == "new_mission_rejected":
            evaluation = {"reason": entry["reason"], "reasons": entry["assessment"]["reasons"]}
            action = "ESCALATE; zero new physics or skill dispatch. No ongoing physical safety guarantee"
        elif value in {"test_only_authorization_issued", "new_mission_authorized"}:
            evaluation = {"scope": "TEST_ONLY", "binding": entry.get("binding")}
            action = "Frozen in-process experiment allowlist; not Human Principal Authority"
        else:
            evaluation = {"status": entry.get("status"), "reason": entry.get("reason")}
            action = "Record separate new mission outcome; original failure retained"
        decision(entry["simulation_time_s"], entry.get("new_mission_id", parent["mission_id"]), "lifecycle",
                 value, evaluation, action, relative + f"/lifecycle_events.json#/{i}")
    if new:
        mission_nodes(new, "new_mission", continuity["before_new_mission"]["time_s"], "new_result.json")
    # Stable time sort preserves source order for zero-physics decisions.
    decisions.sort(key=lambda item: item["time_s"])
    events.sort(key=lambda item: item["time_s"])
    with np.load(source / "poses.npz", allow_pickle=False) as poses:
        times, qpos, qvel = poses["time_s"], poses["qpos"], poses["qvel"]
        if not len(times) or not np.all(np.diff(times) > 0):
            raise ValueError("Invalid native capture times")
        samples = []
        for frame, time in enumerate(times):
            node = next((n for n in nodes if n["start_s"] <= time <= n["end_s"]), nodes[-1])
            begin = int(np.searchsorted(times, node["start_s"], side="left"))
            heading = yaw(qpos[begin]); offset = qpos[frame, :2] - qpos[begin, :2]
            samples.append({"time_s": float(time), "frame_index": frame, "node_index": node["index"],
                            "skill": node["skill"], "mission_id": node["mission_id"], "mission_role": node["mission_role"],
                            "x": float(qpos[frame, 0]), "y": float(qpos[frame, 1]),
                            "speed_mps": float(np.linalg.norm(qvel[frame, :2])), "actual_heading_deg": angle_deg(yaw(qpos[frame])),
                            "local_lateral_m": float(-math.sin(heading)*offset[0] + math.cos(heading)*offset[1]),
                            "source_locator": relative + f"/poses.npz#frame={frame}"})
        frame_map = times.tolist()
    if render_video:
        write_new(output / "render_manifest.json", render(source, output / "rollout.mp4"))
    provenance = {"source_result_path": relative + "/parent_result.json", "source_result_format": "json",
                  "source_protocol_path": (SOURCE / "protocol.json").relative_to(ROOT).as_posix(),
                  "source_runtime_ledger_path": relative + f"/ledger/{parent['mission_id']}/events.jsonl",
                  "source_trace_path": relative + "/state_trace.jsonl.gz",
                  "source_poses_path": relative + "/poses.npz", "source_continuity_path": relative + "/continuity.json",
                  "source_authorization_path": relative + "/requests.json",
                  "protocol_sha": sha(SOURCE / "protocol.json"), "source_commit": receipt["source_commit"],
                  "seed": spec["seed"], "policy_sha": frozen[policy["policy_path"]],
                  "policy_identity": f"{policy['kind']} · {policy['policy_path']} · {policy['source_repository']}@{policy['source_commit']}",
                  "producer_execution_base_commit": receipt["source_commit"],
                  "producer_code_sha": sha(Path(__file__))}
    if lifecycle:
        provenance.update(source_assessment_path=relative + "/assessment.json", source_lifecycle_path=relative + "/lifecycle_events.json")
    if new:
        provenance.update(source_new_result_path=relative + "/new_result.json",
                          source_new_ledger_path=relative + f"/ledger/{new['mission_id']}/events.jsonl")
    terminal = next((e["status"] for e in reversed(lifecycle) if e["event"] in {"new_mission_completed", "new_mission_failed", "new_mission_rejected"}), "NOT_REQUESTED")
    # A post-completion replay rejection is a separate refusal, not the first new mission's outcome.
    if new:
        terminal = "NEW_MISSION_COMPLETED" if new["mission_success"] else "ESCALATE"
    run = {"schema_version": 1, "runtime_kind": "closed_loop_mission", "id": name,
           "label": {"adaptive_authorized": "TEST_ONLY authorized new mission", "halt_only_no_authorization": "Halt-only · authorization denied", "normal_control": "Normal mission control"}[name],
           "experiment_id": "adaptive_mission_lifecycle_001", "case_id": parent["mission_id"], "treatment": name, "seed": spec["seed"],
           "visual_source": "state_playback", "media_caption": "Native same-session MuJoCo capture · TEST_ONLY · render only",
           "duration_s": frame_map[-1], "frame_fps": 20, "frame_map": frame_map, "video_url": f"/media/{name}/rollout.mp4",
           "nodes": nodes, "samples": samples, "runtime_decisions": decisions, "events": events, "ideal_route": [],
           "summary": {"task_status": "PASS" if parent["mission_success"] else "FAIL", "original_mission_status": parent["state"],
                       "strict_status": "FAIL" if any(n["strict_status"] == "FAIL" for n in nodes if n["mission_role"] == "original_mission") else "PASS",
                       "physical_status": "PASS" if parent["physical_success"] else "FAIL", "halt_status": halt["status"] if halt else "NOT_REQUESTED",
                       "new_mission_status": new["state"] if new else "NOT_EXECUTED", "lifecycle_status": terminal},
           "provenance": provenance, "evidence_url": f"/api/evidence/{name}"}
    if render_video:
        write_new(output / "run.json", run)
    else:
        (output / "run.json").write_text(json.dumps(run, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return run


def build():
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    OUTPUT.mkdir(parents=True)
    runs = [build_run(name) for name in RUNS]
    write_new(OUTPUT / "catalog.json", {"schema_version": 1, "title": "M2.2 adaptive mission lifecycle",
              "runs": [{"id": r["id"]} for r in runs], "experiments": [{"id": "adaptive_lifecycle", "title": "M2.2 · Failure → Halt → Assess → New Mission / Escalate",
              "description": "Same-session feedback and explicit TEST_ONLY configuration; no route recovery or Human Principal Authority claim",
              "case_id": runs[0]["case_id"], "arms": [{"id": r["id"], "label": r["label"], "run_url": f"/api/runs/{r['id']}"} for r in runs]}]})
    derived = {p.relative_to(OUTPUT).as_posix(): record(p) for p in OUTPUT.rglob("*") if p.is_file()}
    sources = {SOURCE / "protocol.json", SOURCE / "source_manifest.json", Path(__file__)}
    for name in RUNS:
        source, _, _ = verify_run(name)
        sources.update(p for p in source.rglob("*") if p.is_file())
    write_new(OUTPUT / "manifest.json", {"schema_version": 1, "visual_source": "state_playback", "scientific_evidence_modified": False,
              "files": derived, "sources": {p.relative_to(ROOT).as_posix(): record(p) for p in sorted(sources)}})


def rebind_saved_render():
    """Update this task's derived JSON only, retaining every saved media byte."""
    manifest = load(OUTPUT / "manifest.json")
    for relative, expected in manifest["files"].items():
        if record(OUTPUT / relative) != expected:
            raise ValueError(f"Existing derived artifact changed before rebind: {relative}")
    for relative, expected in manifest["sources"].items():
        if relative != Path(__file__).relative_to(ROOT).as_posix() and record(ROOT / relative) != expected:
            raise ValueError(f"Acquisition source changed before rebind: {relative}")
    for name in RUNS:
        build_run(name, render_video=False)
    manifest["files"] = {relative: record(OUTPUT / relative) for relative in manifest["files"]}
    manifest["sources"][Path(__file__).relative_to(ROOT).as_posix()] = record(Path(__file__))
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["--rebind-saved-render"]:
        rebind_saved_render()
    elif not sys.argv[1:]:
        build()
    else:
        raise SystemExit("usage: build_m22_replay.py [--rebind-saved-render]")
