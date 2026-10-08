"""Canonical, audit-hardened metrics schema for Phase 1.3.

The Phase 1.2b audit found that two experiment paths fed the shared walk
envelope evaluator differently-named metric keys; the missing keys silently
defaulted to ``+inf`` and produced spurious failures.

This module makes the canonical names the only keys the evaluator accepts:

* canonical required keys live in ``REQUIRED_METRICS``;
* known historical aliases (``final_*``, ``absolute_*``, ``completion_*``,
  ``segment_*``) are canonicalized before evaluation;
* a missing required metric raises ``MissingMetricError`` - there is no silent
  fallback of any kind.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

REQUIRED_METRICS = (
    "forward_displacement_m",
    "distance_error_m",
    "lateral_drift_m",
    "heading_error_deg",
    "simulation_time_s",
    "physical_success",
    "task_success",
    "failure_type",
    "failure_reason",
)

ENVELOPE_REQUIRED = (
    "distance_error_m",
    "lateral_drift_m",
    "heading_error_deg",
    "simulation_time_s",
)

NULLABLE_METRICS = ("failure_reason",)

ALIASES = {
    "absolute_distance_error_m": "distance_error_m",
    "completion_sim_time_s": "simulation_time_s",
    "total_simulation_time_s": "simulation_time_s",
    "final_forward_progress_m": "forward_displacement_m",
    "final_lateral_drift_m": "lateral_drift_m",
    "final_heading_error_deg": "heading_error_deg",
    "segment_lateral_drift_m": "lateral_drift_m",
    "segment_heading_error_deg": "heading_error_deg",
}


def _is_missing_value(key: str, value: Any) -> bool:
    if value is None:
        return key not in NULLABLE_METRICS
    return isinstance(value, float) and not math.isfinite(value)


class MissingMetricError(ValueError):
    """A required canonical metric is absent (or non-finite)."""

    def __init__(self, missing: list[str], available: list[str]) -> None:
        self.missing = list(missing)
        self.available = list(available)
        super().__init__(
            "missing required canonical metrics: "
            + ", ".join(missing)
            + f" (available: {', '.join(available) or 'none'})"
        )


def canonicalize(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Rename known aliases to canonical keys; canonical keys win on conflict."""

    canonical: dict[str, Any] = {}
    for key, value in metrics.items():
        target = ALIASES.get(key)
        if target is not None:
            canonical.setdefault(target, value)
    for key, value in metrics.items():
        if key not in ALIASES:
            canonical[key] = value
    return canonical


def require_canonical(
    metrics: Mapping[str, Any], required: tuple[str, ...] = REQUIRED_METRICS
) -> dict[str, Any]:
    """Return the canonical view, raising when a required metric is missing."""

    canonical = canonicalize(metrics)
    missing = [
        key
        for key in required
        if key not in canonical or _is_missing_value(key, canonical[key])
    ]
    if missing:
        raise MissingMetricError(missing, sorted(canonical))
    return canonical


def envelope_input(metrics: Mapping[str, Any]) -> dict[str, float]:
    """Canonical view with the key names the walk envelope reads internally."""

    canonical = require_canonical(metrics, ENVELOPE_REQUIRED)
    return {
        "absolute_distance_error_m": float(canonical["distance_error_m"]),
        "lateral_drift_m": float(canonical["lateral_drift_m"]),
        "heading_error_deg": float(canonical["heading_error_deg"]),
        "completion_sim_time_s": float(canonical["simulation_time_s"]),
    }


@dataclass(frozen=True)
class RunMetrics:
    """Canonical metrics record; extra fields are experiment-specific."""

    forward_displacement_m: float
    distance_error_m: float
    lateral_drift_m: float
    heading_error_deg: float
    simulation_time_s: float
    physical_success: bool
    task_success: bool
    failure_type: str
    failure_reason: str | None
    target_distance_m: float | None = None
    max_abs_lateral_error_m: float | None = None
    max_abs_heading_error_deg: float | None = None
    wall_time_s: float | None = None
    mean_forward_speed_mps: float | None = None
    final_speed_mps: float | None = None
    correction_rms: float | None = None
    correction_max_abs: float | None = None
    saturation_count: int = 0
    saturation_fraction: float = 0.0
    control_oscillation_count: int = 0
    controller_memory_resets: int = 0
    policy_hash: str | None = None
    controller_version: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        missing = [
            key for key in REQUIRED_METRICS if _is_missing_value(key, getattr(self, key))
        ]
        if missing:
            raise MissingMetricError(missing, sorted(self.to_dict()))
        for key in (
            "forward_displacement_m",
            "distance_error_m",
            "lateral_drift_m",
            "heading_error_deg",
            "simulation_time_s",
        ):
            if not math.isfinite(float(getattr(self, key))):
                raise MissingMetricError([key], sorted(self.to_dict()))
        if not str(self.failure_type):
            raise ValueError("failure_type must be a non-empty string")

    def to_dict(self, *, include_aliases: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        extras = payload.pop("extras", {})
        payload.update(extras)
        if include_aliases:
            payload.setdefault("final_forward_progress_m", self.forward_displacement_m)
            payload.setdefault("final_lateral_drift_m", self.lateral_drift_m)
            payload.setdefault("final_heading_error_deg", self.heading_error_deg)
            payload.setdefault("absolute_distance_error_m", self.distance_error_m)
            payload.setdefault("completion_sim_time_s", self.simulation_time_s)
        return payload
