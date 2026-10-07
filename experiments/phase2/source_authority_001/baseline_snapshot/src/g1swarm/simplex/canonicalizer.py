"""Phase 2.2b LLM mission canonicalizer.

Translates one open Chinese utterance into the frozen Phase 2.1 controlled
language, or returns a typed refusal. It never produces Mission IR, step ids,
dependencies, execution modes, risks, controller parameters or robot actions:
the only mission-shaped authority in Phase 2.2b remains the frozen Lark
compiler in ``g1swarm.language.compiler``.

The adapter mirrors the Phase 2.2 LLM compiler contract:

- one frozen system prompt, optionally digest-checked by the caller
- exactly one model call, never a repair loop and never a re-prompt
- exactly one JSON envelope with exact keys and a status/error-code pairing
  that is consistent with the frozen language taxonomy
- raw model text is retained as data for evidence and never executed
- transport failures fail closed with status ``ERROR``

``SimplexRouter`` consumes the returned :class:`CanonicalizerOutcome` through
its duck-typed ``canonicalize`` interface.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..language.errors import LanguageErrorCode
from ..language.normalization import normalize_text
from ..llm.backend import (
    FAILURE_API_ERROR,
    LLMBackend,
    LLMBackendError,
    LLMConfigurationError,
)
from ..paths import resolve_repo_path

CANONICALIZER_VERSION = "2.2b.1"
DEFAULT_PROMPT_PATH = "prompts/llm_mission_canonicalizer_v1.txt"
DEFAULT_PROMPT_VERSION = "llm_mission_canonicalizer_v1"
DEFAULT_MAX_INPUT_CHARS = 512
DEFAULT_MAX_OUTPUT_CHARS = 2048
DEFAULT_MAX_CANONICAL_CHARS = 512

STATUS_SUCCESS = "SUCCESS"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_UNSUPPORTED = "UNSUPPORTED"
STATUS_MALFORMED = "MALFORMED"
STATUS_ERROR = "ERROR"

MODEL_STATUSES = (STATUS_SUCCESS, STATUS_AMBIGUOUS, STATUS_UNSUPPORTED, STATUS_MALFORMED)
ENVELOPE_KEYS = frozenset({"status", "canonical_text", "error_code"})

STATUS_TO_ERROR_CODES: dict[str, frozenset[str]] = {
    STATUS_AMBIGUOUS: frozenset(
        {LanguageErrorCode.AMBIGUOUS_COMMAND.value, LanguageErrorCode.MISSING_PARAMETER.value}
    ),
    STATUS_UNSUPPORTED: frozenset({LanguageErrorCode.UNSUPPORTED_LANGUAGE_CAPABILITY.value}),
    STATUS_MALFORMED: frozenset(
        {
            LanguageErrorCode.INVALID_UNIT.value,
            LanguageErrorCode.MALFORMED_NUMBER.value,
            LanguageErrorCode.CONTRADICTORY_COMMAND.value,
            LanguageErrorCode.LANGUAGE_PARSE_ERROR.value,
            LanguageErrorCode.EMPTY_LANGUAGE_INPUT.value,
            LanguageErrorCode.INPUT_TOO_LONG.value,
        }
    ),
}
MODEL_ERROR_CODES = frozenset(
    code for codes in STATUS_TO_ERROR_CODES.values() for code in codes
)

FAILURE_MALFORMED_OUTPUT = "MALFORMED_OUTPUT"


class CanonicalizerContractError(ValueError):
    """The model response violated the frozen canonicalizer JSON contract."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.failure_type = FAILURE_MALFORMED_OUTPUT
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class CanonicalizerEnvelope:
    """A contract-valid canonicalizer envelope."""

    status: str
    canonical_text: str | None
    error_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "canonical_text": self.canonical_text,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class CanonicalizerOutcome:
    """Typed result consumed by ``SimplexRouter`` and evidence scripts."""

    status: str
    canonical_text: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    provider_tokens: int | None = None
    raw_response: str | None = None
    usage: Mapping[str, Any] | None = None
    error: str | None = None
    latency_s: float = 0.0
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == STATUS_SUCCESS and bool(self.canonical_text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "canonical_text": self.canonical_text,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "provider_tokens": self.provider_tokens,
            "raw_response": self.raw_response,
            "usage": dict(self.usage) if self.usage is not None else None,
            "error": self.error,
            "latency_s": self.latency_s,
            "diagnostics": dict(self.diagnostics),
        }


def _reject_constant(name: str) -> float:
    raise CanonicalizerContractError(
        "non_finite_number",
        f"non-finite JSON constant {name!r} is not allowed",
    )


