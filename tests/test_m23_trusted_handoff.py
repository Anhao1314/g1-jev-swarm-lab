"""Frozen M2.3 interface matrix: fake sessions, zero MuJoCo execution.

Fixture SUCCESS outcomes exercise dispatch wiring only. Existing M2.2 physical
evidence is separate; these tests establish neither real controller continuity
nor concurrent or production authority guarantees.
"""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from g1swarm.mission.ir import Mission
from g1swarm.mission.trusted_handoff import (
    CONTINUATION_PERMISSION, TrustedMissionHandoff,
)
import g1swarm.mission.trusted_handoff as bridge_module
from g1swarm.trusted_handoff_v0 import (
    OfflineHandoff, TestPrincipalAuthority, begin_release_request, full_plan_json,
)
from test_m2_mission_lifecycle import NEW_MISSION, setup


SOURCE = "向前走4米，左转45度，然后停止。"


@pytest.fixture(autouse=True)
def retain_offline_gate_outcomes(monkeypatch, request):
    """Bind actual fixture refusals to the test receipt, without bearer data."""
    original_record = TrustedMissionHandoff._record
    original_prepare = TrustedMissionHandoff.prepare

    def record(self, event, payload):
        original_record(self, event, payload)
        if event in {"trusted_handoff_rejected", "trusted_handoff_dispatch_completed"}:
            summary = {"event": event, "status": payload["status"],
                       "reason": payload.get("reason"),
                       "handoff_consumption": payload["handoff_consumption"],
                       "evidence_kind": "OFFLINE_FAKE_SESSION_FIXTURE"}
            request.node.user_properties.append(("m23_gate_outcome", json.dumps(summary, sort_keys=True)))

    def prepare(self, **arguments):
        try:
            return original_prepare(self, **arguments)
        except ValueError as exc:
            request.node.user_properties.append(("m23_preparation_refusal", str(exc)))
            raise

    monkeypatch.setattr(TrustedMissionHandoff, "_record", record)
    monkeypatch.setattr(TrustedMissionHandoff, "prepare", prepare)


def _plan_hash(mission):
    return hashlib.sha256(full_plan_json(mission).encode("utf8")).hexdigest()


def fixture(grounder, tmp_path, *, permissions=None, opt_in=True):
    lifecycle, _, session, parent = setup(grounder, tmp_path)
    now = [10.0]
    authority = TestPrincipalAuthority(clock=lambda: now[0])
    handoff = OfflineHandoff()
    mission = Mission.from_dict(deepcopy(NEW_MISSION))
    if permissions is None:
        permissions = {("alice", _plan_hash(mission)): {CONTINUATION_PERMISSION}}
    bridge = TrustedMissionHandoff(
        lifecycle=lifecycle, handoff=handoff, authority=authority,
        permissions=permissions, allow_test_principal=opt_in,
    )
    return SimpleNamespace(lifecycle=lifecycle, session=session, parent=parent,
                           bridge=bridge, authority=authority, handoff=handoff,
                           mission=mission, now=now, tmp_path=tmp_path)


def approve(bundle, *, principal="alice", authority=None):
    prep = bundle.bridge.prepare(source=SOURCE, mission=bundle.mission)
    issuer = authority or bundle.authority
    login = issuer.create_test_session(principal)
    issued_plan = Mission.from_dict(json.loads(prep.canonical_mission))
    presentation = issuer.present(SOURCE, issued_plan, prep.context, login)
    confirmation = issuer.respond(login, presentation,
                                  displayed_sha256=presentation.display_sha256,
                                  action="CONFIRM")
    grant = bundle.handoff.authorize(
        source=SOURCE, mission=issued_plan, context=prep.context,
        authority=issuer, confirmation=confirmation, allow_test_principal=True,
    )
    bundle.preparation, bundle.login = prep, login
    bundle.presentation, bundle.confirmation, bundle.grant = presentation, confirmation, grant
    return bundle


def dispatch(bundle, **changes):
    arguments = dict(preparation=bundle.preparation, grant=bundle.grant,
                     source=SOURCE, mission=bundle.mission,
                     context=bundle.preparation.context, confirmation=bundle.confirmation)
    arguments.update(changes)
    return bundle.bridge.dispatch(**arguments)


