"""Viewer sanity check for the Phase 1.3 correction modes (one 8 m walk).

Example::

    python scripts/view_correction.py --mode open_loop
    python scripts/view_correction.py --mode heading_only
    python scripts/view_correction.py --mode heading_lateral

The viewer is a sanity check only - it is never a source of formal metrics.
"""

from __future__ import annotations

import argparse
import json
import math
import time

from g1swarm.boundary.envelope import evaluate_walk_task
from g1swarm.config import build_controller, build_simulation, load_yaml
from g1swarm.control import (
    CorrectionConfig,
    CorrectionTracker,
    CorrectingController,
    PathCorrectionPolicy,
)
from g1swarm.segmentation.mission import MissionFrame
from g1swarm.skills import SkillContext, SkillRequest, SkillRouter, WalkForwardSkill

from view_g1_skills import RealTimeViewerProxy, _walk_timeout, _walk_tolerance, WALK_SPEED_MPS

MODE_FOR_TREATMENT = {
    "open_loop": "none",
    "heading_only": "heading_only",
    "heading_lateral": "heading_lateral",
}


def _correction_config(mode: str, k_heading: float, k_lateral: float) -> CorrectionConfig:
    return CorrectionConfig(
        mode=mode,
        k_heading=k_heading,
        k_lateral=k_lateral,
        max_yaw_rate_radps=0.6,
        deadband_radps=0.01,
        oscillation_threshold_radps=0.05,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=sorted(MODE_FOR_TREATMENT), default="open_loop"
    )
    parser.add_argument("--distance", type=float, default=8.0)
    parser.add_argument("--k-heading", type=float, default=1.5)
    parser.add_argument("--k-lateral", type=float, default=1.0)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--sync-every", type=int, default=8)
    parser.add_argument("--hold-open-seconds", type=float, default=None)
    parser.add_argument(
        "--robot", default="configs/robot/g1_locomotion_12dof.yaml"
    )
    args = parser.parse_args()

    robot = load_yaml(args.robot)
    simulation = build_simulation(robot, seed=0)
    controller = build_controller(robot)
    viewer = simulation.open_viewer()
    proxy = RealTimeViewerProxy(simulation, viewer, speed=args.speed, sync_every=args.sync_every)
    state = simulation.reset(seed=0)
    frame = MissionFrame.from_state(state)
    config = _correction_config(MODE_FOR_TREATMENT[args.mode], args.k_heading, args.k_lateral)
    tracker: CorrectionTracker | None = None
    task_controller = controller
    if config.mode != "none":
        tracker = CorrectionTracker(oscillation_threshold_radps=config.oscillation_threshold_radps)

        def on_sample(sample) -> None:
            print(
                f"  t={sample.sim_time_s:5.2f}s  e_head={math.degrees(sample.heading_error_rad):+6.2f} deg"
                f"  e_lat={sample.lateral_error_m:+.3f} m  yaw_cmd={sample.yaw_clipped:+.3f} rad/s"
                f"  sat={sample.saturated}"
            )

        task_controller = CorrectingController(
            controller,
            PathCorrectionPolicy(config),
            proxy,
            frame,
            tracker=tracker,
            on_sample=on_sample,
            sample_period_s=2.0,
        )
    context = SkillContext(
        simulation=proxy,
        controller=task_controller,
        robot_config=robot,
        max_steps=int(round(1200.0 / simulation.timestep)),
        seed=0,
    )
    router = SkillRouter([WalkForwardSkill()])
    started = time.perf_counter()
    try:
        print(f"Mode: {args.mode} ({config.mode})  distance={args.distance:g} m")
        print(f"Gains: k_heading={args.k_heading} k_lateral={args.k_lateral}\n")
        walk = router.execute(
            SkillRequest(
                "walk_forward",
                {
                    "target_distance_m": float(args.distance),
                    "tolerance_m": _walk_tolerance(args.distance),
                    "speed_mps": WALK_SPEED_MPS,
                    "max_duration_s": _walk_timeout(args.distance),
                    "reset_memory": True,
                },
            ),
            context,
        )
        final_state = proxy.get_robot_state()
        forward, lateral = frame.project(final_state.base_position)
        heading = frame.heading_error_deg(final_state)
        canonical = {
            "forward_displacement_m": forward,
            "distance_error_m": abs(forward - args.distance),
            "lateral_drift_m": lateral,
            "heading_error_deg": heading,
            "simulation_time_s": final_state.simulation_time - state.simulation_time,
            "physical_success": walk.status.value == "SUCCESS",
            "task_success": False,
            "failure_type": "SUCCESS",
            "failure_reason": None,
        }
        evaluation = evaluate_walk_task(canonical, args.distance, physical=canonical["physical_success"])
        summary = tracker.summary() if tracker else {
            "correction_rms": 0.0,
            "correction_max_abs": 0.0,
            "saturation_count": 0,
            "saturation_fraction": 0.0,
            "control_oscillation_count": 0,
        }
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "skill_status": walk.status.value,
                    "forward_m": forward,
                    "lateral_drift_m": lateral,
                    "heading_error_deg": heading,
                    "task_success": evaluation["task_success"],
                    "violations": evaluation["task_violations"],
                    "wall_time_s": time.perf_counter() - started,
                    "correction": summary,
                },
                indent=2,
                sort_keys=True,
            )
        )
        if args.hold_open_seconds is not None and args.hold_open_seconds > 0:
            deadline = time.perf_counter() + args.hold_open_seconds
            while proxy.viewer_running and time.perf_counter() < deadline:
                simulation.sync_viewer()
                time.sleep(0.05)
        elif args.hold_open_seconds is None:
            print("Viewer stays open; close the window or press Ctrl+C to exit.")
            while proxy.viewer_running:
                simulation.sync_viewer()
                time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        simulation.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
