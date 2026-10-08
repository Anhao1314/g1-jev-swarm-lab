"""Independent auditor tests use synthetic evidence exclusively."""
from __future__ import annotations

import copy

from scripts.audit_phase23_session4_evidence import audit_records, text_sha


def fixture():
    common = {"protocol_sha256": "synthetic", "dataset_sha256": {"final_language": "synthetic-data"}}
    context = {"campaign": "final_compiler", "sample_id": "synthetic-1", "dataset_sha256": "synthetic-data", "common_provenance": common, "campaign_manifest_sha256": "synthetic-manifest"}
    provider = {"model": "synthetic", "temperature": 0.0, "max_output_tokens": 4096, "max_network_retries": 2, "retry_backoff_s": 0.5}
    request = {**provider, "stream": False}
    payload = {"model": "synthetic", "input": [{"role": "system", "content": "synthetic-prompt"}, {"role": "user", "content": "synthetic-text"}], "temperature": 0.0, "max_output_tokens": 4096, "stream": False}
    usage = {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}
    diagnostics = {"raw_response": "synthetic-response", "raw_response_sha256": text_sha("synthetic-response"), "model": "synthetic", "usage": usage, "request_parameters": request, "attempts": 1, "latency_s": 0.25, "response_id": "synthetic-response-id"}
    attempt = {**context, "call_id": "synthetic-call", "attempt_id": "synthetic-call-1", "attempt_index": 1}
    events = [{**attempt, "phase": "begin", "request_payload": payload}, {**attempt, "phase": "end", "transport_status": "SUCCESS", "retry_scheduled": False, "retry_reason": None, "latency_s": 0.3, "frozen_latency_s": 0.25, "provider_document": {"id": "synthetic-response-id", "model": "synthetic", "output_text": "synthetic-response", "usage": usage}}]
    call = {**context, "call_id": "synthetic-call", "attempt_ids": ["synthetic-call-1"], "provider_attempts": 1, "retry_reason": [], "terminal_transport_status": "SUCCESS", "transport_failure": False, "response": {"text": "synthetic-response", "model": "synthetic", "latency_s": 0.25, "attempts": 1, "request_parameters": request, "usage": usage, "response_id": "synthetic-response-id"}}
    row = {**context, "text": "synthetic-text", "actual_status": "MALFORMED", "compiled_mission": None, "result": {"status": "MALFORMED", "mission": None, "diagnostics": diagnostics}, "diagnostics": diagnostics, "provider_invoked": True, "provider_attempts": 1, "attempt_ids": ["synthetic-call-1"], "retry_reason": [], "terminal_transport_status": "SUCCESS", "transport_failure": False, "provider_tokens": 3, "latency_s": 0.25}
    return {"expected": {("final_compiler", "synthetic-1"): {"text": "synthetic-text", "dataset_sha256": "synthetic-data"}}, "rows": [row], "events": events, "calls": [call], "common": common, "manifest_sha": "synthetic-manifest", "prompt": "synthetic-prompt", "provider": provider}


def test_independent_audit_accepts_single_semantic_failure_without_retry():
    result = audit_records(**fixture())
    assert result["status"] == "PASS"
    assert result["reported_provider_tokens"] == 3


def test_independent_audit_detects_unrecorded_attempt_and_payload_tuning():
    data = fixture()
    data["events"][0]["request_payload"]["temperature"] = 0.5
    data["calls"][0]["attempt_ids"] = []
    result = audit_records(**data)
    assert result["status"] == "FAIL"
    assert any(error.startswith("request_payload_drift") for error in result["errors"])
    assert any(error.startswith("attempt_ids_mismatch") for error in result["errors"])


def test_independent_audit_detects_primary_metadata_hash_drift_and_pilot():
    data = fixture()
    data["rows"][0]["campaign"] = "pilot"
    data["rows"][0]["dataset_sha256"] = "other"
    result = audit_records(**data)
    assert result["status"] == "FAIL"
    assert result["pilot_mixed"] is True


