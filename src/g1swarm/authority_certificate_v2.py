"""Candidate-blind compact source-authority certificates, exploratory v2.

The first stage accepts ONLY original source. The candidate is never read,
serialized, validated or included in its provider request. A second host stage
validates the source-derived certificate plan and compares complete historical
canonical semantics with the unchanged candidate. This removes direct candidate
anchoring; it does not remove dependent failures from a shared provider/model.

No compiler, Guard, Runtime, Grounder, skills, old protocol or evidence is edited.
Output/schema/provider failures are unusable UNKNOWN; semantic rejections are
usable AMBIGUOUS/UNKNOWN certificates. There is no model-output repair loop.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .llm.backend import LLMBackend, LLMBackendError, LLMConfigurationError
from .mission.ir import MAX_MISSION_STEPS, Mission, MissionStep, SkillName
from .mission.validator import MissionValidator
from .paths import resolve_repo_path
from .simplex.canonical import comparison_payload
from .source_authority import AuthorizationResult, AuthorizationStatus

TREATMENT_CERTIFICATE_V2 = "guarded_direct_llm_candidate_blind_certificate_v2"
CHECK_DIMENSIONS = (
    "action_multiplicity", "action_order", "correction_scope", "repetition_scope",
    "reference_resolution", "temporal_relations", "unresolved_relations",
)
MAX_SOURCE_CHARS = 8192
MAX_CERTIFICATE_CHARS = 16384
MAX_CERTIFICATE_ISSUES = 16


class CheckVerdict(str, Enum):
    UNIQUE = "U"
    AMBIGUOUS = "A"
    UNKNOWN = "?"


class CertificateRelation(str, Enum):
    MULTIPLICITY = "multiplicity"
    ORDER = "order"
    EDIT = "edit"
    REPETITION = "repetition"
    REFERENCE = "reference"
    TEMPORAL = "temporal"
    UNRESOLVED = "unresolved"
    UNIT = "unit"
    QUANTITY = "quantity"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class CertificateReason(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    MISSING = "MISSING"
    VAGUE = "VAGUE"
    MISSING_CONTEXT = "MISSING_CONTEXT"
    UNREPRESENTABLE = "UNREPRESENTABLE"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


_AMBIGUOUS_ISSUE_PAIRS = frozenset(
    {(relation.value, "UNRESOLVED") for relation in (
        CertificateRelation.MULTIPLICITY, CertificateRelation.ORDER,
        CertificateRelation.EDIT, CertificateRelation.REPETITION,
        CertificateRelation.REFERENCE, CertificateRelation.TEMPORAL,
        CertificateRelation.UNRESOLVED,
    )} | {("quantity", "MISSING"), ("quantity", "VAGUE")}
)
_UNKNOWN_ISSUE_PAIRS = frozenset({
    ("reference", "MISSING_CONTEXT"), ("temporal", "UNREPRESENTABLE"),
    ("unresolved", "UNREPRESENTABLE"), ("unit", "MISSING"),
    ("unit", "UNSUPPORTED"), ("quantity", "INVALID"),
    ("quantity", "UNKNOWN"), ("unsupported", "UNSUPPORTED"),
    ("unknown", "UNKNOWN"),
})
ISSUE_STATUS_BY_PAIR = {
    **{pair: AuthorizationStatus.AMBIGUOUS for pair in _AMBIGUOUS_ISSUE_PAIRS},
    **{pair: AuthorizationStatus.UNKNOWN for pair in _UNKNOWN_ISSUE_PAIRS},
}


@dataclass(frozen=True)
class CertifiedAction:
    skill: SkillName
    scalar: float | None = None

    def to_list(self) -> list[Any]:
        return [self.skill.value] if self.skill is SkillName.STOP else [self.skill.value, self.scalar]


@dataclass(frozen=True)
class CertificateIssue:
    relation: CertificateRelation
    reason: CertificateReason

    @property
    def status(self) -> AuthorizationStatus:
        return ISSUE_STATUS_BY_PAIR[(self.relation.value, self.reason.value)]

    def to_dict(self) -> dict[str, str]:
        return {"relation": self.relation.value, "reason": self.reason.value}


@dataclass(frozen=True)
class SourceAuthorityCertificate:
    status: AuthorizationStatus
    checks: tuple[CheckVerdict, ...]
    plan: tuple[CertifiedAction, ...] | None
    issues: tuple[CertificateIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checks": [check.value for check in self.checks],
            "plan": [action.to_list() for action in self.plan] if self.plan is not None else None,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class CertificateOutcome:
    """Usable denotes semantic certificate validity, not release permission."""

    status: AuthorizationStatus
    usable: bool
    reason_code: str
    certificate: SourceAuthorityCertificate | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "usable": self.usable,
            "reason_code": self.reason_code,
            "certificate": self.certificate.to_dict() if self.certificate else None,
            "diagnostics": dict(self.diagnostics),
        }


class CertificateContractError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CertificateContractError("DUPLICATE_CERTIFICATE_KEY")
        result[key] = value
    return result


def _constant(name: str) -> None:
    raise CertificateContractError("NON_FINITE_CERTIFICATE_NUMBER")


def _finite(node: Any) -> None:
    if isinstance(node, float) and not math.isfinite(node):
        raise CertificateContractError("NON_FINITE_CERTIFICATE_NUMBER")
    if isinstance(node, dict):
        for value in node.values():
            _finite(value)
    if isinstance(node, list):
        for value in node:
            _finite(value)


def certificate_plan_mission(certificate: SourceAuthorityCertificate) -> Mission:
    """Host construction of canonical IDs/dependencies, without execution."""
    if certificate.status is not AuthorizationStatus.AUTHORIZED_UNIQUE or certificate.plan is None:
        raise CertificateContractError("NO_AUTHORIZED_CERTIFICATE_PLAN")
    parameter_keys = {
        SkillName.STAND: "duration_s", SkillName.WALK_FORWARD: "distance_m",
        SkillName.TURN: "angle_deg",
    }
    return Mission("source-certificate-v2", tuple(
        MissionStep(
            step_id=f"s{index}", skill=action.skill,
            parameters={} if action.skill is SkillName.STOP else {parameter_keys[action.skill]: action.scalar},
            depends_on=() if index == 1 else (f"s{index - 1}",),
        ) for index, action in enumerate(certificate.plan, start=1)
    ))


def parse_certificate(raw: str) -> SourceAuthorityCertificate:
    """Parse one compact JSON object; reject every shape/status inconsistency."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_CERTIFICATE_CHARS:
        raise CertificateContractError("UNUSABLE_CERTIFICATE_RESPONSE")
    try:
        payload = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (json.JSONDecodeError, TypeError, RecursionError):
        raise CertificateContractError("MALFORMED_CERTIFICATE_RESPONSE") from None
    _finite(payload)
    if not isinstance(payload, dict) or set(payload) != {"status", "checks", "plan", "issues"}:
        raise CertificateContractError("INVALID_CERTIFICATE_SCHEMA")
    try:
        status = AuthorizationStatus(payload["status"])
    except (ValueError, TypeError):
        raise CertificateContractError("INVALID_CERTIFICATE_STATUS") from None
    checks_raw = payload["checks"]
    if not isinstance(checks_raw, list) or len(checks_raw) != len(CHECK_DIMENSIONS):
        raise CertificateContractError("INVALID_CERTIFICATE_CHECKS")
    try:
        checks = tuple(CheckVerdict(check) for check in checks_raw)
    except (ValueError, TypeError):
        raise CertificateContractError("INVALID_CERTIFICATE_CHECKS") from None
    derived = (
        AuthorizationStatus.AMBIGUOUS if CheckVerdict.AMBIGUOUS in checks
        else AuthorizationStatus.UNKNOWN if CheckVerdict.UNKNOWN in checks
        else AuthorizationStatus.AUTHORIZED_UNIQUE
    )
    if status is not derived:
        raise CertificateContractError("CERTIFICATE_STATUS_DISAGREEMENT")
    issues_raw = payload["issues"]
    if not isinstance(issues_raw, list) or len(issues_raw) > MAX_CERTIFICATE_ISSUES:
        raise CertificateContractError("INVALID_CERTIFICATE_ISSUES")
    issues = []
    seen = set()
    for issue in issues_raw:
        if not isinstance(issue, dict) or set(issue) != {"relation", "reason"}:
            raise CertificateContractError("INVALID_CERTIFICATE_ISSUES")
        try:
            relation, reason = CertificateRelation(issue["relation"]), CertificateReason(issue["reason"])
        except (ValueError, TypeError):
            raise CertificateContractError("INVALID_CERTIFICATE_ISSUES") from None
        pair = (relation.value, reason.value)
        if pair not in ISSUE_STATUS_BY_PAIR or pair in seen:
            raise CertificateContractError("INVALID_CERTIFICATE_ISSUE_PAIR")
        relation_index = {
            "multiplicity": 0, "order": 1, "edit": 2, "repetition": 3,
            "reference": 4, "temporal": 5, "unresolved": 6,
            "unit": 6, "quantity": 6, "unsupported": 6, "unknown": 6,
        }[relation.value]
        issue_status = ISSUE_STATUS_BY_PAIR[pair]
        flag = checks[relation_index]
        if (flag is CheckVerdict.UNIQUE
                or issue_status is AuthorizationStatus.AMBIGUOUS and flag is not CheckVerdict.AMBIGUOUS
                or issue_status is AuthorizationStatus.UNKNOWN and flag is CheckVerdict.AMBIGUOUS
                   and status is not AuthorizationStatus.AMBIGUOUS):
            raise CertificateContractError("CERTIFICATE_ISSUE_CHECK_DISAGREEMENT")
        seen.add(pair)
        issues.append(CertificateIssue(relation, reason))
    if status is not AuthorizationStatus.AUTHORIZED_UNIQUE:
        if payload["plan"] is not None:
            raise CertificateContractError("REJECTED_CERTIFICATE_PLAN_MUST_BE_NULL")
        if not issues or not any(issue.status is status for issue in issues):
            raise CertificateContractError("CERTIFICATE_ISSUE_STATUS_DISAGREEMENT")
        if status is AuthorizationStatus.UNKNOWN and any(issue.status is AuthorizationStatus.AMBIGUOUS for issue in issues):
            raise CertificateContractError("CERTIFICATE_ISSUE_STATUS_DISAGREEMENT")
        return SourceAuthorityCertificate(status, checks, None, tuple(issues))
    if issues:
        raise CertificateContractError("AUTHORIZED_CERTIFICATE_HAS_ISSUES")
    plan_raw = payload["plan"]
    if not isinstance(plan_raw, list) or not 1 <= len(plan_raw) <= MAX_MISSION_STEPS:
        raise CertificateContractError("INVALID_CERTIFICATE_PLAN")
    plan = []
    for action in plan_raw:
        if not isinstance(action, list) or not action or not isinstance(action[0], str):
            raise CertificateContractError("INVALID_CERTIFICATE_PLAN")
        try:
            skill = SkillName(action[0])
        except ValueError:
            raise CertificateContractError("INVALID_CERTIFICATE_PLAN") from None
        if skill is SkillName.STOP:
            if len(action) != 1:
                raise CertificateContractError("INVALID_CERTIFICATE_PLAN")
            plan.append(CertifiedAction(skill))
        else:
            if len(action) != 2 or isinstance(action[1], bool) or not isinstance(action[1], (int, float)):
                raise CertificateContractError("INVALID_CERTIFICATE_PLAN")
            if not math.isfinite(float(action[1])):
                raise CertificateContractError("NON_FINITE_CERTIFICATE_NUMBER")
            plan.append(CertifiedAction(skill, float(action[1])))
    certificate = SourceAuthorityCertificate(status, checks, tuple(plan), ())
    if not MissionValidator().validate(certificate_plan_mission(certificate)).valid:
        raise CertificateContractError("INVALID_CERTIFICATE_PLAN")
    return certificate


