"""Phase 1.3 artifact builders: comparison, boundary, risk and capability maps."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .runner import MODE_FOR_TREATMENT, TREATMENTS

SCHEMA_VERSION = "1.3.0"
RISK_LEVELS = ("LOW", "MEDIUM", "HIGH", "UNKNOWN")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def reduction(baseline_value: float | None, candidate_value: float | None) -> float | None:
    """Fractional reduction; None when the baseline is too close to zero."""

    if baseline_value is None or candidate_value is None:
        return None
    if abs(baseline_value) < 1e-6:
        return None
    return (abs(baseline_value) - abs(candidate_value)) / abs(baseline_value)


def _verdict(protocol: dict[str, Any], baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    gate = protocol["improvement"]
    if candidate["task_success"] and not baseline["task_success"] and candidate["physical_success"]:
        return {"verdict": "IMPROVED_TASK_OUTCOME", "reason": "task FAIL -> PASS without physical regression"}
    drift_reduction = reduction(baseline["lateral_drift_m"], candidate["lateral_drift_m"])
    heading_reduction = reduction(baseline["heading_error_deg"], candidate["heading_error_deg"])
    if (
        candidate["task_success"] == baseline["task_success"]
        and candidate["physical_success"]
        and drift_reduction is not None
        and heading_reduction is not None
        and drift_reduction >= float(gate["min_reduction_fraction"])
        and heading_reduction >= float(gate["min_reduction_fraction"])
        and candidate["control_oscillation_count"] <= int(gate["max_oscillation_count"])
        and candidate["simulation_time_s"]
        <= float(gate["max_time_factor"]) * baseline["simulation_time_s"]
    ):
        return {
            "verdict": "IMPROVED_METRICS",
            "reason": (
                f"drift -{drift_reduction:.0%}, heading -{heading_reduction:.0%} with no "
                "physical/oscillation/time regression"
            ),
        }
    return {"verdict": "NO_IMPROVEMENT", "reason": "frozen improvement gate not met"}


def _payload(record: dict[str, Any]) -> dict[str, Any]:
    metrics = record["metrics"]
    return {
        "run_id": record["run_id"],
        "treatment": record["treatment"],
        "physical_success": metrics["physical_success"],
        "task_success": metrics["task_success"],
        "forward_displacement_m": metrics["forward_displacement_m"],
        "distance_error_m": metrics["distance_error_m"],
        "lateral_drift_m": metrics["lateral_drift_m"],
        "heading_error_deg": metrics["heading_error_deg"],
        "max_abs_lateral_error_m": metrics["max_abs_lateral_error_m"],
        "max_abs_heading_error_deg": metrics["max_abs_heading_error_deg"],
        "simulation_time_s": metrics["simulation_time_s"],
        "wall_time_s": metrics["wall_time_s"],
        "mean_forward_speed_mps": metrics["mean_forward_speed_mps"],
        "final_speed_mps": metrics["final_speed_mps"],
        "correction_rms": metrics["correction_rms"],
        "correction_max_abs": metrics["correction_max_abs"],
        "saturation_count": metrics["saturation_count"],
        "saturation_fraction": metrics["saturation_fraction"],
        "control_oscillation_count": metrics["control_oscillation_count"],
        "controller_memory_resets": metrics["controller_memory_resets"],
        "failure_type": metrics["failure_type"],
        "failure_reason": metrics["failure_reason"],
    }


def build_correction_comparison(protocol: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    nominal = [record for record in summary["records"] if record["phase"] == "final"]
    comparison: dict[str, Any] = {"distances": {}}
    for distance in protocol["final"]["distances_m"]:
        key = f"{float(distance):g}"
        entry: dict[str, Any] = {"total_distance_m": float(distance), "treatments": {}}
        baseline: dict[str, Any] | None = None
        for record in nominal:
            if abs(record["distance_m"] - float(distance)) > 1e-9:
                continue
            payload = _payload(record)
            entry["treatments"][record["treatment"]] = payload
            if record["treatment"] == "open_loop":
                baseline = payload
        if baseline is not None:
            for name, payload in entry["treatments"].items():
                payload["drift_reduction"] = reduction(baseline["lateral_drift_m"], payload["lateral_drift_m"])
                payload["heading_reduction"] = reduction(
                    baseline["heading_error_deg"], payload["heading_error_deg"]
                )
                payload["absolute_drift_change_m"] = payload["lateral_drift_m"] - baseline["lateral_drift_m"]
                payload["absolute_heading_change_deg"] = (
                    payload["heading_error_deg"] - baseline["heading_error_deg"]
                )
                if name == "open_loop":
                    payload["improvement_vs_open_loop"] = {"verdict": "BASELINE", "reason": "open-loop baseline"}
                else:
                    payload["improvement_vs_open_loop"] = _verdict(protocol, baseline, payload)
        comparison["distances"][key] = entry
    # Disturbance spot-check rows (if executed).
    disturbance_records = [record for record in summary["records"] if record["phase"] == "disturbance"]
    comparison["disturbance_spot_check"] = {}
    for record in disturbance_records:
        disturbance = record["disturbance"] or {}
        label = disturbance.get("type", "unknown")
        if label == "push":
            label = f"push_{float(disturbance.get('force_n', 0.0)):g}N"
        elif label == "friction":
            label = f"friction_{float(disturbance.get('friction_slide', 0.0)):g}"
        comparison["disturbance_spot_check"].setdefault(label, {})[record["treatment"]] = _payload(record)
    return comparison


def build_boundary_comparison(protocol: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    baseline = protocol["baseline"]["open_loop"]
    extension_max = float(protocol["boundary_extension"]["max_m"])
    treatments: dict[str, Any] = {}
    for treatment in TREATMENTS:
        records = [
            record
            for record in summary["records"]
            if record["treatment"] == treatment and record["phase"] in {"final", "extension"}
        ]
        passing = [record["distance_m"] for record in records if record["metrics"]["task_success"]]
        failing = [record["distance_m"] for record in records if not record["metrics"]["task_success"]]
        treatments[treatment] = {
            "evaluated_distances_m": sorted(record["distance_m"] for record in records),
            "last_reliable_m": max(passing) if passing else None,
            "first_failure_m": min(failing) if failing else None,
            "boundary_not_reached_within_budget": bool(records and not failing and max(passing or [0.0]) >= extension_max),
        }
    open_loop = treatments["open_loop"]
    expansion = {}
    for treatment in ("heading_only", "heading_lateral"):
        if open_loop["last_reliable_m"] is not None and treatments[treatment]["last_reliable_m"] is not None:
            expansion[treatment] = treatments[treatment]["last_reliable_m"] - open_loop["last_reliable_m"]
        else:
            expansion[treatment] = None
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": protocol["experiment_id"],
        "open_loop_reference": {
            "last_reliable_m": baseline["last_reliable_m"],
            "first_failure_m": baseline["first_failure_m"],
            "reference": baseline["reference"],
        },
        "extension_budget_m": extension_max,
        "treatments": treatments,
        "reliable_distance_expansion_m": expansion,
        "boundary_not_reached_within_budget": treatments["heading_lateral"]["boundary_not_reached_within_budget"],
    }


def _risk_for(payload: dict[str, Any], gate: dict[str, Any]) -> str:
    if not payload["physical_success"] or not payload["task_success"]:
        return "HIGH"
    if payload["control_oscillation_count"] > int(gate["max_oscillation_count"]):
        return "MEDIUM"
    if payload["saturation_fraction"] > float(gate["max_saturation_fraction"]):
        return "MEDIUM"
    return "LOW"


def build_risk_map_v1_3(
    protocol: dict[str, Any],
    comparison: dict[str, Any],
    boundary: dict[str, Any],
    source_commit: str | None,
) -> dict[str, Any]:
    gate = protocol["improvement"]
    distances: dict[str, Any] = {}
    for key, entry in comparison["distances"].items():
        distances[key] = {
            treatment: {
                "risk": _risk_for(payload, gate),
                "evidence": {
                    "run_id": payload["run_id"],
                    "physical_success": payload["physical_success"],
                    "task_success": payload["task_success"],
                    "lateral_drift_m": payload["lateral_drift_m"],
                    "heading_error_deg": payload["heading_error_deg"],
                    "saturation_fraction": payload["saturation_fraction"],
                    "control_oscillation_count": payload["control_oscillation_count"],
                },
            }
            for treatment, payload in entry["treatments"].items()
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "source_commit": source_commit,
        "experiment_id": protocol["experiment_id"],
        "task_envelope": protocol["thresholds"]["envelopes"],
        "skills": {
            "walk_forward": {
                "execution_mode": distances,
                "reliable_distance": {
                    treatment: {
                        "last_reliable_m": boundary["treatments"][treatment]["last_reliable_m"],
                        "first_failure_m": boundary["treatments"][treatment]["first_failure_m"],
                        "boundary_not_reached_within_budget": boundary["treatments"][treatment][
                            "boundary_not_reached_within_budget"
                        ],
                    }
                    for treatment in TREATMENTS
                },
                "notes": [
                    "Generic execution-strategy evidence; no decision-model specific fields.",
                    "Risks are computed by the frozen deterministic rules, never by a model.",
                ],
            }
        },
    }


def build_capability_map_v1_3(
    protocol: dict[str, Any],
    comparison: dict[str, Any],
    boundary: dict[str, Any],
    source_commit: str | None,
) -> dict[str, Any]:
    verdicts: dict[str, list[str]] = {}
    for key, entry in comparison["distances"].items():
        for treatment, payload in entry["treatments"].items():
            if treatment == "open_loop":
                continue
            verdict = payload.get("improvement_vs_open_loop", {}).get("verdict")
            if verdict == "IMPROVED_TASK_OUTCOME":
                verdicts.setdefault(treatment, []).append(f"{key}m: task FAIL -> PASS")
            elif verdict == "IMPROVED_METRICS":
                verdicts.setdefault(treatment, []).append(f"{key}m: drift/heading reduction")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "source_commit": source_commit,
        "experiment_id": protocol["experiment_id"],
        "policy_unchanged": {
            "policy_sha256": protocol["provenance"]["policy_sha256"],
            "note": "motion.pt, gains and action scale are unchanged; only the outer command layer differs",
        },
        "capability_change": {
            "category": "closed_loop_execution_strategy",
            "not": "new_locomotion_policy",
            "improvements": verdicts,
            "reliable_distance": {
                treatment: {
                    "open_loop_reference_last_reliable_m": boundary["open_loop_reference"]["last_reliable_m"],
                    "last_reliable_m": boundary["treatments"][treatment]["last_reliable_m"],
                    "expansion_m": boundary["reliable_distance_expansion_m"].get(treatment),
                    "boundary_not_reached_within_budget": boundary["treatments"][treatment][
                        "boundary_not_reached_within_budget"
                    ],
                }
                for treatment in TREATMENTS
            },
        },
        "evidence": {
            "artifact_path": comparison.get("artifact_path"),
            "protocol_sha256": protocol.get("_protocol_sha256"),
        },
    }


def validate_correction_comparison(data: dict[str, Any]) -> None:
    if "distances" not in data or not data["distances"]:
        raise ValueError("comparison must contain distances")
    for key, entry in data["distances"].items():
        treatments = entry.get("treatments", {})
        if "open_loop" not in treatments:
            raise ValueError(f"comparison {key} missing open_loop treatment")


def validate_boundary_comparison(data: dict[str, Any]) -> None:
    for key in ("open_loop_reference", "treatments", "reliable_distance_expansion_m"):
        if key not in data:
            raise ValueError(f"boundary comparison missing {key}")
    for treatment in TREATMENTS:
        if treatment not in data["treatments"]:
            raise ValueError(f"boundary comparison missing treatment {treatment}")


def validate_risk_map_v1_3(data: dict[str, Any]) -> None:
    for key in ("schema_version", "source_commit", "experiment_id", "skills"):
        if key not in data:
            raise ValueError(f"risk map v1.3 missing {key}")
    for entry in data["skills"]["walk_forward"]["execution_mode"].values():
        for payload in entry.values():
            if payload["risk"] not in RISK_LEVELS:
                raise ValueError(f"invalid risk label: {payload['risk']}")


def validate_capability_map_v1_3(data: dict[str, Any]) -> None:
    for key in ("schema_version", "source_commit", "experiment_id", "capability_change"):
        if key not in data:
            raise ValueError(f"capability map v1.3 missing {key}")
    if data["capability_change"]["category"] != "closed_loop_execution_strategy":
        raise ValueError("capability change must be attributed to the closed-loop execution strategy")
