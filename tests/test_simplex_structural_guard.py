"""Tests for the Phase 2.2b trusted structural guard.

The guard is the only layer that runs before any model call in the simplex
router.  These tests pin three properties:

1. the two Phase 2.2 controlled-regression holes are rejected with typed
   reasons;
2. no frozen valid/ambiguous/unsupported sample is ever rejected
   (guard false positive rate stays at zero on the legacy corpora);
3. the router actually consumes the guard: malformed input is rejected with
   zero model invocations, while valid open language still escalates.
"""

from __future__ import annotations

import pytest

from g1swarm.language.compiler import LanguageCompiler
from g1swarm.language.corpus import load_corpus
from g1swarm.language.errors import CompilerStatus
from g1swarm.llm.datasets import load_dataset
from g1swarm.paths import resolve_repo_path
from g1swarm.simplex.router import SimplexRoute, SimplexRouter
from g1swarm.simplex.structural_guard import (
    GuardReason,
    GuardStatus,
    StructuralGuard,
    check_structure,
)

CONTROLLED_CORPUS = "configs/language/controlled_language_001.yaml"
DEVELOPMENT_SET = "experiments/phase2/llm_compiler_001/development_set.yaml"
BLIND_SET = "experiments/phase2/llm_compiler_001/blind_test_set.yaml"

REGRESSION_016 = "前进4米，然后，然后，然后停止。"
REGRESSION_017 = "前进4米，，，，，"
VALID_OPEN_LANGUAGE = "麻烦先往前挪四米，然后朝右边转四十五度，最后停下来"
CANONICAL_REPAIR = "先前进4米，然后停止"


class _RepairingCanonicalizer:
    """Adversarial stub that would silently repair any input it can."""

    model = "repairing-stub"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def canonicalize(self, text: str) -> dict[str, object]:
        self.calls.append(text)
        return {"status": "SUCCESS", "canonical_text": CANONICAL_REPAIR, "error_code": None}


def _guard() -> StructuralGuard:
    return StructuralGuard()


# ---------------------------------------------------------------------------
# Verdict surface
# ---------------------------------------------------------------------------


def test_valid_inputs_pass_without_reason() -> None:
    guard = _guard()
    for utterance in (
        "站立",
        "先前进4米，然后右转45度，最后停止",
        "再往前走3米吧",
        "站立2秒。。。",
        "往前走一点",
        "拿个杯子",
    ):
        result = guard.check(utterance)
        assert result.status is GuardStatus.PASS
        assert result.passed
        assert result.reason_code is None
        assert result.to_dict()["status"] == "PASS"


def test_empty_and_invalid_inputs_are_rejected() -> None:
    guard = _guard()
    assert guard.check("").reason_code is GuardReason.EMPTY_INPUT
    assert guard.check("   ").reason_code is GuardReason.EMPTY_INPUT
    assert guard.check(None).reason_code is GuardReason.INVALID_INPUT  # type: ignore[arg-type]


def test_module_level_helper_matches_class() -> None:
    assert check_structure(REGRESSION_016).to_dict() == _guard().check(REGRESSION_016).to_dict()


def test_repeated_checks_are_deterministic() -> None:
    guard = _guard()
    first = guard.check(REGRESSION_016).to_dict()
    second = guard.check(REGRESSION_016).to_dict()
    assert first == second


# ---------------------------------------------------------------------------
# Regression holes and structural variants
# ---------------------------------------------------------------------------


def test_phase22_regression_016_is_rejected() -> None:
    result = _guard().check(REGRESSION_016)
    assert result.status is GuardStatus.MALFORMED
    assert result.reason_code is GuardReason.REPEATED_CONNECTOR


def test_phase22_regression_017_is_rejected() -> None:
    result = _guard().check(REGRESSION_017)
    assert result.status is GuardStatus.MALFORMED
    assert result.reason_code is GuardReason.REPEATED_SEPARATOR


