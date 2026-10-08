"""TEST_ONLY principal capabilities at both public boundaries; no provider/Runtime."""
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import replace
import hashlib
import json

import pytest

from g1swarm.authority_release_001 import begin_release_request
from g1swarm.authority_release_001.gate import claim_request
from g1swarm.human_principal_001 import TestPrincipalAuthority
from g1swarm.language.errors import CompilerStatus
from g1swarm.language.result import CompilerResult
from g1swarm.mission.ir import Mission
from g1swarm.source_authority import apply_gate
from g1swarm.source_authority.authorization import apply_gate as direct_gate
from g1swarm.source_authority_bounded import BoundedSourceAuthorizationVerifier
from g1swarm.authority_mechanism_001.contract import (
    AuthorityService, Origin, SCOPES, VERSION, plan_digest, receipt_mac, source_digest,
)

SOURCE = "向前走一些，然后停下来"


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class TrapAuthorizer:
    treatment = "TEST_ONLY_NEVER_INVOKED"

    def authorize(self, *args, **kwargs):
        raise AssertionError("human release must never consult model/source authorizer")


def mission():
    return Mission.from_dict({"schema_version": "2.0.0", "mission_id": "test-only-human-plan",
        "steps": [{"id": "s1", "skill": "stand", "parameters": {}},
                  {"id": "s2", "skill": "walk_forward", "parameters": {"distance_m": 8.0}, "depends_on": ["s1"]},
                  {"id": "s3", "skill": "stop", "parameters": {}, "depends_on": ["s2"]}]})


def bundle(*, source=SOURCE, ttl=120):
    clock = FakeClock()
    authority = TestPrincipalAuthority(clock=clock)
    session = authority.create_test_session("alice", ttl_s=300)
    context = begin_release_request(source)
    baseline = CompilerResult(CompilerStatus.SUCCESS, mission(), source)
    offer = authority.present(source, baseline.mission, context, session, ttl_s=ttl)
    response = authority.respond(session, offer, displayed_sha256=offer.display_sha256, action="CONFIRM")
    return clock, authority, session, context, baseline, offer, response


def release(data, *, gate=apply_gate, source=SOURCE, **overrides):
    _, authority, _, context, baseline, _, response = data
    kwargs = dict(request_context=context, principal_authority=authority,
                  principal_confirmation=response, allow_test_principal=True)
    kwargs.update(overrides)
    return gate(source, baseline, TrapAuthorizer(), **kwargs)


@pytest.mark.parametrize("gate", [apply_gate, direct_gate])
def test_explicit_new_instruction_releases_original_b_without_claiming_source_uniqueness(gate):
    data = bundle()
    before = copy.deepcopy(data[4].to_dict())
    result = release(data, gate=gate)
    assert result.success and result.mission is data[4].mission
    assert data[4].to_dict() == before
    decision = result.diagnostics["independent_release"]
    assert decision["explicit_new_plan_instruction"] is True
    assert decision["original_source_unique_under_bounded_contract"] is False
    assert result.diagnostics["source_authorization"]["status"] == "UNKNOWN"
    assert result.diagnostics["production_authority_established"] is False
    assert result.diagnostics["runtime_authorized"] is False
    assert result.diagnostics["principal_identity_assurance"] == "TEST_ONLY_SIMULATED_PRINCIPAL"
    assert decision["provider_calls"] == decision["runtime_calls"] == 0


def test_presentation_contains_complete_plan_and_explicit_defaults():
    data = bundle()
    payload = json.loads(data[5].display_text)
    shown = payload["canonical_mission"]
    assert shown["mission_id"] == data[4].mission.mission_id
    assert [s["id"] for s in shown["steps"]] == ["s1", "s2", "s3"]
    assert shown["steps"][1]["parameters"] == {"distance_m": 8.0}
    assert shown["steps"][1]["depends_on"] == ["s1"]
    assert payload["implicit_stand_defaults"] == [{"step_id": "s1", "duration_s": 2.0}]
    assert payload["source"] == SOURCE
    assert payload["principal_id"] == "alice"
    assert "NEW instruction" in payload["instruction"]
    assert data[5].display_sha256 == hashlib.sha256(data[5].display_text.encode("utf8")).hexdigest()