def parse_canonicalizer_envelope(
    text: str,
    *,
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    max_canonical_chars: int = DEFAULT_MAX_CANONICAL_CHARS,
) -> CanonicalizerEnvelope:
    """Parse exactly one contract-valid canonicalizer envelope or raise."""

    def reject(reason: str, message: str) -> None:
        raise CanonicalizerContractError(reason, message)

    if not isinstance(text, str):
        reject("output_not_text", f"model output must be a string, got {type(text).__name__}")
    if len(text) > int(max_output_chars):
        reject(
            "output_too_long",
            f"model output has {len(text)} characters; limit is {max_output_chars}",
        )
    payload = text.strip()
    if not payload:
        reject("empty_output", "model output is empty")
    try:
        document = json.loads(payload, parse_constant=_reject_constant)
    except CanonicalizerContractError:
        raise
    except json.JSONDecodeError as exc:
        reject("not_single_json_object", f"model output is not one JSON object: {exc.msg}")
    except RecursionError:
        reject("not_single_json_object", "model output nesting exceeds parser limits")

    if not isinstance(document, dict):
        reject(
            "not_json_object",
            f"top-level model output must be a JSON object, got {type(document).__name__}",
        )
    keys = set(document)
    if keys != ENVELOPE_KEYS:
        missing = sorted(ENVELOPE_KEYS - keys)
        unknown = sorted(keys - ENVELOPE_KEYS)
        detail = []
        if missing:
            detail.append(f"missing {missing}")
        if unknown:
            detail.append(f"unknown {unknown}")
        reject(
            "envelope_keys",
            "envelope must contain exactly status/canonical_text/error_code ("
            + ", ".join(detail)
            + ")",
        )

    raw_status = document["status"]
    if not isinstance(raw_status, str) or raw_status not in MODEL_STATUSES:
        reject(
            "invalid_status",
            f"status must be one of {'/'.join(MODEL_STATUSES)}, got {raw_status!r}",
        )
    status = raw_status
    canonical_text = document["canonical_text"]
    raw_error = document["error_code"]

    if status == STATUS_SUCCESS:
        if raw_error is not None:
            reject("success_with_error_code", "SUCCESS must carry error_code = null")
        if not isinstance(canonical_text, str) or not canonical_text.strip():
            reject("success_without_text", "SUCCESS must carry a non-empty canonical_text")
        canonical = canonical_text.strip()
        if any(char in canonical for char in "\r\n\t"):
            reject("canonical_text_control_chars", "canonical_text must be a single line")
        if len(canonical) > int(max_canonical_chars):
            reject(
                "canonical_text_too_long",
                f"canonical_text has {len(canonical)} characters; "
                f"limit is {max_canonical_chars}",
            )
        return CanonicalizerEnvelope(status=status, canonical_text=canonical, error_code=None)

    if canonical_text is not None:
        reject("refusal_with_text", f"{status} must carry canonical_text = null")
    if not isinstance(raw_error, str) or raw_error not in MODEL_ERROR_CODES:
        reject(
            "unknown_error_code",
            f"error_code {raw_error!r} is not a model-emittable language error code",
        )
    if raw_error not in STATUS_TO_ERROR_CODES[status]:
        reject(
            "error_code_status_mismatch",
            f"error_code {raw_error} is inconsistent with status {status}",
        )
    return CanonicalizerEnvelope(status=status, canonical_text=None, error_code=raw_error)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _total_tokens(usage: Mapping[str, Any] | None, fallback: Any) -> int | None:
    candidate = fallback
    if isinstance(usage, Mapping):
        if candidate is None:
            candidate = usage.get("total_tokens")
    if isinstance(candidate, bool):
        return None
    if isinstance(candidate, int) and candidate >= 0:
        return candidate
    if isinstance(candidate, float) and candidate >= 0 and float(candidate).is_integer():
        return int(candidate)
    return None


