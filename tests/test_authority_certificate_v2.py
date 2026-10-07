"""Candidate-blind certificate contract tests; synthetic sources only."""

from __future__ import annotations

import copy
import json

import pytest

from g1swarm.authority_certificate_v2 import (
    CertificateContractError,
    CheckVerdict,
    SourceAuthorityCertificateIssuer,
    certificate_plan_mission,
    parse_certificate,
)
from g1swarm.language.errors import CompilerStatus
from g1swarm.language.result import CompilerResult
from g1swarm.llm.backend import LLMBackendError, LLMBackendResponse
from g1swarm.mission.ir import Mission
from g1swarm.source_authority import AuthorizationStatus, apply_gate

SOURCE = "先站立7秒，然后左转12度，最后停止。"


def _unique() -> dict:
    return {"status": "AUTHORIZED_UNIQUE", "checks": ["U"] * 7,
            "plan": [["stand", 7], ["turn", 12], ["stop"]], "issues": []}


def _rejection(status: str = "AMBIGUOUS") -> dict:
    return {"status": status, "checks": ["U"] * 6 + ["A" if status == "AMBIGUOUS" else "?"],
            "plan": None, "issues": [{"relation": "unresolved", "reason": "UNRESOLVED"}]
            if status == "AMBIGUOUS" else [{"relation": "unknown", "reason": "UNKNOWN"}]}


def _mission() -> Mission:
    return certificate_plan_mission(parse_certificate(json.dumps(_unique())))


class _Backend:
    name = "certificate-test"
    model = "deepseek-flash"

    def __init__(self, payload: dict | str, *, provider_status="completed", finish_reason="completed",
                 model: str | None = None):
        self.raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        self.provider_status = provider_status
        self.finish_reason = finish_reason
        self.response_model = model or self.model
        self.requests = []

    def complete(self, *, system_prompt, user_text):
        self.requests.append({"system_prompt": system_prompt, "user_text": user_text})
        return LLMBackendResponse(self.raw, self.response_model, 0.15, 1,
                                  {"model": self.model, "temperature": 0.0, "max_output_tokens": 4096},
                                  {"input_tokens": 120, "output_tokens": 60, "total_tokens": 180},
                                  "certificate-response", self.finish_reason, self.provider_status)


def test_firststage_only_source_and_compact_typed_certificate() -> None:
    backend = _Backend(_unique())
    issuer = SourceAuthorityCertificateIssuer(backend)
    outcome = issuer.issue_certificate(SOURCE)
    assert outcome.usable and outcome.status is AuthorizationStatus.AUTHORIZED_UNIQUE
    assert outcome.certificate.to_dict() == _unique()
    assert outcome.certificate.checks == (CheckVerdict.UNIQUE,) * 7
    assert json.loads(backend.requests[0]["user_text"]) == {"source": SOURCE}
    assert set(json.loads(backend.requests[0]["user_text"])) == {"source"}
    assert "candidate_ir" not in backend.requests[0]["user_text"]
    assert outcome.diagnostics["candidate_blind"] is True
    assert outcome.diagnostics["usage"]["total_tokens"] == 180
    assert outcome.diagnostics["raw_response"] == backend.raw
    assert outcome.diagnostics["provider_status"] == "completed"


def test_provider_request_is_identical_for_correct_wrong_and_invalid_candidates() -> None:
    backend = _Backend(_unique())
    issuer = SourceAuthorityCertificateIssuer(backend)
    correct = _mission()
    wrong_doc = copy.deepcopy(correct.to_dict())
    wrong_doc["steps"][1]["parameters"]["angle_deg"] = -12
    candidates = [correct, Mission.from_dict(wrong_doc), {"not": "a mission"}, None]
    outcomes = [issuer.authorize(SOURCE, candidate) for candidate in candidates]
    assert outcomes[0].authorized
    assert all(not outcome.authorized for outcome in outcomes[1:])
    assert len(backend.requests) == len(candidates)
    assert all(request == backend.requests[0] for request in backend.requests)


