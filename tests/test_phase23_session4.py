"""Synthetic-only Session 4 collection checks; never evaluate frozen OOD texts."""
from __future__ import annotations

import json

import pytest

from scripts import run_phase23_session4 as campaign
from g1swarm.language.errors import CompilerStatus
from g1swarm.language.result import CompilerResult
from g1swarm.llm.backend import DeepSeekResponsesBackend, LLMBackendConfig, LLMBackendError
from g1swarm.mission.ir import Mission


def test_observer_keeps_frozen_retry_and_records_every_attempt(tmp_path, monkeypatch):
    config = LLMBackendConfig(model="deepseek-flash", base_url="https://example.invalid", api_key="synthetic-test-only", retry_backoff_s=0.0)
    journal = campaign.AttemptJournal(tmp_path / "raw", {"protocol_sha256": "test"})
    journal.start_sample("synthetic", "test-1", "test-dataset")
    attempts = []

    def post(self, payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise LLMBackendError("API_ERROR", "synthetic HTTP 429", retryable=True, context={"http_status": 429})
        return {"id": "synthetic", "model": "deepseek-flash", "output_text": "synthetic-response", "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}, 0.01

    monkeypatch.setattr(DeepSeekResponsesBackend, "_post", post)
    backend = campaign.ObservedFrozenBackend(config, journal)
    response = backend.complete(system_prompt="synthetic-prompt", user_text="synthetic-text")
    assert response.attempts == 2
    assert attempts[0] == attempts[1]
    events = [json.loads(line) for line in journal.attempt_path.read_text().splitlines()]
    assert [event["phase"] for event in events] == ["begin", "end", "backoff", "begin", "end"]
    assert events[1]["retry_scheduled"] is True
    assert journal.sample_summary()["retry_reason"] == ["HTTP_429"]
    assert journal.sample_summary()["provider_attempts"] == 2
    assert journal.sample_summary()["terminal_transport_status"] == "SUCCESS"
    assert "synthetic-test-only" not in journal.attempt_path.read_text()


def test_terminal_failure_has_three_attempts_and_remains_transport(tmp_path, monkeypatch):
    config = LLMBackendConfig(model="deepseek-flash", base_url="https://example.invalid", api_key="synthetic-test-only", retry_backoff_s=0.0)
    journal = campaign.AttemptJournal(tmp_path / "raw", {})
    journal.start_sample("synthetic", "test-2", "test-dataset")

    def fail(self, payload):
        raise LLMBackendError("TIMEOUT", "synthetic timeout", retryable=True)

    monkeypatch.setattr(DeepSeekResponsesBackend, "_post", fail)
    with pytest.raises(LLMBackendError) as caught:
        campaign.ObservedFrozenBackend(config, journal).complete(system_prompt="synthetic", user_text="synthetic")
    assert caught.value.attempts == 3
    summary = journal.sample_summary()
    assert summary["provider_attempts"] == 3
    assert summary["attempts_complete"] is True
    assert summary["transport_failure"] is True
    assert summary["terminal_transport_status"] == "TIMEOUT"
    assert len(summary["retry_reason"]) == 2


def test_ood_position_comparison_preserves_edges_and_repeated_actions():
    expected = {"schema_version": "2.0.0", "mission_id": "expected", "steps": [{"id": "s1", "skill": "stop", "parameters": {}, "depends_on": []}, {"id": "s2", "skill": "stop", "parameters": {}, "depends_on": ["s1"]}]}
    renamed = {"schema_version": "2.0.0", "mission_id": "renamed", "steps": [{"id": "a", "skill": "stop", "parameters": {}, "depends_on": []}, {"id": "b", "skill": "stop", "parameters": {}, "depends_on": ["a"]}]}
    assert campaign.position_ir(expected) == campaign.position_ir(renamed)
    renamed["steps"][1]["depends_on"] = []
    assert campaign.position_ir(expected) != campaign.position_ir(renamed)
    assert campaign.position_ir(expected) != campaign.position_ir({**expected, "steps": expected["steps"][:1]})


def test_ood_unsafe_and_sensitivity_metadata_remain_separate():
    sample = {"candidate_id": "synthetic-sensitivity", "split": "disputed_sensitivity", "expected_status": "MALFORMED", "confidence": "low", "utterance": "synthetic-input"}
    result = CompilerResult(status=CompilerStatus.SUCCESS, mission=Mission.from_dict(campaign.SMOKE_MISSION))
    row = campaign.ood_record(sample, result, {"guard_status": "PASS", "guard_reason_code": None, "guard_rejects": False})
    assert row["split"] == "disputed_sensitivity"
    assert row["unsafe_acceptance"] is True
    assert row["silent_repair"] is True
    assert row["valid_exact_ir"] is False


def test_missing_env_preflight_never_constructs_compiler(tmp_path, monkeypatch):
    monkeypatch.setattr(campaign, "ROOT", tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/verify_phase23_session4.py").write_text("synthetic verifier")
    monkeypatch.setattr(campaign, "verify", lambda: {"status": "PASS", "issues": [], "code_commit": "synthetic"})
    monkeypatch.setattr(campaign.runner, "load_protocol", lambda: {"provider": {"base_url_env": "SYNTHETIC_SESSION4_BASE", "api_key_envs": ["SYNTHETIC_SESSION4_KEY"]}})
    monkeypatch.delenv("SYNTHETIC_SESSION4_BASE", raising=False)
    monkeypatch.delenv("SYNTHETIC_SESSION4_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setattr(campaign, "make_observed_treatment", lambda *args: pytest.fail("missing config must never instantiate tested system"))
    receipt = campaign.preflight(tmp_path / "preflight")
    assert receipt["status"] == "BLOCKED_PROVIDER_CONFIGURATION"
    assert receipt["integrity_status"] == "PASS"
    assert receipt["provider_calls"] == 0
    assert receipt["final_inputs_evaluated"] == receipt["ood_inputs_evaluated"] == 0


def test_evidence_write_is_exclusive(tmp_path):
    target = tmp_path / "immutable.json"
    campaign.write_json(target, {"value": 1})
    with pytest.raises(FileExistsError):
        campaign.write_json(target, {"value": 2})
    assert json.loads(target.read_text()) == {"value": 1}


def test_endpoint_identity_excludes_credentials_and_query():
    value = campaign.endpoint_identity("https://user:secret@example.invalid/v1?token=secret#fragment")
    assert value["endpoint_identity"] == "https://example.invalid/v1"
    assert "secret" not in json.dumps(value)


def test_observer_redacts_only_persisted_credential_echo_and_never_repairs_response(tmp_path, monkeypatch):
    credential = "synthetic-secret-credential"
    config = LLMBackendConfig(model="deepseek-flash", base_url="https://example.invalid", api_key=credential)
    journal = campaign.AttemptJournal(tmp_path / "raw", {})
    journal.start_sample("synthetic", "test-echo", "test-dataset")

    def post(self, payload):
        return {"model": "deepseek-flash", "output_text": "malformed semantic response " + credential}, 0.01

    monkeypatch.setattr(DeepSeekResponsesBackend, "_post", post)
    response = campaign.ObservedFrozenBackend(config, journal).complete(system_prompt="synthetic", user_text="synthetic")
    assert response.text == "malformed semantic response " + credential
    assert response.attempts == 1
    assert credential not in journal.attempt_path.read_text()
    assert credential not in journal.call_path.read_text()
    assert "<REDACTED_PROVIDER_CREDENTIAL>" in journal.call_path.read_text()
    assert journal.safe({"error_message": credential, "values": [credential]}) == {"error_message": "<REDACTED_PROVIDER_CREDENTIAL>", "values": ["<REDACTED_PROVIDER_CREDENTIAL>"]}
