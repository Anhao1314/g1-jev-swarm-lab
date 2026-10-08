"""Host-owned offline consent capabilities. All identities are TEST_ONLY.

No credential authentication, UI delivery proof or Runtime integration exists.
Opaque registered object identity, not JSON, names, hashes or model claims,
establishes a fixture capability. Restart/new service refuses old capabilities.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import secrets
from threading import Lock
import time

from ..authority_mechanism_001.contract import Decision, Origin, SCOPES, source_digest
from ..authority_release_001.gate import is_current_request
from ..mission.ir import Mission
from ..mission.validator import MissionValidator
from ..paths import repo_root
from ..simplex.canonical import canonical_document
from ..simplex.structural_guard import StructuralGuard

ASSURANCE = "TEST_ONLY_SIMULATED_PRINCIPAL"
VERSION = "human_principal_offline_v1"
MAX_TTL_S = 300.0


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(text):
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def full_plan_json(mission):
    parsed = Mission.from_dict(mission.to_dict())
    if not MissionValidator().validate(parsed).valid or any(s.execution_mode_override is not None for s in parsed.steps):
        raise ValueError("Illegal Mission cannot be presented or approved")
    return _json(canonical_document(parsed, allow_text_numbers=False))


def semantics_digest():
    # Bind presentation/default interpretation to actual source, without Runtime.
    names = ["src/g1swarm/mission/ir.py", "src/g1swarm/mission/validator.py",
             "src/g1swarm/mission/task_graph.py", "src/g1swarm/mission/grounding.py",
             "src/g1swarm/mission/runtime.py", "src/g1swarm/skills/basic.py",
             "src/g1swarm/simplex/canonical.py", "src/g1swarm/human_principal_001/contract.py"]
    return _digest(_json({name: hashlib.sha256((repo_root()/name).read_bytes()).hexdigest() for name in names}))


@dataclass(frozen=True)
class TestSession:
    session_id: str
    principal_id: str
    issued_at: float
    expires_at: float
    assurance: str = ASSURANCE


@dataclass(frozen=True)
class Presentation:
    presentation_id: str
    revision: int
    principal_id: str
    session_id: str
    context_id: str
    source_sha256: str
    mission_sha256: str
    semantics_sha256: str
    display_text: str
    display_sha256: str
    issued_at: float
    expires_at: float
    assurance: str = ASSURANCE

    def to_dict(self):
        return asdict(self)  # Display data only; reconstructed objects are untrusted.


@dataclass(frozen=True)
class Confirmation:
    response_id: str
    presentation_id: str
    principal_id: str
    session_id: str
    context_id: str
    source_sha256: str
    mission_sha256: str
    semantics_sha256: str
    display_sha256: str
    action: str
    issued_at: float
    expires_at: float
    assurance: str = ASSURANCE

    def to_dict(self):
        return asdict(self)  # Not a portable authentication/consent receipt.


class TestPrincipalAuthority:
    """Explicit fixture issuer only. Public production-default gate refuses it."""
    __test__ = False

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._last_now = float("-inf")
        self._lock = Lock()
        self._sessions, self._presentations, self._responses = {}, {}, {}
        self._session_bodies, self._presentation_bodies, self._response_bodies = {}, {}, {}
        self._states, self._contexts, self._requests, self._revoked_sessions = {}, {}, {}, set()
        self._events = []

    def _now(self):
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < self._last_now:
            raise ValueError("Nonfinite or rolled-back host clock")
        self._last_now = float(value)
        return float(value)

    @staticmethod
    def _ttl(ttl):
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or not 0 < ttl <= MAX_TTL_S:
            raise ValueError("Fixture capability TTL must be finite in (0,300] seconds")
        return float(ttl)

    def _session_ok(self, session, now):
        return (type(session) is TestSession and self._sessions.get(session.session_id) is session
                and self._session_bodies.get(session.session_id) == _json(asdict(session))
                and session.session_id not in self._revoked_sessions and now < session.expires_at
                and session.assurance == ASSURANCE)

    def create_test_session(self, principal_id, *, ttl_s=300):
        """Simulate a login. A string is NOT real principal authentication."""
        if not isinstance(principal_id, str) or not principal_id.strip() or len(principal_id) > 128:
            raise ValueError("Fixture principal name required")
        with self._lock:
            now = self._now()
            session = TestSession(secrets.token_hex(32), principal_id, now, now+self._ttl(ttl_s))
            self._sessions[session.session_id] = session
            self._session_bodies[session.session_id] = _json(asdict(session))
            return session

    def revoke_session(self, session):
        with self._lock:
            now = self._now()
            if not self._session_ok(session, now):
                raise ValueError("Untrusted or expired fixture session")
            self._revoked_sessions.add(session.session_id)
            self._events.append({"event": "SESSION_REVOKED", "principal_id": session.principal_id, "time": now})

    def present(self, source, mission, context, session, *, ttl_s=120):
        """Return exact full canonical Mission and bound presentation data."""
        plan = full_plan_json(mission)
        if not StructuralGuard().check(source).passed or not is_current_request(source, context):
            raise ValueError("Presentation requires valid source and current host request")
        epoch = semantics_digest()
        with self._lock:
            now = self._now()
            if not self._session_ok(session, now):
                raise ValueError("No authenticated TEST_ONLY session capability")
            previous = self._contexts.get(context.context_id)
            revision = 1
            if previous is not None:
                self._states[previous.presentation_id] = "SUPERSEDED"
                revision = previous.revision+1
            presentation_id = secrets.token_hex(32)
            defaults = [{"step_id": s["id"], "duration_s": 2.0}
                        for s in json.loads(plan)["steps"] if s["skill"] == "stand" and "duration_s" not in s["parameters"]]
            display = _json({"version": VERSION, "assurance": ASSURANCE,
                "instruction": "Explicitly authorize THIS complete plan as a NEW instruction; do not certify original source uniqueness.",
                "source": source, "source_sha256": source_digest(source), "canonical_mission": json.loads(plan),
                "implicit_stand_defaults": defaults, "defaults_scope": "Other execution settings remain frozen host settings; no Runtime permission.",
                "principal_id": session.principal_id, "session_id": session.session_id,
                "request_context_id": context.context_id, "presentation_id": presentation_id, "revision": revision,
                "semantics_sha256": epoch, "execution_authority": "OFFLINE_TEST_ONLY_NOT_PRODUCTION"})
            offer = Presentation(presentation_id, revision, session.principal_id, session.session_id,
                context.context_id, source_digest(source), _digest(plan), epoch, display, _digest(display),
                now, min(session.expires_at, now+self._ttl(ttl_s)))
            self._presentations[presentation_id] = offer
            self._presentation_bodies[presentation_id] = _json(asdict(offer))
            self._requests[presentation_id] = context
            self._contexts[context.context_id] = offer
            self._states[presentation_id] = "PRESENTED"
            self._events.append({"event": "PRESENTED", "presentation_id": presentation_id,
                                 "display_sha256": offer.display_sha256, "time": now})
            return offer

    def respond(self, session, presentation, *, displayed_sha256, action):
        """Explicit bound action, not model 'yes', truthy flag or inferred consent."""
        if type(action) is not str or action not in {"CONFIRM", "REFUSE", "MODIFY", "CLARIFY"}:
            raise ValueError("Explicit CONFIRM/REFUSE/MODIFY/CLARIFY required")
        with self._lock:
            now = self._now()
            if (not self._session_ok(session, now) or type(presentation) is not Presentation
                    or self._presentations.get(presentation.presentation_id) is not presentation
                    or self._presentation_bodies.get(presentation.presentation_id) != _json(asdict(presentation))
                    or session.session_id != presentation.session_id or now >= presentation.expires_at
                    or (action == "CONFIRM" and not is_current_request(json.loads(presentation.display_text)["source"], self._requests[presentation.presentation_id]))
                    or presentation.semantics_sha256 != semantics_digest()
                    or self._states.get(presentation.presentation_id) not in {"PRESENTED", "CONFIRMED"}
                    or displayed_sha256 != presentation.display_sha256):
                raise ValueError("Untrusted, stale or mismatched consent presentation")
            if action == "CONFIRM" and self._states[presentation.presentation_id] != "PRESENTED":
                raise ValueError("Already confirmed; explicit duplicate response rejected")
            # Refuse/edit/clarify can revoke an unconsumed confirmation.
            response = Confirmation(secrets.token_hex(32), presentation.presentation_id,
                session.principal_id, session.session_id, presentation.context_id,
                presentation.source_sha256, presentation.mission_sha256, presentation.semantics_sha256,
                presentation.display_sha256, action, now, presentation.expires_at)
            self._responses[response.response_id] = response
            self._response_bodies[response.response_id] = _json(asdict(response))
            self._states[presentation.presentation_id] = {"CONFIRM": "CONFIRMED", "REFUSE": "REFUSED", "MODIFY": "MODIFIED", "CLARIFY": "CLARIFICATION_REQUIRED"}[action]
            self._events.append({"event": action, "presentation_id": presentation.presentation_id,
                                 "principal_id": session.principal_id, "time": now})
            return response

    def verify_and_consume(self, source, mission, context, confirmation):
        """Permission metadata only; public apply_gate separately claims context."""
        missing = Decision(False, "AUTHORITY_UNESTABLISHED_CLARIFICATION_REQUIRED")
        if confirmation is None:
            return missing, {"assurance": ASSURANCE, "production_authority_established": False}
        with self._lock:
            try:
                now = self._now()
            except ValueError:
                return Decision(False, "PRINCIPAL_CLOCK_INVALID"), {}
            if (type(confirmation) is not Confirmation
                    or self._responses.get(confirmation.response_id) is not confirmation
                    or self._response_bodies.get(confirmation.response_id) != _json(asdict(confirmation))):
                return Decision(False, "UNTRUSTED_PRINCIPAL_CONFIRMATION"), {}
            offer = self._presentations[confirmation.presentation_id]
            session = self._sessions[confirmation.session_id]
            if self._presentation_bodies[offer.presentation_id] != _json(asdict(offer)):
                return Decision(False, "PRINCIPAL_PRESENTATION_MUTATED"), {}
            evidence = {"assurance": ASSURANCE, "principal_id": confirmation.principal_id,
                        "principal_action": confirmation.action, "presentation": offer.to_dict(),
                        "confirmation": confirmation.to_dict(), "production_authority_established": False,
                        "original_source_uniqueness_established": False}
            if not self._session_ok(session, now):
                return Decision(False, "PRINCIPAL_SESSION_INVALID"), evidence
            if now >= offer.expires_at or now >= confirmation.expires_at:
                self._states[offer.presentation_id] = "EXPIRED"
                return Decision(False, "PRINCIPAL_CONFIRMATION_EXPIRED"), evidence
            expected_state = {"CONFIRM": "CONFIRMED", "REFUSE": "REFUSED", "MODIFY": "MODIFIED", "CLARIFY": "CLARIFICATION_REQUIRED"}[confirmation.action]
            if self._states.get(offer.presentation_id) != expected_state:
                return Decision(False, "PRINCIPAL_CONFIRMATION_REVOKED_OR_CONSUMED"), evidence
            try:
                plan_changed = _digest(full_plan_json(mission)) != confirmation.mission_sha256
            except Exception:
                plan_changed = True
            if (source_digest(source) != confirmation.source_sha256 or context is not self._requests[offer.presentation_id]
                    or context.context_id != confirmation.context_id
                    or plan_changed or semantics_digest() != confirmation.semantics_sha256):
                self._states[offer.presentation_id] = "INVALIDATED"
                return Decision(False, "PRINCIPAL_SOURCE_PLAN_CONTEXT_OR_SEMANTICS_MISMATCH"), evidence
            self._states[offer.presentation_id] = "CONSUMED"
            self._events.append({"event": "CONSUMED", "response_id": confirmation.response_id, "time": now})
            if confirmation.action in {"MODIFY", "CLARIFY"}:
                return missing, evidence
            if confirmation.action == "REFUSE":
                return Decision(False, "PRINCIPAL_REFUSED"), evidence
            return Decision(True, "EXPLICIT_TEST_PRINCIPAL_PLAN_AUTHORIZED", Origin.PRINCIPAL.value,
                            SCOPES[Origin.PRINCIPAL], False, True), evidence

    def audit_events(self):
        with self._lock:
            return [dict(e) for e in self._events]
