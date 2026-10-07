"""Aggregation helpers for Phase 1 experiment summaries."""

from __future__ import annotations

from statistics import mean
from typing import Any, Iterable


def summarize_baseline_runs(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize Baseline-001 style runs (Stand -> Walk -> Stop).

    ``runs`` contain per-run metrics dicts with at least
    ``forward_displacement_m``, ``lateral_drift_m``, ``heading_error_deg`` and
    ``fallen``.
    """

    records = list(runs)
    successes = [record for record in records if record.get("success")]
    displacements = [
        float(record["forward_displacement_m"])
        for record in records
        if record.get("forward_displacement_m") is not None
    ]
    lateral = [
        float(record["lateral_drift_m"])
        for record in records
        if record.get("lateral_drift_m") is not None
    ]
    heading = [
        float(record["heading_error_deg"])
        for record in records
        if record.get("heading_error_deg") is not None
    ]
    fall_count = sum(
        1 for record in records if record.get("fallen") or record.get("fall_detected")
    )
    failures = [
        {
            "run_id": record.get("run_id"),
            "status": record.get("completion_status") or record.get("status"),
        }
        for record in records
        if not record.get("success")
    ]
    return {
        "runs": len(records),
        "successes": len(successes),
        "success_rate": (len(successes) / len(records)) if records else None,
        "displacement_mean_m": mean(displacements) if displacements else None,
        "displacement_min_m": min(displacements) if displacements else None,
        "displacement_max_m": max(displacements) if displacements else None,
        "lateral_drift_mean_m": mean(lateral) if lateral else None,
        "heading_error_mean_deg": mean(heading) if heading else None,
        "falls": fall_count,
        "failures": failures,
    }
