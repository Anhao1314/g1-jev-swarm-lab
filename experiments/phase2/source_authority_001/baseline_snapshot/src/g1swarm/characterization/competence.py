"""Machine-readable competence map for the G1 skill library.

The map is generic robot-capability evidence: schema version, provenance
(model/controller revisions and hashes), per-skill preconditions, frozen success
criteria, nominal measurements, perturbation-condition results and observed
failure modes. It contains no decision-model (Jev) specific fields.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.1.0"
REQUIRED_TOP_LEVEL = (
    "schema_version",
    "generated_at",
    "experiment_id",
    "campaign",
    "source_commit",
    "robot",
    "controller",
    "skills",
)
REQUIRED_SKILL_FIELDS = (
    "preconditions",
    "success_criteria",
    "nominal",
    "conditions",
    "known_failure_modes",
    "evidence",
)

SKILL_TASK_KEYS = {
    "walk_forward": "walk_forward_2m",
    "turn": "turn_45",
    "stop": "walk_stop_2m",
    "stand": "stand_hold",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _failure_modes_for_skill(summary: dict[str, Any], skill: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for failure in summary.get("failures", []):
        failure_skills = str(failure.get("skill", "")).split("+")
        if skill not in failure_skills:
            continue
        failure_type = str(failure.get("failure_type", "UNKNOWN_FAILURE"))
        entry = grouped.setdefault(
            failure_type,
            {"failure_type": failure_type, "count": 0, "conditions": set(), "example_run_id": None},
        )
        entry["count"] += 1
        if failure.get("condition"):
            entry["conditions"].add(str(failure["condition"]))
        if entry["example_run_id"] is None:
            entry["example_run_id"] = failure.get("run_id")
    modes = []
    for entry in grouped.values():
        entry["conditions"] = sorted(entry["conditions"])
        modes.append(entry)
    return sorted(modes, key=lambda item: (-item["count"], item["failure_type"]))


def build_competence_map(
    *,
    protocol: dict[str, Any],
    summary: dict[str, Any],
    source_commit: str | None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Assemble the competence map from a frozen protocol and final summary."""

    provenance = protocol.get("provenance", {})
    robot_config = protocol.get("robot", {})
    nominal = summary.get("nominal", {})
    robustness = summary.get("robustness", {})
    skills: dict[str, Any] = {}
    for skill, task_key in SKILL_TASK_KEYS.items():
        conditions = robustness.get(task_key, {}) if skill != "stand" else {}
        skills[skill] = {
            "preconditions": protocol.get("preconditions", {}).get(skill, []),
            "success_criteria": protocol.get("success_criteria", {}).get(skill, {}),
            "nominal": nominal.get(skill, {}),
            "conditions": conditions,
            "known_failure_modes": _failure_modes_for_skill(summary, skill),
            "evidence": {
                "experiment_id": protocol.get("experiment_id"),
                "campaign": summary.get("campaign"),
                "artifact_path": summary.get("artifact_path"),
                "runs": summary.get("runs_total"),
            },
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or _utc_now(),
        "experiment_id": protocol.get("experiment_id", "unknown"),
        "campaign": summary.get("campaign"),
        "source_commit": source_commit,
        "robot": {
            "name": robot_config.get("name"),
            "model_source": provenance.get("model_source"),
            "model_commit": provenance.get("model_commit"),
            "xml": provenance.get("model_xml"),
            "dof": provenance.get("dof"),
            "actuators": provenance.get("actuators"),
        },
        "controller": {
            "kind": provenance.get("controller_kind"),
            "source": provenance.get("controller_source"),
            "version": provenance.get("controller_commit"),
            "policy_sha256": provenance.get("policy_sha256"),
        },
        "skills": skills,
        "failure_taxonomy": summary.get("failure_taxonomy", {}),
        "notes": [
            "Nominal conditions are deterministic and marked as such; standard "
            "deviations of identical repetitions are not evidence of robustness.",
            "Lateral drift and heading error are reported as continuous metrics "
            "for walk_forward; no pass/fail threshold is asserted for them.",
        ],
    }


def validate_competence_map(data: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_TOP_LEVEL if key not in data]
    if missing:
        raise ValueError(f"competence map is missing fields: {', '.join(missing)}")
    if not isinstance(data["schema_version"], str) or not data["schema_version"]:
        raise ValueError("schema_version must be a non-empty string")
    if not isinstance(data["skills"], dict) or not data["skills"]:
        raise ValueError("skills must be a non-empty mapping")
    for name, skill in data["skills"].items():
        skill_missing = [key for key in REQUIRED_SKILL_FIELDS if key not in skill]
        if skill_missing:
            raise ValueError(f"skill {name} is missing fields: {', '.join(skill_missing)}")
        if not isinstance(skill["preconditions"], list):
            raise ValueError(f"skill {name}: preconditions must be a list")
        if not isinstance(skill["known_failure_modes"], list):
            raise ValueError(f"skill {name}: known_failure_modes must be a list")