@pytest.mark.parametrize("gate", [apply_gate, direct_gate])
@pytest.mark.parametrize("enabled", [False, None, 1, "true"])
def test_fixture_capability_never_enables_production_default(gate, enabled):
    assert release(bundle(), gate=gate, allow_test_principal=enabled).mission is None


@pytest.mark.parametrize("response", [None, {}, True, "CONFIRM"])
def test_missing_or_forged_confirmation_does_not_fallback(response):
    data = bundle(source="站立3秒，然后前进6米")
    result = release(data, source="站立3秒，然后前进6米", principal_confirmation=response)
    assert result.mission is None
    if response is None:
        assert result.status == CompilerStatus.AMBIGUOUS
        assert result.diagnostics["clarification_required"]


@pytest.mark.parametrize("part", ["session", "presentation", "confirmation", "context"])
def test_copied_capability_is_not_trusted(part):
    data = bundle()
    _, service, session, context, _, offer, response = data
    if part == "session":
        with pytest.raises(ValueError):
            service.respond(replace(session), offer, displayed_sha256=offer.display_sha256, action="REFUSE")
    elif part == "presentation":
        with pytest.raises(ValueError):
            service.respond(session, replace(offer), displayed_sha256=offer.display_sha256, action="REFUSE")
    else:
        kwargs = {"principal_confirmation": replace(response)} if part == "confirmation" else {"request_context": replace(context)}
        assert release(data, **kwargs).mission is None


@pytest.mark.parametrize("change", ["mission_id", "parameter", "order", "dependency", "step_id"])
def test_any_semantic_plan_change_invalidates_confirmation(change):
    data = bundle()
    document = data[4].mission.to_dict()
    if change == "mission_id": document["mission_id"] = "different-mission"
    if change == "parameter": document["steps"][1]["parameters"]["distance_m"] = 7.0
    if change == "order": document["steps"] = list(reversed(document["steps"]))
    if change == "dependency": document["steps"][2]["depends_on"] = ["s1"]
    if change == "step_id":
        document["steps"][2]["id"] = "other-stop"
    modified = list(data)
    modified[4] = replace(data[4], mission=Mission.from_dict(document))
    assert release(modified).mission is None


def test_source_and_request_context_are_bound():
    assert release(bundle(), source=SOURCE + "。 ").mission is None
    data = bundle()
    assert release(data, request_context=begin_release_request(SOURCE)).mission is None


def test_cross_service_and_other_same_principal_session_refuse():
    data = bundle()
    other = TestPrincipalAuthority(clock=data[0])
    assert release(data, principal_authority=other).mission is None
    data = bundle()
    session2 = data[1].create_test_session("alice")
    with pytest.raises(ValueError):
        data[1].respond(session2, data[5], displayed_sha256=data[5].display_sha256, action="REFUSE")


@pytest.mark.parametrize("action", ["REFUSE", "MODIFY", "CLARIFY"])
def test_cancel_after_confirmation_invalidates_old_consent_and_returns_no_mission(action):
    data = bundle()
    response = data[1].respond(data[2], data[5], displayed_sha256=data[5].display_sha256, action=action)
    assert release(data).mission is None
    data = bundle()
    response = data[1].respond(data[2], data[5], displayed_sha256=data[5].display_sha256, action=action)
    result = release(data, principal_confirmation=response)
    assert result.mission is None
    if action in {"MODIFY", "CLARIFY"}:
        assert result.status == CompilerStatus.AMBIGUOUS
        assert result.diagnostics["clarification_required"]


def test_revision_invalidates_prior_confirm_even_for_identical_plan():
    data = bundle()
    revised = data[1].present(SOURCE, data[4].mission, data[3], data[2])
    assert revised.revision == data[5].revision + 1
    assert release(data).mission is None


@pytest.mark.parametrize("time", [220.0, 400.0, 99.0, float("nan"), float("inf"), True])
def test_expiry_clock_rollback_and_nonfinite_clock_fail_closed(time):
    data = bundle()
    data[0].now = time
    assert release(data).mission is None


def test_revoked_principal_refuses():
    data = bundle()
    data[1].revoke_session(data[2])
    assert release(data).mission is None


def test_replay_and_atomic_concurrent_release():
    data = bundle()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: release(data), range(4)))
    assert sum(result.success for result in results) == 1
    assert release(data).mission is None


