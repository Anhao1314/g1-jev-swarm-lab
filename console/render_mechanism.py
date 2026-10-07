"""Render retained acquisition states in an isolated model; never advance physics."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import mujoco
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from console.render import XML

SOURCE = ROOT / "experiments/phase3a/residual_authority_feasibility_001"
OUTPUT = ROOT / "experiments/research_console/residual_authority_replay_001"
RUNS = {"authority-off": "01--off--primary",
        "authority-combined": "05--combined_inward--primary",
        "authority-corner": "06--corner_forward_inward--primary"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def source_binding(run_id):
    source_run = SOURCE / "evidence/runs" / RUNS[run_id]
    manifest_path = SOURCE / "evidence_manifest.json"
    inventory = json.loads(manifest_path.read_text("utf-8"))["files"]
    paths = [source_run / name for name in ("poses.npz", "result.json", "audit.json")]
    pins = {}
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        expected = inventory[relative]
        actual = digest(path)
        if actual != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            raise ValueError("Retained acquisition artifact does not match publication inventory")
        pins[relative] = actual
    return source_run, {"source_experiment_id": "residual_authority_feasibility_001",
        "source_run_id": RUNS[run_id], "source_pose_path": (source_run / "poses.npz").relative_to(ROOT).as_posix(),
        "source_pose_sha256": digest(source_run / "poses.npz"),
        "source_evidence_manifest_path": manifest_path.relative_to(ROOT).as_posix(),
        "source_evidence_manifest_sha256": digest(manifest_path), "source_artifact_hashes": pins}


def render(run_id, encoder, budget_s=120):
    source_run, binding = source_binding(run_id)
    directory = OUTPUT / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    target, receipt = directory / "rollout.mp4", directory / "render_manifest.json"
    if target.exists() or receipt.exists():
        if target.exists() and receipt.exists():
            old = json.loads(receipt.read_text("utf-8"))
            if (old["passed"] and old["source_pose_sha256"] == binding["source_pose_sha256"]
                    and old["video_sha256"] == digest(target)
                    and old["renderer_code_sha256"] == digest(__file__)):
                print(json.dumps({"run": run_id, "reused_completed_clip": True}), flush=True)
                return old
        raise FileExistsError("Incomplete or changed rendering preserved; no overwrite or automatic repeat")
    poses = np.load(source_run / "poses.npz", allow_pickle=False)
    frames = len(poses["time_s"])
    frame_map = poses["time_s"].tolist()
    if (frames < 2 or not np.all(np.diff(poses["time_s"]) > 0)
            or any(not np.isfinite(poses[key]).all() for key in ("time_s", "qpos", "qvel", "ctrl"))):
        raise ValueError("Invalid retained state arrays")
    fps, width, height = 20, 960, 540
    model = mujoco.MjModel.from_xml_path(str(XML))
    if any(poses[key].shape != (frames, size) for key, size in (("qpos", model.nq), ("qvel", model.nv), ("ctrl", model.nu))):
        raise ValueError("Saved state dimensions do not match the render-only model")
    model.vis.global_.offwidth, model.vis.global_.offheight = width, height
    data, camera = mujoco.MjData(model), mujoco.MjvCamera()
    camera.distance, camera.azimuth, camera.elevation = 2.7, 135, -18
    command = [str(encoder), "-hide_banner", "-loglevel", "error", "-n", "-f", "rawvideo",
        "-vcodec", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps),
        "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)]
    result = json.loads((source_run / "result.json").read_text("utf-8"))
    walk = result["nodes"][1]
    selected_times = [0, walk["start_state"]["simulation_time"],
        walk["start_state"]["simulation_time"] + 2, walk["end_state"]["simulation_time"], poses["time_s"][-1]]
    selected = {int(np.argmin(np.abs(poses["time_s"] - value))) for value in selected_times}
    started, timings, unchanged = time.perf_counter(), [], True
    step_attempts = 0
    original_steps = {name: getattr(mujoco, name) for name in ("mj_step", "mj_step1", "mj_step2")}

    def forbidden_step(*args, **kwargs):
        nonlocal step_attempts
        step_attempts += 1
        raise RuntimeError("Physics stepping is forbidden in acquisition-state playback")

    process = None
    for name in original_steps:
        setattr(mujoco, name, forbidden_step)
    try:
        with (directory / "encoder.log").open("xb") as log:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            with mujoco.Renderer(model, height=height, width=width) as renderer:
                for index, sim_time in enumerate(poses["time_s"]):
                    if time.perf_counter() - started > budget_s:
                        raise TimeoutError("Render wall budget exceeded; partial output retained")
                    frame_started = time.perf_counter()
                    data.qpos[:], data.qvel[:], data.ctrl[:] = poses["qpos"][index], poses["qvel"][index], poses["ctrl"][index]
                    data.time = float(sim_time)
                    mujoco.mj_forward(model, data)
                    camera.lookat[:] = [data.qpos[0], data.qpos[1], .78]
                    renderer.update_scene(data, camera=camera)
                    pixels = renderer.render()
                    process.stdin.write(pixels.tobytes())
                    unchanged &= (np.array_equal(data.qpos, poses["qpos"][index])
                        and np.array_equal(data.qvel, poses["qvel"][index])
                        and np.array_equal(data.ctrl, poses["ctrl"][index]) and data.time == float(sim_time))
                    if index in selected:
                        Image.fromarray(pixels).save(directory / f"frame-{index:04d}.png")
                    timings.append(time.perf_counter() - frame_started)
                    if index % 200 == 0 or index == frames - 1:
                        print(json.dumps({"run": run_id, "rendered_frames": index + 1, "total_frames": frames,
                            "elapsed_s": round(time.perf_counter() - started, 2), "mj_step_calls": step_attempts}), flush=True)
            process.stdin.close()
            if process.wait(timeout=60) != 0:
                raise RuntimeError("Encoder failed; original stderr retained")
        if not unchanged or step_attempts or source_binding(run_id)[1] != binding:
            raise RuntimeError("Playback state or source preservation failed")
    except Exception as error:
        write_new(receipt, {**binding, "passed": False, "visual_source": "state_playback",
            "pose_source": "original_acquisition_state_samples", "error_type": type(error).__name__,
            "completed_frames": len(timings), "mj_step_calls": step_attempts,
            "partial_output_preserved": True, "automatic_repeat": False})
        raise
    finally:
        for name, function in original_steps.items():
            setattr(mujoco, name, function)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        poses.close()
    report = {**binding, "passed": True, "visual_source": "state_playback",
        "pose_source": "original_acquisition_state_samples",
        "render_mechanism": "native MuJoCo Renderer; restore original acquisition states; isolated mj_forward; zero mj_step",
        "mj_step_calls": 0, "mj_forward_calls": frames, "new_physics_acquisition": False,
        "new_probe_runs": 0, "training_steps": 0, "original_model_modified": False,
        "physics_execution_finished_before_rendering": True, "pose_unchanged": unchanged,
        "qvel_ctrl_time_unchanged": unchanged, "frames": frames, "fps": fps, "dimensions": [width, height],
        "camera": {"distance": 2.7, "azimuth": 135, "elevation": -18, "lookat": "actual base x/y, fixed z=.78"},
        "frame_sim_times_s": frame_map,
        "last_frame_note": "Exact final acquisition state appended; use frame_sim_times_s, not media.duration, for time.",
        "median_frame_and_encode_ms": float(np.median(timings) * 1000),
        "p95_frame_and_encode_ms": float(np.quantile(timings, .95) * 1000),
        "render_wall_s": time.perf_counter() - started, "render_budget_s": budget_s,
        "encoder_sha256": digest(encoder), "renderer_code_sha256": digest(__file__),
        "model_sha256": digest(XML), "pose_sha256": binding["source_pose_sha256"], "video_sha256": digest(target)}
    write_new(receipt, report)
    print(json.dumps({"run": run_id, "passed": True, "frames": frames, "video_sha256": report["video_sha256"]}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", choices=["all", *RUNS], default="all")
    parser.add_argument("--encoder", type=Path, default=ROOT / "console/.tools/ffmpeg.exe")
    parser.add_argument("--budget-s", type=float, default=120)
    args = parser.parse_args()
    if not 0 < args.budget_s <= 120:
        parser.error("render budget must be within (0, 120] seconds per clip")
    for selected_run in RUNS if args.run == "all" else [args.run]:
        render(selected_run, args.encoder, args.budget_s)