class SourceAuthorityCertificateIssuer:
    """Stage 1 source-only certificate; stage 2 deterministic exact host check."""

    treatment = TREATMENT_CERTIFICATE_V2
    source_aware = True

    def __init__(self, backend: LLMBackend, *, prompt_path: str | Path | None = None) -> None:
        self.backend = backend
        raw = resolve_repo_path(prompt_path or "prompts/authority_certificate_v2.txt").read_bytes()
        self.prompt_text = raw.decode("utf-8")
        self.prompt_sha256 = hashlib.sha256(raw).hexdigest()

    def issue_certificate(self, source: str) -> CertificateOutcome:
        """This first-stage signature has no candidate or candidate-derived data."""
        started = time.perf_counter()
        evidence: dict[str, Any] = {
            "treatment": self.treatment, "certificate_version": "v2",
            "candidate_blind": True, "provider_calls": 0, "attempts": 0,
            "automatic_repair": False, "raw_response": None, "usage": None,
            "prompt_sha256": self.prompt_sha256,
            "configured_model": str(getattr(self.backend, "model", "unknown")),
            "request_input_fields": ["source"],
        }

        def finish(status: AuthorizationStatus, usable: bool, reason: str,
                   certificate: SourceAuthorityCertificate | None = None) -> CertificateOutcome:
            evidence["latency_s"] = time.perf_counter() - started
            return CertificateOutcome(status, usable, reason, certificate, evidence)

        if not isinstance(source, str) or not source.strip() or len(source) > MAX_SOURCE_CHARS:
            return finish(AuthorizationStatus.UNKNOWN, False, "INVALID_SOURCE_INPUT")
        user_text = json.dumps({"source": source}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        evidence["source_sha256"] = _digest(source)
        evidence["request_input_sha256"] = _digest(user_text)
        evidence["provider_calls"] = 1
        try:
            response = self.backend.complete(system_prompt=self.prompt_text, user_text=user_text)
        except LLMBackendError as exc:
            evidence.update({"attempts": exc.attempts, "backend_failure_type": exc.failure_type})
            return finish(AuthorizationStatus.UNKNOWN, False, "BACKEND_FAILURE")
        except LLMConfigurationError:
            evidence.update({"attempts": 0, "backend_failure_type": "CONFIGURATION_ERROR"})
            return finish(AuthorizationStatus.UNKNOWN, False, "BACKEND_FAILURE")
        except Exception as exc:
            evidence.update({"attempts": None, "backend_failure_type": type(exc).__name__})
            return finish(AuthorizationStatus.UNKNOWN, False, "BACKEND_FAILURE")
        try:
            evidence.update({
                "raw_response": response.text, "raw_response_sha256": _digest(response.text),
                "model": response.model, "attempts": response.attempts,
                "provider_latency_s": response.latency_s,
                "request_parameters": dict(response.request_parameters),
                "usage": dict(response.usage) if response.usage else None,
                "response_id": response.response_id, "provider_status": response.provider_status,
                "finish_reason": response.finish_reason,
            })
            if response.model != evidence["configured_model"]:
                return finish(AuthorizationStatus.UNKNOWN, False, "PROVIDER_MODEL_MISMATCH")
            if response.provider_status != "completed" or response.finish_reason not in {"completed", "stop", "end_turn", "eos_token"}:
                return finish(AuthorizationStatus.UNKNOWN, False, "INCOMPLETE_PROVIDER_RESPONSE")
            certificate = parse_certificate(response.text)
        except CertificateContractError as exc:
            return finish(AuthorizationStatus.UNKNOWN, False, exc.reason_code)
        except Exception:
            return finish(AuthorizationStatus.UNKNOWN, False, "UNUSABLE_CERTIFICATE_RESPONSE")
        reason = {
            AuthorizationStatus.AUTHORIZED_UNIQUE: "UNIQUE_SOURCE_CERTIFICATE",
            AuthorizationStatus.AMBIGUOUS: "SEMANTIC_AMBIGUOUS",
            AuthorizationStatus.UNKNOWN: "SEMANTIC_UNKNOWN",
        }[certificate.status]
        return finish(certificate.status, True, reason, certificate)

    def authorize(self, source: str, candidate_ir: Mission | Mapping[str, Any]) -> AuthorizationResult:
        # This must precede ALL access to the candidate, including validating
        # it or using its size/status to choose a provider request.
        outcome = self.issue_certificate(source)
        diagnostics = dict(outcome.diagnostics)
        diagnostics.update({
            "certificate_usable": outcome.usable,
            "certificate_status": outcome.status.value,
            "certificate_reason_code": outcome.reason_code,
            "certificate": outcome.certificate.to_dict() if outcome.certificate else None,
        })
        if not outcome.usable or outcome.status is not AuthorizationStatus.AUTHORIZED_UNIQUE:
            return AuthorizationResult(outcome.status, outcome.reason_code, diagnostics)
        try:
            source_plan = certificate_plan_mission(outcome.certificate)
            validation = MissionValidator().validate(source_plan)
            diagnostics["authorized_plan_validation"] = validation.to_dict()
            if not validation.valid:
                return AuthorizationResult(AuthorizationStatus.UNKNOWN, "INVALID_CERTIFICATE_PLAN", diagnostics)
            candidate_doc = candidate_ir.to_dict() if isinstance(candidate_ir, Mission) else candidate_ir
            candidate = Mission.from_dict(candidate_doc)
            if any(step.execution_mode_override is not None for step in candidate.steps):
                return AuthorizationResult(AuthorizationStatus.UNKNOWN, "FORBIDDEN_CANDIDATE_FIELD", diagnostics)
            candidate_validation = MissionValidator().validate(candidate)
            diagnostics["candidate_validation"] = candidate_validation.to_dict()
            if not candidate_validation.valid:
                return AuthorizationResult(AuthorizationStatus.UNKNOWN, "INVALID_CANDIDATE_IR", diagnostics)
            match = comparison_payload(source_plan, allow_text_numbers=False) == comparison_payload(candidate, allow_text_numbers=False)
            diagnostics["plan_matches_candidate"] = match
            if not match:
                return AuthorizationResult(AuthorizationStatus.UNKNOWN, "AUTHORIZED_PLAN_DISAGREEMENT", diagnostics)
        except Exception:
            return AuthorizationResult(AuthorizationStatus.UNKNOWN, "INVALID_CANDIDATE_IR", diagnostics)
        return AuthorizationResult(AuthorizationStatus.AUTHORIZED_UNIQUE, "UNIQUE_SOURCE_AUTHORITY", diagnostics)


SourceAuthorizationV2Verifier = SourceAuthorityCertificateIssuer

__all__ = [
    "CHECK_DIMENSIONS", "CheckVerdict",
    "CertificateContractError", "CertificateIssue", "CertificateOutcome",
    "CertificateReason", "CertificateRelation", "CertifiedAction",
    "ISSUE_STATUS_BY_PAIR", "SourceAuthorityCertificate",
    "SourceAuthorityCertificateIssuer", "SourceAuthorizationV2Verifier",
    "TREATMENT_CERTIFICATE_V2", "certificate_plan_mission", "parse_certificate",
]
