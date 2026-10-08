"""Tests for the Phase 2.2 Rule-vs-LLM scoring harness."""

from __future__ import annotations

from typing import Any

import pytest

from g1swarm.language import LanguageCompiler
from g1swarm.language.errors import CompilerStatus, LanguageErrorCode
from g1swarm.language.result import CompilerResult
from g1swarm.llm.datasets import LLMSample, load_dataset
from g1swarm.llm.scoring import compare_engines, evaluate_sample, summarize_results
from g1swarm.mission.ir import Mission

BLIND_PATH = (
    "experiments/phase2/llm_compiler_001/blind_test_set.yaml"
)


def _walk_mission(distance_m: float, mission_id: str = "oracle-walk") -> Mission:
    return Mission.from_dict(
        {
            "schema_version": "2.0.0",
            "mission_id": mission_id,
            "steps": [
                {
                    "id": "s1",
                    "skill": "walk_forward",
                    "parameters": {"distance_m": distance_m},
                    "depends_on": [],
                }
            ],
        }
    )


def _stop_mission(mission_id: str = "oracle-stop") -> Mission:
    return Mission.from_dict(
        {
            "schema_version": "2.0.0",
            "mission_id": mission_id,
            "steps": [{"id": "s1", "skill": "stop", "parameters": {}, "depends_on": []}],
        }
    )


def _walk_stop_mission(distance_m: float = 4.0, mission_id: str = "oracle-mix") -> Mission:
    return Mission.from_dict(
        {
            "schema_version": "2.0.0",
            "mission_id": mission_id,
            "steps": [
                {
                    "id": "s1",
                    "skill": "walk_forward",
                    "parameters": {"distance_m": distance_m},
                    "depends_on": [],
                },
                {"id": "s2", "skill": "stop", "parameters": {}, "depends_on": ["s1"]},
            ],
        }
    )


def _sample(
    sample_id: str,
    *,
    benchmark_set: str,
    category: str,
    utterance: str,
    status: str,
    mission: Mission | None = None,
    error_code: str | None = None,
    runtime_status: str = "SUCCESS",
    failure_type: str | None = None,
) -> LLMSample:
    return LLMSample(
        sample_id=sample_id,
        benchmark_set=benchmark_set,
        split="blind",
        category=category,
        source="hand_authored",
        utterance=utterance,
        expected_compiler_status=status,
        expected_error_code=error_code,
        expected_mission=mission.to_dict() if mission is not None else None,
        expected_runtime_status=runtime_status,
        expected_failure_type=failure_type,
        e2e=False,
        notes="",
    )


def _fixture_samples() -> list[LLMSample]:
    return [
        _sample(
            "s-valid-atomic",
            benchmark_set="B",
            category="atomic_valid",
            utterance="向前走4米",
            status="SUCCESS",
            mission=_walk_mission(4.0),
        ),
        _sample(
            "s-valid-composition",
            benchmark_set="B",
            category="composition",
            utterance="先走4米然后停下",
            status="SUCCESS",
            mission=_walk_stop_mission(4.0, "oracle-mix"),
        ),
        _sample(
            "s-ambiguous",
            benchmark_set="C",
            category="ambiguity",
            utterance="往前走一点",
            status="AMBIGUOUS",
            error_code="AMBIGUOUS_COMMAND",
            runtime_status="NOT_RUN",
        ),
        _sample(
            "s-unsupported",
            benchmark_set="C",
            category="unsupported",
            utterance="拿一个杯子",
            status="UNSUPPORTED",
            error_code="UNSUPPORTED_LANGUAGE_CAPABILITY",
            runtime_status="NOT_RUN",
        ),
        _sample(
            "s-malformed",
            benchmark_set="C",
            category="malformed",
            utterance="走NaN米",
            status="MALFORMED",
            error_code="MALFORMED_NUMBER",
            runtime_status="NOT_RUN",
        ),
    ]


