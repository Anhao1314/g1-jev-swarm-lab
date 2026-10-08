"""Build observer-only Console data from retained acquisition poses and scores.

No simulator, controller, evaluator or scientific runner is imported. Selection
is the three declared primary profiles, never a ranking by observed outcomes.
"""
from __future__ import annotations

import argparse
import bisect
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCIENCE = "experiments/phase3a/residual_authority_feasibility_001"
DEFAULT = ROOT / "experiments/research_console/residual_authority_replay_001"
OLD = "experiments/research_console/vertical_slice_001"
ARMS = (
    ("authority-off", "01--off--primary", "off", "Residual off"),
    ("authority-combined", "05--combined_inward--primary", "combined_inward", "Combined inward"),
    ("authority-corner", "06--corner_forward_inward--primary", "corner_forward_inward", "Forward / inward corner"),
)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    path = Path(path)
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def decoded_rows(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def yaw(quat):
    w, x, y, z = quat
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def lateral(position, origin, heading):
    return float(-math.sin(heading) * (position[0] - origin[0])
                 + math.cos(heading) * (position[1] - origin[1]))


def status(value):
    return "PASS" if value else "FAIL"


def source_paths(source_id):
    base = f"{SCIENCE}/evidence/runs/{source_id}"
    return {"result": f"{base}/result.json", "trace": f"{base}/trace.jsonl.gz",
            "poses": f"{base}/poses.npz", "decisions": f"{base}/decisions.jsonl.gz",
            "independent_audit": f"{base}/independent_audit.json",
            "audit": f"{base}/audit.json", "protocol": f"{SCIENCE}/protocol.json",
            "case": f"{SCIENCE}/case.json", "manifest": f"{SCIENCE}/evidence_manifest.json",
            "summary": f"{SCIENCE}/evidence/summary.json"}


def load_source(source_id, repo_root=ROOT):
    paths = source_paths(source_id)
    manifest = read(repo_root / paths["manifest"])
    for kind in ("result", "trace", "poses", "decisions", "independent_audit", "audit", "summary"):
        pin = manifest["files"][paths[kind]]
        actual = digest(repo_root / paths[kind])
        if actual != {"sha256": pin["sha256"], "bytes": pin["bytes"]}:
            raise ValueError(f"Retained source identity changed: {paths[kind]}")
        if pin["encoding"] == "gzip":
            raw = gzip.decompress((repo_root / paths[kind]).read_bytes())
            if hashlib.sha256(raw).hexdigest() != pin["raw_sha256"]:
                raise ValueError(f"Retained decoded identity changed: {paths[kind]}")
    result, audit = read(repo_root / paths["result"]), read(repo_root / paths["independent_audit"])
    if result["run_id"] != source_id or result["phase"] != "primary" or result["repetition"] != 0:
        raise ValueError("Expected the declared primary acquisition, never a selected repeat")
    if not audit["passed"]:
        raise ValueError("Source independent audit did not pass")
    if digest(repo_root / paths["protocol"])["sha256"] != result["provenance"]["protocol_sha256"]:
        raise ValueError("Source acquisition protocol mismatch")
    if digest(repo_root / paths["case"])["sha256"] != result["provenance"]["case_sha256"]:
        raise ValueError("Source acquisition case mismatch")
    source_manifest = repo_root / SCIENCE / "source_manifest.json"
    if digest(source_manifest)["sha256"] != result["provenance"]["source_manifest_sha256"]:
        raise ValueError("Source acquisition file manifest mismatch")
    for relative, expected in result["provenance"]["source_hashes"].items():
        if digest(repo_root / relative)["sha256"] != expected:
            raise ValueError(f"Source acquisition producer changed: {relative}")
    summary = read(repo_root / paths["summary"])
    row_index = next(i for i, row in enumerate(summary["runs"]) if row["run_id"] == source_id)
    row = summary["runs"][row_index]
    if not row["complete"] or row["first_walk_local_lateral_m"] != result["nodes"][1]["lateral_drift_m"]:
        raise ValueError("Summary/result identity mismatch")
    return {"paths": paths, "result": result, "audit": audit, "summary_row": row,
            "summary_row_index": row_index, "protocol": read(repo_root / paths["protocol"]),
            "case": read(repo_root / paths["case"]), "trace": decoded_rows(repo_root / paths["trace"])}


def window_trace(source):
    duration = source["protocol"]["authority"]["window_s"]
    candidates = [(i, row) for i, row in enumerate(source["trace"]) if row["node_index"] == 1]
    index, row = min(candidates, key=lambda item: abs(item[1]["elapsed_s"] - duration))
    saved = source["audit"]["first_walk_window_state"]
    reference = source["result"]["nodes"][1]["walking_reference"]
    actual = lateral(row["state_before_command"]["base_position"],
                     reference["measurement_origin"], reference["measurement_heading_rad"])
    if abs(row["time_s"] - saved["time_s"]) > source["audit"]["tolerance"]:
        raise ValueError("Audit window state does not identify the retained trace row")
    if abs(actual - saved["local_lateral_m"]) > source["audit"]["tolerance"]:
        raise ValueError("Audit window local metric does not match original trace arithmetic")
    return index, row


def build_run(run_id, source_id, profile, label, *, repo_root=ROOT, data=DEFAULT, finalize=False):
    source, baseline = load_source(source_id, repo_root), load_source(ARMS[0][1], repo_root)
    result, audit, summary = source["result"], source["audit"], source["summary_row"]
    paths, base_paths = source["paths"], baseline["paths"]
    if result["probe_id"] != profile:
        raise ValueError("Declared profile/source mismatch")
    walk = result["nodes"][1]
    walk_start, walk_end = walk["start_state"]["simulation_time"], walk["end_state"]["simulation_time"]
    duration = source["protocol"]["authority"]["window_s"]
    reference = walk["walking_reference"]
    local_origin, local_heading = reference["measurement_origin"], reference["measurement_heading_rad"]
    reference_origin, reference_heading = reference["control_origin"], reference["control_heading_rad"]
    first_walk_target = summary["world_metrics"]["nodes"][1]["commanded_terminal_xy_m"]
    trace_index, boundary_trace = window_trace(source)
    base_trace_index, _ = window_trace(baseline)
    source_locator = paths["result"] + "#json"
    nodes = []
    for index, node in enumerate(result["nodes"]):
        envelope = node["envelope"]
        nodes.append({"index": index, "skill": node["skill"],
                      "start_s": node["start_state"]["simulation_time"], "end_s": node["end_state"]["simulation_time"],
                      "task_status": status(node["task_success"]), "physical_status": status(node["physical_success"]),
                      "strict_status": status(node["strict_success"]), "source_metric": node["lateral_drift_m"],
                      "nominal_lateral_limit_m": envelope["nominal_envelope"]["limits"]["lateral_drift_max_m"] if envelope else None,
                      "strict_lateral_limit_m": envelope["strict_envelope"]["limits"]["lateral_drift_max_m"] if envelope else None,
                      "violations": node["violations"],
                      "strict_violations": envelope["strict_envelope"]["violations"] if envelope else [],
                      "source_locator": source_locator + f"&pointer=/nodes/{index}"})
    trace_times = [row["time_s"] for row in source["trace"]]
    if any(b < a for a, b in zip(trace_times, trace_times[1:])):
        raise ValueError("Retained command trace is not ordered")
    with np.load(repo_root / paths["poses"], allow_pickle=False) as poses:
        times = poses["time_s"].tolist()
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError("Acquisition frame map must be strictly increasing")
        samples = []
        for i, time_s in enumerate(times):
            node_index = int(poses["node_index"][i])
            node = result["nodes"][node_index]
            position = poses["qpos"][i, :2]
            actual_heading = yaw(poses["qpos"][i, 3:7])
            planned_heading = float(poses["planned_heading"][i])
            commanded_heading = planned_heading + (math.radians(node["parameters"]["target_angle_deg"]) if node["skill"] == "turn" else 0)
            command_index = max(0, bisect.bisect_right(trace_times, time_s + 1e-10) - 1)
            command = source["trace"][command_index]
            in_first_walk = walk_start - 1e-10 <= time_s <= walk_end + 1e-10
            # A closest video frame can already belong to Turn. Keep the fixed
            # Walk anchors for every pose, rather than silently resetting the
            # display coordinate frame at that visual boundary. These are
            # diagnostics, never replacements for the exact endpoint score.
            first_local = lateral(position, local_origin, local_heading)
            first_reference = lateral(position, reference_origin, reference_heading)
            pose_reference = float(poses["reference_heading"][i])
            terminal_xy = summary["world_metrics"]["nodes"][node_index]["commanded_terminal_xy_m"]
            samples.append({"time_s": float(time_s), "frame_index": i, "node_index": node_index, "skill": node["skill"],
                "x": float(position[0]), "y": float(position[1]), "actual_heading_deg": math.degrees(actual_heading),
                "commanded_heading_deg": math.degrees(wrap(commanded_heading)),
                "reference_heading_deg": math.degrees(pose_reference) if math.isfinite(pose_reference) else None,
                "local_lateral_m": lateral(position, poses["local_origin"][i], float(poses["local_heading"][i])),
                "global_lateral_m": lateral(position, poses["planned_origin"][i], planned_heading),
                "global_endpoint_error_m": float(math.hypot(position[0] - terminal_xy[0], position[1] - terminal_xy[1])),
                "heading_error_deg": math.degrees(wrap(actual_heading - commanded_heading)),
                "walk_elapsed_s": float(time_s - walk_start), "first_walk_elapsed_s": float(time_s - walk_start),
                "first_walk_local_lateral_m": first_local, "first_walk_reference_lateral_m": first_reference,
                "first_walk_global_endpoint_error_m": float(math.hypot(position[0] - first_walk_target[0], position[1] - first_walk_target[1])),
                "first_walk_state_sample": in_first_walk, "reference_lateral_m": first_reference if in_first_walk else None,
                "residual_action": command["action"], "applied_residual": command["residual"],
                "authority_active": command["active"], "first_walk_authority_active": bool(in_first_walk and command["active"]),
                "residual_nonzero": any(value != 0 for value in command["residual"]),
                "command_sample_time_s": command["time_s"],
                "source_trace_locator": paths["trace"] + f"#decoded-line={command_index + 1}",
                "source_locator": paths["poses"] + f"#frame={i}"})
    strict_limit = nodes[1]["strict_lateral_limit_m"]
    local_effect_window = audit["first_walk_window_state"]["local_lateral_m"] - baseline["audit"]["first_walk_window_state"]["local_lateral_m"]
    local_effect_end = summary["first_walk_local_lateral_m"] - baseline["summary_row"]["first_walk_local_lateral_m"]
    locators = {
        "window_state": paths["independent_audit"] + "#pointer=/first_walk_window_state",
        "window_trace": paths["trace"] + f"#decoded-line={trace_index + 1}",
        "baseline_window_state": base_paths["independent_audit"] + "#pointer=/first_walk_window_state",
        "baseline_window_trace": base_paths["trace"] + f"#decoded-line={base_trace_index + 1}",
        "walk_endpoint": paths["result"] + "#pointer=/nodes/1/lateral_drift_m",
        "baseline_walk_endpoint": base_paths["result"] + "#pointer=/nodes/1/lateral_drift_m",
        "strict_limit": paths["result"] + "#pointer=/nodes/1/envelope/strict_envelope/limits/lateral_drift_max_m",
        "summary": paths["summary"] + f"#pointer=/runs/{source['summary_row_index']}",
        "authority_window": paths["protocol"] + "#pointer=/authority/window_s",
        "walk_start": paths["result"] + "#pointer=/nodes/1/start_state/simulation_time",
        "walk_end": paths["result"] + "#pointer=/nodes/1/end_state/simulation_time",
        "local_reference": paths["result"] + "#pointer=/nodes/1/walking_reference",
    }
    authority = {"walk_start_s": walk_start, "window_end_s": walk_start + duration, "walk_end_s": walk_end,
        "window_duration_s": duration, "reference_origin_xy": reference_origin[:2], "reference_heading_rad": reference_heading,
        "measurement_origin_xy": local_origin[:2], "measurement_heading_rad": local_heading,
        "local_effect_at_window_end_m": local_effect_window, "local_effect_at_walk_end_m": local_effect_end,
        "strict_gap_m": abs(summary["first_walk_local_lateral_m"]) - strict_limit,
        "strict_lateral_limit_m": strict_limit, "local_lateral_at_walk_end_m": summary["first_walk_local_lateral_m"],
        "local_strict_limit_m": strict_limit, "first_walk_ideal_endpoint_reference_xy": first_walk_target,
        "reference_lateral_at_walk_end_m": summary["first_walk_reference_lateral_m"],
        "window_trace_elapsed_s": boundary_trace["elapsed_s"],
        "window_sampling_offset_s": audit["first_walk_window_state"]["sampling_offset_s"],
        "evidence_metrics": copy.deepcopy(summary), "source_locators": locators,
        "local_effect_at_window_end_locator": [locators["window_state"], locators["baseline_window_state"]],
        "local_effect_at_walk_end_locator": [locators["walk_endpoint"], locators["baseline_walk_endpoint"]],
        "strict_gap_locator": [locators["walk_endpoint"], locators["strict_limit"]],
        "terminal_score_origin": "unchanged original node endpoint; never nearest visual pose", "joint_qualifier": summary["joint_qualifier"]}
    route = [result["nodes"][0]["start_state"]["base_position"][:2]]
    for node in summary["world_metrics"]["nodes"]:
        if node["skill"] == "walk_forward":
            route.append(node["commanded_terminal_xy_m"])
    events = [
        {"id": "first-walk-start", "time_s": walk_start, "node_index": 1, "label": "First Walk starts", "metric": "walk_start_s", "value": walk_start, "failure": False, "source_locator": locators["walk_start"]},
        {"id": "authority-window-end", "time_s": walk_start + duration, "node_index": 1, "label": "Original residual window ends", "metric": "local_effect_at_window_end_m", "value": local_effect_window, "failure": False, "source_locator": locators["window_trace"]},
        {"id": "first-walk-strict-end", "time_s": walk_end, "node_index": 1, "label": "First Walk · original strict endpoint", "metric": "lateral_drift_m", "value": walk["lateral_drift_m"], "failure": not walk["strict_success"], "source_locator": locators["walk_endpoint"]},
    ]
    acquisition = result["provenance"]
    provenance = {"experiment_id": acquisition["experiment_id"], "source_run_id": source_id,
        "treatment": result["treatment"], "case_id": result["case_id"], "seed": acquisition["seed"],
        "source_commit": acquisition["code_commit"], "protocol_sha": acquisition["protocol_sha256"],
        "policy_sha": acquisition["base_policy_sha256"], "checkpoint_sha": None,
        "source_result_format": "json", "source_result_locator": source_locator,
        "source_trace_locator": paths["trace"] + "#decoded-lines=1-end", "pose_sha": digest(repo_root / paths["poses"])["sha256"],
        "visual_source": "state_playback", "pose_origin": "original_acquisition_state_samples",
        "acquisition_provenance": copy.deepcopy(acquisition), "producer_code_sha": digest(Path(__file__))["sha256"],
        "producer_code_path": "console/build_authority_replay.py", "simulation_reexecutions": 0, "mj_step_calls": 0,
        "metric_origin": "saved acquisition poses and retained command traces; formal outcomes from original result/summary",
        "first_walk_metric_frame": "fixed original node1 measurement/control anchors, including the boundary pose whose stored node_index is0",
        "trace_alignment": "last original command at or before pose time, with 1e-10s floating point alignment tolerance",
        "global_endpoint_metric_frame": "distance to original commanded terminal XY of the sample node"}
    for kind, path in paths.items():
        provenance[f"source_{kind}_path"] = path
        provenance[f"source_{kind}_sha"] = digest(repo_root / path)["sha256"]
    output = data / "runs" / run_id
    output.mkdir(parents=True, exist_ok=True)
    render_path = output / "render_manifest.json"
    if finalize:
        render = read(render_path)
        if not render["passed"] or render["mj_step_calls"] != 0 or render["source_pose_sha256"] != provenance["pose_sha"]:
            raise ValueError("Render does not bind unchanged acquisition states with zero physics stepping")
        if render["frame_sim_times_s"] != times or render["frames"] != len(times):
            raise ValueError("Renderer frame map differs from acquisition poses")
        if digest(output / "rollout.mp4")["sha256"] != render["video_sha256"]:
            raise ValueError("Rendered video hash mismatch")
        provenance.update(video_sha=render["video_sha256"], render_manifest_sha=digest(render_path)["sha256"])
        fps = render["fps"]
    else:
        fps = 20
    final_world = summary["world_metrics"]
    run = {"schema_version": 1, "id": run_id, "label": label, "experiment_id": acquisition["experiment_id"],
        "treatment": result["treatment"], "treatment_label": result["treatment_label"], "profile": profile,
        "run_id": result["run_id"], "probe_id": result["probe_id"],
        "case_id": result["case_id"], "alpha": result["heading_alignment_alpha"], "seed": acquisition["seed"],
        "visual_source": "state_playback", "media_caption": "Original acquisition states · render-only playback · no new physics",
        "duration_s": result["total_sim_time_s"], "video_url": f"/media/{run_id}/rollout.mp4", "frame_fps": fps,
        "frame_map": times, "ideal_route": route, "samples": samples, "nodes": nodes, "events": events,
        "authority": authority, "summary": {"global_lateral_m": final_world["final_global_lateral_m"],
            "heading_error_deg": final_world["final_global_heading_deg"], "endpoint_error_m": final_world["final_endpoint_error_m"],
            "task_status": status(result["task_success"]), "physical_status": status(result["physical_success"]),
            "strict_status": status(summary["all_node_strict_success"]), "joint_qualifier": summary["joint_qualifier"]},
        "provenance": provenance, "evidence_url": f"/api/evidence/{run_id}"}
    write(output / "run.json", run)
    return run


def copy_previous(data, repo_root=ROOT):
    old = repo_root / OLD
    old_manifest = read(old / "manifest.json")
    for relative, expected in old_manifest["files"].items():
        if relative.startswith("runs/"):
            source, target = old / relative, data / relative
            if digest(source) != expected:
                raise ValueError(f"Previous Console source changed: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.read_bytes() != source.read_bytes():
                    raise ValueError(f"Refusing to overwrite a different previous Console asset: {relative}")
            else:
                shutil.copyfile(source, target)
    return read(old / "catalog.json"), old_manifest


def build(data=DEFAULT, *, repo_root=ROOT, finalize=False):
    data = Path(data)
    runs = [build_run(*arm, repo_root=repo_root, data=data, finalize=finalize) for arm in ARMS]
    previous, old_manifest = copy_previous(data, repo_root)
    arms = [{"id": run["id"], "label": run["label"], "alpha": run["alpha"], "run_url": f"/api/runs/{run['id']}"} for run in runs]
    catalog = {"schema_version": 1, "title": "Research Console", "default_experiment_id": runs[0]["experiment_id"],
        "runs": arms + previous["runs"], "experiments": [{"id": runs[0]["experiment_id"],
            "title": "Residual authority · fixed acquisition profiles", "description": "Same alpha0.5 reference; first Walk authority window, local strict endpoint and global tradeoff",
            "case_id": runs[0]["case_id"], "arms": arms}] + previous["experiments"]}
    write(data / "catalog.json", catalog)
    sources = dict(old_manifest["sources"])
    for run in runs:
        for name, path in run["provenance"].items():
            if name.startswith("source_") and name.endswith("_path"):
                sources[path] = digest(repo_root / path)
        for path in run["provenance"]["acquisition_provenance"]["source_hashes"]:
            sources[path] = digest(repo_root / path)
    for path in (f"{SCIENCE}/source_manifest.json", f"{OLD}/manifest.json", f"{OLD}/catalog.json", "console/build_authority_replay.py"):
        sources[path] = digest(repo_root / path)
    for path, expected in sources.items():
        if digest(repo_root / path) != expected:
            raise ValueError(f"Bound source identity changed: {path}")
    files = {p.relative_to(data).as_posix(): digest(p) for p in sorted(data.rglob("*")) if p.is_file() and p.name != "manifest.json"}
    write(data / "manifest.json", {"schema_version": 1, "scientific_evidence_modified": False,
        "visual_source": "state_playback", "simulation_reexecutions": 0, "mj_step_calls": 0,
        "finalized": finalize, "files": files, "sources": sources,
        "producer_base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()})
    return {"runs": [r["id"] for r in runs], "retained_previous_runs": [r["id"] for r in previous["runs"]],
            "finalized": finalize, "runtime_steps": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT)
    parser.add_argument("--finalize", action="store_true", help="Require and bind completed render-only media")
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.data, finalize=arguments.finalize)))