def unchanged_snapshot(bundle):
    lifecycle = bundle.bridge.lifecycle
    # allow_nan here only records invalid synthetic fixture states for unchanged
    # comparisons. Production canonicalization continues rejecting nonfinite data.
    return json.dumps({
        "calls": lifecycle.session.calls, "steps": lifecycle.session.total_steps,
        "state": lifecycle.session.get_robot_state().to_dict(),
        "execution": lifecycle._execution_snapshot(),
        "parent": lifecycle._parent_result.to_dict(),
        "graph": lifecycle._parent_graph.to_dict(),
        "session": id(lifecycle.session), "simulation": id(lifecycle.session.simulation),
        "controller": id(lifecycle.session.controller),
    }, sort_keys=True, allow_nan=True), {
        str(path.relative_to(bundle.tmp_path)): path.read_bytes()
        for path in bundle.tmp_path.rglob("*") if path.is_file()
    }


def reject_without_execution(bundle, **changes):
    before = unchanged_snapshot(bundle)
    outcome = dispatch(bundle, **changes)
    assert outcome["status"] == "ESCALATE" and outcome["new_mission_result"] is None
    assert unchanged_snapshot(bundle) == before
    assert bundle.bridge.events[-1]["reason"] == outcome["reason"]
    assert bundle.bridge.events[-1]["production_authority"] is False
    return outcome


def assert_registered_attempt_burned(bundle):
    before = unchanged_snapshot(bundle)
    result = dispatch(bundle)
    assert result["reason"] == "UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF"
    assert unchanged_snapshot(bundle) == before


def test_positive_uses_issuer_canonical_bytes_and_preserves_parent(phase13_grounder, tmp_path):
    bundle = approve(fixture(phase13_grounder, tmp_path))
    parent_graph = bundle.lifecycle._parent_graph
    parent_bytes = {path.name: path.read_bytes()
                    for path in (tmp_path / "failed-parent").iterdir()}
    observed = []
    original_run = bundle.lifecycle.executor.run

    def observe(mission, **options):
        observed.append((full_plan_json(mission).encode("utf8"), options["existing_session"]))
        assert mission is not bundle.mission
        return original_run(mission, **options)

    bundle.lifecycle.executor.run = observe
    result = dispatch(bundle, mission=Mission.from_dict(bundle.mission.to_dict()))
    assert result["status"] == "NEW_MISSION_COMPLETED"
    assert result["handoff_consumption"] == "CONSUMED" and result["parent_preserved"]
    assert observed == [(bundle.grant.canonical_mission, bundle.session)]
    # Two encodings are intentionally distinct, each verified in its own domain.
    assert result["handoff_plan_sha256"] != result["lifecycle_mission_sha256"]
    assert bundle.lifecycle._parent_graph is parent_graph
    assert [node for node, _ in bundle.session.calls] == ["s1", "n1", "n2", "n3"]
    assert {path.name: path.read_bytes() for path in (tmp_path / "failed-parent").iterdir()} == parent_bytes
    assert bundle.parent.state == "FAILED"
    assert_registered_attempt_burned(bundle)


def test_caller_mutation_at_consumption_boundary_never_becomes_execution(phase13_grounder, tmp_path):
    bundle = approve(fixture(phase13_grounder, tmp_path))
    original_consume = bundle.handoff.consume

    def mutate_after_verification(*args, **kwargs):
        result = original_consume(*args, **kwargs)
        bundle.mission.steps[0].parameters["distance_m"] = 6.0
        return result

    bundle.handoff.consume = mutate_after_verification
    observed = []
    original_run = bundle.lifecycle.executor.run

    def observe(mission, **options):
        observed.append(full_plan_json(mission).encode("utf8"))
        return original_run(mission, **options)

    bundle.lifecycle.executor.run = observe
    assert dispatch(bundle)["status"] == "NEW_MISSION_COMPLETED"
    assert observed == [bundle.grant.canonical_mission]
    assert bundle.mission.steps[0].parameters["distance_m"] == 6.0


