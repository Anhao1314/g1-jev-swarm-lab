"""Scoring utilities for the Phase 2.2 Rule-vs-LLM compiler benchmark."""

from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ..language.benchmark import canonical_mission_hash, canonical_mission_payload
from ..language.errors import CompilerStatus
from ..mission.ir import SkillName
from ..mission.validator import MissionValidator
from .datasets import LLMSample

SUPPORTED_SKILLS = frozenset(skill.value for skill in SkillName)

UNIT_CATEGORIES = frozenset({"mixed_units", "unit_variant", "open_unit"})
OPEN_LANGUAGE_CATEGORIES = frozenset(
    {
        "atomic_valid",
        "paraphrase",
        "composition",
        "colloquial",
        "noisy_formatting",
        "chinese_numbers",
        "arabic_numbers",
        "mixed_units",
        "open_language",
    }
)
API_FAILURE_TYPES = frozenset({"API_ERROR", "TIMEOUT", "COMPILER_EXCEPTION"})


def _rate(numerator: int | float, denominator: int) -> float | None:
    return (numerator / denominator) if denominator else None


def _step_count(mission: Mapping[str, Any] | None) -> int:
    if not mission:
        return 0
    return len(mission.get("steps", []))


def _skill_sequence(mission: Mapping[str, Any] | None) -> list[str]:
    if not mission:
        return []
    return [str(step.get("skill")) for step in mission.get("steps", [])]


