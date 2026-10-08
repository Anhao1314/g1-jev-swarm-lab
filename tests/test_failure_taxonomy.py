"""Failure taxonomy classification tests."""

from __future__ import annotations

from g1swarm.characterization import FailureType, classify_failure
from g1swarm.skills import SkillStatus


def test_success() -> None:
    assessment = classify_failure(status=SkillStatus.SUCCESS)
    assert assessment.failure_type is FailureType.SUCCESS
    assert assessment.ok
    assert assessment.to_dict()["failure_reason"] is None


def test_fall_precedence_over_distance() -> None:
    assessment = classify_failure(
        status=SkillStatus.SUCCESS, fall=True, distance_error=1.0, distance_tolerance=0.2
    )
    assert assessment.failure_type is FailureType.FALL
    assert assessment.reason


def test_timeout() -> None:
    assessment = classify_failure(status=SkillStatus.TIMEOUT)
    assert assessment.failure_type is FailureType.TIMEOUT


def test_distance_error() -> None:
    assessment = classify_failure(
        status=SkillStatus.SUCCESS, distance_error=0.31, distance_tolerance=0.2
    )
    assert assessment.failure_type is FailureType.DISTANCE_ERROR
    assert "0.310" in (assessment.reason or "")


def test_heading_error() -> None:
    assessment = classify_failure(
        status=SkillStatus.SUCCESS, heading_error_deg=20.0, heading_tolerance_deg=15.0
    )
    assert assessment.failure_type is FailureType.HEADING_ERROR


def test_failed_to_stop() -> None:
    assessment = classify_failure(status=SkillStatus.SUCCESS, failed_to_stop=True)
    assert assessment.failure_type is FailureType.FAILED_TO_STOP


def test_precondition_and_unavailable() -> None:
    assert (
        classify_failure(status=SkillStatus.PRECONDITION_FAILED).failure_type
        is FailureType.PRECONDITION_FAILED
    )
    assert (
        classify_failure(status=SkillStatus.NOT_AVAILABLE).failure_type
        is FailureType.SKILL_UNAVAILABLE
    )
    assert (
        classify_failure(status=SkillStatus.INTERRUPTED).failure_type
        is FailureType.INTERRUPTED
    )


def test_non_finite_and_invalid_control_take_priority() -> None:
    assert (
        classify_failure(status=SkillStatus.SUCCESS, finite=False, fall=True).failure_type
        is FailureType.NON_FINITE_STATE
    )
    assert (
        classify_failure(status=SkillStatus.SUCCESS, control_invalid=True).failure_type
        is FailureType.INVALID_CONTROL
    )


def test_unclassified_failure_is_explicit() -> None:
    assessment = classify_failure(status=SkillStatus.FAILURE, reason="controller exploded")
    assert assessment.failure_type is FailureType.UNKNOWN_FAILURE
    assert assessment.reason == "controller exploded"
