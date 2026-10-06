"""Failure taxonomy for skill characterization.

Every failed run must carry a specific ``failure_type`` plus a human-readable
``failure_reason`` - never a bare FAILURE.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..skills.contract import SkillStatus


class FailureType(str, Enum):
    SUCCESS = "SUCCESS"
    FALL = "FALL"
    TIMEOUT = "TIMEOUT"
    DISTANCE_ERROR = "DISTANCE_ERROR"
    HEADING_ERROR = "HEADING_ERROR"
    EXCESSIVE_DRIFT = "EXCESSIVE_DRIFT"
    FAILED_TO_STOP = "FAILED_TO_STOP"
    UNSTABLE = "UNSTABLE"
    NON_FINITE_STATE = "NON_FINITE_STATE"
    INVALID_CONTROL = "INVALID_CONTROL"
    SKILL_UNAVAILABLE = "SKILL_UNAVAILABLE"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    INTERRUPTED = "INTERRUPTED"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


@dataclass(frozen=True)
class FailureAssessment:
    failure_type: FailureType
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.failure_type is FailureType.SUCCESS

    def to_dict(self) -> dict[str, str | None]:
        return {"failure_type": self.failure_type.value, "failure_reason": self.reason}


def classify_failure(
    *,
    status: SkillStatus,
    fall: bool = False,
    finite: bool = True,
    timeout: bool = False,
    control_invalid: bool = False,
    distance_error: float | None = None,
    distance_tolerance: float | None = None,
    heading_error_deg: float | None = None,
    heading_tolerance_deg: float | None = None,
    failed_to_stop: bool = False,
    drift_exceeded: bool = False,
    unstable: bool = False,
    reason: str | None = None,
) -> FailureAssessment:
    """Map measured outcomes onto the failure taxonomy (ordered by severity)."""

    if control_invalid:
        return FailureAssessment(FailureType.INVALID_CONTROL, reason or "invalid control input")
    if not finite:
        return FailureAssessment(FailureType.NON_FINITE_STATE, reason or "non-finite robot state")
    if status is SkillStatus.PRECONDITION_FAILED:
        return FailureAssessment(FailureType.PRECONDITION_FAILED, reason or "skill preconditions not met")
    if status is SkillStatus.NOT_AVAILABLE:
        return FailureAssessment(FailureType.SKILL_UNAVAILABLE, reason or "skill not available")
    if status is SkillStatus.INTERRUPTED:
        return FailureAssessment(FailureType.INTERRUPTED, reason or "skill interrupted")
    if fall or status is SkillStatus.UNSAFE:
        return FailureAssessment(FailureType.FALL, reason or "fall or unsafe state detected")
    if timeout or status is SkillStatus.TIMEOUT:
        return FailureAssessment(FailureType.TIMEOUT, reason or "skill timed out")
    if (
        distance_error is not None
        and distance_tolerance is not None
        and distance_error > distance_tolerance
    ):
        return FailureAssessment(
            FailureType.DISTANCE_ERROR,
            reason
            or f"distance error {distance_error:.3f} m exceeds tolerance {distance_tolerance:.3f} m",
        )
    if (
        heading_error_deg is not None
        and heading_tolerance_deg is not None
        and heading_error_deg > heading_tolerance_deg
    ):
        return FailureAssessment(
            FailureType.HEADING_ERROR,
            reason
            or f"heading error {heading_error_deg:.2f} deg exceeds tolerance {heading_tolerance_deg:.2f} deg",
        )
    if failed_to_stop:
        return FailureAssessment(FailureType.FAILED_TO_STOP, reason or "stop threshold not sustained")
    if drift_exceeded:
        return FailureAssessment(FailureType.EXCESSIVE_DRIFT, reason or "excessive drift")
    if unstable:
        return FailureAssessment(FailureType.UNSTABLE, reason or "robot unstable at the end of the run")
    if status is SkillStatus.SUCCESS:
        return FailureAssessment(FailureType.SUCCESS, None)
    return FailureAssessment(FailureType.UNKNOWN_FAILURE, reason or "unclassified failure")
