"""Read-only independent audit of source-authority Pilot evidence.

No provider/compiler invocation, no Runtime execution, no evidence rewriting.
Partial collection is explicitly incomplete. Provider-document token usage is
audited even when the backend returned no assistant text and saved an error.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from typing import Any

import yaml

from g1swarm.mission.ir import Mission
from g1swarm.mission.validator import MissionValidator
from g1swarm.language.normalization import normalize_text
from g1swarm.simplex.canonical import canonical_document
from g1swarm.simplex.structural_guard import StructuralGuard

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = "experiments/phase2/source_authority_001"
ANCHOR = "624c8024c6587f7c502b1cc87b2b27797493af03"
OLD = "experiments/phase2/long_horizon_language_001"
DIMENSIONS = {
    "action_multiplicity", "action_order", "correction_scope", "repetition_scope",
    "reference_resolution", "temporal_relations", "unresolved_relations",
}
POPULATION_COUNTS = {"ood": 160, "phase22b": 179, "controlled": 189}
TREATMENTS = ("ambiguity", "source_verifier")


def read(path: Path) -> Any:
    return json.loads(path.read_bytes())


def sha(raw: bytes | str) -> str:
    return hashlib.sha256(raw.encode("utf-8") if isinstance(raw, str) else raw).hexdigest()


def key(sample: dict[str, Any]) -> str:
    return f"{sample['population']}--{sample['sample_id']}"


def mission_shape(document: dict[str, Any] | None, *, positional: bool = False) -> Any:
    """Independent implementation of the frozen scorer's declared comparison."""
    if document is None:
        return None
    steps = []
    for index, step in enumerate(document["steps"], 1):
        steps.append({
            "id": str(step.get("id", f"s{index}")),
            "skill": str(step["skill"]),
            "parameters": {
                name: float(value) if isinstance(value, (float, int)) else value
                for name, value in sorted(step.get("parameters", {}).items())
            },
            "depends_on": [str(dep) for dep in step.get("depends_on", [])],
        })
    if positional:
        positions = {step["id"]: index for index, step in enumerate(steps)}
        steps = [
            {"skill": step["skill"], "parameters": step["parameters"],
             "depends_on": sorted(positions[dep] for dep in step["depends_on"])}
            for step in steps
        ]
    return {"schema_version": document.get("schema_version", "2.0.0"), "steps": steps}


