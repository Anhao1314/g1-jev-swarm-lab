"""Frozen descriptive scoring for the seen-evidence Jev strict-risk shadow.

Unavailable provider calls remain unavailable; they are never scored as a
correct prediction or a model abstention.  This module performs no I/O.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

VARIANTS = ("geometry_only", "geometry_plus_velocity")
RISK_THRESHOLD = 0.5
LOW_CONFIDENCE_BELOW = 0.6


def score(benchmark: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    units = benchmark["assessment_units"]
    expected = {
        (variant, unit["paired_unit_id"]): unit
        for variant in VARIANTS for unit in units[variant]
    }
    if any(len(units[v]) != 18 for v in VARIANTS) or len(expected) != 36:
        raise ValueError("expected 18 paired units in each frozen view")
    observed: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    for call in calls:
        key = (call["variant"], call["paired_unit_id"])
        if key not in expected or key in observed:
            raise ValueError("unknown or repeated assessment unit")
        observed.add(key)
        unit = expected[key]
        result = call["record"].get("result")
        available = bool(call["record"].get("availability"))
        if available != (result is not None):
            raise ValueError("availability/result mismatch")
        row = {
            "variant": key[0], "paired_unit_id": key[1],
            "strict_violation": bool(unit["strict_violation"]),
            "source_cell_ids": unit["source_cell_ids"],
            "source_case_ids": unit["source_case_ids"],
            "availability": available,
            "failure": call["record"].get("failure"),
            "latency_s": call["record"].get("latency_s"),
            "transport_attempts": call["record"].get("transport_attempts"),
        }
        if available:
            probability = result["probability_strict_violation"]
            confidence = result["confidence"]
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                       and math.isfinite(v) and 0 <= v <= 1
                       for v in (probability, confidence)):
                raise ValueError("invalid scored probability/confidence")
            predicted_risk = probability >= RISK_THRESHOLD
            actual_risk = row["strict_violation"]
            row.update({
                "probability_strict_violation": probability,
                "confidence": confidence,
                "typed_choice": result["choice"],
                "predicted_strict_violation": predicted_risk,
                "correct": predicted_risk == actual_risk,
                "false_safe": actual_risk and not predicted_risk,
                "false_alarm": not actual_risk and predicted_risk,
                "low_confidence": confidence < LOW_CONFIDENCE_BELOW,
                "brier": (probability - float(actual_risk)) ** 2,
                "reported_tokens": result["usage"],
                "model": result["model"],
            })
        rows.append(row)
    summaries: dict[str, Any] = {}
    for variant in VARIANTS:
        subset = [r for r in rows if r["variant"] == variant]
        usable = [r for r in subset if r["availability"]]
        risk = [r for r in usable if r["strict_violation"]]
        safe = [r for r in usable if not r["strict_violation"]]
        latency = [r["latency_s"] for r in subset if isinstance(r["latency_s"], (int, float))]
        summaries[variant] = {
            "expected": len(units[variant]), "attempted": len(subset),
            "available": len(usable), "unavailable": len(subset) - len(usable),
            "not_attempted": len(units[variant]) - len(subset),
            "accuracy": sum(r["correct"] for r in usable) / len(usable) if usable else None,
            "false_safe_count": sum(r["false_safe"] for r in usable),
            "false_safe_rate_on_available_risk": sum(r["false_safe"] for r in risk) / len(risk) if risk else None,
            "false_alarm_count": sum(r["false_alarm"] for r in usable),
            "false_alarm_rate_on_available_safe": sum(r["false_alarm"] for r in safe) / len(safe) if safe else None,
            "low_confidence_count": sum(r["low_confidence"] for r in usable),
            "brier_mean": statistics.mean(r["brier"] for r in usable) if usable else None,
            "latency_median_s": statistics.median(latency) if latency else None,
            "latency_all_attempts_s": latency,
            "reported_input_tokens": sum(r["reported_tokens"]["input_tokens"] for r in usable),
            "reported_output_tokens": sum(r["reported_tokens"]["output_tokens"] for r in usable),
            "transport_attempts": sum(r["transport_attempts"] or 0 for r in subset),
            "failure_counts": {reason: sum(r["failure"] == reason for r in subset)
                               for reason in sorted({r["failure"] for r in subset if r["failure"]})},
        }
    return {
        "schema": "phase3b1_jev_risk_score_v1",
        "threshold": RISK_THRESHOLD,
        "low_confidence_below": LOW_CONFIDENCE_BELOW,
        "seen_development_only": True,
        "rows": rows,
        "summary": summaries,
        "limitations": "Descriptive n=18 per view, correlated case clusters; no held-out or stable calibration/P95 claim.",
    }
