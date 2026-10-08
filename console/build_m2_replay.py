"""Publish captured M2 mission runs as read-only, source-bound Console replay.

The renderer owns a fresh MuJoCo model and only calls mj_forward. It never
executes the mission, controller, policy, or a physics step.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SOURCE = ROOT / "experiments/m2/closed_loop_mission_001"
OUTPUT = ROOT / "experiments/research_console/m2_closed_loop_001"
XML = ROOT / "third_party/unitree_rl_gym/resources/robots/g1_description/scene.xml"
ENCODER = ROOT / "console/.tools/ffmpeg.exe"
RUNS = ("success_mission--static_dispatch", "success_mission--strict_feedback",
        "failure_mission--static_dispatch", "failure_mission--strict_feedback")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict:
    return {"sha256": sha(path), "bytes": path.stat().st_size}


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def yaw(qpos: np.ndarray) -> float:
    w, x, y, z = qpos[3:7]
    return math.atan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z))


def angle_deg(value: float) -> float:
    return (math.degrees(value) + 180) % 360 - 180


def verify_source() -> None:
    frozen = load(SOURCE / "source_manifest.json")
    for relative, expected in frozen["files"].items():
        if sha(ROOT / relative) != expected:
            raise ValueError(f"M2 frozen source mismatch: {relative}")
    for name in RUNS:
        path = SOURCE / "artifacts" / name
        receipt = load(path / "receipt.json")
        for key, file in (("result_sha256", "result.json"), ("pose_sha256", "poses.npz")):
            if receipt[key] != sha(path / file):
                raise ValueError(f"M2 acquisition receipt mismatch: {name}/{file}")


def render(source: Path, target: Path, *, width: int = 960, height: int = 540) -> dict:
    if target.exists() or not ENCODER.is_file():
        raise FileExistsError(target) if target.exists() else FileNotFoundError(ENCODER)
    with np.load(source / "poses.npz", allow_pickle=False) as poses:
        times = poses["time_s"]
        model = mujoco.MjModel.from_xml_path(str(XML))
        count = len(times)
        if count < 2 or not np.all(np.diff(times) > 0):
            raise ValueError("Invalid captured state timing")
        for key, dimension in (("qpos", model.nq), ("qvel", model.nv), ("ctrl", model.nu)):
            if poses[key].shape != (count, dimension) or not np.isfinite(poses[key]).all():
                raise ValueError(f"Invalid captured {key}")
        model.vis.global_.offwidth, model.vis.global_.offheight = width, height
        data, camera = mujoco.MjData(model), mujoco.MjvCamera()
        camera.distance, camera.azimuth, camera.elevation = 2.7, 135, -18
        command = [str(ENCODER), "-hide_banner", "-loglevel", "error", "-n", "-f", "rawvideo",
                   "-vcodec", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                   "-r", "20", "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "fast",
                   "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)]
        unchanged = True
        with (target.parent / "encoder.log").open("x", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                with mujoco.Renderer(model, height=height, width=width) as renderer:
                    for i, time_s in enumerate(times):
                        data.qpos[:], data.qvel[:], data.ctrl[:] = poses["qpos"][i], poses["qvel"][i], poses["ctrl"][i]
                        data.time = float(time_s)
                        mujoco.mj_forward(model, data)
                        camera.lookat[:] = [data.qpos[0], data.qpos[1], .78]
                        renderer.update_scene(data, camera=camera)
                        process.stdin.write(renderer.render().tobytes())
                        unchanged &= (np.array_equal(data.qpos, poses["qpos"][i])
                                      and np.array_equal(data.qvel, poses["qvel"][i])
                                      and np.array_equal(data.ctrl, poses["ctrl"][i]))
                process.stdin.close()
                if process.wait(timeout=60) != 0:
                    raise RuntimeError("Encoder failed; stderr retained")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
        if not unchanged:
            raise RuntimeError("Render changed captured state")
        return {"passed": True, "frames": count, "fps": 20, "source_pose_sha256": sha(source / "poses.npz"),
                "video_sha256": sha(target), "model_sha256": sha(XML), "encoder_sha256": sha(ENCODER),
                "renderer_code_sha256": sha(Path(__file__)), "mj_step_calls": 0,
                "visual_source": "state_playback", "frame_sim_times_s": times.tolist()}


def build_run(name: str) -> dict:
    source = SOURCE / "artifacts" / name
    output = OUTPUT / "runs" / name
    output.mkdir(parents=True, exist_ok=False)
    result = load(source / "result.json")
    spec = load(SOURCE / "protocol.json")
    case, mode = name.split("--", 1)
    mission = spec[case]
    ledger = source / "ledger" / result["mission_id"] / "events.jsonl"
    source_paths = {"result": source / "result.json", "poses": source / "poses.npz",
                    "runtime_ledger": ledger, "protocol": SOURCE / "protocol.json"}
    with np.load(source / "poses.npz", allow_pickle=False) as poses:
        times, qpos = poses["time_s"], poses["qpos"]
        durations = [float(node["metrics"]["simulation_time_s"]) for node in result["nodes"]]
        ends = np.cumsum(durations).tolist()
        starts = [0.0] + ends[:-1]
        if abs(ends[-1] - float(times[-1])) > .003:
            raise ValueError(f"Pose/result timing mismatch: {name}")
        node_rows, decisions, events = [], [], []
        initial_heading = yaw(qpos[0])
        heading, origin = initial_heading, np.array(qpos[0, :2], copy=True)
        route = [origin.tolist()]
        node_headings = []
        for i, node in enumerate(result["nodes"]):
            skill, metrics = node["skill"], node["metrics"]
            step = mission["steps"][i]
            node_headings.append(heading)
            strict = None
            if skill == "walk_forward":
                from g1swarm.boundary.envelope import STRICT_WALK_ENVELOPE
                strict = STRICT_WALK_ENVELOPE.evaluate(metrics, float(step["parameters"]["distance_m"]))
                origin = origin + float(step["parameters"]["distance_m"]) * np.array([math.cos(heading), math.sin(heading)])
                route.append(origin.tolist())
            if skill == "turn":
                heading += math.radians(float(step["parameters"]["angle_deg"]))
            raw_decision = node.get("feedback_decision")
            decision = raw_decision["action"] if raw_decision else ("STATIC_CONTINUE" if metrics["task_success"] else "STATIC_STOP")
            continuation = "CONTINUE" if decision in ("CONTINUE", "STATIC_CONTINUE") else "STOP_DEPENDENTS"
            locator = source_paths["result"].relative_to(ROOT).as_posix() + f"#/nodes/{i}"
            decisions.append({"time_s": ends[i], "node_index": i,
                              "observation": raw_decision["observed_metrics"] if raw_decision else {k: metrics.get(k) for k in ("distance_error_m", "lateral_drift_m", "heading_error_deg")},
                              "evaluation": raw_decision["evaluation"] if raw_decision else "No strict feedback gate in static dispatch",
                              "decision": decision, "action": "Dispatch next READY node" if continuation == "CONTINUE" else "Block descendants",
                              "continuation": continuation, "source_locator": locator})
            events.append({"id": f"node-{i}-decision", "time_s": ends[i], "node_index": i,
                           "label": f"{step['id']} {skill}: {decision}", "metric": "runtime_decision",
                           "value": decision, "failure": continuation != "CONTINUE", "source_locator": locator})
            node_rows.append({"index": i, "skill": skill, "start_s": starts[i], "end_s": ends[i],
                              "task_status": "PASS" if metrics["task_success"] else "FAIL",
                              "strict_status": "PASS" if strict and strict.satisfied else "FAIL" if strict else "Unavailable",
                              "physical_status": "PASS" if metrics["physical_success"] else "FAIL",
                              "nominal_lateral_limit_m": None, "strict_lateral_limit_m": strict.limits.lateral_max_m if strict else None,
                              "strict_violations": strict.violations if strict else [], "source_locator": locator})
        samples = []
        for frame, time_s in enumerate(times):
            index = min(int(np.searchsorted(ends, time_s, side="left")), len(ends) - 1)
            node_origin_index = int(np.searchsorted(times, starts[index], side="left"))
            local_origin = qpos[node_origin_index, :2]
            local_heading = yaw(qpos[node_origin_index])
            offset = qpos[frame, :2] - local_origin
            actual = yaw(qpos[frame])
            commanded = node_headings[index]
            samples.append({"time_s": float(time_s), "frame_index": frame, "node_index": index,
                            "skill": result["nodes"][index]["skill"], "x": float(qpos[frame, 0]), "y": float(qpos[frame, 1]),
                            "actual_heading_deg": angle_deg(actual), "commanded_heading_deg": angle_deg(commanded),
                            "reference_heading_deg": None, "local_lateral_m": float(-math.sin(local_heading)*offset[0]+math.cos(local_heading)*offset[1]),
                            "global_lateral_m": None, "heading_error_deg": angle_deg(actual-commanded),
                            "source_locator": source_paths["poses"].relative_to(ROOT).as_posix()+f"#frame={frame}"})
    video = output / "rollout.mp4"
    render_receipt = render(source, video)
    write_new(output / "render_manifest.json", render_receipt)
    provenance = {f"source_{key}_path": path.relative_to(ROOT).as_posix() for key, path in source_paths.items()}
    provenance.update({"source_result_format": "json", "source_result_locator": provenance["source_result_path"],
                       "source_runtime_ledger_locator": provenance["source_runtime_ledger_path"],
                       "source_commit": "d16e9d49c4938ffde10a652daf24a572b6414b7a", "protocol_sha": sha(SOURCE / "protocol.json"),
                       "pose_sha": sha(source / "poses.npz"), "visual_producer_sha": sha(Path(__file__))})
    summary = {"task_status": "PASS" if result["mission_success"] else "FAIL",
               "strict_status": "PASS" if all(row["strict_status"] != "FAIL" for row in node_rows) else "FAIL",
               "physical_status": "PASS" if result["physical_success"] else "FAIL"}
    run = {"schema_version": 1, "runtime_kind": "closed_loop_mission", "id": name,
           "label": f"{case.replace('_',' ')} · {mode.replace('_',' ')}", "experiment_id": "m2_closed_loop_001",
           "case_id": result["mission_id"], "treatment": mode, "duration_s": float(times[-1]),
           "risk_context": "HIGH-risk experimental open-loop override · predeclared Oracle Mission IR" if case == "failure_mission" else None,
           "visual_source": "state_playback", "media_caption": "Original captured MuJoCo states · render only",
           "video_url": f"/media/{name}/rollout.mp4", "frame_fps": 20, "frame_map": times.tolist(),
           "ideal_route": route, "samples": samples, "nodes": node_rows,
           "runtime_decisions": decisions, "events": events, "summary": summary,
           "provenance": provenance, "evidence_url": f"/api/evidence/{name}"}
    write_new(output / "run.json", run)
    return run


def build() -> None:
    verify_source()
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    OUTPUT.mkdir(parents=True)
    runs = [build_run(name) for name in RUNS]
    experiments = []
    for case in ("success_mission", "failure_mission"):
        arms = [{"id": run["id"], "label": run["label"], "run_url": f"/api/runs/{run['id']}"}
                for run in runs if run["id"].startswith(case)]
        experiments.append({"id": case, "title": f"M2 closed loop · {case.replace('_',' ')}",
                            "description": ("HIGH-risk experimental open-loop override · " if case == "failure_mission" else "")
                                           + "Same frozen Oracle Mission IR · static dispatch vs strict feedback gate",
                            "case_id": next(run["case_id"] for run in runs if run["id"].startswith(case)), "arms": arms})
    write_new(OUTPUT / "catalog.json", {"schema_version": 1, "title": "M2 closed-loop mission execution",
                                        "runs": [{"id": run["id"]} for run in runs], "experiments": experiments})
    derived = {p.relative_to(OUTPUT).as_posix(): record(p) for p in OUTPUT.rglob("*") if p.is_file()}
    source_files = {SOURCE / "protocol.json", SOURCE / "source_manifest.json", XML}
    for name in RUNS:
        path = SOURCE / "artifacts" / name
        source_files.update((path / "result.json", path / "poses.npz", path / "receipt.json",
                             path / "ledger" / load(path / "result.json")["mission_id"] / "events.jsonl"))
    sources = {p.relative_to(ROOT).as_posix(): record(p) for p in sorted(source_files)}
    write_new(OUTPUT / "manifest.json", {"schema_version": 1, "visual_source": "state_playback",
                                              "scientific_evidence_modified": False,
                                              "files": derived, "sources": sources,
                                              "source_freeze_commit": "d16e9d49c4938ffde10a652daf24a572b6414b7a"})
    print(json.dumps({"runs": [run["id"] for run in runs], "derived_files": len(derived),
                      "source_files": len(sources)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    if parser.parse_args().build:
        build()
    else:
        raise SystemExit("Use --build")
