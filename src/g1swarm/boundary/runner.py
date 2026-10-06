"""Phase 1.2 failure-boundary campaign runner.

One-factor-at-a-time boundary searches over five parameters, each run recorded
as evidence (manifest/metrics/events) under
``artifacts/g1_failure_boundary_001/<campaign>/<run_id>/``:

* A_distance      - WalkForward target distance (body-frame goal)
* B_push          - lateral push magnitude, fixed direction/duration, seeded trigger
* C_friction      - sliding friction (decreasing)
* D_joint         - initial joint position sigma (seeded, limit-respecting)
* E_yaw           - initial yaw offset (world-frame 2 m goal, not the Turn skill)

No controller parameter, threshold or policy weight is modified here.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from ..characterization.kinematics import (
    forward_lateral,
    horizontal_offset,
    roll_pitch_deg,
    wrap_angle_deg,
    yaw_deg,
    yaw_rad,
)
from ..characterization.perturbations import DisturbanceProxy, PushSpec
from ..config import build_controller, build_simulation, load_yaml
from ..evidence import EnvironmentInfo, RunManifest, RunRecorder, utc_timestamp
from ..paths import artifacts_dir
from ..skills import SkillContext, SkillRequest, SkillRouter, WalkForwardSkill
from .envelope import evaluate_walk_task, failure_type_from_violations, physical_success
from .perturbation_guard import clip_joint_offsets
from .risk import RiskEvidence, risk_label
from .search import BoundarySearch, Observation

EXPERIMENT_ID = "g1_failure_boundary_001"


class BoundaryRunner:
    def __init__(self, protocol_path: str | Path, *, campaign: str) -> None:
        if campaign not in {"pilot", "final"}:
            raise ValueError("campaign must be 'pilot' or 'final'")
        self.protocol_path = str(protocol_path)
        self.protocol = load_yaml(protocol_path)
        self.campaign = campaign
        self.robot = load_yaml(self.protocol["robot_config"])
        self.thresholds = self.protocol["thresholds"]
        self.sampling = self.protocol["sampling"]
        self.protocol_sha256 = hashlib.sha256(Path(self.protocol_path).read_bytes()).hexdigest()
        self.records: list[dict[str, Any]] = []
        self.searches: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # evidence
    # ------------------------------------------------------------------
    def _recorder(
        self,
        run_id: str,
        *,
        spec_key: str,
        value: float,
        seed: int,
        phase: str,
        iteration: int,
        bracket_state: dict[str, Any] | None,
        perturbation_type: str,
        perturbation_parameters: dict[str, Any],
    ) -> RunRecorder:
        provenance = self.protocol["provenance"]
        manifest = RunManifest(
            experiment_id=EXPERIMENT_ID,
            run_id=run_id,
            task=f"{spec_key} = {value:g}",
            config={
                "protocol_path": self.protocol_path,
                "protocol_version": self.protocol.get("protocol_version"),
                "protocol_sha256": self.protocol_sha256,
                "experiment": spec_key,
                "parameter": self.protocol["experiments"][spec_key]["parameter"],
                "value": value,
                "phase": phase,
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
            thresholds={
                "nominal": self.thresholds["envelopes"]["nominal"],
                "strict": self.thresholds["envelopes"]["strict"],
            },
            search_campaign=self.campaign,
            search_parameter=self.protocol["experiments"][spec_key]["parameter"],
            search_iteration=iteration,
            bracket_state=bracket_state,
        )
        return RunRecorder(
            EXPERIMENT_ID,
            f"{self.campaign}/{run_id}",
            root=artifacts_dir(),
            manifest=manifest,
        )

    # ------------------------------------------------------------------
    # one run
    # ------------------------------------------------------------------
    def run_case(
        self,
        spec_key: str,
        value: float,
        seed: int,
        *,
        phase: str,
        iteration: int,
        bracket_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = self.protocol["experiments"][spec_key]
        task_spec = spec["task"]
        run_id = f"{spec_key}-{phase}-{value:g}-seed{seed:03d}"
        simulation = build_simulation(self.robot, seed=seed)
        controller = build_controller(self.robot)
        proxy: DisturbanceProxy | None = None
        perturbation_type = "nominal"
        perturbation_parameters: dict[str, Any] = {}
        recorder = self._recorder(
            run_id,
            spec_key=spec_key,
            value=value,
            seed=seed,
            phase=phase,
            iteration=iteration,
            bracket_state=bracket_state,
            perturbation_type=perturbation_type,
            perturbation_parameters=perturbation_parameters,
        )
        recorder.log_event(
            "boundary_search_decision",
            {
                "experiment": spec_key,
                "value": value,
                "phase": phase,
                "iteration": iteration,
                "bracket_state": bracket_state,
            },
        )
        state = simulation.reset(seed=seed)
        recorder.log_event("reset", {"state": state.to_dict()})

        target_distance = float(task_spec.get("target_distance_m", 2.0))
        if spec_key == "B_push":
            rng = np.random.default_rng(seed)
            low, high = self.thresholds["push"]["trigger_s_range"]
            trigger = float(rng.uniform(low, high))
            proxy = DisturbanceProxy(
                simulation,
                PushSpec(
                    force_n=float(value),
                    direction=tuple(self.thresholds["push"]["direction"]),
                    duration_s=float(self.thresholds["push"]["duration_s"]),
                    trigger_sim_time=trigger,
                ),
            )
            perturbation_type = "push"
            perturbation_parameters = {
                "force_n": float(value),
                "direction": list(self.thresholds["push"]["direction"]),
                "duration_s": float(self.thresholds["push"]["duration_s"]),
                "trigger_s": trigger,
            }
        elif spec_key == "C_friction":
            simulation.set_all_geom_friction(float(value))
            perturbation_type = "friction"
            perturbation_parameters = {
                "friction_slide": float(value),
                "friction_summary": simulation.geom_friction_summary(),
            }
        elif spec_key == "D_joint":
            rng = np.random.default_rng(seed)
            offsets = rng.normal(0.0, float(value), size=simulation.num_actuators)
            velocity_offsets = rng.normal(
                0.0,
                float(self.thresholds["joint"]["velocity_std_radps"]),
                size=simulation.num_actuators,
            )
            positions = simulation.joint_positions()
            low, high = simulation.joint_limits()
            clipped_offsets, clipped_count = clip_joint_offsets(positions, offsets, low, high)
            simulation.offset_joint_state(
                position_offsets=clipped_offsets, velocity_offsets=velocity_offsets
            )
            perturbation_type = "joint"
            perturbation_parameters = {
                "position_sigma_rad": float(value),
                "velocity_std_radps": float(self.thresholds["joint"]["velocity_std_radps"]),
                "max_abs_position_offset_rad": float(np.max(np.abs(clipped_offsets))),
                "limit_clipped_count": clipped_count,
            }
        elif spec_key == "E_yaw":
            simulation.set_base_state(yaw_rad=math.radians(float(value)))
            perturbation_type = "yaw"
            perturbation_parameters = {"initial_yaw_offset_deg": float(value)}

        if perturbation_type != "nominal":
            recorder.log_event(
                "perturbation_applied",
                {
                    "type": perturbation_type,
                    "parameters": perturbation_parameters,
                    "sim_time": simulation.simulation_time,
                },
            )

        router = SkillRouter([WalkForwardSkill()])
        simulation_view = proxy if proxy is not None else simulation
        context = SkillContext(
            simulation=simulation_view,
            controller=controller,
            robot_config=self.robot,
            max_steps=int(round(600.0 / simulation.timestep)),
            seed=seed,
        )
        walk_target = float(value) if spec_key == "A_distance" else target_distance
        walk_timeout = max(
            float(self.thresholds["walk"]["timeout_min_s"]),
            float(self.thresholds["walk"]["timeout_s_per_m"]) * walk_target,
        )
        start_state = simulation_view.get_robot_state()
        recorder.log_event(
            "skill_start",
            {
                "skill": "walk_forward",
                "target_m": walk_target,
                "sim_time": start_state.simulation_time,
            },
        )
        result = router.execute(
            SkillRequest(
                "walk_forward",
                {
                    "target_distance_m": walk_target,
                    "tolerance_m": float(self.thresholds["walk"]["tolerance_min_m"]),
                    "speed_mps": float(self.thresholds["walk"]["speed_mps"]),
                    "max_duration_s": walk_timeout,
                },
            ),
            context,
        )
        final_state = simulation_view.get_robot_state()
        offset = horizontal_offset(start_state, final_state)
        forward, lateral = forward_lateral(offset, yaw_rad(start_state.base_orientation))
        heading_error = wrap_angle_deg(
            yaw_deg(final_state.base_orientation) - yaw_deg(start_state.base_orientation)
        )
        completion_time = final_state.simulation_time - start_state.simulation_time
        if spec_key == "E_yaw":
            # World-frame goal: reaching (2 m, 0) regardless of the initial yaw.
            forward = float(offset[0])
            lateral = float(offset[1])
            heading_error = wrap_angle_deg(yaw_deg(final_state.base_orientation))
            walk_target = target_distance
        roll, pitch = roll_pitch_deg(final_state.base_orientation)
        metrics: dict[str, Any] = {
            "target_distance_m": walk_target,
            "forward_displacement_m": forward,
            "absolute_distance_error_m": abs(forward - walk_target),
            "lateral_drift_m": lateral,
            "heading_error_deg": heading_error,
            "completion_sim_time_s": completion_time,
            "completion_wall_time_s": result.duration_s,
            "mean_speed_mps": (forward / completion_time) if completion_time > 0 else None,
            "residual_speed_mps": final_state.speed(),
            "max_abs_roll_deg": abs(roll),
            "max_abs_pitch_deg": abs(pitch),
            "fallen": bool(result.metrics.get("fallen")),
            "skill_status": result.status.value,
            "skill_reason": result.reason,
            "perturbation_type": perturbation_type,
            "perturbation_parameters": perturbation_parameters,
        }
        physical = physical_success(
            fallen=metrics["fallen"],
            finite=final_state.is_finite(),
            skill_status=result.status.value,
            simulation_completed=True,
        )
        evaluation = evaluate_walk_task(metrics, walk_target, physical=physical)
        metrics.update(evaluation)
        if not physical:
            metrics["failure_type"] = "FALL" if metrics["fallen"] else "UNKNOWN_FAILURE"
            metrics["failure_reason"] = result.reason or "physical failure"
        elif not evaluation["task_success"]:
            metrics["failure_type"] = failure_type_from_violations(evaluation["task_violations"])
            metrics["failure_reason"] = "task envelope violated: " + ", ".join(
                evaluation["task_violations"]
            )
        else:
            metrics["failure_type"] = "SUCCESS"
            metrics["failure_reason"] = None
        recorder.log_event(
            "skill_end",
            {
                "skill": "walk_forward",
                "status": result.status.value,
                "forward_displacement_m": forward,
                "lateral_drift_m": lateral,
                "heading_error_deg": heading_error,
                "physical_success": physical,
                "task_success": evaluation["task_success"],
            },
        )
        if not evaluation["task_success"] and physical:
            recorder.log_event(
                "task_envelope_violation",
                {
                    "violations": evaluation["task_violations"],
                    "nominal": evaluation["nominal_envelope"],
                    "strict": evaluation["strict_envelope"],
                },
            )
        if not physical:
            recorder.log_event(
                "physical_failure",
                {
                    "skill_status": result.status.value,
                    "fallen": metrics["fallen"],
                    "reason": result.reason,
                },
            )
        recorder.finish(
            {
                "status": metrics["failure_type"],
                "physical_success": physical,
                "task_success": evaluation["task_success"],
            },
            metrics,
        )
        if proxy is not None:
            for event in proxy.events:
                payload = {key: item for key, item in event.items() if key != "event"}
                recorder.log_event(str(event["event"]), payload)
            proxy.release()
        simulation.close()
        record = {
            "run_id": run_id,
            "experiment": spec_key,
            "value": float(value),
            "seed": seed,
            "phase": phase,
            "metrics": metrics,
        }
        self.records.append(record)
        return record

    # ------------------------------------------------------------------
    # aggregation
    # ------------------------------------------------------------------
    def evaluate_point(
        self,
        spec_key: str,
        value: float,
        *,
        phase: str,
        seeds: list[int],
        iteration: int = 0,
        bracket_state: dict[str, Any] | None = None,
    ) -> Observation:
        records = [
            self.run_case(
                spec_key,
                value,
                seed,
                phase=phase,
                iteration=iteration,
                bracket_state=bracket_state,
            )
            for seed in seeds
        ]
        physical = sum(1 for record in records if record["metrics"]["physical_success"])
        task = sum(1 for record in records if record["metrics"]["task_success"])
        failure_counts: dict[str, int] = {}
        for record in records:
            if not record["metrics"]["task_success"]:
                key = str(record["metrics"]["failure_type"])
                failure_counts[key] = failure_counts.get(key, 0) + 1
        key_metrics = (
            "absolute_distance_error_m",
            "lateral_drift_m",
            "heading_error_deg",
            "completion_sim_time_s",
            "forward_displacement_m",
        )
        vectors = {
            tuple(round(float(record["metrics"][key]), 12) for key in key_metrics)
            for record in records
        }
        deterministic = len(vectors) == 1
        metrics_summary: dict[str, Any] = {
            "strict_violation_rate": (
                sum(1 for record in records if record["metrics"]["strict_violation"]) / len(records)
                if records
                else 0.0
            ),
            "mean_lateral_drift_m": float(
                np.mean([record["metrics"]["lateral_drift_m"] for record in records])
            ),
            "mean_heading_error_deg": float(
                np.mean([record["metrics"]["heading_error_deg"] for record in records])
            ),
            "mean_completion_sim_time_s": float(
                np.mean([record["metrics"]["completion_sim_time_s"] for record in records])
            ),
            "mean_mean_speed_mps": float(
                np.mean([record["metrics"]["mean_speed_mps"] or 0.0 for record in records])
            ),
        }
        return Observation(
            value=float(value),
            n_runs=len(records),
            physical_successes=physical,
            task_successes=task,
            deterministic=deterministic,
            failure_counts=failure_counts,
            metrics=metrics_summary,
            run_ids=tuple(record["run_id"] for record in records),
        )

    def _seeds_for(self, spec: dict[str, Any], *, phase: str, zone: str | None = None) -> list[int]:
        deterministic = bool(spec.get("deterministic", False))
        if phase == "exploration":
            count = int(
                self.sampling["exploration_seeds_deterministic"]
                if deterministic
                else self.sampling["exploration_seeds_stochastic"]
            )
            return list(range(count))
        if deterministic:
            count = int(self.sampling["final_runs_per_point"]["deterministic"])
        else:
            if zone is None:
                raise ValueError("zone is required for stochastic final sampling")
            count = int(self.sampling["final_runs_per_point"][zone])
        available = list(self.sampling["final_seeds"])
        if count > len(available):
            raise ValueError("final sample plan exceeds available seeds")
        return available[:count]

    # ------------------------------------------------------------------
    # campaigns
    # ------------------------------------------------------------------
    def run_pilot(self) -> None:
        for spec_key, value in self.protocol["pilot_points"].items():
            spec = self.protocol["experiments"][spec_key]
            self.evaluate_point(
                spec_key,
                float(value),
                phase="pilot",
                seeds=self._seeds_for(spec, phase="exploration"),
            )

    def run_experiment(self, spec_key: str) -> dict[str, Any]:
        spec = self.protocol["experiments"][spec_key]
        search = BoundarySearch(
            parameter=spec["parameter"],
            safe_start=float(spec["safe_start"]),
            candidates=[float(value) for value in spec["candidates"]],
            direction=spec["direction"],
            max_evaluations=int(spec.get("max_evaluations", 16)),
            refinement_rounds=int(spec.get("refinement_rounds", 3)),
            resolution=float(spec.get("resolution", 0.0)),
        )

        def evaluate(value: float, decision: str) -> Observation:
            return self.evaluate_point(
                spec_key,
                value,
                phase="exploration",
                seeds=self._seeds_for(spec, phase="exploration"),
            )

        result = search.run(evaluate)
        by_value = {round(observation.value, 9): observation for observation in result.observations}
        final_points: list[float] = [float(spec["safe_start"])]
        if result.bracket is not None:
            low, high = result.bracket
            final_points.append(0.5 * (low + high))
            final_points.append(low if spec["direction"] == "increase" else high)
            final_points.append(high if spec["direction"] == "increase" else low)
        elif result.boundary_estimate is not None:
            final_points.append(result.boundary_estimate)
        deduped: list[float] = []
        for value in final_points:
            if all(abs(value - existing) > 1e-9 for existing in deduped):
                deduped.append(round(float(value), 6))
        final_observations: list[dict[str, Any]] = []
        for value in deduped:
            exploration = by_value.get(round(value, 9))
            zone = exploration.zone if exploration is not None else "transition"
            observation = self.evaluate_point(
                spec_key,
                value,
                phase="final",
                seeds=self._seeds_for(spec, phase="final", zone=zone),
            )
            risk = risk_label(
                RiskEvidence(
                    n_runs=observation.n_runs,
                    deterministic=observation.deterministic,
                    physical_success_rate=observation.physical_success_rate,
                    task_success_rate=observation.task_success_rate,
                    strict_violation_rate=float(observation.metrics.get("strict_violation_rate", 0.0)),
                    failure_counts=dict(observation.failure_counts),
                )
            )
            entry = observation.to_dict()
            entry["risk"] = risk.value
            final_observations.append(entry)
        payload = {"spec": spec, "search": result.to_dict(), "final": final_observations}
        self.searches[spec_key] = payload
        return payload

    def run_final(self) -> None:
        for spec_key in self.protocol["experiments"]:
            self.run_experiment(spec_key)

    # ------------------------------------------------------------------
    # outputs
    # ------------------------------------------------------------------
    def summarize(self) -> dict[str, Any]:
        environment = EnvironmentInfo.collect()
        physical = sum(1 for record in self.records if record["metrics"]["physical_success"])
        task = sum(1 for record in self.records if record["metrics"]["task_success"])
        taxonomy: dict[str, int] = {}
        for record in self.records:
            key = (
                "SUCCESS"
                if record["metrics"]["task_success"]
                else str(record["metrics"]["failure_type"])
            )
            taxonomy[key] = taxonomy.get(key, 0) + 1
        failures = [
            {
                "run_id": record["run_id"],
                "experiment": record["experiment"],
                "value": record["value"],
                "seed": record["seed"],
                "physical_success": record["metrics"]["physical_success"],
                "task_success": record["metrics"]["task_success"],
                "failure_type": record["metrics"]["failure_type"],
                "failure_reason": record["metrics"]["failure_reason"],
            }
            for record in self.records
            if not record["metrics"]["task_success"]
        ]
        return {
            "experiment_id": EXPERIMENT_ID,
            "campaign": self.campaign,
            "protocol_path": self.protocol_path,
            "protocol_sha256": self.protocol_sha256,
            "source_commit": environment.git_commit,
            "generated_at": utc_timestamp(),
            "environment": environment.to_dict(),
            "artifact_path": str(Path("artifacts") / EXPERIMENT_ID / self.campaign),
            "runs_total": len(self.records),
            "physical_successes": physical,
            "task_successes": task,
            "physical_success_rate": (physical / len(self.records)) if self.records else None,
            "task_success_rate": (task / len(self.records)) if self.records else None,
            "failure_taxonomy": taxonomy,
            "failures": failures,
            "experiments": self.searches,
        }

    def write_outputs(self, *, summary_path: str | Path) -> dict[str, Any]:
        summary = self.summarize()
        summary_path = Path(summary_path)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return summary
