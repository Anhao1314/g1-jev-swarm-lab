"""Windows native MuJoCo offscreen gate. Runs in its own short-lived process."""
from pathlib import Path
import argparse
import hashlib
import json
import platform
import time

import mujoco
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / "third_party/unitree_rl_gym/resources/robots/g1_description/scene.xml"


def gate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    timings, hashes = [], []
    for context_index in range(3):
        model = mujoco.MjModel.from_xml_path(str(XML))
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        before = data.qpos.copy()
        camera = mujoco.MjvCamera()
        camera.lookat[:] = data.qpos[:3]
        camera.distance = 2.7
        camera.azimuth = 135
        camera.elevation = -18
        with mujoco.Renderer(model, height=360, width=640) as renderer:
            for index in range(20):
                started = time.perf_counter()
                renderer.update_scene(data, camera=camera)
                pixels = renderer.render().copy()
                timings.append(time.perf_counter() - started)
                hashes.append(hashlib.sha256(pixels.tobytes()).hexdigest())
                if context_index == 0 and index == 0:
                    Image.fromarray(pixels).save(output / "native-g1.png")
        assert np.array_equal(before, data.qpos), "Renderer mutated pose"
    report = {"passed": True, "platform": platform.platform(), "mujoco": mujoco.__version__,
              "backend": "native Windows GLFW offscreen", "separate_process": True,
              "contexts_created_and_closed": 3, "frames": len(timings),
              "identical_pixels_across_contexts": len(set(hashes)) == 1,
              "pose_unchanged": True, "median_render_ms": float(np.median(timings) * 1000),
              "p95_render_ms": float(np.quantile(timings, .95) * 1000),
              "dimensions": [640, 360], "model_sha256": hashlib.sha256(XML.read_bytes()).hexdigest(),
              "image_sha256": hashlib.sha256((output / "native-g1.png").read_bytes()).hexdigest()}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    gate(parser.parse_args().output)
