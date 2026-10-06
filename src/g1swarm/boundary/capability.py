"""Capability boundary map and queryable risk map builders (Phase 1.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..characterization.failures import TAXONOMY_VERSION
from .risk import RISK_RULES_VERSION

SCHEMA_VERSION = "1.2.0"
PHASE11_COMPETENCE_SOURCE = (
    "experiments/baselines/g1_skill_characterization_001/competence_map.json"
)

CONDITION_META = {
    "A_distance": ("distance", "m"),
    "B_push": ("push_force_lateral", "N"),
    "C_friction": ("friction_slide", ""),
    "D_joint": ("joint_position_sigma", "rad"),
    "E_yaw": ("initial_yaw_offset", "deg"),
}

REQUIRED_CAPABILITY_KEYS = (
    "schema_version",
    "source_commit",
    "experiment_id",
    "phase1_1_competence_source",
    "robot",
    "controller",
    "skills",
)
REQUIRED_RISK_KEYS = (
    "schema_version",
    "rules_version",
    "rules",
    "source_commit",
    "experiment_id",
    "skills",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _provenance(protocol: dict[str, Any]) -> dict[str, Any]:
    source = protocol.get("provenance", {})
    return {
        "model_source": source.get("model_source"),
        "model_commit": source.get("model_commit"),
        "controller_source": source.get("controller_source"),
        "controller_commit": source.get("controller_commit"),
        "policy_sha256": source.get("policy_sha256"),
        "dof": source.get("dof"),
        "actuators": source.get("actuators"),
    }


def build_capability_boundary_map(
    *, protocol: dict[str, Any], summary: dict[str, Any], source_commit: str | None
) -> dict[str, Any]:
    experiments = summary.get("experiments", {})
    regions: dict[str, dict[str, list[float]]] = {
        "reliable": {},
        "transition": {},
        "failure": {},
    }
    boundary_estimates: dict[str, Any] = {}
    failure_modes: dict[str, int] = {}
    risk_table: list[dict[str, Any]] = []
    for spec_key, payload in experiments.items():
        condition, unit = CONDITION_META.get(spec_key, (spec_key, ""))
        search = payload.get("search", {})
        for zone in regions:
            regions[zone][condition] = sorted(
                float(value) for value in search.get("zones", {}).get(zone, [])
            )
        boundary_estimates[condition] = {
            "unit": unit,
            "boundary_estimate": search.get("boundary_estimate"),
            "bracket": search.get("bracket"),
            "boundary_reached": bool(search.get("boundary_reached")),
            "stop_reason": search.get("stop_reason"),
            "direction": search.get("direction"),
        }
        for observation in payload.get("final", []):
            risk_table.append(
                {
                    "condition": condition,
                    "value": observation.get("value"),
                    "unit": unit,
                    "risk": observation.get("risk"),
                    "n_runs": observation.get("n_runs"),
                    "deterministic": observation.get("deterministic"),
                    "physical_success_rate": observation.get("physical_success_rate"),
                    "task_success_rate": observation.get("task_success_rate"),
                    "failure_counts": observation.get("failure_counts", {}),
                }
            )
        for record in summary.get("failures", []):
            if record.get("experiment") != spec_key:
                continue
            key = str(record.get("failure_type"))
            failure_modes[key] = failure_modes.get(key, 0) + 1

    walk_forward = {
        "boundary_status": "explored",
        "task_definition": (
            "walk along the initial heading to the requested distance; the E_yaw "
            "condition instead uses a fixed world-frame goal of (2 m, 0)"
        ),
        "task_envelopes": {
            "nominal": protocol.get("thresholds", {}).get("envelopes", {}).get("nominal"),
            "strict": protocol.get("thresholds", {}).get("envelopes", {}).get("strict"),
        },
        "task_envelope_note": (
            "warehouse corridor proxies defined as experiment task constraints; "
            "not official Unitree G1 capability standards"
        ),
        "reliable_region": regions["reliable"],
        "transition_region": regions["transition"],
        "failure_region": regions["failure"],
        "boundary_estimates": boundary_estimates,
        "known_failure_modes": [
            {"failure_type": key, "count": count}
            for key, count in sorted(failure_modes.items(), key=lambda item: -item[1])
        ],
        "risk_table": risk_table,
        "evidence_refs": {
            "experiment_id": summary.get("experiment_id"),
            "campaign": summary.get("campaign"),
            "artifact_path": summary.get("artifact_path"),
            "runs_total": summary.get("runs_total"),
            "protocol_sha256": summary.get("protocol_sha256"),
        },
    }
    not_explored = {
        "boundary_status": "not_explored_in_phase_1_2",
        "reference": PHASE11_COMPETENCE_SOURCE,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "source_commit": source_commit,
        "experiment_id": summary.get("experiment_id"),
        "campaign": summary.get("campaign"),
        "phase1_1_competence_source": PHASE11_COMPETENCE_SOURCE,
        "failure_taxonomy_version": TAXONOMY_VERSION,
        "risk_rules_version": RISK_RULES_VERSION,
        "robot": {
            "name": protocol.get("robot_config"),
            "model_source": protocol.get("provenance", {}).get("model_source"),
            "model_commit": protocol.get("provenance", {}).get("model_commit"),
        },
        "controller": _provenance(protocol),
        "skills": {
            "walk_forward": walk_forward,
            "turn": dict(not_explored),
            "stop": dict(not_explored),
            "stand": dict(not_explored),
        },
    }


def validate_capability_boundary_map(data: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_CAPABILITY_KEYS if key not in data]
    if missing:
        raise ValueError(f"capability map missing fields: {', '.join(missing)}")
    if not isinstance(data["schema_version"], str) or not data["schema_version"]:
        raise ValueError("schema_version must be a non-empty string")
    skills = data["skills"]
    if not isinstance(skills, dict) or "walk_forward" not in skills:
        raise ValueError("skills must include walk_forward")
    walk = skills["walk_forward"]
    for key in ("boundary_status", "reliable_region", "transition_region", "failure_region"):
        if key not in walk:
            raise ValueError(f"walk_forward missing {key}")


def build_risk_map(
    *, protocol: dict[str, Any], summary: dict[str, Any], source_commit: str | None
) -> dict[str, Any]:
    conditions: list[dict[str, Any]] = []
    for spec_key, payload in summary.get("experiments", {}).items():
        condition, unit = CONDITION_META.get(spec_key, (spec_key, ""))
        for observation in payload.get("final", []):
            conditions.append(
                {
                    "condition": condition,
                    "value": observation.get("value"),
                    "unit": unit,
                    "risk": observation.get("risk"),
                    "evidence": {
                        "n_runs": observation.get("n_runs"),
                        "deterministic": observation.get("deterministic"),
                        "physical_success_rate": observation.get("physical_success_rate"),
                        "task_success_rate": observation.get("task_success_rate"),
                        "strict_violation_rate": observation.get("metrics", {}).get(
                            "strict_violation_rate"
                        ),
                        "failure_counts": observation.get("failure_counts", {}),
                        "run_ids": observation.get("run_ids", []),
                    },
                }
            )
    conditions.sort(key=lambda item: (item["condition"], item["value"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "rules_version": RISK_RULES_VERSION,
        "generated_at": _utc_now(),
        "source_commit": source_commit,
        "experiment_id": summary.get("experiment_id"),
        "campaign": summary.get("campaign"),
        "artifact_path": summary.get("artifact_path"),
        "rules": {
            "UNKNOWN": "fewer than 3 runs, or fewer than 5 non-deterministic runs, or missing rates",
            "HIGH": "task success rate <= 0.30 or physical success rate < 0.90",
            "MEDIUM": "transition region (task success < 0.90) or strict-envelope violation",
            "LOW": "reliable region with sufficient evidence and no strict violations",
        },
        "skills": {
            "walk_forward": {
                "task_envelope": protocol.get("thresholds", {}).get("envelopes"),
                "conditions": conditions,
                "notes": [
                    "Deterministic conditions repeat identical trajectories; they are "
                    "reported as such and are not independent random samples.",
                    "Risk labels are produced by a deterministic evaluator, not by a "
                    "language or decision model.",
                    "Generic robot-capability evidence; no decision-model specific fields.",
                ],
            }
        },
    }


def validate_risk_map(data: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_RISK_KEYS if key not in data]
    if missing:
        raise ValueError(f"risk map missing fields: {', '.join(missing)}")
    skills = data["skills"]
    if not isinstance(skills, dict) or "walk_forward" not in skills:
        raise ValueError("skills must include walk_forward")
    for condition in skills["walk_forward"].get("conditions", []):
        if condition.get("risk") not in {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}:
            raise ValueError(f"invalid risk label: {condition.get('risk')}")
