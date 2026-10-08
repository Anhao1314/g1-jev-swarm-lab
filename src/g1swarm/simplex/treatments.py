"""Treatments A-D for the Phase 2.2b architecture comparison.

Every treatment exposes the same ``compile(text) -> CompilerResult`` surface.
The only differences are the architecture around the shared model backend,
frozen Phase 2.1 grammar and Mission IR validator.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..language.compiler import LanguageCompiler
from ..language.errors import CompilerStatus, LanguageErrorCode
from ..language.result import CompilerResult
from ..llm.compiler import LLMMissionCompiler
from .canonicalizer import (
    CanonicalizerOutcome,
    LLMMissionCanonicalizer,
    STATUS_ERROR,
    STATUS_SUCCESS,
)
from .router import SimplexResult, SimplexRouter
from .structural_guard import GuardStatus, StructuralGuard

TREATMENT_DIRECT = "direct_llm_v1"
TREATMENT_GUARDED = "guarded_direct_llm_v1"
TREATMENT_BRIDGE = "canonical_bridge"
TREATMENT_SIMPLEX = "simplex_canonical"


def _guard_reject(guard_result, architecture: str) -> CompilerResult:
    reason = getattr(getattr(guard_result, "reason_code", None), "value", None)
    return CompilerResult(
        status=CompilerStatus.MALFORMED,
        mission=None,
        normalized_text="",
        error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
        error_message=f"structural guard rejected input: {reason or guard_result}",
        diagnostics={
            "architecture": architecture,
            "route": "GUARD_REJECT",
            "guard_status": getattr(getattr(guard_result, "status", None), "value", None),
            "guard_reason_code": reason,
            "llm_invocations": 0,
            "lark_calls": 0,
        },
    )


def _canonical_to_result(
    outcome: CanonicalizerOutcome,
    *,
    architecture: str,
    canonical_lark: CompilerResult | None,
    canonical_text: str | None,
    lark_calls: int,
) -> CompilerResult:
    llm_invocations = 1 if outcome.raw_response is not None or outcome.diagnostics.get("attempts") else 0
    base_diagnostics = {
        "architecture": architecture,
        "route": "CANONICALIZED" if canonical_lark is not None and canonical_lark.success else "CANONICAL_REFUSAL",
        "canonicalizer_status": outcome.status,
        "canonical_text": canonical_text,
        "provider_tokens": outcome.provider_tokens,
        "llm_invocations": llm_invocations,
        "lark_calls": lark_calls,
        "canonicalizer_diagnostics": dict(outcome.diagnostics),
        "raw_response": outcome.raw_response,
    }
    if outcome.status == STATUS_ERROR:
        return CompilerResult(
            status=CompilerStatus.MALFORMED,
            mission=None,
            normalized_text="",
            error_code=LanguageErrorCode.LLM_API_ERROR,
            error_message=outcome.error or "canonicalizer API error",
            diagnostics=base_diagnostics,
        )
    if outcome.status != STATUS_SUCCESS or not canonical_text:
        status = {
            "AMBIGUOUS": CompilerStatus.AMBIGUOUS,
            "UNSUPPORTED": CompilerStatus.UNSUPPORTED,
            "MALFORMED": CompilerStatus.MALFORMED,
        }.get(outcome.status, CompilerStatus.MALFORMED)
        error_code = LanguageErrorCode(outcome.error_code) if outcome.error_code else None
        return CompilerResult(
            status=status,
            mission=None,
            normalized_text=canonical_text or "",
            error_code=error_code,
            error_message=outcome.error_message or f"canonicalizer returned {outcome.status}",
            diagnostics=base_diagnostics,
        )
    if canonical_lark is None or not canonical_lark.success:
        reason = canonical_lark.error_message if canonical_lark is not None else "no Lark result"
        return CompilerResult(
            status=CompilerStatus.MALFORMED,
            mission=None,
            normalized_text=canonical_text,
            error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
            error_message=f"canonical text rejected by frozen grammar: {reason}",
            diagnostics=base_diagnostics,
        )
    base_diagnostics["route"] = "CANONICALIZED"
    return CompilerResult(
        status=CompilerStatus.SUCCESS,
        mission=canonical_lark.mission,
        normalized_text=canonical_lark.normalized_text or canonical_text,
        diagnostics=base_diagnostics,
    )


@dataclass
class Architecture:
    name: str
    backend: Any

    def __post_init__(self) -> None:
        self.treatment = self.name
    def compile(self, text: str) -> CompilerResult:  # pragma: no cover - abstract
        raise NotImplementedError


class DirectLLMTreatment(Architecture):
    def __init__(self, llm_compiler: LLMMissionCompiler) -> None:
        super().__init__(TREATMENT_DIRECT, getattr(llm_compiler, "backend", None))
        self.llm_compiler = llm_compiler

    def compile(self, text: str) -> CompilerResult:
        result = self.llm_compiler.compile(text)
        diagnostics = dict(result.diagnostics)
        diagnostics.update(
            {
                "architecture": TREATMENT_DIRECT,
                "route": "DIRECT_LLM",
                "llm_invocations": 1 if diagnostics.get("raw_response") is not None else 0,
                "lark_calls": 0,
            }
        )
        return CompilerResult(
            status=result.status,
            mission=result.mission,
            normalized_text=result.normalized_text,
            error_code=result.error_code,
            error_message=result.error_message,
            diagnostics=diagnostics,
        )


class GuardedDirectLLMTreatment(Architecture):
    def __init__(self, guard: StructuralGuard, llm_compiler: LLMMissionCompiler) -> None:
        super().__init__(TREATMENT_GUARDED, getattr(llm_compiler, "backend", None))
        self.guard = guard
        self.llm_compiler = llm_compiler

    def compile(self, text: str) -> CompilerResult:
        guard_result = self.guard.check(text)
        if guard_result.status is GuardStatus.MALFORMED:
            return _guard_reject(guard_result, TREATMENT_GUARDED)
        result = self.llm_compiler.compile(text)
        diagnostics = dict(result.diagnostics)
        diagnostics.update(
            {
                "architecture": TREATMENT_GUARDED,
                "route": "GUARDED_DIRECT_LLM",
                "guard_status": guard_result.status.value,
                "guard_reason_code": None,
                "llm_invocations": 1 if diagnostics.get("raw_response") is not None else 0,
                "lark_calls": 0,
            }
        )
        return CompilerResult(
            status=result.status,
            mission=result.mission,
            normalized_text=result.normalized_text,
            error_code=result.error_code,
            error_message=result.error_message,
            diagnostics=diagnostics,
        )


class CanonicalBridgeTreatment(Architecture):
    def __init__(
        self,
        guard: StructuralGuard,
        canonicalizer: LLMMissionCanonicalizer,
        lark_compiler: LanguageCompiler | None = None,
    ) -> None:
        super().__init__(TREATMENT_BRIDGE, getattr(canonicalizer, "backend", None))
        self.guard = guard
        self.canonicalizer = canonicalizer
        self.lark = lark_compiler or LanguageCompiler()

    def compile(self, text: str) -> CompilerResult:
        guard_result = self.guard.check(text)
        if guard_result.status is GuardStatus.MALFORMED:
            return _guard_reject(guard_result, TREATMENT_BRIDGE)
        outcome = self.canonicalizer.canonicalize(text)
        canonical_text = outcome.canonical_text
        canonical_lark = None
        lark_calls = 0
        if outcome.status == STATUS_SUCCESS and canonical_text:
            lark_calls = 1
            canonical_lark = self.lark.compile(canonical_text)
        return _canonical_to_result(
            outcome,
            architecture=TREATMENT_BRIDGE,
            canonical_lark=canonical_lark,
            canonical_text=canonical_text,
            lark_calls=lark_calls,
        )


class SimplexCanonicalTreatment(Architecture):
    def __init__(
        self,
        guard: StructuralGuard,
        canonicalizer: LLMMissionCanonicalizer,
        lark_compiler: LanguageCompiler | None = None,
    ) -> None:
        super().__init__(TREATMENT_SIMPLEX, getattr(canonicalizer, "backend", None))
        self.router = SimplexRouter(
            canonicalizer=canonicalizer,
            guard=guard,
            lark_compiler=lark_compiler,
        )

    def compile(self, text: str) -> CompilerResult:
        result: SimplexResult = self.router.compile(text)
        diagnostics = dict(result.diagnostics)
        diagnostics.setdefault("architecture", TREATMENT_SIMPLEX)
        diagnostics.setdefault("llm_invocations", result.llm_invocations)
        diagnostics.setdefault("lark_calls", 0 if result.route.value == "GUARD_REJECT" else 1)
        return CompilerResult(
            status=result.status,
            mission=result.mission,
            normalized_text=result.normalized_text,
            error_code=result.error_code,
            error_message=result.error_message,
            diagnostics=diagnostics,
        )


def all_treatment_names() -> tuple[str, ...]:
    return (TREATMENT_DIRECT, TREATMENT_GUARDED, TREATMENT_BRIDGE, TREATMENT_SIMPLEX)


__all__ = [
    "Architecture",
    "CanonicalBridgeTreatment",
    "DirectLLMTreatment",
    "GuardedDirectLLMTreatment",
    "SimplexCanonicalTreatment",
    "TREATMENT_BRIDGE",
    "TREATMENT_DIRECT",
    "TREATMENT_GUARDED",
    "TREATMENT_SIMPLEX",
    "all_treatment_names",
]
