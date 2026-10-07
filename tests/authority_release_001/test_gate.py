"""Necessary integration fixtures at the real Mission-returning boundary.

All backend calls are in-memory replays/fixtures. No provider or Runtime runs.
Historical files are read only, including the actual disputed 031 release.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import pytest

from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer
from g1swarm.authority_mechanism_001.contract import AuthorityService, receipt_mac
from g1swarm.authority_release_001 import ReleaseRequestContext, begin_release_request
from g1swarm.language.errors import CompilerStatus
from g1swarm.language.result import CompilerResult
from g1swarm.llm.backend import LLMBackendResponse
from g1swarm.mission.ir import Mission
from g1swarm.source_authority import AuthorizationResult, AuthorizationStatus, apply_gate
from g1swarm.source_authority.authorization import apply_gate as direct_gate
from g1swarm.source_authority_bounded import BoundedSourceAuthorizationVerifier

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "experiments/phase2/authority_release_001"
V1 = ROOT / "experiments/phase2/source_authority_001"
DG4 = ROOT / "experiments/phase2/source_authority_cross_model_001"
SERIAL = ROOT / "experiments/phase2/source_authority_serial_001"
# Public fixture-only material, never a provider or production authority key.
TEST_KEY = b"public-offline-bounded-integration-fixture-only"
CASES = []


def read(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def historical(key="controlled--cl-a-001"):
    row = read(V1 / f"samples/{key}.json")
    result = row["B"]["result"]
    baseline = CompilerResult(CompilerStatus.SUCCESS, Mission.from_dict(result["mission"]),
                              result["normalized_text"], diagnostics=copy.deepcopy(result["diagnostics"]))
    return row["sample"]["source"], baseline, read(DG4 / f"acquisition/{key}/response.json")


class ReplayBackend:
    name = "offline-integration-fixture"
    model = "glm-5.3-flash"

    def __init__(self, first):
        self.first, self.requests = first, []

    def complete(self, **kwargs):
        self.requests.append(kwargs)
        return LLMBackendResponse(**self.first)


def run_gate(label, source, baseline, first, *, gate=apply_gate, **kwargs):
    before = copy.deepcopy(baseline.to_dict())
    backend = ReplayBackend(first)
    result = gate(source, baseline, SourceAuthorityCertificateIssuer(backend), **kwargs)
    record(label, result, backend)
    assert baseline.to_dict() == before
    return result, backend


def record(label, result, backend=None):
    proposal = result.diagnostics.get("proposal_authorization", {})
    evidence = proposal.get("diagnostics", {})
    CASES.append({"id": label, "mission_returned": result.mission is not None,
        "compiler_status": result.status.value,
        "final_authorization_status": result.diagnostics["source_authorization"]["status"],
        "final_reason": result.diagnostics["source_authorization"]["reason_code"],
        "proposal_status": proposal.get("status"), "proposal_certificate_usable": evidence.get("certificate_usable"),
        "proposal_plan_matches_B": evidence.get("plan_matches_candidate"),
        "independent_release": result.diagnostics["independent_release"],
        "clarification_required": result.diagnostics["clarification_required"],
        "fixture_backend_invocations": len(backend.requests) if backend is not None else 0,
        "actual_provider_calls": 0, "runtime_calls": 0})


@pytest.fixture(scope="session", autouse=True)
def save_minimal_evidence(tmp_path_factory):
    yield
    if CASES:
        # Regression receipts are new test output, never frozen release evidence.
        destination = tmp_path_factory.mktemp("authority_release_receipts")
        (destination / "fixture_results.json").write_text(json.dumps({
            "scope": "OFFLINE_EXISTING_EVIDENCE_AND_INTEGRATION_FIXTURES",
            "public_release_entry": "g1swarm.source_authority.apply_gate",
            "cases": CASES, "provider_calls": 0, "held_out_calls": 0,
            "runtime_calls": 0, "new_model_treatments": 0, "D011": "BLOCKED",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


@pytest.mark.parametrize("gate", [apply_gate, direct_gate], ids=["package_export", "direct_module"])
def test_actual_031_false_unique_cannot_release_at_either_public_entry(gate):
    source, baseline, first = historical("ood--ood-m-031")
    path = DG4 / "samples/ood--ood-m-031.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    observed = read(path)["dg"]
    assert observed["score"]["unauthorized_release"] is True
    result, backend = run_gate("actual_031_" + ("export" if gate is apply_gate else "direct"), source, baseline, first, gate=gate)
    assert result.mission is None
    assert result.diagnostics["proposal_authorization"]["status"] == "AUTHORIZED_UNIQUE"
    proposal = result.diagnostics["proposal_authorization"]["diagnostics"]
    assert proposal["certificate_usable"] and proposal["plan_matches_candidate"]
    assert proposal["certificate"]["checks"] == ["U"] * 7
    assert result.diagnostics["source_authorization"]["status"] == "UNKNOWN"
    assert result.diagnostics["clarification_required"]
    assert result.diagnostics["independent_release"]["semantic_rejection_credit"] is False
    assert json.loads(backend.requests[0]["user_text"]) == {"source": source}
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("correct_alias", [False, True], ids=["actual_serial", "unscored_alias_only"])
def test_serial_format_failure_is_not_the_authority_fix(correct_alias):
    source, baseline, _ = historical("ood--ood-m-031")
    first = read(SERIAL / "acquisition/ood--ood-m-031/response.json")
    if correct_alias:
        first["text"] = first["text"].replace('"walk"', '"walk_forward"')
    result, _ = run_gate("serial_031_alias_fixed" if correct_alias else "actual_serial_031", source, baseline, first)
    assert result.mission is None
    assert result.diagnostics["source_authorization"]["reason_code"] == (
        "AUTHORITY_UNESTABLISHED_CLARIFICATION_REQUIRED" if correct_alias else "INVALID_CERTIFICATE_PLAN")
    assert not result.diagnostics["independent_release"]["semantic_rejection_credit"]


@pytest.mark.parametrize("explicit", [False, True], ids=["host_default", "explicit_host_receipt"])
def test_existing_bounded_positive_releases_original_B(explicit):
    source, baseline, first = historical()
    arguments = {}
    if explicit:
        context, service = begin_release_request(source), AuthorityService()
        receipt = service.derive_bounded_receipt(source, context.context_id)
        arguments.update(request_context=context, authority_service=service,
                         authority_receipt=receipt, derive_bounded_authority=False)
    result, _ = run_gate("bounded_positive_explicit" if explicit else "bounded_positive_default", source, baseline, first, **arguments)
    assert result.success and result.mission is baseline.mission
    assert result.normalized_text == baseline.normalized_text
    assert result.diagnostics["independent_release"]["authority_origin"] == "BOUNDED_SOURCE_DERIVATION"
    assert result.diagnostics["independent_release"]["original_source_unique_under_bounded_contract"]


def test_missing_receipt_does_not_trust_inherited_release_diagnostics():
    source, baseline, first = historical()
    baseline.diagnostics.update(released_executable=True, source_authorization={"status": "AUTHORIZED_UNIQUE"})
    result, _ = run_gate("missing_receipt_despite_old_release_flags", source, baseline, first, derive_bounded_authority=False)
    assert result.mission is None and result.diagnostics["clarification_required"]


@pytest.mark.parametrize("change,reason", [
    ("mac", "UNVERIFIED_AUTHORITY_PROVENANCE"),
    ("source", "AUTHORITY_SOURCE_MISMATCH"),
    ("plan", "AUTHORITY_COMPLETE_PLAN_MISMATCH"),
    ("context", "AUTHORITY_CONTEXT_MISMATCH"),
])
def test_forged_or_authentic_mismatched_receipt_cannot_release(change, reason):
    source, baseline, first = historical()
    context = begin_release_request(source)
    service = AuthorityService(bounded_key=TEST_KEY)
    receipt = service.derive_bounded_receipt(source, context.context_id)
    if change == "mac":
        receipt["signature"] = "0" * 64
    else:
        field = {"source": "source_sha256", "plan": "plan_sha256", "context": "context_id"}[change]
        receipt[field] = "other-context" if change == "context" else "0" * 64
        body = {name: value for name, value in receipt.items() if name != "signature"}
        receipt["signature"] = receipt_mac(body, TEST_KEY)
    # Default automatic derivation must never replace an explicit bad receipt.
    result, _ = run_gate("receipt_" + change, source, baseline, first, request_context=context,
                         authority_service=service, authority_receipt=receipt)
    assert result.mission is None
    assert result.diagnostics["source_authorization"]["reason_code"] == reason


def test_context_and_receipt_replay_cannot_reset_with_a_new_service():
    source, baseline, first = historical()
    context = begin_release_request(source)
    service = AuthorityService(bounded_key=TEST_KEY)
    receipt = service.derive_bounded_receipt(source, context.context_id)
    arguments = dict(request_context=context, authority_service=service, authority_receipt=receipt)
    original, _ = run_gate("one_shot_first_release", source, baseline, first, **arguments)
    assert original.success
    arguments["authority_service"] = AuthorityService(bounded_key=TEST_KEY)
    again, backend = run_gate("replayed_context_new_service", source, baseline, first, **arguments)
    assert again.mission is None and not backend.requests
    assert again.diagnostics["source_authorization"]["reason_code"] == "REQUEST_CONTEXT_UNTRUSTED_OR_REPLAYED"
    arguments["request_context"] = begin_release_request(source)
    receipt_again, _ = run_gate("old_receipt_fresh_context", source, baseline, first, **arguments)
    assert receipt_again.mission is None
    assert receipt_again.diagnostics["source_authorization"]["reason_code"] == "AUTHORITY_CONTEXT_MISMATCH"


def test_forged_or_wrong_source_host_context_cannot_call_issuer():
    source, baseline, first = historical()
    real = begin_release_request(source)
    forged = ReleaseRequestContext(**asdict(real))
    result, backend = run_gate("copied_unregistered_context", source, baseline, first, request_context=forged)
    assert result.mission is None and not backend.requests
    wrong_source_context = begin_release_request(source + " ")
    result, backend = run_gate("wrong_source_context", source, baseline, first, request_context=wrong_source_context)
    assert result.mission is None and not backend.requests
    assert result.diagnostics["source_authorization"]["reason_code"] == "REQUEST_CONTEXT_SOURCE_MISMATCH"


def test_concurrent_replay_gets_only_one_Mission_and_one_proposal():
    source, baseline, first = historical()
    context, service = begin_release_request(source), AuthorityService()
    receipt = service.derive_bounded_receipt(source, context.context_id)
    backend = ReplayBackend(first)
    issuer = SourceAuthorityCertificateIssuer(backend)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: apply_gate(source, baseline, issuer, request_context=context,
            authority_service=service, authority_receipt=receipt), range(2)))
    assert sum(result.mission is not None for result in outcomes) == 1
    assert len(backend.requests) == 1
    for index, result in enumerate(outcomes):
        record("atomic_context_claim_" + str(index), result)


def test_custom_model_only_UNIQUE_and_fake_receipt_diagnostics_cannot_bypass():
    source, baseline, _ = historical("ood--ood-m-031")

    class SelfApproved:
        treatment = "model-self-approved-fixture"

        def authorize(self, source, candidate):
            return AuthorizationResult(AuthorizationStatus.AUTHORIZED_UNIQUE, "MODEL_APPROVED", {
                "authority_origin": "BOUNDED_SOURCE_DERIVATION", "human_approved": True,
                "independent_release": {"allow": True}, "released_executable": True})

    result = apply_gate(source, baseline, SelfApproved())
    record("model_only_self_approved", result)
    assert result.mission is None
    assert result.diagnostics["source_authorization"]["reason_code"] == "V2_PROPOSAL_OR_BOUNDED_DERIVATION_REQUIRED"


@pytest.mark.parametrize("failure", ["guard", "illegal_B", "missing_B", "proposal_disagreement"])
def test_existing_preconditions_still_control_Mission(failure):
    source, baseline, first = historical()
    if failure == "guard":
        source = "然后前进6米"
    elif failure == "illegal_B":
        document = baseline.mission.to_dict()
        document["steps"][0]["parameters"]["duration_s"] = -1
        baseline = CompilerResult(CompilerStatus.SUCCESS, Mission.from_dict(document))
    elif failure == "missing_B":
        baseline = CompilerResult(CompilerStatus.SUCCESS)
    else:
        first["text"] = json.dumps({"status": "AUTHORIZED_UNIQUE", "checks": ["U"] * 7,
                                   "plan": [["stop"]], "issues": []})
    result, backend = run_gate("precondition_" + failure, source, baseline, first)
    assert result.mission is None
    assert len(backend.requests) == int(failure == "proposal_disagreement")


def test_candidate_blind_provider_request_and_exact_comparison_unchanged():
    source, baseline, first = historical()
    correct, a = run_gate("blind_request_correct_B", source, baseline, first)
    document = baseline.mission.to_dict()
    document["steps"][0]["parameters"]["duration_s"] = 3
    wrong = CompilerResult(CompilerStatus.SUCCESS, Mission.from_dict(document))
    rejected, b = run_gate("blind_request_wrong_B", source, wrong, first)
    assert correct.mission is baseline.mission and rejected.mission is None
    assert a.requests == b.requests
    assert json.loads(a.requests[0]["user_text"]) == {"source": source}


def test_existing_bounded_only_control_requires_same_independent_receipt():
    source, baseline, _ = historical()
    result = apply_gate(source, baseline, BoundedSourceAuthorizationVerifier())
    record("existing_deterministic_bounded_control", result)
    assert result.success and result.mission is baseline.mission
    assert result.diagnostics["independent_release"]["authority_origin"] == "BOUNDED_SOURCE_DERIVATION"
