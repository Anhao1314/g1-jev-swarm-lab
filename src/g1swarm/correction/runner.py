"""Phase 1.3 closed-loop correction runner.

Per-run structure (single WalkForward invocation, mission frame frozen at
mission start):

    reset -> mission frame -> [optional disturbance] -> WalkForward(distance)
          -> canonical metrics -> envelope evaluation -> evidence bundle

Treatments: ``open_loop`` (raw controller, identical to the historical
open-loop path), ``heading_only`` and ``heading_lateral`` (outer-loop correction
at the policy-command layer).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..boundary.envelope import evaluate_walk_task
from ..characterization.perturbations import DisturbanceProxy, PushSpec
from ..config import build_controller, build_simulation, load_yaml
from ..control import CorrectionConfig, CorrectionTracker, CorrectingController, PathCorrectionPolicy
from ..evidence import EnvironmentInfo, RunManifest, RunRecorder, utc_timestamp
from ..metrics import RunMetrics
from ..paths import artifacts_dir
from ..segmentation.mission import MissionFrame
from ..skills import SkillContext, SkillRequest, SkillRouter, WalkForwardSkill

EXPERIMENT_ID = "g1_closed_loop_correction_001"
TREATMENTS = ("open_loop", "heading_only", "heading_lateral")
MODE_FOR_TREATMENT = {
    "open_loop": "none",
    "heading_only": "heading_only",
    "heading_lateral": "heading_lateral",
}


class MissionMonitor:
    """Simulation proxy tracking path length and mission-frame error extremes."""

    def __init__(self, simulation, frame: MissionFrame) -> None:
        self._simulation = simulation
        self._frame = frame
        state = simulation.get_robot_state()
        self._last_position = np.array(state.base_position[:2], dtype=np.float64)
        self.path_length_m = 0.0
        self.max_abs_lateral_error_m = 0.0
        self.max_abs_heading_error_deg = 0.0

    def step(self, control=None):
        state = self._simulation.step(control)
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


class CorrectionRunner:
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
        self.extension_records: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    def correction_config(self, treatment: str, *, k_heading: float | None = None,
                          k_lateral: float | None = None) -> CorrectionConfig:
        mode = MODE_FOR_TREATMENT[treatment]
        gains = self.protocol["gains"].get(mode, {})
        limits = self.protocol["correction_limits"]
        return CorrectionConfig(
            mode=mode,
            k_heading=float(gains.get("k_heading", 0.0) if k_heading is None else k_heading),
            k_lateral=float(gains.get("k_lateral", 0.0) if k_lateral is None else k_lateral),
            max_yaw_rate_radps=float(limits["max_yaw_rate_radps"]),
            deadband_radps=float(limits["deadband_radps"]),
            oscillation_threshold_radps=float(limits["oscillation_threshold_radps"]),
        )

    def _recorder(
        self, run_id: str, *, treatment: str, distance: float, phase: str, seed: int,
        disturbance: dict[str, Any] | None,
    ) -> RunRecorder:
        provenance = self.protocol["provenance"]
        config = self.correction_config(treatment)
        manifest = RunManifest(
            experiment_id=EXPERIMENT_ID,
            run_id=run_id,
            task=f"{treatment} {distance:g} m",
            config={
                "protocol_path": self.protocol_path,
                "protocol_version": self.protocol.get("protocol_version"),
                "protocol_sha256": self.protocol_sha256,
                "treatment": treatment,
                "distance_m": distance,
                "phase": phase,
                "correction": config.to_dict(),
                "disturbance": disturbance,
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
            perturbation_type=(disturbance or {}).get("type", "nominal"),
            perturbation_parameters=disturbance,
            thresholds={
                "nominal": self.thresholds["envelopes"]["nominal"],
                "strict": self.thresholds["envelopes"]["strict"],
            },
            search_campaign=self.campaign,
            search_parameter=f"treatment:{treatment}",
        )
        return RunRecorder(EXPERIMENT_ID, f"{self.campaign}/{run_id}", root=artifacts_dir(), manifest=manifest)

    # ------------------------------------------------------------------
    def run_mission(
        self,
        treatment: str,
        distance: float,
        *,
        phase: str,
        seed: int = 0,
        disturbance: dict[str, Any] | None = None,
        k_heading: float | None = None,
        k_lateral: float | None = None,
    ) -> dict[str, Any]:
        if treatment not in TREATMENTS:
            raise ValueError(f"unknown treatment: {treatment}")
        config = self.correction_config(treatment, k_heading=k_heading, k_lateral=k_lateral)
        run_id = f"{treatment}-{distance:g}m-{phase}-seed{seed:03d}"
        if disturbance:
            run_id += f"-{disturbance['type']}"
        simulation = build_simulation(self.robot, seed=seed)
        if disturbance and disturbance["type"] == "friction":
            simulation.set_all_geom_friction(float(disturbance["friction_slide"]))
        controller = build_controller(self.robot)
        state = simulation.reset(seed=seed)
        frame = MissionFrame.from_state(state)
        monitor = MissionMonitor(simulation, frame)
        recorder = self._recorder(
            run_id, treatment=treatment, distance=distance, phase=phase, seed=seed,
            disturbance=disturbance,
        )
        recorder.log_event(
            "mission_start",
            {
                "treatment": treatment,
                "mode": config.mode,
                "distance_m": distance,
                "gains": config.to_dict(),
                "disturbance": disturbance,
                "initial_position": list(frame.initial_position),
                "initial_heading_rad": frame.initial_yaw_rad,
            },
        )
        # Disturbance wrapper (push) nests outside the monitor.
        simulation_view = monitor
        if disturbance and disturbance["type"] == "push":
            push = PushSpec(
                force_n=float(disturbance["force_n"]),
                direction=tuple(disturbance["direction"]),
                duration_s=float(disturbance["duration_s"]),
                trigger_sim_time=float(disturbance["trigger_s"]),
            )
            simulation_view = DisturbanceProxy(monitor, push)
        # Correction layer: policy-command level only.
        tracker: CorrectionTracker | None = None
        task_controller = controller
        if config.mode != "none":
            tracker = CorrectionTracker(
                oscillation_threshold_radps=config.oscillation_threshold_radps
            )
            policy = PathCorrectionPolicy(config)

            def on_sample(sample, _recorder=recorder) -> None:
                _recorder.log_event("correction_summary", sample.to_dict())

            task_controller = CorrectingController(
                controller,
                policy,
                simulation_view,
                frame,
                tracker=tracker,
                on_sample=on_sample,
                sample_period_s=1.0,
            )
            recorder.log_event(
                "correction_enabled",
                {"mode": config.mode, "gains": config.to_dict()},
            )
        context = SkillContext(
            simulation=simulation_view,
            controller=task_controller,
            robot_config=self.robot,
            max_steps=int(round(1200.0 / simulation.timestep)),
            seed=seed,
        )
        router = SkillRouter([WalkForwardSkill()])
        recorder.log_event("skill_start", {"skill": "walk_forward", "target_m": distance})
        started = time.perf_counter()
        walk = router.execute(
            SkillRequest(
                "walk_forward",
                {
                    "target_distance_m": float(distance),
                    "tolerance_m": float(self.thresholds["walk"]["tolerance_min_m"]),
                    "speed_mps": float(self.thresholds["walk"]["speed_mps"]),
                    "max_duration_s": max(
                        float(self.thresholds["walk"]["timeout_min_s"]),
                        float(self.thresholds["walk"]["timeout_s_per_m"]) * float(distance),
                    ),
                    "reset_memory": True,
                },
            ),
            context,
        )
        wall_time = time.perf_counter() - started
        final_state = simulation_view.get_robot_state()
        forward, lateral = frame.project(final_state.base_position)
        heading = frame.heading_error_deg(final_state)
        elapsed = final_state.simulation_time - state.simulation_time
        fallen = bool(walk.metrics.get("fallen"))
        physical = bool(not fallen and final_state.is_finite() and walk.status.value == "SUCCESS")
        canonical: dict[str, Any] = {
            "forward_displacement_m": forward,
            "distance_error_m": abs(forward - float(distance)),
            "lateral_drift_m": lateral,
            "heading_error_deg": heading,
            "simulation_time_s": elapsed,
            "physical_success": physical,
            "task_success": False,
            "failure_type": "SUCCESS",
            "failure_reason": None,
        }
        evaluation = evaluate_walk_task(canonical, float(distance), physical=physical)
        canonical["task_success"] = evaluation["task_success"]
        if not physical:
            canonical["failure_type"] = "FALL" if fallen else "UNKNOWN_FAILURE"
            canonical["failure_reason"] = walk.reason or "physical failure"
        elif not evaluation["task_success"]:
            canonical["failure_type"] = (
                evaluation["task_violations"][0]
                if evaluation["task_violations"]
                else "TASK_ENVELOPE_VIOLATION"
            )
            canonical["failure_reason"] = "task envelope violated: " + ", ".join(
                evaluation["task_violations"]
            )
        stats = tracker.summary() if tracker is not None else {
            "correction_rms": 0.0,
            "correction_max_abs": 0.0,
            "saturation_count": 0,
            "saturation_fraction": 0.0,
            "control_oscillation_count": 0,
            "correction_samples": 0,
            "first_saturation_time_s": None,
        }
        run_metrics = RunMetrics(
            target_distance_m=float(distance),
            max_abs_lateral_error_m=monitor.max_abs_lateral_error_m,
            max_abs_heading_error_deg=monitor.max_abs_heading_error_deg,
            wall_time_s=wall_time,
            mean_forward_speed_mps=(forward / elapsed) if elapsed > 0 else None,
            final_speed_mps=final_state.speed(),
            correction_rms=stats["correction_rms"],
            correction_max_abs=stats["correction_max_abs"],
            saturation_count=int(stats["saturation_count"]),
            saturation_fraction=float(stats["saturation_fraction"]),
            control_oscillation_count=int(stats["control_oscillation_count"]),
            controller_memory_resets=1,
            policy_hash=self.protocol["provenance"]["policy_sha256"],
            controller_version=self.protocol["provenance"]["controller_commit"],
            extras={
                "treatment": treatment,
                "correction_mode": config.mode,
                "correction_gains": config.to_dict(),
                "path_length_m": monitor.path_length_m,
                "disturbance": disturbance,
                "correction_samples": stats["correction_samples"],
                "first_saturation_time_s": stats["first_saturation_time_s"],
                "segments": 1,
                "stops": 0,
            },
            **canonical,
        )
        run_metrics.validate()
        metrics_payload = run_metrics.to_dict()
        if stats["saturation_count"] > 0:
            recorder.log_event(
                "saturation_event",
                {
                    "count": stats["saturation_count"],
                    "fraction": stats["saturation_fraction"],
                    "first_time_s": stats["first_saturation_time_s"],
                },
            )
        if stats["control_oscillation_count"] > 0:
            recorder.log_event(
                "oscillation_event",
                {"count": stats["control_oscillation_count"]},
            )
        recorder.log_event(
            "correction_summary",
            {
                "mode": config.mode,
                "correction_rms": stats["correction_rms"],
                "correction_max_abs": stats["correction_max_abs"],
                "saturation_count": stats["saturation_count"],
                "control_oscillation_count": stats["control_oscillation_count"],
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
        recorder.log_event(
            "skill_end",
            {"status": walk.status.value, "reason": walk.reason},
        )
        recorder.log_event(
            "mission_end",
            {
                "forward_displacement_m": forward,
                "lateral_drift_m": lateral,
                "heading_error_deg": heading,
                "physical_success": physical,
                "task_success": evaluation["task_success"],
            },
        )
        recorder.finish(
            {
                "status": metrics_payload["failure_type"],
                "physical_success": physical,
                "task_success": evaluation["task_success"],
            },
            metrics_payload,
        )
        if isinstance(simulation_view, DisturbanceProxy):
            for event in simulation_view.events:
                payload = {key: value for key, value in event.items() if key != "event"}
                recorder.log_event(str(event["event"]), payload)
            simulation_view.release()
        simulation.close()
        record = {
            "run_id": run_id,
            "treatment": treatment,
            "distance_m": float(distance),
            "phase": phase,
            "seed": seed,
            "disturbance": disturbance,
            "metrics": metrics_payload,
        }
        self.records.append(record)
        return record

    # ------------------------------------------------------------------
    def run_pilot_sweep(self, kind: str, *, distances: list[float], k_heading: float | None = None) -> list[dict]:
        """Engineering pilot: up to 2-3 candidate gains, 4 m and 8 m, one run each."""

        pilots = self.protocol["pilot"]
        results: list[dict] = []
        if kind == "heading":
            for gain in pilots["heading_gains"]:
                for distance in distances:
                    results.append(
                        self.run_mission(
                            "heading_only", float(distance), phase="pilot", seed=0,
                            k_heading=float(gain),
                        )
                    )
        elif kind == "lateral":
            if k_heading is None:
                raise ValueError("lateral sweep requires the chosen k_heading")
            for gain in pilots["lateral_gains"]:
                for distance in distances:
                    results.append(
                        self.run_mission(
                            "heading_lateral", float(distance), phase="pilot", seed=0,
                            k_heading=float(k_heading), k_lateral=float(gain),
                        )
                    )
        else:
            raise ValueError("kind must be 'heading' or 'lateral'")
        return results

    def run_final(self) -> None:
        distances = [float(value) for value in self.protocol["final"]["distances_m"]]
        for distance in distances:
            for treatment in TREATMENTS:
                self.run_mission(treatment, distance, phase="final", seed=0)
        # Determinism check: repeat the longest nominal distance 3x per treatment.
        self.determinism: dict[str, dict[str, Any]] = {}
        key_metrics = (
            "forward_displacement_m",
            "lateral_drift_m",
            "heading_error_deg",
            "simulation_time_s",
        )
        for treatment in TREATMENTS:
            first = [
                r
                for r in self.records
                if r["treatment"] == treatment
                and abs(r["distance_m"] - max(distances)) < 1e-9
                and r["phase"] == "final"
            ]
            if not first:
                continue
            repeats = [
                self.run_mission(treatment, max(distances), phase="repeat", seed=seed)
                for seed in (1, 2)
            ]
            vectors = {
                tuple(round(float(r["metrics"][key]), 12) for key in key_metrics)
                for r in first + repeats
            }
            self.determinism[treatment] = {
                "distance_m": max(distances),
                "runs": len(first) + len(repeats),
                "deterministic": len(vectors) == 1,
            }
        # Boundary extension only if the corrected treatment passes the longest
        # nominal distance (frozen budget: 12 / 15 / 20 m).
        extension = self.protocol["boundary_extension"]
        longest = max(distances)
        for treatment in ("heading_only", "heading_lateral"):
            passing = any(
                record["treatment"] == treatment
                and abs(record["distance_m"] - longest) < 1e-9
                and record["metrics"]["task_success"]
                for record in self.records
            )
            self.extension_records[treatment] = []
            if not passing:
                continue
            for distance in extension["distances_m"]:
                record = self.run_mission(treatment, float(distance), phase="extension", seed=0)
                self.extension_records[treatment].append(record)
                if not record["metrics"]["task_success"]:
                    break
        # Disturbance spot-check only if nominal correction showed value.
        spot = self.protocol["disturbance_spot_check"]
        if spot.get("enabled", False):
            for disturbance in spot["conditions"]:
                for treatment in TREATMENTS:
                    self.run_mission(
                        treatment,
                        float(spot["distance_m"]),
                        phase="disturbance",
                        seed=0,
                        disturbance=disturbance,
                    )

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
            "runs_total": len(self.records),
            "physical_successes": physical,
            "task_successes": task,
            "failure_taxonomy": taxonomy,
            "records": [
                {
                    "run_id": record["run_id"],
                    "treatment": record["treatment"],
                    "distance_m": record["distance_m"],
                    "phase": record["phase"],
                    "seed": record["seed"],
                    "disturbance": record["disturbance"],
                    "metrics": record["metrics"],
                }
                for record in self.records
            ],
            "determinism": getattr(self, "determinism", {}),
            "extension": {
                treatment: [
                    {"run_id": record["run_id"], "distance_m": record["distance_m"],
                     "task_success": record["metrics"]["task_success"]}
                    for record in records
                ]
                for treatment, records in self.extension_records.items()
            },
        }

    def write_outputs(self, *, summary_path: str | Path) -> dict[str, Any]:
        summary = self.summarize()
        summary_path = Path(summary_path)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return summary