class LLMMissionCanonicalizer:
    """``canonicalize(text) -> CanonicalizerOutcome`` around a pluggable backend."""

    name = "simplex_llm_canonicalizer"
    version = CANONICALIZER_VERSION

    def __init__(
        self,
        *,
        backend: LLMBackend,
        prompt_path: str | Path | None = None,
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        expected_prompt_sha256: str | None = None,
        max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
        max_canonical_chars: int = DEFAULT_MAX_CANONICAL_CHARS,
    ) -> None:
        if backend is None:
            raise LLMConfigurationError("canonicalizer requires an LLM backend")
        path = (
            resolve_repo_path(prompt_path)
            if prompt_path is not None
            else resolve_repo_path(DEFAULT_PROMPT_PATH)
        )
        self.prompt_path = path
        self.prompt_text = path.read_text(encoding="utf-8")
        if not self.prompt_text.strip():
            raise LLMConfigurationError(f"frozen canonicalizer prompt is empty: {path}")
        self.prompt_sha256 = _sha256_text(self.prompt_text)
        if expected_prompt_sha256 and str(expected_prompt_sha256) != self.prompt_sha256:
            raise LLMConfigurationError(
                "frozen canonicalizer prompt hash mismatch: expected "
                f"{expected_prompt_sha256}, found {self.prompt_sha256}"
            )
        if int(max_input_chars) <= 0 or int(max_output_chars) <= 0:
            raise LLMConfigurationError("canonicalizer character bounds must be positive")
        if int(max_canonical_chars) <= 0:
            raise LLMConfigurationError("max_canonical_chars must be positive")
        self.prompt_version = str(prompt_version)
        self.max_input_chars = int(max_input_chars)
        self.max_output_chars = int(max_output_chars)
        self.max_canonical_chars = int(max_canonical_chars)
        self.backend = backend
        self.model = str(getattr(backend, "model", "unknown"))
        request_parameters = getattr(backend, "request_parameters", None)
        self.request_parameters: dict[str, Any] = (
            dict(request_parameters()) if callable(request_parameters) else {}
        )

    # ------------------------------------------------------------------
    def canonicalize(self, text: str) -> CanonicalizerOutcome:
        started = time.perf_counter()

        def finish(**values: Any) -> CanonicalizerOutcome:
            values.setdefault("latency_s", time.perf_counter() - started)
            return CanonicalizerOutcome(**values)

        if not isinstance(text, str):
            return finish(
                status=STATUS_MALFORMED,
                error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR.value,
                error_message="language input must be a string",
                diagnostics={"failure_type": "INVALID_INPUT"},
            )
        normalized = normalize_text(text)
        if not normalized:
            return finish(
                status=STATUS_MALFORMED,
                error_code=LanguageErrorCode.EMPTY_LANGUAGE_INPUT.value,
                error_message="language input is empty",
                diagnostics={"failure_type": "INVALID_INPUT"},
            )
        if len(normalized) > self.max_input_chars:
            return finish(
                status=STATUS_MALFORMED,
                error_code=LanguageErrorCode.INPUT_TOO_LONG.value,
                error_message=f"language input exceeds {self.max_input_chars} characters",
                diagnostics={"failure_type": "INVALID_INPUT"},
            )

        try:
            response = self.backend.complete(system_prompt=self.prompt_text, user_text=text)
        except LLMBackendError as exc:
            return finish(
                status=STATUS_ERROR,
                error=f"{exc.failure_type}: {exc.message}",
                diagnostics={
                    "failure_type": exc.failure_type,
                    "attempts": exc.attempts,
                    "retryable": exc.retryable,
                },
            )
        except LLMConfigurationError as exc:
            return finish(
                status=STATUS_ERROR,
                error=str(exc),
                diagnostics={"failure_type": FAILURE_API_ERROR, "attempts": 0},
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            return finish(
                status=STATUS_ERROR,
                error=f"backend raised {type(exc).__name__}",
                diagnostics={"failure_type": FAILURE_API_ERROR},
            )

        usage = dict(response.usage) if isinstance(response.usage, Mapping) else None
        provider_tokens = _total_tokens(usage, None)
        base_diagnostics: dict[str, Any] = {
            "failure_type": None,
            "model": str(response.model),
            "prompt_sha256": self.prompt_sha256,
            "prompt_version": self.prompt_version,
            "raw_response_sha256": _sha256_text(response.text),
            "attempts": int(response.attempts),
            "request_parameters": dict(response.request_parameters),
            "response_id": response.response_id,
            "provider_status": response.provider_status,
            "usage": usage,
        }

        try:
            envelope = parse_canonicalizer_envelope(
                response.text,
                max_output_chars=self.max_output_chars,
                max_canonical_chars=self.max_canonical_chars,
            )
        except CanonicalizerContractError as exc:
            diagnostics = dict(base_diagnostics)
            diagnostics.update(
                {"failure_type": exc.failure_type, "contract_reason": exc.reason}
            )
            return finish(
                status=STATUS_MALFORMED,
                error_code=LanguageErrorCode.LANGUAGE_PARSE_ERROR.value,
                error_message=f"canonicalizer output violated the contract: {exc.message}",
                raw_response=response.text,
                usage=usage,
                provider_tokens=provider_tokens,
                diagnostics=diagnostics,
            )

        if envelope.status == STATUS_SUCCESS:
            return finish(
                status=STATUS_SUCCESS,
                canonical_text=envelope.canonical_text,
                raw_response=response.text,
                usage=usage,
                provider_tokens=provider_tokens,
                diagnostics=dict(base_diagnostics),
            )
        return finish(
            status=envelope.status,
            error_code=envelope.error_code,
            raw_response=response.text,
            usage=usage,
            provider_tokens=provider_tokens,
            diagnostics=dict(base_diagnostics),
        )


__all__ = [
    "CANONICALIZER_VERSION",
    "DEFAULT_MAX_CANONICAL_CHARS",
    "DEFAULT_MAX_INPUT_CHARS",
    "DEFAULT_MAX_OUTPUT_CHARS",
    "DEFAULT_PROMPT_PATH",
    "DEFAULT_PROMPT_VERSION",
    "FAILURE_MALFORMED_OUTPUT",
    "MODEL_ERROR_CODES",
    "MODEL_STATUSES",
    "STATUS_AMBIGUOUS",
    "STATUS_ERROR",
    "STATUS_MALFORMED",
    "STATUS_SUCCESS",
    "STATUS_UNSUPPORTED",
    "STATUS_TO_ERROR_CODES",
    "CanonicalizerContractError",
    "CanonicalizerEnvelope",
    "CanonicalizerOutcome",
    "LLMMissionCanonicalizer",
    "parse_canonicalizer_envelope",
]
