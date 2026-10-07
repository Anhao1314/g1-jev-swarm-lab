"""Derive display diagnostics; frozen source records remain scoring authority."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "experiments/research_console/vertical_slice_001"


def digest(path):
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def build_run(directory):
    capture = json.loads((directory / "capture_manifest.json").read_text())
    render = json.loads((directory / "render_manifest.json").read_text())
    if not render["passed"] or not all(capture["parity"][k] for k in
                                     ("capture_off_on_equal", "historical_record_exact", "historical_command_trace_exact")):
        raise ValueError("Failed replay cannot be presented as a matched source visualization")
    poses = np.load(directory / "poses.npz", allow_pickle=False)
    record = capture["source_record"]
    provenance = dict(capture["provenance"])
    run_id = directory.name
    provenance.update(video_sha=render["video_sha256"], render_manifest_sha=digest(directory / "render_manifest.json")["sha256"],
                      capture_manifest_path=f"runs/{run_id}/capture_manifest.json",
                      metric_origin="synchronized display diagnostics derived from saved poses; node-end scores from original source result",
                      console_index_code_sha=digest(Path(__file__))["sha256"])
    nodes = []
    for index, node in enumerate(record["nodes"]):
        envelope = node["envelope"]
        nodes.append({"index": index, "skill": node["skill"],
                      "start_s": node["start_state"]["simulation_time"], "end_s": node["end_state"]["simulation_time"],
                      "task_status": "PASS" if node["task_success"] else "FAIL",
                      "physical_status": "PASS" if node["physical_success"] else "FAIL",
                      "strict_status": "PASS" if node["strict_success"] else "FAIL",
                      "nominal_lateral_limit_m": envelope["nominal_envelope"]["limits"]["lateral_drift_max_m"] if envelope else None,
                      "strict_lateral_limit_m": envelope["strict_envelope"]["limits"]["lateral_drift_max_m"] if envelope else None,
                      "source_metric": node["lateral_drift_m"], "violations": node["violations"],
                      "strict_violations": envelope["strict_envelope"]["violations"] if envelope else [],
                      "source_locator": provenance["source_result_locator"] + f"&pointer=/nodes/{index}"})
    samples = []
    for i, time_s in enumerate(poses["time_s"]):
        node_index = int(poses["node_index"][i])
        node = record["nodes"][node_index]
        x, y = poses["qpos"][i, :2]
        w, qx, qy, qz = poses["qpos"][i, 3:7]
        actual = math.atan2(2 * (w * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))
        local = float(poses["local_heading"][i])
        planned = float(poses["planned_heading"][i])
        commanded = planned + (math.radians(node["parameters"]["target_angle_deg"]) if node["skill"] == "turn" else 0)
        local_offset = poses["qpos"][i, :2] - poses["local_origin"][i]
        global_offset = poses["qpos"][i, :2] - poses["planned_origin"][i]
        reference = float(poses["reference_heading"][i])
        samples.append({"time_s": float(time_s), "frame_index": i, "node_index": node_index, "skill": node["skill"],
                        "x": float(x), "y": float(y), "actual_heading_deg": math.degrees(actual),
                        "commanded_heading_deg": math.degrees(wrap(commanded)),
                        "reference_heading_deg": math.degrees(reference) if math.isfinite(reference) else None,
                        "local_lateral_m": float(-math.sin(local) * local_offset[0] + math.cos(local) * local_offset[1]),
                        "global_lateral_m": float(-math.sin(planned) * global_offset[0] + math.cos(planned) * global_offset[1]),
                        "heading_error_deg": math.degrees(wrap(actual - commanded)),
                        "source_locator": f"runs/{run_id}/poses.npz#frame={i}"})
    initial = record["nodes"][0]["start_state"]
    route = [initial["base_position"][:2]]
    commanded = math.radians(capture["case"].get("initial_yaw_deg", 0))
    origin = np.array(route[0])
    for node in capture["case"]["nodes"]:
        if node["skill"] == "walk_forward":
            origin = origin + node["parameters"]["target_distance_m"] * np.array([math.cos(commanded), math.sin(commanded)])
            route.append(origin.tolist())
        elif node["skill"] == "turn":
            commanded = wrap(commanded + math.radians(node["parameters"]["target_angle_deg"]))
    events = []
    def event(index, label, metric, value, failure=False):
        events.append({"id": f"node-{index}-{metric}", "time_s": nodes[index]["end_s"], "node_index": index,
                       "label": label, "metric": metric, "value": value, "failure": failure,
                       "source_locator": provenance["source_result_locator"] + f"&pointer=/nodes/{index}/{metric}"})
    event(0, "Stand yaw inherited by first Walk", "ideal_path_heading_error_deg", record["nodes"][0]["ideal_path_heading_error_deg"])
    for index, node in enumerate(record["nodes"]):
        if node["skill"] == "walk_forward":
            event(index, f"Walk {node['parameters']['target_distance_m']:g}m · local corridor", "lateral_drift_m",
                  node["lateral_drift_m"], not node["strict_success"])
        if node["skill"] == "turn":
            event(index, "Turn · ideal heading", "ideal_path_heading_error_deg", node["ideal_path_heading_error_deg"])
    event(len(nodes) - 1, "Sequence end · global drift", "ideal_path_lateral_error_m", record["nodes"][-1]["ideal_path_lateral_error_m"])
    final = record["nodes"][-1]
    run = {"schema_version": 1, "id": run_id, "label": f"α={capture['alpha']:g} · residual off",
           "experiment_id": provenance["experiment_id"], "treatment": provenance["treatment"],
           "treatment_label": provenance["treatment"], "case_id": provenance["case_id"], "alpha": capture["alpha"],
           "seed": None, "visual_source": "derived_visualization_replay", "duration_s": record["total_sim_time_s"],
           "video_url": f"/media/{run_id}/rollout.mp4", "frame_fps": 20, "frame_map": poses["time_s"].tolist(),
           "ideal_route": route, "samples": samples, "nodes": nodes, "events": events,
           "summary": {"global_lateral_m": final["ideal_path_lateral_error_m"],
                       "heading_error_deg": final["ideal_path_heading_error_deg"],
                       "endpoint_error_m": record["ideal_endpoint_error_m"],
                       "task_status": "PASS" if record["task_success"] else "FAIL",
                       "physical_status": "PASS" if record["physical_success"] else "FAIL",
                       "strict_status": "PASS" if all(n["strict_success"] for n in record["nodes"]) else "FAIL"},
           "provenance": provenance, "evidence_url": f"/api/evidence/{run_id}"}
    write(directory / "run.json", run)
    return run


def build(data):
    runs = [build_run(path) for path in sorted((data / "runs").iterdir()) if path.is_dir()]
    arms = [{"id": r["id"], "label": r["label"], "alpha": r["alpha"], "run_url": f"/api/runs/{r['id']}"} for r in runs]
    write(data / "catalog.json", {"schema_version": 1, "title": "Research Console", "runs": arms,
                                 "experiments": [{"id": runs[0]["experiment_id"], "title": "Walking reference · 16m sequence",
                                                  "description": "Actual origin · heading alignment α=0 / α=0.5 · same frozen mission",
                                                  "case_id": runs[0]["case_id"], "arms": arms}]})
    files = {path.relative_to(data).as_posix(): digest(path) for path in sorted(data.rglob("*"))
             if path.is_file() and path.name != "manifest.json"}
    paths = {r["provenance"][f"source_{kind}_path"] for r in runs for kind in ("protocol", "result", "trace", "manifest")}
    paths.add("third_party/unitree_rl_gym/deploy/pre_train/g1/motion.pt")
    paths.add("configs/robot/g1_locomotion_12dof.yaml")
    for r in runs:
        capture = json.loads((data / "runs" / r["id"] / "capture_manifest.json").read_text())
        paths.update(capture["source_record"]["provenance"]["source_hashes"])
    write(data / "manifest.json", {"schema_version": 1, "scientific_evidence_modified": False,
          "visual_source": "derived_visualization_replay", "files": files,
          "sources": {path: digest(ROOT / path) for path in sorted(paths)},
          "producer_base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()})
    print(json.dumps({"runs": [r["id"] for r in runs], "derived_files": len(files), "source_files": len(paths)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT)
    build(parser.parse_args().data)