def test_independent_audit_detects_duplicate_semantic_invocation():
    data = fixture()
    data["calls"].append(copy.deepcopy(data["calls"][0]))
    result = audit_records(**data)
    assert result["status"] == "FAIL"
    assert "duplicate_call_id" in result["errors"]
    assert any(error.startswith("sample_call_count") for error in result["errors"])


def test_independent_audit_detects_token_restatement():
    data = fixture()
    data["rows"][0]["provider_tokens"] = 999
    result = audit_records(**data)
    assert result["status"] == "FAIL"
    assert any(error.startswith("row_token_mismatch") for error in result["errors"])


def test_independent_audit_detects_successful_attempt_followed_by_retry():
    data = fixture()
    second = copy.deepcopy(data["events"])
    for event in second:
        event["attempt_id"] = "synthetic-call-2"
        event["attempt_index"] = 2
    data["events"].extend(second)
    result = audit_records(**data)
    assert result["status"] == "FAIL"
    assert any(error.startswith("semantic_or_terminal_failure_retried") for error in result["errors"])


def test_independent_audit_accepts_recovered_frozen_transport_retry():
    data = fixture()
    begin_one = data["events"][0]
    end_two = data["events"][1]
    begin_two = copy.deepcopy(begin_one)
    for event in (begin_two, end_two):
        event.update(attempt_id="synthetic-call-2", attempt_index=2)
    end_one = {key: value for key, value in begin_one.items() if key != "request_payload"}
    end_one.update(phase="end", transport_status="TIMEOUT", retry_scheduled=True, retry_reason="TIMEOUT", error_context={}, latency_s=60.0)
    backoff = {key: value for key, value in end_one.items() if key not in {"transport_status", "retry_scheduled", "retry_reason", "error_context", "latency_s"}}
    backoff.update(phase="backoff", delay_s=0.5, actual_delay_s=0.51)
    data["events"] = [begin_one, end_one, backoff, begin_two, end_two]
    for record in (data["rows"][0], data["calls"][0]):
        record.update(provider_attempts=2, attempt_ids=["synthetic-call-1", "synthetic-call-2"], retry_reason=["TIMEOUT"])
    data["rows"][0]["diagnostics"]["attempts"] = 2
    data["calls"][0]["response"]["attempts"] = 2
    result = audit_records(**data)
    assert result["status"] == "PASS"
    assert result["attempt_begin_count"] == 2
    assert result["reported_provider_tokens"] == 3


def test_independent_audit_accounts_for_reasoning_only_unusable_response():
    data = fixture()
    diagnostics = {"attempts": 1, "failure_type": "API_ERROR", "backend_error": {"retryable": False}}
    row, call = data["rows"][0], data["calls"][0]
    row.update(diagnostics=diagnostics, result={"status": "MALFORMED", "mission": None, "diagnostics": diagnostics}, provider_tokens=None, latency_s=None, terminal_transport_status="API_ERROR", transport_failure=True)
    call.update(terminal_transport_status="API_ERROR", transport_failure=True)
    del call["response"]
    data["events"][1]["provider_document"] = {"model": "synthetic", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": [{"type": "reasoning"}], "usage": {"input_tokens": 243, "output_tokens": 4096, "total_tokens": 5875, "output_tokens_details": {"reasoning_tokens": 4096}}}
    result = audit_records(**data)
    assert result["status"] == "PASS"
    assert result["unusable_response_count"] == 1
    assert result["reported_provider_tokens"] == 5875
    assert result["response_evidence_complete"] is False
    assert row["provider_tokens"] is None


def test_independent_audit_rejects_arbitrary_http_success_api_error_exception():
    data = fixture()
    diagnostics = {"attempts": 1, "failure_type": "API_ERROR", "backend_error": {"retryable": False}}
    data["rows"][0].update(diagnostics=diagnostics, result={"status": "MALFORMED", "mission": None, "diagnostics": diagnostics}, terminal_transport_status="API_ERROR", transport_failure=True)
    data["calls"][0].update(terminal_transport_status="API_ERROR", transport_failure=True)
    del data["calls"][0]["response"]
    result = audit_records(**data)
    assert result["status"] == "FAIL"
    assert any(error.startswith("unreviewed_unusable_provider_response") for error in result["errors"])
