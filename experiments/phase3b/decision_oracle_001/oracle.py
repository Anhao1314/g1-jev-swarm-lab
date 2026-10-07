"""Pure offline, evidence-gated Phase 3B.0 mode oracle; never actuates a robot."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

CONTRACT_ID = "phase3b0_fixed14s_oracle_v0"
RECOVERY_MODES = ("LATERAL_RECOVERY", "YAW_RECOVERY", "COMBINED_RECOVERY")
MODES = ("CONTINUE", *RECOVERY_MODES)
CONTEXT_FIELDS = frozenset(
    ("case_id", "seed", "decision_epoch", "skill", "transition", "alpha", "origin",
     "reference_id", "controller_id", "evaluator_id", "policy_id", "residual_bounds_id",
     "recovery_contract_id")
)
OBSERVABLE_FIELDS = frozenset(
    ("local_lateral_error_m", "local_heading_error_deg", "route_x_error_m",
     "route_y_error_m", "route_heading_error_deg", "reference_heading_deg",
     "instantaneous_strict_margin_m", "remaining_distance_m", "previous_recovery")
)
OUTCOME_FIELDS = frozenset(
    ("nominal", "physical", "all_strict", "final_world_x_error_m",
     "final_world_y_error_m", "final_lateral_error_m", "final_heading_error_deg",
     "endpoint_norm_m", "evidence_source")
)
TOLERANCE = 1e-10


def _exact_fields(value: Any, fields: frozenset[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} fields must equal {sorted(fields)}")


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite numeric")
    return float(value)


def validate_state(state: dict[str, Any]) -> None:
    """Reject unapproved fields, especially future treatment or endpoint outcomes."""
    _exact_fields(state, frozenset(("state_id", "context", "observables")), "state")
    if not isinstance(state["state_id"], str) or not state["state_id"]:
        raise ValueError("state_id must be nonempty")
    context, observed = state["context"], state["observables"]
    _exact_fields(context, CONTEXT_FIELDS, "context")
    _exact_fields(observed, OBSERVABLE_FIELDS, "observables")
    if context["recovery_contract_id"] != CONTRACT_ID:
        raise ValueError("recovery contract mismatch")
    if _finite(context["alpha"], "alpha") != 0.5 or context["origin"] != "actual-start":
        raise ValueError("alpha or origin outside contract")
    if isinstance(context["seed"], bool) or not isinstance(context["seed"], int):
        raise ValueError("seed must be integer")
    for key in CONTEXT_FIELDS - {"alpha", "seed"}:
        if not isinstance(context[key], str) or not context[key]:
            raise ValueError(f"{key} must be nonempty string")
    for key in OBSERVABLE_FIELDS - {"previous_recovery"}:
        _finite(observed[key], key)
    previous = observed["previous_recovery"]
    if previous is not None and previous not in MODES:
        raise ValueError("unknown previous recovery mode")
    if observed["remaining_distance_m"] < 0:
        raise ValueError("remaining distance must be nonnegative")


def context_fingerprint(context: dict[str, Any]) -> str:
    _exact_fields(context, CONTEXT_FIELDS, "context")
    raw = json.dumps(context, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def state_fingerprint(state: dict[str, Any]) -> str:
    """Bind outcomes to the full observed snapshot, not just a reusable state ID."""
    validate_state(state)
    raw = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _read_outcome(outcome: Any) -> dict[str, Any] | None:
    if outcome is None:
        return None
    _exact_fields(outcome, OUTCOME_FIELDS, "outcome")
    for key in ("nominal", "physical", "all_strict"):
        if not isinstance(outcome[key], bool):
            raise ValueError(f"{key} must be boolean")
    for key in OUTCOME_FIELDS - {"nominal", "physical", "all_strict", "evidence_source"}:
        _finite(outcome[key], key)
    if outcome["endpoint_norm_m"] < 0:
        raise ValueError("endpoint norm must be nonnegative")
    if not isinstance(outcome["evidence_source"], str) or not outcome["evidence_source"]:
        raise ValueError("evidence_source must be nonempty")
    return outcome


def _pass_gates(outcome: dict[str, Any]) -> bool:
    return outcome["nominal"] and outcome["physical"] and outcome["all_strict"]


def _global_gain(outcome: dict[str, Any], off: dict[str, Any]) -> bool:
    return (
        outcome["endpoint_norm_m"] < off["endpoint_norm_m"] - TOLERANCE
        and abs(outcome["final_lateral_error_m"]) <= abs(off["final_lateral_error_m"]) + TOLERANCE
        and abs(outcome["final_heading_error_deg"]) <= abs(off["final_heading_error_deg"]) + TOLERANCE
    )


def decide(state: dict[str, Any], catalog_entry: dict[str, Any] | None) -> dict[str, Any]:
    """Return a mode/reason from exact-matched, complete retained outcomes only.

    The catalog is an independent outcome table, never part of model-visible state.
    Missing cells cannot become inferred successes or least-bad selections.
    """
    validate_state(state)
    expected_context = context_fingerprint(state["context"])
    expected_state = state_fingerprint(state)
    if catalog_entry is None:
        return {"mode": "ABSTAIN", "reason": "MISSING_EVIDENCE"}
    _exact_fields(catalog_entry, frozenset(("state_id", "context_fingerprint", "state_fingerprint", "outcomes")), "catalog_entry")
    if (catalog_entry["state_id"] != state["state_id"]
            or catalog_entry["context_fingerprint"] != expected_context
            or catalog_entry["state_fingerprint"] != expected_state):
        return {"mode": "ABSTAIN", "reason": "CONTEXT_MISMATCH"}
    outcomes = catalog_entry["outcomes"]
    if not isinstance(outcomes, dict) or set(outcomes) - set(MODES):
        raise ValueError("outcomes must be a mode-keyed table")
    off = _read_outcome(outcomes.get("CONTINUE"))
    if off is None:
        return {"mode": "ABSTAIN", "reason": "MISSING_OFF_COMPARATOR"}
    if _pass_gates(off):
        return {"mode": "CONTINUE", "reason": "OFF_ADMISSIBLE"}
    if (state["context"]["skill"] != "Walk8m"
            or state["context"]["transition"] != "Stand->Walk8m"
            or state["context"]["decision_epoch"] != "first_walk_entry"):
        return {"mode": "ABSTAIN", "reason": "RECOVERY_OUT_OF_SCOPE"}
    eligible: list[str] = []
    missing = []
    for mode in RECOVERY_MODES:
        outcome = _read_outcome(outcomes.get(mode))
        if outcome is None:
            missing.append(mode)
        elif _pass_gates(outcome) and _global_gain(outcome, off):
            eligible.append(mode)
    if missing:
        return {"mode": "ABSTAIN", "reason": "MISSING_RECOVERY_EVIDENCE", "missing_modes": missing}
    if len(eligible) == 1:
        return {"mode": eligible[0], "reason": "UNIQUE_ADMISSIBLE_RECOVERY"}
    if eligible:
        return {"mode": "ABSTAIN", "reason": "AMBIGUOUS_ADMISSIBLE_RECOVERY", "admissible_modes": eligible}
    return {"mode": "ABSTAIN", "reason": "NO_ADMISSIBLE_RECOVERY"}
