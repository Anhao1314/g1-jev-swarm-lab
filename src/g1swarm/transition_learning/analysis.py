"""Offline Phase 3A summaries and paired comparisons; no learned evaluator.

Every training seed is kept separate via ``treatment_label``. Continuous values
are reported with their denominators. No new improvement threshold is imposed.
Transition heading change contains intended turn rotation and is not an error.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from statistics import mean
from typing import Any, Mapping, Sequence


def _label(record: Mapping[str, Any]) -> str:
    return str(record.get("treatment_label") or record["treatment"])


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _stats(values: Sequence[Any]) -> dict:
    finite = [value for raw in values if (value := _number(raw)) is not None]
    return {"n": len(finite), "missing_or_non_finite": len(values) - len(finite),
            "mean": mean(finite) if finite else None,
            "min": min(finite) if finite else None,
            "max": max(finite) if finite else None}


def _mean_field(nodes: Sequence[Mapping], name: str, *, absolute: bool = False) -> float | None:
    values = [value for node in nodes if (value := _number(node.get(name))) is not None]
    return mean(abs(value) if absolute else value for value in values) if values else None


def _extreme_field(nodes: Sequence[Mapping], name: str, *, minimum: bool = False) -> float | None:
    values = [value for node in nodes if (value := _number(node.get(name))) is not None]
    return (min(values) if minimum else max(values)) if values else None


def _case_metrics(record: Mapping[str, Any]) -> dict[str, float | None]:
    nodes = record.get("nodes", [])
    walks = [node for node in nodes if node.get("skill") == "walk_forward"]
    turns = [node for node in nodes if node.get("skill") == "turn"]
    transitions = [node["transition_metrics"] for node in nodes
                   if isinstance(node.get("transition_metrics"), Mapping)
                   and node["transition_metrics"].get("eligible") is True]
    return {
        "total_sim_time_s": _number(record.get("total_sim_time_s")),
        "walk_mean_abs_lateral_drift_m": _mean_field(walks, "lateral_drift_m", absolute=True),
        "walk_mean_abs_heading_error_deg": _mean_field(walks, "heading_error_deg", absolute=True),
        "turn_mean_abs_heading_error_deg": _mean_field(turns, "heading_error_deg", absolute=True),
        "ideal_path_mean_abs_lateral_error_m": _mean_field(nodes, "ideal_path_lateral_error_m", absolute=True),
        "ideal_path_mean_abs_heading_error_deg": _mean_field(nodes, "ideal_path_heading_error_deg", absolute=True),
        "peak_tilt_deg": _extreme_field(nodes, "max_tilt_deg"),
        "minimum_height_m": _extreme_field(nodes, "min_height_m", minimum=True),
        "transition_mean_window_duration_s": _mean_field(transitions, "duration_s"),
        "transition_mean_completion_duration_s": _mean_field(transitions, "completion_duration_s"),
        "transition_mean_abs_lateral_change_m": _mean_field(transitions, "lateral_change_m", absolute=True),
        "transition_mean_heading_change_deg": _mean_field(transitions, "heading_change_deg"),
        "transition_peak_tilt_deg": _extreme_field(transitions, "max_tilt_deg"),
        "transition_minimum_height_m": _extreme_field(transitions, "min_height_m", minimum=True),
        "transition_mean_speed_rms_mps": _mean_field(transitions, "speed_rms_mps"),
        "transition_mean_final_speed_mps": _mean_field(transitions, "final_speed_mps"),
        "transition_mean_next_skill_final_speed_mps": _mean_field(transitions, "next_skill_final_speed_mps"),
        "transition_mean_angular_speed_rms_radps": _mean_field(transitions, "angular_speed_rms_radps"),
        "transition_mean_standing_fraction": _mean_field(transitions, "standing_fraction"),
        "transition_mean_sustained_tracking_recovery_s": _mean_field(transitions, "sustained_tracking_recovery_s"),
    }


def _diagnostic_coverage(records: Sequence[Mapping[str, Any]]) -> dict:
    """Keep missing recovery evidence visible even inside a multi-node case."""
    windows = [node["transition_metrics"] for record in records
               for node in record.get("nodes", [])
               if isinstance(node.get("transition_metrics"), Mapping)
               and node["transition_metrics"].get("eligible") is True]
    names = ("angular_speed_rms_radps", "standing_fraction", "sustained_tracking_recovery_s",
             "final_speed_mps", "next_skill_final_speed_mps")
    return {name: {"eligible_windows": len(windows),
                   "observed_windows": sum(_number(window.get(name)) is not None for window in windows),
                   "null_or_non_finite_windows": sum(_number(window.get(name)) is None for window in windows)}
            for name in names}


def _failures(record: Mapping[str, Any]) -> Counter:
    failures = record.get("failure_taxonomy", [])
    if isinstance(failures, str):
        return Counter([failures])
    if isinstance(failures, Mapping):
        return Counter(failures)
    return Counter(failures)


def _summarize(records: Sequence[Mapping[str, Any]]) -> dict:
    n = len(records)
    task = sum(record.get("task_success") is True for record in records)
    physical = sum(record.get("physical_success") is True for record in records)
    failures = Counter()
    for record in records:
        failures.update(_failures(record))
    scalars = [_case_metrics(record) for record in records]
    names = _case_metrics({}).keys()
    return {"runs": n, "case_ids": [record["case_id"] for record in records],
            "task_successes": task, "physical_successes": physical,
            "task_success_rate": task / n if n else None,
            "physical_success_rate": physical / n if n else None,
            "physical_success_task_failure": sum(record.get("physical_success") is True
                                                  and record.get("task_success") is False
                                                  for record in records),
            "fallen_node_count": sum(node.get("fallen") is True for record in records
                                     for node in record.get("nodes", [])),
            "failure_taxonomy": dict(sorted(failures.items())),
            "transition_diagnostic_coverage": _diagnostic_coverage(records),
            "metrics": {name: _stats([values[name] for values in scalars]) for name in names}}


def _partitions(records: Sequence[Mapping[str, Any]], field: str) -> dict:
    groups = defaultdict(list)
    for record in records:
        groups[str(record.get(field) or "none")].append(record)
    return {key: _summarize(values) for key, values in sorted(groups.items())}


def summarize_results(records: Sequence[Mapping[str, Any]]) -> dict:
    """Summarize each treatment/seed, retaining separate case/evaluation sets."""
    groups = defaultdict(list)
    for record in records:
        groups[_label(record)].append(record)
    return {"schema_version": "phase3a-results-summary-v1", "record_count": len(records),
            "metric_interpretation": {
                "aggregation": "case means/extremes, then equal weight per recorded case",
                "transition_mean_heading_change_deg": "signed rotation including intended turn angle; not heading error",
                "transition_mean_window_duration_s": "measured transition window, distinct from full completion duration",
                "transition_mean_final_speed_mps": "speed at transition window end",
                "transition_mean_next_skill_final_speed_mps": "speed at target skill completion",
                "transition_mean_sustained_tracking_recovery_s": "observed sustained recovery within the frozen window; null is unavailable recovery evidence, not zero",
                "missing": "missing/non-finite values are counted; never replaced by zero",
            },
            "by_treatment": {label: {
                "overall": _summarize(values),
                "by_group": _partitions(values, "group"),
                "by_transition": _partitions(values, "transition"),
                "by_evaluation_set": _partitions(values, "evaluation_set"),
            } for label, values in sorted(groups.items())}}


def _paired_summary(pairs: Sequence[Mapping[str, Any]]) -> dict:
    names = _case_metrics({}).keys()
    return {"paired_cases": len(pairs),
            "task_fail_to_pass": sum(not pair["baseline_task_success"] and pair["candidate_task_success"] for pair in pairs),
            "task_pass_to_fail": sum(pair["baseline_task_success"] and not pair["candidate_task_success"] for pair in pairs),
            "physical_fail_to_pass": sum(not pair["baseline_physical_success"] and pair["candidate_physical_success"] for pair in pairs),
            "physical_pass_to_fail": sum(pair["baseline_physical_success"] and not pair["candidate_physical_success"] for pair in pairs),
            "metric_deltas": {name: _stats([pair["metrics"][name]["candidate_minus_baseline"] for pair in pairs]) for name in names}}


def compare_results(records: Sequence[Mapping[str, Any]]) -> dict:
    """Pair case IDs against deterministic correction without pooling seeds."""
    groups = defaultdict(dict)
    for record in records:
        label, identifier = _label(record), str(record["case_id"])
        if identifier in groups[label]:
            raise ValueError(f"duplicate treatment/case pair: {label}/{identifier}")
        groups[label][identifier] = record
    baseline_label = "deterministic_correction"
    if baseline_label not in groups and "heading_lateral" in groups:
        baseline_label = "heading_lateral"
    baseline = groups.get(baseline_label, {})
    comparisons = {}
    for label, candidates in sorted(groups.items()):
        if label == baseline_label:
            continue
        pairs = []
        for identifier in sorted(set(baseline) & set(candidates)):
            reference, candidate = baseline[identifier], candidates[identifier]
            for field in ("group", "transition", "evaluation_set"):
                if reference.get(field) != candidate.get(field):
                    raise ValueError(f"paired metadata mismatch: {identifier}/{field}")
            expected_nodes = [(node.get("skill"), node.get("parameters")) for node in reference.get("nodes", [])]
            candidate_nodes = [(node.get("skill"), node.get("parameters")) for node in candidate.get("nodes", [])]
            # Interrupted episodes can have a shorter observed node list.
            shared = min(len(expected_nodes), len(candidate_nodes))
            if expected_nodes[:shared] != candidate_nodes[:shared]:
                raise ValueError(f"paired node mismatch: {identifier}")
            reference_metrics, candidate_metrics = _case_metrics(reference), _case_metrics(candidate)
            metrics = {name: {"baseline": value, "candidate": candidate_metrics[name],
                "candidate_minus_baseline": candidate_metrics[name] - value
                if value is not None and candidate_metrics[name] is not None else None}
                for name, value in reference_metrics.items()}
            pairs.append({"case_id": identifier, "group": candidate.get("group"),
                          "transition": candidate.get("transition"), "evaluation_set": candidate.get("evaluation_set"),
                          "baseline_task_success": reference.get("task_success") is True,
                          "candidate_task_success": candidate.get("task_success") is True,
                          "baseline_physical_success": reference.get("physical_success") is True,
                          "candidate_physical_success": candidate.get("physical_success") is True,
                          "transition_diagnostic_coverage": {
                              "baseline": _diagnostic_coverage([reference]),
                              "candidate": _diagnostic_coverage([candidate]),
                          },
                          "metrics": metrics})
        partitions = {}
        for field in ("group", "transition", "evaluation_set"):
            by = defaultdict(list)
            for pair in pairs:
                by[str(pair.get(field) or "none")].append(pair)
            partitions[f"by_{field}"] = {key: _paired_summary(value) for key, value in sorted(by.items())}
        comparisons[label] = {"overall": _paired_summary(pairs), **partitions,
                              "pairs": pairs,
                              "baseline_only_ids": sorted(set(baseline) - set(candidates)),
                              "candidate_only_ids": sorted(set(candidates) - set(baseline)),
                              "pair_coverage_complete": bool(baseline) and set(baseline) == set(candidates)}
    return {"schema_version": "phase3a-paired-comparison-v1", "baseline_treatment": baseline_label,
            "baseline_cases": len(baseline), "baseline_available": bool(baseline),
            "delta_convention": "candidate minus deterministic correction; raw transition rotation is not an error",
            "improvement_threshold": None, "by_treatment": comparisons}
