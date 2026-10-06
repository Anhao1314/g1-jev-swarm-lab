"""Phase 1.1 characterization runner.

Runs the frozen protocol's nominal experiments (command tracking, stop
characterization) and the one-factor-at-a-time robustness campaign, writes a
per-run evidence bundle for every run and aggregates the results into a summary.

Evidence layout::

    artifacts/g1_skill_characterization_001/<campaign>/<run_id>/
        manifest.json
        metrics.json
        events.jsonl
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

from ..config import build_controller, build_simulation, load_yaml
from ..evidence import EnvironmentInfo, RunManifest, RunRecorder, utc_timestamp
from ..paths import artifacts_dir
from ..skills import (
    SkillContext,
    SkillRequest,
    SkillRouter,
    SkillStatus,
    StandSkill,
    StopSkill,
    TurnSkill,
    WalkForwardSkill,
)
from .competence import build_competence_map, validate_competence_map
from .failures import classify_failure
from .kinematics import forward_lateral, horizontal_offset, wrap_angle_deg, yaw_deg, yaw_rad
from .perturbations import (
    DisturbanceProxy,
    apply_initial_perturbation,
    push_spec_from,
    sample_perturbation,
)
from .stats import is_deterministic, summarize

EXPERIMENT_ID = "g1_skill_characterization_001"


class CharacterizationRunner:
    def __init__(self, protocol_path: str | Path, *, campaign: str) -> None:
        if campaign not in {"pilot", "final"}:
            raise ValueError("campaign must be 'pilot' or 'final'")
        self.protocol_path = str(protocol_path)
        self.protocol = load_yaml(protocol_path)
        self.campaign = campaign
        self.robot = load_yaml(self.protocol["robot_config"])
        self.thresholds = self.protocol["thresholds"]
        self.results: list[dict[str, Any]] = []
        self.protocol_sha256 = hashlib.sha256(
            Path(self.protocol_path).read_bytes()
        ).hexdigest()

    # ------------------------------------------------------------------
    # evidence helpers
    # ------------------------------------------------------------------
    def _recorder(
        self,
        run_id: str,
        *,
        task: str,
        seed: int,
        condition: str,
        perturbation_type: str,
        perturbation_parameters: dict[str, Any] | None,
        thresholds: dict[str, Any],
    ) -> RunRecorder:
        provenance = self.protocol["provenance"]
        manifest = RunManifest(
            experiment_id=EXPERIMENT_ID,
            run_id=run_id,
            task=task,
            config={
                "protocol_path": self.protocol_path,
                "protocol_version": self.protocol.get("protocol_version"),
                "protocol_sha256": self.protocol_sha256,
                "condition": condition,
                "robot": self.robot,
            },
            environment=EnvironmentInfo.collect(),
            seed=seed,
            g1_model_source=provenance["model_source"],
            g1_model_commit=provenance["model_commit"],
            controller_source=provenance["controller_source"],
            controller_version=provenance["controller_commit"],
            controller_hash=provenance["policy_sha256"],
            campaign=self.campaign,
            perturbation_type=perturbation_type,
            perturbation_parameters=perturbation_parameters,
            thresholds=thresholds,
        )
        return RunRecorder(
            EXPERIMENT_ID,
            f"{self.campaign}/{run_id}",
            root=artifacts_dir(),
            manifest=manifest,
        )

    def _execute(
        self,
        router: SkillRouter,
        context: SkillContext,
        recorder: RunRecorder,
        skill_name: str,
        parameters: dict[str, Any],
    ):
        recorder.log_event(
            "skill_start",
            {
                "skill": skill_name,
                "parameters": parameters,
                "sim_time": context.simulation.simulation_time,
            },
        )
        result = router.execute(SkillRequest(skill_name, parameters), context)
        recorder.log_event(
            "skill_end",
            {
                "skill": skill_name,
                "status": result.status.value,
                "reason": result.reason,
                "steps": result.steps,
                "sim_time": context.simulation.simulation_time,
            },
        )
        if result.status is SkillStatus.PRECONDITION_FAILED:
            recorder.log_event(
                "precondition_failed", {"skill": skill_name, "reason": result.reason}
            )
        if result.metrics.get("fallen"):
            recorder.log_event(
                "fall_detected",
                {"skill": skill_name, "sim_time": context.simulation.simulation_time},
            )
        crossing = result.metrics.get("threshold_crossing_sim_time")
        if crossing is not None:
            recorder.log_event(
                "threshold_crossing", {"skill": skill_name, "sim_time": crossing}
            )
        return result

    def _finish_run(
        self,
        recorder: RunRecorder,
        *,
        run_id: str,
        skill: str,
        task: Any,
        condition: str,
        seed: int,
        success: bool,
        failure,
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "status": "SUCCESS" if success else failure.failure_type.value,
            "success": success,
            "failure_type": failure.failure_type.value,
            "failure_reason": failure.reason,
        }
        recorder.finish(payload, metrics)
        record = {
            "run_id": run_id,
            "skill": skill,
            "task": task,
            "condition": condition,
            "seed": seed,
            "success": success,
            "failure_type": failure.failure_type.value,
            "failure_reason": failure.reason,
            "metrics": metrics,
        }
        self.results.append(record)
        return record

    # ------------------------------------------------------------------
    # assessment helpers
    # ------------------------------------------------------------------
    def _walk_metrics(self, result, start_state, final_state, target: float, tolerance: float):
        offset = horizontal_offset(start_state, final_state)
        forward, lateral = forward_lateral(offset, yaw_rad(start_state.base_orientation))
        heading_error = wrap_angle_deg(
            yaw_deg(final_state.base_orientation) - yaw_deg(start_state.base_orientation)
        )
        distance_error = abs(forward - target)
        fall = bool(result.metrics.get("fallen"))
        finite = final_state.is_finite()
        failure = classify_failure(
            status=result.status,
            fall=fall,
            finite=finite,
            timeout=result.status is SkillStatus.TIMEOUT,
            distance_error=distance_error,
            distance_tolerance=tolerance,
            heading_error_deg=abs(heading_error),
            heading_tolerance_deg=None,
            reason=result.reason,
        )
        elapsed = final_state.simulation_time - start_state.simulation_time
        metrics = {
            "target_distance_m": target,
            "forward_displacement_m": forward,
            "absolute_distance_error_m": distance_error,
            "relative_distance_error": (distance_error / target) if target else None,
            "lateral_drift_m": lateral,
            "heading_error_deg": heading_error,
            "completion_sim_time_s": elapsed,
            "completion_wall_time_s": result.duration_s,
            "mean_speed_mps": (forward / elapsed) if elapsed > 0 else None,
            "residual_speed_mps": final_state.speed(),
            "fall_detected": fall,
            "non_finite_state": not finite,
            "skill_status": result.status.value,
            "failure_type": failure.failure_type.value,
            "failure_reason": failure.reason,
            "success": failure.ok,
        }
        return metrics, failure

    def _turn_metrics(self, result, start_state, final_state, target_deg: float, tolerance_deg: float):
        turned = float(result.metrics.get("turned_deg", 0.0))
        heading_error = abs(turned - float(target_deg))
        fall = bool(result.metrics.get("fallen"))
        finite = final_state.is_finite()
        failure = classify_failure(
            status=result.status,
            fall=fall,
            finite=finite,
            timeout=result.status is SkillStatus.TIMEOUT,
            heading_error_deg=heading_error,
            heading_tolerance_deg=tolerance_deg,
            reason=result.reason,
        )
        metrics = {
            "target_yaw_change_deg": float(target_deg),
            "actual_yaw_change_deg": turned,
            "absolute_heading_error_deg": heading_error,
            "translation_drift_m": float(result.metrics.get("translation_drift_m", 0.0)),
            "completion_sim_time_s": final_state.simulation_time - start_state.simulation_time,
            "completion_wall_time_s": result.duration_s,
            "residual_speed_mps": final_state.speed(),
            "fall_detected": fall,
            "non_finite_state": not finite,
            "skill_status": result.status.value,
            "failure_type": failure.failure_type.value,
            "failure_reason": failure.reason,
            "success": failure.ok,
        }
        return metrics, failure

    # ------------------------------------------------------------------
    # nominal experiments
    # ------------------------------------------------------------------
    def run_nominal_walk(self, distance: float, seed: int, repetition: int) -> dict[str, Any]:
        run_id = f"a1-walk-{distance:g}m-rep{repetition}-seed{seed:03d}"
        nominal = self.protocol["nominal"]
        tolerance = max(
            float(self.thresholds["walk_tolerance_min_m"]),
            float(self.thresholds["walk_tolerance_relative"]) * float(distance),
        )
        timeout_s = max(
            float(self.thresholds["walk_timeout_min_s"]),
            float(self.thresholds["walk_timeout_s_per_m"]) * float(distance),
        )
        simulation = build_simulation(self.robot, seed=seed)
        controller = build_controller(self.robot)
        router = SkillRouter([StandSkill(), WalkForwardSkill()])
        context = SkillContext(
            simulation=simulation,
            controller=controller,
            robot_config=self.robot,
            max_steps=int(round(120.0 / simulation.timestep)),
            seed=seed,
        )
        recorder = self._recorder(
            run_id,
            task=f"WalkForward {distance:g} m",
            seed=seed,
            condition="nominal",
            perturbation_type="nominal",
            perturbation_parameters={},
            thresholds={"distance_tolerance_m": tolerance, "timeout_s": timeout_s},
        )
        recorder.log_event("reset", {"state": simulation.reset(seed=seed).to_dict()})
        self._execute(
            router,
            context,
            recorder,
            "stand",
            {"duration_s": float(nominal["stand"]["stand_phase_s"])},
        )
        start_state = simulation.get_robot_state()
        result = self._execute(
            router,
            context,
            recorder,
            "walk_forward",
            {
                "target_distance_m": float(distance),
                "tolerance_m": tolerance,
                "speed_mps": float(nominal["walk_forward"]["speed_mps"]),
                "max_duration_s": timeout_s,
            },
        )
        final_state = simulation.get_robot_state()
        metrics, failure = self._walk_metrics(result, start_state, final_state, float(distance), tolerance)
        metrics["repetition"] = repetition
        simulation.close()
        return self._finish_run(
            recorder,
            run_id=run_id,
            skill="walk_forward",
            task=float(distance),
            condition="nominal",
            seed=seed,
            success=failure.ok,
            failure=failure,
            metrics=metrics,
        )

    def run_nominal_turn(self, angle_deg: float, seed: int, repetition: int) -> dict[str, Any]:
        run_id = f"a2-turn-{angle_deg:g}deg-rep{repetition}-seed{seed:03d}"
        nominal = self.protocol["nominal"]
        tolerance_deg = float(self.thresholds["turn_heading_tolerance_deg"])
        simulation = build_simulation(self.robot, seed=seed)
        controller = build_controller(self.robot)
        router = SkillRouter([StandSkill(), TurnSkill()])
        context = SkillContext(
            simulation=simulation,
            controller=controller,
            robot_config=self.robot,
            max_steps=int(round(120.0 / simulation.timestep)),
            seed=seed,
        )
        recorder = self._recorder(
            run_id,
            task=f"Turn {angle_deg:g} deg",
            seed=seed,
            condition="nominal",
            perturbation_type="nominal",
            perturbation_parameters={},
            thresholds={"heading_tolerance_deg": tolerance_deg},
        )
        recorder.log_event("reset", {"state": simulation.reset(seed=seed).to_dict()})
        self._execute(
            router,
            context,
            recorder,
            "stand",
            {"duration_s": float(nominal["stand"]["stand_phase_s"])},
        )
        start_state = simulation.get_robot_state()
        result = self._execute(
            router,
            context,
            recorder,
            "turn",
            {
                "target_angle_deg": float(angle_deg),
                "tolerance_deg": tolerance_deg,
                "yaw_rate_radps": float(nominal["turn"]["yaw_rate_radps"]),
                "max_duration_s": float(self.thresholds["turn_timeout_s"]),
            },
        )
        final_state = simulation.get_robot_state()
        metrics, failure = self._turn_metrics(result, start_state, final_state, float(angle_deg), tolerance_deg)
        metrics["repetition"] = repetition
        simulation.close()
        return self._finish_run(
            recorder,
            run_id=run_id,
            skill="turn",
            task=float(angle_deg),
            condition="nominal",
            seed=seed,
            success=failure.ok,
            failure=failure,
            metrics=metrics,
        )

    def run_nominal_stand(self, duration_s: float, seed: int, repetition: int) -> dict[str, Any]:
        run_id = f"a3-stand-{duration_s:g}s-rep{repetition}-seed{seed:03d}"
        simulation = build_simulation(self.robot, seed=seed)
        controller = build_controller(self.robot)
        router = SkillRouter([StandSkill()])
        context = SkillContext(
            simulation=simulation,
            controller=controller,
            robot_config=self.robot,
            max_steps=int(round((float(duration_s) + 10.0) / simulation.timestep)),
            seed=seed,
        )
        recorder = self._recorder(
            run_id,
            task=f"Stand {duration_s:g} s",
            seed=seed,
            condition="nominal",
            perturbation_type="nominal",
            perturbation_parameters={},
            thresholds={"duration_s": float(duration_s)},
        )
        recorder.log_event("reset", {"state": simulation.reset(seed=seed).to_dict()})
        result = self._execute(
            router, context, recorder, "stand", {"duration_s": float(duration_s)}
        )
        final_state = simulation.get_robot_state()
        fall = bool(result.metrics.get("fallen"))
        failure = classify_failure(
            status=result.status,
            fall=fall,
            finite=final_state.is_finite(),
            unstable=not final_state.standing,
            reason=result.reason,
        )
        metrics = {
            "duration_s": float(duration_s),
            "base_height_min_m": result.metrics.get("height_min_m"),
            "base_height_mean_m": result.metrics.get("height_mean_m"),
            "base_height_max_m": result.metrics.get("height_max_m"),
            "max_abs_roll_deg": result.metrics.get("max_abs_roll_deg"),
            "max_abs_pitch_deg": result.metrics.get("max_abs_pitch_deg"),
            "position_drift_m": result.metrics.get("base_drift_m"),
            "final_speed_mps": result.metrics.get("final_speed_mps"),
            "mean_speed_mps": result.metrics.get("mean_speed_mps"),
            "fall_detected": fall,
            "non_finite_state": not final_state.is_finite(),
            "skill_status": result.status.value,
            "failure_type": failure.failure_type.value,
            "failure_reason": failure.reason,
            "success": failure.ok,
            "repetition": repetition,
        }
        simulation.close()
        return self._finish_run(
            recorder,
            run_id=run_id,
            skill="stand",
            task=float(duration_s),
            condition="nominal",
            seed=seed,
            success=failure.ok,
            failure=failure,
            metrics=metrics,
        )

    def run_nominal_stop(self, command_speed: float, seed: int, repetition: int) -> dict[str, Any]:
        run_id = f"b-stop-{command_speed:g}mps-rep{repetition}-seed{seed:03d}"
        nominal = self.protocol["nominal"]["stop"]
        threshold = float(self.thresholds["stop_speed_threshold_mps"])
        window_s = float(self.thresholds["stop_window_s"])
        measurement_s = float(self.thresholds["stop_measurement_window_s"])
        simulation = build_simulation(self.robot, seed=seed)
        controller = build_controller(self.robot)
        recorder = self._recorder(
            run_id,
            task=f"Stop from {command_speed:g} m/s",
            seed=seed,
            condition=f"command_{command_speed:g}mps",
            perturbation_type="nominal",
            perturbation_parameters={"command_speed_mps": float(command_speed)},
            thresholds={
                "window_s": window_s,
                "threshold_mps": threshold,
                "measurement_window_s": measurement_s,
            },
        )
        recorder.log_event("reset", {"state": simulation.reset(seed=seed).to_dict()})
        dt = simulation.timestep
        window_steps = max(1, int(round(window_s / dt)))
        forward_command = np.array([float(command_speed), 0.0, 0.0], dtype=np.float64)
        zero_command = np.zeros(3, dtype=np.float64)

        def torque_for(command: np.ndarray) -> np.ndarray:
            return controller.compute_torques(
                joint_positions=simulation.joint_positions(),
                joint_velocities=simulation.joint_velocities(),
                quaternion=simulation.base_quaternion(),
                angular_velocity=simulation.base_angular_velocity(),
                command=command,
                dt=dt,
            )

        warmup_steps = max(1, int(round(float(nominal["warmup_s"]) / dt)))
        warmup_speeds: list[float] = []
        state = simulation.get_robot_state()
        for _ in range(warmup_steps):
            state = simulation.step(torque_for(forward_command))
            warmup_speeds.append(state.speed())
        recent = max(1, int(round(0.5 / dt)))
        velocity_before_stop = float(np.mean(warmup_speeds[-recent:]))

        stop_start_state = simulation.get_robot_state()
        forward_unit = np.array(
            [
                math.cos(yaw_rad(stop_start_state.base_orientation)),
                math.sin(yaw_rad(stop_start_state.base_orientation)),
            ]
        )
        trailing: deque[float] = deque(maxlen=window_steps)
        speeds: list[float] = []
        positions: list[float] = []
        fall = False
        status = SkillStatus.TIMEOUT
        time_to_threshold: float | None = None
        for _ in range(max(1, int(round(measurement_s / dt)))):
            state = simulation.step(torque_for(zero_command))
            speeds.append(state.speed())
            positions.append(float(horizontal_offset(stop_start_state, state) @ forward_unit))
            trailing.append(state.speed())
            if state.fallen:
                fall = True
                status = SkillStatus.UNSAFE
                break
            if (
                time_to_threshold is None
                and len(trailing) >= window_steps
                and float(np.mean(trailing)) <= threshold
            ):
                time_to_threshold = state.simulation_time - stop_start_state.simulation_time
                status = SkillStatus.SUCCESS
        residual_1s = speeds[: max(1, int(round(1.0 / dt)))]
        residual_2s = speeds[: max(1, int(round(2.0 / dt)))]
        sustained = bool(
            time_to_threshold is not None
            and len(trailing) >= window_steps
            and float(np.mean(trailing)) <= threshold
        )
        if status is SkillStatus.SUCCESS and not sustained:
            status = SkillStatus.TIMEOUT
        failure = classify_failure(
            status=status,
            fall=fall,
            finite=state.is_finite(),
            timeout=status is SkillStatus.TIMEOUT,
            failed_to_stop=not sustained,
            reason=None
            if sustained
            else "stop threshold not sustained within the measurement window",
        )
        metrics = {
            "command_speed_mps": float(command_speed),
            "velocity_before_stop_mps": velocity_before_stop,
            "time_to_stop_threshold_s": time_to_threshold,
            "distance_after_stop_command_m": positions[-1] if positions else 0.0,
            "residual_speed_mean_1s_mps": float(np.mean(residual_1s)) if residual_1s else None,
            "residual_speed_max_1s_mps": float(np.max(residual_1s)) if residual_1s else None,
            "residual_speed_mean_2s_mps": float(np.mean(residual_2s)) if residual_2s else None,
            "threshold_sustained": sustained,
            "window_s": window_s,
            "threshold_mps": threshold,
            "fall_detected": fall,
            "non_finite_state": not state.is_finite(),
            "skill_status": status.value,
            "failure_type": failure.failure_type.value,
            "failure_reason": failure.reason,
            "success": failure.ok,
            "repetition": repetition,
        }
        recorder.log_event(
            "threshold_crossing" if sustained else "threshold_not_reached",
            {"threshold_mps": threshold, "window_s": window_s, "time_to_threshold_s": time_to_threshold},
        )
        simulation.close()
        return self._finish_run(
            recorder,
            run_id=run_id,
            skill="stop",
            task=float(command_speed),
            condition=f"command_{command_speed:g}mps",
            seed=seed,
            success=failure.ok,
            failure=failure,
            metrics=metrics,
        )

    # ------------------------------------------------------------------
    # robustness campaign (one factor at a time)
    # ------------------------------------------------------------------
    def run_robustness(self, task_key: str, condition: str, seed: int) -> dict[str, Any]:
        robustness = self.protocol["robustness"]
        task_spec = robustness["tasks"][task_key]
        run_id = f"c-{task_key}-{condition}-seed{seed:03d}"
        simulation = build_simulation(self.robot, seed=seed)
        controller = build_controller(self.robot)
        perturbation_config = dict(self.protocol["perturbations"])
        perturbation_config["robot_mass_kg"] = simulation.total_mass()
        perturbation_config["push_trigger_s_range"] = robustness.get(
            "push_trigger_s_range_by_task", {}
        ).get(task_key, self.protocol["perturbations"]["push_trigger_s_range"])
        perturbation = sample_perturbation(
            condition,
            seed=seed,
            config=perturbation_config,
            num_joints=simulation.num_actuators,
        )
        push = push_spec_from(perturbation)
        proxy = DisturbanceProxy(simulation, push)
        tolerance = max(
            float(self.thresholds["walk_tolerance_min_m"]),
            float(self.thresholds["walk_tolerance_relative"])
            * float(task_spec.get("target_distance_m", 2.0)),
        )
        timeout_s = max(
            float(self.thresholds["walk_timeout_min_s"]),
            float(self.thresholds["walk_timeout_s_per_m"])
            * float(task_spec.get("target_distance_m", 2.0)),
        )
        recorder = self._recorder(
            run_id,
            task=task_key,
            seed=seed,
            condition=condition,
            perturbation_type=perturbation.kind.value,
            perturbation_parameters=perturbation.parameters,
            thresholds={
                "distance_tolerance_m": tolerance,
                "heading_tolerance_deg": float(self.thresholds["turn_heading_tolerance_deg"]),
                "stop_window_s": float(self.thresholds["stop_window_s"]),
                "stop_speed_threshold_mps": float(self.thresholds["stop_speed_threshold_mps"]),
            },
        )
        recorder.log_event("reset", {"state": simulation.reset(seed=seed).to_dict()})
        applied = apply_initial_perturbation(simulation, perturbation)
        recorder.log_event(
            "perturbation_applied",
            {
                "type": perturbation.kind.value,
                "parameters": applied,
                "sim_time": simulation.simulation_time,
                "robot_mass_kg": simulation.total_mass(),
                "friction": simulation.geom_friction_summary(),
            },
        )
        if push is not None:
            proxy.arm_push(simulation.simulation_time + push.trigger_sim_time)
        context = SkillContext(
            simulation=proxy,
            controller=controller,
            robot_config=self.robot,
            max_steps=int(round(120.0 / simulation.timestep)),
            seed=seed,
        )
        router = SkillRouter([StandSkill(), WalkForwardSkill(), TurnSkill(), StopSkill()])
        start_state = proxy.get_robot_state()
        task_start_time = start_state.simulation_time
        skill_name = str(task_spec["skill"])
        extra: dict[str, Any] = {}
        if task_key == "walk_forward_2m":
            result = self._execute(
                router,
                context,
                recorder,
                "walk_forward",
                {
                    "target_distance_m": float(task_spec["target_distance_m"]),
                    "tolerance_m": tolerance,
                    "speed_mps": float(self.protocol["nominal"]["walk_forward"]["speed_mps"]),
                    "max_duration_s": timeout_s,
                },
            )
            final_state = proxy.get_robot_state()
            metrics, failure = self._walk_metrics(
                result, start_state, final_state, float(task_spec["target_distance_m"]), tolerance
            )
        elif task_key == "turn_45":
            tolerance_deg = float(self.thresholds["turn_heading_tolerance_deg"])
            result = self._execute(
                router,
                context,
                recorder,
                "turn",
                {
                    "target_angle_deg": float(task_spec["target_angle_deg"]),
                    "tolerance_deg": tolerance_deg,
                    "yaw_rate_radps": float(self.protocol["nominal"]["turn"]["yaw_rate_radps"]),
                    "max_duration_s": float(self.thresholds["turn_timeout_s"]),
                },
            )
            final_state = proxy.get_robot_state()
            metrics, failure = self._turn_metrics(
                result, start_state, final_state, float(task_spec["target_angle_deg"]), tolerance_deg
            )
        elif task_key == "walk_stop_2m":
            walk_result = self._execute(
                router,
                context,
                recorder,
                "walk_forward",
                {
                    "target_distance_m": float(task_spec["target_distance_m"]),
                    "tolerance_m": tolerance,
                    "speed_mps": float(self.protocol["nominal"]["walk_forward"]["speed_mps"]),
                    "max_duration_s": timeout_s,
                },
            )
            stop_result = self._execute(
                router,
                context,
                recorder,
                "stop",
                {
                    "window_s": float(self.thresholds["stop_window_s"]),
                    "speed_threshold_mps": float(self.thresholds["stop_speed_threshold_mps"]),
                    "max_duration_s": float(self.thresholds["stop_max_duration_s"]),
                },
            )
            final_state = proxy.get_robot_state()
            metrics, walk_failure = self._walk_metrics(
                walk_result, start_state, final_state, float(task_spec["target_distance_m"]), tolerance
            )
            stop_ok = stop_result.status is SkillStatus.SUCCESS
            fall = bool(walk_result.metrics.get("fallen") or stop_result.metrics.get("fallen"))
            failure = classify_failure(
                status=stop_result.status if walk_failure.ok else walk_result.status,
                fall=fall,
                finite=final_state.is_finite(),
                timeout=(walk_result.status is SkillStatus.TIMEOUT)
                or (stop_result.status is SkillStatus.TIMEOUT),
                distance_error=metrics["absolute_distance_error_m"],
                distance_tolerance=tolerance,
                failed_to_stop=not stop_ok,
                reason=stop_result.reason or walk_failure.reason,
            )
            metrics.update(
                {
                    "stop_status": stop_result.status.value,
                    "stop_final_window_mean_speed_mps": stop_result.metrics.get(
                        "final_window_mean_speed_mps"
                    ),
                    "stop_threshold_mps": self.thresholds["stop_speed_threshold_mps"],
                    "stop_window_s": self.thresholds["stop_window_s"],
                    "success": failure.ok,
                    "failure_type": failure.failure_type.value,
                    "failure_reason": failure.reason,
                }
            )
        else:  # pragma: no cover - protocol validation keeps this unreachable
            raise ValueError(f"unknown robustness task: {task_key}")

        for event in proxy.events:
            payload = {key: value for key, value in event.items() if key != "event"}
            recorder.log_event(str(event["event"]), payload)
        proxy.release()
        extra["task_key"] = task_key
        extra["condition"] = condition
        extra["perturbation"] = perturbation.to_dict()
        extra["robot_mass_kg"] = simulation.total_mass()
        extra["friction"] = simulation.geom_friction_summary()
        extra["task_wall_time_s"] = final_state.simulation_time - task_start_time
        metrics.update(extra)
        simulation.close()
        return self._finish_run(
            recorder,
            run_id=run_id,
            skill=skill_name,
            task=task_key,
            condition=condition,
            seed=seed,
            success=failure.ok,
            failure=failure,
            metrics=metrics,
        )

    # ------------------------------------------------------------------
    # campaign drivers
    # ------------------------------------------------------------------
    def run_nominal_suite(self) -> None:
        nominal = self.protocol["nominal"]
        repetitions = int(nominal["walk_forward"]["repetitions"])
        for distance in nominal["walk_forward"]["distances_m"]:
            for repetition in range(repetitions):
                self.run_nominal_walk(float(distance), repetition, repetition)
        repetitions = int(nominal["turn"]["repetitions"])
        for angle in nominal["turn"]["angles_deg"]:
            for repetition in range(repetitions):
                self.run_nominal_turn(float(angle), repetition, repetition)
        repetitions = int(nominal["stand"]["repetitions"])
        for duration in nominal["stand"]["durations_s"]:
            for repetition in range(repetitions):
                self.run_nominal_stand(float(duration), repetition, repetition)
        repetitions = int(nominal["stop"]["repetitions"])
        for speed in nominal["stop"]["command_speeds_mps"]:
            for repetition in range(repetitions):
                self.run_nominal_stop(float(speed), repetition, repetition)

    def run_robustness_suite(self) -> None:
        robustness = self.protocol["robustness"]
        for task_key in robustness["tasks"]:
            for condition in robustness["conditions"]:
                for seed in robustness["seeds"]:
                    self.run_robustness(task_key, condition, int(seed))

    # ------------------------------------------------------------------
    # aggregation
    # ------------------------------------------------------------------
    @staticmethod
    def _group(records: list[dict[str, Any]], metric_keys: tuple[str, ...]) -> dict[str, Any]:
        successes = sum(1 for record in records if record["success"])
        failure_counts: dict[str, int] = {}
        for record in records:
            if not record["success"]:
                failure_counts[record["failure_type"]] = (
                    failure_counts.get(record["failure_type"], 0) + 1
                )
        metrics = {
            key: summarize(
                [
                    record["metrics"][key]
                    for record in records
                    if record["metrics"].get(key) is not None
                ]
            )
            for key in metric_keys
        }
        determinism_inputs = [
            [record["metrics"][key] for record in records if record["metrics"].get(key) is not None]
            for key in metric_keys
            if any(record["metrics"].get(key) is not None for record in records)
        ]
        deterministic = (
            all(is_deterministic(values) for values in determinism_inputs)
            if determinism_inputs
            else True
        )
        return {
            "n": len(records),
            "successes": successes,
            "success_rate": (successes / len(records)) if records else None,
            "deterministic_repetition": deterministic,
            "failure_counts": failure_counts,
            "metrics": metrics,
        }

    def summarize(self) -> dict[str, Any]:
        environment = EnvironmentInfo.collect()
        nominal_map: dict[str, Any] = {}
        # Only the numeric-task nominal experiments; robustness records use task
        # keys such as "walk_forward_2m" and are aggregated separately.
        walk_records = [
            r
            for r in self.results
            if r["skill"] == "walk_forward"
            and r["condition"] == "nominal"
            and isinstance(r["task"], (int, float))
        ]
        nominal_map["walk_forward"] = {
            f"{float(target):g}": self._group(
                [r for r in walk_records if abs(float(r["task"]) - float(target)) < 1e-9],
                (
                    "forward_displacement_m",
                    "absolute_distance_error_m",
                    "lateral_drift_m",
                    "heading_error_deg",
                    "completion_sim_time_s",
                    "mean_speed_mps",
                    "residual_speed_mps",
                ),
            )
            for target in (self.protocol["nominal"]["walk_forward"]["distances_m"] if self.campaign == "final" else sorted({float(r["task"]) for r in walk_records}))
        }
        turn_records = [
            r
            for r in self.results
            if r["skill"] == "turn"
            and r["condition"] == "nominal"
            and isinstance(r["task"], (int, float))
        ]
        nominal_map["turn"] = {
            f"{float(angle):g}": self._group(
                [r for r in turn_records if abs(float(r["task"]) - float(angle)) < 1e-9],
                (
                    "actual_yaw_change_deg",
                    "absolute_heading_error_deg",
                    "translation_drift_m",
                    "completion_sim_time_s",
                    "residual_speed_mps",
                ),
            )
            for angle in (self.protocol["nominal"]["turn"]["angles_deg"] if self.campaign == "final" else sorted({float(r["task"]) for r in turn_records}))
        }
        stand_records = [
            r
            for r in self.results
            if r["skill"] == "stand"
            and r["condition"] == "nominal"
            and isinstance(r["task"], (int, float))
        ]
        nominal_map["stand"] = {
            f"{float(duration):g}": self._group(
                [r for r in stand_records if abs(float(r["task"]) - float(duration)) < 1e-9],
                (
                    "base_height_mean_m",
                    "base_height_min_m",
                    "max_abs_roll_deg",
                    "max_abs_pitch_deg",
                    "position_drift_m",
                    "mean_speed_mps",
                ),
            )
            for duration in (self.protocol["nominal"]["stand"]["durations_s"] if self.campaign == "final" else sorted({float(r["task"]) for r in stand_records}))
        }
        stop_records = [r for r in self.results if r["skill"] == "stop" and r["condition"].startswith("command_")]
        nominal_map["stop"] = {
            f"{float(speed):g}": self._group(
                [r for r in stop_records if abs(float(r["task"]) - float(speed)) < 1e-9],
                (
                    "velocity_before_stop_mps",
                    "time_to_stop_threshold_s",
                    "distance_after_stop_command_m",
                    "residual_speed_mean_1s_mps",
                    "residual_speed_max_1s_mps",
                    "residual_speed_mean_2s_mps",
                ),
            )
            for speed in (self.protocol["nominal"]["stop"]["command_speeds_mps"] if self.campaign == "final" else sorted({float(r["task"]) for r in stop_records}))
        }

        robustness_map: dict[str, Any] = {}
        for task_key in self.protocol["robustness"]["tasks"]:
            robustness_map[task_key] = {}
            for condition in self.protocol["robustness"]["conditions"]:
                records = [
                    r for r in self.results if r["condition"] == condition and r["metrics"].get("task_key") == task_key
                ]
                metric_keys = (
                    "forward_displacement_m",
                    "absolute_distance_error_m",
                    "lateral_drift_m",
                    "heading_error_deg",
                    "completion_sim_time_s",
                )
                if task_key == "turn_45":
                    metric_keys = (
                        "actual_yaw_change_deg",
                        "absolute_heading_error_deg",
                        "translation_drift_m",
                        "completion_sim_time_s",
                    )
                robustness_map[task_key][condition] = self._group(records, metric_keys)

        failures = [
            {
                "run_id": record["run_id"],
                "skill": record["skill"],
                "task": record["task"],
                "condition": record["condition"],
                "seed": record["seed"],
                "failure_type": record["failure_type"],
                "failure_reason": record["failure_reason"],
            }
            for record in self.results
            if not record["success"]
        ]
        failure_taxonomy: dict[str, int] = {}
        for record in self.results:
            failure_taxonomy[record["failure_type"]] = failure_taxonomy.get(record["failure_type"], 0) + 1
        return {
            "experiment_id": EXPERIMENT_ID,
            "campaign": self.campaign,
            "protocol_version": self.protocol.get("protocol_version"),
            "protocol_path": self.protocol_path,
            "protocol_sha256": self.protocol_sha256,
            "source_commit": environment.git_commit,
            "generated_at": utc_timestamp(),
            "environment": environment.to_dict(),
            "artifact_path": str(
                Path("artifacts") / EXPERIMENT_ID / self.campaign
            ),
            "runs_total": len(self.results),
            "nominal": nominal_map,
            "robustness": robustness_map,
            "failure_taxonomy": failure_taxonomy,
            "failures": failures,
        }

    # ------------------------------------------------------------------
    # outputs
    # ------------------------------------------------------------------
    def write_outputs(
        self,
        *,
        summary_path: str | Path,
        competence_path: str | Path | None = None,
    ) -> dict[str, Any]:
        summary = self.summarize()
        summary_path = Path(summary_path)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if competence_path is not None:
            competence = build_competence_map(
                protocol=self.protocol,
                summary=summary,
                source_commit=summary["source_commit"],
            )
            validate_competence_map(competence)
            competence_path = Path(competence_path)
            competence_path.parent.mkdir(parents=True, exist_ok=True)
            competence_path.write_text(
                json.dumps(competence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        return summary
