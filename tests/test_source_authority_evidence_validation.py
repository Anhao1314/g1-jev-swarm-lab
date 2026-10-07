"""Falsification tests for independent evidence accounting and release checks."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_source_authority_evidence.py"
SPEC = importlib.util.spec_from_file_location("source_authority_evidence_validation", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audit)


def write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode())


def sample_row():
    mission = {"schema_version": "2.0.0", "mission_id": "walk", "steps": [
        {"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 4}, "depends_on": []}]}
    sample = {"population": "controlled", "sample_id": "fixture", "source": "前进4米",
        "expected_status": "SUCCESS", "expected_mission": mission, "baseline_recorded": None}
    baseline = {"status": "SUCCESS", "mission": mission, "diagnostics": {}}
    row = {"sample": sample, "baseline_kind": "new_frozen_B_first_response", "gate_order": list(audit.TREATMENTS),
        "B": {"result": baseline, "score": audit.independent_score(sample, baseline)}, "treatments": {}}
    for stage in audit.TREATMENTS:
        witness = {"status": "AUTHORIZED_UNIQUE", "coverage": [
            {"text": sample["source"], "role": "ACTION", "explanation": "explicit complete source"}],
            "dimensions": {name: {"status": "UNIQUE", "explanation": "unique"} for name in audit.DIMENSIONS}}
        if stage == "source_verifier":
            witness["authorized_plan"] = copy.deepcopy(mission["steps"])
        raw = json.dumps(witness, ensure_ascii=False)
        result = {"status": "SUCCESS", "mission": copy.deepcopy(mission), "diagnostics": {
            "release_guard": audit.StructuralGuard().check(sample["source"]).to_dict(),
            "release_validation": audit.MissionValidator().validate(audit.Mission.from_dict(mission)).to_dict(),
            "released_executable": True, "source_authorization": {"status": "AUTHORIZED_UNIQUE",
                "reason_code": "UNIQUE_SOURCE_AUTHORITY", "diagnostics": {"witness": witness,
                    "raw_response": raw, "raw_response_sha256": audit.sha(raw), "source_sha256": audit.sha(sample["source"])}}}}
        row["treatments"][stage] = {"result": result, "score": audit.independent_score(sample, result),
            "live_evidence": {"provider_calls": 1}}
    return sample, row


def test_independent_scores_preserve_positional_ood_dependencies_and_action_multiplicity():
    sample, row = sample_row()
    result = copy.deepcopy(row["B"]["result"])
    result["mission"]["steps"][0]["id"] = "other-id"
    assert audit.independent_score(sample, result)["unauthorized_release"]
    sample["population"] = "ood"
    assert audit.independent_score(sample, result)["valid_exact"]
    result["mission"]["steps"].append({"id": "second", "skill": "stop", "parameters": {}, "depends_on": ["other-id"]})
    assert audit.independent_score(sample, result)["unauthorized_release"]


def test_correct_paired_gate_evidence_passes_independent_release_checks():
    sample, row = sample_row()
    assert audit.row_errors(row, sample, 0) == []


@pytest.mark.parametrize("authority", ["UNKNOWN", "AMBIGUOUS"])
def test_nonunique_gate_cannot_keep_executable_mission(authority):
    sample, row = sample_row()
    result = row["treatments"]["source_verifier"]["result"]
    result["diagnostics"]["source_authorization"]["status"] = authority
    assert any("release predicate differs" in error for error in audit.row_errors(row, sample, 0))
    assert any("nonunique authorization retains" in error for error in audit.row_errors(row, sample, 0))


def test_authorized_candidate_change_detected_even_when_score_is_recomputed():
    sample, row = sample_row()
    output = row["treatments"]["source_verifier"]
    output["result"]["mission"]["steps"][0]["parameters"]["distance_m"] = 6
    output["score"] = audit.independent_score(sample, output["result"])
    assert any("candidate changed from B" in error for error in audit.row_errors(row, sample, 0))


def test_forged_score_and_source_label_edits_are_detected():
    sample, row = sample_row()
    row["B"]["score"]["valid_exact"] = False
    row["sample"] = {**sample, "expected_status": "MALFORMED"}
    errors = audit.row_errors(row, sample, 0)
    assert any("frozen input" in error for error in errors)
    assert any("independent scoring" in error for error in errors)


def test_whole_source_witness_omission_and_missing_unique_witness_detected():
    sample, row = sample_row()
    result = row["treatments"]["ambiguity"]["result"]
    diagnostics = result["diagnostics"]["source_authorization"]["diagnostics"]
    diagnostics["witness"]["coverage"][0]["text"] = "前进"
    diagnostics["raw_response"] = json.dumps(diagnostics["witness"], ensure_ascii=False)
    assert any("full source bytes" in error for error in audit.row_errors(row, sample, 0))
    del diagnostics["witness"]
    assert any("no parsed full-source witness" in error for error in audit.row_errors(row, sample, 0))


def fixture_stage(directory: Path, *, empty: bool = False):
    text = "" if empty else '{"status":"UNKNOWN"}'
    begin = {"index": 1, "request_sha256": "request"}
    document = {"status": "incomplete" if empty else "completed", "output": [],
        "usage": {"input_tokens": 12, "output_tokens": 4096, "total_tokens": 4108}}
    if empty:
        document["incomplete_details"] = {"reason": "max_output_tokens"}
    else:
        document["output"] = [{"type": "message", "content": [{"type": "output_text", "text": text}]}]
    end = {**begin, "status": "SUCCESS", "provider_document": document, "latency_s": 1.0}
    response = {"error_type": "LLMBackendError", "failure_type": "API_ERROR", "attempts": 1} if empty else {
        "text": text, "attempts": 1, "usage": document["usage"]}
    diagnostics = {"raw_response_sha256": audit.sha(text), "raw_response": text} if not empty else {"raw_response": None}
    receipt = {"result": {"status": "MALFORMED", "mission": None,
        "diagnostics": {"source_authorization": {"status": "UNKNOWN", "diagnostics": diagnostics}}},
        "recovered": False, "added_wall_s": 1.0, "live_evidence": {
            "provider_calls": 1, "provider_attempts": 1, "events": [end], "responses": [response]}}
    for name, payload in [("started.json", {"started": True}), ("attempt-01-begin.json", begin),
                          ("attempt-01-end.json", end), ("response.json", response), ("stage_result.json", receipt)]:
        write(directory / name, payload)
    return receipt


def test_first_response_raw_hash_and_receipt_match_are_independently_checked(tmp_path):
    fixture_stage(tmp_path)
    assert audit.stage_audit(tmp_path, expected_hash="request", partial=False)["errors"] == []
    receipt = audit.read(tmp_path / "stage_result.json")
    receipt["result"]["diagnostics"]["source_authorization"]["diagnostics"]["raw_response_sha256"] = "bad"
    write(tmp_path / "stage_result.json", receipt)
    assert any("SHA-256 differs" in error for error in audit.stage_audit(tmp_path, expected_hash="request", partial=False)["errors"])


def test_reasoning_only_budget_response_tokens_count_despite_backend_error(tmp_path):
    fixture_stage(tmp_path, empty=True)
    result = audit.stage_audit(tmp_path, expected_hash="request", partial=False)
    assert result["errors"] == []
    assert result["provider_document_tokens"] == 4108
    assert result["backend_response_tokens"] == 0
    assert result["empty_assistant_documents"] == result["output_budget_documents"] == 1


def test_reissue_after_first_provider_success_is_detected(tmp_path):
    fixture_stage(tmp_path)
    write(tmp_path / "attempt-02-begin.json", {"index": 2, "request_sha256": "request"})
    errors = audit.stage_audit(tmp_path, expected_hash="request", partial=False)["errors"]
    assert any("continued after first semantic response" in error for error in errors)


def test_changed_request_hash_and_mutated_stage_ledger_are_detected(tmp_path):
    fixture_stage(tmp_path)
    errors = audit.stage_audit(tmp_path, expected_hash="different", partial=False)["errors"]
    assert any("exact source/prompt/candidate" in error for error in errors)
    event = audit.read(tmp_path / "attempt-01-end.json")
    event["request_sha256"] = "altered"
    write(tmp_path / "attempt-01-end.json", event)
    errors = audit.stage_audit(tmp_path, expected_hash="request", partial=False)["errors"]
    assert any("matching request begin" in error for error in errors)
    assert any("receipt differs" in error for error in errors)


def test_partial_active_call_is_explicitly_incomplete_without_final_claim(tmp_path):
    write(tmp_path / "started.json", {"started": True})
    write(tmp_path / "attempt-01-begin.json", {"index": 1, "request_sha256": "request"})
    partial = audit.stage_audit(tmp_path, expected_hash="request", partial=True)
    assert partial["errors"] == []
    assert not partial["complete"]
    assert partial["unmatched_transport_attempts"] == 1
    final = audit.stage_audit(tmp_path, expected_hash="request", partial=False)
    assert "stage acquisition is incomplete" in final["errors"]


def test_bounded_control_preserves_byte_link_score_candidate_and_full_source(tmp_path):
    sample, original = sample_row()
    identity = audit.key(sample)
    base = tmp_path / audit.EXPERIMENT
    baseline_file = base / "samples" / f"{identity}.json"
    write(baseline_file, original)
    result = copy.deepcopy(original["treatments"]["source_verifier"]["result"])
    normalized = audit.normalize_text(sample["source"])
    result["diagnostics"]["source_authorization"]["diagnostics"] = {
        "source_witness": {"text": sample["source"], "sha256": audit.sha(sample["source"]), "characters": len(sample["source"])},
        "normalized_source_witness": {"text": normalized, "sha256": audit.sha(normalized), "characters": len(normalized)},
        "authorized_plan": audit.mission_shape(original["B"]["result"]["mission"]),
        "parse_witness": {"full_consumption": True, "start": 0, "end": len(normalized),
            "tokens": [{"start": 0, "end": len(normalized), "text": normalized}]},
        "quantity_normalization_witness": [{"contiguous": True}],
    }
    record = {"population": sample["population"], "sample_id": sample["sample_id"], "result": result,
        "baseline_evidence_sha256": audit.sha(baseline_file.read_bytes()), "score": audit.independent_score(sample, result),
        "live_evidence": {"provider_calls": 0, "provider_attempts": 0, "events": [], "responses": []}}
    document = {"evidence_role": "post_hoc_exploratory_bounded_control", "records": [record]}
    write(base / "bounded_control.json", document)
    checked = audit.bounded_control_audit(tmp_path, [sample])
    assert checked["errors"] == ["bounded control does not contain exact unique 528 membership"]
    assert checked["independent_scores"]["valid_exact"] == 1
    record["baseline_evidence_sha256"] = "altered"
    record["result"]["mission"]["steps"][0]["parameters"]["distance_m"] = 6
    record["score"] = audit.independent_score(sample, result)
    write(base / "bounded_control.json", document)
    errors = audit.bounded_control_audit(tmp_path, [sample])["errors"]
    assert any("byte-hash link differs" in error for error in errors)
    assert any("candidate changed from B" in error for error in errors)