@pytest.mark.parametrize(
    ("utterance", "reason"),
    [
        ("前进4米然后然后停止", GuardReason.REPEATED_CONNECTOR),
        ("前进4米，然后，然后停止", GuardReason.REPEATED_CONNECTOR),
        ("前进4米，最后，最后停止", GuardReason.REPEATED_CONNECTOR),
        ("前进4米，，，，", GuardReason.REPEATED_SEPARATOR),
        ("前进4米,,,", GuardReason.REPEATED_SEPARATOR),
        ("前进4米然后接着停止", GuardReason.DUPLICATE_CONNECTOR),
        ("前进4米，然后，停止", GuardReason.EMPTY_CLAUSE),
        ("前进4米。然后。停止", GuardReason.EMPTY_CLAUSE),
        ("然后前进4米", GuardReason.LEADING_CONNECTOR),
        ("先先前进4米", GuardReason.REPEATED_SEQUENCE_MARKER),
        ("前进4米然后", GuardReason.TRAILING_CONNECTOR),
        ("然后", GuardReason.CONNECTOR_ONLY),
        ("再", GuardReason.CONNECTOR_ONLY),
        ("先", GuardReason.SEQUENCE_MARKER_ONLY),
        ("先，", GuardReason.SEQUENCE_MARKER_ONLY),
        ("。。。", GuardReason.PUNCTUATION_ONLY),
    ],
)
def test_structural_variants_are_rejected(utterance: str, reason: GuardReason) -> None:
    result = _guard().check(utterance)
    assert result.status is GuardStatus.MALFORMED
    assert result.reason_code is reason


def test_guard_does_not_touch_tolerated_noise() -> None:
    guard = _guard()
    for utterance in ("站立2秒。。。", "再往前走3米吧", "往前走吧"):
        assert guard.check(utterance).status is GuardStatus.PASS


# ---------------------------------------------------------------------------
# Frozen corpora: zero false positives
# ---------------------------------------------------------------------------


def test_no_false_positive_on_controlled_corpus() -> None:
    guard = _guard()
    corpus = load_corpus(resolve_repo_path(CONTROLLED_CORPUS))
    by_id = {sample.sample_id: sample for sample in corpus.samples}
    for sample in corpus.samples:
        if sample.expected_compiler_status == "MALFORMED":
            continue
        assert guard.check(sample.utterance).passed, sample.sample_id
    for sample_id in ("cl-h-016", "cl-h-017"):
        assert guard.check(by_id[sample_id].utterance).malformed, sample_id


@pytest.mark.parametrize("path", [DEVELOPMENT_SET, BLIND_SET])
def test_no_false_positive_on_legacy_llm_datasets(path: str) -> None:
    guard = _guard()
    dataset = load_dataset(resolve_repo_path(path))
    for sample in dataset.samples:
        if sample.expected_compiler_status == "MALFORMED":
            continue
        assert guard.check(sample.utterance).passed, sample.sample_id


# ---------------------------------------------------------------------------
# Router integration
# ---------------------------------------------------------------------------


def test_router_guard_rejects_before_any_model_call() -> None:
    canonicalizer = _RepairingCanonicalizer()
    router = SimplexRouter(
        guard=_guard(),
        canonicalizer=canonicalizer,
        lark_compiler=LanguageCompiler(),
    )
    result = router.compile(REGRESSION_016)
    assert result.status is CompilerStatus.MALFORMED
    assert result.route is SimplexRoute.GUARD_REJECT
    assert result.guard_status == "MALFORMED"
    assert result.guard_reason_code == "REPEATED_CONNECTOR"
    assert result.llm_invocations == 0
    assert canonicalizer.calls == []


def test_router_guard_rejects_dangling_commas_before_model() -> None:
    canonicalizer = _RepairingCanonicalizer()
    router = SimplexRouter(
        guard=_guard(),
        canonicalizer=canonicalizer,
        lark_compiler=LanguageCompiler(),
    )
    result = router.compile(REGRESSION_017)
    assert result.status is CompilerStatus.MALFORMED
    assert result.route is SimplexRoute.GUARD_REJECT
    assert result.guard_reason_code == "REPEATED_SEPARATOR"
    assert canonicalizer.calls == []