def test_state_change_after_source_consumption_is_reassessed_before_execution(phase13_grounder, tmp_path):
    bundle = approve(fixture(phase13_grounder, tmp_path))
    original_consume = bundle.handoff.consume
    before_calls, before_steps = list(bundle.session.calls), bundle.session.total_steps
    parent_bytes = {path.name: path.read_bytes()
                    for path in (tmp_path / "failed-parent").iterdir()}

    def change_state_after_verification(*args, **kwargs):
        canonical = original_consume(*args, **kwargs)
        bundle.session._data.qvel[6] = 0.1
        return canonical

    bundle.handoff.consume = change_state_after_verification
    result = dispatch(bundle)
    assert result["reason"] == "ASSESSMENT_REJECTED"
    assert "EXECUTION_STATE_CHANGED" in result["assessment"]["reasons"]
    assert result["handoff_consumption"] == "CONSUMED"
    assert (bundle.session.calls, bundle.session.total_steps) == (before_calls, before_steps)
    assert {path.name: path.read_bytes() for path in (tmp_path / "failed-parent").iterdir()} == parent_bytes
    assert_registered_attempt_burned(bundle)


@pytest.mark.parametrize("change", [
    lambda m: m["steps"][0]["parameters"].update(distance_m=6.0),
    lambda m: m.update(mission_id="different-mission"),
    lambda m: m["steps"][0].update(id="different-node"),
    lambda m: m["steps"][0].update(skill="stop", parameters={}),
    lambda m: m["steps"][1].update(depends_on=[]),
    lambda m: m["steps"].reverse(),
    lambda m: m.update(schema_version="1.0.0"),
    lambda m: m["steps"][0].update(execution_mode_override="open_loop"),
])
def test_complete_plan_mutation_rejected_and_consumed(phase13_grounder, tmp_path, change):
    bundle = approve(fixture(phase13_grounder, tmp_path))
    altered = bundle.mission.to_dict()
    change(altered)
    result = reject_without_execution(bundle, mission=altered)
    assert result["handoff_consumption"] == "REJECTED"
    assert_registered_attempt_burned(bundle)


@pytest.mark.parametrize("kind", ["missing", "forged", "copied", "revoked"])
def test_invalid_grant_never_dispatches(phase13_grounder, tmp_path, kind):
    bundle = approve(fixture(phase13_grounder, tmp_path))
    grant = {"missing": None, "forged": {}, "copied": replace(bundle.grant)}.get(kind, bundle.grant)
    if kind == "revoked":
        bundle.handoff.revoke(grant)
    reject_without_execution(bundle, grant=grant)
    if kind == "revoked":
        assert_registered_attempt_burned(bundle)


@pytest.mark.parametrize("kind", ["source", "context", "copied_preparation"])
def test_source_context_preparation_binding(phase13_grounder, tmp_path, kind):
    bundle = approve(fixture(phase13_grounder, tmp_path))
    changes = {
        "source": {"source": SOURCE + " 再站立。"},
        "context": {"context": begin_release_request(SOURCE)},
        "copied_preparation": {"preparation": replace(bundle.preparation)},
    }[kind]
    reject_without_execution(bundle, **changes)
    assert_registered_attempt_burned(bundle)


@pytest.mark.parametrize("kind", ["copied_confirmation", "revoked_identity", "expired_identity", "foreign_issuer"])
def test_principal_proof_is_registered_not_a_name(phase13_grounder, tmp_path, kind):
    bundle = fixture(phase13_grounder, tmp_path)
    foreign = TestPrincipalAuthority(clock=lambda: bundle.now[0]) if kind == "foreign_issuer" else None
    approve(bundle, authority=foreign)
    changes = {}
    if kind == "copied_confirmation":
        changes["confirmation"] = replace(bundle.confirmation)
    elif kind == "revoked_identity":
        bundle.authority.revoke_session(bundle.login)
    elif kind == "expired_identity":
        bundle.now[0] = 131.0
    reject_without_execution(bundle, **changes)
    assert_registered_attempt_burned(bundle)


def test_valid_identity_without_continuation_permission_is_refused(phase13_grounder, tmp_path):
    plan_hash = _plan_hash(Mission.from_dict(NEW_MISSION))
    permissions = {("alice", plan_hash): {"DISPLAY_ONLY"},
                   ("operator", plan_hash): {CONTINUATION_PERMISSION}}
    bundle = approve(fixture(phase13_grounder, tmp_path, permissions=permissions))
    result = reject_without_execution(bundle)
    assert result["reason"] == "PRINCIPAL_CONTINUATION_PERMISSION_MISSING"
    assert_registered_attempt_burned(bundle)


