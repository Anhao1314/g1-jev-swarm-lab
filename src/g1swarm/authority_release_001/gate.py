"""Host request lifecycle and the existing independent-authority contract.

No Runtime or human authorization channel is added. Contexts are host-owned
one-shot capabilities, not model fields. A new process has no old registered
contexts, so it refuses old context objects/receipts. Authority services and
their keys remain trusted host configuration. The default service supports
only the existing bounded derivation and is shared across requests.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import secrets
from threading import Lock
from typing import Any

from ..authority_certificate_v2 import SourceAuthorityCertificateIssuer
from ..authority_mechanism_001.contract import AuthorityService, Decision, evaluate_release, source_digest
from ..source_authority import AuthorizationResult
from ..source_authority_bounded import BoundedSourceAuthorizationVerifier


@dataclass(frozen=True)
class ReleaseRequestContext:
    context_id: str
    source_sha256: str


_lock = Lock()
_active: dict[str, ReleaseRequestContext] = {}
_default_service: AuthorityService | None = None


def begin_release_request(source: str) -> ReleaseRequestContext:
    """Create a trusted one-shot request before deriving an optional receipt."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("release request requires an original nonempty source")
    context = ReleaseRequestContext(secrets.token_hex(32), source_digest(source))
    with _lock:
        _active[context.context_id] = context
    return context


def is_current_request(source: str, context: Any) -> bool:
    """Read-only presentation precondition; never establishes principal identity."""
    if type(context) is not ReleaseRequestContext:
        return False
    with _lock:
        return (_active.get(context.context_id) is context
                and context.source_sha256 == source_digest(source))


def claim_request(source: str, context: Any) -> tuple[ReleaseRequestContext | None, Decision | None]:
    if context is None:
        context = begin_release_request(source)
    if type(context) is not ReleaseRequestContext:
        return None, Decision(False, "UNTRUSTED_REQUEST_CONTEXT")
    with _lock:
        if _active.get(context.context_id) is not context:
            return None, Decision(False, "REQUEST_CONTEXT_UNTRUSTED_OR_REPLAYED")
        if context.source_sha256 != source_digest(source):
            return None, Decision(False, "REQUEST_CONTEXT_SOURCE_MISMATCH")
        del _active[context.context_id]
    return context, None


def default_service() -> AuthorityService:
    global _default_service
    with _lock:
        if _default_service is None:
            _default_service = AuthorityService()
        return _default_service


def independent_decision(*, source, candidate, proposal: AuthorizationResult, authorizer,
                         context: ReleaseRequestContext, service, receipt,
                         derive_bounded_authority: bool) -> Decision:
    """Called only after the common Guard/IR/mutation and proposal checks.

    v2 uses the frozen complete offline contract. The existing deterministic
    bounded-only control has no provider proposal; after its unchanged full
    source check, it still needs the same source/complete-plan/context receipt.
    Generic model/custom authorizers cannot supply executable authority.
    """
    if type(authorizer) not in (SourceAuthorityCertificateIssuer, BoundedSourceAuthorizationVerifier):
        return Decision(False, "V2_PROPOSAL_OR_BOUNDED_DERIVATION_REQUIRED")
    service = default_service() if service is None else service
    if type(service) is not AuthorityService:
        return Decision(False, "UNTRUSTED_AUTHORITY_SERVICE")
    if isinstance(receipt, dict) and receipt.get("origin") == "EXPLICIT_PRINCIPAL_PLAN_AUTHORIZATION":
        # The old MAC prototype has no identity, presentation or expiry proof.
        # Keep its low-level offline contract intact, but do not grant public
        # human authority through it. Use the explicit principal channel.
        return Decision(False, "PRINCIPAL_CONFIRMATION_CHANNEL_REQUIRED")
    if receipt is None and derive_bounded_authority is True:
        receipt = service.derive_bounded_receipt(source, context.context_id)
    else:
        receipt = copy.deepcopy(receipt)
    if type(authorizer) is BoundedSourceAuthorizationVerifier:
        # Common live gate checks and the unchanged full-source bounded control
        # have already passed. This is the deterministic, zero-provider route.
        return service._verify_and_consume(receipt, source, candidate, context.context_id)
    evidence = proposal.diagnostics
    completed = (evidence.get("provider_status") == "completed"
                 and evidence.get("finish_reason") in {"completed", "stop", "end_turn", "eos_token"})
    return evaluate_release(source=source, candidate=candidate,
        raw_proposal=evidence.get("raw_response"), provider_completed=completed,
        proposal_source_sha256=evidence.get("source_sha256"), receipt=receipt,
        context_id=context.context_id, authority=service)
