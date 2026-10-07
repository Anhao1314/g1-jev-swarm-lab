"""Read-only forensic checks of saved Session 4 records; no SUT imports/calls."""
from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "experiments/phase2/long_horizon_language_001"
AUDIT = BASE / "session4_audit"
RUN = ROOT / "artifacts/long_horizon_language_001/session4"
OOD = ROOT / "artifacts/long_horizon_language_001/final_guard_ood"
IDS = ("ood-m-012", "ood-m-025", "ood-m-031", "ood-m-052", "ood-m-066", "ood-m-069")


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def numbered(path: Path):
    return [(n, json.loads(line)) for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if line.strip()]


def output_text(document):
    return "".join(part["text"] for item in document.get("output", []) for part in item.get("content", [])
                   if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str)).strip()


def mission_shape(document):
    # Mission.to_dict omits an empty s1 depends_on; the benchmark spells it [].
    # Preserve every identifier, action, parameter and actual dependency edge.
    return {"schema_version": document["schema_version"], "mission_id": document["mission_id"],
            "steps": [{"id": step["id"], "skill": step["skill"], "parameters": step.get("parameters", {}),
                       "depends_on": step.get("depends_on", [])} for step in document["steps"]]}


def chain_checks(source, guard, result, begin, end, call, compact, prompt):
    """Check saved links/predicate consistency; never change or replace a score."""
    sid = source["candidate_id"]
    document = end["provider_document"]
    text = output_text(document)
    parsed = json.loads(text)
    payload = begin["request_payload"]
    unsafe = source["expected_status"] == "MALFORMED" and result["compiled_mission"] is not None
    checks = {
        "sample_links": all(row["sample_id"] == sid for row in (guard, result, begin, end, call, compact)),
        "original_metadata": all(result.get(k) == v and guard.get(k) == v for k, v in source.items()),
        "full_source_in_request": payload["input"][1]["content"] == source["utterance"],
        "unchanged_system_prompt": payload["input"][0]["content"] == prompt,
        "frozen_request_parameters": all(payload.get(k) == v for k, v in
           {"model": "deepseek-flash", "temperature": 0.0, "max_output_tokens": 4096, "stream": False}.items()),
        "guard_pass_recorded": guard["guard_status"] == result["guard_status"] == "PASS" and not guard["guard_rejects"],
        "single_attempt": begin["attempt_index"] == end["attempt_index"] == result["provider_attempts"] == call["provider_attempts"] == 1,
        "call_links": begin["call_id"] == end["call_id"] == call["call_id"],
        "transport_success": end["transport_status"] == call["terminal_transport_status"] == "SUCCESS",
        "provider_model": document["model"] == call["response"]["model"] == "deepseek-flash",
        "raw_response_links": text == call["response"]["text"] == result["diagnostics"]["raw_response"],
        "compact_raw_response_hash": compact["diagnostics"]["raw_response_sha256"] == sha(text.encode("utf-8")),
        "envelope_and_mission_links": parsed["status"] == result["actual_status"] == "SUCCESS" and parsed["error_code"] is None
           and mission_shape(parsed["mission"]) == mission_shape(result["compiled_mission"]) == mission_shape(result["result"]["mission"]),
        "recorded_static_validation": result["diagnostics"]["validation"] == {"valid": True, "issues": []},
        "recorded_contract_violations": result["diagnostics"]["contract_violation_count"] == 0,
        "frozen_evaluator_predicate_consistency": result["unsafe_acceptance"] == unsafe and result["silent_repair"] == unsafe,
        "split_confidence_consistency": source["split"] == ("primary_gold" if source["confidence"] == "high" else "disputed_sensitivity"),
    }
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=AUDIT / "safety_chain_checks_v2.json")
    args = parser.parse_args()
    manifest = json.loads((BASE / "session4/campaign_manifest.json").read_text(encoding="utf-8"))
    datasets = {row["candidate_id"]: (line, row) for line, row in numbered(BASE / "ood/guard_ood_dataset.jsonl")}
    guards = {row["sample_id"]: (line, row) for line, row in numbered(OOD / "guard_only_results.jsonl")}
    results = {row["sample_id"]: (line, row) for line, row in numbered(OOD / "ood_results.jsonl")}
    compact = {row["sample_id"]: row for row in json.loads((BASE / "session4/ood_full_system_results.json").read_text(encoding="utf-8"))["records"]}
    events = numbered(RUN / "raw/provider_attempts.jsonl")
    calls = numbered(RUN / "raw/provider_calls.jsonl")
    prompt = (ROOT / "prompts/llm_mission_compiler_v1.txt").read_text(encoding="utf-8")
    records = []
    for sid in IDS:
        source_line, source = datasets[sid]
        guard_line, guard = guards[sid]
        result_line, result = results[sid]
        related = [(line, row) for line, row in events if row["sample_id"] == sid]
        begin_line, begin = next(item for item in related if item[1]["phase"] == "begin")
        end_line, end = next(item for item in related if item[1]["phase"] == "end")
        linked_calls = [(line, row) for line, row in calls if row["sample_id"] == sid]
        assert len(related) == 2 and len(linked_calls) == 1
        call_line, call = linked_calls[0]
        checks = chain_checks(source, guard, result, begin, end, call, compact[sid], prompt)
        records.append({"sample_id": sid, "source": source, "guard_status": guard["guard_status"],
            "actual_status": result["actual_status"], "accepted_mission": result["compiled_mission"],
            "provider_call_id": call["call_id"], "raw_assistant_text_sha256": sha(call["response"]["text"].encode("utf-8")),
            "evidence_locations": {"dataset": {"path": str((BASE / "ood/guard_ood_dataset.jsonl").relative_to(ROOT)), "line": source_line},
                "guard": {"path": str((OOD / "guard_only_results.jsonl").relative_to(ROOT)), "line": guard_line},
                "system_result": {"path": str((OOD / "ood_results.jsonl").relative_to(ROOT)), "line": result_line},
                "provider_call": {"path": str((RUN / "raw/provider_calls.jsonl").relative_to(ROOT)), "line": call_line},
                "provider_attempt": {"path": str((RUN / "raw/provider_attempts.jsonl").relative_to(ROOT)), "begin_line": begin_line, "end_line": end_line}},
            "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"})
    paths = [BASE / "ood/guard_ood_dataset.jsonl", OOD / "guard_only_results.jsonl", OOD / "ood_results.jsonl",
             RUN / "raw/provider_calls.jsonl", RUN / "raw/provider_attempts.jsonl", ROOT / "prompts/llm_mission_compiler_v1.txt",
             ROOT / "src/g1swarm/llm/compiler.py", ROOT / "src/g1swarm/mission/validator.py", ROOT / "scripts/run_phase23_session4.py"]
    result = {"schema_version": "session4-source-chain-audit-v1", "trusted_session4_commit": "5fabf3c050df4420f414a564dcdf5ce255a5b0fa",
        "common_provenance": manifest["common_provenance"], "status": "PASS" if all(row["status"] == "PASS" for row in records) else "FAIL",
        "checks": sum(len(row["checks"]) for row in records), "records": records,
        "source_hashes": {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in paths},
        "scoring_policy": "Only check consistency of frozen evaluator predicate and saved flags; no new labels/scores replace Session4.",
        "boundary": {"provider_calls": 0, "guard_calls": 0, "compiler_calls": 0, "runtime_calls": 0, "frozen_changes": False}}
    result['audit_checker_sha256'] = sha(Path(__file__).read_bytes())
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2); handle.write("\n")
    print(json.dumps({"status": result["status"], "cases": len(records), "checks": result["checks"]}))
    assert result["status"] == "PASS"


if __name__ == "__main__":
    main()
