"""Run the Phase 2.1 controlled-language compiler benchmark.

Pilot mode checks a small pre-flight set. Final mode compiles the frozen
corpus, writes compiler evidence, and runs the selected language missions
through the unchanged Phase 2.0 runtime against Oracle IR equivalents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from g1swarm.config import load_yaml
from g1swarm.evidence import EnvironmentInfo, utc_timestamp
from g1swarm.language import COMPILER_VERSION, LanguageCompiler
from g1swarm.language.benchmark import (
    canonical_mission_hash,
    evaluate_compiler_sample,
    summarize_compiler_results,
)
from g1swarm.language.corpus import load_corpus as load_language_corpus
from g1swarm.language.equivalence import (
    compare_runtime_results,
    load_runtime_protocol,
    mission_equivalence,
    oracle_mission_from_sample,
    build_runtime_executor,
)
from g1swarm.paths import artifacts_dir, repo_root, resolve_repo_path

EXPERIMENT_ID = "controlled_language_001"
DEFAULT_PROTOCOL = "configs/experiments/controlled_language_001.yaml"
EXPERIMENT_DIR = ("experiments", "phase2", EXPERIMENT_ID)
PILOT_FALLBACK_IDS = (
    "pilot-walk4",
    "pilot-sequence-right45-stop",
    "pilot-chinese-left90",
    "pilot-unit-4m",
    "pilot-ambiguous-point",
    "pilot-missing-right-turn",
    "pilot-unsupported-cup",
    "pilot-capability-unknown-25m",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_repo_output(path: Path) -> Path:
    root = repo_root().resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise SystemExit(f"output path escapes repository: {resolved}")
    return resolved


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def _load_protocol(path: str | Path) -> tuple[dict[str, Any], Path, str]:
    resolved = resolve_repo_path(path)
    protocol = load_yaml(resolved)
    protocol["protocol_path"] = str(resolved.relative_to(repo_root()).as_posix())
    digest = _sha256_file(resolved)
    protocol["_protocol_sha256"] = digest
    return protocol, resolved, digest


def _select_samples(
    corpus: Mapping[str, Any], sample_ids: tuple[str, ...] | None
) -> list[dict[str, Any]]:
    samples = [sample.to_dict() for sample in corpus.samples]
    if sample_ids is None:
        return samples
    by_id = {sample["sample_id"]: sample for sample in samples}
    missing = [sample_id for sample_id in sample_ids if sample_id not in by_id]
    if missing:
        raise SystemExit(f"unknown language sample_id(s): {', '.join(missing)}")
    return [by_id[sample_id] for sample_id in sample_ids]


def _sample_ids_from_protocol(protocol: Mapping[str, Any], key: str) -> tuple[str, ...] | None:
    values = protocol.get(key)
    if values is None:
        return None
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise SystemExit(f"protocol {key} must be a list of sample IDs")
    return tuple(values)


def _run_compiler_only(
    *,
    samples: list[dict[str, Any]],
    compiler: LanguageCompiler,
    protocol: Mapping[str, Any],
    corpus: Mapping[str, Any],
    campaign: str,
    corpus_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results = [evaluate_compiler_sample(sample, compiler) for sample in samples]
    summary = summarize_compiler_results(results)
    summary.update(
        {
            "experiment_id": EXPERIMENT_ID,
            "campaign": campaign,
            "compiler_version": COMPILER_VERSION,
            "grammar_sha256": compiler.grammar_sha256,
            "protocol_sha256": protocol.get("_protocol_sha256"),
            "corpus_id": corpus.corpus_id,
            "corpus_sha256": _sha256_file(corpus_path),
            "environment": EnvironmentInfo.collect().to_dict(),
            "generated_at": utc_timestamp(),
        }
    )
    return results, summary


def _print_results(results: list[dict[str, Any]]) -> None:
    for item in results:
        print(
            f"[{item['sample_id']}] expected={item['expected_status']} "
            f"actual={item['actual_status']} exact={item['exact_ir_match']} "
            f"error={item['actual_error_code']} utterance={item['utterance']!r}"
        )


def _run_end_to_end(
    *,
    samples: list[dict[str, Any]],
    compiler: LanguageCompiler,
    language_protocol: Mapping[str, Any],
    corpus: Mapping[str, Any],
    corpus_path: Path,
    runtime_protocol_path: str,
    campaign: str,
) -> dict[str, Any]:
    runtime_protocol = load_runtime_protocol(runtime_protocol_path)
    sample_ids = _sample_ids_from_protocol(language_protocol, "e2e_sample_ids")
    if sample_ids is None:
        sample_ids = tuple(
            sample["sample_id"]
            for sample in samples
            if sample.get("expected_compiler_status") == "SUCCESS"
        )[:12]
    selected = _select_samples(corpus, sample_ids)
    records: list[dict[str, Any]] = []
    for sample in selected:
        sample_id = str(sample["sample_id"])
        result = compiler.compile(str(sample["utterance"]))
        record: dict[str, Any] = {
            "sample_id": sample_id,
            "utterance": sample["utterance"],
            "compiler_status": result.status.value,
            "compiler_error": result.error_code.value if result.error_code else None,
            "expected_runtime_status": sample.get("expected_runtime_status"),
        }
        if result.mission is None:
            record["ir_equivalence"] = False
            record["runtime_equivalence"] = False
            record["simulation_steps_executed"] = None
            records.append(record)
            continue

        expected_mission = sample["expected_mission"]
        oracle_mission = oracle_mission_from_sample(
            expected_mission, mission_id=f"oracle-{sample_id}"
        )
        ir_check = mission_equivalence(result.mission, oracle_mission)
        record["ir"] = ir_check
        record["compiled_ir_hash"] = canonical_mission_hash(result.mission)
        record["oracle_ir_hash"] = canonical_mission_hash(oracle_mission)

        provenance_base = {
            "language_input": sample["utterance"],
            "compiler_type": "rule_lark",
            "compiler_version": COMPILER_VERSION,
            "grammar_sha256": compiler.grammar_sha256,
            "corpus_sha256": _sha256_file(corpus_path),
            "compiled_ir_hash": canonical_mission_hash(result.mission),
            "oracle_ir_hash": canonical_mission_hash(oracle_mission),
            "exact_match": ir_check["exact_match"],
        }
        evidence_root = artifacts_dir() / EXPERIMENT_ID / campaign / "e2e" / sample_id
        _ensure_repo_output(evidence_root)
        compiled_executor = build_runtime_executor(
            protocol=runtime_protocol,
            recorder_root=evidence_root / "compiled",
            provenance={**provenance_base, "entry": "compiled_language"},
        )
        oracle_executor = build_runtime_executor(
            protocol=runtime_protocol,
            recorder_root=evidence_root / "oracle",
            provenance={**provenance_base, "entry": "oracle_ir"},
        )
        compiled_result = compiled_executor.run(
            result.mission, phase=f"language-{campaign}", write_evidence=True
        )
        oracle_result = oracle_executor.run(
            oracle_mission, phase=f"oracle-{campaign}", write_evidence=True
        )
        runtime_check = compare_runtime_results(compiled_result, oracle_result)
        record["runtime"] = runtime_check
        record["runtime_equivalence"] = runtime_check["runtime_equivalent"]
        record["compiled_state"] = compiled_result.state
        record["oracle_state"] = oracle_result.state
        record["compiled_failure_type"] = compiled_result.failure_type
        record["oracle_failure_type"] = oracle_result.failure_type
        record["simulation_steps_executed"] = compiled_result.simulation_steps_executed
        # The corpus records the runtime state (REJECTED) separately from the
        # Phase 2.0 failure taxonomy (CAPABILITY_UNKNOWN / CAPABILITY_REJECTED).
        rejection_expected = (
            sample.get("expected_runtime_status") == "REJECTED"
            or sample.get("expected_failure_type")
            in {"CAPABILITY_UNKNOWN", "CAPABILITY_REJECTED"}
        )
        record["zero_step_compliant"] = (
            compiled_result.simulation_steps_executed == 0 if rejection_expected else None
        )
        records.append(record)
        print(
            f"[e2e {sample_id}] ir={ir_check['exact_match']} "
            f"runtime={runtime_check['runtime_equivalent']} "
            f"state={compiled_result.state} steps={compiled_result.simulation_steps_executed}"
        )

    payload = {
        "schema_version": "2.1.0",
        "experiment_id": EXPERIMENT_ID,
        "campaign": campaign,
        "protocol_sha256": language_protocol.get("_protocol_sha256"),
        "corpus_sha256": _sha256_file(corpus_path),
        "grammar_sha256": compiler.grammar_sha256,
        "runtime_protocol_sha256": runtime_protocol.get("_protocol_sha256"),
        "samples": records,
        "summary": {
            "samples": len(records),
            "ir_equivalence_rate": (
                sum(bool(item.get("ir", {}).get("exact_match")) for item in records)
                / len(records)
                if records
                else None
            ),
            "runtime_equivalence_rate": (
                sum(bool(item.get("runtime_equivalence")) for item in records) / len(records)
                if records
                else None
            ),
            "zero_step_compliant": all(
                item.get("zero_step_compliant") is not False for item in records
            ),
        },
        "generated_at": utc_timestamp(),
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    parser.add_argument("--corpus", default=None)
    parser.add_argument("--runtime-protocol", default=None)
    parser.add_argument("--e2e-sample-ids", default=None)
    parser.add_argument("--skip-e2e", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pilot", action="store_true")
    mode.add_argument("--final", action="store_true")
    args = parser.parse_args(argv)

    protocol, protocol_path, _ = _load_protocol(args.protocol)
    if args.final and not bool(protocol.get("frozen", False)):
        raise SystemExit("protocol is not marked frozen=True; refusing final benchmark")
    corpus_path = resolve_repo_path(args.corpus or protocol["language_corpus"])
    corpus = load_language_corpus(corpus_path)
    campaign = "final" if args.final else "pilot"
    compiler = LanguageCompiler(
        max_input_chars=int(protocol.get("compiler", {}).get("max_input_chars", 512))
    )
    pilot_ids = _sample_ids_from_protocol(protocol, "pilot_sample_ids")
    if pilot_ids is None:
        pilot_ids = PILOT_FALLBACK_IDS
    samples = _select_samples(corpus, None if args.final else pilot_ids)
    results, summary = _run_compiler_only(
        samples=samples,
        compiler=compiler,
        protocol=protocol,
        corpus=corpus,
        campaign=campaign,
        corpus_path=corpus_path,
    )
    print(f"campaign={campaign} samples={len(results)} protocol={protocol_path}")
    _print_results(results)

    if args.final:
        out_dir = _ensure_repo_output(repo_root().joinpath(*EXPERIMENT_DIR))
        _write_json(out_dir / "compiler_results.json", results)
        _write_jsonl(out_dir / "compiler_results.jsonl", results)
        _write_json(out_dir / "compiler_summary.json", summary)
    else:
        pilot_dir = _ensure_repo_output(artifacts_dir() / EXPERIMENT_ID / "pilot")
        _write_jsonl(pilot_dir / "compiler_results.jsonl", results)
        _write_json(pilot_dir / "compiler_summary.json", summary)

    e2e_payload: dict[str, Any] | None = None
    if args.final and not args.skip_e2e:
        if args.e2e_sample_ids:
            protocol["e2e_sample_ids"] = [
                value.strip() for value in args.e2e_sample_ids.split(",") if value.strip()
            ]
        runtime_protocol_path = (
            args.runtime_protocol or protocol.get("runtime_protocol", "configs/experiments/oracle_mission_runtime_001.yaml")
        )
        e2e_payload = _run_end_to_end(
            samples=samples,
            compiler=compiler,
            language_protocol=protocol,
            corpus=corpus,
            corpus_path=corpus_path,
            runtime_protocol_path=runtime_protocol_path,
            campaign=campaign,
        )
        _write_json(
            _ensure_repo_output(repo_root().joinpath(*EXPERIMENT_DIR))
            / "execution_equivalence.json",
            e2e_payload,
        )

    hard_gates = {
        "hallucinated_skill_count": summary["hallucinated_skill_count"],
        "invalid_language_reaching_robot": summary["invalid_language_reaching_robot"],
        "ambiguous_language_reaching_robot": summary["ambiguous_language_reaching_robot"],
        "unsupported_language_reaching_robot": summary["unsupported_language_reaching_robot"],
    }
    print(json.dumps({"hard_gates": hard_gates, "summary": summary}, ensure_ascii=False, indent=2))
    if any(value != 0 for value in hard_gates.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
