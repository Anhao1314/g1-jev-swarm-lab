"""Phase 2.2b Simplex canonical compiler router (Treatment D).

Frozen routing rule (protocol section 21):

1. Structural guard MALFORMED -> reject immediately, no LLM call.
2. Guard PASS -> run the frozen Phase 2.1 Lark compiler.
3. Lark SUCCESS -> return Mission IR, no LLM call.
4. Lark non-SUCCESS -> escalate to the LLM canonicalizer.
5. Canonicalizer SUCCESS -> compile ``canonical_text`` with the same Lark.
6. Canonicalized Lark SUCCESS -> return Mission IR.
7. Otherwise -> reject.

The router never repairs model output, never re-prompts, never retries a
semantic decision and never lets a canonicalization response skip the frozen
grammar: canonical text is only ever data for the Phase 2.1 compiler. Every
``compile`` call ends with at most one model invocation.

The return value intentionally mirrors ``CompilerResult`` (``status`` /
``mission`` / ``normalized_text`` / ``error_code`` / ``error_message`` /
``diagnostics``) so the frozen Phase 2.1/2.2 scoring harness can evaluate the
router without a special case. Routing detail lives in ``diagnostics`` and in
the typed fields below.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable

from ..language.compiler import LanguageCompiler
from ..language.errors import CompilerStatus, LanguageErrorCode
from ..language.normalization import normalize_text
from ..language.result import CompilerResult
from ..mission.ir import Mission

SIMPLEX_TREATMENT = "simplex_canonical"
ROUTER_VERSION = "2.2b.1"

GUARD_PASS = "PASS"
GUARD_SKIPPED = "SKIPPED"
GUARD_MALFORMED = "MALFORMED"
GUARD_ERROR = "ERROR"

CANONICAL_SUCCESS = "SUCCESS"
CANONICAL_AMBIGUOUS = "AMBIGUOUS"
CANONICAL_UNSUPPORTED = "UNSUPPORTED"
CANONICAL_MALFORMED = "MALFORMED"
CANONICAL_ERROR = "ERROR"

_FROZEN_STATUS_MAP = {
    "SUCCESS": CompilerStatus.SUCCESS,
    "AMBIGUOUS": CompilerStatus.AMBIGUOUS,
    "UNSUPPORTED": CompilerStatus.UNSUPPORTED,
    "MALFORMED": CompilerStatus.MALFORMED,
}


class SimplexRoute(str, Enum):
    """Which frozen branch produced the final result."""

    GUARD_REJECT = "GUARD_REJECT"
    LARK_FAST_PATH = "LARK_FAST_PATH"
    CANONICALIZED = "CANONICALIZED"
    CANONICALIZER_REFUSAL = "CANONICALIZER_REFUSAL"
    CANONICAL_LARK_REJECT = "CANONICAL_LARK_REJECT"


ESCALATION_ROUTES = frozenset(
    {
        SimplexRoute.CANONICALIZED,
        SimplexRoute.CANONICALIZER_REFUSAL,
        SimplexRoute.CANONICAL_LARK_REJECT,
    }
)
NO_LLM_ROUTES = frozenset({SimplexRoute.GUARD_REJECT, SimplexRoute.LARK_FAST_PATH})


@runtime_checkable
class StructuralGuardLike(Protocol):  # pragma: no cover - protocol
    def check(self, text: str) -> Any: ...


@runtime_checkable
class CanonicalizerLike(Protocol):  # pragma: no cover - protocol
    def canonicalize(self, text: str) -> Any: ...


@dataclass(frozen=True)
class SimplexResult:
    """Typed router result: a ``CompilerResult`` plus routing evidence."""

    status: CompilerStatus
    mission: Mission | None = None
    normalized_text: str = ""
    error_code: LanguageErrorCode | None = None
    error_message: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    route: SimplexRoute = SimplexRoute.CANONICALIZER_REFUSAL
    guard_status: str = GUARD_PASS
    guard_reason_code: str | None = None
    canonical_text: str | None = None
    canonicalization_status: str | None = None
    llm_invocations: int = 0
    provider_tokens: int | None = None
    latency_s: float = 0.0

    @property
    def success(self) -> bool:
        return self.status is CompilerStatus.SUCCESS and self.mission is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "mission": self.mission.to_dict() if self.mission is not None else None,
            "normalized_text": self.normalized_text,
            "error_code": self.error_code.value if self.error_code is not None else None,
            "error_message": self.error_message,
            "diagnostics": dict(self.diagnostics),
            "route": self.route.value,
            "guard_status": self.guard_status,
            "guard_reason_code": self.guard_reason_code,
            "canonical_text": self.canonical_text,
            "canonicalization_status": self.canonicalization_status,
            "llm_invocations": self.llm_invocations,
            "provider_tokens": self.provider_tokens,
            "latency_s": self.latency_s,
        }


@dataclass(frozen=True)
class _GuardOutcome:
    status: str
    reason_code: str | None = None
    error: str | None = None
    latency_s: float = 0.0


@dataclass(frozen=True)
class _CanonicalOutcome:
    status: str
    canonical_text: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    provider_tokens: int | None = None
    raw_response: str | None = None
    usage: Mapping[str, Any] | None = None
    error: str | None = None
    diagnostics: Mapping[str, Any] | None = None
    latency_s: float = 0.0


class SimplexRouter:
    """Frozen Treatment D router: Guard -> Lark -> Canonicalizer -> Lark."""

    name = "simplex_router"
    treatment = SIMPLEX_TREATMENT
    version = ROUTER_VERSION

    def __init__(
        self,
        *,
        canonicalizer: CanonicalizerLike,
        guard: StructuralGuardLike | None = None,
        lark_compiler: Any | None = None,
    ) -> None:
        if canonicalizer is None:
            raise ValueError("SimplexRouter requires a canonicalizer")
        self.canonicalizer = canonicalizer
        self.guard = guard
        self.lark = lark_compiler if lark_compiler is not None else LanguageCompiler()
        self.model = str(getattr(canonicalizer, "model", "unknown"))
        self.prompt_sha256 = getattr(canonicalizer, "prompt_sha256", None)
        self.prompt_path = getattr(canonicalizer, "prompt_path", None)
        self.prompt_version = getattr(canonicalizer, "prompt_version", None)

    # ------------------------------------------------------------------
    def compile(self, text: str) -> SimplexResult:
        started = time.perf_counter()
        latencies: dict[str, float | None] = {
            "guard_s": None,
            "lark_s": None,
            "canonicalizer_s": None,
            "canonical_lark_s": None,
        }
        normalized = normalize_text(text) if isinstance(text, str) else ""

        if not isinstance(text, str) or not normalized:
            return self._result(
                status=CompilerStatus.MALFORMED,
                route=SimplexRoute.GUARD_REJECT,
                normalized=normalized,
                guard_status=GUARD_MALFORMED,
                guard_reason_code="EMPTY_INPUT",
                error_code=LanguageErrorCode.EMPTY_LANGUAGE_INPUT,
                error_message="language input is empty",
                diagnostics={"treatment": SIMPLEX_TREATMENT, "router_version": ROUTER_VERSION},
                latencies=latencies,
                started=started,
            )

        # Stage 1: trusted structural monitor. It never decides semantics; it
        # only blocks structurally malformed source language before any model.
        guard_outcome = self._run_guard(text)
        latencies["guard_s"] = guard_outcome.latency_s
        guard_status = guard_outcome.status
        if guard_outcome.error is not None:
            return self._result(
                status=CompilerStatus.MALFORMED,
                route=SimplexRoute.GUARD_REJECT,
                normalized=normalized,
                guard_status=GUARD_ERROR,
                guard_reason_code="GUARD_ERROR",
                error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
                error_message=f"structural guard failed closed: {guard_outcome.error}",
                diagnostics={
                    "treatment": SIMPLEX_TREATMENT,
                    "router_version": ROUTER_VERSION,
                    "failure_type": "GUARD_ERROR",
                    "guard_error": guard_outcome.error,
                },
                latencies=latencies,
                started=started,
            )
        if guard_status not in {GUARD_PASS, GUARD_SKIPPED}:
            return self._result(
                status=CompilerStatus.MALFORMED,
                route=SimplexRoute.GUARD_REJECT,
                normalized=normalized,
                guard_status=GUARD_MALFORMED,
                guard_reason_code=guard_outcome.reason_code,
                error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
                error_message=(
                    "structural guard rejected malformed source language"
                    + (f": {guard_outcome.reason_code}" if guard_outcome.reason_code else "")
                ),
                diagnostics={
                    "treatment": SIMPLEX_TREATMENT,
                    "router_version": ROUTER_VERSION,
                    "failure_type": "MALFORMED_INPUT",
                    "guard_reason_code": guard_outcome.reason_code,
                },
                latencies=latencies,
                started=started,
            )

        # Stage 2: frozen deterministic compiler is the fast path and the only
        # authority for the direct branch.
        lark_started = time.perf_counter()
        lark_result = self._compile_frozen(text)
        latencies["lark_s"] = time.perf_counter() - lark_started
        if lark_result.success:
            return self._result(
                status=CompilerStatus.SUCCESS,
                route=SimplexRoute.LARK_FAST_PATH,
                normalized=lark_result.normalized_text or normalized,
                mission=lark_result.mission,
                guard_status=guard_status,
                diagnostics={
                    "treatment": SIMPLEX_TREATMENT,
                    "router_version": ROUTER_VERSION,
                    "lark_status": lark_result.status.value,
                    "lark_fast_path": True,
                },
                latencies=latencies,
                started=started,
            )

        # Stage 3: escalate non-success to the LLM canonicalizer. The model may
        # propose controlled language only; it never sees Mission IR authority.
        canonical_started = time.perf_counter()
        canonical_outcome = self._run_canonicalizer(text)
        latencies["canonicalizer_s"] = time.perf_counter() - canonical_started
        llm_invocations = 1
        if canonical_outcome.error is not None:
            return self._result(
                status=CompilerStatus.MALFORMED,
                route=SimplexRoute.CANONICALIZER_REFUSAL,
                normalized=normalized,
                guard_status=guard_status,
                canonicalization_status=CANONICAL_ERROR,
                error_code=LanguageErrorCode.LLM_API_ERROR,
                error_message=f"canonicalizer failed closed: {canonical_outcome.error}",
                diagnostics={
                    "treatment": SIMPLEX_TREATMENT,
                    "router_version": ROUTER_VERSION,
                    "failure_type": "CANONICALIZER_ERROR",
                    "lark_status": lark_result.status.value,
                    "canonicalizer_error": canonical_outcome.error,
                    **_canonicalizer_evidence(canonical_outcome),
                },
                llm_invocations=llm_invocations,
                latencies=latencies,
                started=started,
            )

        if canonical_outcome.status != CANONICAL_SUCCESS or not canonical_outcome.canonical_text:
            status = _FROZEN_STATUS_MAP.get(canonical_outcome.status, CompilerStatus.MALFORMED)
            return self._result(
                status=status,
                route=SimplexRoute.CANONICALIZER_REFUSAL,
                normalized=normalized,
                guard_status=guard_status,
                canonicalization_status=canonical_outcome.status,
                error_code=_error_code_for(status),
                error_message=(
                    canonical_outcome.error_message
                    or f"canonicalizer returned {canonical_outcome.status}"
                ),
                diagnostics={
                    "treatment": SIMPLEX_TREATMENT,
                    "router_version": ROUTER_VERSION,
                    "failure_type": "CANONICALIZER_REFUSAL",
                    "lark_status": lark_result.status.value,
                    "canonicalizer_status": canonical_outcome.status,
                    "canonicalizer_error_code": canonical_outcome.error_code,
                    **_canonicalizer_evidence(canonical_outcome),
                },
                llm_invocations=llm_invocations,
                provider_tokens=canonical_outcome.provider_tokens,
                latencies=latencies,
                started=started,
                raw_response=canonical_outcome.raw_response,
            )

        # Stage 4: canonical text is data for the same frozen grammar. A parse
        # failure is a rejection, never a second model call.
        canonical_text = canonical_outcome.canonical_text
        second_started = time.perf_counter()
        canonical_lark_result = self._compile_frozen(canonical_text)
        latencies["canonical_lark_s"] = time.perf_counter() - second_started
        if canonical_lark_result.success:
            return self._result(
                status=CompilerStatus.SUCCESS,
                route=SimplexRoute.CANONICALIZED,
                normalized=canonical_lark_result.normalized_text or canonical_text,
                mission=canonical_lark_result.mission,
                guard_status=guard_status,
                canonical_text=canonical_text,
                canonicalization_status=CANONICAL_SUCCESS,
                diagnostics={
                    "treatment": SIMPLEX_TREATMENT,
                    "router_version": ROUTER_VERSION,
                    "lark_status": lark_result.status.value,
                    "canonical_lark_status": canonical_lark_result.status.value,
                    "canonical_text_lark_accepted": True,
                    **_canonicalizer_evidence(canonical_outcome),
                },
                llm_invocations=llm_invocations,
                provider_tokens=canonical_outcome.provider_tokens,
                latencies=latencies,
                started=started,
                raw_response=canonical_outcome.raw_response,
            )

        return self._result(
            status=CompilerStatus.MALFORMED,
            route=SimplexRoute.CANONICAL_LARK_REJECT,
            normalized=normalized,
            guard_status=guard_status,
            canonical_text=canonical_text,
            canonicalization_status=CANONICAL_SUCCESS,
            error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
            error_message=(
                "canonical text was rejected by the frozen Phase 2.1 grammar: "
                f"{canonical_lark_result.error_message or canonical_lark_result.status.value}"
            ),
            diagnostics={
                "treatment": SIMPLEX_TREATMENT,
                "router_version": ROUTER_VERSION,
                "failure_type": "CANONICAL_LARK_REJECT",
                "lark_status": lark_result.status.value,
                "canonical_lark_status": canonical_lark_result.status.value,
                "canonical_text_lark_accepted": False,
                    **_canonicalizer_evidence(canonical_outcome),
            },
            llm_invocations=llm_invocations,
            provider_tokens=canonical_outcome.provider_tokens,
            latencies=latencies,
            started=started,
            raw_response=canonical_outcome.raw_response,
        )

    # ------------------------------------------------------------------
    def _run_guard(self, text: str) -> _GuardOutcome:
        if self.guard is None:
            return _GuardOutcome(status=GUARD_SKIPPED, latency_s=0.0)
        checker = getattr(self.guard, "check", None)
        if checker is None and callable(self.guard):
            checker = self.guard
        if checker is None:
            return _GuardOutcome(
                status=GUARD_ERROR, error="guard has no check() method", latency_s=0.0
            )
        started = time.perf_counter()
        try:
            raw = checker(text)
        except Exception as exc:  # fail closed: no LLM without a guard verdict
            return _GuardOutcome(
                status=GUARD_ERROR,
                error=f"{type(exc).__name__}: {exc}",
                latency_s=time.perf_counter() - started,
            )
        latency_s = time.perf_counter() - started
        status = _enum_text(_field(raw, "status", None))
        if status is None:
            if raw is True:
                status = GUARD_PASS
            elif raw is False:
                status = GUARD_MALFORMED
        if status is None:
            return _GuardOutcome(
                status=GUARD_ERROR,
                error="guard result has no typed status",
                latency_s=latency_s,
            )
        status = status.strip().upper()
        if status not in {GUARD_PASS, GUARD_MALFORMED}:
            return _GuardOutcome(
                status=GUARD_ERROR,
                error=f"unknown guard status {status!r}",
                latency_s=latency_s,
            )
        reason = _enum_text(_field(raw, "reason_code", None))
        return _GuardOutcome(
            status=status,
            reason_code=reason.strip().upper() if isinstance(reason, str) and reason.strip() else None,
            latency_s=latency_s,
        )

    def _run_canonicalizer(self, text: str) -> _CanonicalOutcome:
        call = getattr(self.canonicalizer, "canonicalize", None)
        if call is None and callable(self.canonicalizer):
            call = self.canonicalizer
        if call is None:
            return _CanonicalOutcome(
                status=CANONICAL_ERROR, error="canonicalizer has no canonicalize() method"
            )
        started = time.perf_counter()
        try:
            raw = call(text)
        except Exception as exc:  # transport or contract failure: fail closed
            return _CanonicalOutcome(
                status=CANONICAL_ERROR,
                error=f"{type(exc).__name__}: {exc}",
                latency_s=time.perf_counter() - started,
            )
        latency_s = time.perf_counter() - started
        status = _enum_text(_field(raw, "status", None))
        if status is None:
            return _CanonicalOutcome(
                status=CANONICAL_ERROR,
                error="canonicalizer result has no typed status",
                latency_s=latency_s,
            )
        status = status.strip().upper()
        canonical_text = _field(raw, "canonical_text", None)
        if not isinstance(canonical_text, str) or not canonical_text.strip():
            canonical_text = None
        usage = _field(raw, "usage", None)
        diagnostics = _field(raw, "diagnostics", None)
        error_text = _text_or_none(_field(raw, "error", None))
        if status == CANONICAL_ERROR and error_text is None:
            error_text = _text_or_none(_field(raw, "error_message", None))
        return _CanonicalOutcome(
            status=status,
            canonical_text=canonical_text.strip() if canonical_text else None,
            error_code=_enum_text(_field(raw, "error_code", None)),
            error_message=_text_or_none(_field(raw, "error_message", None)),
            provider_tokens=_provider_tokens(raw, usage),
            raw_response=_text_or_none(
                _field(raw, "raw_response", None)
                or (diagnostics.get("raw_response") if isinstance(diagnostics, Mapping) else None)
            ),
            usage=usage if isinstance(usage, Mapping) else None,
            diagnostics=diagnostics if isinstance(diagnostics, Mapping) else None,
            error=error_text,
            latency_s=latency_s,
        )

    def _compile_frozen(self, text: str) -> CompilerResult:
        try:
            result = self.lark.compile(text)
        except Exception as exc:  # pragma: no cover - defensive boundary
            return CompilerResult(
                status=CompilerStatus.MALFORMED,
                mission=None,
                normalized_text="",
                error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
                error_message=f"frozen compiler raised {type(exc).__name__}",
            )
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _result(
        *,
        status: CompilerStatus,
        route: SimplexRoute,
        normalized: str,
        guard_status: str,
        error_code: LanguageErrorCode | None = None,
        error_message: str | None = None,
        diagnostics: Mapping[str, Any] | None = None,
        mission: Mission | None = None,
        canonical_text: str | None = None,
        canonicalization_status: str | None = None,
        llm_invocations: int = 0,
        provider_tokens: int | None = None,
        latencies: Mapping[str, float | None] | None = None,
        started: float | None = None,
        guard_reason_code: str | None = None,
        raw_response: str | None = None,
    ) -> SimplexResult:
        total_latency = (time.perf_counter() - started) if started is not None else 0.0
        stage_latency = {
            key: value for key, value in dict(latencies or {}).items() if value is not None
        }
        payload = dict(diagnostics or {})
        payload.update(
            {
                "route": route.value,
                "guard_status": guard_status,
                "guard_missing": guard_status == GUARD_SKIPPED,
                "guard_reason_code": guard_reason_code,
                "canonicalization_status": canonicalization_status,
                "llm_invocations": int(llm_invocations),
                "provider_tokens": provider_tokens,
                "latency_s": total_latency,
                "stage_latency_s": stage_latency,
            }
        )
        if raw_response is not None:
            payload["raw_response"] = raw_response
        return SimplexResult(
            status=status,
            mission=mission,
            normalized_text=normalized,
            error_code=error_code,
            error_message=error_message,
            diagnostics=payload,
            route=route,
            guard_status=guard_status,
            guard_reason_code=guard_reason_code,
            canonical_text=canonical_text,
            canonicalization_status=canonicalization_status,
            llm_invocations=int(llm_invocations),
            provider_tokens=provider_tokens,
            latency_s=total_latency,
        )


# ----------------------------------------------------------------------
def _field(raw: Any, name: str, default: Any) -> Any:
    if isinstance(raw, Mapping):
        return raw.get(name, default)
    return getattr(raw, name, default)


def _enum_text(value: Any) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", value)
    if isinstance(enum_value, str):
        return enum_value
    return str(enum_value)


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _provider_tokens(raw: Any, usage: Any) -> int | None:
    candidate = _field(raw, "provider_tokens", None)
    if candidate is None:
        candidate = _field(raw, "total_tokens", None)
    if candidate is None and isinstance(usage, Mapping):
        candidate = usage.get("total_tokens")
    if isinstance(candidate, bool):
        return None
    if isinstance(candidate, int):
        return candidate if candidate >= 0 else None
    if isinstance(candidate, float) and candidate >= 0 and float(candidate).is_integer():
        return int(candidate)
    return None


def _canonicalizer_evidence(outcome: _CanonicalOutcome) -> dict[str, Any]:
    diagnostics = dict(outcome.diagnostics or {})
    evidence: dict[str, Any] = {}
    failure_type = diagnostics.get("failure_type")
    if failure_type:
        evidence["canonicalizer_failure_type"] = failure_type
    if diagnostics:
        evidence["canonicalizer_diagnostics"] = diagnostics
    if outcome.usage is not None:
        evidence["canonicalizer_usage"] = dict(outcome.usage)
    return evidence


def _error_code_for(status: CompilerStatus) -> LanguageErrorCode:
    if status is CompilerStatus.AMBIGUOUS:
        return LanguageErrorCode.AMBIGUOUS_COMMAND
    if status is CompilerStatus.UNSUPPORTED:
        return LanguageErrorCode.UNSUPPORTED_LANGUAGE_CAPABILITY
    return LanguageErrorCode.LANGUAGE_PARSE_ERROR


__all__ = [
    "ESCALATION_ROUTES",
    "GUARD_MALFORMED",
    "GUARD_PASS",
    "GUARD_SKIPPED",
    "NO_LLM_ROUTES",
    "ROUTER_VERSION",
    "SIMPLEX_TREATMENT",
    "SimplexResult",
    "SimplexRoute",
    "SimplexRouter",
]
