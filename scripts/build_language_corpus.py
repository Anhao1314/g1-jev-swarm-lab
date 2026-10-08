"""Build the frozen Phase 2.1 controlled-language corpus.

The corpus combines three disjoint sources, as required by the Phase 2.1
protocol:

* ``hand_authored`` - paraphrases, ambiguity/unsupported/malformed cases and
  capability-unknown probes authored in ``configs/language/sources``;
* ``generated`` - deterministic template generation from
  :mod:`g1swarm.language.corpus_generator` (same grammar vocabulary, bounded
  sample count, no duplicate utterances, expected IR built structurally);
* ``composition`` - hand-authored compositions of known primitives.

Usage::

    python scripts/build_language_corpus.py
    python scripts/build_language_corpus.py --check

``--check`` rebuilds in memory and fails if the frozen YAML differs from the
sources, so the committed corpus stays reproducible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from g1swarm.language.corpus import (  # noqa: E402
    CORPUS_SCHEMA_VERSION,
    LanguageCorpus,
    parse_corpus,
)
from g1swarm.language.corpus_generator import (  # noqa: E402
    DEFAULT_SEED,
    GENERATOR_VERSION,
    generate_samples,
)

DEFAULT_SOURCE = "configs/language/sources/hand_authored_001.yaml"
DEFAULT_OUTPUT = "configs/language/controlled_language_001.yaml"
DEFAULT_GENERATED_COUNT = 38
CATEGORY_ORDER = (
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expand_template(
    sample_id: str, template: Mapping[str, Any]
) -> dict[str, Any]:
    raw_steps = template.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("template steps must be a non-empty list")
    steps = []
    for index, raw in enumerate(raw_steps, start=1):
        step = dict(raw)
        skill = str(step["skill"])
        parameters = {str(key): float(value) for key, value in dict(step.get("parameters", {})).items()}
        document: dict[str, Any] = {"id": f"s{index}", "skill": skill, "parameters": parameters}
        if index > 1:
            document["depends_on"] = [f"s{index - 1}"]
        steps.append(document)
    return {
        "schema_version": "2.0.0",
        "mission_id": f"oracle-{sample_id}",
        "steps": steps,
    }


def _load_source(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ValueError("hand-authored source must be a YAML mapping")
    templates = document.get("templates", {})
    entries = document.get("entries")
    if not isinstance(templates, Mapping):
        raise ValueError("templates must be a mapping")
    if not isinstance(entries, list) or not entries:
        raise ValueError("entries must be a non-empty list")
    return dict(templates), [dict(entry) for entry in entries]


def _build_sample(entry: Mapping[str, Any], templates: Mapping[str, Any]) -> dict[str, Any]:
    template_name = entry.get("template")
    expected_mission = None
    if template_name is not None:
        if template_name not in templates:
            raise ValueError(f"unknown template {template_name!r}")
        expected_mission = _expand_template(str(entry["sample_id"]), templates[template_name])
    repeated = entry.get("utterance_repeat")
    if repeated is not None:
        utterance = str(repeated["text"]) * int(repeated["count"])
    else:
        utterance = str(entry["utterance"])
    return {
        "sample_id": str(entry["sample_id"]),
        "group_id": str(entry["group_id"]),
        "category": str(entry["category"]),
        "source": str(entry["source"]),
        "utterance": utterance,
        "expected_compiler_status": str(entry["expected_compiler_status"]),
        "expected_error_code": entry.get("expected_error_code"),
        "expected_mission": expected_mission,
        "expected_runtime_status": str(entry["expected_runtime_status"]),
        "expected_failure_type": entry.get("expected_failure_type"),
        "expected_simulation_steps": entry.get("expected_simulation_steps"),
        "e2e": bool(entry.get("e2e", False)),
        "horizon": entry.get("horizon"),
        "oracle_mission_id": entry.get("oracle_mission_id"),
        "notes": str(entry.get("notes", "")),
    }


def build_corpus(
    *, source_path: Path, output_path: Path, seed: int, generated_count: int
) -> LanguageCorpus:
    templates, entries = _load_source(source_path)
    samples = [_build_sample(entry, templates) for entry in entries]
    by_category = {category: 0 for category in CATEGORY_ORDER}
    for sample in samples:
        by_category[sample["category"]] = by_category.get(sample["category"], 0) + 1
    hand_utterances = [sample["utterance"] for sample in samples]

    generated = generate_samples(
        seed=seed, count=generated_count, avoid_utterances=hand_utterances
    )
    samples.extend(sample.to_dict() for sample in generated)

    counts: dict[str, int] = {category: 0 for category in CATEGORY_ORDER}
    source_counts = {"hand_authored": 0, "generated": 0, "composition": 0}
    for sample in samples:
        counts[sample["category"]] = counts.get(sample["category"], 0) + 1
        source_counts[sample["source"]] = source_counts.get(sample["source"], 0) + 1
    counts["total"] = len(samples)
    counts["end_to_end"] = sum(bool(sample["e2e"]) for sample in samples)

    document = {
        "corpus_id": "controlled_language_001",
        "corpus_schema_version": CORPUS_SCHEMA_VERSION,
        "corpus_version": "1.0.0",
        "seed": int(seed),
        "generator_version": GENERATOR_VERSION,
        "compiler_interface": "LanguageCompiler.compile(text: str) -> CompilerResult",
        "runtime_rejected_note": (
            "No frozen HIGH-only walk case exists in the Phase 1.3 evidence, so "
            "category runtime_rejected is intentionally empty; capability-unknown "
            "cases cover the zero-step rejection path instead."
        ),
        "source_hashes": {
            "hand_authored_yaml": _sha256(source_path),
            "grammar_lark": _sha256(REPO_ROOT / "src/g1swarm/language/grammar.lark"),
            "corpus_generator_py": _sha256(
                REPO_ROOT / "src/g1swarm/language/corpus_generator.py"
            ),
        },
        "counts": counts,
        "samples": samples,
    }
    corpus = parse_corpus(document, path=output_path)
    return corpus


def _dump(corpus: LanguageCorpus, path: Path) -> None:
    payload = corpus.to_dict()
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=200)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--generated-count", type=int, default=DEFAULT_GENERATED_COUNT)
    parser.add_argument("--check", action="store_true", help="verify the frozen corpus only")
    args = parser.parse_args()

    source_path = (REPO_ROOT / args.source).resolve()
    output_path = (REPO_ROOT / args.output).resolve()
    corpus = build_corpus(
        source_path=source_path,
        output_path=output_path,
        seed=args.seed,
        generated_count=args.generated_count,
    )
    if args.check:
        if not output_path.exists():
            print(f"FROZEN CORPUS MISSING: {output_path}")
            return 1
        frozen = parse_corpus(
            yaml.safe_load(output_path.read_text(encoding="utf-8")), path=output_path
        )
        rebuilt = json.dumps(corpus.to_dict(), ensure_ascii=False, sort_keys=True)
        stored = json.dumps(frozen.to_dict(), ensure_ascii=False, sort_keys=True)
        if rebuilt != stored:
            print("CORPUS MISMATCH: rebuild the corpus with scripts/build_language_corpus.py")
            return 1
        print(f"CORPUS OK: {output_path} ({len(frozen)} samples)")
        return 0

    _dump(corpus, output_path)
    print(f"WROTE {output_path} ({len(corpus)} samples)")
    for category in CATEGORY_ORDER:
        print(f"  {category:20s} {corpus.counts.get(category, 0):3d}")
    print(f"  {'end_to_end':20s} {corpus.counts.get('end_to_end', 0):3d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
