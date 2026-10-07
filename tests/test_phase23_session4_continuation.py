"""Synthetic-only continuation checks: no compiler/provider/Guard evaluation."""
import json

import pytest

from scripts.continue_phase23_session4 import ContinuingJournal, classify_unusable, pending_schedule


def test_pending_schedule_never_retries_existing_failed_id():
    rows = [{"sample_id": "a", "transport_failure": True}, {"sample_id": "b"}]
    assert pending_schedule(["a", "b", "c", "d"], rows, ["a", "b"]) == ["c", "d"]


def test_pending_schedule_rejects_unrecorded_already_attempted_id():
    with pytest.raises(ValueError):
        pending_schedule(["a", "b", "c"], [{"sample_id": "a"}], ["a", "b"])
    with pytest.raises(ValueError):
        pending_schedule(["a", "b", "c"], [{"sample_id": "b"}], ["b"])


def test_unusable_response_requires_exact_reviewed_provider_evidence():
    document = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": [{"type": "reasoning"}], "usage": {"input_tokens": 1779, "output_tokens": 4096, "total_tokens": 5875, "output_tokens_details": {"reasoning_tokens": 4096}}}
    events = [{"phase": "end", "transport_status": "SUCCESS", "provider_document": document}]
    calls = [{"terminal_transport_status": "API_ERROR", "sample_id": "synthetic", "campaign": "guard_ood", "call_id": "call-000280", "provider_attempts": 1}]
    result = classify_unusable(events, calls)
    assert result["provider_response_class"] == "UNUSABLE_PROVIDER_RESPONSE"
    assert result["provider_usage"]["total_tokens"] == 5875
    assert result["semantic_response_observed"] is False
    document["output_text"] = "assistant-response"
    assert classify_unusable(events, calls) is None
    del document["output_text"]
    document["usage"]["output_tokens_details"]["reasoning_tokens"] = 4095
    assert classify_unusable(events, calls) is None


def test_continuing_journal_preserves_old_bytes_and_increments_call_ids(tmp_path):
    directory = tmp_path / "raw"
    directory.mkdir()
    attempts = directory / "provider_attempts.jsonl"
    calls = directory / "provider_calls.jsonl"
    attempts.write_text("original-attempt\n")
    calls.write_text("original-call\n")
    journal = ContinuingJournal(directory, {"original": True}, {"continuation": True}, [{"call_id": "call-000001"}, {"call_id": "call-000002"}])
    assert journal.call_count == 2
    journal.start_sample("guard_ood", "never-called", "frozen", "manifest")
    journal.attempt({"phase": "begin", "call_id": "call-000003", "attempt_id": "call-000003-attempt-1"})
    assert attempts.read_text().startswith("original-attempt\n")
    appended = json.loads(attempts.read_text().splitlines()[1])
    assert appended["common_provenance"] == {"original": True}
    assert appended["continuation_provenance"] == {"continuation": True}
    assert calls.read_text() == "original-call\n"


def test_continuing_journal_rejects_noncontiguous_original_calls(tmp_path):
    (tmp_path / "provider_attempts.jsonl").touch()
    (tmp_path / "provider_calls.jsonl").touch()
    with pytest.raises(ValueError):
        ContinuingJournal(tmp_path, {}, {}, [{"call_id": "call-000003"}])
