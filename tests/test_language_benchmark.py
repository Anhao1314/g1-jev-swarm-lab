"""Tests for compiler benchmark scoring and canonical Mission IR comparison."""

from __future__ import annotations

from g1swarm.language import LanguageCompiler
from g1swarm.language.benchmark import (
    canonical_mission_hash,
    canonical_mission_payload,
    evaluate_compiler_sample,
    summarize_compiler_results,
)
from g1swarm.mission import MISSION_SCHEMA_VERSION


def _expected_walk4() -> dict:
    return {
        "schema_version": MISSION_SCHEMA_VERSION,
        "steps": [
            {
                "id": "s1",
                "skill": "walk_forward",
                "parameters": {"distance_m": 4.0},
                "depends_on": [],
            }
        ],
    }


def _sample(
    sample_id: str,
    utterance: str,
    status: str,
    *,
    category: str = "atomic_valid",
    group_id: str | None = None,
    expected_mission: dict | None = None,
    expected_error_code: str | None = None,
) -> dict:
    return {
        "sample_id": sample_id,
        "group_id": group_id or sample_id,
        "category": category,
        "source": "hand_authored",
        "utterance": utterance,
        "expected_compiler_status": status,
        "expected_mission": expected_mission,
        "expected_runtime_status": "SUCCESS" if status == "SUCCESS" else "NOT_RUN",
        "expected_error_code": expected_error_code,
        "notes": "",
    }


def test_canonical_payload_ignores_formatting_and_mission_id() -> None:
    first = {
        "mission_id": "lang-a",
        "schema_version": MISSION_SCHEMA_VERSION,
        "steps": [
            {
                "skill": "stop",
                "id": "s1",
                "parameters": {},
                "depends_on": [],
            }
        ],
    }
    second = {
        "mission_id": "lang-b",
        "steps": [
            {
                "id": "s1",
                "skill": "stop",
                "parameters": {},
            }
        ],
        "schema_version": MISSION_SCHEMA_VERSION,
    }
    assert canonical_mission_payload(first) == canonical_mission_payload(second)
    assert canonical_mission_hash(first) == canonical_mission_hash(second)


def test_compiler_benchmark_scores_exact_ir_and_rejection_statuses() -> None:
    compiler = LanguageCompiler()
    results = [
        evaluate_compiler_sample(
            _sample("s-success", "前进4米", "SUCCESS", expected_mission=_expected_walk4()),
            compiler,
        ),
        evaluate_compiler_sample(
            _sample(
                "s-ambiguous",
                "往前走一点",
                "AMBIGUOUS",
                category="ambiguous",
                expected_error_code="AMBIGUOUS_COMMAND",
            ),
            compiler,
        ),
        evaluate_compiler_sample(
            _sample(
                "s-unsupported",
                "拿杯子",
                "UNSUPPORTED",
                category="unsupported",
                expected_error_code="UNSUPPORTED_LANGUAGE_CAPABILITY",
            ),
            compiler,
        ),
    ]
    assert results[0]["exact_ir_match"] is True
    assert results[0]["schema_valid"] is True
    assert results[1]["status_match"] is True
    assert results[2]["status_match"] is True
    summary = summarize_compiler_results(results)
    assert summary["total_samples"] == 3
    assert summary["valid_sample_exact_ir_match"] == 1.0
    assert summary["ambiguity_detection_recall"] == 1.0
    assert summary["unsupported_detection_recall"] == 1.0
    assert summary["hallucinated_skill_count"] == 0
    assert summary["invalid_language_reaching_robot"] == 0
    assert summary["ambiguous_language_reaching_robot"] == 0
    assert summary["unsupported_language_reaching_robot"] == 0


def test_false_rejection_is_visible_and_not_hidden_by_safety_metrics() -> None:
    compiler = LanguageCompiler()
    results = [
        evaluate_compiler_sample(
            _sample(
                "s-false-reject",
                "右转",
                "SUCCESS",
                expected_mission={
                    "schema_version": MISSION_SCHEMA_VERSION,
                    "steps": [
                        {
                            "id": "s1",
                            "skill": "turn",
                            "parameters": {"angle_deg": -45.0},
                            "depends_on": [],
                        }
                    ],
                },
            ),
            compiler,
        )
    ]
    summary = summarize_compiler_results(results)
    assert results[0]["false_rejection"] is True
    assert summary["false_rejection_rate"] == 1.0
    assert summary["hallucinated_skill_count"] == 0
