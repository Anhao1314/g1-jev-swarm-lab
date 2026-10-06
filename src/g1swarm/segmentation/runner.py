"""Phase 1.2b: walk-distance boundary refinement and segmentation study.

Treatments (all under the Phase 1.2 nominal warehouse task envelope, mission
frame fixed at mission start):

* ``direct_long``            - one WalkForward(total) invocation
* ``segmented_reset``        - 2 m WalkForward segments + Stop, standard skill
                               lifecycle (each Walk invocation resets the LSTM)
* ``segmented_continuous``   - same segmentation, but ``reset_memory=False`` so
                               the recurrent policy state stays continuous
* ``segmented_state_aware``  - continuous memory + the remaining mission-axis
                               distance recomputed before each segment (no yaw
                               or lateral correction of any kind)

No policy weight, gain, action scale or envelope threshold is modified.
"""

from __future__ import annotations

import hashlib
import math
import json
import time
from pathlib import Path
from typing import Any

from ..boundary.envelope import evaluate_walk_task
from ..characterization.kinematics import wrap_angle_deg
from ..config import build_controller, build_simulation, load_yaml
from ..evidence import EnvironmentInfo, RunManifest, RunRecorder, utc_timestamp
from ..paths import artifacts_dir
from ..skills import SkillContext, SkillRequest, SkillRouter, StopSkill, WalkForwardSkill
from .mission import (
    MissionFrame,
    PathLengthProxy,
    build_segment_schedule,
    build_state_aware_schedule,
    drift_per_meter,
    heading_error_per_meter,
)

EXPERIMENT_ID = "g1_distance_segmentation_001"
TREATMENTS = (
    "direct_long",
    "segmented_reset",
    "segmented_continuous",
    "segmented_state_aware",
)
MEMORY_CONTINUOUS = {"segmented_continuous", "segmented_state_aware"}