def test_candidate_is_not_even_read_until_certificate_request_completed() -> None:
    backend = _Backend(_unique())

    class CandidateAfterProvider(Mission):
        def to_dict(self):
            assert len(backend.requests) == 1
            return super().to_dict()

    mission = _mission()
    candidate = CandidateAfterProvider(mission.mission_id, mission.steps)
    assert SourceAuthorityCertificateIssuer(backend).authorize(SOURCE, candidate).authorized


def test_semantic_rejection_never_touches_candidate() -> None:
    class UnreadableCandidate(Mission):
        def to_dict(self):
            raise AssertionError("candidate must remain unread")

    mission = _mission()
    candidate = UnreadableCandidate(mission.mission_id, mission.steps)
    backend = _Backend(_rejection())
    outcome = SourceAuthorityCertificateIssuer(backend).authorize(SOURCE, candidate)
    assert outcome.status is AuthorizationStatus.AMBIGUOUS
    assert outcome.diagnostics["certificate_usable"] is True
    assert len(backend.requests) == 1


@pytest.mark.parametrize("status", ["AMBIGUOUS", "UNKNOWN"])
def test_semantic_rejections_are_usable_but_never_released(status: str) -> None:
    backend = _Backend(_rejection(status))
    issuer = SourceAuthorityCertificateIssuer(backend)
    outcome = issuer.issue_certificate(SOURCE)
    assert outcome.usable
    assert outcome.status.value == status
    assert outcome.certificate.plan is None
    baseline = CompilerResult(CompilerStatus.SUCCESS, _mission(), SOURCE)
    gated = apply_gate(SOURCE, baseline, issuer)
    assert gated.mission is None
    assert gated.diagnostics["source_authorization"]["diagnostics"]["certificate_usable"] is True


@pytest.mark.parametrize("index,relation", list(enumerate(["multiplicity", "order", "edit", "repetition", "reference", "temporal", "unresolved"])))
def test_all_seven_ambiguity_dimensions_withhold_plan(index: int, relation: str) -> None:
    payload = _rejection()
    payload["checks"] = ["U"] * 7
    payload["checks"][index] = "A"
    payload["issues"] = [{"relation": relation, "reason": "UNRESOLVED"}]
    outcome = SourceAuthorityCertificateIssuer(_Backend(payload)).issue_certificate(SOURCE)
    assert outcome.usable and outcome.status is AuthorizationStatus.AMBIGUOUS


@pytest.mark.parametrize("pair", [("reference", "MISSING_CONTEXT"), ("temporal", "UNREPRESENTABLE"), ("unresolved", "UNREPRESENTABLE"), ("unit", "MISSING"), ("unit", "UNSUPPORTED"), ("quantity", "INVALID"), ("quantity", "UNKNOWN"), ("unsupported", "UNSUPPORTED"), ("unknown", "UNKNOWN")])
def test_unknown_issue_pairs_are_typed_semantic_rejections(pair) -> None:
    relation, reason = pair
    payload = _rejection("UNKNOWN")
    payload["checks"] = ["U"] * 7
    payload["checks"][{"reference": 4, "temporal": 5}.get(relation, 6)] = "?"
    payload["issues"] = [{"relation": relation, "reason": reason}]
    outcome = SourceAuthorityCertificateIssuer(_Backend(payload)).issue_certificate(SOURCE)
    assert outcome.usable and outcome.status is AuthorizationStatus.UNKNOWN


def test_ambiguity_dominates_unknown_without_discarding_typed_issue() -> None:
    payload = _rejection()
    payload["checks"][4] = "?"
    payload["issues"].append({"relation": "reference", "reason": "MISSING_CONTEXT"})
    outcome = SourceAuthorityCertificateIssuer(_Backend(payload)).issue_certificate(SOURCE)
    assert outcome.usable and outcome.status is AuthorizationStatus.AMBIGUOUS
    assert len(outcome.certificate.issues) == 2