def _parameter_sequence(mission: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not mission:
        return []
    return [dict(step.get("parameters", {})) for step in mission.get("steps", [])]


def _same_values(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(float(left)) and math.isfinite(float(right)) and float(left) == float(right)
    return left == right


def evaluate_sample(sample: LLMSample, compiler) -> dict[str, Any]:
    started = time.perf_counter()
    compile_exception: str | None = None
    result = None
    try:
        result = compiler.compile(sample.utterance)
    except Exception as exc:  # noqa: BLE001 - a hard compiler crash must not abort a campaign
        compile_exception = f"{type(exc).__name__}: {exc}"
    latency_s = time.perf_counter() - started

    if result is None:
        actual_mission = None
        actual_status = "EXCEPTION"
        actual_error = None
        diagnostics: dict[str, Any] = {}
    else:
        actual_mission = result.mission.to_dict() if result.mission is not None else None
        actual_status = result.status.value
        actual_error = result.error_code.value if result.error_code is not None else None
        diagnostics = dict(result.diagnostics)
    expected_mission = sample.expected_mission
    expected_status = sample.expected_compiler_status
    expected_canonical = (
        canonical_mission_payload(expected_mission) if expected_mission is not None else None
    )
    actual_canonical = (
        canonical_mission_payload(actual_mission) if actual_mission is not None else None
    )
    expected_skills = _skill_sequence(expected_mission)
    actual_skills = _skill_sequence(actual_mission)
    expected_parameters = _parameter_sequence(expected_mission)
    actual_parameters = _parameter_sequence(actual_mission)
    parameter_hits = sum(
        1
        for expected, actual in zip(expected_parameters, actual_parameters)
        if expected.keys() == actual.keys()
        and all(_same_values(actual[key], value) for key, value in expected.items())
    )
    skills_match = expected_skills == actual_skills
    order_match = skills_match
    exact_ir_match = bool(
        expected_status == "SUCCESS"
        and actual_status == "SUCCESS"
        and expected_canonical is not None
        and actual_canonical == expected_canonical
    )
    schema_valid = False
    if result is not None:
        if result.mission is not None:
            schema_valid = MissionValidator().validate(result.mission).valid
        else:
            # A typed refusal emits no mission and is schema-valid by construction.
            schema_valid = actual_status in {"AMBIGUOUS", "UNSUPPORTED", "MALFORMED"}
    hallucinated_skills = sorted(set(actual_skills) - SUPPORTED_SKILLS)
    expected_non_success = expected_status != "SUCCESS"
    unsafe_acceptance = bool(expected_non_success and actual_status == "SUCCESS")
    over_refusal = bool(expected_status == "SUCCESS" and actual_status != "SUCCESS")
    failure_type = diagnostics.get("failure_type")
    if failure_type is None:
        if actual_status == "EXCEPTION":
            failure_type = "COMPILER_EXCEPTION"
        elif unsafe_acceptance:
            failure_type = "UNSAFE_ACCEPTANCE"
        elif over_refusal:
            failure_type = "OVER_REFUSAL"
        elif actual_status == "SUCCESS" and not exact_ir_match:
            failure_type = "WRONG_IR"
        elif expected_status == "SUCCESS" and actual_status == "SUCCESS":
            failure_type = "SUCCESS"
        elif expected_status != "SUCCESS" and actual_status == expected_status:
            failure_type = "EXPECTED_REFUSAL"
    usage = diagnostics.get("usage") or {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    total_tokens = usage.get("total_tokens")
    if total_tokens is None and isinstance(input_tokens, int) and isinstance(output_tokens, int):
        total_tokens = input_tokens + output_tokens
    return {
        "sample_id": sample.sample_id,
        "benchmark_set": sample.benchmark_set,
        "split": sample.split,
        "category": sample.category,
        "source": sample.source,
        "utterance": sample.utterance,
        "expected_status": expected_status,
        "actual_status": actual_status,
        "expected_error_code": sample.expected_error_code,
        "actual_error_code": actual_error,
        "expected_ir_hash": (
            canonical_mission_hash(expected_mission) if expected_mission is not None else None
        ),
        "actual_ir_hash": (
            canonical_mission_hash(actual_mission) if actual_mission is not None else None
        ),
        "expected_mission": expected_mission,
        "actual_mission": actual_mission,
        "exact_ir_match": exact_ir_match,
        "status_match": actual_status == expected_status,
        "error_code_match": actual_error == sample.expected_error_code,
        "schema_valid": schema_valid,
        "skill_accuracy": (
            _rate(int(skills_match), 1) if expected_status == "SUCCESS" else None
        ),
        "parameter_accuracy": (
            _rate(parameter_hits, len(expected_parameters))
            if expected_status == "SUCCESS" and expected_parameters
            else None
        ),
        "order_accuracy": (
            _rate(int(order_match), 1) if expected_status == "SUCCESS" else None
        ),
        "false_rejection": over_refusal,
        "over_refusal": over_refusal,
        "unsafe_acceptance": unsafe_acceptance,
        "hallucinated_skills": hallucinated_skills,
        "latency_s": latency_s,
        "attempts": diagnostics.get("attempts"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "failure_type": failure_type,
        "compile_exception": compile_exception,
        "diagnostics": diagnostics,
    }


def _category_percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    expected_success = [item for item in results if item["expected_status"] == "SUCCESS"]
    actual_success = [item for item in results if item["actual_status"] == "SUCCESS"]
    ambiguities = [item for item in results if item["expected_status"] == "AMBIGUOUS"]
    unsupported = [item for item in results if item["expected_status"] == "UNSUPPORTED"]
    malformed = [item for item in results if item["expected_status"] == "MALFORMED"]
    expected_refusals = [item for item in results if item["expected_status"] != "SUCCESS"]
    exact = sum(bool(item["exact_ir_match"]) for item in expected_success)
    skill_hits = sum(
        1
        for item in expected_success
        if item["skill_accuracy"] == 1.0 and item["actual_status"] == "SUCCESS"
    )
    parameter_values = [
        item["parameter_accuracy"]
        for item in expected_success
        if item["parameter_accuracy"] is not None
    ]
    order_hits = sum(
        1
        for item in expected_success
        if item["order_accuracy"] == 1.0 and item["actual_status"] == "SUCCESS"
    )
    unit_items = [
        item
        for item in expected_success
        if item.get("category") in {"unit_variant", "mixed_units", "open_unit"}
    ]
    latency = sorted(float(item["latency_s"]) for item in results)
    tokens = [
        int(item["total_tokens"])
        for item in results
        if isinstance(item.get("total_tokens"), int)
    ]
    inputs = [
        int(item["input_tokens"])
        for item in results
        if isinstance(item.get("input_tokens"), int)
    ]
    outputs = [
        int(item["output_tokens"])
        for item in results
        if isinstance(item.get("output_tokens"), int)
    ]
    malformed_outputs = sum(
        1 for item in results if item.get("failure_type") == "MALFORMED_OUTPUT"
    )
    invalid_schema = sum(
        1 for item in results if item.get("failure_type") == "INVALID_SCHEMA"
    )
    hallucinated_fields = sum(
        1 for item in results if item.get("failure_type") == "HALLUCINATED_FIELD"
    )
    api_failures = sum(
        1 for item in results if item.get("failure_type") in API_FAILURE_TYPES
    )
    abstentions = [item for item in results if item["actual_status"] != "SUCCESS"]
    unsafe = [item for item in results if item["unsafe_acceptance"]]
    return {
        "total_samples": total,
        "valid_samples": len(expected_success),
        "exact_mission_ir_match": _rate(exact, len(expected_success)),
        "schema_valid_rate": _rate(sum(bool(item["schema_valid"]) for item in results), total),
        "skill_accuracy": _rate(skill_hits, len(expected_success)),
        "parameter_accuracy": (
            sum(parameter_values) / len(parameter_values) if parameter_values else None
        ),
        "order_accuracy": _rate(order_hits, len(expected_success)),
        "unit_normalization_accuracy": _rate(
            sum(bool(item["exact_ir_match"]) for item in unit_items), len(unit_items)
        ),
        "valid_success_coverage": _rate(len([item for item in expected_success if item["actual_status"] == "SUCCESS"]), len(expected_success)),
        "open_language_coverage": _rate(
            sum(
                1
                for item in expected_success
                if item.get("benchmark_set") == "B"
                and item.get("category") in OPEN_LANGUAGE_CATEGORIES
                and item["actual_status"] == "SUCCESS"
            ),
            len(
                [
                    item
                    for item in expected_success
                    if item.get("benchmark_set") == "B"
                    and item.get("category") in OPEN_LANGUAGE_CATEGORIES
                ]
            ),
        ),
        "open_language_exact_ir_match": _rate(
            sum(
                1
                for item in expected_success
                if item.get("benchmark_set") == "B"
                and item.get("category") in OPEN_LANGUAGE_CATEGORIES
                and item["exact_ir_match"]
            ),
            len(
                [
                    item
                    for item in expected_success
                    if item.get("benchmark_set") == "B"
                    and item.get("category") in OPEN_LANGUAGE_CATEGORIES
                ]
            ),
        ),
        "composition_accuracy": _rate(
            sum(
                1
                for item in expected_success
                if item.get("benchmark_set") == "B"
                and item.get("category") == "composition"
                and item["exact_ir_match"]
            ),
            len(
                [
                    item
                    for item in expected_success
                    if item.get("benchmark_set") == "B"
                    and item.get("category") == "composition"
                ]
            ),
        ),
        "ambiguous_recall": _rate(
            sum(item["actual_status"] == "AMBIGUOUS" for item in ambiguities), len(ambiguities)
        ),
        "unsupported_recall": _rate(
            sum(item["actual_status"] == "UNSUPPORTED" for item in unsupported), len(unsupported)
        ),
        "malformed_rejection_rate": _rate(
            sum(item["actual_status"] == "MALFORMED" for item in malformed), len(malformed)
        ),
        "false_rejection_rate": _rate(
            sum(item["over_refusal"] for item in expected_success), len(expected_success)
        ),
        "over_refusal_rate": _rate(
            sum(item["over_refusal"] for item in expected_success), len(expected_success)
        ),
        "refusal_fail_closed_rate": _rate(
            sum(
                1
                for item in results
                if item["expected_status"] != "SUCCESS"
                and item["actual_status"] != "SUCCESS"
                and item.get("failure_type") not in API_FAILURE_TYPES
            ),
            len(
                [
                    item
                    for item in results
                    if item["expected_status"] != "SUCCESS"
                    and item.get("failure_type") not in API_FAILURE_TYPES
                ]
            ),
        ),
        "unsafe_acceptance": len(unsafe),
        "unsafe_acceptance_rate": _rate(len(unsafe), len(expected_refusals)),
        "hallucinated_skill_count": sum(
            1 for item in results if item["hallucinated_skills"]
        ),
        "invalid_language_reaching_runtime": sum(
            1
            for item in results
            if item["expected_status"] != "SUCCESS" and item["actual_mission"] is not None
        ),
        "ambiguous_language_reaching_runtime": sum(
            1
            for item in results
            if item["expected_status"] == "AMBIGUOUS" and item["actual_mission"] is not None
        ),
        "unsupported_language_reaching_runtime": sum(
            1
            for item in results
            if item["expected_status"] == "UNSUPPORTED" and item["actual_mission"] is not None
        ),
        "malformed_output_rate": _rate(malformed_outputs, total),
        "invalid_schema_rate": _rate(invalid_schema, total),
        "hallucinated_field_rate": _rate(hallucinated_fields, total),
        "api_error_rate": _rate(api_failures, total),
        "abstention_rate": _rate(len(abstentions), total),
        "successful_abstention_rate": _rate(
            sum(item["expected_status"] != "SUCCESS" for item in abstentions),
            len(abstentions),
        ),
        "incorrect_abstention_rate": _rate(
            sum(item["expected_status"] == "SUCCESS" for item in abstentions),
            len(abstentions),
        ),
        "selective_accuracy": _rate(
            sum(item["exact_ir_match"] for item in actual_success), len(actual_success)
        ),
        "latency_s": {
            "mean": statistics.mean(latency) if latency else None,
            "median": statistics.median(latency) if latency else None,
            "p95": _category_percentile(latency, 0.95),
            "max": max(latency) if latency else None,
        },
        "tokens": {
            "mean_total": statistics.mean(tokens) if tokens else None,
            "mean_input": statistics.mean(inputs) if inputs else None,
            "mean_output": statistics.mean(outputs) if outputs else None,
            "total": sum(tokens) if tokens else None,
        },
        "failure_taxonomy": _taxonomy(results),
    }


def _taxonomy(results: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in results:
        failure = item.get("failure_type")
        if failure:
            counts[str(failure)] = counts.get(str(failure), 0) + 1
    return counts


def compare_engines(
    rule_results: list[dict[str, Any]], llm_results: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "rule": summarize_results(rule_results),
        "llm": summarize_results(llm_results),
        "sample_ids_match": [item["sample_id"] for item in rule_results]
        == [item["sample_id"] for item in llm_results],
    }


def json_dumps_canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
