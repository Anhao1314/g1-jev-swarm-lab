"""Rejection-capable Phase 2.4 language authorization; never executes missions."""

from .authorization import (
    AUTHORITY_DIMENSIONS,
    AuthorizationResult,
    AuthorizationStatus,
    LLMSemanticAmbiguityGate,
    LLMSourceAuthorizationVerifier,
    apply_gate,
    source_authorization,
)

__all__ = [
    "AUTHORITY_DIMENSIONS",
    "AuthorizationResult",
    "AuthorizationStatus",
    "LLMSemanticAmbiguityGate",
    "LLMSourceAuthorizationVerifier",
    "apply_gate",
    "source_authorization",
]