@pytest.mark.parametrize("action", [True, 1, None, "yes", "confirm", " CONFIRM "])
def test_confirmation_is_explicit_not_truthy_or_model_yes(action):
    data = bundle()
    with pytest.raises(ValueError):
        data[1].respond(data[2], data[5], displayed_sha256=data[5].display_sha256, action=action)


def test_display_mismatch_refuses_and_double_confirm_refuses():
    data = bundle()
    with pytest.raises(ValueError):
        data[1].respond(data[2], data[5], displayed_sha256="0" * 64, action="REFUSE")
    with pytest.raises(ValueError):
        data[1].respond(data[2], data[5], displayed_sha256=data[5].display_sha256, action="CONFIRM")


@pytest.mark.parametrize("ttl", [0, -1, 301, float("nan"), float("inf"), True])
def test_bad_capability_lifetime_rejected(ttl):
    service = TestPrincipalAuthority(clock=FakeClock())
    with pytest.raises(ValueError):
        service.create_test_session("alice", ttl_s=ttl)


@pytest.mark.parametrize("gate", [apply_gate, direct_gate])
def test_old_fixture_mac_is_not_public_human_authentication_but_frozen_lowlevel_contract_remains(gate):
    source = "站立3秒，然后前进6米"
    authorizer = BoundedSourceAuthorizationVerifier()
    baseline = authorizer.compiler.compile(source)
    assert baseline.success
    context = begin_release_request(source)
    key = b"TEST_ONLY_PUBLIC_FIXTURE_PRINCIPAL_KEY_32_BYTES"
    service = AuthorityService(principal_verification_key=key)
    body = dict(version=VERSION, origin=Origin.PRINCIPAL.value,
                scope=SCOPES[Origin.PRINCIPAL], source_sha256=source_digest(source),
                plan_sha256=plan_digest(baseline.mission), context_id=context.context_id,
                nonce="1234567890abcdef" * 2, ruleset_sha256=None)
    receipt = {**body, "signature": receipt_mac(body, key)}
    result = gate(source, baseline, authorizer, request_context=context,
                  authority_service=service, authority_receipt=receipt)
    assert result.mission is None
    assert result.diagnostics["independent_release"]["reason"] == "PRINCIPAL_CONFIRMATION_CHANNEL_REQUIRED"
    independent_fixture_service = AuthorityService(principal_verification_key=key)
    decision = independent_fixture_service._verify_and_consume(receipt, source, baseline.mission, context.context_id)
    assert decision.allow and decision.explicit_new_plan_instruction
    assert not decision.original_source_unique_under_bounded_contract


@pytest.mark.parametrize("part,field,value", [
    ("session", "principal_id", "forged-admin"),
    ("session", "expires_at", 1000000.0),
    ("presentation", "display_text", "{}"),
    ("presentation", "expires_at", 1000000.0),
    ("presentation", "mission_sha256", "0" * 64),
    ("confirmation", "principal_id", "forged-admin"),
    ("confirmation", "action", "REFUSE"),
    ("confirmation", "expires_at", 1000000.0),
    ("confirmation", "mission_sha256", "0" * 64),
    ("confirmation", "display_sha256", "0" * 64),
])
def test_same_registered_object_with_tampered_sealed_body_refuses(part, field, value):
    data = bundle()
    capability = {"session": data[2], "presentation": data[5], "confirmation": data[6]}[part]
    # Frozen dataclasses prevent ordinary assignment, but are not a trust boundary.
    object.__setattr__(capability, field, value)
    assert release(data).mission is None


@pytest.mark.parametrize("action", ["REFUSE", "MODIFY", "CLARIFY"])
def test_withdrawal_after_context_claim_before_verification_wins_deterministically(action):
    data = bundle()
    _, service, session, context, baseline, presentation, prior_confirmation = data
    claimed, failure = claim_request(SOURCE, context)
    assert failure is None and claimed is context
    withdrawal = service.respond(session, presentation,
                                 displayed_sha256=presentation.display_sha256, action=action)
    assert withdrawal.action == action
    decision, _ = service.verify_and_consume(SOURCE, baseline.mission, claimed, prior_confirmation)
    assert not decision.allow
    assert decision.reason == "PRINCIPAL_CONFIRMATION_REVOKED_OR_CONSUMED"
