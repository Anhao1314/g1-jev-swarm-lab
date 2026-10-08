"""Offline, TEST_ONLY authority-to-execution boundary. Never executes a Mission."""
from dataclasses import asdict, dataclass
import json
import secrets
from threading import Lock
from .principal import TestPrincipalAuthority, ASSURANCE, full_plan_json
from .support import claim_request

@dataclass(frozen=True)
class HandoffGrant:
    grant_id: str
    canonical_mission: bytes
    source_sha256: str
    principal_id: str
    context_id: str
    origin: str
    scope: str
    mission_sha256: str
    semantics_sha256: str
    expires_at: float
    assurance: str = ASSURANCE
    original_source_unique: bool = False
    production_authority: bool = False

def _seal(grant):
    body=asdict(grant)
    body['canonical_mission']=grant.canonical_mission.decode('utf8')
    return json.dumps(body,sort_keys=True,ensure_ascii=False,allow_nan=False)

class OfflineHandoff:
    """Registered grants, one dispatch consumption. Not a production adapter.

    consume returns canonical bytes, never the caller's mutable Mission. The
    consumer must use these bytes exclusively and enforce lifecycle/permission
    gates. This issuer never executes or grants production Runtime authority.
    """
    def __init__(self):
        self._lock=Lock()
        self._issued={}
        self._used=set()

    def authorize(self, *, source, mission, context, authority, confirmation,
                  allow_test_principal=False):
        if allow_test_principal is not True or type(authority) is not TestPrincipalAuthority:
            raise ValueError('TEST_ONLY_AUTHORITY_DISABLED_OR_UNTRUSTED')
        snapshot=full_plan_json(mission)
        claimed,failure=claim_request(source,context)
        if failure is not None:
            raise ValueError(failure.reason)
        # A detached copy prevents authority routines from altering caller B.
        from ..mission.ir import Mission
        detached=Mission.from_dict(json.loads(snapshot))
        decision,_=authority.verify_and_consume(source,detached,claimed,confirmation)
        if not decision.allow or not decision.explicit_new_plan_instruction:
            raise ValueError(decision.reason)
        if full_plan_json(mission)!=snapshot or not authority.revalidate_handoff_identity(
                confirmation,source=source,plan_json=snapshot,context=context):
            raise ValueError('AUTHORIZATION_BINDING_CHANGED')
        grant=HandoffGrant(secrets.token_hex(32),snapshot.encode('utf8'),
            confirmation.source_sha256,confirmation.principal_id,confirmation.context_id,
            decision.authority_origin,decision.authority_scope,confirmation.mission_sha256,
            confirmation.semantics_sha256,confirmation.expires_at)
        with self._lock:
            self._issued[grant.grant_id]=(grant,_seal(grant),authority,confirmation,context,
                                          snapshot.encode('utf8'))
        return grant

    def revoke(self, grant):
        with self._lock:
            grant_id = getattr(grant, 'grant_id', None)
            if type(grant) is not HandoffGrant or self._issued.get(grant_id,(None,))[0] is not grant:
                raise ValueError('UNTRUSTED_HANDOFF')
            self._used.add(grant_id)

    def consume(self, grant, *, source, mission, context, allow_test_principal=False):
        """Offline pre-dispatch check; linearized, at most once, fail closed.

        Valid registered attempts burn the grant even on mismatch. Consumption
        is the proposed dispatch boundary; callers cannot delay/reuse it as a
        permanent permission token. No physical execution occurs here.
        """
        with self._lock:
            try:
                if type(grant) is not HandoffGrant:
                    raise ValueError('UNTRUSTED_HANDOFF')
                grant_id=grant.grant_id
                entry=self._issued.get(grant_id)
                if entry is None or entry[0] is not grant or grant_id in self._used:
                    raise ValueError('UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF')
                self._used.add(grant_id)
                _,sealed,authority,confirmation,bound_context,bound_bytes=entry
                if (allow_test_principal is not True or _seal(grant)!=sealed
                        or grant.assurance!=ASSURANCE or grant.production_authority
                        or context is not bound_context):
                    raise ValueError('HANDOFF_ASSURANCE_OR_BINDING_INVALID')
                current=full_plan_json(mission)
                if current.encode('utf8')!=bound_bytes:
                    raise ValueError('PLAN_CHANGED')
                if not authority.revalidate_handoff_identity(confirmation,
                        source=source,plan_json=current,context=context):
                    raise ValueError('PRINCIPAL_OR_SOURCE_BINDING_STALE')
                return bound_bytes
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError('INVALID_HANDOFF') from exc