def test_without_guard_the_repairing_model_gets_the_malformed_input() -> None:
    """Documents the threat model the guard exists to close."""

    canonicalizer = _RepairingCanonicalizer()
    router = SimplexRouter(canonicalizer=canonicalizer, lark_compiler=LanguageCompiler())
    result = router.compile(REGRESSION_016)
    assert canonicalizer.calls == [REGRESSION_016]
    assert result.llm_invocations == 1


def test_router_still_escalates_valid_open_language() -> None:
    canonicalizer = _RepairingCanonicalizer()
    router = SimplexRouter(
        guard=_guard(),
        canonicalizer=canonicalizer,
        lark_compiler=LanguageCompiler(),
    )
    result = router.compile(VALID_OPEN_LANGUAGE)
    assert result.status is CompilerStatus.SUCCESS
    assert result.route is SimplexRoute.CANONICALIZED
    assert result.llm_invocations == 1
    assert canonicalizer.calls == [VALID_OPEN_LANGUAGE]


def test_router_guard_rejects_connector_only_input_without_model() -> None:
    canonicalizer = _RepairingCanonicalizer()
    router = SimplexRouter(
        guard=_guard(),
        canonicalizer=canonicalizer,
        lark_compiler=LanguageCompiler(),
    )
    result = router.compile("然后")
    assert result.status is CompilerStatus.MALFORMED
    assert result.route is SimplexRoute.GUARD_REJECT
    assert canonicalizer.calls == []
def test_router_blocks_deterministic_silent_repair_before_lark() -> None:
    """The frozen normalizer would accept this; the guard must reject it."""

    canonicalizer = _RepairingCanonicalizer()
    guard = _guard()
    assert LanguageCompiler().compile("站立2秒，然后，停止").success
    router = SimplexRouter(
        guard=guard,
        canonicalizer=canonicalizer,
        lark_compiler=LanguageCompiler(),
    )
    result = router.compile("站立2秒，然后，停止")
    assert result.status is CompilerStatus.MALFORMED
    assert result.route is SimplexRoute.GUARD_REJECT
    assert result.guard_reason_code == "EMPTY_CLAUSE"
    assert result.llm_invocations == 0
    assert canonicalizer.calls == []


def _hardening_builder() -> object:
    import importlib.util

    path = resolve_repo_path("scripts/build_simplex_datasets.py")
    spec = importlib.util.spec_from_file_location("build_simplex_datasets", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hardening_structural_corpus_is_fully_rejected() -> None:
    builder = _hardening_builder()
    guard = _guard()
    missed = [u for u in builder.MALFORMED_STRUCTURES if guard.check(u).passed]
    assert missed == []


def test_hardening_valid_surfaces_have_no_false_positives() -> None:
    builder = _hardening_builder()
    guard = _guard()
    for spec_name, _steps in builder.DEV_VALID_SPECS:
        for utterance in builder.DEV_VALID_SURFACES[spec_name]:
            assert guard.check(utterance).passed, utterance


def test_hardening_blind_set_silent_repair_invariant() -> None:
    """Never let the frozen grammar silently accept a MALFORMED sample."""

    builder = _hardening_builder()
    guard = _guard()
    compiler = LanguageCompiler()
    silent_repairs: list[str] = []
    for sample in builder._blind_samples():
        utterance = sample["utterance"]
        status = sample.get("expected_compiler_status") or sample.get("status")
        if status == "MALFORMED":
            if compiler.compile(utterance).status is CompilerStatus.SUCCESS:
                silent_repairs.append(sample["sample_id"])
                assert guard.check(utterance).malformed, sample["sample_id"]
        else:
            assert guard.check(utterance).passed, sample["sample_id"]
    assert silent_repairs
