"""Offline trust-boundary regressions, not new model or held-out evidence."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path

import pytest

from g1swarm.authority_certificate_v2 import certificate_plan_mission, parse_certificate
from g1swarm.authority_mechanism_001.contract import (
    AuthorityService, Origin, SCOPES, VERSION, evaluate_release,
    plan_digest, receipt_mac, source_digest,
)
from g1swarm.mission.ir import Mission

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "experiments/phase2/source_authority_001"
DG4 = ROOT / "experiments/phase2/source_authority_cross_model_001"
SERIAL = ROOT / "experiments/phase2/source_authority_serial_001"
# Public fixture material only: never use for a real authority service.
TEST_KEY = b"public-offline-principal-fixture-key-only"
CONTEXT = "offline-fixture-context"


def unique(plan):
    return json.dumps({"status": "AUTHORIZED_UNIQUE", "checks": ["U"] * 7,
                       "plan": plan, "issues": []}, ensure_ascii=False)


def mission(raw):
    return certificate_plan_mission(parse_certificate(raw))


def historical():
    row = json.loads((V1 / "samples/ood--ood-m-031.json").read_text(encoding="utf8"))
    first = json.loads((DG4 / "acquisition/ood--ood-m-031/response.json").read_text(encoding="utf8"))
    return row["sample"]["source"], Mission.from_dict(row["B"]["result"]["mission"]), first["text"]


def check(service, source, candidate, raw, receipt=None, **overrides):
    arguments = dict(source=source, candidate=candidate, raw_proposal=raw,
                     receipt=receipt, context_id=CONTEXT, authority=service,
                     provider_completed=True, proposal_source_sha256=source_digest(source))
    arguments.update(overrides)
    return evaluate_release(**arguments)


def principal_fixture(source, approved_plan, **overrides):
    body = dict(version=VERSION, origin=Origin.PRINCIPAL.value,
                scope=SCOPES[Origin.PRINCIPAL], source_sha256=source_digest(source),
                plan_sha256=plan_digest(approved_plan), context_id=CONTEXT,
                nonce="0123456789abcdef" * 2, ruleset_sha256=None)
    body.update(overrides)
    return {**body, "signature": receipt_mac(body, TEST_KEY)}


def test_actual_legal_false_unique_cannot_mint_authority():
    source, candidate, raw = historical()
    assert plan_digest(mission(raw)) == plan_digest(candidate)
    service = AuthorityService()
    assert service.derive_bounded_receipt(source, CONTEXT) is None
    decision = check(service, source, candidate, raw)
    assert not decision.allow
    assert decision.reason == "AUTHORITY_UNESTABLISHED_CLARIFICATION_REQUIRED"
    assert not decision.semantic_rejection_credit


def test_serial_alias_failure_and_legal_unscored_counterfactual():
    source, candidate, _ = historical()
    raw = json.loads((SERIAL / "acquisition/ood--ood-m-031/response.json").read_text(encoding="utf8"))["text"]
    assert check(AuthorityService(), source, candidate, raw).reason == "INVALID_PROPOSAL_CERTIFICATE"
    # Local unscored fixture; never overwrite/repair the observed response.
    counterfactual = raw.replace('"walk"', '"walk_forward"')
    assert plan_digest(mission(counterfactual)) == plan_digest(candidate)
    decision = check(AuthorityService(), source, candidate, counterfactual)
    assert not decision.allow and not decision.semantic_rejection_credit
    assert decision.reason == "AUTHORITY_UNESTABLISHED_CLARIFICATION_REQUIRED"


def test_source_only_bounded_positive_and_replay():
    source, raw = "站立2秒", unique([["stand", 2]])
    service = AuthorityService()
    receipt = service.derive_bounded_receipt(source, CONTEXT)
    assert receipt is not None
    first = check(service, source, mission(raw), raw, receipt)
    assert first.allow and first.original_source_unique_under_bounded_contract
    assert not first.explicit_new_plan_instruction and not first.semantic_rejection_credit
    assert check(service, source, mission(raw), raw, receipt).reason == "AUTHORITY_RECEIPT_ALREADY_CONSUMED"


@pytest.mark.parametrize("source", ["站立2秒，其他照旧", "前进1 2米", "站立2秒；把这一步做两次", ""])
def test_full_source_and_numeric_loss_cannot_be_clipped(source):
    assert AuthorityService().derive_bounded_receipt(source, CONTEXT) is None


def test_principal_unconfigured_by_default():
    source, candidate, raw = historical()
    receipt = principal_fixture(source, candidate)
    assert check(AuthorityService(), source, candidate, raw, receipt).reason == "AUTHORITY_ORIGIN_NOT_CONFIGURED"


def test_fixture_new_complete_plan_authorization_is_not_old_source_uniqueness():
    source, candidate, raw = historical()
    service = AuthorityService(principal_verification_key=TEST_KEY)
    decision = check(service, source, candidate, raw, principal_fixture(source, candidate))
    assert decision.allow and decision.explicit_new_plan_instruction
    assert not decision.original_source_unique_under_bounded_contract
    assert not decision.semantic_rejection_credit
    assert decision.authority_scope == SCOPES[Origin.PRINCIPAL]


def test_alternate_approved_plan_does_not_replace_B():
    source, candidate, raw = historical()
    alternate = mission(unique([["stand", 1], ["stand", 1], ["turn", -45], ["stop"],
                                ["turn", -45], ["walk_forward", 8], ["walk_forward", 8]]))
    original = copy.deepcopy(candidate.to_dict())
    service = AuthorityService(principal_verification_key=TEST_KEY)
    decision = check(service, source, candidate, raw, principal_fixture(source, alternate))
    assert decision.reason == "AUTHORITY_COMPLETE_PLAN_MISMATCH"
    assert candidate.to_dict() == original


@pytest.mark.parametrize("changed,reason", [
    ({"source_sha256": "0" * 64}, "AUTHORITY_SOURCE_MISMATCH"),
    ({"plan_sha256": "0" * 64}, "AUTHORITY_COMPLETE_PLAN_MISMATCH"),
    ({"context_id": "other"}, "AUTHORITY_CONTEXT_MISMATCH"),
    ({"ruleset_sha256": "0" * 64}, "AUTHORITY_RULESET_MISMATCH"),
    ({"scope": "SOURCE_IS_UNIQUE"}, "INVALID_AUTHORITY_ENVELOPE"),
    ({"nonce": "n" * 32}, "INVALID_AUTHORITY_ENVELOPE"),
    ({"source_sha256": 123}, "INVALID_AUTHORITY_ENVELOPE"),
])
def test_even_authentic_receipt_requires_all_bindings(changed, reason):
    source, candidate, raw = historical()
    service = AuthorityService(principal_verification_key=TEST_KEY)
    assert check(service, source, candidate, raw, principal_fixture(source, candidate, **changed)).reason == reason


@pytest.mark.parametrize("change,reason", [
    ({"signature": "0" * 64}, "UNVERIFIED_AUTHORITY_PROVENANCE"),
    ({"origin": "MODEL_APPROVED"}, "UNTRUSTED_AUTHORITY_ORIGIN"),
    ({"human_approved": True}, "INVALID_AUTHORITY_ENVELOPE"),
    ({"context_id": "tampered"}, "UNVERIFIED_AUTHORITY_PROVENANCE"),
    ({"signature": "\u4e00" * 64}, "INVALID_AUTHORITY_ENVELOPE"),
])
def test_untrusted_model_claims_and_tampering_do_not_mint_authority(change, reason):
    source, candidate, raw = historical()
    service = AuthorityService(principal_verification_key=TEST_KEY)
    receipt = {**principal_fixture(source, candidate), **change}
    assert check(service, source, candidate, raw, receipt).reason == reason


@pytest.mark.parametrize("variant", ["order", "distance", "stop", "dependency", "id"])
def test_receipt_binds_complete_plan_not_repeat_and_stop_flags(variant):
    source, candidate, raw = historical()
    altered = copy.deepcopy(candidate.to_dict())
    if variant == "order":
        first, second = altered["steps"][0], altered["steps"][1]
        first["skill"], second["skill"] = second["skill"], first["skill"]
        first["parameters"], second["parameters"] = second["parameters"], first["parameters"]
    elif variant == "distance":
        altered["steps"][6]["parameters"]["distance_m"] = 7
    elif variant == "stop":
        altered["steps"][3]["skill"] = "stand"
    elif variant == "dependency":
        altered["steps"][6]["depends_on"] = ["s1"]
    else:
        altered["steps"][6]["id"] = "last"
    alternate = Mission.from_dict(altered)
    assert plan_digest(alternate) != plan_digest(candidate)
    service = AuthorityService(principal_verification_key=TEST_KEY)
    receipt = principal_fixture(source, alternate)
    assert check(service, source, candidate, raw, receipt).reason == "AUTHORITY_COMPLETE_PLAN_MISMATCH"


def test_mission_identity_is_not_plan_semantics_but_raw_source_is_bound():
    source, candidate, raw = historical()
    renamed = candidate.to_dict()
    renamed["mission_id"] = "different-evidence-name"
    assert plan_digest(Mission.from_dict(renamed)) == plan_digest(candidate)
    service = AuthorityService(principal_verification_key=TEST_KEY)
    receipt = principal_fixture(source, candidate)
    assert check(service, source + " ", candidate, raw, receipt).reason == "AUTHORITY_SOURCE_MISMATCH"


@pytest.mark.parametrize("overrides,reason", [
    ({"provider_completed": False}, "PROPOSAL_PROVIDER_UNAVAILABLE"),
    ({"provider_completed": 1}, "PROPOSAL_PROVIDER_UNAVAILABLE"),
    ({"proposal_source_sha256": "0" * 64}, "PROPOSAL_SOURCE_MISMATCH"),
    ({"context_id": ""}, "AUTHORITY_CONTEXT_MISMATCH"),
    ({"raw_proposal": "{broken"}, "INVALID_PROPOSAL_CERTIFICATE"),
])
def test_origin_receipt_does_not_bypass_proposal_boundary(overrides, reason):
    source, candidate, raw = historical()
    service = AuthorityService(principal_verification_key=TEST_KEY)
    receipt = principal_fixture(source, candidate)
    assert check(service, source, candidate, raw, receipt, **overrides).reason == reason
    # A failed precondition must not consume the otherwise valid receipt.
    assert check(service, source, candidate, raw, receipt).allow


def test_ambiguous_proposal_is_not_overridden_by_new_principal_instruction():
    source, candidate, _ = historical()
    raw = json.dumps({"status": "AMBIGUOUS", "checks": ["U"] * 6 + ["A"],
                      "plan": None, "issues": [{"relation": "unresolved", "reason": "UNRESOLVED"}]})
    service = AuthorityService(principal_verification_key=TEST_KEY)
    assert check(service, source, candidate, raw, principal_fixture(source, candidate)).reason == "PROPOSAL_NOT_UNIQUE"


def test_receipt_does_not_bypass_candidate_legality_or_disagreement():
    source, candidate, raw = historical()
    service = AuthorityService(principal_verification_key=TEST_KEY)
    receipt = principal_fixture(source, candidate)
    altered = candidate.to_dict()
    altered["steps"][2]["parameters"]["distance_m"] = -1
    assert check(service, source, Mission.from_dict(altered), raw, receipt).reason == "INVALID_CANDIDATE"
    altered["steps"][2]["parameters"]["distance_m"] = 7
    assert check(service, source, Mission.from_dict(altered), raw, receipt).reason == "PROPOSAL_CANDIDATE_DISAGREEMENT"
    altered = candidate.to_dict()
    altered["steps"][0]["execution_mode_override"] = "open_loop"
    assert check(service, source, Mission.from_dict(altered), raw, receipt).reason == "INVALID_CANDIDATE"
    assert check(service, source, candidate, raw, receipt).allow


def test_same_instance_consumption_is_atomic_but_not_a_persistence_claim():
    source, candidate, raw = historical()
    receipt = principal_fixture(source, candidate)
    service = AuthorityService(principal_verification_key=TEST_KEY)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: check(service, source, candidate, raw, receipt), range(8)))
    assert sum(decision.allow for decision in outcomes) == 1
    # This explicitly demonstrates the offline limitation after reconstruction.
    assert check(AuthorityService(principal_verification_key=TEST_KEY), source, candidate, raw, receipt).allow


@pytest.mark.parametrize("key", [b"", b"short", "x" * 32])
def test_invalid_configured_key_cannot_silently_use_default(key):
    with pytest.raises(ValueError):
        AuthorityService(bounded_key=key)