@pytest.mark.parametrize("opt_in", [False, None, 1, "true"])
def test_strict_boolean_opt_in_required_before_preparation(phase13_grounder, tmp_path, opt_in):
    bundle = fixture(phase13_grounder, tmp_path, opt_in=opt_in)
    before = unchanged_snapshot(bundle)
    with pytest.raises(ValueError, match="TEST_ONLY_INTEGRATION_DISABLED"):
        bundle.bridge.prepare(source=SOURCE, mission=bundle.mission)
    assert unchanged_snapshot(bundle) == before


def test_full_plan_allowlist_is_host_owned_copied_configuration(phase13_grounder, tmp_path):
    plan_hash = _plan_hash(Mission.from_dict(NEW_MISSION))
    permissions = {("alice", plan_hash): {CONTINUATION_PERMISSION}}
    bundle = fixture(phase13_grounder, tmp_path, permissions=permissions)
    permissions.clear()
    approve(bundle)
    assert dispatch(bundle)["status"] == "NEW_MISSION_COMPLETED"


def test_plan_outside_allowlist_refused_before_issuance(phase13_grounder, tmp_path):
    bundle = fixture(phase13_grounder, tmp_path, permissions={})
    before = unchanged_snapshot(bundle)
    with pytest.raises(ValueError, match="PLAN_OUTSIDE_FROZEN_TEST_ONLY_ALLOWLIST"):
        bundle.bridge.prepare(source=SOURCE, mission=bundle.mission)
    assert unchanged_snapshot(bundle) == before


@pytest.mark.parametrize("change", [
    lambda b: setattr(b.session, "total_steps", b.session.total_steps + 1),
    lambda b: b.session._state.update(simulation_time=2.002),
    lambda b: b.session._data.qpos.__setitem__(7, 0.1),
    lambda b: b.session._data.qvel.__setitem__(6, 0.1),
    lambda b: b.session._data.ctrl.__setitem__(0, 0.1),
    lambda b: setattr(b.session.controller, "_counter", 1),
    lambda b: b.session._state.update(linear_velocity=[0.451, 0.0, 0.0]),
    lambda b: b.session._state.update(fallen=True),
    lambda b: b.session._state.update(standing=False),
    lambda b: b.session._state.update(linear_velocity=[float("nan"), 0.0, 0.0]),
    lambda b: b.parent.physical_halt.update(status="HALT_FAILED"),
    lambda b: b.parent.physical_halt.update(checks={"final_speed": True}),
    lambda b: b.lifecycle._parent_graph.get("s2").parameters.update(tampered=1.0),
])
def test_state_or_parent_change_burns_grant_and_never_dispatches(phase13_grounder, tmp_path, change):
    bundle = approve(fixture(phase13_grounder, tmp_path))
    change(bundle)
    reject_without_execution(bundle)
    assert_registered_attempt_burned(bundle)


def test_other_actual_lifecycle_with_same_name_is_not_owner(phase13_grounder, tmp_path):
    bundle = approve(fixture(phase13_grounder, tmp_path))
    other_path = tmp_path / "other"
    other_path.mkdir()
    other, _, _, _ = setup(phase13_grounder, other_path)
    assert other.session_id == bundle.lifecycle.session_id
    bundle.bridge.lifecycle = other
    assert reject_without_execution(bundle)["reason"] == "LIFECYCLE_OWNER_CHANGED"
    assert_registered_attempt_burned(bundle)


def test_integration_epoch_change_refuses_after_consumption(phase13_grounder, tmp_path, monkeypatch):
    bundle = approve(fixture(phase13_grounder, tmp_path))
    monkeypatch.setattr(bridge_module, "semantics_digest", lambda: "f" * 64)
    assert reject_without_execution(bundle)["reason"] == "INTEGRATION_EPOCH_CHANGED"
    assert_registered_attempt_burned(bundle)


def test_evidence_destination_collision_is_not_overwritten(phase13_grounder, tmp_path):
    bundle = approve(fixture(phase13_grounder, tmp_path))
    collision = tmp_path / NEW_MISSION["mission_id"]
    collision.mkdir()
    (collision / "existing.txt").write_bytes(b"retained")
    outcome = reject_without_execution(bundle)
    assert "NEW_EVIDENCE_PATH_EXISTS" in outcome["assessment"]["reasons"]
    assert_registered_attempt_burned(bundle)