@pytest.mark.parametrize("raw", ["", "no json", "[]", "null", "{}", "{} {}", "```json\n{}\n```", "{\"status\":NaN}", "{\"status\":Infinity}", "{\"status\":1e999}", "{\"status\":\"UNKNOWN\",\"status\":\"AUTHORIZED_UNIQUE\"}"])
def test_bad_output_is_unusable_unknown_and_not_repaired(raw: str) -> None:
    backend = _Backend(raw)
    outcome = SourceAuthorityCertificateIssuer(backend).issue_certificate(SOURCE)
    assert outcome.status is AuthorizationStatus.UNKNOWN
    assert not outcome.usable and outcome.certificate is None
    assert len(backend.requests) == 1


@pytest.mark.parametrize("change", ["extra", "checks_short", "checks_long", "checks_bool", "checks_bad", "unique_A", "unique_question", "empty_plan", "oversize_plan", "stop_scalar", "stand_no_scalar", "boolean_scalar", "text_scalar", "unknown_skill", "extra_scalar", "invalid_range", "unique_issue", "issue_extra", "issue_duplicate", "issue_badpair", "issue_flag_disagreement"])
def test_strict_schema_rejects_malformed_certificates(change: str) -> None:
    payload = _unique()
    if change == "extra":
        payload["confidence"] = 1
    elif change == "checks_short":
        payload["checks"].pop()
    elif change == "checks_long":
        payload["checks"].append("U")
    elif change == "checks_bool":
        payload["checks"][0] = True
    elif change == "checks_bad":
        payload["checks"][0] = "UNIQUE"
    elif change == "unique_A":
        payload["checks"][0] = "A"
    elif change == "unique_question":
        payload["checks"][0] = "?"
    elif change == "empty_plan":
        payload["plan"] = []
    elif change == "oversize_plan":
        payload["plan"] = [["stop"]] * 33
    elif change == "stop_scalar":
        payload["plan"][-1].append(1)
    elif change == "stand_no_scalar":
        payload["plan"][0].pop()
    elif change == "boolean_scalar":
        payload["plan"][0][1] = True
    elif change == "text_scalar":
        payload["plan"][0][1] = "7"
    elif change == "unknown_skill":
        payload["plan"][0][0] = "teleport"
    elif change == "extra_scalar":
        payload["plan"][0].append(5)
    elif change == "invalid_range":
        payload["plan"][0][1] = 61
    elif change == "unique_issue":
        payload["issues"] = [{"relation": "unresolved", "reason": "UNRESOLVED"}]
    else:
        payload = _rejection()
        if change == "issue_extra":
            payload["issues"][0]["rationale"] = "not allowed"
        elif change == "issue_duplicate":
            payload["issues"].append(copy.deepcopy(payload["issues"][0]))
        elif change == "issue_badpair":
            payload["issues"][0]["reason"] = "MISSING"
        else:
            payload["checks"][6] = "U"
            payload["checks"][0] = "A"
    outcome = SourceAuthorityCertificateIssuer(_Backend(payload)).issue_certificate(SOURCE)
    assert outcome.status is AuthorizationStatus.UNKNOWN and not outcome.usable


@pytest.mark.parametrize("change", ["nonnull_plan", "no_issues", "wrong_issue_status", "unknown_with_ambiguous_issue", "status_disagreement"])
def test_rejection_contract_is_consistent(change: str) -> None:
    payload = _rejection("UNKNOWN")
    if change == "nonnull_plan":
        payload["plan"] = [["stop"]]
    elif change == "no_issues":
        payload["issues"] = []
    elif change in {"wrong_issue_status", "unknown_with_ambiguous_issue"}:
        payload["issues"] = [{"relation": "unresolved", "reason": "UNRESOLVED"}]
    else:
        payload["status"] = "AMBIGUOUS"
    assert not SourceAuthorityCertificateIssuer(_Backend(payload)).issue_certificate(SOURCE).usable


