"""Narrow host-owned support extracted for the TEST_ONLY handoff adapter.

This module deliberately excludes certificate issuers, bounded-language release,
model providers and production authorization. Registered request objects and
their one-use claim semantics come from Source Authority Handoff v0.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import secrets
from threading import Lock
from typing import Any


class Origin(str, Enum):
    BOUNDED = "BOUNDED_SOURCE_DERIVATION"
    PRINCIPAL = "EXPLICIT_PRINCIPAL_PLAN_AUTHORIZATION"


SCOPES = {
    Origin.BOUNDED: "UNIQUENESS_UNDER_FROZEN_BOUNDED_LANGUAGE",
    Origin.PRINCIPAL: "NEW_EXPLICIT_PLAN_INSTRUCTION_NOT_SOURCE_UNIQUENESS",
}


def source_digest(source: str) -> str:
    return hashlib.sha256(source.encode("utf8")).hexdigest()


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


@dataclass(frozen=True)
class ReleaseRequestContext:
    context_id: str
    source_sha256: str


_lock = Lock()
_active: dict[str, ReleaseRequestContext] = {}


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