class SegmentationRunner:
    def __init__(self, protocol_path: str | Path, *, campaign: str) -> None:
        if campaign not in {"pilot", "final"}:
            raise ValueError("campaign must be 'pilot' or 'final'")
        self.protocol_path = str(protocol_path)
        self.protocol = load_yaml(protocol_path)
        self.campaign = campaign
        self.robot = load_yaml(self.protocol["robot_config"])
        self.thresholds = self.protocol["thresholds"]
        self.protocol_sha256 = hashlib.sha256(Path(self.protocol_path).read_bytes()).hexdigest()
        self.records: list[dict[str, Any]] = []

    def _recorder(
        self,
        run_id: str,
        *,
        treatment: str,
        total_distance: float,
        phase: str,
        seed: int,
    ) -> RunRecorder:
        provenance = self.protocol["provenance"]
        manifest = RunManifest(
            experiment_id=EXPERIMENT_ID,
            run_id=run_id,
            task=f"{treatment} {total_distance:g} m",
            config={
                "protocol_path": self.protocol_path,
                "protocol_version": self.protocol.get("protocol_version"),
                "protocol_sha256": self.protocol_sha256,
                "treatment": treatment,
                "total_distance_m": total_distance,
                "segment_length_m": float(self.protocol["segmentation"]["segment_length_m"]),
                "memory_continuous": treatment in MEMORY_CONTINUOUS,
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
            perturbation_type="nominal",
            perturbation_parameters={"treatment": treatment},
            thresholds={
                "walk": self.thresholds["walk"],
                "nominal_envelope": self.thresholds["envelopes"]["nominal"],
                "strict_envelope": self.thresholds["envelopes"]["strict"],
            },
            search_campaign=self.campaign,
            search_parameter=f"treatment:{treatment}",
        )
        return RunRecorder(
            EXPERIMENT_ID,
            f"{self.campaign}/{run_id}",
            root=artifacts_dir(),
            manifest=manifest,
        )

    # ------------------------------------------------------------------
    def run_mission(self, treatment: str, total_distance: float, *, phase: str, seed: int = 0) -> dict[str, Any]:
        if treatment not in TREATMENTS:
            raise ValueError(f"unknown treatment: {treatment}")
        spec = self.protocol["segmentation"]
        segment_length = float(spec["segment_length_m"])
        run_id = f"{treatment}-{total_distance:g}m-{phase}-seed{seed:03d}"
        simulation = build_simulation(self.robot, seed=seed)
        controller = build_controller(self.robot)
        proxy = PathLengthProxy(simulation)
        router = SkillRouter([WalkForwardSkill(), StopSkill()])
        context = SkillContext(
            simulation=proxy,
            controller=controller,
            robot_config=self.robot,
            max_steps=int(round(900.0 / simulation.timestep)),
            seed=seed,
        )
        recorder = self._recorder(
            run_id,
            treatment=treatment,
            total_distance=total_distance,
            phase=phase,
            seed=seed,
        )
        state = simulation.reset(seed=seed)
        frame = MissionFrame.from_state(state)
        recorder.log_event(
            "mission_start",
            {
                "treatment": treatment,
                "total_distance_m": total_distance,
                "segment_length_m": segment_length,
                "memory_continuous": treatment in MEMORY_CONTINUOUS,
                "initial_position": list(frame.initial_position),
                "initial_heading_deg": wrap_angle_deg(
                    math.degrees(frame.initial_yaw_rad)
                ),
            },
        )
        started = time.perf_counter()
        segments: list[dict[str, Any]] = []
        walk_calls = 0
        stop_calls = 0
        memory_resets = 0
        stopping_time = 0.0
        fallen = False
        forward_progress = 0.0
        pending = list(build_segment_schedule(total_distance, segment_length_m=segment_length))
        guard = 0
        while not fallen and guard < 64:
            guard += 1
            if treatment == "direct_long":
                if walk_calls > 0:
                    break
                target = float(total_distance)
            elif treatment == "segmented_state_aware":
                remaining_schedule = build_state_aware_schedule(
                    total_distance, forward_progress, segment_length_m=segment_length
                )
                if not remaining_schedule:
                    break
                target = remaining_schedule[0]
            else:
                if not pending:
                    break
                target = pending.pop(0)
            reset_memory = treatment not in MEMORY_CONTINUOUS
            segment_start_state = proxy.get_robot_state()
            segment_start_time = segment_start_state.simulation_time
            recorder.log_event(
                "segment_start",
                {
                    "index": walk_calls,
                    "target_m": target,
                    "sim_time": segment_start_time,
                    "forward_progress_m": forward_progress,
                },
            )
            recorder.log_event(
                "skill_start",
                {"skill": "walk_forward", "target_m": target, "reset_memory": reset_memory},
            )
            walk = router.execute(
                SkillRequest(
                    "walk_forward",
                    {
                        "target_distance_m": target,
                        "tolerance_m": float(self.thresholds["walk"]["tolerance_min_m"]),
                        "speed_mps": float(self.thresholds["walk"]["speed_mps"]),
                        "max_duration_s": max(
                            float(self.thresholds["walk"]["timeout_min_s"]),
                            float(self.thresholds["walk"]["timeout_s_per_m"]) * target,
                        ),
                        "reset_memory": reset_memory,
                    },
                ),
                context,
            )
            walk_calls += 1
            if reset_memory:
                memory_resets += 1
            recorder.log_event(
                "memory_reset" if reset_memory else "memory_continued",
                {"segment_index": walk_calls - 1, "reset": reset_memory, "policy": "motion.pt"},
            )
            recorder.log_event(
                "skill_end",
                {"skill": "walk_forward", "status": walk.status.value, "reason": walk.reason},
            )
            if walk.metrics.get("fallen"):
                fallen = True
            if treatment != "direct_long":
                recorder.log_event("stop_start", {"sim_time": proxy.get_robot_state().simulation_time})
                stop_start = proxy.get_robot_state().simulation_time
                stop = router.execute(
                    SkillRequest(
                        "stop",
                        {
                            "window_s": float(self.thresholds["stop"]["window_s"]),
                            "speed_threshold_mps": float(
                                self.thresholds["stop"]["speed_threshold_mps"]
                            ),
                            "max_duration_s": float(self.thresholds["stop"]["max_duration_s"]),
                        },
                    ),
                    context,
                )
                stop_calls += 1
                stopping_time += proxy.get_robot_state().simulation_time - stop_start
                recorder.log_event(
                    "stop_end",
                    {"status": stop.status.value, "sim_time": proxy.get_robot_state().simulation_time},
                )
                if stop.metrics.get("fallen"):
                    fallen = True
            checkpoint_state = proxy.get_robot_state()
            forward, lateral = frame.project(checkpoint_state.base_position)
            heading = frame.heading_error_deg(checkpoint_state)
            forward_progress = forward
            segment_record = {
                "index": walk_calls - 1,
                "target_m": target,
                "walk_status": walk.status.value,
                "stop_status": None if treatment == "direct_long" else stop.status.value,
                "start_pose": list(segment_start_state.base_position),
                "end_pose": list(checkpoint_state.base_position),
                "forward_delta_m": forward - frame.project(segment_start_state.base_position)[0],
                "lateral_delta_m": lateral - frame.project(segment_start_state.base_position)[1],
                "heading_delta_deg": heading
                - frame.heading_error_deg(segment_start_state),
                "forward_progress_m": forward,
                "lateral_drift_m": lateral,
                "heading_error_deg": heading,
                "segment_sim_time_s": checkpoint_state.simulation_time - segment_start_time,
                "memory_reset": reset_memory,
            }
            segments.append(segment_record)
            recorder.log_event("state_checkpoint", segment_record)
            if treatment == "direct_long":
                break
        final_state = proxy.get_robot_state()
        forward, lateral = frame.project(final_state.base_position)
        heading = frame.heading_error_deg(final_state)
        elapsed = final_state.simulation_time - state.simulation_time
        wall = time.perf_counter() - started
        physical = bool(
            not fallen
            and final_state.is_finite()
            and walk.status.value not in {"UNSAFE", "NON_FINITE_STATE", "INTERRUPTED"}
        )
        metrics: dict[str, Any] = {
            "treatment": treatment,
            "total_target_distance_m": float(total_distance),
            "segment_length_m": segment_length,
            "memory_continuous": treatment in MEMORY_CONTINUOUS,
            "final_forward_progress_m": forward,
            "final_lateral_drift_m": lateral,
            "final_heading_error_deg": heading,
            "absolute_distance_error_m": abs(forward - float(total_distance)),
            "completion_sim_time_s": elapsed,
            "total_simulation_time_s": elapsed,
            "total_wall_time_s": wall,
            "total_stopping_time_s": stopping_time,
            "path_length_m": proxy.path_length_m,
            "skill_invocations": walk_calls,
            "stops": stop_calls,
            "controller_memory_resets": memory_resets,
            "physical_success": physical,
            "fallen": fallen,
            "segments": segments,
            "drift_per_meter": drift_per_meter(lateral, forward),
            "heading_error_per_meter": heading_error_per_meter(heading, forward),
        }
        evaluation = evaluate_walk_task(metrics, float(total_distance), physical=physical)
        metrics.update(evaluation)
        if not physical:
            metrics["failure_type"] = "FALL" if fallen else "UNKNOWN_FAILURE"
            metrics["failure_reason"] = "physical failure"
        elif not evaluation["task_success"]:
            metrics["failure_type"] = (
                evaluation["task_violations"][0]
                if evaluation["task_violations"]
                else "TASK_ENVELOPE_VIOLATION"
            )
            metrics["failure_reason"] = "task envelope violated: " + ", ".join(
                evaluation["task_violations"]
            )
        else:
            metrics["failure_type"] = "SUCCESS"
            metrics["failure_reason"] = None
        recorder.log_event(
            "mission_end",
            {
                "forward_progress_m": forward,
                "lateral_drift_m": lateral,
                "heading_error_deg": heading,
                "physical_success": physical,
                "task_success": evaluation["task_success"],
                "skill_invocations": walk_calls,
                "stops": stop_calls,
                "controller_memory_resets": memory_resets,
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
        simulation.close()
        record = {
            "run_id": run_id,
            "treatment": treatment,
            "total_distance_m": float(total_distance),
            "phase": phase,
            "seed": seed,
            "metrics": metrics,
        }
        self.records.append(record)
        return record

    # ------------------------------------------------------------------
    def run_pilot(self) -> None:
        pilot = self.protocol["pilot"]
        for treatment, distance in pilot["missions"]:
            self.run_mission(str(treatment), float(distance), phase="pilot", seed=0)

    def run_final(self) -> None:
        for distance in self.protocol["segmentation"]["total_distances_m"]:
            for treatment in TREATMENTS:
                self.run_mission(treatment, float(distance), phase="final", seed=0)

    def summarize(self) -> dict[str, Any]:
        environment = EnvironmentInfo.collect()
        physical = sum(1 for r in self.records if r["metrics"]["physical_success"])
        task = sum(1 for r in self.records if r["metrics"]["task_success"])
        taxonomy: dict[str, int] = {}
        for record in self.records:
            key = "SUCCESS" if record["metrics"]["task_success"] else str(record["metrics"]["failure_type"])
            taxonomy[key] = taxonomy.get(key, 0) + 1
        return {
            "experiment_id": EXPERIMENT_ID,
            "campaign": self.campaign,
            "protocol_path": self.protocol_path,
            "protocol_sha256": self.protocol_sha256,
            "source_commit": environment.git_commit,
            "generated_at": utc_timestamp(),
            "environment": environment.to_dict(),
            "artifact_path": str(Path("artifacts") / EXPERIMENT_ID / self.campaign),
            "missions_total": len(self.records),
            "physical_successes": physical,
            "task_successes": task,
            "failure_taxonomy": taxonomy,
        }


def _improved(protocol: dict[str, Any], direct: dict[str, Any], treatment: dict[str, Any]) -> dict[str, Any]:
    cfg = protocol["improvement"]
    factor = float(cfg["material_factor"])
    if treatment["task_success"] and not direct["task_success"]:
        return {"verdict": "IMPROVED_TASK_OUTCOME", "reason": "task outcome FAIL -> PASS"}
    if (
        direct["task_success"] == treatment["task_success"]
        and treatment["physical_success"]
        and direct["physical_success"]
        and abs(treatment["lateral_drift_m"]) <= factor * abs(direct["lateral_drift_m"])
        and abs(treatment["heading_error_deg"]) <= factor * abs(direct["heading_error_deg"])
        and (
            abs(treatment["lateral_drift_m"]) < abs(direct["lateral_drift_m"]) - 1e-9
            or abs(treatment["heading_error_deg"])
            < abs(direct["heading_error_deg"]) - 1e-9
        )
    ):
        return {
            "verdict": "IMPROVED_METRICS",
            "reason": f"both drift and heading reduced by at least {1 - factor:.0%}",
        }
    return {"verdict": "NO_IMPROVEMENT", "reason": "no material task-metric improvement"}


def build_segmentation_comparison(
    protocol: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any]:
    comparison: dict[str, Any] = {"distances": {}}
    for distance in protocol["segmentation"]["total_distances_m"]:
        key = f"{float(distance):g}"
        entry: dict[str, Any] = {"total_distance_m": float(distance), "treatments": {}}
        direct: dict[str, Any] | None = None
        for record in records:
            if abs(record["total_distance_m"] - float(distance)) > 1e-9:
                continue
            metrics = record["metrics"]
            payload = {
                "treatment": record["treatment"],
                "physical_success": metrics["physical_success"],
                "task_success": metrics["task_success"],
                "final_forward_progress_m": metrics["final_forward_progress_m"],
                "lateral_drift_m": metrics["final_lateral_drift_m"],
                "heading_error_deg": metrics["final_heading_error_deg"],
                "total_simulation_time_s": metrics["total_simulation_time_s"],
                "total_stopping_time_s": metrics["total_stopping_time_s"],
                "path_length_m": metrics["path_length_m"],
                "skill_invocations": metrics["skill_invocations"],
                "stops": metrics["stops"],
                "controller_memory_resets": metrics["controller_memory_resets"],
                "failure_type": metrics["failure_type"],
                "run_id": record["run_id"],
            }
            entry["treatments"][record["treatment"]] = payload
            if record["treatment"] == "direct_long":
                direct = payload
        if not entry["treatments"]:
            continue
        if direct is not None:
            for name, payload in entry["treatments"].items():
                if name == "direct_long":
                    payload["improvement_vs_direct"] = {
                        "verdict": "BASELINE",
                        "reason": "single long skill baseline",
                    }
                    continue
                payload["improvement_vs_direct"] = _improved(protocol, direct, payload)
                payload["delta_vs_direct"] = {
                    "lateral_drift_m": payload["lateral_drift_m"] - direct["lateral_drift_m"],
                    "heading_error_deg": payload["heading_error_deg"]
                    - direct["heading_error_deg"],
                    "simulation_time_s": payload["total_simulation_time_s"]
                    - direct["total_simulation_time_s"],
                }
        comparison["distances"][key] = entry
    return comparison


def build_distance_boundary(protocol: dict[str, Any], boundary_payload: dict[str, Any]) -> dict[str, Any]:
    search = boundary_payload["search"]
    final = boundary_payload["final"]
    reliable = sorted(
        (o for o in final if o["task_success_rate"] >= 0.9), key=lambda o: o["value"]
    )
    failing = sorted((o for o in final if o["task_success_rate"] < 0.9), key=lambda o: o["value"])
    last_reliable = reliable[-1]["value"] if reliable else None
    first_failure = failing[0]["value"] if failing else None
    failure_modes: dict[str, int] = {}
    for observation in final:
        for key, count in observation["failure_counts"].items():
            failure_modes[key] = failure_modes.get(key, 0) + count
    return {
        "schema_version": "1.2.0",
        "experiment_id": protocol["experiment_id"],
        "bracket_provenance": protocol["boundary"]["bracket_provenance"],
        "search": {
            "safe_start_m": protocol["boundary"]["safe_start_m"],
            "initial_bracket_m": protocol["boundary"]["initial_bracket_m"],
            "resolution_m": protocol["boundary"]["resolution_m"],
            "bracket": search["bracket"],
            "boundary_estimate_m": search["boundary_estimate"],
            "boundary_reached": search["boundary_reached"],
            "stop_reason": search["stop_reason"],
            "trace": search["trace"],
        },
        "last_reliable_m": last_reliable,
        "first_failure_m": first_failure,
        "task_boundary_bracket_m": search["bracket"],
        "dominant_failure_modes": [
            {"failure_type": key, "count": count}
            for key, count in sorted(failure_modes.items(), key=lambda item: -item[1])
        ],
        "final_observations": final,
        "drift_per_meter": {
            f"{record['value']:g}": record["metrics"].get("drift_per_meter")
            for record in final
        },
    }


def build_risk_map_v1_2b(
    *,
    protocol: dict[str, Any],
    boundary: dict[str, Any],
    comparison: dict[str, Any],
    source_commit: str | None,
) -> dict[str, Any]:
    strategies: dict[str, Any] = {}
    for key, entry in comparison["distances"].items():
        per_treatment: dict[str, Any] = {}
        for name, payload in entry["treatments"].items():
            if not payload["physical_success"]:
                risk = "HIGH"
            elif not payload["task_success"]:
                risk = "HIGH"
            elif payload.get("improvement_vs_direct", {}).get("verdict") == "IMPROVED_METRICS":
                risk = "LOW"
            else:
                risk = "MEDIUM"
            per_treatment[name] = {
                "risk": risk,
                "evidence": {
                    "run_id": payload["run_id"],
                    "physical_success": payload["physical_success"],
                    "task_success": payload["task_success"],
                    "lateral_drift_m": payload["lateral_drift_m"],
                    "heading_error_deg": payload["heading_error_deg"],
                },
            }
        strategies[key] = per_treatment
    return {
        "schema_version": "1.2.0",
        "generated_at": utc_timestamp(),
        "source_commit": source_commit,
        "experiment_id": protocol["experiment_id"],
        "phase1_2_reference": "experiments/baselines/g1_failure_boundary_001/risk_map.json",
        "task_envelope": protocol["thresholds"]["envelopes"],
        "skills": {
            "walk_forward": {
                "distance_boundary": {
                    "last_reliable_m": boundary["last_reliable_m"],
                    "first_failure_m": boundary["first_failure_m"],
                    "bracket_m": boundary["task_boundary_bracket_m"],
                    "resolution_m": boundary["search"]["resolution_m"],
                    "dominant_failure_modes": boundary["dominant_failure_modes"],
                },
                "execution_strategy": strategies,
                "notes": [
                    "Execution-strategy risks are derived from measured Phase 1.2b "
                    "missions under the frozen nominal envelope.",
                    "Generic robot-capability evidence; no decision-model specific fields.",
                ],
            }
        },
    }


def build_execution_strategy_map(
    *, protocol: dict[str, Any], comparison: dict[str, Any], source_commit: str | None
) -> dict[str, Any]:
    strategies: dict[str, Any] = {}
    for key, entry in comparison["distances"].items():
        strategies[key] = {
            "total_distance_m": entry["total_distance_m"],
            "direct_long": entry["treatments"].get("direct_long", {}),
            "segmented_2m": entry["treatments"].get("segmented_continuous", {}),
            "reference": {
                "phase1_2_risk_map": "experiments/baselines/g1_failure_boundary_001/risk_map.json",
                "protocol_sha256": protocol.get("_protocol_sha256"),
            },
        }
    return {
        "schema_version": "1.2.0",
        "generated_at": utc_timestamp(),
        "source_commit": source_commit,
        "experiment_id": protocol["experiment_id"],
        "skill": "walk_forward",
        "strategies": strategies,
        "use": "Phase 2 task planner can read this to choose direct_long vs segmented_2m.",
    }


def validate_distance_boundary(data: dict[str, Any]) -> None:
    for key in ("last_reliable_m", "first_failure_m", "task_boundary_bracket_m", "final_observations"):
        if key not in data:
            raise ValueError(f"distance boundary missing {key}")


def validate_comparison(data: dict[str, Any]) -> None:
    if "distances" not in data or not data["distances"]:
        raise ValueError("comparison must contain distances")
    if not any("direct_long" in entry["treatments"] for entry in data["distances"].values()):
        raise ValueError("comparison contains no direct_long baseline")


def validate_risk_map_v1_2b(data: dict[str, Any]) -> None:
    for key in ("schema_version", "source_commit", "experiment_id", "skills"):
        if key not in data:
            raise ValueError(f"risk map v1.2b missing {key}")
    boundary = data["skills"]["walk_forward"]["distance_boundary"]
    for key in ("last_reliable_m", "first_failure_m", "bracket_m"):
        if key not in boundary:
            raise ValueError(f"distance boundary missing {key}")


def validate_execution_strategy(data: dict[str, Any]) -> None:
    for key in ("schema_version", "source_commit", "experiment_id", "skill", "strategies"):
        if key not in data:
            raise ValueError(f"execution strategy map missing {key}")
