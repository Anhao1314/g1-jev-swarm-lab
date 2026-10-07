"""Offline release contract with an authority origin independent of model claims.

This module does not replace v2, collect provider responses, execute Missions or
authenticate a real human. A principal receipt is verification-only: a future
trusted principal channel must issue it. Test signers are not user approvals.

A MAC proves provenance/binding under protected-key assumptions, not natural
language truth. Automatic authority reuses the existing bounded full-source
derivation, with its inherited language and normalization limitations.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json
from pathlib import Path
import secrets
from threading import Lock
from typing import Any, Mapping

from ..authority_certificate_v2 import certificate_plan_mission, parse_certificate
from ..mission.ir import Mission
from ..mission.validator import MissionValidator
from ..simplex.canonical import comparison_payload
from ..simplex.structural_guard import StructuralGuard
from ..source_authority import AuthorizationStatus
from .. import source_authority_bounded as bounded_module
from ..source_authority_bounded import BoundedSourceAuthorizationVerifier

VERSION = "offline_authority_contract_v1"
DOMAIN = b"g1swarm-independent-release-authority-v1\0"


class Origin(str, Enum):
    BOUNDED = "BOUNDED_SOURCE_DERIVATION"
    PRINCIPAL = "EXPLICIT_PRINCIPAL_PLAN_AUTHORIZATION"


SCOPES = {
    Origin.BOUNDED: "UNIQUENESS_UNDER_FROZEN_BOUNDED_LANGUAGE",
    Origin.PRINCIPAL: "NEW_EXPLICIT_PLAN_INSTRUCTION_NOT_SOURCE_UNIQUENESS",
}
BODY_KEYS = frozenset({"version", "origin", "scope", "source_sha256", "plan_sha256",
                       "context_id", "nonce", "ruleset_sha256"})


def source_digest(source: str) -> str:
    return hashlib.sha256(source.encode("utf8")).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf8")


def plan_digest(mission: Mission) -> str:
    return hashlib.sha256(canonical_bytes(comparison_payload(mission, allow_text_numbers=False))).hexdigest()


def receipt_mac(body: Mapping[str, Any], key: bytes) -> str:
    """Low-level envelope primitive, not a principal authentication API."""
    return hmac.new(key, DOMAIN + canonical_bytes(dict(body)), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str
    authority_origin: str | None = None
    authority_scope: str | None = None
    original_source_unique_under_bounded_contract: bool = False
    explicit_new_plan_instruction: bool = False
    semantic_rejection_credit: bool = False
    provider_calls: int = 0
    runtime_calls: int = 0


class AuthorityService:
    """Host-held trusted keys and instance-local replay checks.

    No principal issuer exists here. Configuring its verification key represents
    an external authenticated authority service; only tests configure a fixture
    signer. Never pass keys to a model. Production identity, consent, key
    storage, persistent replay protection and recovery are unbuilt.
    """

    def __init__(self, *, bounded_key: bytes | None = None,
                 principal_verification_key: bytes | None = None) -> None:
        self._keys = {Origin.BOUNDED: secrets.token_bytes(32) if bounded_key is None else bounded_key}
        if principal_verification_key is not None:
            self._keys[Origin.PRINCIPAL] = principal_verification_key
        if any(not isinstance(key, bytes) or len(key) < 32 for key in self._keys.values()):
            raise ValueError("trusted authority keys must contain at least 32 bytes")
        self._used: set[tuple[str, str]] = set()
        self._consume_lock = Lock()
        self._bounded = BoundedSourceAuthorizationVerifier()
        self.ruleset_sha256 = hashlib.sha256(canonical_bytes({
            "bounded_language_files": self._bounded.frozen_file_hashes,
            "bounded_authorizer_sha256": hashlib.sha256(Path(bounded_module.__file__).read_bytes()).hexdigest(),
        })).hexdigest()

    def derive_bounded_receipt(self, source: str, context_id: str) -> dict | None:
        """Source-only derivation: no B candidate, proposal or gold is read."""
        if (not isinstance(source, str) or not source.strip()
                or not isinstance(context_id, str) or not context_id.strip()):
            return None
        try:
            compiled = self._bounded.compiler.compile(source)
            if not compiled.success:
                return None
            authority = self._bounded.authorize(source, compiled.mission)
        except Exception:
            return None
        if not authority.authorized:
            return None
        body = {"version": VERSION, "origin": Origin.BOUNDED.value,
                "scope": SCOPES[Origin.BOUNDED], "source_sha256": source_digest(source),
                "plan_sha256": plan_digest(compiled.mission), "context_id": context_id,
                "nonce": secrets.token_hex(16), "ruleset_sha256": self.ruleset_sha256}
        return {**body, "signature": receipt_mac(body, self._keys[Origin.BOUNDED])}

    def _verify_and_consume(self, receipt: Any, source: str, candidate: Mission,
                            context_id: str) -> Decision:
        """Envelope check only; evaluate_release is the sole release boundary."""
        if receipt is None:
            return Decision(False, "AUTHORITY_UNESTABLISHED_CLARIFICATION_REQUIRED")
        if not isinstance(context_id, str) or not context_id.strip():
            return Decision(False, "AUTHORITY_CONTEXT_MISMATCH")
        if not isinstance(receipt, dict) or set(receipt) != BODY_KEYS | {"signature"}:
            return Decision(False, "INVALID_AUTHORITY_ENVELOPE")
        try:
            origin = Origin(receipt["origin"])
        except (ValueError, TypeError):
            return Decision(False, "UNTRUSTED_AUTHORITY_ORIGIN")
        key = self._keys.get(origin)
        if key is None:
            return Decision(False, "AUTHORITY_ORIGIN_NOT_CONFIGURED")
        if (receipt["version"] != VERSION or receipt["scope"] != SCOPES[origin]
                or not isinstance(receipt["nonce"], str) or len(receipt["nonce"]) != 32
                or any(char not in "0123456789abcdef" for char in receipt["nonce"])
                or any(not isinstance(receipt[name], str) or len(receipt[name]) != 64
                       or any(char not in "0123456789abcdef" for char in receipt[name])
                       for name in ("signature", "source_sha256", "plan_sha256"))
                or not isinstance(receipt["context_id"], str) or not receipt["context_id"].strip()):
            return Decision(False, "INVALID_AUTHORITY_ENVELOPE")
        expected_ruleset = self.ruleset_sha256 if origin is Origin.BOUNDED else None
        if receipt["ruleset_sha256"] != expected_ruleset:
            return Decision(False, "AUTHORITY_RULESET_MISMATCH")
        body = {name: receipt[name] for name in BODY_KEYS}
        try:
            signature_matches = hmac.compare_digest(receipt["signature"], receipt_mac(body, key))
        except (TypeError, ValueError, OverflowError):
            signature_matches = False
        if not signature_matches:
            return Decision(False, "UNVERIFIED_AUTHORITY_PROVENANCE")
        if receipt["source_sha256"] != source_digest(source):
            return Decision(False, "AUTHORITY_SOURCE_MISMATCH")
        if receipt["plan_sha256"] != plan_digest(candidate):
            return Decision(False, "AUTHORITY_COMPLETE_PLAN_MISMATCH")
        if receipt["context_id"] != context_id:
            return Decision(False, "AUTHORITY_CONTEXT_MISMATCH")
        token = (origin.value, receipt["nonce"])
        with self._consume_lock:
            if token in self._used:
                return Decision(False, "AUTHORITY_RECEIPT_ALREADY_CONSUMED")
            self._used.add(token)
        return Decision(True, "INDEPENDENT_AUTHORITY_VERIFIED", origin.value, SCOPES[origin],
                        origin is Origin.BOUNDED, origin is Origin.PRINCIPAL)


def evaluate_release(*, source: str, candidate: Mission, raw_proposal: str,
                     provider_completed: bool, proposal_source_sha256: str,
                     receipt: Any, context_id: str, authority: AuthorityService) -> Decision:
    """Pure offline boundary; returns permission metadata, never a Mission.

    Transport completion/source binding must come from the trusted journal,
    not model text. No live adapter is called, and this is not wired to Runtime.
    """
    if not isinstance(source, str) or not source.strip():
        return Decision(False, "INVALID_SOURCE")
    if not StructuralGuard().check(source).passed:
        return Decision(False, "GUARD_REJECT")
    try:
        checked = Mission.from_dict(candidate.to_dict())
        if (not MissionValidator().validate(checked).valid
                or any(step.execution_mode_override is not None for step in checked.steps)):
            return Decision(False, "INVALID_CANDIDATE")
    except Exception:
        return Decision(False, "INVALID_CANDIDATE")
    if provider_completed is not True:
        return Decision(False, "PROPOSAL_PROVIDER_UNAVAILABLE")
    if proposal_source_sha256 != source_digest(source):
        return Decision(False, "PROPOSAL_SOURCE_MISMATCH")
    try:
        proposal = parse_certificate(raw_proposal)
    except Exception:
        return Decision(False, "INVALID_PROPOSAL_CERTIFICATE")
    if proposal.status is not AuthorizationStatus.AUTHORIZED_UNIQUE:
        return Decision(False, "PROPOSAL_NOT_UNIQUE")
    if plan_digest(certificate_plan_mission(proposal)) != plan_digest(checked):
        return Decision(False, "PROPOSAL_CANDIDATE_DISAGREEMENT")
    return authority._verify_and_consume(receipt, source, checked, context_id)
