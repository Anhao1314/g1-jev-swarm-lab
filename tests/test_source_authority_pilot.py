"""Synthetic Pilot accounting and population-integrity tests; no live provider."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from g1swarm.language.errors import CompilerStatus
from g1swarm.language.result import CompilerResult
from g1swarm.llm.backend import LLMBackendConfig, LLMBackendError
from g1swarm.mission.ir import Mission


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_source_authority_pilot.py"
SPEC = importlib.util.spec_from_file_location("source_authority_pilot_test", SCRIPT)
pilot = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pilot)


def sample(sid="synthetic-stop"):
    return {
        "sample_id": sid,
        "population": "controlled",
        "split": "already_seen_regression",
        "family": "synthetic",
        "source": "停止",
        "expected_status": "SUCCESS",
        "expected_mission": {
            "schema_version": "2.0.0",
            "mission_id": "expected",
            "steps": [{"id": "s1", "skill": "stop", "parameters": {}, "depends_on": []}],
        },
        "baseline_recorded": None,
    }


def evidence(calls=0, *, tokens=None):
    return {
        "provider_calls": calls,
        "provider_attempts": calls,
        "events": [],
        "responses": [{"usage": {"total_tokens": tokens}}] if tokens is not None else [],
    }


def row(sid="synthetic-stop", *, reason="UNIQUE_SOURCE_AUTHORITY", status="AUTHORIZED_UNIQUE", calls=1):
    s = sample(sid)
    b = CompilerResult(CompilerStatus.SUCCESS, Mission.from_dict(s["expected_mission"]), s["source"])
    gated = CompilerResult(
        CompilerStatus.SUCCESS if status == "AUTHORIZED_UNIQUE" else CompilerStatus.MALFORMED,
        b.mission if status == "AUTHORIZED_UNIQUE" else None,
        s["source"],
        diagnostics={
            "source_authorization": {
                "status": status,
                "reason_code": reason,
                "diagnostics": {"provider_calls": calls},
            }
        },
    )
    arm = {
        "result": gated.to_dict(),
        "score": pilot.score(s, gated),
        "added_wall_s": 0.5,
        "live_evidence": evidence(calls),
    }
    return {
        "sample": s,
        "baseline_kind": "new_frozen_B_first_response",
        "B": {"result": b.to_dict(), "score": pilot.score(s, b), "live_evidence": evidence()},
        "treatments": {"ambiguity": copy.deepcopy(arm), "source_verifier": arm},
    }


@pytest.mark.parametrize("reason", [
    "UNUSABLE_RESPONSE", "MALFORMED_OUTPUT", "INCOMPLETE_SOURCE_COVERAGE", "BACKEND_FAILURE",
])
def test_actual_authorizer_unusable_reason_codes_are_counted(reason):
    result = pilot.aggregate([row(reason=reason, status="UNKNOWN")], "source_verifier")
    assert result["verifier_unusable"] == 1
    assert result["new_provider_calls"] == 1
    assert result["authorization_status"] == {"UNKNOWN": 1}


def test_usable_source_candidate_disagreement_is_not_unusable_response():
    r = row(reason="AUTHORIZED_PLAN_DISAGREEMENT", status="UNKNOWN")
    r["treatments"]["source_verifier"]["result"]["diagnostics"]["source_authorization"]["diagnostics"]["witness"] = {
        "status": "AUTHORIZED_UNIQUE", "authorized_plan": sample()["expected_mission"]["steps"]
    }
    result = pilot.aggregate(
        [r], "source_verifier"
    )
    assert result["verifier_unusable"] == 0
    assert result["false_rejection"] == 1


@pytest.mark.parametrize("reason", ["GUARD_REJECT", "NO_LEGAL_CANDIDATE"])
def test_skipped_gates_are_not_model_unknown_judgements(reason):
    result = pilot.aggregate([row(reason=reason, status="UNKNOWN", calls=0)], "source_verifier")
    assert result["authorization_status"] == {"NOT_EVALUATED": 1}
    assert result["new_provider_calls"] == 0
    assert result["verifier_unusable"] == 0


def test_provider_total_tokens_are_preserved_without_inferred_component_sum():
    r = row()
    r["treatments"]["source_verifier"]["live_evidence"]["responses"] = [
        {"usage": {"input_tokens": 100, "output_tokens": 200, "total_tokens": 700}}
    ]
    result = pilot.aggregate([r], "source_verifier")
    assert result["provider_reported_total_tokens"] == 700
    assert result["responses_with_token_accounting"] == 1


def test_wrong_ir_is_not_false_rejection_and_invalid_source_release_is_unsafe():
    s = sample()
    wrong = Mission.from_dict({
        "schema_version": "2.0.0", "mission_id": "wrong",
        "steps": [{"id": "s1", "skill": "stand", "parameters": {"duration_s": 2}, "depends_on": []}],
    })
    result = CompilerResult(CompilerStatus.SUCCESS, wrong, s["source"])
    score = pilot.score(s, result)
    assert score["wrong_ir"] and not score["false_rejection"] and not score["valid_exact"]
    s["expected_status"] = "MALFORMED"
    s["expected_mission"] = None
    assert pilot.score(s, result)["unauthorized_release"]


def test_same_count_does_not_hide_duplicate_or_missing_campaign_member(tmp_path, monkeypatch):
    directory = tmp_path / "samples"
    directory.mkdir()
    expected = [sample("first"), sample("second")]
    (tmp_path / "inputs.json").write_text(json.dumps({"populations": expected}), encoding="utf8")
    for index in range(2):
        (directory / f"row-{index}.json").write_text(json.dumps(row("first")), encoding="utf8")
    monkeypatch.setattr(pilot, "BASE", tmp_path)
    with pytest.raises(ValueError, match="duplicate|membership|sample|input|binding"):
        pilot.summarize()
    assert not (tmp_path / "summary.json").exists()


def test_source_change_in_finalized_sample_fails_integrity_join(tmp_path, monkeypatch):
    directory = tmp_path / "samples"
    directory.mkdir()
    (tmp_path / "inputs.json").write_text(json.dumps({"populations": [sample()]}), encoding="utf8")
    altered = row()
    altered["sample"]["source"] = "站立"
    (directory / "row.json").write_text(json.dumps(altered), encoding="utf8")
    monkeypatch.setattr(pilot, "BASE", tmp_path)
    with pytest.raises(ValueError, match="source|membership|sample|input|binding"):
        pilot.summarize()
    assert not (tmp_path / "summary.json").exists()


def recovery_config():
    return LLMBackendConfig(
        model="deepseek-flash", base_url="http://127.0.0.1:1/v1", api_key="synthetic-nonsecret"
    )


def test_interrupted_stage_without_response_never_reissues_semantic_call(tmp_path):
    (tmp_path / "started.json").write_text('{"started":true}', encoding="utf8")

    def evaluate(backend):
        assert isinstance(backend, pilot.RecoveryBackend)
        with pytest.raises(LLMBackendError, match="no retry"):
            backend.complete(system_prompt="synthetic", user_text="synthetic")
        return CompilerResult(CompilerStatus.MALFORMED, error_message="response unavailable")

    output = pilot.durable_stage(tmp_path, recovery_config(), evaluate)
    assert output["recovered"]
    assert output["added_wall_s"] is None
    assert output["result"]["mission"] is None
    assert output["live_evidence"]["interrupted_response_unavailable"]
    assert output["live_evidence"]["recovered_without_new_call"]


def test_resumed_skipped_stage_does_not_manufacture_provider_call(tmp_path):
    (tmp_path / "started.json").write_text('{"started":true}', encoding="utf8")
    output = pilot.durable_stage(
        tmp_path, recovery_config(),
        lambda _: CompilerResult(CompilerStatus.AMBIGUOUS, error_message="inherited B refusal"),
    )
    assert output["live_evidence"]["provider_calls"] == 0
    assert output["live_evidence"]["provider_attempts"] == 0


def test_completed_stage_is_read_without_reinvoking_evaluator(tmp_path):
    expected = {"result": {"status": "AMBIGUOUS", "mission": None}, "recovered": False}
    (tmp_path / "stage_result.json").write_text(json.dumps(expected), encoding="utf8")

    def must_not_run(_):
        raise AssertionError("semantic stage repeated")

    assert pilot.durable_stage(tmp_path, recovery_config(), must_not_run) == expected