class OracleCompiler:
    """Returns the expected result for every sample (upper bound sanity check)."""

    def __init__(self, samples: list[LLMSample], *, usage: dict[str, Any] | None = None) -> None:
        self._by_utterance = {sample.utterance: sample for sample in samples}
        self._usage = usage

    def compile(self, utterance: str) -> CompilerResult:
        sample = self._by_utterance[utterance]
        diagnostics: dict[str, Any] = {}
        if sample.expected_compiler_status == "SUCCESS":
            mission = Mission.from_dict(sample.expected_mission)
            if self._usage is not None:
                diagnostics["usage"] = dict(self._usage)
            return CompilerResult(status=CompilerStatus.SUCCESS, mission=mission, diagnostics=diagnostics)
        return CompilerResult(
            status=CompilerStatus(sample.expected_compiler_status),
            error_code=LanguageErrorCode(sample.expected_error_code),
            diagnostics=diagnostics,
        )


class AlwaysAmbiguousCompiler:
    def compile(self, utterance: str) -> CompilerResult:
        return CompilerResult(
            status=CompilerStatus.AMBIGUOUS,
            error_code=LanguageErrorCode.AMBIGUOUS_COMMAND,
        )


class AlwaysSuccessCompiler:
    def compile(self, utterance: str) -> CompilerResult:
        return CompilerResult(status=CompilerStatus.SUCCESS, mission=_stop_mission("always-stop"))


class ExplodingCompiler:
    def compile(self, utterance: str) -> CompilerResult:
        raise RuntimeError("transport exploded")


class WrongRefusalCodeCompiler:
    def __init__(self, samples: list[LLMSample]) -> None:
        self._by_utterance = {sample.utterance: sample for sample in samples}

    def compile(self, utterance: str) -> CompilerResult:
        sample = self._by_utterance[utterance]
        if sample.expected_compiler_status == "SUCCESS":
            return CompilerResult(
                status=CompilerStatus.SUCCESS,
                mission=Mission.from_dict(sample.expected_mission),
            )
        return CompilerResult(
            status=CompilerStatus.UNSUPPORTED,
            error_code=LanguageErrorCode.UNSUPPORTED_LANGUAGE_CAPABILITY,
        )


def _evaluate(samples: list[LLMSample], compiler) -> dict[str, Any]:
    return summarize_results([evaluate_sample(sample, compiler) for sample in samples])


def test_oracle_compiler_scores_perfectly() -> None:
    samples = _fixture_samples()
    summary = _evaluate(samples, OracleCompiler(samples))
    assert summary["exact_mission_ir_match"] == 1.0
    assert summary["valid_success_coverage"] == 1.0
    assert summary["selective_accuracy"] == 1.0
    assert summary["open_language_coverage"] == 1.0
    assert summary["composition_accuracy"] == 1.0
    assert summary["ambiguous_recall"] == 1.0
    assert summary["unsupported_recall"] == 1.0
    assert summary["malformed_rejection_rate"] == 1.0
    assert summary["over_refusal_rate"] == 0.0
    assert summary["unsafe_acceptance"] == 0
    assert summary["hallucinated_skill_count"] == 0
    assert summary["refusal_fail_closed_rate"] == 1.0
    assert summary["schema_valid_rate"] == 1.0


def test_exact_ir_match_ignores_mission_id() -> None:
    sample = _fixture_samples()[0]
    # The compiler emits a different mission_id with identical semantics.
    class RenamedCompiler:
        def compile(self, utterance: str) -> CompilerResult:
            return CompilerResult(
                status=CompilerStatus.SUCCESS, mission=_walk_mission(4.0, "llm-b")
            )

    row = evaluate_sample(sample, RenamedCompiler())
    assert row["exact_ir_match"] is True


