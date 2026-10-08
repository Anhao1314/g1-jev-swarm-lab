"""Baseline-001: Stand -> WalkForward 2.0 m -> Stop -> Evaluate.

Runs the frozen protocol from ``configs/experiments/g1_baseline_001.yaml`` over
its configured seeds. Success requires measured base displacement inside the
pre-frozen window after the stop skill, with no fall detected. Evidence is
written to ``artifacts/baseline-001/run-XXX/`` and the lightweight summary to
``experiments/baselines/g1_baseline_001/summary.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

from g1swarm.config import build_controller, build_simulation, load_yaml
from g1swarm.evaluation import summarize_baseline_runs
from g1swarm.evidence import RunRecorder
from g1swarm.paths import repo_root, resolve_repo_path
from g1swarm.skills import (
    SkillContext,
    SkillRequest,
    SkillRouter,
    StandSkill,
    StopSkill,
    WalkForwardSkill,
)

from exp_common import manifest_for


def _yaw_rad(quaternion) -> float:
    w, x, y, z = (float(value) for value in quaternion)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def run_one(robot: dict, experiment: dict, seed: int) -> dict:
    protocol = experiment.get("protocol", {})
    run_id = f"run-{seed:03d}"
    simulation = build_simulation(robot, seed=seed)
    controller = build_controller(robot)
    router = SkillRouter([StandSkill(), WalkForwardSkill(), StopSkill()])
    context = SkillContext(
        simulation=simulation,
        controller=controller,
        robot_config=robot,
        parameters={},
        max_steps=int(round(60.0 / simulation.timestep)),
        seed=seed,
    )
    recorder = RunRecorder(
        "baseline-001",
        run_id,
        manifest=manifest_for(
            experiment_id="g1_baseline_001",
            run_id=run_id,
            task=str(experiment.get("task", "baseline-001")),
            robot=robot,
            experiment=experiment,
            seed=seed,
        ),
    )
    started = time.perf_counter()
    initial_state = simulation.reset(seed=seed)
    recorder.log_event("reset", {"state": initial_state.to_dict()})

    stand = router.execute(
        SkillRequest("stand", {"duration_s": float(protocol.get("stand_duration_s", 2.0))}),
        context,
    )
    recorder.log_event("skill_result", stand.to_dict())

    walk = router.execute(
        SkillRequest(
            "walk_forward",
            {
                "target_distance_m": float(experiment.get("target_distance_m", 2.0)),
                "tolerance_m": float(experiment.get("tolerance_m", 0.2)),
                "speed_mps": float(protocol.get("walk_speed_mps", 0.5)),
                "max_duration_s": float(protocol.get("walk_max_duration_s", 15.0)),
                "stop_at_distance_m": float(
                    protocol.get("walk_stop_at_m", experiment.get("target_distance_m", 2.0))
                ),
            },
        ),
        context,
    )
    recorder.log_event("skill_result", walk.to_dict())

    stop = router.execute(
        SkillRequest(
            "stop",
            {
                "max_duration_s": float(protocol.get("stop_max_duration_s", 4.0)),
                "window_s": float(protocol.get("stop_window_s", 1.0)),
                "speed_threshold_mps": float(protocol.get("stop_speed_threshold_mps", 0.05)),
            },
        ),
        context,
    )
    recorder.log_event("skill_result", stop.to_dict())

    final_state = simulation.get_robot_state()
    yaw0 = _yaw_rad(initial_state.base_orientation)
    forward = np.array([math.cos(yaw0), math.sin(yaw0)])
    offset = np.array(final_state.base_position[:2]) - np.array(initial_state.base_position[:2])
    forward_displacement = float(offset @ forward)
    lateral_drift = float(forward[0] * offset[1] - forward[1] * offset[0])
    heading_error = math.degrees(_wrap_angle(_yaw_rad(final_state.base_orientation) - yaw0))
    window = experiment.get("success_window_m", [1.8, 2.2])
    within_window = float(window[0]) <= forward_displacement <= float(window[1])
    fallen = bool(
        stand.metrics.get("fallen") or walk.metrics.get("fallen") or stop.metrics.get("fallen")
    )
    success = bool(stand.ok and walk.ok and stop.ok and within_window and not fallen)
    metrics = {
        "run_id": run_id,
        "seed": seed,
        "initial_position": list(initial_state.base_position),
        "final_position": list(final_state.base_position),
        "forward_displacement_m": forward_displacement,
        "lateral_drift_m": lateral_drift,
        "heading_error_deg": heading_error,
        "elapsed_sim_time_s": final_state.simulation_time - initial_state.simulation_time,
        "elapsed_wall_time_s": time.perf_counter() - started,
        "fall_detected": fallen,
        "success_window_m": [float(window[0]), float(window[1])],
        "target_distance_m": float(experiment.get("target_distance_m", 2.0)),
        "tolerance_m": float(experiment.get("tolerance_m", 0.2)),
        "within_success_window": within_window,
        "completion_status": "SUCCESS" if success else "FAILURE",
        "success": success,
        "stand": stand.to_dict(),
        "walk_forward": walk.to_dict(),
        "stop": stop.to_dict(),
    }
    recorder.finish({"status": metrics["completion_status"], "success": success}, metrics)
    simulation.close()
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/experiments/g1_baseline_001.yaml")
    parser.add_argument("--seeds", type=int, nargs="*", default=None)
    parser.add_argument("--summary-out", default=None)
    args = parser.parse_args()

    experiment = load_yaml(args.config)
    robot = load_yaml(experiment["robot"])
    seeds = args.seeds if args.seeds is not None else list(experiment.get("seeds", [0]))
    results = []
    for seed in seeds:
        metrics = run_one(robot, experiment, int(seed))
        results.append(metrics)
        print(
            f"[run-{seed:03d}] status={metrics['completion_status']}"
            f" displacement={metrics['forward_displacement_m']:.3f}m"
            f" lateral={metrics['lateral_drift_m']:.3f}m"
            f" heading_err={metrics['heading_error_deg']:.2f}deg"
            f" wall={metrics['elapsed_wall_time_s']:.1f}s"
        )
    summary = summarize_baseline_runs(results)
    summary["experiment_id"] = str(experiment.get("experiment_id", "g1_baseline_001"))
    summary["task"] = str(experiment.get("task", ""))
    summary["seeds"] = [int(seed) for seed in seeds]
    summary["success_window_m"] = [
        float(value) for value in experiment.get("success_window_m", [1.8, 2.2])
    ]
    summary["robot_config"] = str(experiment.get("robot"))
    summary["artifact_path"] = str(Path("artifacts") / "baseline-001")
    out_path = (
        resolve_repo_path(args.summary_out)
        if args.summary_out
        else repo_root() / "experiments" / "baselines" / "g1_baseline_001" / "summary.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"summary written to {out_path}")
    return 0 if summary["successes"] == summary["runs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
