"""Collect first attempts for pending frozen OOD IDs after an interrupted run.

This is a continuation of an immutable schedule, never a retry of any existing
sample. Original manifests/state/results remain unchanged. The original frozen
observer/compiler own every request, transport retry and semantic decision.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Sequence

from scripts import run_phase23_session4 as original
from scripts.audit_phase23_session4_evidence import audit_records, normalized_usage, output_text, read_rows
from scripts.verify_phase23_session4 import verify

ROOT = original.ROOT
BASE = original.BASE


def pending_schedule(scheduled_ids: Sequence[str], existing_rows: Sequence[Mapping[str, Any]], previously_called_ids: Sequence[str]) -> list[str]:
    observed = [row["sample_id"] for row in existing_rows]
    if observed != list(scheduled_ids[:len(observed)]) or len(observed) != len(set(observed)):
        raise ValueError("existing OOD results do not form a unique frozen schedule prefix")
    if set(previously_called_ids) - set(observed):
        raise ValueError("an already attempted OOD sample has no result; cannot resample it")
    return list(scheduled_ids[len(observed):])


def classify_unusable(events: Sequence[Mapping[str, Any]], calls: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The known HTTP-success/no-assistant case has retained raw token evidence."""
    if len(calls) != 1 or calls[0].get("terminal_transport_status") != "API_ERROR":
        return None
    ends = [event for event in events if event.get("phase") == "end"]
    if not ends or ends[-1].get("transport_status") != "SUCCESS":
        return None
    document = ends[-1].get("provider_document", {})
    if output_text(document) or document.get("status") != "incomplete" or (document.get("incomplete_details") or {}).get("reason") != "max_output_tokens":
        return None
    usage = normalized_usage(document)
    reasoning = (document.get("usage") or {}).get("output_tokens_details", {}).get("reasoning_tokens")
    if not usage or usage.get("output_tokens") != 4096 or reasoning != 4096:
        return None
    return {"sample_id": calls[0]["sample_id"], "campaign": calls[0]["campaign"], "provider_response_class": "UNUSABLE_PROVIDER_RESPONSE", "semantic_response_observed": False, "provider_transport_outage": False, "provider_usage": usage, "provider_reasoning_tokens": reasoning, "provider_status": "incomplete", "incomplete_reason": "max_output_tokens", "provider_call_id": calls[0]["call_id"], "provider_attempts": calls[0]["provider_attempts"]}


class ContinuingJournal(original.AttemptJournal):
    def __init__(self, directory: Path, common: Mapping[str, Any], continuation: Mapping[str, Any], existing_calls: Sequence[Mapping[str, Any]]) -> None:
        self.attempt_path = directory / "provider_attempts.jsonl"
        self.call_path = directory / "provider_calls.jsonl"
        if not self.attempt_path.is_file() or not self.call_path.is_file():
            raise ValueError("original provider ledger missing")
        self.provenance = dict(common)
        self.context = {}
        numbers = [int(call["call_id"].split("-")[-1]) for call in existing_calls]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("original provider call sequence is not contiguous")
        self.call_count = max(numbers, default=0)
        self.sample_events = []
        self.sample_calls = []
        self._credential = None
        self.continuation = dict(continuation)

    def attempt(self, row):
        super().attempt({**row, "continuation_provenance": self.continuation})

    def call(self, row):
        super().call({**row, "continuation_provenance": self.continuation})


