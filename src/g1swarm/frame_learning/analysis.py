"""Prospectively fixed, offline same-frame PPO analysis.

The input is the 252 primary episodes only. Original scores are never changed;
fresh transition cases and seen regression cases remain separate. Signs are
descriptive paired observations, without significance tests or seed selection.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
from statistics import mean
from typing import Any, Mapping, Sequence

from ..transition_learning.analysis import _case_metrics, summarize_results
from .cases import HELDOUT_CASES, REGRESSION_CASES
from .env import arm_label


ALPHAS = (0.0, 0.5)
SEEDS = (11, 29)
FAMILIES = ("walk_to_turn", "turn_to_walk", "walk_to_stop", "stand_to_walk")
SPLITS = ("fresh_heldout", "seen_regression")
CASES = {case["id"]: case for case in (*HELDOUT_CASES, *REGRESSION_CASES)}
FRESH_IDS = frozenset(case["id"] for case in HELDOUT_CASES)

# These are reporting directions, not new thresholds or a joint objective.
# Duration and speed changes are reported without calling them improvements.
TARGET_DIRECTIONS = {
    "abs_local_heading_error_deg": -1,
    "abs_local_lateral_drift_m": -1,
    "abs_ideal_heading_error_deg": -1,
    "abs_ideal_lateral_error_m": -1,
    "duration_s": None,
    "max_tilt_deg": -1,
    "min_height_m": 1,
    "window_duration_s": None,
    "completion_duration_s": None,
    "window_lateral_change_m": None,
    "window_heading_change_deg": None,
    "window_max_tilt_deg": -1,
    "window_min_height_m": 1,
    "window_speed_rms_mps": None,
    "window_final_speed_mps": None,
    "next_skill_final_speed_mps": None,
    "window_angular_speed_rms_radps": None,
    "window_standing_fraction": 1,
    "sustained_tracking_recovery_s": -1,
}
CASE_DIRECTIONS = {
    name: (-1 if "abs_" in name or name.endswith("tilt_deg") else
           1 if name in ("minimum_height_m", "transition_minimum_height_m",
                         "transition_mean_standing_fraction") else None)
    for name in _case_metrics({})
}
CASE_DIRECTIONS.update({
    "final_abs_ideal_lateral_error_m": -1,
    "final_abs_ideal_heading_error_deg": -1,
    "ideal_endpoint_error_m": -1,
})
METADATA_KEYS = frozenset({
    "treatment", "treatment_label", "provenance", "checkpoint", "phase",
    "repetition", "evaluation_set", "residual_enabled", "PPO_training",
    "learned_policy_configured", "policy_decision_calls", "wall_time_s",
    "elapsed_wall_time_s", "recorded_at",
})


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else None


def _stats(values: Sequence[Any]) -> dict:
    finite = [value for raw in values if (value := _number(raw)) is not None]
    return {"n": len(finite), "missing_or_non_finite": len(values) - len(finite),
            "mean": mean(finite) if finite else None,
            "min": min(finite) if finite else None,
            "max": max(finite) if finite else None}


def _abs(value: Any) -> float | None:
    parsed = _number(value)
    return abs(parsed) if parsed is not None else None


def _physical_payload(value: Any) -> Any:
    """Discard acquisition/treatment metadata; retain every physical diagnostic."""
    if isinstance(value, Mapping):
        return {key: _physical_payload(item) for key, item in value.items() if key not in METADATA_KEYS}
    if isinstance(value, list):
        return [_physical_payload(item) for item in value]
    return value


def _strict_case(record: Mapping) -> bool | None:
    nodes = record.get("nodes", [])
    if any(node.get("strict_success") is False for node in nodes):
        return False
    if len(nodes) == len(CASES[record["case_id"]]["nodes"]) and all(node.get("strict_success") is True for node in nodes):
        return True
    return None


def _strict_summary(records: Sequence[Mapping]) -> dict:
    nodes = [(record, i, node) for record in records for i, node in enumerate(record.get("nodes", []))]
    expected = sum(len(CASES[record["case_id"]]["nodes"]) for record in records)
    states = [_strict_case(record) for record in records]
    failures = [{"case_id": record["case_id"], "node_index": i, "skill": node["skill"],
                 "strict_success": node.get("strict_success"), "task_success": node.get("task_success"),
                 "physical_success": node.get("physical_success"),
                 "strict_envelope": (node.get("envelope") or {}).get("strict_envelope")}
                for record, i, node in nodes if node.get("strict_success") is not True]
    return {"expected_nodes": expected, "observed_nodes": len(nodes),
            "unobserved_nodes": expected - len(nodes),
            "original_node_strict_pass": sum(node.get("strict_success") is True for _, _, node in nodes),
            "original_node_strict_fail": sum(node.get("strict_success") is False for _, _, node in nodes),
            "original_node_strict_missing": sum(node.get("strict_success") not in (True, False) for _, _, node in nodes),
            "derived_case_all_nodes_strict_pass": sum(value is True for value in states),
            "derived_case_any_node_strict_fail": sum(value is False for value in states),
            "derived_case_strict_unknown": sum(value is None for value in states),
            "failures": failures}


def _target_metrics(record: Mapping) -> dict:
    nodes = record.get("nodes", [])
    target = nodes[1] if record.get("group") == "transition" and len(nodes) > 1 else {}
    window = target.get("transition_metrics") or {}
    return {
        "abs_local_heading_error_deg": _abs(target.get("heading_error_deg")),
        "abs_local_lateral_drift_m": _abs(target.get("lateral_drift_m")),
        "abs_ideal_heading_error_deg": _abs(target.get("ideal_path_heading_error_deg")),
        "abs_ideal_lateral_error_m": _abs(target.get("ideal_path_lateral_error_m")),
        "duration_s": _number(target.get("duration_s")),
        "max_tilt_deg": _number(target.get("max_tilt_deg")),
        "min_height_m": _number(target.get("min_height_m")),
        "window_duration_s": _number(window.get("duration_s")),
        "completion_duration_s": _number(window.get("completion_duration_s")),
        "window_lateral_change_m": _number(window.get("lateral_change_m")),
        "window_heading_change_deg": _number(window.get("heading_change_deg")),
        "window_max_tilt_deg": _number(window.get("max_tilt_deg")),
        "window_min_height_m": _number(window.get("min_height_m")),
        "window_speed_rms_mps": _number(window.get("speed_rms_mps")),
        "window_final_speed_mps": _number(window.get("final_speed_mps")),
        "next_skill_final_speed_mps": _number(window.get("next_skill_final_speed_mps")),
        "window_angular_speed_rms_radps": _number(window.get("angular_speed_rms_radps")),
        "window_standing_fraction": _number(window.get("standing_fraction")),
        "sustained_tracking_recovery_s": _number(window.get("sustained_tracking_recovery_s")),
    }


def _metrics(record: Mapping) -> dict:
    nodes = record.get("nodes", [])
    final = nodes[-1] if nodes else {}
    return {**_case_metrics(record),
            "final_abs_ideal_lateral_error_m": _abs(final.get("ideal_path_lateral_error_m")),
            "final_abs_ideal_heading_error_deg": _abs(final.get("ideal_path_heading_error_deg")),
            "ideal_endpoint_error_m": _number(record.get("ideal_endpoint_error_m"))}


def _metric_summary(records: Sequence[Mapping], target: bool = False) -> dict:
    getter = _target_metrics if target else _metrics
    names = TARGET_DIRECTIONS if target else CASE_DIRECTIONS
    values = [getter(record) for record in records]
    return {name: _stats([row[name] for row in values]) for name in names}


def _sequence(record: Mapping) -> dict:
    nodes = record.get("nodes", [])
    final = nodes[-1] if nodes else {}
    first8 = next(((i, node) for i, node in enumerate(nodes)
                   if node.get("skill") == "walk_forward" and node.get("parameters", {}).get("target_distance_m") == 8), None)
    eight = None
    if first8:
        i, node = first8
        eight = {"node_index": i, "local_lateral_drift_m": node.get("lateral_drift_m"),
                 "abs_local_lateral_drift_m": _abs(node.get("lateral_drift_m")),
                 "local_heading_error_deg": node.get("heading_error_deg"),
                 "nominal_task_success": node.get("task_success"), "strict_success": node.get("strict_success"),
                 "duration_s": node.get("duration_s"), "envelope": node.get("envelope")}
    windows = [{"node_index": i, "skill": node["skill"], "duration_s": node.get("duration_s"),
                "window_duration_s": (node.get("transition_metrics") or {}).get("duration_s"),
                "completion_duration_s": (node.get("transition_metrics") or {}).get("completion_duration_s"),
                "completion_after_authority_window": _number(node.get("duration_s")) > 2
                if _number(node.get("duration_s")) is not None else None}
               for i, node in enumerate(nodes) if (node.get("transition_metrics") or {}).get("eligible") is True]
    return {"case_id": record["case_id"], "task_success": record.get("task_success"),
            "physical_success": record.get("physical_success"), "all_nodes_strict_success": _strict_case(record),
            "final_signed_ideal_lateral_error_m": _number(final.get("ideal_path_lateral_error_m")),
            "final_abs_ideal_lateral_error_m": _abs(final.get("ideal_path_lateral_error_m")),
            "final_signed_ideal_heading_error_deg": _number(final.get("ideal_path_heading_error_deg")),
            "final_abs_ideal_heading_error_deg": _abs(final.get("ideal_path_heading_error_deg")),
            "ideal_endpoint_error_m": _number(record.get("ideal_endpoint_error_m")),
            "total_sim_time_s": record.get("total_sim_time_s"),
            "completed_nodes": len(nodes), "expected_nodes": len(CASES[record["case_id"]]["nodes"]),
            "first_8m_walk": eight, "eligible_transition_windows": windows}


def _delta_metrics(baseline: dict, candidate: dict) -> dict:
    return {name: {"baseline": value, "candidate": candidate[name],
                   "candidate_minus_baseline": candidate[name] - value
                   if value is not None and candidate[name] is not None else None}
            for name, value in baseline.items()}


def _score_change(baseline: Any, candidate: Any) -> str:
    if baseline not in (True, False) or candidate not in (True, False):
        return "unknown"
    return ("PASS" if baseline else "FAIL") + "_to_" + ("PASS" if candidate else "FAIL")


def _pair(baseline: Mapping, candidate: Mapping) -> dict:
    bn, cn = baseline.get("nodes", []), candidate.get("nodes", [])
    nodes = []
    for i in range(max(len(bn), len(cn))):
        b, c = (bn[i] if i < len(bn) else {}), (cn[i] if i < len(cn) else {})
        nodes.append({"node_index": i, "skill": b.get("skill") or c.get("skill"),
                      "baseline_observed": bool(b), "candidate_observed": bool(c),
                      "nominal_change": _score_change(b.get("task_success"), c.get("task_success")),
                      "physical_change": _score_change(b.get("physical_success"), c.get("physical_success")),
                      "strict_change": _score_change(b.get("strict_success"), c.get("strict_success"))})
    return {"case_id": candidate["case_id"], "evaluation_set": candidate["evaluation_set"],
            "group": candidate["group"], "transition": candidate.get("transition"),
            "nominal_change": _score_change(baseline.get("task_success"), candidate.get("task_success")),
            "physical_change": _score_change(baseline.get("physical_success"), candidate.get("physical_success")),
            "derived_all_nodes_strict_change": _score_change(_strict_case(baseline), _strict_case(candidate)),
            "metrics": _delta_metrics(_metrics(baseline), _metrics(candidate)),
            "target_node_metrics": _delta_metrics(_target_metrics(baseline), _target_metrics(candidate)),
            "node_score_changes": nodes,
            "primitive_physical_exact": _physical_payload(baseline) == _physical_payload(candidate)
            if candidate["group"] == "primitive" else None}


def _pair_summary(pairs: Sequence[Mapping]) -> dict:
    changes = {name: dict(Counter(pair[name] for pair in pairs))
               for name in ("nominal_change", "physical_change", "derived_all_nodes_strict_change")}
    strict_nodes = [node for pair in pairs for node in pair["node_score_changes"]]
    return {"paired_cases": len(pairs), "score_changes": changes,
            "original_node_strict_changes": dict(Counter(node["strict_change"] for node in strict_nodes)),
            "metric_deltas": {name: _stats([pair["metrics"][name]["candidate_minus_baseline"] for pair in pairs])
                              for name in CASE_DIRECTIONS},
            "target_node_metric_deltas": {name: _stats([pair["target_node_metrics"][name]["candidate_minus_baseline"] for pair in pairs])
                                          for name in TARGET_DIRECTIONS}}


def _sign(value: float | None) -> str:
    return "missing" if value is None else "decrease" if value < 0 else "increase" if value > 0 else "unchanged"


def _concordance(pairs11: Sequence[Mapping], pairs29: Sequence[Mapping], target: bool = False) -> dict:
    left, right = {pair["case_id"]: pair for pair in pairs11}, {pair["case_id"]: pair for pair in pairs29}
    directions = TARGET_DIRECTIONS if target else CASE_DIRECTIONS
    field = "target_node_metrics" if target else "metrics"
    result = {}
    for name, favorable in directions.items():
        rows = []
        for identifier in sorted(set(left) & set(right)):
            a = left[identifier][field][name]["candidate_minus_baseline"]
            b = right[identifier][field][name]["candidate_minus_baseline"]
            sa, sb = _sign(a), _sign(b)
            rows.append({"case_id": identifier, "seed11_delta": a, "seed29_delta": b,
                         "seed11_direction": sa, "seed29_direction": sb,
                         "direction_agrees": sa == sb if "missing" not in (sa, sb) else None,
                         "both_favorable": favorable * a > 0 and favorable * b > 0
                         if favorable is not None and a is not None and b is not None else None})
        result[name] = {"declared_favorable_direction": favorable,
                        "paired_cases": len(rows),
                        "complete_two_seed_deltas": sum(row["direction_agrees"] is not None for row in rows),
                        "direction_agreement_count": sum(row["direction_agrees"] is True for row in rows),
                        "both_decreased_count": sum(row["seed11_direction"] == row["seed29_direction"] == "decrease" for row in rows),
                        "both_increased_count": sum(row["seed11_direction"] == row["seed29_direction"] == "increase" for row in rows),
                        "both_unchanged_count": sum(row["seed11_direction"] == row["seed29_direction"] == "unchanged" for row in rows),
                        "both_favorable_count": sum(row["both_favorable"] is True for row in rows) if favorable is not None else None,
                        "cases": rows}
    return result


def _validate(records: Sequence[Mapping]) -> dict:
    if len(records) != 252 or any(record.get("phase") != "primary" for record in records):
        raise ValueError("Analysis requires exactly 252 primary records; repeats must be excluded")
    expected = {arm_label(alpha, seed): (alpha, seed) for alpha in ALPHAS for seed in (None, *SEEDS)}
    index = {label: {} for label in expected}
    for record in records:
        label, identifier = record.get("treatment_label"), record.get("case_id")
        if label not in expected or identifier not in CASES or identifier in index[label]:
            raise ValueError(f"Invalid or duplicate arm/case: {label}/{identifier}")
        alpha, seed = expected[label]
        split = "fresh_heldout" if identifier in FRESH_IDS else "seen_regression"
        case = CASES[identifier]
        if record.get("heading_alignment_alpha") != alpha or record.get("evaluation_set") != split:
            raise ValueError(f"Frame/split mismatch: {label}/{identifier}")
        if (record.get("checkpoint") is None) != (seed is None):
            raise ValueError(f"Baseline/checkpoint mismatch: {label}/{identifier}")
        if record.get("group") != case["group"] or record.get("transition") != case.get("transition"):
            raise ValueError(f"Case metadata mismatch: {label}/{identifier}")
        nodes = record.get("nodes", [])
        if len(nodes) > len(case["nodes"]):
            raise ValueError(f"Too many observed nodes: {label}/{identifier}")
        for node, planned in zip(nodes, case["nodes"]):
            if node.get("skill") != planned["skill"] or node.get("parameters") != planned["parameters"]:
                raise ValueError(f"Node recipe mismatch: {label}/{identifier}")
        index[label][identifier] = record
    if any(set(values) != set(CASES) for values in index.values()):
        raise ValueError("Every arm must contain all 16 fresh and 26 seen cases")
    return index


def analyze(records: Sequence[Mapping[str, Any]]) -> dict:
    """Analyze six fixed arms without pooling repeats, seeds, or frame effects."""
    index = _validate(records)
    summary = summarize_results(records)
    arms, comparisons, concordance = {}, {}, {}
    for label, indexed in sorted(index.items()):
        values = list(indexed.values())
        arms[label] = {
            "original_summary": summary["by_treatment"][label],
            "strict": _strict_summary(values),
            "by_evaluation_set": {split: {
                "strict": _strict_summary([r for r in values if r["evaluation_set"] == split]),
                "metrics": _metric_summary([r for r in values if r["evaluation_set"] == split]),
                "transition_target_by_family": {family: {
                    "case_ids": [r["case_id"] for r in values if r["evaluation_set"] == split and r.get("transition") == family],
                    "metrics": _metric_summary([r for r in values if r["evaluation_set"] == split and r.get("transition") == family], target=True),
                } for family in FAMILIES},
            } for split in SPLITS},
            "sequences": {r["case_id"]: _sequence(r) for r in values if r["group"] == "sequence"},
            "original_failures": [{"case_id": r["case_id"], "task_success": r["task_success"],
                                   "physical_success": r["physical_success"], "failure_taxonomy": r.get("failure_taxonomy"),
                                   "nodes": [{"node_index": i, **{key: node.get(key) for key in
                                       ("skill", "status", "reason", "task_success", "physical_success", "strict_success", "violations", "envelope")}}
                                       for i, node in enumerate(r.get("nodes", [])) if node.get("task_success") is not True or node.get("physical_success") is not True or node.get("strict_success") is not True]}
                                  for r in values if r.get("task_success") is not True or r.get("physical_success") is not True or _strict_case(r) is not True],
        }
    for alpha in ALPHAS:
        baseline_label = arm_label(alpha)
        baseline = index[baseline_label]
        by_seed = {}
        for seed in SEEDS:
            label = arm_label(alpha, seed)
            pairs = [_pair(baseline[identifier], index[label][identifier]) for identifier in sorted(CASES)]
            by_seed[seed] = pairs
            primitives = [pair for pair in pairs if pair["group"] == "primitive"]
            comparisons[label] = {
                "baseline_arm": baseline_label, "candidate_arm": label,
                "delta_convention": "learned minus its own same-frame residual-off baseline",
                "overall": _pair_summary(pairs),
                "by_evaluation_set": {split: _pair_summary([p for p in pairs if p["evaluation_set"] == split]) for split in SPLITS},
                "fresh_target_by_family": {family: _pair_summary([p for p in pairs if p["evaluation_set"] == "fresh_heldout" and p["transition"] == family]) for family in FAMILIES},
                "primitive_physical_identity": {"cases": len(primitives),
                    "exact_count": sum(p["primitive_physical_exact"] is True for p in primitives),
                    "mismatch_ids": [p["case_id"] for p in primitives if p["primitive_physical_exact"] is not True]},
                "pairs": pairs,
            }
        left, right = by_seed[11], by_seed[29]
        concordance[str(alpha)] = {
            "baseline_arm": baseline_label,
            "by_evaluation_set": {split: _concordance([p for p in left if p["evaluation_set"] == split], [p for p in right if p["evaluation_set"] == split]) for split in SPLITS},
            "fresh_target_by_family": {family: _concordance([p for p in left if p["evaluation_set"] == "fresh_heldout" and p["transition"] == family], [p for p in right if p["evaluation_set"] == "fresh_heldout" and p["transition"] == family], target=True) for family in FAMILIES},
            "sequences": {identifier: _concordance([p for p in left if p["case_id"] == identifier], [p for p in right if p["case_id"] == identifier]) for identifier in CASES if CASES[identifier]["group"] == "sequence"},
            "fresh_family_mean_directions": {family: {
                name: {"seed11_mean_delta": (a := _stats([p["target_node_metrics"][name]["candidate_minus_baseline"] for p in left if p["evaluation_set"] == "fresh_heldout" and p["transition"] == family])["mean"]),
                       "seed29_mean_delta": (b := _stats([p["target_node_metrics"][name]["candidate_minus_baseline"] for p in right if p["evaluation_set"] == "fresh_heldout" and p["transition"] == family])["mean"]),
                       "seed11_direction": _sign(a), "seed29_direction": _sign(b)}
                for name in TARGET_DIRECTIONS} for family in FAMILIES},
        }
    findings = []
    for label, comparison in comparisons.items():
        fresh = comparison["by_evaluation_set"]["fresh_heldout"]
        findings.append({"arm": label, "same_frame_baseline": comparison["baseline_arm"],
                         "fresh_nominal_score_changes": fresh["score_changes"]["nominal_change"],
                         "fresh_physical_score_changes": fresh["score_changes"]["physical_change"],
                         "strict_node_changes_all_42_cases": comparison["overall"]["original_node_strict_changes"],
                         "primitive_exact_count": comparison["primitive_physical_identity"]["exact_count"],
                         "interpretation": "Descriptive fixed-seed pilot; direction concordance is not significance, tuning, or a combined quality verdict"})
    return {"schema_version": "phase3a-same-frame-PPO-analysis-v1", "primary_record_count": 252,
            "arms": arms, "same_frame_comparisons": comparisons,
            "cross_seed_concordance": concordance, "descriptive_findings": findings,
            "analysis_contract": {
                "primary": "6 arms × (fresh16 + seen26); repeats rejected and never pooled",
                "comparisons": "Each of four learned actors paired only to its own alpha residual-off baseline; midpoint frame benefit is not learned benefit",
                "scores": "Original nominal/physical/node strict booleans and envelopes retained; all-node strict is a descriptive derived conjunction with missing coverage",
                "metric_directions": {"case": CASE_DIRECTIONS, "target": TARGET_DIRECTIONS},
                "duration": "Time decrease means faster only; never independently proves quality or absence of reward hacking",
                "transition_heading_change": "Raw signed rotation includes intended turns; not heading error",
                "authority": "Residual authority is first 2 seconds of eligible target nodes only (frozen elapsed < 2−1e−9); later completion and sequence endpoints are full-system outcomes",
                "missing": "Null diagnostics remain missing with coverage; no replacement by zero",
                "primitive_identity_excluded_metadata_keys": sorted(METADATA_KEYS),
                "inference": "Two predeclared training seeds; deterministic repeats check replay identity, not independent sample size; no significance test or best-seed selection",
                "new_thresholds_or_total_score": None,
            }}
