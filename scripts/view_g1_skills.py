"""Interactive MuJoCo viewer for the existing G1 skills (observation only).

Runs one real-time sequence with the existing Skill Router and skills - no new
control logic, no parameter changes:

    Reset -> Stand 5 s -> WalkForward 2.0 m -> Stop -> pause 2 s
          -> Turn +45 deg -> Stop -> pause 2 s
          -> Turn -45 deg -> Stop -> pause 2 s
          -> WalkForward 5.0 m -> Stop

The simulation is stepped through the existing ``G1Simulation``; a thin proxy
only adds viewer synchronisation, wall-clock pacing and clean exit handling.
After the sequence the window stays open and the robot keeps standing until the
window is closed (or ``--hold-open-seconds`` elapses).

Examples::

    python scripts/view_g1_skills.py
    python scripts/view_g1_skills.py --speed 2.0
"""

from __future__ import annotations

import argparse
import math
import time

from g1swarm.characterization.kinematics import (
    forward_lateral,
    horizontal_offset,
    wrap_angle_deg,
    yaw_deg,
    yaw_rad,
)
from g1swarm.config import build_controller, build_simulation, load_yaml
from g1swarm.skills import (
    SkillContext,
    SkillRequest,
    SkillRouter,
    StandSkill,
    StopSkill,
    TurnSkill,
    WalkForwardSkill,
)

ROBOT_CONFIG = "configs/robot/g1_locomotion_12dof.yaml"

# Phase 1.2 observation-only scenarios (viewer is never a metric source).
SCENARIOS = {
    "reliable-walk2m": {"distance_m": 2.0},
    "transition-yaw10deg": {"distance_m": 2.0, "yaw_offset_deg": 10.0},
    "failure-yaw20deg": {"distance_m": 2.0, "yaw_offset_deg": 20.0},
    "failure-walk10m": {"distance_m": 10.0},
    "low-friction-0p15": {"distance_m": 2.0, "friction_slide": 0.15},
}

# Frozen Phase 1 / Phase 1.1 values, reused unchanged.
STOP_WINDOW_S = 1.0
STOP_THRESHOLD_MPS = 0.10
STOP_MAX_DURATION_S = 4.0
TURN_TOLERANCE_DEG = 15.0
TURN_MAX_DURATION_S = 10.0
WALK_SPEED_MPS = 0.5


class ViewerClosed(RuntimeError):
    """Raised when the user closes the MuJoCo viewer window."""


class RealTimeViewerProxy:
    """Delegates to ``G1Simulation`` and adds viewer sync + real-time pacing."""

    def __init__(
        self, simulation, viewer, *, speed: float = 1.0, sync_every: int = 8
    ) -> None:
        self._simulation = simulation
        self._viewer = viewer
        self._speed = max(0.05, float(speed))
        # Viewer sync is the expensive part of the loop; syncing every few 500 Hz
        # steps keeps the picture smooth while staying close to real time.
        self._sync_every = max(1, int(sync_every))
        self._steps_since_sync = 0
        self.simulated_time = 0.0
        self.wall_time = 0.0

    @property
    def viewer_running(self) -> bool:
        return bool(self._viewer.is_running())

    def step(self, control=None):
        if not self.viewer_running:
            raise ViewerClosed("viewer window closed")
        started = time.perf_counter()
        state = self._simulation.step(control)
        self._steps_since_sync += 1
        if self._steps_since_sync >= self._sync_every:
            self._simulation.sync_viewer()
            self._steps_since_sync = 0
        elapsed = time.perf_counter() - started
        self.wall_time += elapsed
        budget = self._simulation.timestep / self._speed
        remaining = budget - elapsed
        if remaining > 0.0:
            time.sleep(remaining)
            self.wall_time += remaining
        self.simulated_time = state.simulation_time
        return state

    def pause(self, seconds: float) -> None:
        """Freeze the physics but keep the window responsive for ``seconds``."""

        deadline = time.perf_counter() + max(0.0, float(seconds))
        while time.perf_counter() < deadline:
            if not self.viewer_running:
                raise ViewerClosed("viewer window closed")
            self._simulation.sync_viewer()
            time.sleep(min(0.05, max(0.0, deadline - time.perf_counter())))

    def __getattr__(self, name: str):
        return getattr(self._simulation, name)