def validate_existing(campaign_dir: Path, ood_dir: Path) -> dict[str, Any]:
    verification = verify()
    if verification["status"] != "PASS":
        raise ValueError("freeze or frozen baseline drift; continuation forbidden")
    manifest_path = campaign_dir / "campaign_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    common = manifest["common_provenance"]
    for field in ("protocol_sha256", "freeze_manifest_sha256", "freeze_tag", "freeze_commit", "compiler_provenance", "prompt_sha256"):
        if common.get(field) != verification.get(field):
            raise ValueError(f"frozen provenance differs: {field}")
    if common["harness_sha256"] != original.sha(Path(original.__file__)) or common["verifier_sha256"] != original.sha(ROOT / "scripts/verify_phase23_session4.py"):
        raise ValueError("original collector or verifier has changed")
    for key, expected in (("final_language", "final_dataset_sha256"), ("final_canonical", "canonical_dataset_sha256"), ("ood", "ood_dataset_sha256")):
        if common["dataset_sha256"][key] != verification[expected]:
            raise ValueError("frozen dataset provenance differs")
    state_path = campaign_dir / "campaign_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    manifest_sha = original.sha(manifest_path)
    if state.get("common_provenance") != common or state.get("campaign_manifest_sha256") != manifest_sha or not state.get("status", "").startswith("BLOCKED"):
        raise ValueError("original interrupted state is missing or unbound")
    events = read_rows(campaign_dir / "raw/provider_attempts.jsonl")
    calls = read_rows(campaign_dir / "raw/provider_calls.jsonl")
    ledger_hashes = {"attempts": original.sha(campaign_dir / "raw/provider_attempts.jsonl"), "calls": original.sha(campaign_dir / "raw/provider_calls.jsonl")}
    if state.get("provider_ledger_sha256") != ledger_hashes:
        raise ValueError("original stopped ledger hashes differ")
    protocol = original.runner.load_protocol()
    receipt_path = ROOT / manifest["preflight_receipt"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if original.sha(receipt_path) != manifest["preflight_sha256"] or receipt.get("status") != "PASS" or receipt.get("common_provenance") != common:
        raise ValueError("original successful preflight receipt has changed")
    binding_path = ROOT / receipt["provider_binding_path"]
    if original.sha(binding_path) != receipt["provider_binding_sha256"] or receipt["provider_binding"]["status"] != "PASS":
        raise ValueError("historical provider binding has changed")
    if original.missing_environment(protocol):
        raise ValueError("provider configuration missing")
    endpoint = os.environ.get(protocol["provider"]["base_url_env"]) or os.environ.get("OPENAI_BASE_URL")
    if original.endpoint_identity(str(endpoint))["endpoint_fingerprint"] != receipt["endpoint_fingerprint"] or manifest["endpoint_fingerprint"] != receipt["endpoint_fingerprint"]:
        raise ValueError("provider endpoint drift")
    for key, filename in (("attempts", "provider_attempts.jsonl"), ("calls", "provider_calls.jsonl")):
        if original.sha(receipt_path.parent / "raw" / filename) != receipt["provider_ledger_sha256"][key]:
            raise ValueError("preflight ledger drift")
    from g1swarm.config import load_yaml
    final_samples = load_yaml(BASE / "final/language_realizations_final.yaml")["samples"]
    ood_samples = read_rows(BASE / "ood/guard_ood_dataset.jsonl")
    final_rows = read_rows(campaign_dir / "compiler_results.jsonl")
    ood_rows = read_rows(ood_dir / "ood_results.jsonl")
    guard_rows = read_rows(ood_dir / "guard_only_results.jsonl")
    if [row["sample_id"] for row in final_rows] != [row["sample_id"] for row in final_samples] or len(final_rows) != 306:
        raise ValueError("Final compiler evidence not complete; this continuation is OOD-only")
    scheduled = [row["candidate_id"] for row in ood_samples]
    if manifest["scheduled_samples"]["ood"] != scheduled or [row["sample_id"] for row in guard_rows] != scheduled:
        raise ValueError("frozen OOD schedule or Guard-only coverage differs")
    remaining = pending_schedule(scheduled, ood_rows, [call["sample_id"] for call in calls if call["campaign"] == "guard_ood"])
    if state["pending_samples"]["ood"] != remaining or state["completed_samples"]["ood"] != len(ood_rows):
        raise ValueError("interrupted state pending schedule differs")
    expected = {("final_compiler", row["sample_id"]): {"text": row["text"], "dataset_sha256": common["dataset_sha256"]["final_language"]} for row in final_samples}
    expected.update({("guard_ood", row["candidate_id"]): {"text": row["utterance"], "dataset_sha256": common["dataset_sha256"]["ood"]} for row in ood_samples[:len(ood_rows)]})
    journal_audit = audit_records(expected=expected, rows=final_rows + ood_rows, events=events, calls=calls, common=common, manifest_sha=manifest_sha, prompt=(ROOT / protocol["prompt"]["direct"]).read_text(encoding="utf-8"), provider=protocol["provider"])
    if journal_audit["status"] != "PASS":
        raise ValueError("existing sample/payload/attempt evidence audit failed: " + ", ".join(journal_audit["errors"][:5]))
    original_cases = []
    for row in ood_rows:
        reference = ood_samples[scheduled.index(row["sample_id"])]
        guard = guard_rows[scheduled.index(row["sample_id"])]
        if any(row.get(key) != value for key, value in reference.items()) or any(row.get(key) != guard.get(key) for key in ("guard_status", "guard_reason_code", "guard_rejects")):
            raise ValueError("existing OOD original labels/metadata/Guard observation differs")
        sample_events = [event for event in events if event["campaign"] == "guard_ood" and event["sample_id"] == row["sample_id"]]
        sample_calls = [call for call in calls if call["campaign"] == "guard_ood" and call["sample_id"] == row["sample_id"]]
        case = classify_unusable(sample_events, sample_calls)
        if case:
            original_cases.append(case)
    if len(original_cases) != 1 or original_cases[0]["sample_id"] != "ood-m-038":
        raise ValueError("interruption is not the reviewed ood-m-038 no-assistant response")
    return {"manifest": manifest, "manifest_sha256": manifest_sha, "common": common, "state_path": state_path, "state": state, "ledger_hashes": ledger_hashes, "protocol": protocol, "receipt_path": receipt_path, "receipt": receipt, "final_rows": final_rows, "ood_samples": ood_samples, "ood_rows": ood_rows, "guard_rows": guard_rows, "events": events, "calls": calls, "remaining": remaining, "verification": verification, "existing_journal_audit": journal_audit, "original_cases": original_cases}


def run(campaign_dir: Path, ood_dir: Path) -> dict[str, Any]:
    for name in ("continuation_manifest.json", "campaign_completion_state.json", "response_classification.json"):
        if (campaign_dir / name).exists():
            raise FileExistsError("continuation output exists; refuse another semantic campaign")
    data = validate_existing(campaign_dir, ood_dir)
    common = data["common"]
    continuation = {"code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "harness_sha256": original.sha(Path(__file__)), "original_scientific_code_commit": common["code_commit"]}
    manifest = {"schema_version": "session4-continuation-v1", "created_utc": original.utc_now(), "common_provenance": common, "continuation_provenance": continuation, "original_campaign_manifest_sha256": data["manifest_sha256"], "original_campaign_state_sha256": original.sha(data["state_path"]), "original_provider_ledger_sha256": data["ledger_hashes"], "original_provider_ledger_bytes": {"attempts": (campaign_dir / "raw/provider_attempts.jsonl").stat().st_size, "calls": (campaign_dir / "raw/provider_calls.jsonl").stat().st_size}, "original_ood_results_sha256": original.sha(ood_dir / "ood_results.jsonl"), "original_ood_results_bytes": (ood_dir / "ood_results.jsonl").stat().st_size, "guard_only_results_sha256": original.sha(ood_dir / "guard_only_results.jsonl"), "provider_preflight_sha256": original.sha(data["receipt_path"]), "scheduled_remaining_ids": data["remaining"], "already_recorded_ids": [row["sample_id"] for row in data["ood_rows"]], "semantic_retry": False, "runtime_execution": False, "known_unusable_response": data["original_cases"][0], "precontinuation_integrity": {"freeze_status": "PASS", "freeze_checks": data["verification"]["check_counts"], "provider_journal_status": "PASS", "provider_journal_checks": data["existing_journal_audit"]["checks"]}}
    original.write_json(campaign_dir / "continuation_manifest.json", manifest)
    continuation_sha = original.sha(campaign_dir / "continuation_manifest.json")
    continuation["continuation_manifest_sha256"] = continuation_sha
    journal = ContinuingJournal(campaign_dir / "raw", common, continuation, data["calls"])
    compiler, _, endpoint = original.make_observed_treatment(data["protocol"], journal)
    if endpoint["endpoint_fingerprint"] != data["receipt"]["endpoint_fingerprint"]:
        raise ValueError("provider endpoint drift at continuation start")
    rows = list(data["ood_rows"])
    cases = list(data["original_cases"])
    issues = []
    for index in range(len(rows), len(data["ood_samples"])):
        sample = data["ood_samples"][index]
        guard = data["guard_rows"][index]
        journal.start_sample("guard_ood", sample["candidate_id"], common["dataset_sha256"]["ood"], data["manifest_sha256"])
        started = time.perf_counter()
        result = compiler.compile(sample["utterance"])
        row = original.ood_record(sample, result, guard)
        row.update(campaign="guard_ood", sample_index=index, wall_time_s=time.perf_counter() - started, **journal.sample_summary())
        case = classify_unusable(journal.sample_events, journal.sample_calls)
        if case:
            cases.append(case)
            row.update(**{key: value for key, value in case.items() if key not in {"sample_id", "campaign", "provider_attempts"}}, semantic_outcome="NOT_OBSERVED_UNUSABLE_PROVIDER_RESPONSE", false_rejection=False, raw_reported_provider_tokens=case["provider_usage"]["total_tokens"])
        elif row["transport_failure"]:
            row.update(semantic_outcome="NOT_OBSERVED_TRANSPORT_FAILURE", false_rejection=False, provider_response_class="TERMINAL_TRANSPORT_FAILURE")
        else:
            row["semantic_outcome"] = result.status.value
        row = journal.safe({**row, "common_provenance": common, "dataset_sha256": common["dataset_sha256"]["ood"], "campaign_manifest_sha256": data["manifest_sha256"], "continuation_provenance": continuation})
        original.append_jsonl(ood_dir / "ood_results.jsonl", row)
        rows.append(row)
        issues = original.provider_response_issues(result, data["protocol"], journal)
        for event in journal.sample_events:
            document = event.get("provider_document")
            if document is not None and document.get("model", data["protocol"]["provider"]["model"]) != data["protocol"]["provider"]["model"]:
                issues.append("provider response model drift")
        if result.diagnostics.get("guard_status") != guard["guard_status"]:
            issues.append("frozen Guard observation mismatch")
        print(f"OOD continuation {len(rows)}/160: {sample['candidate_id']} {row['semantic_outcome']}", flush=True)
        if issues:
            break
    remaining = [row["candidate_id"] for row in data["ood_samples"][len(rows):]]
    true_transport = sum(bool(row.get("transport_failure")) for row in rows) - len(cases)
    state = {"schema_version": "session4-continuation-completion-v1", "common_provenance": common, "continuation_provenance": continuation, "campaign_manifest_sha256": data["manifest_sha256"], "original_campaign_state_sha256": manifest["original_campaign_state_sha256"], "continuation_manifest_sha256": continuation_sha, "status": "BLOCKED_PROVENANCE_DRIFT" if issues else "COMPLETE", "collection_status": "INCOMPLETE" if remaining else "COMPLETE", "response_evidence_complete": not remaining and not cases and true_transport == 0, "scientific_campaign_completeness": "INCOMPLETE_RESPONSES" if remaining or cases or true_transport else "COMPLETE", "issues": issues, "completed_samples": {"compiler": 306, "ood_guard_only": 160, "ood": len(rows)}, "pending_samples": {"compiler": [], "ood_guard_only": [], "ood": remaining}, "provider_calls": journal.call_count, "unusable_response_count": len(cases), "terminal_transport_failure_count": true_transport, "provider_ledger_sha256": {"attempts": original.sha(journal.attempt_path), "calls": original.sha(journal.call_path)}, "completed_utc": original.utc_now()}
    original.write_json(campaign_dir / "response_classification.json", {"common_provenance": common, "continuation_provenance": continuation, "campaign_manifest_sha256": data["manifest_sha256"], "samples": cases})
    original.write_json(campaign_dir / "campaign_completion_state.json", state)
    original.write_json(ood_dir / "campaign_completion_state.json", state)
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, default=ROOT / "artifacts/long_horizon_language_001/session4")
    parser.add_argument("--ood-dir", type=Path, default=ROOT / "artifacts/long_horizon_language_001/final_guard_ood")
    args = parser.parse_args(argv)
    result = run(args.campaign_dir, args.ood_dir)
    print(json.dumps({key: result[key] for key in ("status", "collection_status", "response_evidence_complete", "unusable_response_count", "terminal_transport_failure_count")}, ensure_ascii=False))
    return 0 if result["collection_status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
