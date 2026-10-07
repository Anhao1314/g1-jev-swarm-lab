"""Exploratory bounded control tests using synthetic examples, without models."""

from __future__ import annotations

import copy
import hashlib

import pytest

from g1swarm.language.compiler import LanguageCompiler
from g1swarm.language.errors import CompilerStatus
from g1swarm.language.result import CompilerResult
from g1swarm.mission.ir import Mission
from g1swarm.source_authority import AuthorizationStatus, apply_gate
from g1swarm.source_authority_bounded import BoundedSourceAuthorizationVerifier


def _baseline(source: str) -> CompilerResult:
    result = LanguageCompiler().compile(source)
    assert result.success
    return CompilerResult(CompilerStatus.SUCCESS, result.mission, result.normalized_text,
                          diagnostics={"architecture": "guarded_direct_llm_v1"})


@pytest.mark.parametrize("source", ["站立", "先站立3秒，然后前进6米，最后停止。", "前进200cm再右转三十度然后停止", " 站立３秒；前进６米。\n", "左转135度", "前进125米"])
def test_bounded_unique_source_authorizes_exact_plan(source: str) -> None:
    baseline = _baseline(source)
    before = copy.deepcopy(baseline.to_dict())
    result = apply_gate(source, baseline, BoundedSourceAuthorizationVerifier())
    assert result.success
    assert result.mission is baseline.mission
    assert baseline.to_dict() == before
    evidence = result.diagnostics["source_authorization"]["diagnostics"]
    assert evidence["provider_calls"] == 0
    assert evidence["exploratory_post_hoc"] is True
    assert evidence["parse_witness"]["full_consumption"] is True
    normalized = evidence["normalized_source_witness"]["text"]
    assert "".join(token["text"] for token in evidence["parse_witness"]["tokens"]) == normalized
    assert evidence["source_witness"]["text"] == source
    assert evidence["source_witness"]["sha256"] == hashlib.sha256(source.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("suffix", ["，范围尚未确定", "，重复以上动作但次数待定", "，修改哪一步稍后说明", "，先后关系尚未确定", "，另一项指令取决于外部消息", " extra unknown suffix", "，同时响铃"])
def test_entire_source_unrecognized_suffix_is_never_dropped(suffix: str) -> None:
    source = "站立3秒" + suffix
    authorizer = BoundedSourceAuthorizationVerifier()
    authority = authorizer.authorize(source, _baseline("站立3秒").mission)
    assert authority.status is AuthorizationStatus.UNKNOWN
    assert authority.reason_code == "OUTSIDE_BOUNDED_LANGUAGE"
    assert authority.diagnostics["source_witness"]["text"] == source
    assert "parse_witness" not in authority.diagnostics


@pytest.mark.parametrize("source", ["前进一点", "右转", "前进"])
def test_frozen_compiler_ambiguity_is_preserved(source: str) -> None:
    authority = BoundedSourceAuthorizationVerifier().authorize(source, _baseline("站立").mission)
    assert authority.status is AuthorizationStatus.AMBIGUOUS
    assert authority.reason_code == "BOUNDED_SOURCE_AMBIGUOUS"


@pytest.mark.parametrize("source", ["跳一下", "前进5英尺", "站立3秒之前先做别的", "前进2米重复三次", "", None])
def test_unsupported_malformed_or_outside_language_is_unknown(source) -> None:
    authority = BoundedSourceAuthorizationVerifier().authorize(source, _baseline("站立").mission)
    assert authority.status is AuthorizationStatus.UNKNOWN
    assert not authority.authorized


@pytest.mark.parametrize("change", ["multiplicity", "order", "parameters", "ids", "dependencies"])
def test_exact_candidate_comparison_detects_all_semantic_fields(change: str) -> None:
    source = "站立3秒然后前进6米"
    baseline = _baseline(source)
    document = copy.deepcopy(baseline.mission.to_dict())
    steps = document["steps"]
    if change == "multiplicity":
        steps.append({"id": "s3", "skill": "stop", "parameters": {}, "depends_on": ["s2"]})
    elif change == "order":
        steps[0]["skill"], steps[1]["skill"] = steps[1]["skill"], steps[0]["skill"]
        steps[0]["parameters"], steps[1]["parameters"] = steps[1]["parameters"], steps[0]["parameters"]
    elif change == "parameters":
        steps[1]["parameters"]["distance_m"] = 7
    elif change == "ids":
        steps[0]["id"] = "first"
        steps[1]["id"] = "second"
        steps[1]["depends_on"] = ["first"]
    else:
        steps[1]["depends_on"] = []
    authority = BoundedSourceAuthorizationVerifier().authorize(source, Mission.from_dict(document))
    assert authority.status is AuthorizationStatus.UNKNOWN
    assert authority.reason_code == "AUTHORIZED_PLAN_DISAGREEMENT"


def test_mission_identity_is_ignored() -> None:
    source = "站立3秒"
    document = _baseline(source).mission.to_dict()
    document["mission_id"] = "another-identity"
    assert BoundedSourceAuthorizationVerifier().authorize(source, Mission.from_dict(document)).authorized


@pytest.mark.parametrize("source", ["前进1 2米", "前进１ ２米", "前进1 .2米", "前进1. 2米", "前进三 十米"])
def test_frozen_normalization_numeric_merging_is_unknown_without_changing_B(source: str) -> None:
    baseline = _baseline(source)
    result = BoundedSourceAuthorizationVerifier().authorize(source, baseline.mission)
    assert result.status is AuthorizationStatus.UNKNOWN
    assert result.reason_code == "NORMALIZATION_QUANTITY_LOSS_RISK"
    assert baseline.success
    assert result.diagnostics["normalized_source_witness"]["changed"] is True
    assert any(not item["contiguous"] for item in result.diagnostics["quantity_normalization_witness"])
    assert "whitespace removal" in result.diagnostics["normalization_assumption"]


def test_whitespace_between_quantity_and_unit_does_not_invent_number() -> None:
    source = "前进12 米"
    result = BoundedSourceAuthorizationVerifier().authorize(source, _baseline(source).mission)
    assert result.authorized
    assert all(item["contiguous"] for item in result.diagnostics["quantity_normalization_witness"])


def test_guard_still_blocks_normalizer_structural_repair() -> None:
    source = "站立3秒然后，停止"
    # Frozen LanguageCompiler accepts this normalization; frozen Guard blocks
    # release first, and the bounded control does not replace that Guard.
    baseline = _baseline(source)
    result = apply_gate(source, baseline, BoundedSourceAuthorizationVerifier())
    assert result.mission is None
    assert result.diagnostics["source_authorization"]["reason_code"] == "GUARD_REJECT"


def test_invalid_ir_cannot_be_authorized() -> None:
    document = _baseline("前进6米").mission.to_dict()
    document["steps"][0]["parameters"]["distance_m"] = -6
    result = BoundedSourceAuthorizationVerifier().authorize("前进6米", document)
    assert result.status is AuthorizationStatus.UNKNOWN
    assert result.reason_code == "INVALID_CANDIDATE_IR"


def test_execution_override_is_forbidden() -> None:
    document = _baseline("站立").mission.to_dict()
    document["steps"][0]["execution_mode_override"] = "open_loop"
    result = BoundedSourceAuthorizationVerifier().authorize("站立", document)
    assert result.status is AuthorizationStatus.UNKNOWN
    assert result.reason_code == "FORBIDDEN_CANDIDATE_FIELD"


def test_compiler_normalized_bound_is_preserved() -> None:
    source = "前进1米然后" * 150 + "停止"
    result = BoundedSourceAuthorizationVerifier().authorize(source, _baseline("站立").mission)
    assert result.status is AuthorizationStatus.UNKNOWN
    assert result.diagnostics["bounded_compiler"]["error_code"] == "INPUT_TOO_LONG"
