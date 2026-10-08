"""Compiler benchmark scoring helpers for Phase 2.1.

The benchmark compares canonical Mission IR documents, never JSON formatting.
It does not run MuJoCo; end-to-end equivalence is a separate script.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from statistics import mean
from typing import Any, Mapping

from ..mission.ir import MISSION_SCHEMA_VERSION, Mission, SkillName
from ..mission.validator import MissionValidator

SUPPORTED_SKILLS = frozenset(skill.value for skill in SkillName)


def canonical_mission_payload(
    mission: Mission | Mapping[str, Any],
    *,
    include_mission_id: bool = False,
) -> dict[str, Any]:
    if isinstance(mission, Mission):
        document = mission.to_dict()
    else:
        document = dict(mission)
    steps = []
    for index, raw_step in enumerate(document.get("steps", []), start=1):
        step = dict(raw_step)
        parameters = {
            str(key): float(value) if isinstance(value, (int, float)) else value
            for key, value in dict(step.get("parameters", {})).items()
        }
        steps.append(
            {
                "id": str(step.get("id", f"s{index}")),
                "skill": str(step.get("skill")),
                "parameters": dict(sorted(parameters.items())),
                "depends_on": [str(value) for value in step.get("depends_on", [])],
            }
        )
    payload: dict[str, Any] = {
        "schema_version": document.get("schema_version", MISSION_SCHEMA_VERSION),
        "steps": steps,
    }
    if include_mission_id:
        payload["mission_id"] = str(document.get("mission_id"))
    return payload


def canonical_mission_hash(
    mission: Mission | Mapping[str, Any], *, include_mission_id: bool = False
) -> str:
    payload = canonical_mission_payload(mission, include_mission_id=include_mission_id)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _expected_mission(sample: Mapping[str, Any]) -> dict[str, Any] | None:
    expected = sample.get("expected_mission")
    if expected is None:
        return None
    return canonical_mission_payload(expected)


def evaluate_compiler_sample(sample: Mapping[str, Any], compiler) -> dict[str, Any]:
    started = time.perf_counter()
    result = compiler.compile(str(sample.get("utterance", "")))
    latency_s = time.perf_counter() - started
    expected_status = str(sample.get("expected_compiler_status"))
    expected_error = sample.get("expected_error_code")
    expected_mission = _expected_mission(sample)
    actual_mission = (
        canonical_mission_payload(result.mission) if result.mission is not None else None
    )
    schema_valid = False
    if result.mission is not None:
        schema_valid = MissionValidator().validate(result.mission).valid
    exact_ir_match = bool(
        result.status.value == "SUCCESS"
        and expected_status == "SUCCESS"
        and expected_mission is not None
        and actual_mission == expected_mission
    )
    expected_status_match = result.status.value == expected_status
    expected_error_match = (
        expected_error is None
        or (result.error_code is not None and result.error_code.value == expected_error)
    )
    actual_skills = {
        str(step["skill"])
        for step in (actual_mission or {}).get("steps", [])
    }
    hallucinated_skills = sorted(actual_skills - SUPPORTED_SKILLS)
    invalid_expected = expected_status != "SUCCESS"
    return {
        "sample_id": sample.get("sample_id"),
        "group_id": sample.get("group_id"),
        "category": sample.get("category"),
        "source": sample.get("source"),
        "utterance": sample.get("utterance"),
        "expected_status": expected_status,
        "actual_status": result.status.value,
        "expected_error_code": expected_error,
        "actual_error_code": result.error_code.value if result.error_code else None,
        "expected_ir_hash": (
            canonical_mission_hash(expected_mission) if expected_mission is not None else None
        ),
        "actual_ir_hash": (
            canonical_mission_hash(result.mission) if result.mission is not None else None
        ),
        "actual_mission_id": result.mission.mission_id if result.mission else None,
        "expected_mission": expected_mission,
        "actual_mission": actual_mission,
        "exact_ir_match": exact_ir_match,
        "status_match": expected_status_match,
        "error_code_match": expected_error_match,
        "schema_valid": schema_valid,
        "false_rejection": expected_status == "SUCCESS" and result.status.value != "SUCCESS",
        "invalid_language_reaching_robot": bool(
            invalid_expected and result.mission is not None
        ),
        "hallucinated_skills": hallucinated_skills,
        "latency_s": latency_s,
        "normalized_text": result.normalized_text,
        "error_message": result.error_message,
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return (numerator / denominator) if denominator else None


def _category_match(results: list[dict[str, Any]], category: str) -> tuple[int, int]:
    selected = [item for item in results if item.get("category") == category]
    return sum(bool(item["exact_ir_match"]) for item in selected), len(selected)


def summarize_compiler_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    success_expected = [item for item in results if item["expected_status"] == "SUCCESS"]
    success_actual = [item for item in results if item["actual_status"] == "SUCCESS"]
    ambiguous_expected = [item for item in results if item["expected_status"] == "AMBIGUOUS"]
    unsupported_expected = [
        item for item in results if item["expected_status"] == "UNSUPPORTED"
    ]
    malformed_expected = [item for item in results if item["expected_status"] == "MALFORMED"]
    exact_matches = sum(bool(item["exact_ir_match"]) for item in success_expected)
    schema_valid = sum(bool(item["schema_valid"]) for item in success_actual)

    paraphrase_groups: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        if item["expected_status"] == "SUCCESS" and item.get("group_id"):
            paraphrase_groups.setdefault(str(item["group_id"]), []).append(item)
    paraphrase_total = 0
    paraphrase_consistent = 0
    for items in paraphrase_groups.values():
        if len(items) < 2:
            continue
        paraphrase_total += 1
        hashes = {
            json.dumps(item["actual_mission"], sort_keys=True, ensure_ascii=False)
            for item in items
        }
        if all(item["exact_ir_match"] for item in items) and len(hashes) == 1:
            paraphrase_consistent += 1

    atomic_hits, atomic_total = _category_match(results, "atomic_valid")
    composition_hits, composition_total = _category_match(results, "composition")
    unit_hits, unit_total = _category_match(results, "unit_variant")
    number_items = [
        item
        for item in results
        if item.get("category") in {"atomic_valid", "unit_variant", "sequence_variant"}
    ]
    number_hits = sum(bool(item["exact_ir_match"]) for item in number_items)
    false_rejections = sum(bool(item["false_rejection"]) for item in success_expected)
    hallucinated = sum(1 for item in results if item["hallucinated_skills"])
    invalid_reaching = sum(bool(item["invalid_language_reaching_robot"]) for item in results)
    by_source: dict[str, dict[str, Any]] = {}
    for source in sorted({str(item.get("source")) for item in results}):
        subset = [item for item in results if str(item.get("source")) == source]
        subset_success = [item for item in subset if item["expected_status"] == "SUCCESS"]
        by_source[source] = {
            "samples": len(subset),
            "expected_success": len(subset_success),
            "exact_ir_match_rate": _rate(
                sum(bool(item["exact_ir_match"]) for item in subset_success),
                len(subset_success),
            ),
            "status_match_rate": _rate(
                sum(bool(item["status_match"]) for item in subset), len(subset)
            ),
            "hallucinated_skill_count": sum(
                1 for item in subset if item["hallucinated_skills"]
            ),
            "ambiguous_language_reaching_robot": sum(
                item["expected_status"] == "AMBIGUOUS" and item["actual_mission"] is not None
                for item in subset
            ),
            "unsupported_language_reaching_robot": sum(
                item["expected_status"] == "UNSUPPORTED" and item["actual_mission"] is not None
                for item in subset
            ),
        }
    return {
        "total_samples": total,
        "valid_sample_exact_ir_match": _rate(exact_matches, len(success_expected)),
        "schema_valid_rate": _rate(schema_valid, len(success_actual)),
        "paraphrase_consistency_rate": _rate(paraphrase_consistent, paraphrase_total),
        "atomic_accuracy": _rate(atomic_hits, atomic_total),
        "composition_accuracy": _rate(composition_hits, composition_total),
        "number_normalization_accuracy": _rate(number_hits, len(number_items)),
        "unit_normalization_accuracy": _rate(unit_hits, unit_total),
        "ambiguity_detection_recall": _rate(
            sum(item["actual_status"] == "AMBIGUOUS" for item in ambiguous_expected),
            len(ambiguous_expected),
        ),
        "ambiguity_false_positive_rate": _rate(
            sum(item["actual_status"] == "AMBIGUOUS" for item in results if item["expected_status"] != "AMBIGUOUS"),
            len([item for item in results if item["expected_status"] != "AMBIGUOUS"]),
        ),
        "unsupported_detection_recall": _rate(
            sum(item["actual_status"] == "UNSUPPORTED" for item in unsupported_expected),
            len(unsupported_expected),
        ),
        "malformed_rejection_rate": _rate(
            sum(item["actual_status"] == "MALFORMED" for item in malformed_expected),
            len(malformed_expected),
        ),
        "false_rejection_rate": _rate(false_rejections, len(success_expected)),
        "hallucinated_skill_count": hallucinated,
        "invalid_language_reaching_robot": invalid_reaching,
        "ambiguous_language_reaching_robot": sum(
            item["expected_status"] == "AMBIGUOUS" and item["actual_mission"] is not None
            for item in results
        ),
        "unsupported_language_reaching_robot": sum(
            item["expected_status"] == "UNSUPPORTED" and item["actual_mission"] is not None
            for item in results
        ),
        "mean_compiler_latency_s": mean(item["latency_s"] for item in results) if results else None,
        "by_source": by_source,
        "max_compiler_latency_s": max((item["latency_s"] for item in results), default=None),
    }