def _walk_tolerance(target_m: float) -> float:
    return max(0.2, 0.10 * float(target_m))


def _walk_timeout(target_m: float) -> float:
    return max(15.0, 6.0 * float(target_m))


def _print_state_block(
    skill: str,
    target: str,
    *,
    simulation_time: float,
    position,
    heading_deg: float,
    forward_m: float | None,
    lateral_m: float | None,
    status: str,
) -> None:
    print(f"Skill: {skill}")
    print(f"  Target: {target}")
    print(f"  Simulation time: {simulation_time:.2f} s")
    print(f"  Base position: x={position[0]:+.3f} m  y={position[1]:+.3f} m  z={position[2]:.3f} m")
    print(f"  Heading: {heading_deg:+.2f} deg")
    if forward_m is not None:
        print(f"  Forward: {forward_m:+.3f} m")
    if lateral_m is not None:
        print(f"  Lateral drift: {lateral_m:+.3f} m")
    print(f"  Skill status: {status}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot", default=ROBOT_CONFIG, help="robot config path")
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="playback speed relative to real time (default 1.0)",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default=None,
        help="run one Phase 1.2 observation scenario instead of the default sequence",
    )
    parser.add_argument(
        "--sync-every",
        type=int,
        default=8,
        help="sync the viewer every N physics steps (default 8 = 62 Hz)",
    )
    parser.add_argument(
        "--hold-open-seconds",
        type=float,
        default=None,
        help="after the sequence, keep standing this long instead of until the window closes",
    )
    args = parser.parse_args()

    robot = load_yaml(args.robot)
    simulation = build_simulation(robot, seed=args.seed)
    controller = build_controller(robot)
    if controller is None:
        raise SystemExit("no official locomotion controller configured for this robot")

    viewer = simulation.open_viewer()
    proxy = RealTimeViewerProxy(
        simulation, viewer, speed=args.speed, sync_every=args.sync_every
    )
    router = SkillRouter([StandSkill(), WalkForwardSkill(), TurnSkill(), StopSkill()])
    context = SkillContext(
        simulation=proxy,
        controller=controller,
        robot_config=robot,
        max_steps=int(round(600.0 / simulation.timestep)),
        seed=args.seed,
    )

    def execute(skill_name: str, parameters: dict, target: str, mode: str) -> None:
        start_state = proxy.get_robot_state()
        result = router.execute(SkillRequest(skill_name, parameters), context)
        final_state = proxy.get_robot_state()
        forward_m = None
        lateral_m = None
        heading = yaw_deg(final_state.base_orientation)
        if mode == "walk":
            offset = horizontal_offset(start_state, final_state)
            forward_m, lateral_m = forward_lateral(offset, yaw_rad(start_state.base_orientation))
        elif mode == "turn":
            heading = wrap_angle_deg(
                yaw_deg(final_state.base_orientation) - yaw_deg(start_state.base_orientation)
            )
        _print_state_block(
            skill_name,
            target,
            simulation_time=final_state.simulation_time,
            position=final_state.base_position,
            heading_deg=heading,
            forward_m=forward_m,
            lateral_m=lateral_m,
            status=result.status.value,
        )

    started = time.perf_counter()
    try:
        if args.scenario is not None:
            scenario = SCENARIOS[args.scenario]
            simulation.reset(seed=args.seed)
            details: list[str] = []
            if "friction_slide" in scenario:
                simulation.set_all_geom_friction(float(scenario["friction_slide"]))
                details.append(f"friction_slide={scenario['friction_slide']}")
            if "yaw_offset_deg" in scenario:
                simulation.set_base_state(
                    yaw_rad=math.radians(float(scenario["yaw_offset_deg"]))
                )
                details.append(f"initial_yaw={scenario['yaw_offset_deg']}deg")
            distance = float(scenario["distance_m"])
            print(f"Scenario: {args.scenario} ({', '.join(details) or 'nominal'})\n")
            execute(
                "walk_forward",
                {"target_distance_m": distance, "tolerance_m": _walk_tolerance(distance),
                 "speed_mps": WALK_SPEED_MPS, "max_duration_s": _walk_timeout(distance)},
                f"{distance:g} m",
                "walk",
            )
            if args.hold_open_seconds is not None and args.hold_open_seconds > 0:
                router.execute(
                    SkillRequest("stand", {"duration_s": float(args.hold_open_seconds)}),
                    context,
                )
            return 0
        print("Opening MuJoCo viewer. Close the window or press Ctrl+C to stop.")
        print()
        simulation.reset(seed=args.seed)
        simulation.sync_viewer()
        print("Reset\n")

        execute("stand", {"duration_s": 5.0}, "hold stance 5.0 s", "stand")

        walk_2 = {"target_distance_m": 2.0, "tolerance_m": _walk_tolerance(2.0),
                  "speed_mps": WALK_SPEED_MPS, "max_duration_s": _walk_timeout(2.0)}
        execute("walk_forward", walk_2, "2.0 m", "walk")
        execute("stop", {"window_s": STOP_WINDOW_S, "speed_threshold_mps": STOP_THRESHOLD_MPS,
                         "max_duration_s": STOP_MAX_DURATION_S}, "zero velocity", "stop")
        print("Pause 2.0 s (physics frozen for observation)\n")
        proxy.pause(2.0)

        for angle in (45.0, -45.0):
            execute("turn", {"target_angle_deg": angle, "tolerance_deg": TURN_TOLERANCE_DEG,
                             "yaw_rate_radps": 0.5, "max_duration_s": TURN_MAX_DURATION_S},
                    f"{angle:+.1f} deg", "turn")
            execute("stop", {"window_s": STOP_WINDOW_S, "speed_threshold_mps": STOP_THRESHOLD_MPS,
                             "max_duration_s": STOP_MAX_DURATION_S}, "zero velocity", "stop")
            print("Pause 2.0 s (physics frozen for observation)\n")
            proxy.pause(2.0)

        walk_5 = {"target_distance_m": 5.0, "tolerance_m": _walk_tolerance(5.0),
                  "speed_mps": WALK_SPEED_MPS, "max_duration_s": _walk_timeout(5.0)}
        execute("walk_forward", walk_5, "5.0 m", "walk")
        execute("stop", {"window_s": STOP_WINDOW_S, "speed_threshold_mps": STOP_THRESHOLD_MPS,
                         "max_duration_s": STOP_MAX_DURATION_S}, "zero velocity", "stop")

        if args.hold_open_seconds is not None:
            if args.hold_open_seconds > 0:
                print(f"Holding stance for {args.hold_open_seconds:.1f} s, then closing.\n")
                router.execute(
                    SkillRequest("stand", {"duration_s": float(args.hold_open_seconds)}), context
                )
        else:
            print("Sequence complete. The viewer stays open and the robot keeps standing.")
            print("Close the MuJoCo window (or press Esc) to exit.\n")
            while proxy.viewer_running:
                router.execute(SkillRequest("stand", {"duration_s": 10.0}), context)
    except ViewerClosed:
        print("\nViewer window closed - stopping.")
    except KeyboardInterrupt:
        print("\nInterrupted - stopping.")
    finally:
        wall = time.perf_counter() - started
        simulation.close()
        rate = (proxy.simulated_time / wall) if wall > 0 else 0.0
        print(f"Total simulated {proxy.simulated_time:.2f} s in {wall:.2f} s wall ({rate:.2f}x real time).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