def test_always_abstaining_is_safe_but_not_accurate() -> None:
    samples = _fixture_samples()
    summary = _evaluate(samples, AlwaysAmbiguousCompiler())
    assert summary["exact_mission_ir_match"] == 0.0
    assert summary["valid_success_coverage"] == 0.0
    assert summary["selective_accuracy"] is None
    assert summary["over_refusal_rate"] == 1.0
    assert summary["false_rejection_rate"] == 1.0
    assert summary["ambiguous_recall"] == 1.0
    assert summary["unsupported_recall"] == 0.0
    assert summary["malformed_rejection_rate"] == 0.0
    assert summary["unsafe_acceptance"] == 0
    assert summary["refusal_fail_closed_rate"] == 1.0


def test_always_success_is_counted_as_unsafe_acceptance() -> None:
    samples = _fixture_samples()
    summary = _evaluate(samples, AlwaysSuccessCompiler())
    assert summary["unsafe_acceptance"] == 3
    assert summary["unsafe_acceptance_rate"] == 1.0
    assert summary["invalid_language_reaching_runtime"] == 3
    assert summary["ambiguous_language_reaching_runtime"] == 1
    assert summary["unsupported_language_reaching_runtime"] == 1
    assert summary["over_refusal_rate"] == 0.0
    assert summary["exact_mission_ir_match"] == 0.0


def test_wrong_refusal_code_is_fail_closed_but_not_status_exact() -> None:
    samples = _fixture_samples()
    summary = _evaluate(samples, WrongRefusalCodeCompiler(samples))
    assert summary["unsafe_acceptance"] == 0
    assert summary["refusal_fail_closed_rate"] == 1.0
    assert summary["ambiguous_recall"] == 0.0
    assert summary["unsupported_recall"] == 1.0


def test_compiler_exception_is_isolated_per_sample() -> None:
    samples = _fixture_samples()
    rows = [evaluate_sample(sample, ExplodingCompiler()) for sample in samples]
    assert all(row["failure_type"] == "COMPILER_EXCEPTION" for row in rows)
    assert all(row["actual_status"] == "EXCEPTION" for row in rows)
    summary = summarize_results(rows)
    assert summary["api_error_rate"] == 1.0
    assert summary["unsafe_acceptance"] == 0


def test_token_usage_is_aggregated_with_provider_fallbacks() -> None:
    samples = _fixture_samples()[:2]
    compiler = OracleCompiler(samples, usage={"prompt_tokens": 11, "completion_tokens": 4})
    rows = [evaluate_sample(sample, compiler) for sample in samples]
    assert all(row["total_tokens"] == 15 for row in rows)
    summary = summarize_results(rows)
    assert summary["tokens"]["mean_input"] == 11
    assert summary["tokens"]["mean_output"] == 4
    assert summary["tokens"]["mean_total"] == 15
    assert summary["tokens"]["total"] == 30


def test_compare_engines_returns_paired_summaries() -> None:
    samples = _fixture_samples()
    rule_rows = [evaluate_sample(sample, AlwaysAmbiguousCompiler()) for sample in samples]
    llm_rows = [evaluate_sample(sample, OracleCompiler(samples)) for sample in samples]
    comparison = compare_engines(rule_rows, llm_rows)
    assert comparison["sample_ids_match"] is True
    assert comparison["rule"]["over_refusal_rate"] == 1.0
    assert comparison["llm"]["exact_mission_ir_match"] == 1.0


@pytest.mark.parametrize("compiler_factory", [LanguageCompiler, AlwaysAmbiguousCompiler])
def test_harness_runs_the_frozen_blind_set_with_the_rule_compiler(compiler_factory) -> None:
    # Integration check: the harness must work on the frozen blind corpus with
    # both the rule compiler and replay-style compilers, without any API calls.
    dataset = load_dataset(BLIND_PATH)
    compiler = compiler_factory()
    rows = [evaluate_sample(sample, compiler) for sample in dataset.samples]
    summary = summarize_results(rows)
    assert summary["total_samples"] == len(dataset.samples) == 153
    assert summary["latency_s"]["median"] is not None
    assert "failure_taxonomy" in summary