@pytest.mark.parametrize("provider_status,finish_reason", [(None, None), ("completed", None), ("incomplete", "max_output_tokens"), ("completed", "length"), ("failed", "stop")])
def test_completion_provenance_is_explicit(provider_status, finish_reason) -> None:
    outcome = SourceAuthorityCertificateIssuer(_Backend(_unique(), provider_status=provider_status,
                                                        finish_reason=finish_reason)).issue_certificate(SOURCE)
    assert outcome.status is AuthorizationStatus.UNKNOWN and not outcome.usable
    assert outcome.reason_code == "INCOMPLETE_PROVIDER_RESPONSE"


def test_model_provenance_exact_match() -> None:
    outcome = SourceAuthorityCertificateIssuer(_Backend(_unique(), model="another-model")).issue_certificate(SOURCE)
    assert not outcome.usable and outcome.reason_code == "PROVIDER_MODEL_MISMATCH"


@pytest.mark.parametrize("change", ["count", "order", "parameter", "ids", "dependencies"])
def test_host_exact_candidate_comparison(change: str) -> None:
    candidate = _mission().to_dict()
    steps = candidate["steps"]
    if change == "count":
        steps.append({"id": "s4", "skill": "stop", "parameters": {}, "depends_on": ["s3"]})
    elif change == "order":
        steps[0]["skill"], steps[1]["skill"] = steps[1]["skill"], steps[0]["skill"]
        steps[0]["parameters"], steps[1]["parameters"] = steps[1]["parameters"], steps[0]["parameters"]
    elif change == "parameter":
        steps[1]["parameters"]["angle_deg"] = 13
    elif change == "ids":
        steps[0]["id"] = "first"
        steps[1]["depends_on"] = ["first"]
    else:
        steps[1]["depends_on"] = []
    result = SourceAuthorityCertificateIssuer(_Backend(_unique())).authorize(SOURCE, candidate)
    assert result.status is AuthorizationStatus.UNKNOWN
    assert result.reason_code == "AUTHORIZED_PLAN_DISAGREEMENT"
    assert result.diagnostics["certificate_usable"] is True


def test_mission_identity_ignored_and_released_candidate_unchanged() -> None:
    document = _mission().to_dict()
    document["mission_id"] = "candidate-identity"
    candidate = Mission.from_dict(document)
    baseline = CompilerResult(CompilerStatus.SUCCESS, candidate, SOURCE)
    before = copy.deepcopy(baseline.to_dict())
    result = apply_gate(SOURCE, baseline, SourceAuthorityCertificateIssuer(_Backend(_unique())))
    assert result.success and result.mission is candidate
    assert baseline.to_dict() == before


@pytest.mark.parametrize("source", [None, "", " ", "x" * 8193])
def test_invalid_source_fails_before_provider(source) -> None:
    backend = _Backend(_unique())
    outcome = SourceAuthorityCertificateIssuer(backend).issue_certificate(source)
    assert not outcome.usable and backend.requests == []


def test_response_bound() -> None:
    assert not SourceAuthorityCertificateIssuer(_Backend(" " * 16385)).issue_certificate(SOURCE).usable


def test_backend_transport_failure_retains_attempts_without_semantic_retry() -> None:
    class FailingBackend:
        model = "deepseek-flash"
        calls = 0

        def complete(self, **kwargs):
            self.calls += 1
            raise LLMBackendError("TIMEOUT", "network failure", attempts=3)

    backend = FailingBackend()
    outcome = SourceAuthorityCertificateIssuer(backend).issue_certificate(SOURCE)
    assert not outcome.usable and outcome.reason_code == "BACKEND_FAILURE"
    assert outcome.diagnostics["attempts"] == 3
    assert backend.calls == 1


def test_firststage_and_compact_prompt_are_fixed() -> None:
    issuer = SourceAuthorityCertificateIssuer(_Backend(_unique()))
    assert len(issuer.prompt_text.split()) <= 400
    assert "tuple field names never supply missing units" in issuer.prompt_text
    assert "confidence" in issuer.prompt_text
    assert "source copies" in issuer.prompt_text


def test_parse_function_exposes_typed_contract_failures() -> None:
    with pytest.raises(CertificateContractError):
        parse_certificate('{"status":"UNKNOWN","checks":[],"plan":null,"issues":[]}')
