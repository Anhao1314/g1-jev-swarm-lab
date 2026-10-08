"""Compatibility spike: official Unitree G1 MJCF under native Windows MuJoCo.

For every configured model this script performs the minimum closed loop
required by Phase 1: load -> reset -> step (>= 1000 steps) -> read qpos/qvel.
It is headless, writes structured evidence under
``artifacts/compat-spike/<run_id>/`` and never opens a viewer.
"""

from __future__ import annotations

import argparse
import math
import time

import numpy as np

from g1swarm.config import build_controller, build_simulation, load_yaml
from g1swarm.evidence import RunRecorder
from g1swarm.paths import resolve_repo_path

from exp_common import manifest_for


def _tilt_deg(quaternion) -> float:
    w, x, y, z = (float(value) for value in quaternion)
    norm = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    up_z = (w * w - x * x - y * y + z * z) / (norm * norm)
    return math.degrees(math.acos(max(-1.0, min(1.0, up_z))))


def _run_model(robot: dict, *, steps: int, seed: int, experiment: dict) -> dict:
    simulation = build_simulation(robot, seed=seed)
    controller = build_controller(robot)
    run_id = f"{robot['name']}-run-{seed:03d}"
    recorder = RunRecorder(
        "compat-spike",
        run_id,
        manifest=manifest_for(
            experiment_id="g1_compat_spike",
            run_id=run_id,
            task=str(experiment.get("task", "compatibility spike")),
            robot=robot,
            experiment=experiment,
            seed=seed,
        ),
    )
    recorder.log_event("model_loaded", simulation.model_summary())

    heights: list[float] = []
    tilts: list[float] = []
    speeds: list[float] = []
    contacts: list[int] = []
    fall_step: int | None = None
    state_error: str | None = None
    started = time.perf_counter()
    completed = 0
    state = simulation.get_robot_state()
    try:
        for step in range(steps):
            if controller is None:
                control = np.zeros(simulation.num_actuators, dtype=np.float64)
            else:
                control = controller.compute_torques(
                    joint_positions=simulation.joint_positions(),
                    joint_velocities=simulation.joint_velocities(),
                    quaternion=simulation.base_quaternion(),
                    angular_velocity=simulation.base_angular_velocity(),
                    command=np.zeros(3, dtype=np.float64),
                    dt=simulation.timestep,
                )
            state = simulation.step(control)
            completed = step + 1
            heights.append(state.base_position[2])
            tilts.append(_tilt_deg(state.base_orientation))
            speeds.append(state.speed())
            contacts.append(simulation.contact_count())
            if state.fallen and fall_step is None:
                fall_step = step + 1
                recorder.log_event("fall_detected", {"step": step + 1, "state": state.to_dict()})
            if (step + 1) % 250 == 0:
                recorder.log_event(
                    "progress",
                    {
                        "step": step + 1,
                        "simulation_time": state.simulation_time,
                        "base_position": list(state.base_position),
                        "speed_mps": state.speed(),
                        "standing": state.standing,
                    },
                )
    except Exception as exc:  # noqa: BLE001 - recorded as evidence
        state_error = f"{type(exc).__name__}: {exc}"
    wall_time = time.perf_counter() - started
    warning_count, warning_text = simulation.mujoco_warning()
    simulated_time = state.simulation_time
    metrics = {
        "success": completed >= steps and state_error is None and state.is_finite(),
        "steps_requested": steps,
        "steps_completed": completed,
        "simulation_timestep_s": simulation.timestep,
        "simulated_time_s": simulated_time,
        "wall_clock_s": wall_time,
        "real_time_factor": (simulated_time / wall_time) if wall_time > 0 else None,
        "qpos_shape": [simulation.num_qpos],
        "qvel_shape": [simulation.num_qvel],
        "control_dim": simulation.num_actuators,
        "actuator_names": list(simulation.actuator_names()),
        "contacts_final": contacts[-1] if contacts else None,
        "contacts_max": max(contacts) if contacts else None,
        "nan_or_inf_detected": state_error is not None or not state.is_finite(),
        "state_error": state_error,
        "mujoco_warning_count": warning_count,
        "mujoco_warning_text": warning_text,
        "fallen": fall_step is not None,
        "fall_step": fall_step,
        "standing_at_end": state.standing,
        "final_position": list(state.base_position),
        "min_height_m": min(heights) if heights else None,
        "max_height_m": max(heights) if heights else None,
        "max_tilt_deg": max(tilts) if tilts else None,
        "mean_speed_mps": float(np.mean(speeds)) if speeds else None,
        "controller": "official_pretrained_policy" if controller else "zero_torque",
    }
    recorder.finish(
        {
            "status": "SUCCESS" if metrics["success"] else "FAILURE",
            "model": robot["name"],
            "steps_completed": completed,
        },
        metrics,
    )
    simulation.close()
    return {"run_id": run_id, **metrics}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="configs/experiments/g1_compat_spike.yaml",
        help="experiment config path (relative to the repository root)",
    )
    parser.add_argument("--steps", type=int, default=None, help="override step count")
    args = parser.parse_args()

    experiment = load_yaml(resolve_repo_path(args.config))
    steps = int(args.steps or experiment.get("steps", 1000))
    seeds = list(experiment.get("seeds", [0]))
    results = []
    for model_path in experiment.get("models", []):
        robot = load_yaml(model_path)
        for seed in seeds:
            result = _run_model(robot, steps=steps, seed=int(seed), experiment=experiment)
            results.append(result)
            print(
                f"[{result['run_id']}] success={result['success']} steps={result['steps_completed']}"
                f" rtf={result['real_time_factor']:.1f}x fallen={result['fallen']}"
            )
    failures = [result for result in results if not result["success"]]
    print(f"compat spike: {len(results) - len(failures)}/{len(results)} runs successful")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
