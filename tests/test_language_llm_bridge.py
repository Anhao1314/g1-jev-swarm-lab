"""Tests for the runner-facing Phase 2.2 bridge (language.llm API)."""

from __future__ import annotations

import json

import pytest

from g1swarm.language.llm import (
    BackendError,
    LLMMissionCompiler,
    ReplayBackend,
    OpenAICompatibleBackend,
    run_llm_campaign,
    write_records,
)
from g1swarm.llm.backend import ScriptedBackend
from g1swarm.mission import MISSION_SCHEMA_VERSION
from g1swarm.paths import resolve_repo_path

PROMPT_PATH = resolve_repo_path("prompts/llm_mission_compiler_v1.txt")


def _envelope(status, mission, error_code) -> str:
    return json.dumps(
        {"status": status, "mission": mission, "error_code": error_code},
        ensure_ascii=False,
    )


def _walk4() -> dict:
    return {
        "schema_version": MISSION_SCHEMA_VERSION,
        "mission_id": "bridge-walk4",
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
    sample_id, utterance, status, *, mission=None, error_code=None, category="atomic_valid"
):
    return {
        "sample_id": sample_id,
        "category": category,
        "source": "test",
        "utterance": utterance,
        "expected_compiler_status": status,
        "expected_mission": mission,
        "expected_error_code": error_code,
    }


class _Corpus:
    dataset_id = "bridge-test"


def _compiler(backend) -> LLMMissionCompiler:
    return LLMMissionCompiler(
        backend,
        prompt_path=PROMPT_PATH,
        max_input_chars=512,
        max_output_chars=16384,
        expected_prompt_sha256=None,
    )


def test_openai_compatible_backend_requires_configured_key() -> None:
    with pytest.raises(BackendError) as info:
        OpenAICompatibleBackend.from_env(
            model="deepseek-flash",
            base_url="http://127.0.0.1:9/v1",
            api_key_env="MISSING_BRIDGE_KEY",
            environ={},
        )
    assert info.value.reason == "configuration"
    assert "MISSING_BRIDGE_KEY" in info.value.message


def test_bridge_compiler_exposes_runner_diagnostics() -> None:
    backend = ScriptedBackend({"前进4米": _envelope("SUCCESS", _walk4(), None)})
    result = _compiler(backend).compile("前进4米")
    assert result.mission is not None
    diagnostics = result.diagnostics
    for key in (
        "prompt_sha256",
        "model",
        "request_parameters",
        "raw_response",
        "validation",
        "usage",
        "attempts",
        "failure_type",
    ):
        assert key in diagnostics
    assert diagnostics["validation"]["valid"] is True


def test_campaign_records_replay_and_scores() -> None:
    responses = {
        "前进4米": _envelope("SUCCESS", _walk4(), None),
        "往前走一点": _envelope("AMBIGUOUS", None, "AMBIGUOUS_COMMAND"),
        "拿一个杯子": _envelope("UNSUPPORTED", None, "UNSUPPORTED_LANGUAGE_CAPABILITY"),
    }
    samples = [
        _sample("b-1", "前进4米", "SUCCESS", mission=_walk4()),
        _sample("b-2", "往前走一点", "AMBIGUOUS", error_code="AMBIGUOUS_COMMAND", category="ambiguity"),
        _sample(
            "b-3",
            "拿一个杯子",
            "UNSUPPORTED",
            error_code="UNSUPPORTED_LANGUAGE_CAPABILITY",
            category="unsupported",
        ),
    ]
    compiler = _compiler(ScriptedBackend(responses))
    run = run_llm_campaign(
        compiler=compiler,
        samples=samples,
        protocol={"experiment_id": "llm_compiler_001", "_protocol_sha256": "sha"},
        corpus=_Corpus(),
        corpus_path=PROMPT_PATH,
        campaign="development",
        backend_kind="http",
        record_raw=True,
    )
    assert run.summary["total_samples"] == 3
    assert run.summary["valid_sample_exact_ir_match"] == 1.0
    assert run.summary["invalid_language_reaching_robot"] == 0
    assert run.summary["live_llm_call"] is True
    assert run.summary["dataset_id"] == "bridge-test"
    assert run.summary["llm_diagnostics"]["samples"] == 3
    assert len(run.records) == 3

    replay = _compiler(ReplayBackend(run.records))
    replay_statuses = [replay.compile(sample["utterance"]).status.value for sample in samples]
    assert replay_statuses == ["SUCCESS", "AMBIGUOUS", "UNSUPPORTED"]


def test_replay_backend_miss_fails_closed() -> None:
    backend = ReplayBackend(
        [
            {
                "request_key": "0" * 64,
                "utterance": "前进4米",
                "response_text": "{}",
                "model": "m",
            }
        ]
    )
    result = _compiler(backend).compile("没有记录")
    assert result.status.value == "MALFORMED"
    assert result.error_code is not None
    assert result.error_code.value == "LLM_CONFIGURATION_ERROR"


def test_write_records_round_trip(tmp_path) -> None:
    from g1swarm.language.llm import load_records

    path = write_records(tmp_path / "records.jsonl", [{"a": 1}, {"b": 2}])
    assert load_records(path) == [{"a": 1}, {"b": 2}]
