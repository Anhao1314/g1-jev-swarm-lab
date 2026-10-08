"""Scoring, evidence records and aggregation for the Phase 2.3 benchmark.

All metrics are derived from machine-readable records produced by the runner;
nothing here reads prose reports. The three layers stay separate:

- Language correctness  -> compiler records (exact IR, status, parameters)
- Grounding             -> GroundedPlan status recorded on the runtime result
- Embodied correctness  -> MissionResult state / failure types

End-to-end success is defined as ``exact_ir AND grounding GROUNDED AND
mission_success``; runtime-given-exact-IR is reported separately.
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable, Mapping, Sequence

from ..language.equivalence import compare_runtime_results, mission_equivalence
from ..mission.ir import Mission

SUPPORTED_SKILLS = frozenset({"stand", "walk_forward", "turn", "stop"})

#: Runtime failure types (frozen Phase 2.0 taxonomy) -> Phase 2.3 attribution.
RUNTIME_FAILURE_ATTRIBUTION: dict[str, str] = {
    "VALIDATION_FAILURE": "COMPILER_WRONG_IR",
    "UNSUPPORTED_SKILL": "COMPILER_WRONG_IR",
    "CAPABILITY_REJECTED": "GROUNDING_REJECTED",
    "CAPABILITY_UNKNOWN": "GROUNDING_UNKNOWN",
    "PRECONDITION_FAILURE": "SKILL_FAILURE",
    "SKILL_FAILURE": "SKILL_FAILURE",
    "TRANSITION_FAILURE": "TRANSITION_FAILURE",
    "MISSION_TIMEOUT": "PHYSICAL_FAILURE",
    "INVALID_STATE": "PHYSICAL_FAILURE",
    "INTERNAL_ERROR": "PHYSICAL_FAILURE",
}

ATTRIBUTION_CATEGORIES: tuple[str, ...] = (
    "COMPILER_WRONG_IR",
    "COMPILER_FALSE_REJECT",
    "LANGUAGE_UNSAFE_ACCEPT",
    "GROUNDING_UNKNOWN",
    "GROUNDING_REJECTED",
    "SKILL_FAILURE",
    "TRANSITION_FAILURE",
    "EXCESSIVE_DRIFT",
    "HEADING_ERROR",
    "PHYSICAL_FAILURE",
    "BLOCKED_AFTER_FAILURE",
    "RUNTIME_CONTRADICTION",
)


def as_mission(document: Mapping[str, Any] | Mission) -> Mission:
    if isinstance(document, Mission):
        return document
    filtered = {
        "schema_version": str(document.get("schema_version", "2.0.0")),
        "mission_id": str(document["mission_id"]),
        "steps": list(document["steps"]),
    }
    return Mission.from_dict(filtered)


def mission_document(document: Mapping[str, Any] | Mission) -> dict[str, Any]:
    mission = as_mission(document)
    return {
        "schema_version": mission.schema_version,
        "mission_id": mission.mission_id,
        "steps": [
            {
                "id": step.step_id,
                "skill": step.skill.value,
                "parameters": dict(step.parameters),
                "depends_on": list(step.depends_on),
            }
            for step in mission.steps
        ],
    }


def compare_ir(compiled: Mission | None, oracle: Mission) -> dict[str, Any]:
    """Exact-IR comparison plus diagnostic breakdown for scoring records."""
    oracle_skills = [step.skill.value for step in oracle.steps]
    oracle_params = [dict(step.parameters) for step in oracle.steps]
    if compiled is None:
        return {
            "exact_ir_match": False,
            "step_order_match": False,
            "step_count_match": False,
            "parameters_match": False,
            "compiled_ir_hash": None,
            "oracle_ir_hash": None,
        }
    base = mission_equivalence(compiled, oracle)
    compiled_skills = [step.skill.value for step in compiled.steps]
    compiled_params = [dict(step.parameters) for step in compiled.steps]
    order_match = compiled_skills == oracle_skills
    parameters_match = order_match and compiled_params == oracle_params
    return {
        "exact_ir_match": bool(base["exact_match"]),
        "step_order_match": order_match,
        "step_count_match": len(compiled.steps) == len(oracle.steps),
        "parameters_match": parameters_match,
        "compiled_ir_hash": base["compiled_ir_hash"],
        "oracle_ir_hash": base["oracle_ir_hash"],
    }


def _latency_of(result: Any) -> float | None:
    diagnostics = dict(getattr(result, "diagnostics", {}) or {})
    value = diagnostics.get("latency_s")
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def _tokens_of(result: Any) -> int | None:
    diagnostics = dict(getattr(result, "diagnostics", {}) or {})
    usage = diagnostics.get("usage")
    if isinstance(usage, Mapping):
        total = usage.get("total_tokens")
        if isinstance(total, int) and total >= 0:
            return total
    usage = diagnostics.get("canonicalizer_usage")
    if isinstance(usage, Mapping):
        total = usage.get("total_tokens")
        if isinstance(total, int) and total >= 0:
            return total
    return None


def compiler_record(
    *,
    experiment_id: str,
    sample: Mapping[str, Any],
    mission: Mapping[str, Any] | Mission,
    result: Any,
    provenance: Mapping[str, Any] | None = None,
    wall_time_s: float | None = None,
) -> dict[str, Any]:
    """One Stage A (compiler-only) evidence record for an expected-valid sample."""
    oracle = as_mission(mission)
    diagnostics = dict(getattr(result, "diagnostics", {}) or {})
    comparison = compare_ir(getattr(result, "mission", None), oracle)
    skills = (
        [step.skill.value for step in result.mission.steps]
        if getattr(result, "mission", None) is not None
        else []
    )
    hallucinated = sorted({skill for skill in skills if skill not in SUPPORTED_SKILLS})
    status = str(getattr(getattr(result, "status", None), "value", getattr(result, "status", "")))
    record: dict[str, Any] = {
        "experiment_id": experiment_id,
        "sample_id": str(sample["sample_id"]),
        "mission_id": str(sample["mission_id"]),
        "horizon": str(sample["horizon"]),
        "condition": str(sample["condition"]),
        "text": str(sample["text"]),
        "expected_status": "SUCCESS",
        "actual_status": status,
        "route": diagnostics.get("route"),
        "guard_status": diagnostics.get("guard_status"),
        "guard_reason_code": diagnostics.get("guard_reason_code"),
        "llm_invocations": int(diagnostics.get("llm_invocations", 0) or 0),
        "provider_attempts": (
            int(diagnostics["attempts"]) if isinstance(diagnostics.get("attempts"), int) else None
        ),
        "provider_tokens": _tokens_of(result),
        "latency_s": _latency_of(result),
        "wall_time_s": wall_time_s,
        "false_rejection": status != "SUCCESS",
        "hallucinated_skills": hallucinated,
        "unsafe_acceptance": False,
        "compiled_mission": mission_document(result.mission) if getattr(result, "mission", None) else None,
        "oracle_mission": mission_document(oracle),
        "error_code": str(getattr(getattr(result, "error_code", None), "value", "") or "") or None,
        "error_message": getattr(result, "error_message", None),
        "provenance": dict(provenance or {}),
    }
    record.update(comparison)
    return record


def control_record(
    *,
    experiment_id: str,
    control: Mapping[str, Any],
    result: Any,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One safety-control record (long malformed / ambiguous / unsupported /
    capability-unknown inputs). Nothing here enters the success corpus."""
    diagnostics = dict(getattr(result, "diagnostics", {}) or {})
    status = str(getattr(getattr(result, "status", None), "value", getattr(result, "status", "")))
    mission = getattr(result, "mission", None)
    skills = [step.skill.value for step in mission.steps] if mission is not None else []
    hallucinated = sorted({skill for skill in skills if skill not in SUPPORTED_SKILLS})
    expected_status = str(control["expected_compiler_status"])
    return {
        "experiment_id": experiment_id,
        "control_id": str(control["control_id"]),
        "kind": str(control["kind"]),
        "text": str(control["text"]),
        "expected_compiler_status": expected_status,
        "expected_runtime": str(control.get("expected_runtime", "NOT_RUN")),
        "expected_grounding": control.get("expected_grounding"),
        "actual_status": status,
        "status_match": status == expected_status,
        "mission_produced": mission is not None,
        "unsafe_acceptance": expected_status != "SUCCESS" and mission is not None,
        "hallucinated_skills": hallucinated,
        "compiled_mission": mission_document(mission) if mission is not None else None,
        "route": diagnostics.get("route"),
        "guard_status": diagnostics.get("guard_status"),
        "guard_reason_code": diagnostics.get("guard_reason_code"),
        "llm_invocations": int(diagnostics.get("llm_invocations", 0) or 0),
        "provider_attempts": (
            int(diagnostics["attempts"]) if isinstance(diagnostics.get("attempts"), int) else None
        ),
        "latency_s": _latency_of(result),
        "provenance": dict(provenance or {}),
    }


