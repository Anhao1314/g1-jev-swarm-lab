"""Deterministic bracket + refinement boundary search.

Given an ordered candidate ladder, the search evaluates points from a known
safe value outward, brackets the first point that leaves the reliable zone and
refines inside the bracket. Every decision is written to the trace so the
search is reproducible and auditable.

Zones (frozen in the Phase 1.2 protocol):

* reliable: task success rate >= 0.90
* transition: 0.30 < task success rate < 0.90
* failure: task success rate <= 0.30
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

Zone = Literal["reliable", "transition", "failure"]

RELIABLE_MIN_RATE = 0.90
FAILURE_MAX_RATE = 0.30


def classify_zone(
    task_success_rate: float,
    *,
    reliable_min_rate: float = RELIABLE_MIN_RATE,
    failure_max_rate: float = FAILURE_MAX_RATE,
) -> Zone:
    if task_success_rate >= reliable_min_rate:
        return "reliable"
    if task_success_rate <= failure_max_rate:
        return "failure"
    return "transition"


@dataclass(frozen=True)
class Observation:
    """Aggregated evidence for one parameter value."""

    value: float
    n_runs: int
    physical_successes: int
    task_successes: int
    deterministic: bool
    failure_counts: dict[str, int] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    run_ids: tuple[str, ...] = ()

    @property
    def physical_success_rate(self) -> float:
        return (self.physical_successes / self.n_runs) if self.n_runs else 0.0

    @property
    def task_success_rate(self) -> float:
        return (self.task_successes / self.n_runs) if self.n_runs else 0.0

    @property
    def zone(self) -> Zone:
        return classify_zone(self.task_success_rate)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "n_runs": self.n_runs,
            "physical_successes": self.physical_successes,
            "task_successes": self.task_successes,
            "physical_success_rate": self.physical_success_rate,
            "task_success_rate": self.task_success_rate,
            "zone": self.zone,
            "deterministic": self.deterministic,
            "failure_counts": dict(self.failure_counts),
            "metrics": dict(self.metrics),
            "run_ids": list(self.run_ids),
        }


@dataclass
class SearchResult:
    parameter: str
    direction: str
    candidates: list[float]
    observations: list[Observation]
    bracket: tuple[float, float] | None
    boundary_estimate: float | None
    boundary_reached: bool
    stop_reason: str
    trace: list[dict[str, Any]]

    def zones(self) -> dict[str, list[float]]:
        result: dict[str, list[float]] = {"reliable": [], "transition": [], "failure": []}
        for observation in self.observations:
            result[observation.zone].append(observation.value)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "direction": self.direction,
            "candidates": list(self.candidates),
            "observations": [observation.to_dict() for observation in self.observations],
            "bracket": list(self.bracket) if self.bracket else None,
            "boundary_estimate": self.boundary_estimate,
            "boundary_reached": self.boundary_reached,
            "stop_reason": self.stop_reason,
            "zones": self.zones(),
            "trace": list(self.trace),
        }


class BoundarySearch:
    """Bracket + bisection search over an explicit, frozen candidate ladder."""

    def __init__(
        self,
        *,
        parameter: str,
        safe_start: float,
        candidates: Iterable[float],
        direction: str,
        max_evaluations: int = 16,
        refinement_rounds: int = 3,
        resolution: float = 0.0,
    ) -> None:
        if direction not in {"increase", "decrease"}:
            raise ValueError("direction must be 'increase' or 'decrease'")
        self.parameter = parameter
        self.safe_start = float(safe_start)
        self.candidates = [float(value) for value in candidates]
        self.direction = direction
        self.max_evaluations = int(max_evaluations)
        self.refinement_rounds = int(refinement_rounds)
        self.resolution = float(resolution)
        if not self.candidates:
            raise ValueError("candidates must not be empty")

    def run(self, evaluate: Callable[[float, str], Observation]) -> SearchResult:
        observations: list[Observation] = []
        trace: list[dict[str, Any]] = []
        evaluations = 0

        def probe(value: float, decision: str) -> Observation:
            nonlocal evaluations
            observation = evaluate(float(value), decision)
            evaluations += 1
            observations.append(observation)
            trace.append(
                {
                    "decision": decision,
                    "value": observation.value,
                    "zone": observation.zone,
                    "n_runs": observation.n_runs,
                    "physical_success_rate": observation.physical_success_rate,
                    "task_success_rate": observation.task_success_rate,
                    "failure_counts": dict(observation.failure_counts),
                    "evaluation_index": evaluations,
                }
            )
            return observation

        start = probe(self.safe_start, "safe_start")
        last_reliable: Observation | None = start if start.zone == "reliable" else None
        bracket: tuple[float, float] | None = None
        stop_reason = "boundary_not_reached"
        current = self.safe_start
        failure_point: Observation | None = None

        for candidate in self.candidates:
            if evaluations >= self.max_evaluations:
                stop_reason = "evaluation_budget_exhausted"
                break
            if self.direction == "increase" and candidate <= current:
                continue
            if self.direction == "decrease" and candidate >= current:
                continue
            observation = probe(candidate, "expand")
            if observation.zone == "reliable":
                last_reliable = observation
                current = observation.value
                continue
            failure_point = observation
            if last_reliable is not None:
                bracket = (last_reliable.value, observation.value)
            break

        if bracket is not None and last_reliable is not None and failure_point is not None:
            low_value = min(bracket)
            high_value = max(bracket)
            reliable_value = last_reliable.value
            reliable_is_lower = reliable_value <= failure_point.value
            for _ in range(self.refinement_rounds):
                if evaluations >= self.max_evaluations:
                    stop_reason = "evaluation_budget_exhausted"
                    break
                if (high_value - low_value) <= self.resolution:
                    stop_reason = "boundary_refined"
                    break
                midpoint = 0.5 * (low_value + high_value)
                observation = probe(midpoint, "refine")
                if observation.zone == "reliable":
                    if reliable_is_lower:
                        low_value = midpoint
                    else:
                        high_value = midpoint
                else:
                    if reliable_is_lower:
                        high_value = midpoint
                    else:
                        low_value = midpoint
                stop_reason = "boundary_refined"
            bracket = (low_value, high_value)

        boundary_estimate: float | None = None
        if bracket is not None and last_reliable is not None:
            boundary_estimate = last_reliable.value
            for observation in observations:
                if observation.zone == "reliable":
                    if self.direction == "increase" and observation.value > boundary_estimate:
                        boundary_estimate = observation.value
                    if self.direction == "decrease" and observation.value < boundary_estimate:
                        boundary_estimate = observation.value

        return SearchResult(
            parameter=self.parameter,
            direction=self.direction,
            candidates=list(self.candidates),
            observations=observations,
            bracket=bracket,
            boundary_estimate=boundary_estimate,
            boundary_reached=bracket is not None,
            stop_reason=stop_reason,
            trace=trace,
        )
