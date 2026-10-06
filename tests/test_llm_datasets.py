"""Tests for the frozen Phase 2.2 development / blind datasets."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

from g1swarm.llm.datasets import LLMDatasetError, load_dataset, parse_dataset
from g1swarm.paths import repo_root

REPO = repo_root()
EXPERIMENT_DIR = REPO / "experiments" / "phase2" / "llm_compiler_001"
DEV_PATH = EXPERIMENT_DIR / "development_set.yaml"
BLIND_PATH = EXPERIMENT_DIR / "blind_test_set.yaml"
MANIFEST_PATH = EXPERIMENT_DIR / "dataset_manifest.json"
PROMPT_PATH = REPO / "prompts" / "llm_mission_compiler_v1.txt"
CONTROLLED_PATH = REPO / "configs" / "language" / "controlled_language_001.yaml"
BUILDER_PATH = REPO / "scripts" / "build_llm_datasets.py"

CATEGORIES = {
    "atomic_valid",
    "paraphrase",
    "composition",
    "colloquial",
    "noisy_formatting",
    "chinese_numbers",
    "arabic_numbers",
    "mixed_units",
    "ambiguity",
    "unsupported",
    "malformed",
    "capability_unknown",
    "prompt_injection",
}


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_llm_datasets", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    normalized = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def _normalize(text: str) -> str:
    return "".join(text.split())


def _prompt_examples() -> list[str]:
    examples = []
    for line in PROMPT_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("User: "):
            examples.append(line[len("User: ") :].strip())
    return examples


def test_frozen_files_reproduce_from_hand_authored_sources() -> None:
    builder = _load_builder()
    payloads = builder.build_payloads()
    assert set(payloads) == {DEV_PATH, BLIND_PATH, MANIFEST_PATH}
    for path, expected in payloads.items():
        assert path.read_text(encoding="utf-8") == expected, f"{path} is not reproducible"


def test_split_sizes_and_category_coverage() -> None:
    development = load_dataset(DEV_PATH)
    blind = load_dataset(BLIND_PATH)
    assert 80 <= len(development.samples) <= 120
    assert 150 <= len(blind.samples) <= 250
    assert {sample.category for sample in blind.samples} == CATEGORIES
    assert {sample.expected_compiler_status for sample in blind.samples} == {
        "SUCCESS",
        "AMBIGUOUS",
        "UNSUPPORTED",
        "MALFORMED",
    }


def test_benchmark_sets_and_e2e_selection() -> None:
    development = load_dataset(DEV_PATH)
    blind = load_dataset(BLIND_PATH)
    assert {sample.benchmark_set for sample in development.samples} == {"B", "C"}
    assert {sample.benchmark_set for sample in blind.samples} == {"B", "C"}
    assert sum(sample.e2e for sample in blind.samples) == 14
    assert not any(sample.e2e for sample in development.samples)
    # 12-20 representative end-to-end samples per spec section 40.
    assert 12 <= sum(sample.e2e for sample in blind.samples) <= 20


def test_development_and_blind_utterances_are_disjoint() -> None:
    development = {sample.utterance for sample in load_dataset(DEV_PATH).samples}
    blind = {sample.utterance for sample in load_dataset(BLIND_PATH).samples}
    assert not (development & blind)


def test_blind_utterances_do_not_leak_from_the_frozen_prompt() -> None:
    examples = [_normalize(example) for example in _prompt_examples()]
    assert examples, "the frozen prompt must contain User: examples"
    for sample in load_dataset(BLIND_PATH).samples:
        utterance = _normalize(sample.utterance)
        for example in examples:
            assert utterance != example, f"{sample.sample_id} equals a prompt example"
            if len(example) >= 6:
                assert example not in utterance, f"{sample.sample_id} embeds a prompt example"
            if len(utterance) >= 12:
                assert utterance not in example, f"{sample.sample_id} is inside a prompt example"


def test_rejected_samples_never_carry_a_mission() -> None:
    for sample in load_dataset(BLIND_PATH).samples:
        if sample.expected_compiler_status == "SUCCESS":
            assert sample.expected_mission is not None
            assert sample.expected_error_code is None
        else:
            assert sample.expected_mission is None
            assert sample.expected_error_code
            assert sample.expected_runtime_status == "NOT_RUN"
            assert sample.expected_failure_type is None


def test_capability_unknown_is_compiler_success_and_runtime_rejected() -> None:
    unknown = [
        sample
        for sample in load_dataset(BLIND_PATH).samples
        if sample.category == "capability_unknown"
    ]
    assert unknown
    for sample in unknown:
        assert sample.expected_compiler_status == "SUCCESS"
        assert sample.expected_mission is not None
        assert sample.expected_runtime_status == "REJECTED"
        assert sample.expected_failure_type == "CAPABILITY_UNKNOWN"
        distances = [
            step["parameters"]["distance_m"] for step in sample.expected_mission["steps"]
        ]
        assert all(distance > 20.0 for distance in distances)
    assert any(sample.e2e for sample in unknown)


def test_manifest_hashes_match_the_frozen_artifacts() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["datasets"]["development"]["sha256"] == _sha256(DEV_PATH)
    assert manifest["datasets"]["blind"]["sha256"] == _sha256(BLIND_PATH)
    assert manifest["prompt"]["sha256"] == _sha256(PROMPT_PATH)
    assert manifest["controlled_regression"]["sha256"] == _sha256(CONTROLLED_PATH)
    assert manifest["controlled_regression"]["sample_count"] == 189
    assert manifest["frozen_before_blind_campaign"] is True


def test_strict_loader_rejects_corrupted_documents() -> None:
    document = yaml.safe_load(DEV_PATH.read_text(encoding="utf-8"))

    bad_set = json.loads(json.dumps(document))
    bad_set["samples"][0]["benchmark_set"] = "Z"
    with pytest.raises(LLMDatasetError):
        parse_dataset(bad_set)

    duplicate = json.loads(json.dumps(document))
    duplicate["samples"][1]["utterance"] = duplicate["samples"][0]["utterance"]
    with pytest.raises(LLMDatasetError):
        parse_dataset(duplicate)

    unknown_field = json.loads(json.dumps(document))
    unknown_field["samples"][0]["risk_map"] = "LOW"
    with pytest.raises(LLMDatasetError):
        parse_dataset(unknown_field)

    missing_mission = json.loads(json.dumps(document))
    success = next(
        sample
        for sample in missing_mission["samples"]
        if sample["expected_compiler_status"] == "SUCCESS"
    )
    success["expected_mission"] = None
    with pytest.raises(LLMDatasetError):
        parse_dataset(missing_mission)
