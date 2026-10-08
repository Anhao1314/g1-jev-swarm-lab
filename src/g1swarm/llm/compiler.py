"""Fail-closed LLM Mission Compiler for Phase 2.2.

``LLMMissionCompiler.compile(text) -> CompilerResult`` is the only bridge
between a language model and the validated Mission IR pipeline. It sends the
frozen prompt, parses exactly one envelope, builds a typed ``Mission`` and runs
the Phase 2.0 static validator.

It never invokes the simulator, skill router, task graph, capability grounder
or controller, it never selects an execution mode, and it never repairs or
re-prompts model output. Every failure is returned as a typed
``CompilerResult`` with a scoring ``failure_type`` in its diagnostics:

- ``MALFORMED_OUTPUT``: not one JSON envelope / contract violation
- ``HALLUCINATED_FIELD``: forbidden mission or step fields
- ``INVALID_SCHEMA``: mission document that is not legal Mission IR
- ``API_ERROR`` / ``TIMEOUT``: transport failure
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from ..language.errors import CompilerStatus, LanguageErrorCode
from ..language.normalization import normalize_text
from ..language.result import CompilerResult
from ..mission.ir import Mission, SkillName
from ..mission.validator import MissionValidator
from ..paths import repo_root
from .backend import (
    FAILURE_API_ERROR,
    FAILURE_TIMEOUT,
    LLMBackend,
    LLMBackendError,
    LLMConfigurationError,
)
from .parsing import LLMContractError, contract_violations, parse_envelope

COMPILER_VERSION = "2.2.0"
DEFAULT_MAX_INPUT_CHARS = 512
DEFAULT_MAX_OUTPUT_CHARS = 16384
FROZEN_STATUSES = tuple(status.value for status in CompilerStatus)
FROZEN_SKILLS = tuple(skill.value for skill in SkillName)


class LLMMissionCompiler:
    """``compile(text) -> CompilerResult`` around a pluggable LLM backend."""

    def __init__(
        self,
        *,
        backend: LLMBackend,
        prompt_path: str | Path,
        protocol: Mapping[str, Any],
        validator: MissionValidator | None = None,
    ) -> None:
        self.backend = backend
        self.protocol = dict(protocol)
        self.prompt_path = Path(prompt_path)
        self.prompt_text = self.prompt_path.read_text(encoding="utf-8")
        self.prompt_sha256 = _sha256_text(self.prompt_text)

        prompt_config = dict(self.protocol.get("prompt", {}))
        expected_prompt_hash = prompt_config.get("sha256")
        if expected_prompt_hash and str(expected_prompt_hash) != self.prompt_sha256:
            raise LLMConfigurationError(
                "frozen system prompt hash mismatch: expected "
                f"{expected_prompt_hash}, found {self.prompt_sha256}"
            )

        compiler_config = dict(self.protocol.get("compiler", {}))
        self.max_input_chars = int(
            compiler_config.get("max_input_chars", DEFAULT_MAX_INPUT_CHARS)
        )
        self.max_output_chars = int(
            compiler_config.get("max_output_chars", DEFAULT_MAX_OUTPUT_CHARS)
        )
        if compiler_config.get("json_only", True) is not True:
            raise LLMConfigurationError("Phase 2.2 requires json_only: true")
        if compiler_config.get("automatic_repair", False) is not False:
            raise LLMConfigurationError(
                "Phase 2.2 forbids automatic_repair; model output is never repaired"
            )
        statuses = tuple(str(value) for value in compiler_config.get("statuses", FROZEN_STATUSES))
        unknown_statuses = sorted(set(statuses) - set(FROZEN_STATUSES))
        if unknown_statuses:
            raise LLMConfigurationError(
                f"protocol lists unknown compiler statuses: {unknown_statuses}"
            )
        allowed = tuple(
            str(value) for value in compiler_config.get("allowed_skills", FROZEN_SKILLS)
        )
        unknown_skills = sorted(set(allowed) - set(FROZEN_SKILLS))
        if unknown_skills:
            raise LLMConfigurationError(
                f"protocol lists unsupported skills: {unknown_skills}"
            )
        if self.max_input_chars <= 0 or self.max_output_chars <= 0:
            raise LLMConfigurationError("compiler character bounds must be positive")

        self.allowed_skills = frozenset(allowed)
        self.validator = validator or MissionValidator()
        self.compiler_version = COMPILER_VERSION
        self.model = str(getattr(backend, "model", "unknown"))
        self.request_parameters: dict[str, Any] = {
            "model": self.model,
            "json_only": True,
            "automatic_repair": False,
        }
        request_parameters = getattr(backend, "request_parameters", None)
        if callable(request_parameters):
            self.request_parameters.update(dict(request_parameters()))

    # ------------------------------------------------------------------
    def compile(self, text: str) -> CompilerResult:
        try:
            return self._compile(text)
        except Exception as exc:  # pragma: no cover - defensive boundary
            return self._failure(
                normalized="",
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.LLM_API_ERROR,
                message=f"compiler internal error: {type(exc).__name__}",
                diagnostics={"failure_type": FAILURE_API_ERROR},
            )

    def _compile(self, text: str) -> CompilerResult:
        if not isinstance(text, str):
            return self._failure(
                normalized="",
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.LANGUAGE_PARSE_ERROR,
                message="language input must be a string",
                diagnostics=self._base_diagnostics(""),
            )

        normalized = normalize_text(text)
        diagnostics = self._base_diagnostics(normalized)
        if not normalized:
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.EMPTY_LANGUAGE_INPUT,
                message="language input is empty",
                diagnostics=diagnostics,
            )
        if len(normalized) > self.max_input_chars:
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.INPUT_TOO_LONG,
                message=f"language input exceeds {self.max_input_chars} characters",
                diagnostics=diagnostics,
            )

        try:
            response = self.backend.complete(
                system_prompt=self.prompt_text, user_text=text
            )
        except LLMBackendError as exc:
            diagnostics.update(
                {
                    "failure_type": exc.failure_type,
                    "attempts": exc.attempts,
                    "backend_error": {
                        "message": exc.message,
                        "retryable": exc.retryable,
                        "context": dict(exc.context),
                    },
                }
            )
            code = (
                LanguageErrorCode.LLM_TIMEOUT
                if exc.failure_type == FAILURE_TIMEOUT
                else LanguageErrorCode.LLM_API_ERROR
            )
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=code,
                message=exc.message,
                diagnostics=diagnostics,
            )
        except LLMConfigurationError as exc:
            diagnostics.update(
                {"failure_type": FAILURE_API_ERROR, "attempts": 0, "backend_error": str(exc)}
            )
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.LLM_CONFIGURATION_ERROR,
                message=str(exc),
                diagnostics=diagnostics,
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            diagnostics.update(
                {
                    "failure_type": FAILURE_API_ERROR,
                    "attempts": None,
                    "backend_error": f"{type(exc).__name__}",
                }
            )
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.LLM_API_ERROR,
                message=f"backend raised {type(exc).__name__}",
                diagnostics=diagnostics,
            )

        diagnostics.update(
            {
                "model": response.model,
                "latency_s": float(response.latency_s),
                "attempts": int(response.attempts),
                "request_parameters": dict(response.request_parameters),
                "raw_response": response.text,
                "raw_response_sha256": _sha256_text(response.text),
                "usage": dict(response.usage) if response.usage else None,
                "response_id": response.response_id,
                "provider_status": response.provider_status,
                "failure_type": None,
                "validation": None,
            }
        )

        try:
            envelope = parse_envelope(
                response.text, max_output_chars=self.max_output_chars
            )
        except LLMContractError as exc:
            diagnostics.update(
                {"failure_type": exc.failure_type, "contract_reason": exc.reason}
            )
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.LLM_OUTPUT_INVALID,
                message=f"LLM output violated the contract: {exc.message}",
                diagnostics=diagnostics,
            )

        if envelope.status is not CompilerStatus.SUCCESS:
            return self._rejection(normalized, envelope, diagnostics)

        assert envelope.mission is not None  # guaranteed by parse_envelope
        try:
            mission = Mission.from_dict(envelope.mission)
        except Exception as exc:
            diagnostics.update(
                {
                    "failure_type": "INVALID_SCHEMA",
                    "schema_error": str(exc)[:512],
                }
            )
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.LLM_OUTPUT_INVALID,
                message=f"LLM mission is not legal Mission IR: {exc}",
                diagnostics=diagnostics,
            )

        disallowed = sorted(
            {step.skill.value for step in mission.steps} - self.allowed_skills
        )
        if disallowed:
            diagnostics.update(
                {
                    "failure_type": "INVALID_SCHEMA",
                    "schema_error": f"skills outside the frozen vocabulary: {disallowed}",
                }
            )
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.LLM_OUTPUT_INVALID,
                message=f"LLM mission used skills outside the frozen vocabulary: {disallowed}",
                diagnostics=diagnostics,
            )

        report = self.validator.validate(mission)
        diagnostics["validation"] = report.to_dict()
        if not report.valid:
            diagnostics["failure_type"] = "INVALID_SCHEMA"
            return self._failure(
                normalized=normalized,
                status=CompilerStatus.MALFORMED,
                code=LanguageErrorCode.LLM_OUTPUT_INVALID,
                message="LLM mission failed static validation: "
                + "; ".join(issue.message for issue in report.issues),
                diagnostics=diagnostics,
            )

        violations = contract_violations(envelope.mission)
        diagnostics.update(
            {
                "failure_type": None,
                "step_count": len(mission.steps),
                "mission_id": mission.mission_id,
                "contract_violations": list(violations),
                "contract_violation_count": len(violations),
            }
        )
        return CompilerResult(
            status=CompilerStatus.SUCCESS,
            mission=mission,
            normalized_text=normalized,
            diagnostics=diagnostics,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _rejection(
        normalized: str, envelope, diagnostics: dict[str, Any]
    ) -> CompilerResult:
        return CompilerResult(
            status=envelope.status,
            mission=None,
            normalized_text=normalized,
            error_code=envelope.error_code,
            error_message=(
                f"model returned {envelope.status.value} "
                f"({envelope.error_code.value if envelope.error_code else 'no code'})"
            ),
            diagnostics=diagnostics,
        )

    def _base_diagnostics(self, normalized: str) -> dict[str, Any]:
        return {
            "compiler": "llm_mission_compiler",
            "compiler_version": COMPILER_VERSION,
            "model": self.model,
            "prompt_path": _relative_or_absolute(self.prompt_path),
            "prompt_sha256": self.prompt_sha256,
            "protocol_sha256": self.protocol.get("_protocol_sha256"),
            "request_parameters": dict(self.request_parameters),
            "max_input_chars": self.max_input_chars,
            "max_output_chars": self.max_output_chars,
            "normalized_length": len(normalized),
            "failure_type": None,
        }

    @staticmethod
    def _failure(
        *,
        normalized: str,
        status: CompilerStatus,
        code: LanguageErrorCode,
        message: str,
        diagnostics: dict[str, Any],
    ) -> CompilerResult:
        return CompilerResult(
            status=status,
            mission=None,
            normalized_text=normalized,
            error_code=code,
            error_message=message,
            diagnostics=diagnostics,
        )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _relative_or_absolute(path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
