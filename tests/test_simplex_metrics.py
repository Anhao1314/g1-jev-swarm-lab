"""Tests for Phase 2.2b simplex routing metrics and hard gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from g1swarm.language.errors import CompilerStatus, LanguageErrorCode
from g1swarm.mission.ir import MISSION_SCHEMA_VERSION, Mission, MissionStep, SkillName
from g1swarm.simplex.metrics import (
    COMPARISON_KEYS,
    comparison_row,
    evaluate_hard_gates,
    evaluate_simplex_sample,
    latency_metrics,
    percentile,
    summarize_simplex_results,
)


@dataclass
class StubResult:
    status: CompilerStatus
    mission: Mission | None = None
    normalized_text: str = ""
    error_code: LanguageErrorCode | None = None
    error_message: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    route: str = "LARK_FAST_PATH"
    guard_status: str = "PASS"
    guard_reason_code: str | None = None
    canonical_text: str | None = None
    canonicalization_status: str | None = None
    llm_invocations: int = 0
    provider_tokens: int | None = None
    latency_s: float = 0.0


class ScriptedCompiler:
    treatment = "simplex_canonical"

    def __init__(self, plan):
        self.plan = plan
        self.calls: list[str] = []

    def compile(self, text: str) -> StubResult:
        self.calls.append(text)
        return self.plan[text]


def _mission(skill: SkillName, parameters: dict[str, float]) -> Mission:
    return Mission(
        mission_id="m-metrics-test",
        steps=(
            MissionStep(step_id="s1", skill=skill, parameters=parameters),
        ),
        schema_version=MISSION_SCHEMA_VERSION,
    )


STAND_MISSION = _mission(SkillName.STAND, {"duration_s": 2.0})
WALK_MISSION = _mission(SkillName.WALK_FORWARD, {"distance_m": 4.0})


def _sample(sample_id: str, utterance: str, expected_status: str, expected_mission=None) -> dict:
    return {
        "sample_id": sample_id,
        "group_id": None,
        "category": "test",
        "source": "unit",
        "utterance": utterance,
        "expected_compiler_status": expected_status,
        "expected_error_code": None,
        "expected_mission": expected_mission,
    }


def _expected(mission: Mission) -> dict:
    return mission.to_dict()


VALID_1 = _sample("s-valid-1", "站立", "SUCCESS", _expected(STAND_MISSION))
VALID_2 = _sample("s-valid-2", "麻烦往前走四米", "SUCCESS", _expected(WALK_MISSION))
VALID_3 = _sample("s-valid-3", "向前走四米", "SUCCESS", _expected(WALK_MISSION))
MALFORMED_DUP = _sample("s-mal-dup", "前进4米然后然后停止", "MALFORMED")
MALFORMED_LEAD = _sample("s-mal-lead", "然后前进4米", "MALFORMED")
MALFORMED_TRAIL = _sample("s-mal-trail", "前进4米然后", "MALFORMED")
MALFORMED_SILENT = _sample("s-mal-silent", "前进4米，然后，再停止", "MALFORMED")
AMBIGUOUS = _sample("s-amb", "往前走一点", "AMBIGUOUS")
UNSUPPORTED = _sample("s-unsup", "拿杯子", "UNSUPPORTED")


def _plan() -> dict[str, StubResult]:
    return {
        "站立": StubResult(
            status=CompilerStatus.SUCCESS,
            mission=STAND_MISSION,
            route="LARK_FAST_PATH",
            llm_invocations=0,
        ),
        "麻烦往前走四米": StubResult(
            status=CompilerStatus.SUCCESS,
            mission=WALK_MISSION,
            route="CANONICALIZED",
            llm_invocations=1,
            provider_tokens=100,
            canonical_text="前进4米",
            canonicalization_status="SUCCESS",
        ),
        "向前走四米": StubResult(
            status=CompilerStatus.MALFORMED,
            route="GUARD_REJECT",
            guard_status="MALFORMED",
            guard_reason_code="EMPTY_CLAUSE",
            error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
            llm_invocations=0,
        ),
        "前进4米然后然后停止": StubResult(
            status=CompilerStatus.MALFORMED,
            route="GUARD_REJECT",
            guard_status="MALFORMED",
            guard_reason_code="DUPLICATE_CONNECTOR",
            error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
            llm_invocations=0,
        ),
        "然后前进4米": StubResult(
            status=CompilerStatus.MALFORMED,
            route="GUARD_REJECT",
            guard_status="MALFORMED",
            guard_reason_code="LEADING_CONNECTOR",
            error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
            llm_invocations=0,
        ),
        "前进4米然后": StubResult(
            status=CompilerStatus.MALFORMED,
            route="CANONICAL_LARK_REJECT",
            guard_status="PASS",
            canonical_text="前进4米然后停止",
            canonicalization_status="SUCCESS",
            error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
            llm_invocations=1,
            provider_tokens=60,
        ),
        "前进4米，然后，再停止": StubResult(
            status=CompilerStatus.SUCCESS,
            mission=WALK_MISSION,
            route="CANONICALIZED",
            guard_status="PASS",
            canonical_text="前进4米，然后停止",
            canonicalization_status="SUCCESS",
            llm_invocations=1,
            provider_tokens=50,
        ),
        "往前走一点": StubResult(
            status=CompilerStatus.AMBIGUOUS,
            route="CANONICALIZER_REFUSAL",
            guard_status="PASS",
            canonicalization_status="AMBIGUOUS",
            error_code=LanguageErrorCode.AMBIGUOUS_COMMAND,
            llm_invocations=1,
            provider_tokens=80,
        ),
        "拿杯子": StubResult(
            status=CompilerStatus.UNSUPPORTED,
            route="CANONICALIZER_REFUSAL",
            guard_status="PASS",
            canonicalization_status="UNSUPPORTED",
            error_code=LanguageErrorCode.UNSUPPORTED_LANGUAGE_CAPABILITY,
            llm_invocations=1,
            provider_tokens=70,
        ),
    }


def _campaign():
    samples = [
        VALID_1,
        VALID_2,
        VALID_3,
        MALFORMED_DUP,
        MALFORMED_LEAD,
        MALFORMED_TRAIL,
        MALFORMED_SILENT,
        AMBIGUOUS,
        UNSUPPORTED,
    ]
    latencies = [0.01, 0.50, 0.02, 0.03, 0.60, 0.70, 0.80, 0.04, 0.90]
    compiler = ScriptedCompiler(_plan())
    rows = []
    for sample, latency in zip(samples, latencies):
        row = evaluate_simplex_sample(sample, compiler)
        row["system_latency_s"] = latency
        row["latency_s"] = latency
        rows.append(row)
    return rows


def test_evaluate_simplex_sample_records_routing_fields() -> None:
    rows = _campaign()
    by_id = {row["sample_id"]: row for row in rows}

    assert by_id["s-valid-1"]["route"] == "LARK_FAST_PATH"
    assert by_id["s-valid-1"]["llm_invocations"] == 0
    assert by_id["s-valid-2"]["route"] == "CANONICALIZED"
    assert by_id["s-valid-2"]["provider_tokens"] == 100
    assert by_id["s-mal-dup"]["guard_reason_code"] == "DUPLICATE_CONNECTOR"
    assert by_id["s-valid-3"]["guard_status"] == "MALFORMED"
    assert by_id["s-mal-silent"]["actual_mission"] is not None


def test_summary_reports_silent_repair_and_unsafe_acceptance() -> None:
    summary = summarize_simplex_results(_campaign())

    assert summary["malformed_expected_samples"] == 4
    assert summary["silent_repair_count"] == 1
    assert summary["silent_repair_rate"] == pytest.approx(0.25)
    assert summary["silent_repair_sample_ids"] == ["s-mal-silent"]
    assert summary["unsafe_acceptance"] == 1
    assert summary["invalid_language_reaching_robot"] == 1


def test_guard_confusion_matrix_counts_false_positives() -> None:
    summary = summarize_simplex_results(_campaign())

    assert summary["guard_true_positive"] == 2
    assert summary["guard_false_positive"] == 1
    assert summary["guard_true_negative"] == 4
    assert summary["guard_false_negative"] == 2
    assert summary["guard_precision"] == pytest.approx(2 / 3)
    assert summary["guard_recall"] == pytest.approx(0.5)
    assert summary["guard_false_positive_rate"] == pytest.approx(0.2)


def test_provider_invocation_accounting() -> None:
    summary = summarize_simplex_results(_campaign())

    assert summary["llm_calls"] == 5
    assert summary["llm_invocation_rate"] == pytest.approx(5 / 9)
    assert summary["direct_lark_hit_rate"] == pytest.approx(1 / 9)
    assert summary["guard_reject_without_llm_rate"] == pytest.approx(3 / 9)
    assert summary["canonicalizer_escalation_rate"] == pytest.approx(5 / 9)
    assert summary["canonicalization_success_rate"] == pytest.approx(2 / 5)
    assert summary["canonical_text_lark_acceptance_rate"] == pytest.approx(2 / 3)
    assert summary["route_breakdown"]["GUARD_REJECT"] == 3


def test_token_efficiency_metrics() -> None:
    summary = summarize_simplex_results(_campaign(), baseline_mean_tokens=100.0)

    assert summary["total_provider_tokens"] == 360
    assert summary["mean_tokens_per_llm_call"] == pytest.approx(72.0)
    assert summary["tokens_per_user_mission"] == pytest.approx(40.0)
    assert summary["tokens_per_successful_mission"] == pytest.approx(180.0)
    assert summary["avoided_provider_calls"] == 4
    assert summary["estimated_tokens_saved_vs_direct"] == pytest.approx(540.0)


def test_latency_percentiles_and_route_split() -> None:
    rows = _campaign()
    metrics = latency_metrics(rows)

    assert metrics["mean_system_latency_s"] == pytest.approx(sum(row["latency_s"] for row in rows) / 9)
    assert metrics["p95_system_latency_s"] == pytest.approx(0.90)
    assert metrics["max_system_latency_s"] == pytest.approx(0.90)
    assert metrics["fast_path_latency"]["samples"] == 1
    assert metrics["escalated_latency"]["samples"] == 5


def test_percentile_helper_is_deterministic() -> None:
    assert percentile([], 0.5) is None
    assert percentile([4.0], 0.95) == 4.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    with pytest.raises(ValueError):
        percentile([1.0], 1.5)


def test_hard_gates_fail_when_silent_repair_is_nonzero() -> None:
    summary = summarize_simplex_results(_campaign())
    gates = evaluate_hard_gates(summary)

    assert gates["all_pass"] is False
    assert gates["gates"]["silent_repair_rate"]["pass"] is False
    assert gates["gates"]["unsafe_acceptance"]["value"] == 1
    assert set(COMPARISON_KEYS) <= set(comparison_row(summary))


def test_injected_open_language_coverage_feeds_the_gate() -> None:
    summary = summarize_simplex_results(
        _campaign(), extra={"open_language_coverage": 0.99}
    )

    assert summary["open_language_coverage"] == pytest.approx(0.99)
    gates = evaluate_hard_gates(summary)
    assert gates["gates"]["open_language_coverage"]["pass"] is True
