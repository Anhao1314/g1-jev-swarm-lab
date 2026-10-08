"""Strict dataset loading for the Phase 2.2 LLM compiler benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..mission.ir import MISSION_SCHEMA_VERSION, Mission
from ..mission.validator import MissionValidator
from ..language.errors import CompilerStatus, LanguageErrorCode

DATASET_SCHEMA_VERSION = "1.0.0"
DATASET_KEYS = frozenset({"schema_version", "dataset_id", "split", "samples"})
SAMPLE_KEYS = frozenset(
    {
        "sample_id",
        "benchmark_set",
        "split",
        "category",
        "source",
        "utterance",
        "expected_compiler_status",
        "expected_error_code",
        "expected_mission",
        "expected_runtime_status",
        "expected_failure_type",
        "e2e",
        "notes",
    }
)
SPLITS = {"development", "blind"}
BENCHMARK_SETS = {"A", "B", "C"}
RUNTIME_STATUSES = {"SUCCESS", "REJECTED", "NOT_RUN"}
_ERROR_CODES = {item.value for item in LanguageErrorCode}
_STATUSES = {item.value for item in CompilerStatus}


class LLMDatasetError(ValueError):
    """The development or blind dataset is malformed."""


@dataclass(frozen=True)
class LLMSample:
    sample_id: str
    benchmark_set: str
    split: str
    category: str
    source: str
    utterance: str
    expected_compiler_status: str
    expected_error_code: str | None
    expected_mission: dict[str, Any] | None
    expected_runtime_status: str
    expected_failure_type: str | None
    e2e: bool
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "benchmark_set": self.benchmark_set,
            "split": self.split,
            "category": self.category,
            "source": self.source,
            "utterance": self.utterance,
            "expected_compiler_status": self.expected_compiler_status,
            "expected_error_code": self.expected_error_code,
            "expected_mission": self.expected_mission,
            "expected_runtime_status": self.expected_runtime_status,
            "expected_failure_type": self.expected_failure_type,
            "e2e": self.e2e,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class LLMDataset:
    dataset_id: str
    split: str
    samples: tuple[LLMSample, ...]
    path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DATASET_SCHEMA_VERSION,
            "dataset_id": self.dataset_id,
            "split": self.split,
            "samples": [sample.to_dict() for sample in self.samples],
        }


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LLMDatasetError(f"{field_name} must be a mapping")
    return value


def _string(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise LLMDatasetError(f"{field_name} must be a non-empty string")
    return value


def _expected_mission(raw: Any, sample_id: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    document = dict(_mapping(raw, "expected_mission"))
    document.setdefault("mission_id", f"oracle-{sample_id}")
    if document.get("schema_version") is None:
        document["schema_version"] = MISSION_SCHEMA_VERSION
    try:
        mission = Mission.from_dict(document)
    except Exception as exc:  # noqa: BLE001 - corpus boundary
        raise LLMDatasetError(f"{sample_id}: expected_mission is not valid Mission IR: {exc}") from exc
    report = MissionValidator().validate(mission)
    if not report.valid:
        messages = "; ".join(issue.message for issue in report.issues)
        raise LLMDatasetError(f"{sample_id}: expected_mission is invalid: {messages}")
    return mission.to_dict()


def _parse_sample(raw: Any, index: int) -> LLMSample:
    sample = _mapping(raw, f"samples[{index}]")
    unknown = set(sample) - SAMPLE_KEYS
    if unknown:
        raise LLMDatasetError(f"samples[{index}] has unknown fields: {', '.join(sorted(unknown))}")
    missing = (SAMPLE_KEYS - {"source"}) - set(sample)
    if missing:
        raise LLMDatasetError(f"samples[{index}] is missing fields: {', '.join(sorted(missing))}")
    sample_id = _string(sample["sample_id"], f"samples[{index}].sample_id")
    split = _string(sample["split"], f"samples[{index}].split")
    if split not in SPLITS:
        raise LLMDatasetError(f"{sample_id}: unknown split {split!r}")
    category = _string(sample["category"], f"samples[{index}].category")
    benchmark_set = _string(sample["benchmark_set"], f"samples[{index}].benchmark_set")
    if benchmark_set not in BENCHMARK_SETS:
        raise LLMDatasetError(f"{sample_id}: unknown benchmark set {benchmark_set!r}")
    source = _string(sample.get("source", ""), f"samples[{index}].source", allow_empty=True)
    utterance = _string(sample["utterance"], f"samples[{index}].utterance")
    status = _string(sample["expected_compiler_status"], f"samples[{index}].expected_compiler_status")
    if status not in _STATUSES:
        raise LLMDatasetError(f"{sample_id}: unknown compiler status {status!r}")
    error_raw = sample["expected_error_code"]
    error_code = None
    if error_raw is not None:
        error_code = _string(error_raw, f"samples[{index}].expected_error_code")
        if error_code not in _ERROR_CODES:
            raise LLMDatasetError(f"{sample_id}: unknown error code {error_code!r}")
    expected_mission = _expected_mission(sample["expected_mission"], sample_id)
    if status == CompilerStatus.SUCCESS.value:
        if expected_mission is None or error_code is not None:
            raise LLMDatasetError(f"{sample_id}: SUCCESS requires a mission and no error code")
    elif expected_mission is not None or error_code is None:
        raise LLMDatasetError(f"{sample_id}: non-SUCCESS requires null mission and an error code")
    runtime_status = _string(sample["expected_runtime_status"], f"samples[{index}].expected_runtime_status")
    if runtime_status not in RUNTIME_STATUSES:
        raise LLMDatasetError(f"{sample_id}: unknown runtime status {runtime_status!r}")
    failure_type = sample["expected_failure_type"]
    if failure_type is not None:
        failure_type = _string(failure_type, f"samples[{index}].expected_failure_type")
    if status != CompilerStatus.SUCCESS.value and runtime_status != "NOT_RUN":
        raise LLMDatasetError(f"{sample_id}: language rejection must use runtime NOT_RUN")
    if runtime_status == "REJECTED" and failure_type is None:
        raise LLMDatasetError(f"{sample_id}: runtime rejection needs an expected failure type")
    e2e = sample["e2e"]
    if not isinstance(e2e, bool):
        raise LLMDatasetError(f"{sample_id}: e2e must be boolean")
    notes = _string(sample["notes"], f"samples[{index}].notes", allow_empty=True)
    return LLMSample(
        sample_id=sample_id,
        benchmark_set=benchmark_set,
        split=split,
        category=category,
        source=source,
        utterance=utterance,
        expected_compiler_status=status,
        expected_error_code=error_code,
        expected_mission=expected_mission,
        expected_runtime_status=runtime_status,
        expected_failure_type=failure_type,
        e2e=e2e,
        notes=notes,
    )


def parse_dataset(document: Mapping[str, Any], *, path: Path | None = None) -> LLMDataset:
    raw = _mapping(document, "dataset")
    unknown = set(raw) - DATASET_KEYS
    if unknown:
        raise LLMDatasetError(f"dataset has unknown fields: {', '.join(sorted(unknown))}")
    missing = DATASET_KEYS - set(raw)
    if missing:
        raise LLMDatasetError(f"dataset is missing fields: {', '.join(sorted(missing))}")
    if raw["schema_version"] != DATASET_SCHEMA_VERSION:
        raise LLMDatasetError(f"dataset schema_version must be {DATASET_SCHEMA_VERSION!r}")
    split = _string(raw["split"], "split")
    if split not in SPLITS:
        raise LLMDatasetError(f"unknown dataset split {split!r}")
    samples_raw = raw["samples"]
    if not isinstance(samples_raw, list) or not samples_raw:
        raise LLMDatasetError("samples must be a non-empty list")
    samples = tuple(_parse_sample(item, index) for index, item in enumerate(samples_raw))
    seen: set[str] = set()
    utterances: dict[str, str] = {}
    for sample in samples:
        if sample.sample_id in seen:
            raise LLMDatasetError(f"duplicate sample_id {sample.sample_id!r}")
        seen.add(sample.sample_id)
        if sample.split != split:
            raise LLMDatasetError(f"{sample.sample_id}: sample split does not match dataset split")
        if sample.utterance in utterances:
            raise LLMDatasetError(
                f"duplicate utterance {sample.utterance!r} in "
                f"{utterances[sample.utterance]!r} and {sample.sample_id!r}"
            )
        utterances[sample.utterance] = sample.sample_id
    return LLMDataset(dataset_id=_string(raw["dataset_id"], "dataset_id"), split=split, samples=samples, path=path)


def load_dataset(path: str | Path) -> LLMDataset:
    dataset_path = Path(path)
    document = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise LLMDatasetError("dataset document must be a YAML mapping")
    return parse_dataset(document, path=dataset_path)
