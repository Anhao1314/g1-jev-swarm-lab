"""Offline V2 accounting, request blindness and audit-integrity falsification."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import analyze_authority_certificate_v2 as analysis
from scripts import package_authority_certificate_v2 as package_v2
from scripts import package_source_authority as package_v1
from scripts import run_authority_certificate_v2_pilot as run
from g1swarm.language.errors import CompilerStatus
from g1swarm.language.result import CompilerResult
from g1swarm.mission.ir import Mission


def _mission() -> dict:
    return {"schema_version": "2.0.0", "mission_id": "unchanged-B",
            "steps": [{"id": "s1", "skill": "stop", "parameters": {}, "depends_on": []}]}


def _certificate() -> dict:
    return {"status": "AUTHORIZED_UNIQUE", "checks": ["U"] * 7,
            "plan": [["stop"]], "issues": []}


def _sample(sid="synthetic", population="controlled", *, valid=True) -> dict:
    return {"sample_id": sid, "population": population,
            "split": "primary_gold" if population == "ood" else "already_seen_regression",
            "source": "停止", "family": "synthetic",
            "expected_status": "SUCCESS" if valid else "MALFORMED",
            "expected_mission": _mission() if valid else None}


def _wire(*, tokens=200, exhausted=False) -> dict:
    document = {"status": "incomplete" if exhausted else "completed",
                "usage": {"total_tokens": tokens},
                "output": [] if exhausted else [{"content": [{"type": "output_text", "text": "saved"}]}]}
    if exhausted:
        document["incomplete_details"] = {"reason": "max_output_tokens"}
    return {"provider_calls": 1, "provider_attempts": 1,
            "events": [{"status": "SUCCESS", "provider_document": document}],
            "responses": [{"usage": {"total_tokens": tokens}}]}


def _output(sample: dict, *, authority="AUTHORIZED_UNIQUE", certificate=None,
            certificate_status="AUTHORIZED_UNIQUE", usable=True, reason="UNIQUE_SOURCE_AUTHORITY") -> dict:
    certificate = _certificate() if certificate is None else certificate
    released = authority == "AUTHORIZED_UNIQUE"
    result = CompilerResult(CompilerStatus.SUCCESS if released else CompilerStatus.MALFORMED,
                            Mission.from_dict(_mission()) if released else None,
                            sample["source"], diagnostics={"source_authorization": {
                                "status": authority, "reason_code": reason,
                                "diagnostics": {"certificate_usable": usable,
                                                "certificate_status": certificate_status,
                                                "certificate": certificate,
                                                "raw_response": json.dumps(certificate),
                                                "plan_matches_candidate": released}}})
    return {"result": result.to_dict(), "score": run.old.score(sample, result),
            "added_wall_s": 0.5, "live_evidence": _wire()}


def _row(sample: dict, output: dict) -> dict:
    baseline = _output(sample)
    return {"prior": {"sample": sample, "B": baseline,
                      "treatments": {"source_verifier": copy.deepcopy(output)}},
            "v2": output, "input_binding": {}}


def _json_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf8")


def _fixture(tmp_path: Path, monkeypatch) -> dict:
    """One completely synthetic auditable source, candidate and first response."""
    root = tmp_path
    base = root / "v2"
    prompt = "synthetic immutable prompt"
    (root / "prompts").mkdir()
    (root / "prompts/authority_certificate_v2.txt").write_text(prompt, encoding="utf8")
    sample = _sample()
    prior = _row(sample, _output(sample))["prior"]
    prior_path = root / "v1/synthetic.json"
    _json_write(prior_path, prior)
    binding = {"population": sample["population"], "sample_id": sample["sample_id"],
               "v1_sample_path": "v1/synthetic.json",
               "v1_sample_sha256": run.sha(prior_path.read_bytes()),
               "source_sha256": run.sha(sample["source"].encode("utf8"))}
    config = {"model": "deepseek-flash", "temperature": 0.0, "max_output_tokens": 4096}
    _json_write(base / "inputs.json", {"rows": [binding]})
    _json_write(base / "preflight.json", {"pass": True, "acquisition_hashes": {}, "provider_config": config})
    output = _output(sample)
    raw = output["result"]["diagnostics"]["source_authorization"]["diagnostics"]["raw_response"]
    detail = output["result"]["diagnostics"]["source_authorization"]["diagnostics"]
    detail.update({"source_sha256": binding["source_sha256"], "request_input_fields": ["source"],
                   "raw_response_sha256": run.sha(raw.encode("utf8")),
                   "model": config["model"], "provider_status": "completed", "finish_reason": "completed"})
    user_text = json.dumps({"source": sample["source"]}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    payload = {"model": config["model"], "input": [{"role": "system", "content": prompt},
                {"role": "user", "content": user_text}], "temperature": 0.0,
               "max_output_tokens": 4096, "stream": False}
    request_sha = run.sha(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf8"))
    begin = {"index": 1, "request_sha256": request_sha}
    end = {**begin, "status": "SUCCESS", "provider_document": {
        "status": "completed", "usage": {"total_tokens": 200},
        "output": [{"content": [{"type": "output_text", "text": raw}]}]}}
    response = {"text": raw, "model": "deepseek-flash", "latency_s": 0.15, "attempts": 1,
                "request_parameters": config, "usage": {"total_tokens": 200},
                "response_id": "first-response", "provider_status": "completed", "finish_reason": "completed"}
    output["live_evidence"] = {"provider_calls": 1, "provider_attempts": 1,
                               "events": [end], "responses": [response]}
    stage_dir = base / "acquisition/controlled--synthetic"
    _json_write(stage_dir / "attempt-01-begin.json", begin)
    _json_write(stage_dir / "attempt-01-end.json", end)
    _json_write(stage_dir / "response.json", response)

    def persist():
        _json_write(stage_dir / "stage_result.json", {k: v for k, v in output.items() if k != "score"})
        _json_write(base / "samples/controlled--synthetic.json", {"input_binding": binding, "v2": output})

    persist()
    monkeypatch.setattr(analysis, "ROOT", root)
    monkeypatch.setattr(analysis, "BASE", base)
    monkeypatch.setattr(analysis, "preserved_anchor", lambda _: None)
    monkeypatch.setattr(run, "binding", lambda: {})
    monkeypatch.setattr(run.old, "resolve_provider", lambda: (_ for _ in ()).throw(AssertionError("credential access forbidden")))
    return {"root": root, "base": base, "output": output, "binding": binding,
            "stage_dir": stage_dir, "persist": persist, "request_sha": request_sha}


def test_offline_audit_accepts_complete_candidate_blind_first_response(tmp_path, monkeypatch) -> None:
    _fixture(tmp_path, monkeypatch)
    rows, receipt = analysis.validate()
    assert len(rows) == 1
    assert receipt["candidate_blind_requests_verified"] == 1
    assert receipt["runtime_calls"] == 0


def test_candidate_leak_changes_request_sha_and_is_rejected(tmp_path, monkeypatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    path = fixture["stage_dir"] / "attempt-01-begin.json"
    begin = analysis.read(path)
    begin["request_sha256"] = run.sha(b"request containing candidate or label")
    _json_write(path, begin)
    with pytest.raises(ValueError, match="candidate leaked|request drift"):
        analysis.validate()


@pytest.mark.parametrize("change", ["missing", "duplicate", "unexpected"])
def test_membership_integrity_is_not_just_same_record_count(tmp_path, monkeypatch, change) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    sample_path = fixture["base"] / "samples/controlled--synthetic.json"
    if change == "missing":
        sample_path.unlink()
    elif change == "duplicate":
        _json_write(fixture["base"] / "samples/duplicate.json", analysis.read(sample_path))
    else:
        row = analysis.read(sample_path)
        row["input_binding"]["sample_id"] = "unregistered"
        _json_write(sample_path, row)
    with pytest.raises(ValueError, match="campaign|membership|binding|members"):
        analysis.validate()


def test_certificate_host_equality_is_recomputed_not_trusted(tmp_path, monkeypatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    detail = analysis.detail(fixture["output"])
    certificate = _certificate()
    certificate["plan"] = [["stand", 2]]
    detail["certificate"] = certificate
    detail["raw_response"] = json.dumps(certificate)
    detail["raw_response_sha256"] = run.sha(detail["raw_response"].encode("utf8"))
    detail["plan_matches_candidate"] = True
    # Keep all first-response forms consistent so the equality check itself
    # must reject the different legal certificate plan and unchanged B stop.
    response = fixture["output"]["live_evidence"]["responses"][0]
    response["text"] = detail["raw_response"]
    _json_write(fixture["stage_dir"] / "response.json", response)
    event = fixture["output"]["live_evidence"]["events"][0]
    event["provider_document"]["output"][0]["content"][0]["text"] = detail["raw_response"]
    _json_write(fixture["stage_dir"] / "attempt-01-end.json", event)
    fixture["persist"]()
    with pytest.raises(ValueError, match="certificate|candidate|plan|authority"):
        analysis.validate()


def test_missing_first_response_receipt_cannot_be_hidden_by_embedded_copy(tmp_path, monkeypatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    (fixture["stage_dir"] / "response.json").unlink()
    with pytest.raises(ValueError, match="response|receipt|ledger"):
        analysis.validate()


def test_parsed_certificate_must_come_from_first_saved_response(tmp_path, monkeypatch) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    response = fixture["output"]["live_evidence"]["responses"][0]
    response["text"] = "a different first assistant response"
    _json_write(fixture["stage_dir"] / "response.json", response)
    fixture["persist"]()
    with pytest.raises(ValueError, match="response|certificate|first"):
        analysis.validate()


def _run_analysis(rows, monkeypatch) -> dict:
    captured = {}
    monkeypatch.setattr(analysis, "validate", lambda: (rows, {"status": "PASS"}))
    monkeypatch.setattr(analysis, "read", lambda _: {"bounded_control_sha256": "unchanged"})
    monkeypatch.setattr(analysis, "write", lambda path, value: captured.__setitem__(path.name, value))
    analysis.analyze()
    return captured


@pytest.mark.parametrize("failure", ["generic_unknown", "quantity_unknown", "unique_host_mismatch", "provider_failure"])
def test_dependent_failure_withholding_is_not_semantic_safety_credit(monkeypatch, failure) -> None:
    rows = []
    for index in range(7):
        population = "ood" if index < 5 else "phase22b" if index == 5 else "controlled"
        sample = _sample(f"synthetic-unsafe-{index}", population, valid=False)
        cert = {"status": "UNKNOWN", "checks": ["U"] * 6 + ["?"], "plan": None,
                "issues": [{"relation": "unit", "reason": "MISSING"}]}
        if index == 0:
            if failure == "generic_unknown":
                cert["issues"] = [{"relation": "unknown", "reason": "UNKNOWN"}]
            elif failure == "quantity_unknown":
                cert["issues"] = [{"relation": "quantity", "reason": "UNKNOWN"}]
            elif failure == "unique_host_mismatch":
                cert = _certificate()
        output = _output(sample, authority="UNKNOWN", certificate=cert,
                         certificate_status=cert["status"],
                         usable=not (index == 0 and failure == "provider_failure"),
                         reason="AUTHORIZED_PLAN_DISAGREEMENT" if failure == "unique_host_mismatch" and index == 0 else "SEMANTIC_UNKNOWN")
        rows.append(_row(sample, output))
    captured = _run_analysis(rows, monkeypatch)
    unsafe = captured["analysis.json"]["unsafe"]
    assert len(unsafe) == 7
    assert not unsafe[0]["specific_semantic_rejection_candidate"]
    assert not captured["summary.json"]["operational_checks"]["all_unsafe_specific_usable_rejection"]
    assert captured["summary.json"]["cohorts"]["all"]["v2"]["unauthorized_release"] == 0
    assert captured["summary.json"]["manual_semantic_review_required"] is True
    assert captured["summary.json"]["manual_semantic_review_complete"] is False


def test_reasoning_only_exhausted_output_tokens_are_counted_once() -> None:
    sample = _sample()
    output = _output(sample, authority="UNKNOWN", usable=False, reason="BACKEND_FAILURE")
    output["live_evidence"] = _wire(tokens=4500, exhausted=True)
    output["live_evidence"]["responses"] = [{"failure_type": "API_ERROR"}]
    result = analysis.metrics([_row(sample, output)], "v2")
    assert result["reported_tokens"] == 4500
    assert result["mean_reported_tokens_per_call"] == 4500
    assert result["output_exhaustion"] == 1
    assert result["empty_assistant"] == 1
    assert result["usable"] == 0


def test_transport_failure_without_usage_is_explicit_unavailable_cost() -> None:
    sample = _sample()
    output = _output(sample, authority="UNKNOWN", usable=False, reason="BACKEND_FAILURE")
    output["live_evidence"] = {"provider_calls": 1, "provider_attempts": 1,
                               "events": [{"status": "TIMEOUT"}], "responses": []}
    result = analysis.metrics([_row(sample, output)], "v2")
    assert result["failed_attempts_unavailable_usage"] == 1
    assert result["usable"] == 0


def test_new_namespace_does_not_enter_old_discovery_or_acquisition_binding() -> None:
    root = Path(__file__).resolve().parents[1]
    v1_paths = set(package_v1.default_paths(root))
    v2_paths = set(package_v2.default_paths(root))
    names = {"src/g1swarm/authority_certificate_v2.py", "prompts/authority_certificate_v2.txt",
             "tests/test_authority_certificate_v2.py", "tests/test_authority_certificate_v2_pilot.py",
             "scripts/run_authority_certificate_v2_pilot.py", "scripts/analyze_authority_certificate_v2.py"}
    assert not names & v1_paths
    assert names <= v2_paths
    prior_binding = run.old.read(run.V1 / "preflight.json")["acquisition_hashes"]
    assert run.old.acquisition_binding() == prior_binding
    assert not names & set(prior_binding)


def test_current_pilot_metrics_recompute_offline_without_credentials(monkeypatch) -> None:
    monkeypatch.setattr(run.old, "resolve_provider", lambda: (_ for _ in ()).throw(AssertionError("no credential access")))
    rows, receipt = analysis.validate()
    measured = analysis.metrics(rows, "v2")
    saved = analysis.read(run.BASE / "summary.json")["cohorts"]["all"]["v2"]
    assert measured == saved
    assert receipt["completed"] == 528
    assert measured["called"] == 291
    assert measured["usable"] == 275
    assert measured["valid_exact"] == 273
    assert len(measured["incremental_false_rejection_ids"]) == 11
    assert measured["unauthorized_release"] == 0
