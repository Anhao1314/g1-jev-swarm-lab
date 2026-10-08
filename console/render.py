"""Separate-process native rendering of saved derived replay poses, no mj_step."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import mujoco
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / "third_party/unitree_rl_gym/resources/robots/g1_description/scene.xml"


def render(run, encoder):
    target = run / "rollout.mp4"
    if target.exists():
        raise FileExistsError(target)
    poses = np.load(run / "poses.npz", allow_pickle=False)
    manifest = json.loads((run / "capture_manifest.json").read_text())
    assert manifest["parity"]["historical_record_exact"]
    assert manifest["parity"]["capture_off_on_equal"]
    fps, width, height = 20, 960, 540
    model = mujoco.MjModel.from_xml_path(str(XML))
    # Render-only clone framebuffer dimensions; original physics model is absent.
    model.vis.global_.offwidth = width
    model.vis.global_.offheight = height
    data = mujoco.MjData(model)
    camera = mujoco.MjvCamera()
    camera.distance, camera.azimuth, camera.elevation = 2.7, 135, -18
    command = [str(encoder), "-hide_banner", "-loglevel", "error", "-n", "-f", "rawvideo",
               "-vcodec", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps),
               "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "22",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)]
    timings = []
    pose_unchanged = True
    with (run / "encoder.log").open("xb") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with mujoco.Renderer(model, height=height, width=width) as renderer:
                for index, sim_time in enumerate(poses["time_s"]):
                    started = time.perf_counter()
                    data.qpos[:] = poses["qpos"][index]
                    data.qvel[:] = poses["qvel"][index]
                    data.ctrl[:] = poses["ctrl"][index]
                    data.time = sim_time
                    mujoco.mj_forward(model, data)
                    camera.lookat[:] = [data.qpos[0], data.qpos[1], .78]
                    renderer.update_scene(data, camera=camera)
                    pixels = renderer.render()
                    process.stdin.write(pixels.tobytes())
                    pose_unchanged &= bool(np.array_equal(data.qpos, poses["qpos"][index]))
                    if index in (0, 400, 540, len(poses["time_s"]) - 1):
                        Image.fromarray(pixels).save(run / f"frame-{index:04d}.png")
                    timings.append(time.perf_counter() - started)
            process.stdin.close()
            if process.wait(timeout=60) != 0:
                raise RuntimeError("Encoder failed; stderr retained")
        finally:
            if process.poll() is None:
                process.kill()
    report = {"passed": pose_unchanged, "visual_source": "derived_visualization_replay",
              "pose_source": "new offline historical visualization replay; not original acquisition poses",
              "render_mechanism": "native MuJoCo Renderer; mj_forward on isolated model/data; zero mj_step",
              "original_model_modified": False, "camera": {"distance": 2.7, "azimuth": 135, "elevation": -18,
                  "lookat": "actual base x/y, fixed z=.78"},
              "physics_execution_finished_before_rendering": True, "frames": len(timings), "fps": fps,
              "dimensions": [width, height], "pose_unchanged": pose_unchanged,
              "median_frame_and_encode_ms": float(np.median(timings) * 1000),
              "p95_frame_and_encode_ms": float(np.quantile(timings, .95) * 1000),
              "frame_sim_times_s": poses["time_s"].tolist(),
              "last_frame_note": "Final exact pose appended at next encoded frame. Use frame_sim_times_s, not media.duration, for time.",
              "encoder_sha256": hashlib.sha256(encoder.read_bytes()).hexdigest(),
              "renderer_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "model_sha256": hashlib.sha256(XML.read_bytes()).hexdigest(),
              "pose_sha256": hashlib.sha256((run / "poses.npz").read_bytes()).hexdigest(),
              "video_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    with (run / "render_manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps({k: report[k] for k in ("passed", "frames", "dimensions", "median_frame_and_encode_ms", "video_sha256")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--encoder", type=Path, default=ROOT / "console/.tools/ffmpeg.exe")
    args = parser.parse_args()
    render(args.run, args.encoder)
