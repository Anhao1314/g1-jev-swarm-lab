"""Physical success vs task success: frozen task envelopes.

Phase 1.2 separates:

* **physical success** - the robot stayed upright, state stayed finite, the
  controller stayed alive, control stayed valid and the simulation completed;
* **task success** - the measured trajectory also satisfied the geometric task
  envelope for that skill.

A robot that walks 10 m without falling but drifts 1.5 m sideways is a
``physical_success = true`` / ``task_success = false`` case.

The envelopes below are **experiment task constraints** (warehouse corridor
proxies), not official Unitree G1 capability standards. They are frozen in the
Phase 1.2 protocol before the final campaign and reused unchanged by every
run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class EnvelopeLimits:
    distance_error_max_m: float
    lateral_max_m: float
    heading_max_deg: float
    timeout_max_s: float

    def to_dict(self) -> dict[str, float]:
        return {
            "distance_error_max_m": self.distance_error_max_m,
            "lateral_drift_max_m": self.lateral_max_m,
            "heading_error_max_deg": self.heading_max_deg,
            "timeout_max_s": self.timeout_max_s,
        }


@dataclass(frozen=True)
class WalkEnvelope:
    """Geometric acceptance region for one walk invocation."""

    name: str
    distance_error_rule: tuple[float, float]  # (absolute floor m, relative fraction)
    lateral_rule: tuple[float, float]
    heading_max_deg: float
    timeout_rule: tuple[float, float]  # (absolute floor s, seconds per metre)

    def limits(self, target_m: float) -> EnvelopeLimits:
        distance_floor, distance_relative = self.distance_error_rule
        lateral_floor, lateral_relative = self.lateral_rule
        timeout_floor, timeout_per_m = self.timeout_rule
        target = float(target_m)
        return EnvelopeLimits(
            distance_error_max_m=max(distance_floor, distance_relative * target),
            lateral_max_m=max(lateral_floor, lateral_relative * target),
            heading_max_deg=float(self.heading_max_deg),
            timeout_max_s=max(timeout_floor, timeout_per_m * target),
        )

    def evaluate(self, metrics: Mapping[str, Any], target_m: float) -> "EnvelopeEvaluation":
        limits = self.limits(target_m)
        distance_error = float(metrics.get("absolute_distance_error_m", math.inf))
        lateral = abs(float(metrics.get("lateral_drift_m", math.inf)))
        heading = abs(float(metrics.get("heading_error_deg", math.inf)))
        completion = float(metrics.get("completion_sim_time_s", math.inf))
        violations: list[str] = []
        if distance_error > limits.distance_error_max_m:
            violations.append("DISTANCE_ERROR")
        if lateral > limits.lateral_max_m:
            violations.append("EXCESSIVE_DRIFT")
        if heading > limits.heading_max_deg:
            violations.append("HEADING_ERROR")
        if completion > limits.timeout_max_s:
            violations.append("TIMEOUT")
        return EnvelopeEvaluation(
            envelope=self.name,
            limits=limits,
            distance_error_m=distance_error,
            lateral_drift_m=lateral,
            heading_error_deg=heading,
            completion_sim_time_s=completion,
            violations=tuple(violations),
        )


@dataclass(frozen=True)
class EnvelopeEvaluation:
    envelope: str
    limits: EnvelopeLimits
    distance_error_m: float
    lateral_drift_m: float
    heading_error_deg: float
    completion_sim_time_s: float
    violations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def satisfied(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope": self.envelope,
            "limits": self.limits.to_dict(),
            "distance_error_m": self.distance_error_m,
            "lateral_drift_m": self.lateral_drift_m,
            "heading_error_deg": self.heading_error_deg,
            "completion_sim_time_s": self.completion_sim_time_s,
            "violations": list(self.violations),
            "satisfied": self.satisfied,
        }


# 1.0 m corridor proxy (nominal) and 0.4 m corridor proxy (strict).
NOMINAL_WALK_ENVELOPE = WalkEnvelope(
    name="nominal",
    distance_error_rule=(0.30, 0.10),
    lateral_rule=(0.35, 0.07),
    heading_max_deg=15.0,
    timeout_rule=(15.0, 6.0),
)
STRICT_WALK_ENVELOPE = WalkEnvelope(
    name="strict",
    distance_error_rule=(0.15, 0.05),
    lateral_rule=(0.20, 0.035),
    heading_max_deg=8.0,
    timeout_rule=(12.0, 5.0),
)


def physical_success(
    *,
    fallen: bool,
    finite: bool,
    skill_status: str,
    simulation_completed: bool,
    invalid_control: bool = False,
) -> bool:
    """Physical-success predicate shared by every Phase 1.2 run."""

    if fallen or not finite or invalid_control or not simulation_completed:
        return False
    return skill_status not in {"UNSAFE", "NON_FINITE_STATE", "INVALID_CONTROL", "INTERRUPTED"}


def evaluate_walk_task(
    metrics: Mapping[str, Any],
    target_m: float,
    *,
    physical: bool,
) -> dict[str, Any]:
    """Evaluate nominal + strict envelopes and combine with physical success."""

    nominal = NOMINAL_WALK_ENVELOPE.evaluate(metrics, target_m)
    strict = STRICT_WALK_ENVELOPE.evaluate(metrics, target_m)
    task_success = bool(physical and nominal.satisfied)
    strict_success = bool(physical and strict.satisfied)
    return {
        "physical_success": bool(physical),
        "task_success": task_success,
        "nominal_envelope": nominal.to_dict(),
        "strict_envelope": strict.to_dict(),
        "strict_violation": bool(physical and not strict.satisfied),
        "strict_success": strict_success,
        "task_violations": list(nominal.violations),
    }


def failure_type_from_violations(violations: tuple[str, ...] | list[str]) -> str:
    """Map envelope violations to the Phase 1.1/1.2 failure taxonomy."""

    ordered = ("DISTANCE_ERROR", "EXCESSIVE_DRIFT", "HEADING_ERROR", "TIMEOUT")
    for candidate in ordered:
        if candidate in violations:
            return candidate
    return "TASK_ENVELOPE_VIOLATION"
