"""Deterministic risk labelling from measured evidence.

Risk levels are computed by frozen rules (Phase 1.2 protocol), never by an LLM:

* UNKNOWN - not enough evidence (fewer than 3 runs, or fewer than 5 runs and
  non-deterministic), or missing rates
* HIGH - task success rate <= 0.30 or physical success rate < 0.90
* MEDIUM - transition region (task success < 0.90), or a strict-envelope
  violation at an otherwise reliable point (task-metric degradation)
* LOW - reliable region with sufficient evidence and no strict violations

Deterministic repetitions are reported as such and are not counted as
independent random samples.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

RISK_RULES_VERSION = "1.2.0"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RiskEvidence:
    n_runs: int
    deterministic: bool
    physical_success_rate: float | None
    task_success_rate: float | None
    strict_violation_rate: float = 0.0
    failure_counts: dict[str, int] = field(default_factory=dict)

    @property
    def independent_samples(self) -> int:
        return 1 if self.deterministic and self.n_runs > 0 else self.n_runs

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_runs": self.n_runs,
            "independent_samples": self.independent_samples,
            "deterministic": self.deterministic,
            "physical_success_rate": self.physical_success_rate,
            "task_success_rate": self.task_success_rate,
            "strict_violation_rate": self.strict_violation_rate,
            "failure_counts": dict(self.failure_counts),
        }


def risk_label(
    evidence: RiskEvidence,
    *,
    min_runs_for_label: int = 3,
    min_runs_for_low: int = 5,
) -> RiskLevel:
    if evidence.n_runs < min_runs_for_label:
        return RiskLevel.UNKNOWN
    if evidence.physical_success_rate is None or evidence.task_success_rate is None:
        return RiskLevel.UNKNOWN
    if evidence.task_success_rate <= 0.30 or evidence.physical_success_rate < 0.90:
        return RiskLevel.HIGH
    if evidence.task_success_rate < 0.90 or evidence.strict_violation_rate > 0.0:
        return RiskLevel.MEDIUM
    if evidence.n_runs < min_runs_for_low and not evidence.deterministic:
        return RiskLevel.UNKNOWN
    return RiskLevel.LOW


def risk_label_for_observation(observation: dict[str, Any]) -> RiskLevel:
    """Convenience wrapper for serialized observations."""

    metrics = observation.get("metrics", {})
    return risk_label(
        RiskEvidence(
            n_runs=int(observation.get("n_runs", 0)),
            deterministic=bool(observation.get("deterministic", False)),
            physical_success_rate=observation.get("physical_success_rate"),
            task_success_rate=observation.get("task_success_rate"),
            strict_violation_rate=float(metrics.get("strict_violation_rate", 0.0)),
            failure_counts=dict(observation.get("failure_counts", {})),
        )
    )
