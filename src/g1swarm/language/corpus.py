"""Controlled-language corpus schema, loader and validator (Phase 2.1).

The corpus is the frozen evaluation set for the deterministic compiler. Each
sample pairs a controlled-Chinese utterance with the canonical Mission IR 2.0
that the compiler must produce (or with the language-level rejection code that
it must raise). The corpus never encodes execution modes, risk labels or
capability decisions: those stay in the frozen Phase 2.0 grounding layer.

Loading is strict and fail-closed: unknown keys, duplicate ids, duplicate
utterances, inconsistent status/mission combinations and schema-invalid
expected missions are all reported as corpus errors instead of being ignored.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..mission.ir import Mission, MissionIRError
from ..mission.validator import MissionValidator
from .errors import CompilerStatus, LanguageErrorCode

CORPUS_SCHEMA_VERSION = "1.0.0"
MAX_LANGUAGE_INPUT_CHARS = 512
MAX_CORPUS_UTTERANCE_CHARS = 4096

CATEGORIES = (
    "atomic_valid",
    "paraphrase",
    "unit_variant",
    "sequence_variant",
    "composition",
    "ambiguous",
    "unsupported",
    "malformed",
    "capability_unknown",
    "runtime_rejected",
)
SOURCES = ("generated", "hand_authored", "composition")
RUNTIME_STATUSES = ("SUCCESS", "REJECTED", "NOT_RUN")

TOP_LEVEL_KEYS = frozenset(
    {
        "corpus_id",
        "corpus_schema_version",
        "corpus_version",
        "seed",
        "generator_version",
        "compiler_interface",
        "runtime_rejected_note",
        "source_hashes",
        "counts",
        "samples",
    }
)
SAMPLE_KEYS = frozenset(
    {
        "sample_id",
        "group_id",
        "category",
        "source",
        "utterance",
        "expected_compiler_status",
        "expected_error_code",
        "expected_mission",
        "expected_runtime_status",
        "expected_failure_type",
        "expected_simulation_steps",
        "e2e",
        "horizon",
        "oracle_mission_id",
        "notes",
    }
)
SAMPLE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

_COMPILER_STATUS_VALUES = frozenset(status.value for status in CompilerStatus)
_ERROR_CODE_VALUES = frozenset(code.value for code in LanguageErrorCode)


class CorpusError(ValueError):
    """The corpus document is structurally invalid or inconsistent."""


@dataclass(frozen=True)
class CorpusSample:
    sample_id: str
    group_id: str
    category: str
    source: str
    utterance: str
    expected_compiler_status: str
    expected_error_code: str | None
    expected_mission: dict[str, Any] | None
    expected_runtime_status: str
    expected_failure_type: str | None
    expected_simulation_steps: int | None
    e2e: bool
    horizon: int | None
    oracle_mission_id: str | None
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "group_id": self.group_id,
            "category": self.category,
            "source": self.source,
            "utterance": self.utterance,
            "expected_compiler_status": self.expected_compiler_status,
            "expected_error_code": self.expected_error_code,
            "expected_mission": (
                dict(self.expected_mission) if self.expected_mission is not None else None
            ),
            "expected_runtime_status": self.expected_runtime_status,
            "expected_failure_type": self.expected_failure_type,
            "expected_simulation_steps": self.expected_simulation_steps,
            "e2e": self.e2e,
            "horizon": self.horizon,
            "oracle_mission_id": self.oracle_mission_id,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class LanguageCorpus:
    corpus_id: str
    corpus_schema_version: str
    corpus_version: str
    seed: int
    generator_version: str
    compiler_interface: str
    runtime_rejected_note: str
    source_hashes: dict[str, str]
    counts: dict[str, int]
    samples: tuple[CorpusSample, ...]
    path: Path | None = None

    def __len__(self) -> int:
        return len(self.samples)

    def by_category(self, category: str) -> tuple[CorpusSample, ...]:
        return tuple(sample for sample in self.samples if sample.category == category)

    def by_source(self, source: str) -> tuple[CorpusSample, ...]:
        return tuple(sample for sample in self.samples if sample.source == source)

    def e2e_samples(self) -> tuple[CorpusSample, ...]:
        return tuple(sample for sample in self.samples if sample.e2e)

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_id": self.corpus_id,
            "corpus_schema_version": self.corpus_schema_version,
            "corpus_version": self.corpus_version,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "compiler_interface": self.compiler_interface,
            "runtime_rejected_note": self.runtime_rejected_note,
            "source_hashes": dict(self.source_hashes),
            "counts": dict(self.counts),
            "samples": [sample.to_dict() for sample in self.samples],
        }


@dataclass(frozen=True)
class CorpusValidationReport:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": list(self.errors), "warnings": list(self.warnings)}


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CorpusError(f"{field_name} must be a mapping")
    return value


def _require_str(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise CorpusError(f"{field_name} must be a non-empty string")
    return value


def _clean_document(document: Mapping[str, Any]) -> Mission | None:
    """Return the parsed expected mission, letting the IR layer reject shape bugs."""

    return Mission.from_dict(document)


def _parse_sample(raw: Any, index: int) -> CorpusSample:
    prefix = f"samples[{index}]"
    sample = _require_mapping(raw, prefix)
    unknown = set(sample) - SAMPLE_KEYS
    if unknown:
        raise CorpusError(f"{prefix} has unknown fields: {', '.join(sorted(unknown))}")
    missing = SAMPLE_KEYS - set(sample)
    if missing:
        raise CorpusError(f"{prefix} is missing fields: {', '.join(sorted(missing))}")

    sample_id = _require_str(sample["sample_id"], f"{prefix}.sample_id")
    if not SAMPLE_ID_PATTERN.match(sample_id):
        raise CorpusError(f"{prefix}.sample_id {sample_id!r} is not corpus-id safe")
    group_id = _require_str(sample["group_id"], f"{prefix}.group_id")
    category = _require_str(sample["category"], f"{prefix}.category")
    if category not in CATEGORIES:
        raise CorpusError(f"{prefix}.category {category!r} is not a known category")
    source = _require_str(sample["source"], f"{prefix}.source")
    if source not in SOURCES:
        raise CorpusError(f"{prefix}.source {source!r} is not a known source")
    utterance = _require_str(sample["utterance"], f"{prefix}.utterance")
    if len(utterance) > MAX_CORPUS_UTTERANCE_CHARS:
        raise CorpusError(
            f"{prefix}.utterance exceeds the corpus safety bound of "
            f"{MAX_CORPUS_UTTERANCE_CHARS} characters"
        )

    compiler_status = _require_str(
        sample["expected_compiler_status"], f"{prefix}.expected_compiler_status"
    )
    if compiler_status not in _COMPILER_STATUS_VALUES:
        raise CorpusError(
            f"{prefix}.expected_compiler_status {compiler_status!r} is not a compiler status"
        )
    error_code_raw = sample["expected_error_code"]
    if error_code_raw is not None:
        error_code_raw = _require_str(error_code_raw, f"{prefix}.expected_error_code")
        if error_code_raw not in _ERROR_CODE_VALUES:
            raise CorpusError(f"{prefix}.expected_error_code {error_code_raw!r} is unknown")
    expected_mission_raw = sample["expected_mission"]
    if expected_mission_raw is not None:
        expected_mission_raw = dict(_require_mapping(expected_mission_raw, f"{prefix}.expected_mission"))

    if compiler_status == CompilerStatus.SUCCESS.value:
        if expected_mission_raw is None:
            raise CorpusError(f"{prefix} expects SUCCESS but has no expected_mission")
        if error_code_raw is not None:
            raise CorpusError(f"{prefix} expects SUCCESS but declares an error code")
        try:
            mission = _clean_document(expected_mission_raw)
        except MissionIRError as exc:
            raise CorpusError(
                f"{prefix}.expected_mission is not Mission-IR parseable: {exc}"
            ) from exc
        report = MissionValidator().validate(mission)
        if not report.valid:
            messages = "; ".join(issue.message for issue in report.issues)
            raise CorpusError(f"{prefix}.expected_mission is not Mission-IR valid: {messages}")
    else:
        if expected_mission_raw is not None:
            raise CorpusError(
                f"{prefix} expects {compiler_status} but declares an expected_mission"
            )
        if error_code_raw is None:
            raise CorpusError(f"{prefix} expects {compiler_status} but has no error code")

    runtime_status = _require_str(
        sample["expected_runtime_status"], f"{prefix}.expected_runtime_status"
    )
    if runtime_status not in RUNTIME_STATUSES:
        raise CorpusError(f"{prefix}.expected_runtime_status {runtime_status!r} is unknown")
    failure_type_raw = sample["expected_failure_type"]
    if failure_type_raw is not None:
        failure_type_raw = _require_str(failure_type_raw, f"{prefix}.expected_failure_type")
    sim_steps_raw = sample["expected_simulation_steps"]
    if sim_steps_raw is not None:
        if isinstance(sim_steps_raw, bool) or not isinstance(sim_steps_raw, int) or sim_steps_raw < 0:
            raise CorpusError(f"{prefix}.expected_simulation_steps must be null or a non-negative int")

    if compiler_status != CompilerStatus.SUCCESS.value and runtime_status != "NOT_RUN":
        raise CorpusError(
            f"{prefix} is rejected by the language layer and must not claim a runtime status"
        )
    if runtime_status == "SUCCESS":
        if compiler_status != CompilerStatus.SUCCESS.value:
            raise CorpusError(f"{prefix} cannot be runtime SUCCESS without compiler SUCCESS")
        if failure_type_raw is not None:
            raise CorpusError(f"{prefix} is runtime SUCCESS but declares a failure type")
    if runtime_status == "REJECTED":
        if compiler_status != CompilerStatus.SUCCESS.value:
            raise CorpusError(f"{prefix} cannot be runtime REJECTED without compiler SUCCESS")
        if failure_type_raw is None:
            raise CorpusError(f"{prefix} is runtime REJECTED but has no failure type")
        if sim_steps_raw != 0:
            raise CorpusError(
                f"{prefix} is runtime REJECTED and must declare 0 simulation steps"
            )
    if category in {"capability_unknown", "runtime_rejected"} and runtime_status != "REJECTED":
        raise CorpusError(
            f"{prefix} category {category!r} must expect a runtime rejection"
        )

    e2e = sample["e2e"]
    if not isinstance(e2e, bool):
        raise CorpusError(f"{prefix}.e2e must be a boolean")
    horizon_raw = sample["horizon"]
    if horizon_raw is not None:
        if isinstance(horizon_raw, bool) or not isinstance(horizon_raw, int) or horizon_raw < 1:
            raise CorpusError(f"{prefix}.horizon must be null or a positive int")
    oracle_raw = sample["oracle_mission_id"]
    if oracle_raw is not None:
        oracle_raw = _require_str(oracle_raw, f"{prefix}.oracle_mission_id")
    notes = _require_str(sample["notes"], f"{prefix}.notes", allow_empty=True)

    return CorpusSample(
        sample_id=sample_id,
        group_id=group_id,
        category=category,
        source=source,
        utterance=utterance,
        expected_compiler_status=compiler_status,
        expected_error_code=error_code_raw,
        expected_mission=expected_mission_raw,
        expected_runtime_status=runtime_status,
        expected_failure_type=failure_type_raw,
        expected_simulation_steps=sim_steps_raw,
        e2e=e2e,
        horizon=horizon_raw,
        oracle_mission_id=oracle_raw,
        notes=notes,
    )


def parse_corpus(document: Mapping[str, Any], *, path: Path | None = None) -> LanguageCorpus:
    raw = _require_mapping(document, "corpus")
    unknown = set(raw) - TOP_LEVEL_KEYS
    if unknown:
        raise CorpusError(f"corpus has unknown fields: {', '.join(sorted(unknown))}")
    missing = TOP_LEVEL_KEYS - set(raw)
    if missing:
        raise CorpusError(f"corpus is missing fields: {', '.join(sorted(missing))}")

    samples_raw = raw["samples"]
    if not isinstance(samples_raw, list) or not samples_raw:
        raise CorpusError("corpus samples must be a non-empty list")
    samples = tuple(_parse_sample(item, index) for index, item in enumerate(samples_raw))

    source_hashes_raw = _require_mapping(raw["source_hashes"], "source_hashes")
    source_hashes = {
        _require_str(key, "source_hashes key"): _require_str(value, f"source_hashes.{key}")
        for key, value in source_hashes_raw.items()
    }
    counts_raw = _require_mapping(raw["counts"], "counts")
    counts = {}
    for key, value in counts_raw.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CorpusError(f"counts.{key} must be a non-negative int")
        counts[str(key)] = value

    seed = raw["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise CorpusError("seed must be an integer")
    runtime_note = _require_str(raw["runtime_rejected_note"], "runtime_rejected_note", allow_empty=True)

    corpus = LanguageCorpus(
        corpus_id=_require_str(raw["corpus_id"], "corpus_id"),
        corpus_schema_version=_require_str(raw["corpus_schema_version"], "corpus_schema_version"),
        corpus_version=_require_str(raw["corpus_version"], "corpus_version"),
        seed=seed,
        generator_version=_require_str(raw["generator_version"], "generator_version"),
        compiler_interface=_require_str(raw["compiler_interface"], "compiler_interface"),
        runtime_rejected_note=runtime_note,
        source_hashes=source_hashes,
        counts=counts,
        samples=samples,
        path=path,
    )
    report = validate_corpus(corpus)
    if not report.valid:
        raise CorpusError("; ".join(report.errors))
    return corpus


def load_corpus(path: str | Path) -> LanguageCorpus:
    corpus_path = Path(path)
    document = yaml.safe_load(corpus_path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise CorpusError("corpus document must be a YAML mapping")
    return parse_corpus(document, path=corpus_path)


def validate_corpus(corpus: LanguageCorpus) -> CorpusValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    seen_utterances: dict[str, str] = {}
    for sample in corpus.samples:
        if sample.sample_id in seen_ids:
            errors.append(f"duplicate sample_id {sample.sample_id!r}")
        seen_ids.add(sample.sample_id)
        if sample.utterance in seen_utterances:
            errors.append(
                f"duplicate utterance {sample.utterance!r} in "
                f"{seen_utterances[sample.utterance]!r} and {sample.sample_id!r}"
            )
        seen_utterances[sample.utterance] = sample.sample_id
        if sample.expected_mission is not None:
            try:
                mission = Mission.from_dict(sample.expected_mission)
            except Exception as exc:  # noqa: BLE001 - report, never propagate YAML shape bugs
                errors.append(f"{sample.sample_id}: expected_mission is unparseable: {exc}")
                continue
            report = MissionValidator().validate(mission)
            if not report.valid:
                messages = "; ".join(issue.message for issue in report.issues)
                errors.append(f"{sample.sample_id}: expected_mission invalid: {messages}")
    categories = {sample.category for sample in corpus.samples}
    unknown_categories = categories - set(CATEGORIES)
    if unknown_categories:
        errors.append(f"unknown categories: {', '.join(sorted(unknown_categories))}")
    for category in ("atomic_valid", "paraphrase", "composition", "ambiguous", "unsupported", "malformed"):
        if category not in categories:
            warnings.append(f"corpus has no samples in required category {category!r}")
    if not corpus.e2e_samples():
        warnings.append("corpus has no end-to-end representative samples")
    return CorpusValidationReport(errors=tuple(errors), warnings=tuple(warnings))


def corpus_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
