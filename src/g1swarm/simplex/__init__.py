"""Phase 2.2b neuro-symbolic / simplex mission compiler package.

The simplex architecture keeps learned coverage and deterministic authority in
separate layers: an LLM canonicalizer may only propose controlled language,
the frozen Phase 2.1 grammar produces Mission IR, and the router decides which
inputs are allowed to escalate to the model at all.
"""

from __future__ import annotations

from .canonical import (
    CanonicalizationCode,
    CanonicalizationError,
    canonicalize_mission,
    comparison_hash,
    comparison_payload,
)
from .canonicalizer import (
    CanonicalizerEnvelope,
    CanonicalizerOutcome,
    LLMMissionCanonicalizer,
    parse_canonicalizer_envelope,
)
from .metrics import (
    comparison_row,
    evaluate_hard_gates,
    evaluate_simplex_sample,
    summarize_simplex_results,
)
from .router import (
    SIMPLEX_TREATMENT,
    SimplexResult,
    SimplexRoute,
    SimplexRouter,
)
from .structural_guard import (
    GuardReason,
    GuardResult,
    GuardStatus,
    StructuralGuard,
    check_structure,
)

__all__ = [
    "CanonicalizationCode",
    "CanonicalizationError",
    "CanonicalizerEnvelope",
    "CanonicalizerOutcome",
    "GuardReason",
    "GuardResult",
    "GuardStatus",
    "LLMMissionCanonicalizer",
    "SIMPLEX_TREATMENT",
    "SimplexResult",
    "SimplexRoute",
    "SimplexRouter",
    "StructuralGuard",
    "canonicalize_mission",
    "check_structure",
    "comparison_hash",
    "comparison_payload",
    "comparison_row",
    "evaluate_hard_gates",
    "evaluate_simplex_sample",
    "parse_canonicalizer_envelope",
    "summarize_simplex_results",
]
