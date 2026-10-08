"""Independent offline evidence audit for Session 4; no system evaluation.

Checks immutable schedules, provider payloads and every attempt lifecycle against
the frozen policy. It never constructs a compiler, Guard, backend, or runtime.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

import yaml

try:
    from scripts.verify_phase23_session4 import verify
except ModuleNotFoundError:
    from verify_phase23_session4 import verify

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "experiments/phase2/long_horizon_language_001"


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def output_text(document: Mapping[str, Any]) -> str:
    pieces = []
    for item in document.get("output", []):
        for part in item.get("content", []):
            if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                pieces.append(part["text"])
    if pieces:
        return "".join(pieces).strip()
    if isinstance(document.get("output_text"), str) and document["output_text"].strip():
        return document["output_text"].strip()
    choices = document.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content")
        if isinstance(content, str):
            return content.strip()
    return ""


def normalized_usage(document: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = document.get("usage")
    if not isinstance(raw, Mapping):
        return None
    usage = {"input_tokens": raw.get("input_tokens", raw.get("prompt_tokens")), "output_tokens": raw.get("output_tokens", raw.get("completion_tokens")), "total_tokens": raw.get("total_tokens")}
    return usage if any(value is not None for value in usage.values()) else None


def normalized_mission(document: Mapping[str, Any] | None) -> Any:
    if document is None:
        return None
    return {"schema_version": document["schema_version"], "mission_id": document["mission_id"], "steps": [{"id": step["id"], "skill": step["skill"], "parameters": step.get("parameters", {}), "depends_on": step.get("depends_on", [])} for step in document["steps"]]}


def audit_records(
    *, expected: Mapping[tuple[str, str], Mapping[str, Any]], rows: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]], calls: Sequence[Mapping[str, Any]],
    common: Mapping[str, Any], manifest_sha: str | None, prompt: str, provider: Mapping[str, Any],
) -> dict[str, Any]:
    """Pure journal audit, usable with synthetic evidence in isolated tests."""
    errors: list[str] = []
    checks = 0

    def check(condition, description):
        nonlocal checks
        checks += 1
        if not condition:
            errors.append(description)

    def key(value):
        return value.get("campaign"), value.get("sample_id")

    observed = Counter(key(row) for row in rows)
    check(set(observed) == set(expected), "sample_schedule_coverage")
    for sample_key, count in observed.items():
        check(count == 1, f"duplicate_sample:{sample_key}")
    by_sample: dict[Any, list[Any]] = defaultdict(list)
    by_call_events: dict[Any, list[Any]] = defaultdict(list)
    by_call: dict[Any, list[Any]] = defaultdict(list)
    for call in calls:
        by_sample[key(call)].append(call)
        by_call[call.get("call_id")].append(call)
    for event in events:
        by_call_events[event.get("call_id")].append(event)
    check(set(by_call_events) == set(by_call), "call_attempt_schedule_coverage")
    check(all(len(group) == 1 for group in by_call.values()), "duplicate_call_id")
    for value in list(rows) + list(events) + list(calls):
        sample_key = key(value)
        check(sample_key in expected, f"unexpected_sample_context:{sample_key}")
        check(value.get("common_provenance") == common, f"common_provenance_drift:{sample_key}")
        check(value.get("campaign_manifest_sha256") == manifest_sha, f"manifest_hash_drift:{sample_key}")
        if sample_key in expected:
            check(value.get("dataset_sha256") == expected[sample_key]["dataset_sha256"], f"dataset_hash_drift:{sample_key}")
    successful_tokens = []
    attempt_latencies = []
    unusable_responses = []
    for row in rows:
        sample_key = key(row)
        reference = expected.get(sample_key, {})
        expected_text = reference.get("text")
        check(row.get("text", row.get("utterance")) == expected_text, f"sample_text_drift:{sample_key}")
        result = row.get("result", {})
        diagnostics = row.get("diagnostics", {})
        check(result.get("status") == row.get("actual_status"), f"result_status_mismatch:{sample_key}")
        check(result.get("diagnostics") == diagnostics, f"result_diagnostics_mismatch:{sample_key}")
        check(normalized_mission(result.get("mission")) == normalized_mission(row.get("compiled_mission")), f"result_mission_mismatch:{sample_key}")
        linked = by_sample.get(sample_key, [])
        invoked = row.get("provider_invoked") is True
        check(len(linked) == int(invoked), f"sample_call_count:{sample_key}")
        if not invoked:
            check(row.get("provider_attempts") == 0 and not row.get("attempt_ids"), f"uninvoked_sample_attempts:{sample_key}")
            check(row.get("terminal_transport_status") == "NOT_INVOKED", f"uninvoked_transport_status:{sample_key}")
            continue
        if len(linked) != 1:
            continue
        call = linked[0]
        call_id = call.get("call_id")
        call_events = by_call_events.get(call_id, [])
        begins = [event for event in call_events if event.get("phase") == "begin"]
        ends = [event for event in call_events if event.get("phase") == "end"]
        backoffs = [event for event in call_events if event.get("phase") == "backoff"]
        indices = [event.get("attempt_index") for event in begins]
        check(indices == list(range(1, len(begins) + 1)) and 1 <= len(begins) <= 1 + provider["max_network_retries"], f"attempt_sequence:{call_id}")
        begin_ids = [event.get("attempt_id") for event in begins]
        check(len(begin_ids) == len(set(begin_ids)), f"duplicate_attempt_id:{call_id}")
        check(Counter(begin_ids) == Counter(event.get("attempt_id") for event in ends), f"attempt_begin_end_coverage:{call_id}")
        check(begin_ids == row.get("attempt_ids") == call.get("attempt_ids"), f"attempt_ids_mismatch:{call_id}")
        check(len(begins) == row.get("provider_attempts") == call.get("provider_attempts") == diagnostics.get("attempts"), f"attempt_count_mismatch:{call_id}")
        retry_ends = [event for event in ends if event.get("retry_scheduled")]
        check(Counter(event.get("attempt_id") for event in retry_ends) == Counter(event.get("attempt_id") for event in backoffs), f"backoff_coverage:{call_id}")
        reasons = [event.get("retry_reason") for event in retry_ends]
        check(reasons == row.get("retry_reason") == call.get("retry_reason"), f"retry_reason_mismatch:{call_id}")
        for begin in begins:
            check(key(begin) == sample_key, f"attempt_sample_context:{call_id}")
            expected_payload = {"model": provider["model"], "input": [{"role": "system", "content": prompt}, {"role": "user", "content": expected_text}], "temperature": provider["temperature"], "max_output_tokens": provider["max_output_tokens"], "stream": False}
            check(begin.get("request_payload") == expected_payload, f"request_payload_drift:{begin.get('attempt_id')}")
        for index, end in enumerate(ends, start=1):
            check(end.get("attempt_index") == index, f"attempt_end_sequence:{call_id}")
            check(isinstance(end.get("latency_s"), (int, float)) and end["latency_s"] >= 0, f"attempt_latency:{call_id}")
            if isinstance(end.get("latency_s"), (int, float)):
                attempt_latencies.append(end["latency_s"])
            retry = end.get("retry_scheduled") is True
            if retry:
                context = end.get("error_context", {})
                allowed = end.get("transport_status") in {"TIMEOUT", "API_ERROR"} and ("http_status" not in context or context["http_status"] in {429, 500, 502, 503, 504})
                check(allowed and index <= provider["max_network_retries"] and index < len(ends), f"retry_policy_violation:{end.get('attempt_id')}")
                reason = f"HTTP_{context['http_status']}" if "http_status" in context else end.get("transport_status")
                check(end.get("retry_reason") == reason, f"retry_reason_drift:{end.get('attempt_id')}")
            else:
                check(index == len(ends), f"semantic_or_terminal_failure_retried:{end.get('attempt_id')}")
        for backoff in backoffs:
            expected_delay = min(provider["retry_backoff_s"] * 2 ** (backoff["attempt_index"] - 1), 8.0)
            check(backoff.get("delay_s") == expected_delay, f"backoff_policy_drift:{call_id}")
            check(isinstance(backoff.get("actual_delay_s"), (int, float)) and backoff["actual_delay_s"] >= 0, f"backoff_observation_missing:{call_id}")
        terminal = call.get("terminal_transport_status")
        check(row.get("terminal_transport_status") == terminal, f"terminal_status_mismatch:{call_id}")
        check(row.get("transport_failure") is (terminal != "SUCCESS") and call.get("transport_failure") is (terminal != "SUCCESS"), f"transport_failure_mismatch:{call_id}")
        if terminal != "SUCCESS":
            if ends and ends[-1].get("transport_status") == "SUCCESS":
                document = ends[-1].get("provider_document", {})
                usage = normalized_usage(document)
                reasoning = (document.get("usage") or {}).get("output_tokens_details", {}).get("reasoning_tokens")
                known_unusable = terminal == "API_ERROR" and not output_text(document) and document.get("status") == "incomplete" and (document.get("incomplete_details") or {}).get("reason") == "max_output_tokens" and usage is not None and usage.get("output_tokens") == 4096 and reasoning == 4096
                check(known_unusable, f"unreviewed_unusable_provider_response:{call_id}")
                check(document.get("model", provider["model"]) == provider["model"], f"unusable_response_model_drift:{call_id}")
                if known_unusable:
                    check("response" not in call, f"unusable_call_claims_semantic_response:{call_id}")
                    check(row.get("provider_tokens") in {None, usage.get("total_tokens")}, f"unusable_response_token_restatement:{call_id}")
                    check(diagnostics.get("backend_error", {}).get("retryable") is False, f"unusable_response_retryability:{call_id}")
                    check(diagnostics.get("raw_response") is None and row.get("compiled_mission") is None, f"unusable_response_semantics_inferred:{call_id}")
                    if isinstance(usage.get("total_tokens"), int):
                        successful_tokens.append(usage["total_tokens"])
                    if "raw_reported_provider_tokens" in row:
                        check(row["raw_reported_provider_tokens"] == usage.get("total_tokens"), f"unusable_raw_token_restatement:{call_id}")
                    unusable_responses.append({"sample_id": row["sample_id"], "campaign": row["campaign"], "call_id": call_id, "provider_response_class": "UNUSABLE_PROVIDER_RESPONSE", "provider_usage": usage, "reasoning_tokens": reasoning, "semantic_response_observed": False})
            continue
        check(bool(ends) and ends[-1].get("transport_status") == "SUCCESS", f"successful_call_lacks_response:{call_id}")
        if not ends:
            continue
        document = ends[-1].get("provider_document", {})
        response = call.get("response", {})
        raw_text = output_text(document)
        check(raw_text == response.get("text") == diagnostics.get("raw_response"), f"raw_response_mismatch:{call_id}")
        check(text_sha(raw_text) == diagnostics.get("raw_response_sha256"), f"raw_response_hash_mismatch:{call_id}")
        check(document.get("model", provider["model"]) == response.get("model") == diagnostics.get("model") == provider["model"], f"response_model_drift:{call_id}")
        usage = normalized_usage(document)
        check(usage == response.get("usage") == diagnostics.get("usage"), f"usage_mismatch:{call_id}")
        check(isinstance(usage, Mapping) and isinstance(usage.get("total_tokens"), int) and usage["total_tokens"] > 0, f"missing_token_accounting:{call_id}")
        if isinstance(usage, Mapping) and isinstance(usage.get("total_tokens"), int):
            successful_tokens.append(usage["total_tokens"])
            check(row.get("provider_tokens") == usage["total_tokens"], f"row_token_mismatch:{call_id}")
        request = response.get("request_parameters", {})
        expected_request = {name: provider[name] for name in ("model", "temperature", "max_output_tokens", "max_network_retries", "retry_backoff_s")}
        expected_request["stream"] = False
        check(request == diagnostics.get("request_parameters") == expected_request, f"request_parameter_drift:{call_id}")
        check(response.get("attempts") == len(begins), f"response_attempt_count:{call_id}")
        check(response.get("latency_s") == diagnostics.get("latency_s") == row.get("latency_s") == ends[-1].get("frozen_latency_s"), f"successful_attempt_latency_mismatch:{call_id}")
        check(response.get("response_id") == diagnostics.get("response_id") == document.get("id"), f"response_id_mismatch:{call_id}")
    return {"status": "PASS" if not errors else "FAIL", "checks": checks, "errors": sorted(set(errors)), "sample_count": len(rows), "call_count": len(calls), "attempt_begin_count": sum(event.get("phase") == "begin" for event in events), "attempt_end_count": sum(event.get("phase") == "end" for event in events), "reported_provider_tokens": sum(successful_tokens), "unusable_response_count": len(unusable_responses), "unusable_responses": unusable_responses, "response_evidence_complete": not unusable_responses and all(row.get("terminal_transport_status") in {"SUCCESS", "NOT_INVOKED"} for row in rows), "observed_attempt_latency_s": sum(attempt_latencies), "pilot_mixed": any(key(row)[0] not in {"final_compiler", "guard_ood", "provider_preflight"} for row in rows)}


def audit(campaign_dir: Path, ood_dir: Path) -> dict[str, Any]:
    manifest_path = campaign_dir / "campaign_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_sha = file_sha(manifest_path)
    common = manifest["common_provenance"]
    completion_path = campaign_dir / "campaign_completion_state.json"
    state = json.loads((completion_path if completion_path.exists() else campaign_dir / "campaign_state.json").read_text(encoding="utf-8"))
    protocol = yaml.safe_load((BASE / "protocol.yaml").read_text(encoding="utf-8"))
    finals = yaml.safe_load((BASE / "final/language_realizations_final.yaml").read_text(encoding="utf-8"))["samples"]
    ood = read_rows(BASE / "ood/guard_ood_dataset.jsonl")
    expected = {(campaign, sample_id): {"text": text, "dataset_sha256": dataset_sha} for campaign, samples, text_key, id_key, dataset_sha in [("final_compiler", finals, "text", "sample_id", common["dataset_sha256"]["final_language"]), ("guard_ood", ood, "utterance", "candidate_id", common["dataset_sha256"]["ood"])] for sample in samples for sample_id, text in [(sample[id_key], sample[text_key])]}
    compiler_rows = read_rows(campaign_dir / "compiler_results.jsonl")
    ood_rows = read_rows(ood_dir / "ood_results.jsonl")
    guard_rows = read_rows(ood_dir / "guard_only_results.jsonl")
    events = read_rows(campaign_dir / "raw/provider_attempts.jsonl")
    calls = read_rows(campaign_dir / "raw/provider_calls.jsonl")
    prompt = (ROOT / protocol["prompt"]["direct"]).read_text(encoding="utf-8")
    journal = audit_records(expected=expected, rows=compiler_rows + ood_rows, events=events, calls=calls, common=common, manifest_sha=manifest_sha, prompt=prompt, provider=protocol["provider"])
    verification = verify()
    errors = list(journal["errors"])

    def check(condition, description):
        if not condition:
            errors.append(description)

    check(verification["status"] == "PASS", "frozen_baseline_or_manifest_drift")
    check(subprocess.run(["git", "merge-base", "--is-ancestor", common["code_commit"], "HEAD"], cwd=ROOT, capture_output=True).returncode == 0, "tested_code_commit_not_in_current_history")
    for field in ("protocol_sha256", "freeze_manifest_sha256", "freeze_tag", "freeze_commit", "compiler_provenance", "prompt_sha256"):
        check(common.get(field) == verification.get(field), f"verification_provenance_mismatch:{field}")
    for field, source in (("harness_sha256", "scripts/run_phase23_session4.py"), ("verifier_sha256", "scripts/verify_phase23_session4.py")):
        check(common.get(field) == file_sha(ROOT / source), f"tested_code_hash_drift:{source}")
        expected_blob = subprocess.check_output(["git", "rev-parse", f"{common['code_commit']}:{source}"], cwd=ROOT, text=True).strip()
        current_blob = subprocess.check_output(["git", "hash-object", "--path", source, source], cwd=ROOT, text=True).strip()
        check(expected_blob == current_blob, f"code_commit_blob_mismatch:{source}")
    check(state.get("status") == "COMPLETE" and state.get("campaign_manifest_sha256") == manifest_sha and state.get("common_provenance") == common, "campaign_state_incomplete_or_drift")
    check(state.get("provider_calls") == len(calls), "campaign_call_count_mismatch")
    check(state.get("provider_ledger_sha256") == {"attempts": file_sha(campaign_dir / "raw/provider_attempts.jsonl"), "calls": file_sha(campaign_dir / "raw/provider_calls.jsonl")}, "terminal_ledger_hash_mismatch")
    if completion_path.exists():
        continuation_path = campaign_dir / "continuation_manifest.json"
        continuation = json.loads(continuation_path.read_text(encoding="utf-8"))
        check(state.get("continuation_manifest_sha256") == file_sha(continuation_path), "continuation_manifest_hash_mismatch")
        check(continuation.get("common_provenance") == common and continuation.get("original_campaign_manifest_sha256") == manifest_sha, "continuation_scientific_provenance_mismatch")
        check(file_sha(campaign_dir / "campaign_state.json") == continuation["original_campaign_state_sha256"] == state.get("original_campaign_state_sha256"), "original_interrupted_state_changed")
        check(file_sha(ood_dir / "guard_only_results.jsonl") == continuation["guard_only_results_sha256"], "original_guard_only_evidence_changed")
        for key, filename in (("attempts", "provider_attempts.jsonl"), ("calls", "provider_calls.jsonl")):
            prefix = (campaign_dir / "raw" / filename).read_bytes()[:continuation["original_provider_ledger_bytes"][key]]
            check(hashlib.sha256(prefix).hexdigest() == continuation["original_provider_ledger_sha256"][key], f"original_ledger_prefix_changed:{key}")
        prefix = (ood_dir / "ood_results.jsonl").read_bytes()[:continuation["original_ood_results_bytes"]]
        check(hashlib.sha256(prefix).hexdigest() == continuation["original_ood_results_sha256"], "original_ood_results_prefix_changed")
        prior = continuation["already_recorded_ids"]
        later = continuation["scheduled_remaining_ids"]
        check(prior + later == manifest["scheduled_samples"]["ood"] and not set(prior) & set(later), "continuation_schedule_changed_or_retried")
        continuation_provenance = {**continuation["continuation_provenance"], "continuation_manifest_sha256": file_sha(continuation_path)}
        for value in list(ood_rows) + list(events) + list(calls):
            if value.get("campaign") == "guard_ood" and value.get("sample_id") in set(later):
                check(value.get("continuation_provenance") == continuation_provenance, f"continuation_actual_code_provenance_mismatch:{value.get('sample_id')}")
        check(continuation_provenance["harness_sha256"] == file_sha(ROOT / "scripts/continue_phase23_session4.py"), "continuation_source_hash_drift")
        check(state.get("unusable_response_count") == journal["unusable_response_count"] and state.get("response_evidence_complete") == journal["response_evidence_complete"], "completion_response_evidence_classification_mismatch")
    ood_manifest = json.loads((ood_dir / "campaign_manifest.json").read_text(encoding="utf-8"))
    check(ood_manifest.get("parent_manifest_sha256") == manifest_sha and {key: value for key, value in ood_manifest.items() if key != "parent_manifest_sha256"} == manifest, "ood_campaign_manifest_binding_mismatch")
    receipt_path = ROOT / manifest["preflight_receipt"]
    check(file_sha(receipt_path) == manifest["preflight_sha256"], "preflight_receipt_hash_mismatch")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    check(receipt.get("status") == "PASS" and receipt.get("common_provenance") == common, "preflight_status_or_provenance_drift")
    check(file_sha(ROOT / receipt["provider_binding_path"]) == receipt["provider_binding_sha256"] and receipt["provider_binding"]["status"] == "PASS", "historical_provider_binding_drift")
    check(manifest.get("endpoint_fingerprint") == receipt.get("endpoint_fingerprint"), "endpoint_fingerprint_drift")
    for key, filename in (("attempts", "provider_attempts.jsonl"), ("calls", "provider_calls.jsonl")):
        check(file_sha(receipt_path.parent / "raw" / filename) == receipt["provider_ledger_sha256"][key], f"preflight_ledger_hash_mismatch:{key}")
    smoke_result = receipt.get("result", {})
    smoke_diagnostics = smoke_result.get("diagnostics", {})
    smoke_row = {**receipt, "campaign": "provider_preflight", "sample_id": "session4-smoke", "dataset_sha256": None, "campaign_manifest_sha256": None, "text": receipt.get("smoke_text"), "actual_status": smoke_result.get("status"), "compiled_mission": smoke_result.get("mission"), "diagnostics": smoke_diagnostics, "provider_tokens": (smoke_diagnostics.get("usage") or {}).get("total_tokens"), "latency_s": smoke_diagnostics.get("latency_s")}
    preflight_journal = audit_records(expected={("provider_preflight", "session4-smoke"): {"text": "前进4米", "dataset_sha256": None}}, rows=[smoke_row], events=read_rows(receipt_path.parent / "raw/provider_attempts.jsonl"), calls=read_rows(receipt_path.parent / "raw/provider_calls.jsonl"), common=common, manifest_sha=None, prompt=prompt, provider=protocol["provider"])
    check(preflight_journal["status"] == "PASS", "preflight_independent_journal_audit_failed")
    smoke_mission = normalized_mission(smoke_result.get("mission"))
    check(smoke_result.get("status") == "SUCCESS" and smoke_mission is not None and len(smoke_mission["steps"]) == 1 and smoke_mission["steps"][0]["skill"] == "walk_forward" and smoke_mission["steps"][0]["parameters"] == {"distance_m": 4.0} and smoke_mission["steps"][0]["depends_on"] == [], "preflight_independent_exact_smoke_check_failed")
    check(all(manifest.get(key) == "PASS" for key in ("freeze_verification_status", "provider_preflight_status", "provider_binding_status")), "campaign_prerequisite_not_PASS")
    check(manifest.get("semantic_retry") is False and manifest.get("runtime_execution") is False, "campaign_scope_violation")
    check(manifest["scheduled_samples"]["compiler"] == [row["sample_id"] for row in finals], "manifest_final_schedule_drift")
    check(manifest["scheduled_samples"]["ood"] == [row["candidate_id"] for row in ood], "manifest_ood_schedule_drift")
    check([row["sample_id"] for row in compiler_rows] == [row["sample_id"] for row in finals], "final_execution_order_or_coverage_drift")
    check([row["sample_id"] for row in ood_rows] == [row["candidate_id"] for row in ood], "ood_execution_order_or_coverage_drift")
    check([row["sample_id"] for row in guard_rows] == [row["candidate_id"] for row in ood], "guard_only_order_or_coverage_drift")
    by_ood = {row["candidate_id"]: row for row in ood}
    by_guard = {row["sample_id"]: row for row in guard_rows}
    for row in guard_rows + ood_rows:
        reference = by_ood.get(row["sample_id"], {})
        check(all(row.get(key) == value for key, value in reference.items()), f"ood_original_metadata_drift:{row['sample_id']}")
        check(row.get("common_provenance") == common and row.get("campaign_manifest_sha256") == manifest_sha and row.get("dataset_sha256") == common["dataset_sha256"]["ood"], f"ood_provenance_drift:{row['sample_id']}")
    for row in ood_rows:
        guard = by_guard.get(row["sample_id"], {})
        check(all(row.get(key) == guard.get(key) for key in ("guard_status", "guard_reason_code", "guard_rejects")), f"guard_observation_mismatch:{row['sample_id']}")
        if guard.get("guard_rejects"):
            check(row.get("provider_attempts") == 0 and row.get("actual_status") == "MALFORMED" and row.get("compiled_mission") is None, f"guard_reject_provider_or_mission_violation:{row['sample_id']}")
    first_ood_begin = [event for event in events if event.get("campaign") == "guard_ood" and event.get("phase") == "begin"]
    if first_ood_begin:
        check(dt.datetime.fromisoformat(first_ood_begin[0]["timestamp_utc"]).timestamp() >= (ood_dir / "guard_only_results.jsonl").stat().st_mtime, "ood_provider_invoked_before_guard_only_file_completed")
    aggregate = json.loads((campaign_dir / "compiler_results.json").read_text(encoding="utf-8"))
    check(aggregate.get("records") == compiler_rows and aggregate.get("record_count") == 306, "final_json_jsonl_roundtrip_mismatch")
    return {"schema_version": "session4-independent-evidence-audit-v1", "status": "PASS" if not errors else "FAIL", "common_provenance": common, "campaign_manifest_sha256": manifest_sha, "audit_script_sha256": file_sha(Path(__file__)), "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "errors": sorted(set(errors)), "provider_journal": journal, "preflight_journal": preflight_journal, "freeze_verification_status": verification["status"], "freeze_check_counts": verification["check_counts"], "frozen_baseline_drift": verification["baseline_drift_count"], "sample_counts": {"compiler": len(compiler_rows), "ood": len(ood_rows), "guard_only": len(guard_rows)}, "response_evidence_complete": journal["response_evidence_complete"], "raw_logs_exclude_pilot": journal["pilot_mixed"] is False, "runtime_evaluated": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, default=ROOT / "artifacts/long_horizon_language_001/session4")
    parser.add_argument("--ood-dir", type=Path, default=ROOT / "artifacts/long_horizon_language_001/final_guard_ood")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError("audit evidence output already exists")
    result = audit(args.campaign_dir, args.ood_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"status": result["status"], "errors": result["errors"], "sample_counts": result["sample_counts"]}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
