"""Offline pre-dispatch boundary; no provider or Runtime execution."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace, FrozenInstanceError
import copy
import hashlib
import json

import pytest

from g1swarm.authority_release_001 import begin_release_request
from g1swarm.execution_handoff_001.contract import OfflineHandoff
from g1swarm.human_principal_001.contract import ASSURANCE, full_plan_json
from g1swarm.mission.ir import Mission
from tests.human_principal_001.test_boundary import SOURCE, bundle


def granted():
    data = bundle()
    host = OfflineHandoff()
    grant = host.authorize(source=SOURCE, mission=data[4].mission, context=data[3],
        authority=data[1], confirmation=data[6], allow_test_principal=True)
    return host, grant, data


def consume(host, grant, data, **overrides):
    args = dict(source=SOURCE, mission=data[4].mission, context=data[3], allow_test_principal=True)
    args.update(overrides)
    return host.consume(grant, **args)


def test_complete_canonical_snapshot_and_new_instruction_identity():
    host, grant, data = granted()
    expected = full_plan_json(data[4].mission).encode('utf8')
    assert type(grant.canonical_mission) is bytes
    assert grant.canonical_mission == expected
    assert grant.mission_sha256 == hashlib.sha256(expected).hexdigest()
    assert grant.principal_id == 'alice'
    assert grant.source_sha256 == data[6].source_sha256
    assert grant.context_id == data[3].context_id
    assert grant.origin == 'EXPLICIT_PRINCIPAL_PLAN_AUTHORIZATION'
    assert grant.scope == 'NEW_EXPLICIT_PLAN_INSTRUCTION_NOT_SOURCE_UNIQUENESS'
    assert not grant.original_source_unique and not grant.production_authority
    assert grant.assurance == ASSURANCE
    assert consume(host, grant, data) == expected
    assert json.loads(expected)['mission_id'] == data[4].mission.mission_id
    with pytest.raises(ValueError):
        consume(host, grant, data)


def test_returned_bytes_do_not_alias_mutable_mission():
    host, grant, data = granted()
    snapshot = consume(host, grant, data)
    data[4].mission.steps[1].parameters['distance_m'] = 1.0
    assert json.loads(snapshot)['steps'][1]['parameters']['distance_m'] == 8.0
    with pytest.raises(FrozenInstanceError):
        grant.production_authority = True


@pytest.mark.parametrize('mutation', ['distance', 'mission_id', 'steps', 'dependency', 'step_id', 'skill'])
def test_plan_mutation_after_authorization_is_rejected_and_burned(mutation):
    host, grant, data = granted()
    original = copy.deepcopy(data[4].mission)
    current = data[4].mission
    if mutation == 'distance':
        current.steps[1].parameters['distance_m'] = 7.0
    elif mutation == 'mission_id':
        object.__setattr__(current, 'mission_id', 'replacement-plan')
    elif mutation == 'steps':
        object.__setattr__(current, 'steps', tuple(reversed(current.steps)))
    elif mutation == 'dependency':
        object.__setattr__(current.steps[1], 'depends_on', ())
    elif mutation == 'step_id':
        object.__setattr__(current.steps[2], 'step_id', 'different-id')
    else:
        object.__setattr__(current.steps[2], 'skill', current.steps[0].skill)
    with pytest.raises(ValueError):
        consume(host, grant, data)
    with pytest.raises(ValueError):
        consume(host, grant, data, mission=original)


def test_equal_detached_plan_is_accepted_because_identity_is_canonical_content():
    host, grant, data = granted()
    detached = Mission.from_dict(json.loads(grant.canonical_mission))
    assert detached is not data[4].mission
    assert consume(host, grant, data, mission=detached) == grant.canonical_mission


@pytest.mark.parametrize('replacement', ['source', 'context_copy', 'context_other'])
def test_source_or_request_substitution_rejected(replacement):
    host, grant, data = granted()
    overrides = {'source': SOURCE + '。'} if replacement == 'source' else {
        'context': copy.copy(data[3]) if replacement == 'context_copy' else begin_release_request(SOURCE)}
    with pytest.raises(ValueError):
        consume(host, grant, data, **overrides)


@pytest.mark.parametrize('forger', [copy.copy, copy.deepcopy, lambda g: replace(g), lambda g: g.__dict__])
def test_copied_or_serialized_grant_has_no_authority(forger):
    host, grant, data = granted()
    with pytest.raises(ValueError):
        consume(host, forger(grant), data)
    assert consume(host, grant, data) == grant.canonical_mission


@pytest.mark.parametrize('field,value', [
    ('production_authority', True), ('assurance', 'PRODUCTION'),
    ('principal_id', 'mallory'), ('source_sha256', '0'*64),
    ('context_id', 'forged'), ('mission_sha256', '0'*64),
    ('semantics_sha256', '0'*64), ('origin', 'BOUNDED_SOURCE_DERIVATION'),
    ('scope', 'ORIGINAL_SOURCE_UNIQUE'), ('original_source_unique', True),
    ('expires_at', 999999.0), ('canonical_mission', b'{}')])
def test_frozen_dataclass_bypass_still_rejected_by_seal(field, value):
    host, grant, data = granted()
    object.__setattr__(grant, field, value)
    with pytest.raises(ValueError):
        consume(host, grant, data)


@pytest.mark.parametrize('failure', ['expiry', 'session_expiry', 'revoked', 'session_identity', 'confirmation_identity', 'offer_identity', 'clock_rollback'])
def test_principal_identity_is_revalidated_before_dispatch(failure):
    host, grant, data = granted()
    clock, authority, session, _, _, offer, response = data
    if failure == 'expiry':
        clock.now = response.expires_at
    elif failure == 'session_expiry':
        clock.now = session.expires_at
    elif failure == 'revoked':
        authority.revoke_session(session)
    elif failure == 'session_identity':
        object.__setattr__(session, 'principal_id', 'mallory')
    elif failure == 'confirmation_identity':
        object.__setattr__(response, 'principal_id', 'mallory')
    elif failure == 'offer_identity':
        object.__setattr__(offer, 'principal_id', 'mallory')
    else:
        clock.now -= 1
    with pytest.raises(ValueError):
        consume(host, grant, data)


def test_revoke_and_other_host_reject():
    host, grant, data = granted()
    with pytest.raises(ValueError):
        consume(OfflineHandoff(), grant, data)
    host.revoke(grant)
    with pytest.raises(ValueError):
        consume(host, grant, data)


def test_concurrent_consumers_get_exactly_one_snapshot():
    host, grant, data = granted()
    def attempt(_):
        try:
            return consume(host, grant, data)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(24)))
    assert outcomes.count(grant.canonical_mission) == 1
    assert outcomes.count(None) == 23


@pytest.mark.parametrize('enabled', [False, None, 1, 'true'])
def test_test_authority_requires_exact_explicit_opt_in_at_issuance(enabled):
    data = bundle()
    with pytest.raises(ValueError):
        OfflineHandoff().authorize(source=SOURCE, mission=data[4].mission, context=data[3],
            authority=data[1], confirmation=data[6], allow_test_principal=enabled)


@pytest.mark.parametrize('enabled', [False, None, 1, 'true'])
def test_test_authority_requires_exact_explicit_opt_in_at_consumption(enabled):
    host, grant, data = granted()
    with pytest.raises(ValueError):
        consume(host, grant, data, allow_test_principal=enabled)


def test_confirmation_cannot_issue_two_grants():
    host, grant, data = granted()
    with pytest.raises(ValueError):
        host.authorize(source=SOURCE, mission=data[4].mission, context=data[3],
            authority=data[1], confirmation=data[6], allow_test_principal=True)
    assert consume(host, grant, data) == grant.canonical_mission


@pytest.mark.parametrize('action', ['REFUSE', 'MODIFY', 'CLARIFY'])
def test_nonconfirmation_cannot_issue_grant(action):
    data = bundle()
    response = data[1].respond(data[2], data[5], displayed_sha256=data[5].display_sha256, action=action)
    with pytest.raises(ValueError):
        OfflineHandoff().authorize(source=SOURCE, mission=data[4].mission, context=data[3],
            authority=data[1], confirmation=response, allow_test_principal=True)


@pytest.mark.parametrize('binding', ['plan', 'source', 'context', 'confirmation', 'authority'])
def test_issuance_rejects_changed_or_untrusted_authorization(binding):
    data = bundle()
    args = dict(source=SOURCE, mission=data[4].mission, context=data[3],
        authority=data[1], confirmation=data[6], allow_test_principal=True)
    if binding == 'plan':
        data[4].mission.steps[1].parameters['distance_m'] = 7.0
    elif binding == 'source':
        args['source'] = SOURCE + '。'
    elif binding == 'context':
        args['context'] = begin_release_request(SOURCE)
    elif binding == 'confirmation':
        args['confirmation'] = replace(data[6])
    else:
        args['authority'] = object()
    with pytest.raises(ValueError):
        OfflineHandoff().authorize(**args)


def test_semantics_epoch_change_rejects_previously_authorized_plan(monkeypatch):
    host, grant, data = granted()
    import g1swarm.human_principal_001.contract as identity
    monkeypatch.setattr(identity, 'semantics_digest', lambda: 'changed-code-epoch')
    with pytest.raises(ValueError):
        consume(host, grant, data)

def test_internal_snapshot_survives_external_grant_mutation_during_final_check(monkeypatch):
    host, grant, data = granted()
    expected = grant.canonical_mission
    original = data[1].revalidate_handoff_identity
    def checking(*args, **kwargs):
        valid = original(*args, **kwargs)
        object.__setattr__(grant, 'canonical_mission', b'{"forged":"post-check"}')
        return valid
    monkeypatch.setattr(data[1], 'revalidate_handoff_identity', checking)
    assert consume(host, grant, data) == expected
    with pytest.raises(ValueError):
        consume(host, grant, data)