# ---------------------------------------------------------------------------
# Aggregation helpers


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * quantile))))
    return float(ordered[index])


def _compiler_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(records)
    exact = sum(bool(record.get("exact_ir_match")) for record in records)
    rejected = sum(bool(record.get("false_rejection")) for record in records)
    wrong_order = sum(
        bool(record.get("status") != "SUCCESS") is False
        and not bool(record.get("step_order_match"))
        for record in records
    )
    wrong_parameter = sum(
        bool(record.get("step_order_match")) and not bool(record.get("parameters_match"))
        for record in records
    )
    hallucinated = sum(bool(record.get("hallucinated_skills")) for record in records)
    unsafe = sum(bool(record.get("unsafe_acceptance")) for record in records)
    latencies = [float(record["latency_s"]) for record in records if record.get("latency_s") is not None]
    tokens = [int(record["provider_tokens"]) for record in records if record.get("provider_tokens") is not None]
    return {
        "samples": total,
        "exact_ir_count": exact,
        "exact_ir_rate": (exact / total) if total else None,
        "status_accuracy": (
            sum(record.get("actual_status") == record.get("expected_status") for record in records) / total
            if total
            else None
        ),
        "false_rejection_count": rejected,
        "false_rejection_rate": (rejected / total) if total else None,
        "wrong_step_order_count": wrong_order,
        "wrong_parameter_count": wrong_parameter,
        "hallucinated_skill_count": hallucinated,
        "unsafe_acceptance_count": unsafe,
        "latency_mean_s": statistics.fmean(latencies) if latencies else None,
        "latency_median_s": statistics.median(latencies) if latencies else None,
        "latency_p95_s": _percentile(latencies, 0.95),
        "provider_tokens_total": sum(tokens) if tokens else None,
        "provider_tokens_mean": statistics.fmean(tokens) if tokens else None,
    }


