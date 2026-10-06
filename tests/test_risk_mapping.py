"""Risk label mapping tests (frozen deterministic rules)."""

from __future__ import annotations

from g1swarm.boundary import RiskEvidence, RiskLevel, risk_label, risk_label_for_observation


def _evidence(**overrides) -> RiskEvidence:
    values = dict(
        n_runs=6,
        deterministic=False,
        physical_success_rate=1.0,
        task_success_rate=1.0,
        strict_violation_rate=0.0,
    )
    values.update(overrides)
    return RiskEvidence(**values)


def test_low_requires_sufficient_reliable_evidence() -> None:
    assert risk_label(_evidence()) is RiskLevel.LOW
    assert risk_label(_evidence(n_runs=6, deterministic=True)) is RiskLevel.LOW
    assert risk_label(_evidence(n_runs=3, deterministic=True)) is RiskLevel.LOW
    assert risk_label(_evidence(n_runs=5, strict_violation_rate=0.2)) is RiskLevel.MEDIUM


def test_medium_transition_region() -> None:
    assert risk_label(_evidence(task_success_rate=0.8)) is RiskLevel.MEDIUM
    assert risk_label(_evidence(task_success_rate=0.5)) is RiskLevel.MEDIUM


def test_high_failure_region() -> None:
    assert risk_label(_evidence(task_success_rate=0.2)) is RiskLevel.HIGH
    assert risk_label(_evidence(physical_success_rate=0.8)) is RiskLevel.HIGH


def test_unknown_when_evidence_is_insufficient() -> None:
    assert risk_label(_evidence(n_runs=2)) is RiskLevel.UNKNOWN
    assert risk_label(_evidence(n_runs=4, deterministic=False)) is RiskLevel.UNKNOWN
    assert risk_label(_evidence(physical_success_rate=None)) is RiskLevel.UNKNOWN
    assert risk_label(_evidence(task_success_rate=None)) is RiskLevel.UNKNOWN


def test_deterministic_evidence_counts_one_independent_sample() -> None:
    evidence = _evidence(n_runs=6, deterministic=True)
    assert evidence.independent_samples == 1
    assert evidence.to_dict()["independent_samples"] == 1


def test_risk_label_for_serialized_observation() -> None:
    observation = {
        "n_runs": 10,
        "deterministic": False,
        "physical_success_rate": 1.0,
        "task_success_rate": 0.1,
        "metrics": {"strict_violation_rate": 1.0},
        "failure_counts": {"FALL": 9},
    }
    assert risk_label_for_observation(observation) is RiskLevel.HIGH
