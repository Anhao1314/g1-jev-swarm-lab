"""Boundary search harness tests (deterministic, synthetic evaluators)."""

from __future__ import annotations

from g1swarm.boundary import BoundarySearch, Observation, classify_zone


def _observation(value: float, task_rate: float, n: int = 2) -> Observation:
    task_successes = int(round(task_rate * n))
    return Observation(
        value=value,
        n_runs=n,
        physical_successes=n,
        task_successes=task_successes,
        deterministic=False,
    )


def test_zone_thresholds_are_the_frozen_ones() -> None:
    assert classify_zone(1.0) == "reliable"
    assert classify_zone(0.90) == "reliable"
    assert classify_zone(0.89) == "transition"
    assert classify_zone(0.31) == "transition"
    assert classify_zone(0.30) == "failure"
    assert classify_zone(0.0) == "failure"


def test_increase_search_brackets_and_refines() -> None:
    boundary = 100.0
    calls: list[float] = []

    def evaluate(value: float, decision: str) -> Observation:
        calls.append(value)
        return _observation(value, 1.0 if value <= boundary else 0.0)

    search = BoundarySearch(
        parameter="force",
        safe_start=20.0,
        candidates=[40.0, 80.0, 160.0, 320.0],
        direction="increase",
        max_evaluations=8,
        refinement_rounds=2,
        resolution=5.0,
    )
    result = search.run(evaluate)
    assert result.boundary_reached
    assert result.bracket is not None
    low, high = result.bracket
    assert low <= boundary <= high
    assert result.boundary_estimate is not None and result.boundary_estimate <= boundary
    assert result.trace[0]["decision"] == "safe_start"
    assert any(entry["decision"] == "refine" for entry in result.trace)
    assert "force" == result.parameter

    second_calls: list[float] = []

    def evaluate_again(value: float, decision: str) -> Observation:
        second_calls.append(value)
        return _observation(value, 1.0 if value <= boundary else 0.0)

    BoundarySearch(
        parameter="force",
        safe_start=20.0,
        candidates=[40.0, 80.0, 160.0, 320.0],
        direction="increase",
        max_evaluations=8,
        refinement_rounds=2,
        resolution=5.0,
    ).run(evaluate_again)
    assert calls == second_calls


def test_decrease_search_brackets_the_transition() -> None:
    def evaluate(value: float, decision: str) -> Observation:
        return _observation(value, 1.0 if value >= 0.2 else 0.0)

    result = BoundarySearch(
        parameter="friction",
        safe_start=1.0,
        candidates=[0.5, 0.25, 0.125, 0.0625],
        direction="decrease",
        max_evaluations=8,
        refinement_rounds=2,
        resolution=0.01,
    ).run(evaluate)
    assert result.boundary_reached
    assert result.bracket is not None
    low, high = result.bracket
    assert low <= 0.2 <= high


def test_boundary_not_reached_is_reported() -> None:
    def evaluate(value: float, decision: str) -> Observation:
        return _observation(value, 1.0)

    result = BoundarySearch(
        parameter="distance",
        safe_start=5.0,
        candidates=[10.0, 20.0, 40.0],
        direction="increase",
        max_evaluations=10,
    ).run(evaluate)
    assert not result.boundary_reached
    assert result.bracket is None
    assert result.stop_reason in {"boundary_not_reached", "evaluation_budget_exhausted"}
    assert result.zones()["reliable"] == [5.0, 10.0, 20.0, 40.0]


def test_invalid_direction_is_rejected() -> None:
    try:
        BoundarySearch(parameter="x", safe_start=0.0, candidates=[1.0], direction="sideways")
    except ValueError as exc:
        assert "direction" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("invalid direction must raise")
