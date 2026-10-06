"""Live MuJoCo mission session (real skills + correction layer).

One continuous simulation executes every node of a mission, so skill-to-skill
transitions happen in the same physics state - exactly the thing the runtime is
supposed to measure. Each WalkForward node uses its own node-start mission
frame; after a Turn the next Walk runs along the new heading (task-graph
semantics), while the closed-loop correction of that node is applied in the
node's own start frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import numpy as np

from ..config import build_controller, build_simulation
from ..control import (
    CorrectionConfig,
    CorrectionTracker,
    CorrectingController,
    PathCorrectionPolicy,
)
from ..metrics import RunMetrics
from ..segmentation.mission import MissionFrame
from ..skills import (
    SkillContext,
    SkillRequest,
    SkillRouter,
    StandSkill,
    StopSkill,
    TurnSkill,
    WalkForwardSkill,
)

# Whitelist registry: mission skill names map to registered skill classes only.
# No dynamic import and no user-controlled class path is ever resolved.
SKILL_REGISTRY = {
    "stand": StandSkill,
    "walk_forward": WalkForwardSkill,
    "turn": TurnSkill,
    "stop": StopSkill,
}

ZERO_CORRECTION = {
    "correction_rms": 0.0,
    "correction_max_abs": 0.0,
    "saturation_count": 0,
    "saturation_fraction": 0.0,
    "control_oscillation_count": 0,
    "correction_samples": 0,
}


class NodeMonitor:
    """Simulation proxy: counts steps and tracks path length / error extremes."""

    def __init__(self, simulation, frame: MissionFrame) -> None:
        self._simulation = simulation
        self._frame = frame
        self.steps = 0
        self.path_length_m = 0.0
        self.max_abs_lateral_error_m = 0.0
        self.max_abs_heading_error_deg = 0.0
        position = simulation.get_robot_state().base_position
        self._last_position = np.array(position[:2], dtype=np.float64)

    def step(self, control=None):
        state = self._simulation.step(control)
        self.steps += 1
        position = np.array(state.base_position[:2], dtype=np.float64)
        self.path_length_m += float(np.linalg.norm(position - self._last_position))
        self._last_position = position
        _, lateral = self._frame.project(state.base_position)
        heading = self._frame.heading_error_deg(state)
        self.max_abs_lateral_error_m = max(self.max_abs_lateral_error_m, abs(lateral))
        self.max_abs_heading_error_deg = max(self.max_abs_heading_error_deg, abs(heading))
        return state

    def __getattr__(self, name: str):
        return getattr(self._simulation, name)


@dataclass
class NodeExecution:
    skill: str
    status: str
    reason: str | None
    physical_success: bool
    metrics: dict[str, Any]
    start_state: dict[str, Any]
    end_state: dict[str, Any]
    simulation_steps: int
    memory_resets: int
    correction: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "status": self.status,
            "reason": self.reason,
            "physical_success": self.physical_success,
            "metrics": self.metrics,
            "start_state": self.start_state,
            "end_state": self.end_state,
            "simulation_steps": self.simulation_steps,
            "memory_resets": self.memory_resets,
            "correction": self.correction,
        }


class LiveMissionSession:
    def __init__(
        self,
        *,
        robot_config: Mapping[str, Any],
        protocol: Mapping[str, Any],
        seed: int = 0,
        simulation_wrapper: Callable[[Any], Any] | None = None,
    ) -> None:
        self.robot_config = dict(robot_config)
        self.protocol = dict(protocol)
        self.seed = int(seed)
        self.simulation_wrapper = simulation_wrapper
        self.simulation = build_simulation(self.robot_config, seed=self.seed)
        self.controller = build_controller(self.robot_config)
        self.current_state = self.simulation.reset(seed=self.seed)
        self.total_steps = 0
        self.router = SkillRouter(
            [SKILL_REGISTRY[name]() for name in ("stand", "walk_forward", "turn", "stop")]
        )

    # ------------------------------------------------------------------
    def state(self):
        return self.current_state

    def _skill_parameters(self, node) -> dict[str, Any]:
        spec = self.protocol["skill_parameters"]
        skill = node.skill.value
        if skill == "walk_forward":
            distance = float(node.parameters["distance_m"])
            walk = spec["walk_forward"]
            return {
                "target_distance_m": distance,
                "tolerance_m": float(walk["tolerance_m"]),
                "speed_mps": float(walk["speed_mps"]),
                "max_duration_s": max(
                    float(walk["timeout_min_s"]), float(walk["timeout_s_per_m"]) * distance
                ),
                "reset_memory": True,
            }
        if skill == "turn":
            turn = spec["turn"]
            return {
                "target_angle_deg": float(node.parameters["angle_deg"]),
                "tolerance_deg": float(turn["tolerance_deg"]),
                "yaw_rate_radps": float(turn["yaw_rate_radps"]),
                "max_duration_s": float(turn["max_duration_s"]),
                "settle_s": float(turn["settle_s"]),
                "reset_memory": True,
            }
        if skill == "stand":
            stand = spec["stand"]
            return {
                "duration_s": float(
                    node.parameters.get("duration_s", stand["default_duration_s"])
                ),
                "reset_memory": True,
            }
        stop = spec["stop"]
        return {
            "window_s": float(stop["window_s"]),
            "speed_threshold_mps": float(stop["speed_threshold_mps"]),
            "max_duration_s": float(stop["max_duration_s"]),
        }

    # ------------------------------------------------------------------
    def run_node(self, node, execution_mode: str) -> NodeExecution:
        skill = node.skill.value
        frame = MissionFrame.from_state(self.current_state)
        monitor = NodeMonitor(self.simulation, frame)
        view = self.simulation_wrapper(monitor) if self.simulation_wrapper else monitor
        tracker: CorrectionTracker | None = None
        task_controller = self.controller
        if execution_mode in {"heading_only", "heading_lateral"}:
            grounding = self.protocol["grounding"]
            gains = grounding["correction_gains"][execution_mode]
            limits = grounding["correction_limits"]
            config = CorrectionConfig(
                mode=execution_mode,
                k_heading=float(gains["k_heading"]),
                k_lateral=float(gains.get("k_lateral", 0.0)),
                max_yaw_rate_radps=float(limits["max_yaw_rate_radps"]),
                deadband_radps=float(limits["deadband_radps"]),
                oscillation_threshold_radps=float(limits["oscillation_threshold_radps"]),
            )
            tracker = CorrectionTracker(
                oscillation_threshold_radps=config.oscillation_threshold_radps
            )
            task_controller = CorrectingController(
                self.controller,
                PathCorrectionPolicy(config),
                view,
                frame,
                tracker=tracker,
                sample_period_s=1.0,
            )
        context = SkillContext(
            simulation=view,
            controller=task_controller,
            robot_config=self.robot_config,
            max_steps=int(round(1200.0 / self.simulation.timestep)),
            seed=self.seed,
        )
        start_state = self.current_state
        result = self.router.execute(
            SkillRequest(skill, self._skill_parameters(node)), context
        )
        final_state = view.get_robot_state()
        elapsed = final_state.simulation_time - start_state.simulation_time
        forward, lateral = frame.project(final_state.base_position)
        frame_heading = frame.heading_error_deg(final_state)
        if skill == "walk_forward":
            distance_error = abs(forward - float(node.parameters["distance_m"]))
            heading_error = frame_heading
        elif skill == "turn":
            turned = float(result.metrics.get("turned_deg", 0.0))
            distance_error = 0.0
            heading_error = abs(turned - float(node.parameters["angle_deg"]))
        else:
            distance_error = 0.0
            heading_error = frame_heading
        fallen = bool(result.metrics.get("fallen"))
        finite = final_state.is_finite()
        physical = bool(
            not fallen
            and finite
            and result.status.value
            not in {"UNSAFE", "NON_FINITE_STATE", "INVALID_CONTROL", "INTERRUPTED"}
        )
        task_success = bool(result.status.value == "SUCCESS" and physical)
        if task_success:
            failure_type = "SUCCESS"
            failure_reason = None
        elif result.status.value != "SUCCESS":
            failure_type = result.status.value
            failure_reason = result.reason
        else:
            failure_type = "UNKNOWN_FAILURE"
            failure_reason = "skill reported success but the node was not physically valid"
        stats = tracker.summary() if tracker is not None else dict(ZERO_CORRECTION)
        run_metrics = RunMetrics(
            target_distance_m=(
                float(node.parameters["distance_m"]) if skill == "walk_forward" else None
            ),
            max_abs_lateral_error_m=monitor.max_abs_lateral_error_m,
            max_abs_heading_error_deg=monitor.max_abs_heading_error_deg,
            wall_time_s=result.duration_s,
            mean_forward_speed_mps=(forward / elapsed) if elapsed > 0 else None,
            final_speed_mps=final_state.speed(),
            correction_rms=float(stats["correction_rms"]),
            correction_max_abs=float(stats["correction_max_abs"]),
            saturation_count=int(stats["saturation_count"]),
            saturation_fraction=float(stats["saturation_fraction"]),
            control_oscillation_count=int(stats["control_oscillation_count"]),
            controller_memory_resets=1 if skill in {"stand", "walk_forward", "turn"} else 0,
            policy_hash=str(self.protocol["provenance"]["policy_sha256"]),
            controller_version=str(self.protocol["provenance"]["controller_commit"]),
            extras={
                "node_id": node.node_id,
                "skill": skill,
                "execution_mode": execution_mode,
                "skill_status": result.status.value,
                "path_length_m": monitor.path_length_m,
                "correction_samples": int(stats["correction_samples"]),
                "simulation_steps": monitor.steps,
            },
            forward_displacement_m=forward,
            distance_error_m=distance_error,
            lateral_drift_m=lateral,
            heading_error_deg=heading_error,
            simulation_time_s=elapsed,
            physical_success=physical,
            task_success=task_success,
            failure_type=failure_type,
            failure_reason=failure_reason,
        )
        run_metrics.validate()
        self.current_state = final_state
        self.total_steps += monitor.steps
        return NodeExecution(
            skill=skill,
            status=result.status.value,
            reason=result.reason,
            physical_success=physical,
            metrics=run_metrics.to_dict(),
            start_state=start_state.to_dict(),
            end_state=final_state.to_dict(),
            simulation_steps=monitor.steps,
            memory_resets=1 if skill in {"stand", "walk_forward", "turn"} else 0,
            correction=dict(stats),
        )

    def close(self) -> None:
        self.simulation.close()
