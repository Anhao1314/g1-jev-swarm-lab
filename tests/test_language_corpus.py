"""Frozen controlled-language corpus and compiler-benchmark tests (Phase 2.1).

These tests pin the frozen corpus artefact, its deterministic generator, and the
measured compiler behaviour on the corpus. They are the regression guard for
the Phase 2.1 hard-safety metrics: any compiler change that lets ambiguous,
unsupported or malformed language reach a Mission IR fails here.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from g1swarm.language.benchmark import (
    canonical_mission_hash,
    canonical_mission_payload,
    evaluate_compiler_sample,
    summarize_compiler_results,
)
from g1swarm.language.compiler import DEFAULT_MAX_INPUT_CHARS, LanguageCompiler
from g1swarm.language.corpus import (
    CATEGORIES,
    CorpusError,
    corpus_sha256,
    load_corpus,
    parse_corpus,
)
from g1swarm.language.corpus_generator import (
    DEFAULT_SEED,
    MAX_GENERATED_SAMPLES,
    generate_samples,
)
from g1swarm.paths import resolve_repo_path

CORPUS_PATH = "configs/language/controlled_language_001.yaml"
SOURCE_PATH = "configs/language/sources/hand_authored_001.yaml"
GENERATED_COUNT = 38
EXPECTED_TOTAL = 189


def _corpus():
    return load_corpus(resolve_repo_path(CORPUS_PATH))


def _document() -> dict:
    return yaml.safe_load(resolve_repo_path(CORPUS_PATH).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# frozen artefact
# ---------------------------------------------------------------------------
def test_frozen_corpus_loads_with_expected_distribution() -> None:
    corpus = _corpus()
    assert len(corpus) == EXPECTED_TOTAL
    expected_counts = {
        "atomic_valid": 38,
        "paraphrase": 40,
        "unit_variant": 24,
        "sequence_variant": 18,
        "composition": 11,
        "ambiguous": 18,
        "unsupported": 16,
        "malformed": 18,
        "capability_unknown": 6,
        "runtime_rejected": 0,
        "total": EXPECTED_TOTAL,
        "end_to_end": 11,
    }
    for key, value in expected_counts.items():
        assert corpus.counts[key] == value, key
    assert corpus.counts["total"] == len(corpus.samples)
    assert set(corpus.counts) - {"total", "end_to_end"} <= set(CATEGORIES)


def test_corpus_sources_are_disjoint_and_counted() -> None:
    corpus = _corpus()
    assert len(corpus.by_source("generated")) == GENERATED_COUNT
    assert len(corpus.by_source("hand_authored")) == EXPECTED_TOTAL - GENERATED_COUNT - 11
    assert len(corpus.by_source("composition")) == 11
    assert {sample.sample_id for sample in corpus.samples} == {
        sample.sample_id for sample in corpus.samples
    }


def test_sample_ids_and_utterances_are_unique() -> None:
    corpus = _corpus()
    ids = [sample.sample_id for sample in corpus.samples]
    utterances = [sample.utterance for sample in corpus.samples]
    assert len(ids) == len(set(ids))
    assert len(utterances) == len(set(utterances))


def test_expected_missions_are_schema_valid_and_status_consistent() -> None:
    corpus = _corpus()
    for sample in corpus.samples:
        if sample.expected_compiler_status == "SUCCESS":
            assert sample.expected_mission is not None
            assert sample.expected_error_code is None
        else:
            assert sample.expected_mission is None
            assert sample.expected_error_code is not None
            assert sample.expected_runtime_status == "NOT_RUN"
        if sample.category in {"capability_unknown", "runtime_rejected"}:
            assert sample.expected_runtime_status == "REJECTED"
            assert sample.expected_failure_type == "CAPABILITY_UNKNOWN"
            assert sample.expected_simulation_steps == 0


def test_paraphrase_groups_share_one_canonical_mission() -> None:
    corpus = _corpus()
    groups: dict[str, list] = {}
    for sample in corpus.samples:
        if sample.expected_compiler_status == "SUCCESS":
            groups.setdefault(sample.group_id, []).append(sample)
    multi = {group: items for group, items in groups.items() if len(items) > 1}
    assert len(multi) == 8
    for items in multi.values():
        payloads = {json.dumps(canonical_mission_payload(item.expected_mission), sort_keys=True) for item in items}
        assert len(payloads) == 1


def test_end_to_end_subset_covers_horizons_units_and_signs() -> None:
    corpus = _corpus()
    e2e = corpus.e2e_samples()
    assert 10 <= len(e2e) <= 15
    assert {sample.horizon for sample in e2e} >= {1, 4, 5, 8}
    assert any(sample.expected_mission["steps"][0]["parameters"].get("angle_deg", 0) > 0 for sample in e2e)
    assert any(sample.expected_mission["steps"][0]["parameters"].get("angle_deg", 0) < 0 for sample in e2e)
    assert any(sample.expected_mission["steps"][0]["parameters"].get("distance_m") == 4.0 for sample in e2e)
    assert any(
        sample.expected_runtime_status == "REJECTED" for sample in e2e
    ), "the capability-unknown zero-step case must be in the end-to-end set"


def test_input_length_fuzz_sample_exceeds_compiler_bound() -> None:
    corpus = _corpus()
    sample = next(item for item in corpus.samples if item.expected_error_code == "INPUT_TOO_LONG")
    assert len(sample.utterance) > DEFAULT_MAX_INPUT_CHARS
    assert sample.expected_compiler_status == "MALFORMED"


def test_corpus_hash_is_stable_nonempty() -> None:
    digest = corpus_sha256(resolve_repo_path(CORPUS_PATH))
    assert len(digest) == 64 and digest == corpus_sha256(resolve_repo_path(CORPUS_PATH))


# ---------------------------------------------------------------------------
# generator reproducibility
# ---------------------------------------------------------------------------
def test_generator_is_deterministic_and_bounded() -> None:
    avoid = ["前进4米", "向右转45度"]
    first = generate_samples(seed=DEFAULT_SEED, count=GENERATED_COUNT, avoid_utterances=avoid)
    second = generate_samples(seed=DEFAULT_SEED, count=GENERATED_COUNT, avoid_utterances=avoid)
    assert [sample.to_dict() for sample in first] == [sample.to_dict() for sample in second]
    assert len({sample.utterance for sample in first}) == GENERATED_COUNT
    assert not ({sample.utterance for sample in first} & set(avoid))
    with pytest.raises(ValueError):
        generate_samples(seed=DEFAULT_SEED, count=MAX_GENERATED_SAMPLES + 1)


def test_frozen_generated_subset_reproduces_from_generator() -> None:
    spec = importlib.util.spec_from_file_location(
        "phase21_build_language_corpus", resolve_repo_path("scripts/build_language_corpus.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rebuilt = module.build_corpus(
        source_path=resolve_repo_path(SOURCE_PATH),
        output_path=resolve_repo_path(CORPUS_PATH),
        seed=DEFAULT_SEED,
        generated_count=GENERATED_COUNT,
    )
    frozen = _corpus()
    assert rebuilt.to_dict() == frozen.to_dict()


def test_generated_samples_are_inside_the_frozen_evidence_envelope() -> None:
    corpus = _corpus()
    for sample in corpus.by_source("generated"):
        assert sample.expected_compiler_status == "SUCCESS"
        assert sample.expected_runtime_status == "SUCCESS"
        for step in sample.expected_mission["steps"]:
            parameters = step["parameters"]
            if step["skill"] == "walk_forward":
                assert parameters["distance_m"] in {4.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0}
            elif step["skill"] == "turn":
                assert abs(parameters["angle_deg"]) <= 90.0
            elif step["skill"] == "stand":
                assert 0.0 < parameters["duration_s"] <= 20.0


# ---------------------------------------------------------------------------
# loader strictness
# ---------------------------------------------------------------------------
def test_loader_rejects_duplicate_utterance() -> None:
    document = _document()
    document["samples"][1]["utterance"] = document["samples"][0]["utterance"]
    with pytest.raises(CorpusError):
        parse_corpus(document)


def test_loader_rejects_nonzero_steps_on_runtime_rejection() -> None:
    document = _document()
    target = next(item for item in document["samples"] if item["category"] == "capability_unknown")
    target["expected_simulation_steps"] = 1
    with pytest.raises(CorpusError):
        parse_corpus(document)


def test_loader_rejects_success_without_mission() -> None:
    document = _document()
    target = next(item for item in document["samples"] if item["expected_compiler_status"] == "SUCCESS")
    target["expected_mission"] = None
    with pytest.raises(CorpusError):
        parse_corpus(document)


def test_loader_rejects_unknown_sample_fields() -> None:
    document = _document()
    document["samples"][0]["unexpected_field"] = 1
    with pytest.raises(CorpusError):
        parse_corpus(document)


def test_loader_rejects_malformed_expected_mission() -> None:
    document = _document()
    target = next(item for item in document["samples"] if item["sample_id"] == "cl-a-009")
    target["expected_mission"]["steps"][0]["parameters"] = {"distance_m": -4.0}
    with pytest.raises(CorpusError):
        parse_corpus(document)


def test_loader_does_not_mutate_input_document() -> None:
    document = _document()
    snapshot = copy.deepcopy(document)
    parse_corpus(document)
    assert document == snapshot


# ---------------------------------------------------------------------------
# measured benchmark
# ---------------------------------------------------------------------------
def test_compiler_benchmark_meets_hard_safety_invariants() -> None:
    corpus = _corpus()
    results = [evaluate_compiler_sample(sample.to_dict(), LanguageCompiler()) for sample in corpus.samples]
    summary = summarize_compiler_results(results)
    assert summary["total_samples"] == EXPECTED_TOTAL
    assert summary["valid_sample_exact_ir_match"] == 1.0
    assert summary["schema_valid_rate"] == 1.0
    assert summary["paraphrase_consistency_rate"] == 1.0
    assert summary["atomic_accuracy"] == 1.0
    assert summary["composition_accuracy"] == 1.0
    assert summary["number_normalization_accuracy"] == 1.0
    assert summary["unit_normalization_accuracy"] == 1.0
    assert summary["ambiguity_detection_recall"] == 1.0
    assert summary["ambiguity_false_positive_rate"] == 0.0
    assert summary["unsupported_detection_recall"] == 1.0
    assert summary["malformed_rejection_rate"] == 1.0
    assert summary["false_rejection_rate"] == 0.0
    assert summary["hallucinated_skill_count"] == 0
    assert summary["invalid_language_reaching_robot"] == 0
    assert summary["ambiguous_language_reaching_robot"] == 0
    assert summary["unsupported_language_reaching_robot"] == 0
    by_source = summary["by_source"]
    assert set(by_source) == {"generated", "hand_authored", "composition"}
    assert by_source["generated"]["samples"] == GENERATED_COUNT
    assert by_source["hand_authored"]["samples"] == EXPECTED_TOTAL - GENERATED_COUNT - 11
    assert by_source["composition"]["samples"] == 11
    for metrics in by_source.values():
        assert metrics["status_match_rate"] == 1.0
        assert metrics["hallucinated_skill_count"] == 0
        assert metrics["ambiguous_language_reaching_robot"] == 0
        assert metrics["unsupported_language_reaching_robot"] == 0


def test_every_sample_status_and_error_code_match() -> None:
    corpus = _corpus()
    results = [evaluate_compiler_sample(sample.to_dict(), LanguageCompiler()) for sample in corpus.samples]
    mismatches = [
        result
        for result in results
        if not (
            result["status_match"]
            and result["error_code_match"]
            and (result["exact_ir_match"] or result["expected_status"] != "SUCCESS")
        )
    ]
    assert mismatches == []


def test_compiler_is_deterministic_on_repeated_and_fresh_instances() -> None:
    corpus = _corpus()
    samples = corpus.samples[::7]
    shared = LanguageCompiler()
    for sample in samples:
        first = shared.compile(sample.utterance)
        second = shared.compile(sample.utterance)
        third = LanguageCompiler().compile(sample.utterance)
        assert first.status == second.status == third.status
        assert first.error_code == second.error_code == third.error_code
        hashes = [canonical_mission_hash(result.mission) if result.mission else None for result in (first, second, third)]
        assert hashes[0] == hashes[1] == hashes[2]


def test_language_rejections_never_produce_a_mission() -> None:
    corpus = _corpus()
    compiler = LanguageCompiler()
    for sample in corpus.samples:
        if sample.expected_compiler_status == "SUCCESS":
            continue
        result = compiler.compile(sample.utterance)
        assert result.mission is None
        assert result.error_code is not None
        assert result.error_code.value == sample.expected_error_code


def test_capability_unknown_samples_compile_within_schema() -> None:
    corpus = _corpus()
    compiler = LanguageCompiler()
    for sample in corpus.by_category("capability_unknown"):
        result = compiler.compile(sample.utterance)
        assert result.status.value == "SUCCESS"
        assert result.mission is not None
        assert canonical_mission_payload(result.mission) == canonical_mission_payload(
            sample.expected_mission
        )
        # The compiler must not reject on capability; the grounder does that.
        assert sample.expected_runtime_status == "REJECTED"
        assert sample.expected_simulation_steps == 0


def test_no_sample_utterance_exceeds_corpus_safety_bound() -> None:
    corpus = _corpus()
    assert max(len(sample.utterance) for sample in corpus.samples) < 4096
    assert Path(resolve_repo_path(CORPUS_PATH)).is_file()
