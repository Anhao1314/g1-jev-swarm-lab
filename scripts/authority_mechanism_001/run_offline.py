"""Bounded offline mechanism study. No provider adapter or Runtime is used."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess

from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer
from g1swarm.authority_mechanism_001.contract import (
    AuthorityService, evaluate_release, source_digest,
)
from g1swarm.language.errors import CompilerStatus
from g1swarm.language.result import CompilerResult
from g1swarm.llm.backend import LLMBackendResponse
from g1swarm.mission.ir import Mission
from g1swarm.source_authority import apply_gate

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "experiments/phase2/authority_mechanism_001"
V1 = "experiments/phase2/source_authority_001"
DG4 = "experiments/phase2/source_authority_cross_model_001"
SERIAL = "experiments/phase2/source_authority_serial_001"
KEY_031 = "ood--ood-m-031"
KEY_POSITIVE = "controlled--cl-a-001"
CONTEXT = "offline-mechanism-study-001"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    indent=2, allow_nan=False) + "\n", encoding="utf8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_paths():
    paths = {"prompts/authority_certificate_v2.txt", "src/g1swarm/authority_certificate_v2.py",
             "src/g1swarm/source_authority/authorization.py", "src/g1swarm/source_authority_bounded.py",
             "src/g1swarm/simplex/canonical.py", "src/g1swarm/simplex/structural_guard.py",
             "src/g1swarm/mission/ir.py", "src/g1swarm/mission/validator.py",
             "src/g1swarm/authority_mechanism_001/contract.py",
             "scripts/authority_mechanism_001/run_offline.py",
             "tests/authority_mechanism_001/test_contract.py",
             "experiments/phase2/authority_mechanism_001/protocol.json",
             "experiments/phase2/long_horizon_language_001/ood/guard_ood_dataset.jsonl"}
    paths.update("src/g1swarm/language/" + name for name in
                 ("compiler.py", "grammar.lark", "normalization.py", "transformer.py", "units.py"))
    for key in (KEY_031, KEY_POSITIVE):
        paths.update((f"{V1}/samples/{key}.json", f"{DG4}/samples/{key}.json",
                      f"{DG4}/acquisition/{key}/response.json", f"{DG4}/acquisition/{key}/stage_result.json"))
    paths.update(f"{SERIAL}/samples/ood--ood-m-{suffix}.json" for suffix in ("012", "025", "031", "052", "066", "069"))
    paths.update(f"{SERIAL}/{name}" for name in ("partial_analysis.json", "partial_summary.json",
        "semantic_review.json", "report.md", "decision.json", "stop_receipt.json", "protocol.json"))
    paths.update(f"{SERIAL}/acquisition/{KEY_031}/{name}.json" for name in ("response", "stage_result"))
    paths.update(f"{DG4}/{name}" for name in ("protocol.json", "report.md", "semantic_review.json", "decision.json"))
    return sorted(paths)


def preservation_errors(protocol):
    """The new study may add files; no tracked path at the anchor may change."""
    anchor = protocol["base_commit"]
    historical = set(subprocess.check_output(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", anchor], text=True).splitlines())
    changed = set(subprocess.check_output(["git", "-C", str(ROOT), "diff", anchor, "--name-only"], text=True).splitlines())
    return sorted(historical & changed), len(historical)


def prepare():
    if (DEST / "inputs.json").exists():
        raise RuntimeError("inputs already frozen; do not silently replace a study binding")
    protocol = read(DEST / "protocol.json")
    errors, count = preservation_errors(protocol)
    if errors:
        raise RuntimeError("historical tracked paths changed: " + str(errors))
    write(DEST / "inputs.json", {"schema": "offline_mechanism_inputs_v1",
        "base_commit": protocol["base_commit"], "historical_tracked_paths": count,
        "raw_byte_bindings": {path: {"sha256": sha(ROOT / path), "bytes": (ROOT / path).stat().st_size}
                              for path in input_paths()},
        "provider_calls": 0, "runtime_calls": 0, "held_out_calls": 0})


class OfflineReplay:
    """One in-memory replay of already acquired response; no transport."""
    name = "offline-historical-response"
    model = "glm-5.3-flash"

    def __init__(self, first, raw):
        self.first, self.raw, self.calls = first, raw, 0

    def complete(self, **kwargs):
        self.calls += 1
        return LLMBackendResponse(**{**self.first, "text": self.raw})


def old_release(row, first, raw):
    result = row["B"]["result"]
    baseline = CompilerResult(CompilerStatus.SUCCESS, Mission.from_dict(result["mission"]),
                              result["normalized_text"], diagnostics=result["diagnostics"])
    replay = OfflineReplay(first, raw)
    outcome = apply_gate(row["sample"]["source"], baseline, SourceAuthorityCertificateIssuer(replay))
    assert replay.calls == 1
    return {"released": outcome.success, "reason_code": outcome.diagnostics["source_authorization"]["reason_code"],
            "in_memory_replays": replay.calls, "actual_provider_calls": 0}


def check(service, source, candidate, raw, receipt=None, **overrides):
    arguments = dict(source=source, candidate=candidate, raw_proposal=raw,
                     provider_completed=True, proposal_source_sha256=source_digest(source),
                     receipt=receipt, context_id=CONTEXT, authority=service)
    arguments.update(overrides)
    return asdict(evaluate_release(**arguments))


def run():
    protocol, inputs = read(DEST / "protocol.json"), read(DEST / "inputs.json")
    if set(inputs["raw_byte_bindings"]) != set(input_paths()):
        raise RuntimeError("input binding membership changed")
    def validate():
        errors = [path for path, binding in inputs["raw_byte_bindings"].items()
                  if sha(ROOT / path) != binding["sha256"] or (ROOT / path).stat().st_size != binding["bytes"]]
        old_changes, count = preservation_errors(protocol)
        return errors + old_changes, count
    errors, count = validate()
    if errors:
        raise RuntimeError("input/history drift: " + str(errors))
    results = []
    row = read(ROOT / f"{V1}/samples/{KEY_031}.json")
    first = read(ROOT / f"{DG4}/acquisition/{KEY_031}/response.json")
    serial = read(ROOT / f"{SERIAL}/acquisition/{KEY_031}/response.json")
    source, candidate = row["sample"]["source"], Mission.from_dict(row["B"]["result"]["mission"])
    assert row["sample"]["expected_status"] == "MALFORMED"
    assert row["sample"]["split"] == "disputed_sensitivity"
    assert first["provider_status"] == serial["provider_status"] == "completed"
    assert first["finish_reason"] == serial["finish_reason"] == "stop"
    for identifier, raw, response, expected_old, expected_reason in (
        ("actual_DG4_ood-m-031", first["text"], first, True, "AUTHORITY_UNESTABLISHED_CLARIFICATION_REQUIRED"),
        ("actual_DG_serial_ood-m-031", serial["text"], serial, False, "INVALID_PROPOSAL_CERTIFICATE"),
        ("unscored_alias_only_serial_counterfactual", serial["text"].replace('"walk"', '"walk_forward"'), serial,
         True, "AUTHORITY_UNESTABLISHED_CLARIFICATION_REQUIRED"),
    ):
        authority = AuthorityService()
        assert authority.derive_bounded_receipt(source, CONTEXT) is None
        old, new = old_release(row, response, raw), check(authority, source, candidate, raw)
        assert old["released"] is expected_old and not new["allow"] and new["reason"] == expected_reason
        results.append({"id": identifier, "evidence_kind": "UNSCORED_SYNTHETIC_COUNTERFACTUAL" if identifier.startswith("unscored")
                        else "HISTORICAL_OBSERVATION_REPLAY", "old_gate": old, "new_offline_contract": new,
                        "raw_sha256": hashlib.sha256(raw.encode("utf8")).hexdigest()})
    assert [result["id"] for result in results] == protocol["decision_critical_order"]

    # One existing positive after the three decision-critical replays.
    positive = read(ROOT / f"{V1}/samples/{KEY_POSITIVE}.json")
    positive_first = read(ROOT / f"{DG4}/acquisition/{KEY_POSITIVE}/response.json")
    positive_source = positive["sample"]["source"]
    positive_B = Mission.from_dict(positive["B"]["result"]["mission"])
    bounded = AuthorityService()
    bounded_receipt = bounded.derive_bounded_receipt(positive_source, CONTEXT)
    assert bounded_receipt is not None
    positive_result = check(bounded, positive_source, positive_B, positive_first["text"], bounded_receipt)
    assert positive_result["allow"] and positive_result["original_source_unique_under_bounded_contract"]
    results.append({"id": "existing_bounded_source_positive", "evidence_kind": "HISTORICAL_OBSERVATION_REPLAY",
                    "new_offline_contract": positive_result, "sample_key": KEY_POSITIVE})

    known = read(ROOT / f"{SERIAL}/partial_analysis.json")["known_unsafe_cases"]
    observations = [{"sample_id": item["sample_id"], "split": item["split"],
                     "historical_DG4": {name: item["arms"]["DG4"][name] for name in
                         ("usable", "taxonomy", "final_failure", "raw_false_unique_claim", "unauthorized_release")},
                     "closed_DG_serial": {name: item["arms"]["DG_serial"][name] for name in
                         ("usable", "taxonomy", "final_failure", "raw_false_unique_claim", "unauthorized_release")},
                     "new_model_semantic_observation": None} for item in known]
    closed = read(ROOT / f"{SERIAL}/decision.json")
    assert closed["status"] == "PARTIAL_STOPPED" and closed["D011"] == "BLOCKED"
    assert all(not result["new_offline_contract"]["semantic_rejection_credit"] for result in results)
    errors, count_after = validate()
    assert not errors and count_after == count
    evidence = {"schema": "offline_mechanism_results_v1", "scope": "DEVELOPMENT_MECHANISM_ONLY",
        "inputs_sha256": sha(DEST / "inputs.json"), "results_in_evaluation_order": results,
        "preserved_known_unsafe_observations": observations,
        "provider_calls": 0, "runtime_calls": 0, "held_out_calls": 0, "new_model_treatments": 0,
        "real_principal_authorizations": 0, "new_semantic_gains": 0,
        "D011": "BLOCKED", "DG_serial": "PARTIAL_STOPPED_NO_RESUME"}
    write(DEST / "offline_results.json", evidence)
    write(DEST / "integrity.json", {"status": "PASS", "input_binding_count": len(inputs["raw_byte_bindings"]),
        "raw_bindings_verified_before_and_after": True, "pre_existing_tracked_paths": count,
        "pre_existing_tracked_paths_changed_against_anchor": [],
        "old_DG4_031_replay_still_releases": True, "old_labels_and_disputed_role_unchanged": True,
        "serial_stop_and_censoring_preserved": True, "protocol_sha256": sha(DEST / "protocol.json"),
        "inputs_sha256": sha(DEST / "inputs.json"), "offline_results_sha256": sha(DEST / "offline_results.json"),
        "provider_calls": 0, "runtime_calls": 0, "held_out_calls": 0})
    print(json.dumps({"status": "PASS", "critical_replays": 3, "minimum_controls": 1,
                      "provider_calls": 0, "D011": "BLOCKED"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run"))
    mode = parser.parse_args().mode
    prepare() if mode == "prepare" else run()