def independent_score(sample: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    released = result["status"] == "SUCCESS" and result.get("mission") is not None
    valid = sample["expected_status"] == "SUCCESS"
    exact = bool(valid and released and
        mission_shape(result["mission"], positional=sample["population"] == "ood") ==
        mission_shape(sample["expected_mission"], positional=sample["population"] == "ood"))
    return {"released": released, "valid_exact": exact,
            "unauthorized_release": bool(released and (not valid or not exact)),
            "false_rejection": bool(valid and not released),
            "wrong_ir": bool(valid and released and not exact), "status": result["status"]}


def legal(document: dict[str, Any] | None) -> bool:
    try:
        parsed = Mission.from_dict(document)
        return (not any(step.execution_mode_override for step in parsed.steps)
                and MissionValidator().validate(parsed).valid)
    except Exception:
        return False


def output_text(document: dict[str, Any]) -> str:
    """Extract assistant text independently, ignoring reasoning-only output."""
    pieces = []
    for item in document.get("output", []):
        if isinstance(item, dict):
            for part in item.get("content", []):
                if isinstance(part, dict) and part.get("type") in {"text", "output_text"} and isinstance(part.get("text"), str):
                    pieces.append(part["text"])
    if pieces:
        return "".join(pieces).strip()
    if isinstance(document.get("output_text"), str):
        return document["output_text"].strip()
    choices = document.get("choices", [])
    if choices and isinstance(choices[0], dict):
        value = choices[0].get("message", {}).get("content")
        if isinstance(value, str):
            return value.strip()
    return ""


def expected_request_hash(root: Path, sample: dict[str, Any], stage: str, baseline: dict[str, Any]) -> str:
    if stage == "B":
        system = (root / "prompts/llm_mission_compiler_v1.txt").read_text(encoding="utf-8")
        user = sample["source"]
    else:
        prompt = "source_authority_ambiguity_v1.txt" if stage == "ambiguity" else "source_authority_verifier_v1.txt"
        system = (root / "prompts" / prompt).read_bytes().decode("utf-8")
        payload = {"source": sample["source"]}
        if stage == "source_verifier":
            payload["candidate_ir"] = canonical_document(baseline["mission"], allow_text_numbers=False)
        user = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    payload = {"model": "deepseek-flash", "input": [
        {"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.0, "max_output_tokens": 4096, "stream": False}
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def witness_errors(sample: dict[str, Any], baseline: dict[str, Any], result: dict[str, Any], stage: str) -> list[str]:
    authority = result["diagnostics"]["source_authorization"]
    diagnostics = authority.get("diagnostics", {})
    witness = diagnostics.get("witness")
    if not witness:
        return ["AUTHORIZED_UNIQUE has no parsed full-source witness"] if authority["status"] == "AUTHORIZED_UNIQUE" else []
    errors = []
    if json.loads(diagnostics["raw_response"]) != witness:
        errors.append("parsed witness differs from saved raw assistant response")
    if "".join(segment["text"] for segment in witness["coverage"]) != sample["source"]:
        errors.append("witness omits or changes full source bytes")
    if set(witness["dimensions"]) != DIMENSIONS:
        errors.append("witness dimension inventory differs")
    states = {item["status"] for item in witness["dimensions"].values()}
    derived = "AMBIGUOUS" if "AMBIGUOUS" in states else "UNKNOWN" if "UNKNOWN" in states else "AUTHORIZED_UNIQUE"
    if witness["status"] != derived:
        if authority["status"] != "UNKNOWN" or authority["reason_code"] != "VERIFIER_STATUS_DISAGREEMENT":
            errors.append("dimension/declaration disagreement did not fail closed")
    elif derived != "AUTHORIZED_UNIQUE":
        if authority["status"] != derived:
            errors.append("nonunique witness and authorization status differ")
    elif stage == "source_verifier":
        plan = {"schema_version": "2.0.0", "mission_id": "source-authorized-plan", "steps": witness["authorized_plan"]}
        same = legal(plan) and mission_shape(plan) == mission_shape(baseline["mission"])
        if authority["status"] == "AUTHORIZED_UNIQUE" and not same:
            errors.append("released witness plan is illegal or differs from B")
        if same and authority["status"] != "AUTHORIZED_UNIQUE":
            errors.append("legal matching unique witness was recorded as nonunique")
    elif authority["status"] != "AUTHORIZED_UNIQUE":
        errors.append("unique source-only witness was recorded as nonunique")
    return errors


def row_errors(row: dict[str, Any], sample: dict[str, Any], index: int) -> list[str]:
    errors = []
    if row["sample"] != sample:
        errors.append("source, label, or oracle differs from frozen input")
    order = list(TREATMENTS) if index % 2 == 0 else list(reversed(TREATMENTS))
    if row.get("gate_order") != order or set(row["treatments"]) != set(TREATMENTS):
        errors.append("treatment membership or fixed acquisition order differs")
    baseline = row["B"]["result"]
    guard = StructuralGuard().check(sample["source"])
    executable = baseline["status"] == "SUCCESS" and legal(baseline.get("mission"))
    if baseline["status"] == "SUCCESS" and (not executable or not guard.passed):
        errors.append("B released an illegal or Guard-rejected candidate")
    if sample.get("baseline_recorded") is not None:
        if baseline != sample["baseline_recorded"] or row["baseline_kind"] != "historical_B_raw_replay_verified":
            errors.append("historical B result was changed")
    elif row.get("baseline_kind") != "new_frozen_B_first_response":
        errors.append("regression B acquisition kind differs from first-response protocol")
    for stage, output in [("B", row["B"]), *row["treatments"].items()]:
        result = output["result"]
        if output["score"] != independent_score(sample, result):
            errors.append(f"{stage}: stored score differs from independent scoring")
        if result["status"] != "SUCCESS" and result.get("mission") is not None:
            errors.append(f"{stage}: rejected result retains executable Mission")
        if result["status"] == "SUCCESS" and result.get("mission") is None:
            errors.append(f"{stage}: SUCCESS has no Mission")
        if stage == "B":
            continue
        diagnostics = result["diagnostics"]
        authority = diagnostics["source_authorization"]
        predicate = guard.passed and executable and authority["status"] == "AUTHORIZED_UNIQUE"
        expected_calls = int(guard.passed and executable)
        if output["live_evidence"]["provider_calls"] != expected_calls:
            errors.append(f"{stage}: gate call count differs from executable B candidate policy")
        if expected_calls and authority.get("diagnostics", {}).get("source_sha256") != sha(sample["source"]):
            errors.append(f"{stage}: authorization source SHA differs")
        if (result["status"] == "SUCCESS") != predicate or diagnostics.get("released_executable") != predicate:
            errors.append(f"{stage}: release predicate differs")
        if diagnostics.get("release_guard") != guard.to_dict():
            errors.append(f"{stage}: recorded Guard verdict differs")
        if predicate and result["mission"] != baseline["mission"]:
            errors.append(f"{stage}: authorized executable candidate changed from B")
        if authority["status"] in {"UNKNOWN", "AMBIGUOUS"} and result.get("mission") is not None:
            errors.append(f"{stage}: nonunique authorization retains executable Mission")
        if executable and guard.passed:
            validation = MissionValidator().validate(Mission.from_dict(baseline["mission"])).to_dict()
            if diagnostics.get("release_validation") != validation:
                errors.append(f"{stage}: recorded IR legality differs")
        errors.extend(f"{stage}: {message}" for message in witness_errors(sample, baseline, result, stage))
    return errors


def stage_audit(directory: Path, *, expected_hash: str | None, partial: bool) -> dict[str, Any]:
    errors = []
    begins = [read(path) for path in sorted(directory.glob("attempt-*-begin.json"))]
    ends = [read(path) for path in sorted(directory.glob("attempt-*-end.json"))]
    receipt = read(directory / "stage_result.json") if (directory / "stage_result.json").exists() else None
    response = read(directory / "response.json") if (directory / "response.json").exists() else None
    if not (directory / "started.json").exists():
        errors.append("stage has no first-call marker")
    if [event["index"] for event in begins] != list(range(1, len(begins) + 1)) or len(begins) > 3:
        errors.append("attempt begins are noncontiguous or exceed frozen transport budget")
    by_index = {event["index"]: event for event in begins}
    if len(by_index) != len(begins) or len({event["index"] for event in ends}) != len(ends):
        errors.append("duplicate attempt ledger indexes")
    first_success = next((event for event in ends if event["status"] == "SUCCESS"), None)
    if first_success and any(event["index"] > first_success["index"] for event in begins):
        errors.append("provider call continued after first semantic response")
    for event in ends:
        begin = by_index.get(event["index"])
        if begin is None or begin["request_sha256"] != event["request_sha256"]:
            errors.append("attempt end has no matching request begin")
        if event["status"] == "SUCCESS" and not isinstance(event.get("provider_document"), dict):
            errors.append("successful transport has no provider response document")
        if event["index"] > 1:
            prior = next((item for item in ends if item["index"] == event["index"] - 1), None)
            if prior is not None and prior["status"] not in {"TIMEOUT", "API_ERROR"}:
                errors.append("transport retry followed a non-retryable failure class")
            if prior is not None and prior.get("http_status") is not None and prior["http_status"] not in {429, 500, 502, 503, 504}:
                errors.append("transport retry followed an HTTP status outside frozen policy")
    if expected_hash and any(event["request_sha256"] != expected_hash for event in begins):
        errors.append("request hash differs from exact source/prompt/candidate request")
    if response and "text" in response:
        if first_success is None or output_text(first_success.get("provider_document", {})) != response["text"]:
            errors.append("saved assistant text differs from first successful provider document")
        if first_success and response["attempts"] != first_success["index"]:
            errors.append("response attempt count differs from first response index")
    elif response and first_success and output_text(first_success.get("provider_document", {})):
        errors.append("backend error was saved despite assistant text in first response")
    if receipt:
        evidence = receipt["live_evidence"]
        if evidence["provider_calls"] not in (0, 1) or evidence["provider_attempts"] != len(begins):
            errors.append("stage call/attempt count differs from ledger")
        if evidence["events"] != ends or evidence["responses"] != ([response] if response is not None else []):
            errors.append("stage receipt differs from immutable attempt/response files")
        if bool(begins) != bool(evidence["provider_calls"]):
            if not evidence.get("interrupted_response_unavailable"):
                errors.append("semantic call count inconsistent with transport ledger")
        result = receipt["result"]
        diagnostics = result["diagnostics"].get("source_authorization", {}).get("diagnostics", result["diagnostics"])
        if response and "text" in response:
            if diagnostics.get("raw_response_sha256") != sha(response["text"]):
                errors.append("diagnostic raw assistant SHA-256 differs")
            if "raw_response" in diagnostics and diagnostics["raw_response"] != response["text"]:
                errors.append("diagnostic raw assistant text differs")
        if receipt.get("recovered") and receipt.get("added_wall_s") is not None:
            errors.append("recovery duration was presented as original live latency")
    elif not partial:
        errors.append("stage acquisition is incomplete")
    unmatched = len(begins) - len(ends)
    if unmatched and receipt and not receipt.get("recovered"):
        errors.append("completed non-recovered stage retains unmatched transport attempt")
    documents = [event["provider_document"] for event in ends if isinstance(event.get("provider_document"), dict)]
    total_tokens = sum(doc.get("usage", {}).get("total_tokens", 0) or 0 for doc in documents)
    response_tokens = (response or {}).get("usage", {}).get("total_tokens", 0) if isinstance((response or {}).get("usage"), dict) else 0
    return {"errors": errors, "complete": receipt is not None, "transport_attempts": len(begins),
            "unmatched_transport_attempts": unmatched, "provider_document_tokens": total_tokens,
            "backend_response_tokens": response_tokens or 0,
            "provider_document_count": len(documents),
            "empty_assistant_documents": sum(not output_text(doc) for doc in documents),
            "incomplete_provider_documents": sum(doc.get("status") == "incomplete" for doc in documents),
            "output_budget_documents": sum(doc.get("incomplete_details", {}).get("reason") == "max_output_tokens" for doc in documents)}


def anchor_blob(root: Path, name: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), "show", f"{ANCHOR}:{name}"], stderr=subprocess.DEVNULL)


def trusted_inputs(root: Path) -> list[dict[str, Any]]:
    result = []
    ood = json.loads(anchor_blob(root, f"{OLD}/session4/ood_full_system_results.json"))["records"]
    for row in ood:
        result.append({"sample_id": row["sample_id"], "population": "ood", "split": row["split"],
            "family": row["author_phenomenon_group"], "source": row["utterance"],
            "expected_status": row["expected_status"], "expected_mission": row.get("oracle_mission"),
            "baseline_recorded": row["result"], "baseline_semantic_outcome": row["semantic_outcome"]})
    for population, path in [("phase22b", "experiments/phase2/simplex_compiler_001/fresh_blind_set.yaml"),
                             ("controlled", "configs/language/controlled_language_001.yaml")]:
        for row in yaml.safe_load(anchor_blob(root, path))["samples"]:
            result.append({"sample_id": row["sample_id"], "population": population, "split": "already_seen_regression",
                "family": row["category"], "source": row["utterance"],
                "expected_status": row["expected_compiler_status"], "expected_mission": row.get("expected_mission"),
                "baseline_recorded": None})
    return result


def bounded_control_audit(root: Path, expected: list[dict[str, Any]]) -> dict[str, Any]:
    """Audit stored post-hoc control links and predicates; never rerun its parser."""
    base = root / EXPERIMENT
    document = read(base / "bounded_control.json")
    errors = []
    samples = {key(sample): sample for sample in expected}
    records = document["records"]
    identities = [f"{row['population']}--{row['sample_id']}" for row in records]
    if len(identities) != 528 or len(set(identities)) != 528 or set(identities) != set(samples):
        errors.append("bounded control does not contain exact unique 528 membership")
    if document.get("evidence_role") != "post_hoc_exploratory_bounded_control":
        errors.append("bounded control lost its post-hoc evidence classification")
    scores = Counter()
    statuses = Counter()
    for identity, control in zip(identities, records):
        if identity not in samples:
            continue
        sample = samples[identity]
        original_path = base / "samples" / f"{identity}.json"
        if control["baseline_evidence_sha256"] != sha(original_path.read_bytes()):
            errors.append(f"{identity}: bounded control baseline byte-hash link differs")
        original = read(original_path)
        baseline = original["B"]["result"]
        result = control["result"]
        score = independent_score(sample, result)
        if score != control["score"]:
            errors.append(f"{identity}: bounded score differs from independent scoring")
        for field, value in score.items():
            if isinstance(value, bool):
                scores[field] += value
        if control["live_evidence"] != {"provider_calls": 0, "provider_attempts": 0, "events": [], "responses": []}:
            errors.append(f"{identity}: bounded control unexpectedly used provider calls")
        diagnostics = result["diagnostics"]
        authority = diagnostics["source_authorization"]
        evidence = authority.get("diagnostics", {})
        guard = StructuralGuard().check(sample["source"])
        candidate_legal = baseline["status"] == "SUCCESS" and legal(baseline.get("mission"))
        predicate = guard.passed and candidate_legal and authority["status"] == "AUTHORIZED_UNIQUE"
        if (result["status"] == "SUCCESS") != predicate or diagnostics.get("released_executable") != predicate:
            errors.append(f"{identity}: bounded release predicate differs")
        if diagnostics.get("release_guard") != guard.to_dict():
            errors.append(f"{identity}: bounded Guard verdict differs")
        if not predicate and result.get("mission") is not None:
            errors.append(f"{identity}: bounded nonunique result retains executable Mission")
        if predicate and result.get("mission") != baseline.get("mission"):
            errors.append(f"{identity}: bounded executable candidate changed from B")
        status = "NOT_EVALUATED" if authority.get("reason_code") in {"GUARD_REJECT", "NO_LEGAL_CANDIDATE"} else authority["status"]
        statuses[status] += 1
        if candidate_legal and guard.passed:
            source_witness = evidence.get("source_witness", {})
            if source_witness != {"text": sample["source"], "sha256": sha(sample["source"]), "characters": len(sample["source"])}:
                errors.append(f"{identity}: bounded full-source byte-hash witness differs")
            normalized = normalize_text(sample["source"])
            normalized_witness = evidence.get("normalized_source_witness", {})
            if (normalized_witness.get("text") != normalized or normalized_witness.get("sha256") != sha(normalized)
                    or normalized_witness.get("characters") != len(normalized)):
                errors.append(f"{identity}: bounded normalized-source witness differs")
        if predicate:
            plan = evidence.get("authorized_plan")
            parsed_plan = dict(plan or {}, mission_id="bounded-checked-plan")
            if not legal(parsed_plan) or mission_shape(plan) != mission_shape(baseline["mission"]):
                errors.append(f"{identity}: bounded authorized plan is illegal or differs from B")
            parse = evidence.get("parse_witness", {})
            tokens = parse.get("tokens", [])
            normalized = normalize_text(sample["source"])
            cursor = 0
            for token in tokens:
                if token["start"] != cursor or normalized[token["start"]:token["end"]] != token["text"]:
                    errors.append(f"{identity}: bounded parse token witness has a gap or changed span")
                cursor = token["end"]
            if (not parse.get("full_consumption") or parse.get("start") != 0 or parse.get("end") != len(normalized)
                    or cursor != len(normalized) or "".join(token["text"] for token in tokens) != normalized):
                errors.append(f"{identity}: bounded parse lacks full normalized-source consumption")
            if any(not quantity.get("contiguous") for quantity in evidence.get("quantity_normalization_witness", [])):
                errors.append(f"{identity}: bounded release retained numeric normalization loss")
    return {"status": "FAIL" if errors else "PASS", "errors": errors, "records": len(records),
        "independent_scores": dict(scores), "authorization_counts": dict(statuses),
        "provider_calls": 0, "exploratory_post_hoc": True,
        "parser_rerun": False,
        "old_language_worktree_byte_pins_reasserted": False,
        "note": "Old language semantic preservation uses Git anchor checks; recorded worktree hashes are retained as provenance, not cross-checkout byte pins."}


def validate(root: Path = ROOT, *, partial: bool = False, bounded: bool = False) -> dict[str, Any]:
    base = root / EXPERIMENT
    issues = []
    inputs = read(base / "inputs.json")
    expected = inputs["populations"]
    if inputs.get("anchor") != ANCHOR or expected != trusted_inputs(root):
        issues.append("frozen input source/label/oracle differs from trusted audit Git blobs")
    counts = dict(Counter(sample["population"] for sample in expected))
    expected_by_key = {key(sample): (index, sample) for index, sample in enumerate(expected)}
    if counts != POPULATION_COUNTS or len(expected_by_key) != 528:
        issues.append("input membership is not exactly 160 OOD + 179 Phase 2.2b + 189 controlled")
    for path, digest in inputs["source_blobs"].items():
        if sha(anchor_blob(root, path)) != digest:
            issues.append(f"trusted input Git-blob digest differs: {path}")
    preflight = read(base / "preflight.json")
    if not preflight["pass"] or not all(preflight["checks"].values()) or len(preflight["checks"]) != 10:
        issues.append("provider preflight did not pass its ten frozen checks")
    for path, digest in preflight["acquisition_hashes"].items():
        if sha((root / path).read_bytes()) != digest:
            issues.append(f"acquisition code/input/prompt changed after preflight: {path}")
    spec = importlib.util.spec_from_file_location("source_authority_packaging_check", ROOT / "scripts/package_source_authority.py")
    packaging = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(packaging)
    try:
        packaging.preserved_baseline(root)
        baseline_preserved = True
    except Exception as error:
        baseline_preserved = False
        issues.append(f"immutable baseline preservation failed: {error}")
    rows = [read(path) for path in sorted((base / "samples").glob("*.json"))]
    observed = [key(row["sample"]) for row in rows]
    if len(observed) != len(set(observed)) or not set(observed).issubset(expected_by_key):
        issues.append("sample membership repeats or contains an unexpected sample")
    missing = sorted(set(expected_by_key).difference(observed))
    if missing and not partial:
        issues.append(f"final campaign incomplete: {len(missing)} of 528 samples missing")
    scores = {name: Counter() for name in ("B", *TREATMENTS)}
    authorities = {name: Counter() for name in TREATMENTS}
    stage_totals = {name: Counter() for name in ("B", *TREATMENTS)}
    examined = set()
    for row in rows:
        identity = key(row["sample"])
        if identity not in expected_by_key:
            continue
        index, sample = expected_by_key[identity]
        issues.extend(f"{identity}: {error}" for error in row_errors(row, sample, index))
        for name, output in [("B", row["B"]), *row["treatments"].items()]:
            score = independent_score(sample, output["result"])
            for field, value in score.items():
                if isinstance(value, bool):
                    scores[name][field] += value
            if name != "B":
                authority = output["result"]["diagnostics"]["source_authorization"]
                status = "NOT_EVALUATED" if authority.get("reason_code") in {"GUARD_REJECT", "NO_LEGAL_CANDIDATE"} else authority["status"]
                authorities[name][status] += 1
            if name == "B" and sample.get("baseline_recorded") is not None:
                if output["live_evidence"] != {"provider_calls": 0, "provider_attempts": 0, "events": [], "responses": []}:
                    issues.append(f"{identity}: historical B unexpectedly acquired a new response")
                continue
            directory = base / "acquisition" / identity / name
            receipt_path = directory / "stage_result.json"
            if not receipt_path.exists():
                issues.append(f"{identity}/{name}: final sample missing durable stage receipt")
                continue
            receipt = read(receipt_path)
            if {k: v for k, v in output.items() if k != "score"} != receipt:
                issues.append(f"{identity}/{name}: sample evidence differs from durable stage receipt")
    for directory in sorted((base / "acquisition").glob("*/*")):
        if not directory.is_dir():
            continue
        identity, stage = directory.parent.name, directory.name
        if identity not in expected_by_key or stage not in ("B", *TREATMENTS):
            issues.append(f"unexpected acquisition stage: {identity}/{stage}")
            continue
        _, sample = expected_by_key[identity]
        baseline = sample.get("baseline_recorded")
        baseline_path = directory.parent / "B/stage_result.json"
        if baseline is None and baseline_path.exists():
            baseline = read(baseline_path)["result"]
        request_possible = stage == "B" or (baseline and baseline["status"] == "SUCCESS" and legal(baseline.get("mission")))
        expected_hash = expected_request_hash(root, sample, stage, baseline) if request_possible else None
        audited = stage_audit(directory, expected_hash=expected_hash, partial=partial)
        examined.add((identity, stage))
        issues.extend(f"{identity}/{stage}: {error}" for error in audited.pop("errors"))
        for field, value in audited.items():
            if isinstance(value, (bool, int)):
                stage_totals[stage][field] += value
    replay = read(base / "baseline_replay.json")
    raw = read(base / "session4_raw_replay.json")
    raw_by_key = {(row["campaign"], row["sample_id"]): row for row in raw["rows"]}
    trusted_history = {}
    for filename, campaign in [("ood_full_system_results.json", "guard_ood"), ("compiler_results.json", "final_compiler")]:
        document = json.loads(anchor_blob(root, f"{OLD}/session4/{filename}"))
        for row in document.get("records", document.get("samples")):
            trusted_history[(campaign, row["sample_id"])] = {
                "source": row.get("utterance", row.get("text")), "recorded_result": row["result"]}
    for identity, original in raw_by_key.items():
        if identity not in trusted_history or any(original[field] != value for field, value in trusted_history.get(identity, {}).items()):
            issues.append(f"historical raw replay differs from anchor source/result: {identity}")
    replay_members = [(row["campaign"], row["sample_id"]) for row in replay["rows"]]
    if len(raw_by_key) != 466 or len(replay_members) != 466 or len(set(replay_members)) != 466 or set(replay_members) != set(raw_by_key):
        issues.append("historical B raw replay membership differs from 160 OOD + 306 Final")
    for row in replay["rows"]:
        original = raw_by_key[(row["campaign"], row["sample_id"])]
        result = row["replayed_result"]
        recorded = original["recorded_result"]
        if (result["status"] != recorded["status"] or mission_shape(result.get("mission")) != mission_shape(recorded.get("mission")) or row["network_provider_calls"] != 0 or not row["same_status_and_ir"]):
            issues.append(f"historical replay changed B: {row['campaign']}/{row['sample_id']}")
        call = original.get("raw_call") or {}
        response = call.get("response") or {}
        if response.get("text") and sha(response["text"]) != recorded["diagnostics"].get("raw_response_sha256"):
            issues.append(f"historical raw response SHA differs: {row['campaign']}/{row['sample_id']}")
    if not replay["all_status_and_ir_match"]:
        issues.append("historical replay declared a discrepancy")
    bounded_result = bounded_control_audit(root, expected) if bounded else None
    if bounded_result:
        issues.extend(f"bounded: {error}" for error in bounded_result["errors"])
    complete = len(observed) == 528 and not missing and len(set(observed)) == 528
    return {"schema": "source_authority_evidence_validation_v1", "status": "FAIL" if issues else "PASS",
        "collection_status": "COMPLETE" if complete else "INCOMPLETE_PARTIAL",
        "final_acceptance_claim": bool(complete and not partial and not issues),
        "partial_mode": partial, "expected_samples": 528, "completed_samples": len(rows),
        "missing_sample_keys": missing, "population_counts": counts, "issues": issues,
        "baseline_anchor_preserved": baseline_preserved, "historical_replay_rows": len(replay_members),
        "independent_scores": {name: dict(value) for name, value in scores.items()},
        "authorization_counts": {name: dict(value) for name, value in authorities.items()},
        "durable_stage_metrics": {name: dict(value) for name, value in stage_totals.items()},
        "bounded_control_validation": bounded_result,
        "preflight_provider_document_tokens": sum(
            event.get("provider_document", {}).get("usage", {}).get("total_tokens", 0) or 0
            for event in preflight["provider_evidence"]["events"]),
        "failed_preflight_preserved": (base / "failed_preflight_001.json").exists(),
        "provider_recovery_preserved": (base / "provider_recovery.json").exists(),
        "unknown_resource_failure_semantic_safety_claim": False,
        "provider_calls_by_validator": 0, "runtime_calls_by_validator": 0,
        "limitations": ["Independent bookkeeping audit; shares immutable Guard and MissionValidator contracts.",
            "UNKNOWN from output-budget failure demonstrates withheld release, not semantic recognition of ambiguity.",
            "Partial mode can observe active unmatched attempt begins and never claims final acceptance.",
            "Provider-reported document totals are retained as reported, including no-assistant-text responses."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--bounded", action="store_true", help="also audit the finalized post-hoc bounded_control.json")
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    root = options.root.resolve()
    if options.output:
        output = options.output.resolve()
        if output.is_relative_to(root / EXPERIMENT):
            parser.error("write validation outputs outside the frozen experiment package")
    try:
        result = validate(root, partial=options.partial, bounded=options.bounded)
    except Exception as error:
        result = {"status": "FAIL", "validator_exception": type(error).__name__, "detail": str(error),
                  "final_acceptance_claim": False, "provider_calls_by_validator": 0, "runtime_calls_by_validator": 0}
    raw = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if options.output:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_bytes(raw.encode("utf-8"))
        print(json.dumps({key: result.get(key) for key in ["status", "collection_status", "completed_samples", "final_acceptance_claim"]}))
    else:
        print(raw)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
