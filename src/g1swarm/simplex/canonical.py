"""Deterministic canonicalization of Phase 2.2b simplex mission drafts.

The simplex compiler receives mission proposals from several front ends (the
rule compiler, the LLM adapter, graders and tests).  Those proposals may differ
only in representation: key spelling, unit notation, integral-vs-float
numbers, key order or duplicated dependency entries.  Canonicalization turns
any such proposal into exactly one Mission IR 2.0 document plus a byte-stable
JSON encoding, or fails closed with a typed error.

Rules:

- Only representation is normalized.  The canonicalizer never invents, drops
  or rounds a semantic value: numbers become finite floats (``-0.0`` becomes
  ``0.0``), aliases resolve through fixed tables, and ``depends_on`` entries
  are de-duplicated in first-seen order.  Range/semantics checks (negative
  distance, dependency cycles, ...) stay in the Mission validator.
- Aliases are never fuzzy: a skill or parameter that is not in the frozen
  tables is rejected.
- ``execution_mode_override`` is rejected unless the caller explicitly opts
  in; it is an experiment/grading field and must not arrive from a language
  front end.
- ``comparison_payload`` / ``comparison_hash`` reproduce the Phase 2.1/2.2
  benchmark canonical form byte-for-byte, so the historical comparison
  semantics are preserved.  ``canonical_json`` / ``canonical_sha256`` hash the
  full canonical document including ``mission_id``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from enum import Enum
from typing import Any, Mapping

from ..mission.ir import (
    MAX_MISSION_STEPS,
    MISSION_SCHEMA_VERSION,
    PARAMETER_KEYS,
    REQUIRED_PARAMETERS,
    ExecutionModeOverride,
    Mission,
    MissionStep,
    SkillName,
    is_path_safe_mission_id,
)

MISSION_KEYS = frozenset({"schema_version", "mission_id", "steps"})
STEP_KEYS = frozenset({"id", "skill", "parameters", "depends_on", "execution_mode_override"})

_QUANTITY_RE = re.compile(r"^([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))\s*([^\d\s]*)$")


class CanonicalizationCode(str, Enum):
    """Typed, stably named canonicalization failures."""

    NOT_A_MAPPING = "NOT_A_MAPPING"
    UNKNOWN_MISSION_FIELD = "UNKNOWN_MISSION_FIELD"
    INVALID_SCHEMA_VERSION = "INVALID_SCHEMA_VERSION"
    INVALID_MISSION_ID = "INVALID_MISSION_ID"
    INVALID_STEPS = "INVALID_STEPS"
    TOO_MANY_STEPS = "TOO_MANY_STEPS"
    STEP_NOT_A_MAPPING = "STEP_NOT_A_MAPPING"
    UNKNOWN_STEP_FIELD = "UNKNOWN_STEP_FIELD"
    MISSING_STEP_FIELD = "MISSING_STEP_FIELD"
    INVALID_STEP_ID = "INVALID_STEP_ID"
    DUPLICATE_STEP_ID = "DUPLICATE_STEP_ID"
    UNKNOWN_SKILL = "UNKNOWN_SKILL"
    UNKNOWN_PARAMETER = "UNKNOWN_PARAMETER"
    AMBIGUOUS_PARAMETER = "AMBIGUOUS_PARAMETER"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    INVALID_PARAMETERS = "INVALID_PARAMETERS"
    INVALID_PARAMETER_VALUE = "INVALID_PARAMETER_VALUE"
    NON_FINITE_NUMBER = "NON_FINITE_NUMBER"
    INVALID_DEPENDENCY = "INVALID_DEPENDENCY"
    UNKNOWN_DEPENDENCY = "UNKNOWN_DEPENDENCY"
    INVALID_EXECUTION_MODE = "INVALID_EXECUTION_MODE"
    FORBIDDEN_FIELD = "FORBIDDEN_FIELD"


class CanonicalizationError(ValueError):
    """A mission draft could not be canonicalized."""

    def __init__(self, code: CanonicalizationCode, path: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.message = message

    def __str__(self) -> str:
        return f"{self.code.value} at {self.path}: {self.message}"


_SKILL_ALIASES: dict[str, str] = {
    "stand": "stand",
    "stand_still": "stand",
    "hold": "stand",
    "站": "stand",
    "站立": "stand",
    "walk": "walk_forward",
    "walk_forward": "walk_forward",
    "walkforward": "walk_forward",
    "forward": "walk_forward",
    "move_forward": "walk_forward",
    "前进": "walk_forward",
    "向前走": "walk_forward",
    "turn": "turn",
    "rotate": "turn",
    "yaw": "turn",
    "转身": "turn",
    "转向": "turn",
    "stop": "stop",
    "halt": "stop",
    "停": "stop",
    "停止": "stop",
}

_PARAMETER_ALIASES: dict[SkillName, dict[str, str]] = {
    SkillName.STAND: {
        "duration": "duration_s",
        "duration_s": "duration_s",
        "second": "duration_s",
        "seconds": "duration_s",
        "s": "duration_s",
        "time": "duration_s",
        "时长": "duration_s",
        "秒": "duration_s",
    },
    SkillName.WALK_FORWARD: {
        "distance": "distance_m",
        "distance_m": "distance_m",
        "meter": "distance_m",
        "meters": "distance_m",
        "m": "distance_m",
        "距离": "distance_m",
        "米": "distance_m",
    },
    SkillName.TURN: {
        "angle": "angle_deg",
        "angle_deg": "angle_deg",
        "degree": "angle_deg",
        "degrees": "angle_deg",
        "deg": "angle_deg",
        "°": "angle_deg",
        "角度": "angle_deg",
        "度": "angle_deg",
    },
    SkillName.STOP: {},
}

_UNIT_FACTORS: dict[str, dict[str, float]] = {
    "distance_m": {
        "": 1.0,
        "m": 1.0,
        "meter": 1.0,
        "meters": 1.0,
        "米": 1.0,
        "cm": 0.01,
        "厘米": 0.01,
    },
    "angle_deg": {
        "": 1.0,
        "deg": 1.0,
        "degree": 1.0,
        "degrees": 1.0,
        "°": 1.0,
        "度": 1.0,
    },
    "duration_s": {
        "": 1.0,
        "s": 1.0,
        "sec": 1.0,
        "second": 1.0,
        "seconds": 1.0,
        "秒": 1.0,
    },
}


def _normalize_token(token: str) -> str:
    normalized = unicodedata.normalize("NFKC", token).strip().lower()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def _fail(code: CanonicalizationCode, path: str, message: str) -> CanonicalizationError:
    return CanonicalizationError(code, path, message)


def normalize_skill(token: str) -> SkillName:
    """Resolve one skill token through the frozen alias table."""

    if not isinstance(token, str) or not token.strip():
        raise _fail(CanonicalizationCode.UNKNOWN_SKILL, "skill", "skill must be a non-empty string")
    resolved = _SKILL_ALIASES.get(_normalize_token(token))
    if resolved is None:
        allowed = ", ".join(sorted(skill.value for skill in SkillName))
        raise _fail(
            CanonicalizationCode.UNKNOWN_SKILL,
            "skill",
            f"unknown skill {token!r}; supported skills are {allowed}",
        )
    return SkillName(resolved)


def normalize_parameter(skill: SkillName | str, name: str) -> str:
    """Resolve one parameter name for a skill through the frozen alias table."""

    resolved_skill = normalize_skill(skill.value if isinstance(skill, SkillName) else skill)
    if not isinstance(name, str) or not name.strip():
        raise _fail(
            CanonicalizationCode.UNKNOWN_PARAMETER,
            "parameters",
            "parameter name must be a non-empty string",
        )
    resolved = _PARAMETER_ALIASES[resolved_skill].get(_normalize_token(name))
    if resolved is None:
        allowed = ", ".join(sorted(PARAMETER_KEYS[resolved_skill]))
        raise _fail(
            CanonicalizationCode.UNKNOWN_PARAMETER,
            "parameters",
            f"unknown parameter {name!r} for {resolved_skill.value}; allowed: {allowed}",
        )
    return resolved


def _finite_float(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(
            CanonicalizationCode.INVALID_PARAMETER_VALUE,
            path,
            f"expected a number, got {type(value).__name__}",
        )
    number = float(value)
    if not math.isfinite(number):
        raise _fail(
            CanonicalizationCode.NON_FINITE_NUMBER,
            path,
            f"number must be finite, got {value!r}",
        )
    return 0.0 if number == 0.0 else number


def _text_float(text: str, path: str) -> float:
    try:
        number = float(text)
    except ValueError as exc:
        raise _fail(
            CanonicalizationCode.INVALID_PARAMETER_VALUE,
            path,
            f"{text!r} is not a decimal number",
        ) from exc
    if not math.isfinite(number):
        raise _fail(
            CanonicalizationCode.NON_FINITE_NUMBER,
            path,
            f"number must be finite, got {text!r}",
        )
    return number


def _scale(number: float, factor: float, path: str) -> float:
    scaled = number * factor
    if not math.isfinite(scaled):
        raise _fail(
            CanonicalizationCode.NON_FINITE_NUMBER,
            path,
            "value overflows after unit conversion",
        )
    return 0.0 if scaled == 0.0 else scaled


def _coerce_parameter_value(
    parameter: str,
    raw_value: Any,
    path: str,
    *,
    allow_text_numbers: bool,
) -> float:
    units = _UNIT_FACTORS[parameter]
    if isinstance(raw_value, Mapping):
        unknown = set(raw_value) - {"value", "unit"}
        if unknown:
            raise _fail(
                CanonicalizationCode.INVALID_PARAMETER_VALUE,
                path,
                f"quantity object has unknown keys: {sorted(unknown)}",
            )
        if "value" not in raw_value:
            raise _fail(
                CanonicalizationCode.INVALID_PARAMETER_VALUE,
                path,
                "quantity object requires a 'value' key",
            )
        raw_unit = raw_value.get("unit", "")
        if not isinstance(raw_unit, str):
            raise _fail(
                CanonicalizationCode.INVALID_PARAMETER_VALUE,
                path,
                "quantity unit must be a string",
            )
        unit = _normalize_token(raw_unit)
        if raw_unit.strip() and not unit:
            raise _fail(
                CanonicalizationCode.INVALID_PARAMETER_VALUE,
                path,
                f"unsupported unit {raw_unit!r}; allowed: {sorted(units)}",
            )
        if unit not in units:
            raise _fail(
                CanonicalizationCode.INVALID_PARAMETER_VALUE,
                path,
                f"unsupported unit {raw_unit!r}; allowed: {sorted(units)}",
            )
        inner = raw_value["value"]
        if isinstance(inner, str):
            text = unicodedata.normalize("NFKC", inner).strip()
            if not _QUANTITY_RE.match(text) or _QUANTITY_RE.match(text).group(2):
                raise _fail(
                    CanonicalizationCode.INVALID_PARAMETER_VALUE,
                    path,
                    "quantity value must be a unitless decimal number",
                )
            number = _text_float(text, path)
        else:
            number = _finite_float(inner, path)
        return _scale(number, units[unit], path)

    if isinstance(raw_value, str):
        if not allow_text_numbers:
            raise _fail(
                CanonicalizationCode.INVALID_PARAMETER_VALUE,
                path,
                "text numbers are disabled; provide a numeric value",
            )
        text = unicodedata.normalize("NFKC", raw_value).strip()
        match = _QUANTITY_RE.match(text)
        if match is None:
            raise _fail(
                CanonicalizationCode.INVALID_PARAMETER_VALUE,
                path,
                f"{raw_value!r} is not a decimal number with an optional unit",
            )
        number = _text_float(match.group(1), path)
        raw_unit = match.group(2)
        unit = _normalize_token(raw_unit)
        if raw_unit and not unit:
            raise _fail(
                CanonicalizationCode.INVALID_PARAMETER_VALUE,
                path,
                f"unsupported unit {raw_unit!r}; allowed: {sorted(units)}",
            )
        if unit not in units:
            raise _fail(
                CanonicalizationCode.INVALID_PARAMETER_VALUE,
                path,
                f"unsupported unit {match.group(2)!r}; allowed: {sorted(units)}",
            )
        return _scale(number, units[unit], path)

    return _finite_float(raw_value, path)


def _canonicalize_step(
    raw_step: Any,
    index: int,
    *,
    strict: bool,
    allow_text_numbers: bool,
    allow_execution_mode_override: bool,
) -> MissionStep:
    path = f"steps[{index}]"
    if not isinstance(raw_step, Mapping):
        raise _fail(
            CanonicalizationCode.STEP_NOT_A_MAPPING,
            path,
            f"step must be a mapping, got {type(raw_step).__name__}",
        )
    unknown = set(raw_step) - STEP_KEYS
    if unknown:
        raise _fail(
            CanonicalizationCode.UNKNOWN_STEP_FIELD,
            path,
            f"unknown step fields: {sorted(unknown)}",
        )

    raw_skill = raw_step.get("skill")
    if not isinstance(raw_skill, str) or not raw_skill.strip():
        raise _fail(
            CanonicalizationCode.MISSING_STEP_FIELD,
            path,
            "step requires a non-empty 'skill'",
        )
    try:
        skill = normalize_skill(raw_skill)
    except CanonicalizationError as exc:
        raise _fail(exc.code, path, exc.message) from exc

    raw_id = raw_step.get("id")
    if raw_id is None or (isinstance(raw_id, str) and not raw_id.strip()):
        if strict:
            raise _fail(
                CanonicalizationCode.INVALID_STEP_ID,
                path,
                "step requires a non-empty string 'id'",
            )
        step_id = f"s{index}"
    elif not isinstance(raw_id, str):
        raise _fail(
            CanonicalizationCode.INVALID_STEP_ID,
            path,
            f"step id must be a string, got {type(raw_id).__name__}",
        )
    else:
        step_id = raw_id.strip()

    raw_parameters = raw_step.get("parameters", {})
    if raw_parameters is None and not strict:
        raw_parameters = {}
    if not isinstance(raw_parameters, Mapping):
        raise _fail(
            CanonicalizationCode.INVALID_PARAMETERS,
            path,
            f"parameters must be a mapping, got {type(raw_parameters).__name__}",
        )
    parameters: dict[str, float] = {}
    for raw_name, raw_value in raw_parameters.items():
        try:
            parameter = normalize_parameter(skill, raw_name)
        except CanonicalizationError as exc:
            raise _fail(exc.code, f"{path}.parameters", exc.message) from exc
        if parameter in parameters:
            raise _fail(
                CanonicalizationCode.AMBIGUOUS_PARAMETER,
                path,
                f"parameter {parameter!r} was provided more than once via aliases",
            )
        parameters[parameter] = _coerce_parameter_value(
            parameter,
            raw_value,
            f"{path}.parameters.{parameter}",
            allow_text_numbers=allow_text_numbers,
        )
    missing = REQUIRED_PARAMETERS[skill] - set(parameters)
    if missing:
        raise _fail(
            CanonicalizationCode.MISSING_PARAMETER,
            path,
            f"missing required parameter(s) for {skill.value}: {sorted(missing)}",
        )

    raw_dependencies = raw_step.get("depends_on", [])
    if raw_dependencies is None and not strict:
        raw_dependencies = []
    if not isinstance(raw_dependencies, (list, tuple)):
        raise _fail(
            CanonicalizationCode.INVALID_DEPENDENCY,
            path,
            "depends_on must be a list of step ids",
        )
    depends_on: list[str] = []
    for dependency in raw_dependencies:
        if not isinstance(dependency, str) or not dependency.strip():
            raise _fail(
                CanonicalizationCode.INVALID_DEPENDENCY,
                path,
                "depends_on entries must be non-empty strings",
            )
        resolved = dependency.strip()
        if resolved not in depends_on:
            depends_on.append(resolved)

    override: ExecutionModeOverride | None = None
    raw_override = raw_step.get("execution_mode_override")
    if raw_override is not None:
        if not allow_execution_mode_override:
            raise _fail(
                CanonicalizationCode.FORBIDDEN_FIELD,
                path,
                "execution_mode_override is not accepted from a mission draft",
            )
        if not isinstance(raw_override, str):
            raise _fail(
                CanonicalizationCode.INVALID_EXECUTION_MODE,
                path,
                "execution_mode_override must be a string",
            )
        try:
            override = ExecutionModeOverride(raw_override)
        except ValueError as exc:
            raise _fail(
                CanonicalizationCode.INVALID_EXECUTION_MODE,
                path,
                f"unknown execution mode {raw_override!r}",
            ) from exc

    return MissionStep(
        step_id=step_id,
        skill=skill,
        parameters=parameters,
        depends_on=tuple(depends_on),
        execution_mode_override=override,
    )


def canonicalize_mission(
    document: Mission | Mapping[str, Any],
    *,
    strict: bool = True,
    allow_text_numbers: bool = True,
    allow_execution_mode_override: bool = False,
) -> Mission:
    """Canonicalize a mission draft into Mission IR 2.0.

    ``strict=True`` requires an explicit schema version, step ids and
    list-typed ``depends_on``.  ``strict=False`` fills only representation
    defaults (schema version ``2.0.0``, ``s1..sn`` ids, empty ``depends_on``,
    empty optional parameters); it never invents a mission id or a skill.
    """

    if isinstance(document, Mission):
        document = document.to_dict()
    if not isinstance(document, Mapping):
        raise _fail(
            CanonicalizationCode.NOT_A_MAPPING,
            "mission",
            f"mission draft must be a mapping, got {type(document).__name__}",
        )
    unknown = set(document) - MISSION_KEYS
    if unknown:
        raise _fail(
            CanonicalizationCode.UNKNOWN_MISSION_FIELD,
            "mission",
            f"unknown mission fields: {sorted(unknown)}",
        )

    schema_version = document.get("schema_version")
    if schema_version is None and not strict:
        schema_version = MISSION_SCHEMA_VERSION
    if schema_version != MISSION_SCHEMA_VERSION:
        raise _fail(
            CanonicalizationCode.INVALID_SCHEMA_VERSION,
            "schema_version",
            f"unsupported schema_version {schema_version!r}; expected {MISSION_SCHEMA_VERSION!r}",
        )

    mission_id = document.get("mission_id")
    if not isinstance(mission_id, str) or not is_path_safe_mission_id(mission_id):
        raise _fail(
            CanonicalizationCode.INVALID_MISSION_ID,
            "mission_id",
            "mission_id must be a path-safe, non-reserved name matching "
            "[A-Za-z0-9][A-Za-z0-9._-]{0,63}",
        )

    raw_steps = document.get("steps")
    if not isinstance(raw_steps, (list, tuple)) or not raw_steps:
        raise _fail(
            CanonicalizationCode.INVALID_STEPS,
            "steps",
            "steps must be a non-empty list",
        )
    if len(raw_steps) > MAX_MISSION_STEPS:
        raise _fail(
            CanonicalizationCode.TOO_MANY_STEPS,
            "steps",
            f"mission has {len(raw_steps)} steps; the limit is {MAX_MISSION_STEPS}",
        )

    steps = tuple(
        _canonicalize_step(
            raw_step,
            index,
            strict=strict,
            allow_text_numbers=allow_text_numbers,
            allow_execution_mode_override=allow_execution_mode_override,
        )
        for index, raw_step in enumerate(raw_steps, start=1)
    )

    seen: set[str] = set()
    for step in steps:
        if step.step_id in seen:
            raise _fail(
                CanonicalizationCode.DUPLICATE_STEP_ID,
                "steps",
                f"duplicate step id {step.step_id!r}",
            )
        seen.add(step.step_id)
    for step in steps:
        for dependency in step.depends_on:
            if dependency not in seen:
                raise _fail(
                    CanonicalizationCode.UNKNOWN_DEPENDENCY,
                    f"steps[{step.step_id}]",
                    f"dependency {dependency!r} does not name a step in this mission",
                )

    return Mission(mission_id=mission_id, steps=steps, schema_version=schema_version)


def canonical_document(
    document: Mission | Mapping[str, Any],
    *,
    strict: bool = True,
    allow_text_numbers: bool = True,
    allow_execution_mode_override: bool = False,
) -> dict[str, Any]:
    """Return the canonical, JSON-ready Mission IR document."""

    mission = canonicalize_mission(
        document,
        strict=strict,
        allow_text_numbers=allow_text_numbers,
        allow_execution_mode_override=allow_execution_mode_override,
    )
    steps: list[dict[str, Any]] = []
    for step in mission.steps:
        payload: dict[str, Any] = {
            "id": step.step_id,
            "skill": step.skill.value,
            "parameters": {key: float(step.parameters[key]) for key in sorted(step.parameters)},
            "depends_on": list(step.depends_on),
        }
        if step.execution_mode_override is not None:
            payload["execution_mode_override"] = step.execution_mode_override.value
        steps.append(payload)
    return {
        "schema_version": mission.schema_version,
        "mission_id": mission.mission_id,
        "steps": steps,
    }


def _json_text(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_json(
    document: Mission | Mapping[str, Any],
    *,
    strict: bool = True,
    allow_text_numbers: bool = True,
    allow_execution_mode_override: bool = False,
) -> str:
    """Byte-stable JSON for the full canonical document (mission_id included)."""

    return _json_text(
        canonical_document(
            document,
            strict=strict,
            allow_text_numbers=allow_text_numbers,
            allow_execution_mode_override=allow_execution_mode_override,
        )
    )


def canonical_sha256(
    document: Mission | Mapping[str, Any],
    *,
    strict: bool = True,
    allow_text_numbers: bool = True,
    allow_execution_mode_override: bool = False,
) -> str:
    """SHA-256 of :func:`canonical_json`."""

    encoded = canonical_json(
        document,
        strict=strict,
        allow_text_numbers=allow_text_numbers,
        allow_execution_mode_override=allow_execution_mode_override,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def comparison_payload(
    document: Mission | Mapping[str, Any],
    *,
    include_mission_id: bool = False,
    strict: bool = True,
    allow_text_numbers: bool = True,
    allow_execution_mode_override: bool = False,
) -> dict[str, Any]:
    """Phase 2.1/2.2 comparison payload (execution override excluded)."""

    mission = canonicalize_mission(
        document,
        strict=strict,
        allow_text_numbers=allow_text_numbers,
        allow_execution_mode_override=allow_execution_mode_override,
    )
    steps = [
        {
            "id": step.step_id,
            "skill": step.skill.value,
            "parameters": {key: float(step.parameters[key]) for key in sorted(step.parameters)},
            "depends_on": list(step.depends_on),
        }
        for step in mission.steps
    ]
    payload: dict[str, Any] = {"schema_version": mission.schema_version, "steps": steps}
    if include_mission_id:
        payload["mission_id"] = mission.mission_id
    return payload


def comparison_hash(
    document: Mission | Mapping[str, Any],
    *,
    include_mission_id: bool = False,
    strict: bool = True,
    allow_text_numbers: bool = True,
    allow_execution_mode_override: bool = False,
) -> str:
    """SHA-256 that matches the historical benchmark canonical hash."""

    payload = comparison_payload(
        document,
        include_mission_id=include_mission_id,
        strict=strict,
        allow_text_numbers=allow_text_numbers,
        allow_execution_mode_override=allow_execution_mode_override,
    )
    return hashlib.sha256(_json_text(payload).encode("utf-8")).hexdigest()
