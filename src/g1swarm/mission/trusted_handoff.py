"""TEST_ONLY Source Authority v0 to M2.2 lifecycle, trusted serial entry.

The simulated principal and explicit host permission are experiment fixtures,
not production identity or concurrent consume-and-dispatch guarantees. The
existing MissionExecutor remains independently callable by trusted Python.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Iterable, Mapping

from ..trusted_handoff_v0 import (
    ASSURANCE, HandoffGrant, OfflineHandoff, Origin, SCOPES, TestPrincipalAuthority,
    begin_release_request, full_plan_json, semantics_digest, source_digest,
)
from .ir import Mission
from .lifecycle import (
    MissionLifecycle, TestOnlyMissionAuthorizer, canonical_sha256, mission_sha256,
)


CONTINUATION_PERMISSION = "TEST_ONLY_SAME_SESSION_NEW_MISSION"


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class PreparedMissionHandoff:
    """Display/issuance data; reconstructed objects do not establish trust."""

    canonical_mission: bytes
    source_sha256: str
    context: object
    handoff_plan_sha256: str
    lifecycle_mission_sha256: str
    integration_epoch: str


class TrustedMissionHandoff:
    """One bounded adapter around unchanged M2.2 checks and execution.

    permissions is copied host configuration keyed by (fixture principal ID,
    v0 complete-plan hash). A principal string alone is never identity proof:
    the exact configured issuer must revalidate its registered confirmation.
    Every registered external grant attempt is consumed before adapter refusal.
    Only the bytes returned by that issuer-owned consumption are executable.
    """

    def __init__(self, *, lifecycle: MissionLifecycle, handoff: OfflineHandoff,
                 authority: TestPrincipalAuthority,
                 permissions: Mapping[tuple[str, str], Iterable[str]],
                 allow_test_principal: bool = False) -> None:
        if (type(lifecycle) is not MissionLifecycle or type(handoff) is not OfflineHandoff
                or type(authority) is not TestPrincipalAuthority):
            raise ValueError("UNTRUSTED_INTEGRATION_COMPONENT")
        self.lifecycle = lifecycle
        self.handoff = handoff
        self.authority = authority
        self.allow_test_principal = allow_test_principal is True
        self._permissions = {key: frozenset(value) for key, value in permissions.items()}
        self._prepared: dict[int, dict] = {}
        self.events: list[dict] = []

    @staticmethod
    def _mission_snapshot(mission_input) -> Mission:
        # Always parse into a private Mission. frozen=True is shallow: the
        # existing MissionStep.parameters dictionary is still mutable.
        document = mission_input.to_dict() if type(mission_input) is Mission else deepcopy(mission_input)
        return Mission.from_dict(document)

    def prepare(self, *, source: str, mission) -> PreparedMissionHandoff:
        if not self.allow_test_principal:
            raise ValueError("TEST_ONLY_INTEGRATION_DISABLED")
        private = self._mission_snapshot(mission)
        canonical = full_plan_json(private).encode("utf8")
        plan_hash = _bytes_sha256(canonical)
        if not any(key[1] == plan_hash and CONTINUATION_PERMISSION in permissions
                   for key, permissions in self._permissions.items()):
            raise ValueError("PLAN_OUTSIDE_FROZEN_TEST_ONLY_ALLOWLIST")
        assessment = self.lifecycle.assess(private)
        if not assessment["eligible"]:
            raise ValueError("PREPARATION_ASSESSMENT_REJECTED:" + ",".join(assessment["reasons"]))
        if full_plan_json(private).encode("utf8") != canonical:
            raise ValueError("PREPARATION_PLAN_CHANGED")
        context = begin_release_request(source)
        preparation = PreparedMissionHandoff(
            canonical, source_digest(source), context, plan_hash,
            mission_sha256(private), semantics_digest(),
        )
        # Object owners are never replaced by serialized names or hashes.
        self._prepared[id(preparation)] = {
            "preparation": preparation, "lifecycle": self.lifecycle,
            "session": self.lifecycle.session, "binding": deepcopy(self.lifecycle._binding(assessment)),
            "handoff": self.handoff, "authority": self.authority,
            "permission_policy_sha256": self._policy_sha256(),
            "seal": self._preparation_seal(preparation), "used": False,
        }
        self._record("trusted_handoff_prepared", {
            "context_id": context.context_id,
            "handoff_plan_sha256": preparation.handoff_plan_sha256,
            "lifecycle_mission_sha256": preparation.lifecycle_mission_sha256,
            "integration_epoch": preparation.integration_epoch,
        })
        return preparation

    def _policy_sha256(self) -> str:
        return canonical_sha256(sorted(
            (principal, plan, sorted(permissions))
            for (principal, plan), permissions in self._permissions.items()))

    @staticmethod
    def _preparation_seal(preparation: PreparedMissionHandoff) -> tuple:
        return (preparation.canonical_mission, preparation.source_sha256,
                preparation.context, preparation.context.context_id,
                preparation.context.source_sha256, preparation.handoff_plan_sha256,
                preparation.lifecycle_mission_sha256, preparation.integration_epoch)

    def _record(self, event: str, payload: dict) -> None:
        item = {"event": event, "scope": "TEST_ONLY", "assurance": ASSURANCE,
                "production_authority": False, **deepcopy(payload)}
        self.events.append(item)
        self.lifecycle._event(event, item)

    def _parent_preserved(self) -> bool:
        try:
            return (canonical_sha256(self.lifecycle._parent_result.to_dict()) == self.lifecycle.parent_result_sha256
                    and canonical_sha256(self.lifecycle._parent_graph.to_dict()) == self.lifecycle.parent_graph_sha256)
        except Exception:
            return False

    def _reject(self, reason: str, *, consumption: str, assessment=None) -> dict:
        result = {"status": "ESCALATE", "reason": reason,
                  "handoff_consumption": consumption, "assessment": assessment,
                  "parent_preserved": self._parent_preserved(),
                  "new_mission_result": None}
        self._record("trusted_handoff_rejected", result)
        return result

    def dispatch(self, *, preparation, grant, source: str, mission, context,
                 confirmation, phase: str = "m23", write_evidence: bool = True) -> dict:
        # Call the v0 boundary first, including on an invalid preparation or
        # changed runtime state. v0 burns registered attempts on mismatches.
        try:
            comparison_mission = self._mission_snapshot(mission)
        except Exception:
            # The grant must still be burned when malformed caller input cannot
            # be parsed. v0 consume handles the invalid comparison fail closed.
            comparison_mission = mission
        try:
            canonical = self.handoff.consume(
                grant, source=source, mission=comparison_mission, context=context,
                allow_test_principal=self.allow_test_principal,
            )
        except ValueError as exc:
            return self._reject(str(exc), consumption="REJECTED")
        except Exception:
            return self._reject("HANDOFF_CONSUMPTION_ERROR", consumption="REJECTED")
        consumption = "CONSUMED"
        entry = self._prepared.get(id(preparation))
        if (type(preparation) is not PreparedMissionHandoff or entry is None
                or entry["preparation"] is not preparation):
            return self._reject("PREPARATION_UNRECOGNIZED", consumption=consumption)
        if entry["used"]:
            return self._reject("PREPARATION_REPLAY", consumption=consumption)
        entry["used"] = True
        if (entry["lifecycle"] is not self.lifecycle or entry["session"] is not self.lifecycle.session
                or entry["handoff"] is not self.handoff or entry["authority"] is not self.authority):
            return self._reject("LIFECYCLE_OWNER_CHANGED", consumption=consumption)
        try:
            seal_matches = self._preparation_seal(preparation) == entry["seal"]
            epoch_matches = preparation.integration_epoch == semantics_digest()
            policy_matches = self._policy_sha256() == entry["permission_policy_sha256"]
        except Exception:
            return self._reject("INTEGRATION_BINDING_INVALID", consumption=consumption)
        if not seal_matches:
            return self._reject("PREPARATION_BINDING_CHANGED", consumption=consumption)
        if not epoch_matches:
            return self._reject("INTEGRATION_EPOCH_CHANGED", consumption=consumption)
        if not policy_matches:
            return self._reject("PERMISSION_POLICY_CHANGED", consumption=consumption)
        if (context is not preparation.context or source_digest(source) != preparation.source_sha256
                or type(canonical) is not bytes or canonical != preparation.canonical_mission
                or _bytes_sha256(canonical) != preparation.handoff_plan_sha256):
            return self._reject("PREPARATION_SOURCE_PLAN_CONTEXT_MISMATCH", consumption=consumption)
        if (type(grant) is not HandoffGrant or grant.production_authority
                or grant.assurance != ASSURANCE or grant.original_source_unique
                or grant.origin != Origin.PRINCIPAL.value or grant.scope != SCOPES[Origin.PRINCIPAL]
                or grant.mission_sha256 != preparation.handoff_plan_sha256):
            return self._reject("HANDOFF_SCOPE_INVALID", consumption=consumption)
        if not self.authority.revalidate_handoff_identity(
                confirmation, source=source, plan_json=canonical.decode("utf8"), context=context):
            return self._reject("PRINCIPAL_ISSUER_OR_CONFIRMATION_INVALID", consumption=consumption)
        # These fields are checked only after original registered identity proof.
        if (confirmation.principal_id != grant.principal_id
                or confirmation.mission_sha256 != preparation.handoff_plan_sha256
                or confirmation.context_id != context.context_id):
            return self._reject("PRINCIPAL_GRANT_BINDING_MISMATCH", consumption=consumption)
        permissions = self._permissions.get(
            (confirmation.principal_id, preparation.handoff_plan_sha256), frozenset())
        if CONTINUATION_PERMISSION not in permissions:
            return self._reject("PRINCIPAL_CONTINUATION_PERMISSION_MISSING", consumption=consumption)
        try:
            # This is the sole executable plan origin, never caller comparison.
            private = Mission.from_dict(json.loads(canonical.decode("utf8")))
            if (full_plan_json(private).encode("utf8") != canonical
                    or mission_sha256(private) != preparation.lifecycle_mission_sha256):
                return self._reject("CANONICAL_RECONSTRUCTION_MISMATCH", consumption=consumption)
            assessment = self.lifecycle.assess(private)
            if not assessment["eligible"]:
                return self._reject("ASSESSMENT_REJECTED", consumption=consumption, assessment=assessment)
            if self.lifecycle._binding(assessment) != entry["binding"]:
                return self._reject("LIVE_LIFECYCLE_BINDING_CHANGED", consumption=consumption, assessment=assessment)
            local_authority = TestOnlyMissionAuthorizer(
                allowed_mission_sha256={preparation.lifecycle_mission_sha256})
            local_grant = local_authority.issue(self.lifecycle, private)
            self._record("trusted_handoff_verified", {
                "context_id": context.context_id,
                "handoff_plan_sha256": preparation.handoff_plan_sha256,
                "lifecycle_mission_sha256": preparation.lifecycle_mission_sha256,
                "integration_epoch": preparation.integration_epoch,
                "principal_id": confirmation.principal_id,
                "permission": CONTINUATION_PERMISSION,
            })
            result = self.lifecycle.dispatch(
                private, authorization=local_grant, authorizer=local_authority,
                phase=phase, write_evidence=write_evidence,
            )
        except Exception as exc:
            return self._reject("TRUSTED_HANDOFF_DISPATCH_ERROR:" + type(exc).__name__, consumption=consumption)
        result["handoff_consumption"] = consumption
        result["handoff_plan_sha256"] = preparation.handoff_plan_sha256
        result["lifecycle_mission_sha256"] = preparation.lifecycle_mission_sha256
        self._record("trusted_handoff_dispatch_completed", result)
        return result