def summarize_compiler(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def group(key: str) -> dict[str, Any]:
        buckets: dict[str, list[Mapping[str, Any]]] = {}
        for record in records:
            buckets.setdefault(str(record.get(key)), []).append(record)
        return {name: _compiler_metrics(group_records) for name, group_records in sorted(buckets.items())}

    combined: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        key = f"{record.get('horizon')}/{record.get('condition')}"
        combined.setdefault(key, []).append(record)
    return {
        "overall": _compiler_metrics(list(records)),
        "by_horizon": group("horizon"),
        "by_condition": group("condition"),
        "by_horizon_condition": {key: _compiler_metrics(value) for key, value in sorted(combined.items())},
    }


def attribute_runtime_failure(
    *,
    language_result: Any,
    oracle_result: Any | None,
    equivalence: Mapping[str, Any] | None,
    grounded: bool,
) -> str | None:
    if language_result.mission_success:
        return None
    failure_type = language_result.failure_type
    if not grounded and failure_type in {"CAPABILITY_UNKNOWN", "CAPABILITY_REJECTED"}:
        return RUNTIME_FAILURE_ATTRIBUTION[failure_type]
    if oracle_result is not None and oracle_result.mission_success and equivalence is not None:
        if not bool(equivalence.get("runtime_equivalent", False)):
            return "RUNTIME_CONTRADICTION"
    return RUNTIME_FAILURE_ATTRIBUTION.get(str(failure_type), str(failure_type))


def runtime_record(
    *,
    experiment_id: str,
    sample: Mapping[str, Any],
    compiler_row: Mapping[str, Any],
    language_result: Any,
    oracle_result: Any,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One Stage B record: language path executed for an exact-IR sample."""
    equivalence = compare_runtime_results(language_result, oracle_result)
    grounding = dict(language_result.grounding or {})
    grounding_status = grounding.get("status")
    grounded = grounding_status == "GROUNDED"
    attribution = attribute_runtime_failure(
        language_result=language_result,
        oracle_result=oracle_result,
        equivalence=equivalence,
        grounded=grounded,
    )
    return {
        "experiment_id": experiment_id,
        "sample_id": str(sample["sample_id"]),
        "mission_id": str(sample["mission_id"]),
        "horizon": str(sample["horizon"]),
        "condition": str(sample["condition"]),
        "text": str(sample["text"]),
        "exact_ir": True,
        "compiled_ir_hash": compiler_row.get("compiled_ir_hash"),
        "oracle_ir_hash": compiler_row.get("oracle_ir_hash"),
        "grounding_status": grounding_status,
        "grounding": grounding,
        "state": language_result.state,
        "mission_success": bool(language_result.mission_success),
        "failure_type": language_result.failure_type,
        "failure_reason": language_result.failure_reason,
        "attribution": attribution,
        "completed_nodes": int(language_result.completed_nodes),
        "failed_node": language_result.failed_node,
        "skill_invocations": int(language_result.skill_invocations),
        "simulation_steps_executed": int(language_result.simulation_steps_executed),
        "total_simulation_time_s": float(language_result.total_simulation_time_s),
        "wall_time_s": float(language_result.total_wall_time_s),
        "transition_count": int(language_result.transition_count),
        "controller_memory_resets": int(language_result.controller_memory_resets),
        "physical_success": bool(language_result.physical_success),
        "path_length_m": float(language_result.path_length_m),
        "oracle": {
            "state": oracle_result.state,
            "mission_success": bool(oracle_result.mission_success),
            "failure_type": oracle_result.failure_type,
            "completed_nodes": int(oracle_result.completed_nodes),
            "simulation_steps_executed": int(oracle_result.simulation_steps_executed),
            "transition_count": int(oracle_result.transition_count),
        },
        "runtime_equivalent": bool(equivalence.get("runtime_equivalent", False)),
        "transitions": [dict(transition) for transition in language_result.transitions],
        "nodes": [
            {
                "node_id": node.get("node_id"),
                "skill": node.get("skill"),
                "execution_mode": node.get("execution_mode"),
                "risk": node.get("risk"),
                "metrics": dict(node.get("metrics", {})),
            }
            for node in language_result.nodes
        ],
        "provenance": dict(provenance or {}),
    }


def _runtime_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(records)
    successes = sum(bool(record.get("mission_success")) for record in records)
    oracle_successes = sum(bool(record.get("oracle", {}).get("mission_success")) for record in records)
    contradictions = sum(record.get("attribution") == "RUNTIME_CONTRADICTION" for record in records)
    return {
        "entered_from_exact_ir": total,
        "runtime_success_count": successes,
        "runtime_success_given_exact_ir": (successes / total) if total else None,
        "oracle_success_count": oracle_successes,
        "oracle_success_rate": (oracle_successes / total) if total else None,
        "runtime_equivalence_rate": (
            sum(bool(record.get("runtime_equivalent")) for record in records) / total if total else None
        ),
        "runtime_contradiction_count": contradictions,
        "transition_count_total": sum(int(record.get("transition_count", 0)) for record in records),
        "controller_memory_resets_total": sum(
            int(record.get("controller_memory_resets", 0)) for record in records
        ),
    }


def summarize_runtime(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def group(key: str) -> dict[str, Any]:
        buckets: dict[str, list[Mapping[str, Any]]] = {}
        for record in records:
            buckets.setdefault(str(record.get(key)), []).append(record)
        return {name: _runtime_metrics(value) for name, value in sorted(buckets.items())}

    combined: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        combined.setdefault(f"{record.get('horizon')}/{record.get('condition')}", []).append(record)
    return {
        "overall": _runtime_metrics(list(records)),
        "by_horizon": group("horizon"),
        "by_condition": group("condition"),
        "by_horizon_condition": {key: _runtime_metrics(value) for key, value in sorted(combined.items())},
    }


def build_horizon_summary(
    compiler_records: Sequence[Mapping[str, Any]],
    runtime_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Horizon x condition table: exact IR, runtime|exact, E2E success."""
    compiler_by: dict[str, list[Mapping[str, Any]]] = {}
    runtime_by: dict[str, list[Mapping[str, Any]]] = {}
    for record in compiler_records:
        compiler_by.setdefault(f"{record.get('horizon')}/{record.get('condition')}", []).append(record)
    for record in runtime_records:
        runtime_by.setdefault(f"{record.get('horizon')}/{record.get('condition')}", []).append(record)
    rows: dict[str, Any] = {}
    for key in sorted(compiler_by):
        compiler_rows = compiler_by[key]
        runtime_rows = runtime_by.get(key, [])
        total = len(compiler_rows)
        exact = sum(bool(record.get("exact_ir_match")) for record in compiler_rows)
        e2e_success = sum(bool(record.get("mission_success")) for record in runtime_rows)
        oracle_rows = [record for record in runtime_rows if record.get("oracle")]
        oracle_success = sum(bool(record["oracle"].get("mission_success")) for record in oracle_rows)
        horizon, condition = key.split("/")
        rows[key] = {
            "horizon": horizon,
            "condition": condition,
            "language_samples": total,
            "exact_ir_count": exact,
            "exact_ir_rate": (exact / total) if total else None,
            "runtime_entered": len(runtime_rows),
            "runtime_success_count": e2e_success,
            "runtime_success_given_exact_ir": (e2e_success / len(runtime_rows)) if runtime_rows else None,
            "oracle_runtime_success_count": oracle_success,
            "oracle_runtime_success_rate": (oracle_success / len(oracle_rows)) if oracle_rows else None,
            "end_to_end_success_count": e2e_success,
            "end_to_end_success_rate": (e2e_success / total) if total else None,
            "failure_attribution": _attribution_counts(runtime_rows),
            "compiler": {
                "false_rejection_count": sum(bool(record.get("false_rejection")) for record in compiler_rows),
                "wrong_step_order_count": sum(
                    not bool(record.get("step_order_match")) for record in compiler_rows
                ),
                "wrong_parameter_count": sum(
                    bool(record.get("step_order_match")) and not bool(record.get("parameters_match"))
                    for record in compiler_rows
                ),
                "hallucinated_skill_count": sum(
                    bool(record.get("hallucinated_skills")) for record in compiler_rows
                ),
            },
        }
    return {"rows": rows, "by_horizon": _pool(rows, "horizon"), "by_condition": _pool(rows, "condition")}


def _attribution_counts(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {category: 0 for category in ATTRIBUTION_CATEGORIES}
    for record in records:
        attribution = record.get("attribution")
        if attribution is None:
            continue
        counts[str(attribution)] = counts.get(str(attribution), 0) + 1
    return {key: value for key, value in counts.items() if value}


def _pool(rows: Mapping[str, Mapping[str, Any]], key: str) -> dict[str, Any]:
    buckets: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows.values():
        buckets.setdefault(str(row[key]), []).append(row)
    pooled: dict[str, Any] = {}
    for name, group in sorted(buckets.items()):
        language_samples = sum(int(row["language_samples"]) for row in group)
        exact = sum(int(row["exact_ir_count"]) for row in group)
        entered = sum(int(row["runtime_entered"]) for row in group)
        success = sum(int(row["runtime_success_count"]) for row in group)
        pooled[name] = {
            "language_samples": language_samples,
            "exact_ir_count": exact,
            "exact_ir_rate": (exact / language_samples) if language_samples else None,
            "runtime_entered": entered,
            "runtime_success_given_exact_ir": (success / entered) if entered else None,
            "end_to_end_success_count": success,
            "end_to_end_success_rate": (success / language_samples) if language_samples else None,
        }
    return pooled


def horizon_deltas(summary: Mapping[str, Any]) -> dict[str, Any]:
    horizons = ["H1", "H3", "H5", "H8", "H12", "H16"]
    pooled = summary.get("by_horizon", {})
    deltas: dict[str, Any] = {}
    for previous, current in zip(horizons, horizons[1:]):
        if previous not in pooled or current not in pooled:
            continue
        before, after = pooled[previous], pooled[current]
        entry: dict[str, Any] = {}
        for metric in ("exact_ir_rate", "runtime_success_given_exact_ir", "end_to_end_success_rate"):
            a, b = before.get(metric), after.get(metric)
            if a is None or b is None:
                entry[metric] = None
                continue
            entry[metric] = {
                "from": a,
                "to": b,
                "delta": b - a,
                "relative": ((b - a) / a) if a else None,
            }
        deltas[f"{previous}->{current}"] = entry
    return deltas


def transition_analysis(
    records: Sequence[Mapping[str, Any]], *, min_pair_samples: int = 5
) -> dict[str, Any]:
    pairs: dict[str, dict[str, Any]] = {}
    for record in records:
        transitions = list(record.get("transitions") or [])
        failed_node = record.get("failed_node")
        for transition in transitions:
            pair = f"{transition.get('previous_skill')}->{transition.get('next_skill')}"
            entry = pairs.setdefault(
                pair,
                {
                    "count": 0,
                    "failed_next_count": 0,
                    "position_delta_m": [],
                    "heading_delta_deg": [],
                    "memory_resets": 0,
                },
            )
            entry["count"] += 1
            if failed_node is not None and failed_node == transition.get("next_node_id"):
                entry["failed_next_count"] += 1
            delta = transition.get("position_delta_m")
            if isinstance(delta, (list, tuple)) and len(delta) == 3:
                entry["position_delta_m"].append(sum(abs(float(value)) for value in delta))
            heading = transition.get("heading_delta_deg")
            if isinstance(heading, (int, float)):
                entry["heading_delta_deg"].append(abs(float(heading)))
            entry["memory_resets"] += int(bool(transition.get("controller_memory_reset")))
    summary: dict[str, Any] = {}
    for pair, entry in sorted(pairs.items()):
        count = entry["count"]
        position = entry.pop("position_delta_m")
        heading = entry.pop("heading_delta_deg")
        entry["mean_position_delta_m"] = statistics.fmean(position) if position else None
        entry["mean_heading_delta_deg"] = statistics.fmean(heading) if heading else None
        entry["failure_rate"] = (entry["failed_next_count"] / count) if count else None
        entry["rate_reportable"] = count >= min_pair_samples
        summary[pair] = entry
    return {
        "pairs": summary,
        "min_pair_samples_for_rate": min_pair_samples,
        "totals": {
            "transitions": sum(int(record.get("transition_count", 0)) for record in records),
            "missions": len(records),
        },
    }


def latency_token_summary(compiler_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[Mapping[str, Any]]] = {}
    for record in compiler_records:
        buckets.setdefault(str(record.get("horizon")), []).append(record)
    output: dict[str, Any] = {}
    for horizon, group in sorted(buckets.items()):
        latencies = [float(r["latency_s"]) for r in group if r.get("latency_s") is not None]
        tokens = [int(r["provider_tokens"]) for r in group if r.get("provider_tokens") is not None]
        exact = [r for r in group if r.get("exact_ir_match")]
        exact_tokens = [int(r["provider_tokens"]) for r in exact if r.get("provider_tokens") is not None]
        wall = [float(r["wall_time_s"]) for r in group if r.get("wall_time_s") is not None]
        output[horizon] = {
            "samples": len(group),
            "latency_mean_s": statistics.fmean(latencies) if latencies else None,
            "latency_median_s": statistics.median(latencies) if latencies else None,
            "latency_p95_s": _percentile(latencies, 0.95),
            "wall_time_mean_s": statistics.fmean(wall) if wall else None,
            "wall_time_median_s": statistics.median(wall) if wall else None,
            "wall_time_p95_s": _percentile(wall, 0.95),
            "wall_time_max_s": max(wall) if wall else None,
            "provider_tokens_total": sum(tokens) if tokens else None,
            "provider_tokens_mean": statistics.fmean(tokens) if tokens else None,
            "provider_tokens_per_successful_mission": (
                statistics.fmean(exact_tokens) if exact_tokens else None
            ),
        }
    return output


def failure_taxonomy_summary(
    runtime_records: Sequence[Mapping[str, Any]],
    control_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    by_horizon: dict[str, dict[str, int]] = {}
    for record in runtime_records:
        attribution = record.get("attribution")
        if attribution is None:
            continue
        bucket = by_horizon.setdefault(str(record.get("horizon")), {})
        bucket[str(attribution)] = bucket.get(str(attribution), 0) + 1
    controls = {
        "unsafe_acceptance_count": sum(bool(record.get("unsafe_acceptance")) for record in control_records),
        "status_mismatch_count": sum(not bool(record.get("status_match")) for record in control_records),
        "hallucinated_skill_count": sum(bool(record.get("hallucinated_skills")) for record in control_records),
        "by_control": {
            str(record.get("control_id")): {
                "kind": record.get("kind"),
                "expected_compiler_status": record.get("expected_compiler_status"),
                "actual_status": record.get("actual_status"),
                "status_match": bool(record.get("status_match")),
                "mission_produced": bool(record.get("mission_produced")),
                "unsafe_acceptance": bool(record.get("unsafe_acceptance")),
            }
            for record in control_records
        },
    }
    return {"by_horizon": by_horizon, "safety_controls": controls}
