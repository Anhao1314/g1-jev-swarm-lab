"""Strict, fail-closed parsing of the Phase 2.2 LLM compiler contract.

The model may only return one JSON envelope that carries either a Mission IR
2.0 document or a typed language rejection. Anything else is a contract
failure and never yields a mission payload.

Hard rules:
- exactly one JSON object, no markdown, no trailing text, bounded length
- exactly the keys ``status``, ``mission``, ``error_code``
- SUCCESS carries a mission and ``error_code = null``
- non-SUCCESS carries ``mission = null`` and a model-emittable error code
  consistent with the status
- no unknown mission/step fields, so the model can never smuggle in
  ``execution_mode_override``, controller, risk or capability fields
- every number is finite

Soft rules (recorded, still executable): step IDs ``s1, s2, ...`` in order and
an explicit linear ``depends_on`` chain with the two optional keys present.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from ..language.errors import CompilerStatus, LanguageErrorCode

ENVELOPE_KEYS = frozenset({"status", "mission", "error_code"})
MISSION_KEYS = frozenset({"schema_version", "mission_id", "steps"})
STEP_KEYS = frozenset({"id", "skill", "parameters", "depends_on"})

FAILURE_MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
FAILURE_INVALID_SCHEMA = "INVALID_SCHEMA"
FAILURE_HALLUCINATED_FIELD = "HALLUCINATED_FIELD"

MODEL_AMBIGUOUS_CODES = frozenset({"AMBIGUOUS_COMMAND", "MISSING_PARAMETER"})
MODEL_UNSUPPORTED_CODES = frozenset({"UNSUPPORTED_LANGUAGE_CAPABILITY"})
MODEL_MALFORMED_CODES = frozenset(
    {
        "INVALID_UNIT",
        "MALFORMED_NUMBER",
        "CONTRADICTORY_COMMAND",
        "LANGUAGE_PARSE_ERROR",
        "EMPTY_LANGUAGE_INPUT",
        "INPUT_TOO_LONG",
    }
)
MODEL_EMITTABLE_ERROR_CODES = (
    MODEL_AMBIGUOUS_CODES | MODEL_UNSUPPORTED_CODES | MODEL_MALFORMED_CODES
)
STATUS_TO_ERROR_CODES: dict[CompilerStatus, frozenset[str]] = {
    CompilerStatus.AMBIGUOUS: MODEL_AMBIGUOUS_CODES,
    CompilerStatus.UNSUPPORTED: MODEL_UNSUPPORTED_CODES,
    CompilerStatus.MALFORMED: MODEL_MALFORMED_CODES,
}
_STATUS_BY_VALUE = {status.value: status for status in CompilerStatus}


class LLMContractError(ValueError):
    """The model output violated the frozen JSON contract."""

    def __init__(self, failure_type: str, reason: str, message: str) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class LLMEnvelope:
    """A contract-valid envelope; the mission still needs Mission IR validation."""

    status: CompilerStatus
    mission: dict[str, Any] | None
    error_code: LanguageErrorCode | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "mission": dict(self.mission) if self.mission is not None else None,
            "error_code": self.error_code.value if self.error_code is not None else None,
        }


def _reject_constant(name: str) -> float:
    raise LLMContractError(
        FAILURE_MALFORMED_OUTPUT,
        "non_finite_number",
        f"non-finite JSON constant {name!r} is not allowed",
    )


def _has_non_finite(node: Any) -> bool:
    if isinstance(node, float):
        return not math.isfinite(node)
    if isinstance(node, Mapping):
        return any(_has_non_finite(value) for value in node.values())
    if isinstance(node, (list, tuple)):
        return any(_has_non_finite(value) for value in node)
    return False


def parse_envelope(text: str, *, max_output_chars: int) -> LLMEnvelope:
    """Parse one model response into a contract-valid envelope or raise."""

    def reject(reason: str, message: str) -> None:
        raise LLMContractError(FAILURE_MALFORMED_OUTPUT, reason, message)

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
    except LLMContractError:
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
    if _has_non_finite(document):
        reject("non_finite_number", "mission contains a non-finite number")

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
            "envelope must contain exactly status/mission/error_code (" + ", ".join(detail) + ")",
        )

    raw_status = document["status"]
    if not isinstance(raw_status, str) or raw_status not in _STATUS_BY_VALUE:
        reject(
            "invalid_status",
            "status must be one of SUCCESS/AMBIGUOUS/UNSUPPORTED/MALFORMED, "
            f"got {raw_status!r}",
        )
    status = _STATUS_BY_VALUE[raw_status]
    mission_document = document["mission"]
    raw_error = document["error_code"]

    if status is CompilerStatus.SUCCESS:
        if raw_error is not None:
            reject("success_with_error_code", "SUCCESS must carry error_code = null")
        if not isinstance(mission_document, dict):
            reject(
                "success_without_mission",
                f"SUCCESS must carry a mission object, got {type(mission_document).__name__}",
            )
        _check_mission_shape(mission_document)
        return LLMEnvelope(status=status, mission=dict(mission_document), error_code=None)

    if mission_document is not None:
        reject("non_success_with_mission", f"{status.value} must carry mission = null")
    if not isinstance(raw_error, str) or raw_error not in MODEL_EMITTABLE_ERROR_CODES:
        reject(
            "unknown_error_code",
            f"error_code {raw_error!r} is not a model-emittable language error code",
        )
    if raw_error not in STATUS_TO_ERROR_CODES[status]:
        reject(
            "error_code_status_mismatch",
            f"error_code {raw_error} is inconsistent with status {status.value}",
        )
    return LLMEnvelope(status=status, mission=None, error_code=LanguageErrorCode(raw_error))


def _check_mission_shape(document: Mapping[str, Any]) -> None:
    unknown = set(document) - MISSION_KEYS
    if unknown:
        raise LLMContractError(
            FAILURE_HALLUCINATED_FIELD,
            "unknown_mission_field",
            f"mission contains field(s) the LLM contract forbids: {sorted(unknown)}",
        )
    steps = document.get("steps")
    if not isinstance(steps, list):
        raise LLMContractError(
            FAILURE_INVALID_SCHEMA,
            "invalid_steps",
            f"mission.steps must be a JSON array, got {type(steps).__name__}",
        )
    for index, step in enumerate(steps):
        if not isinstance(step, Mapping):
            raise LLMContractError(
                FAILURE_INVALID_SCHEMA,
                "invalid_step",
                f"steps[{index}] must be a JSON object, got {type(step).__name__}",
            )
        step_unknown = set(step) - STEP_KEYS
        if step_unknown:
            raise LLMContractError(
                FAILURE_HALLUCINATED_FIELD,
                "unknown_step_field",
                f"steps[{index}] contains field(s) the LLM contract forbids: "
                f"{sorted(step_unknown)}",
            )
        if not isinstance(step.get("id"), str) or not step.get("id"):
            raise LLMContractError(
                FAILURE_INVALID_SCHEMA,
                "invalid_step_id",
                f"steps[{index}].id must be a non-empty string",
            )
        if not isinstance(step.get("skill"), str) or not step.get("skill"):
            raise LLMContractError(
                FAILURE_INVALID_SCHEMA,
                "invalid_step_skill",
                f"steps[{index}].skill must be a non-empty string",
            )
        if "parameters" in step and not isinstance(step["parameters"], Mapping):
            raise LLMContractError(
                FAILURE_INVALID_SCHEMA,
                "invalid_step_parameters",
                f"steps[{index}].parameters must be a JSON object",
            )
        if "depends_on" in step and not isinstance(step["depends_on"], list):
            raise LLMContractError(
                FAILURE_INVALID_SCHEMA,
                "invalid_step_depends_on",
                f"steps[{index}].depends_on must be a JSON array",
            )


def contract_violations(mission_document: Mapping[str, Any]) -> tuple[str, ...]:
    """Soft prompt-conformance deviations; the mission may still be valid."""

    violations: list[str] = []
    steps = mission_document.get("steps")
    if not isinstance(steps, list):
        return ("steps_not_a_list",)
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, Mapping):
            violations.append(f"steps[{index}] not an object")
            continue
        if "parameters" not in step:
            violations.append(f"steps[{index}] missing explicit parameters key")
        if "depends_on" not in step:
            violations.append(f"steps[{index}] missing explicit depends_on key")
        expected_id = f"s{index}"
        if step.get("id") != expected_id:
            violations.append(
                f"steps[{index}] id is {step.get('id')!r}, expected {expected_id!r}"
            )
        expected_dependencies = [] if index == 1 else [f"s{index - 1}"]
        if list(step.get("depends_on", [])) != expected_dependencies:
            violations.append(
                f"steps[{index}] depends_on is {list(step.get('depends_on', []))!r}, "
                f"expected {expected_dependencies!r}"
            )
    return tuple(violations)
