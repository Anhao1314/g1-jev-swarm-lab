"""Run the Phase 2.2 DeepSeek-v4.1flash mission compiler benchmark.

Development mode is for prompt tuning. Blind mode is allowed only after the
protocol is frozen and performs exactly one API generation per sample. The
repeatability study is a separate call budget, and end-to-end execution reuses
recorded blind outputs without invoking the model again.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

from g1swarm.config import load_yaml
from g1swarm.evidence import EnvironmentInfo, utc_timestamp
from g1swarm.language import LanguageCompiler
from g1swarm.language.benchmark import canonical_mission_hash
from g1swarm.language.errors import LanguageErrorCode
from g1swarm.language.equivalence import (
    build_runtime_executor,
    compare_runtime_results,
    load_runtime_protocol,
    mission_equivalence,
    oracle_mission_from_sample,
)
from g1swarm.language.llm import (
    BackendError,
    LLMMissionCompiler,
    OpenAICompatibleBackend,
    ReplayBackend,
    run_llm_campaign,
    write_records,
)
from g1swarm.llm.datasets import LLMSample, load_dataset
from g1swarm.llm.scoring import compare_engines, evaluate_sample, summarize_results
from g1swarm.mission.ir import Mission
from g1swarm.paths import artifacts_dir, repo_root, resolve_repo_path

EXPERIMENT_ID = "llm_compiler_001"
DEFAULT_PROTOCOL = "configs/experiments/llm_compiler_001.yaml"
EXPERIMENT_DIR = ("experiments", "phase2", EXPERIMENT_ID)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_repo_output(path: Path) -> Path:
    root = repo_root().resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise SystemExit(f"output path escapes repository: {resolved}")
    return resolved


def _write_json(path: Path, payload: Any) -> Path:
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


def _load_protocol(path: str | Path) -> tuple[dict[str, Any], Path]:
    resolved = resolve_repo_path(path)
    protocol = load_yaml(resolved)
    protocol["protocol_path"] = str(resolved.relative_to(repo_root()).as_posix())
    protocol["_protocol_sha256"] = _sha256_file(resolved)
    return protocol, resolved


def _resolve_api_key_env(protocol: Mapping[str, Any]) -> str:
    names = [str(item) for item in protocol["provider"]["api_key_envs"]]
    for name in names:
        if os.environ.get(name):
            return name
    return names[0]


def _make_backend(protocol: Mapping[str, Any]) -> OpenAICompatibleBackend:
    provider = protocol["provider"]
    base_url_env = str(provider["base_url_env"])
    base_url = os.environ.get(base_url_env) or os.environ.get("OPENAI_BASE_URL")
    if not base_url:
        raise BackendError(
            LanguageErrorCode.LLM_CONFIGURATION_ERROR,
            f"environment variable {base_url_env} is not set",
            reason="configuration",
        )
    return OpenAICompatibleBackend.from_env(
        model=str(provider["model"]),
        base_url=base_url,
        api_key_env=_resolve_api_key_env(protocol),
        provider="deepseek-relay",
        timeout_s=float(provider["timeout_s"]),
        temperature=float(provider["temperature"]),
        max_output_tokens=int(provider["max_output_tokens"]),
        max_network_retries=int(provider["max_network_retries"]),
        retry_backoff_s=float(provider["retry_backoff_s"]),
    )


def _make_llm_compiler(protocol: Mapping[str, Any], backend=None) -> LLMMissionCompiler:
    return LLMMissionCompiler(
        backend or _make_backend(protocol),
        prompt_path=resolve_repo_path(protocol["prompt"]["path"]),
        max_input_chars=int(protocol["compiler"]["max_input_chars"]),
        max_output_chars=int(protocol["compiler"]["max_output_chars"]),
        expected_prompt_sha256=str(protocol["prompt"]["sha256"]),
    )




def _raw_record(sample: LLMSample, record: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = dict(record.get("diagnostics") or {})
    return {
        "sample_id": sample.sample_id,
        "split": sample.split,
        "utterance": sample.utterance,
        "prompt_sha256": diagnostics.get("prompt_sha256"),
        "model": diagnostics.get("model"),
        "request_parameters": diagnostics.get("request_parameters"),
        "raw_response": diagnostics.get("raw_response"),
        "parsed_result": {
            "status": record.get("actual_status"),
            "mission": record.get("actual_mission"),
            "error_code": record.get("actual_error_code"),
        },
        "validation": diagnostics.get("validation"),
        "latency_s": record.get("latency_s"),
        "usage": diagnostics.get("usage"),
        "attempts": diagnostics.get("attempts"),
        "expected": {
            "status": record.get("expected_status"),
            "mission": record.get("expected_mission"),
            "error_code": record.get("expected_error_code"),
            "runtime_status": sample.expected_runtime_status,
        },
        "actual": {
            "status": record.get("actual_status"),
            "mission": record.get("actual_mission"),
            "error_code": record.get("actual_error_code"),
        },
        "exact_ir_match": record.get("exact_ir_match"),
        "failure_type": record.get("failure_type"),
    }


def _parallel_evaluate(
    samples: list[LLMSample],
    compiler,
    *,
    workers: int,
) -> list[dict[str, Any]]:
    if workers <= 1:
        return [evaluate_sample(sample, compiler) for sample in samples]
    results: list[dict[str, Any] | None] = [None] * len(samples)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(evaluate_sample, sample, compiler): index
            for index, sample in enumerate(samples)
        }
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            results[index] = future.result()
    return [item for item in results if item is not None]


def _summary_metadata(protocol: Mapping[str, Any], corpus_path: Path, campaign: str) -> dict[str, Any]:
    return {
        "experiment_id": EXPERIMENT_ID,
        "campaign": campaign,
        "protocol_sha256": protocol.get("_protocol_sha256"),
        "dataset_sha256": _sha256_file(corpus_path),
        "prompt_sha256": _sha256_file(resolve_repo_path(protocol["prompt"]["path"])),
        "model": protocol["provider"]["model"],
        "environment": EnvironmentInfo.collect().to_dict(),
        "generated_at": utc_timestamp(),
    }


def _run_development(protocol: Mapping[str, Any], dataset_path: Path) -> dict[str, Any]:
    dataset = load_dataset(dataset_path)
    live_compiler = _make_llm_compiler(protocol, _make_backend(protocol))
    live = run_llm_campaign(
        compiler=live_compiler,
        samples=[sample.to_dict() for sample in dataset.samples],
        protocol=protocol,
        corpus=dataset,
        corpus_path=dataset_path,
        campaign="development",
        backend_kind="http",
        record_raw=True,
    )
    replay_compiler = _make_llm_compiler(protocol, ReplayBackend(live.records))
    records = [evaluate_sample(sample, replay_compiler) for sample in dataset.samples]
    summary = summarize_results(records)
    summary.update(_summary_metadata(protocol, dataset_path, "development"))
    summary["llm_diagnostics"] = live.summary.get("llm_diagnostics")
    out_dir = _ensure_repo_output(artifacts_dir() / EXPERIMENT_ID / "development")
    _write_json(out_dir / "summary.json", summary)
    _write_json(out_dir / "results.json", records)
    write_records(out_dir / "raw_responses.jsonl", live.records)
    return summary


def _run_blind(protocol: Mapping[str, Any], dataset_path: Path) -> dict[str, Any]:
    dataset = load_dataset(dataset_path)
    live_compiler = _make_llm_compiler(protocol, _make_backend(protocol))
    live = run_llm_campaign(
        compiler=live_compiler,
        samples=[sample.to_dict() for sample in dataset.samples],
        protocol=protocol,
        corpus=dataset,
        corpus_path=dataset_path,
        campaign="blind",
        backend_kind="http",
        record_raw=True,
    )
    replay_compiler = _make_llm_compiler(protocol, ReplayBackend(live.records))
    llm_records = [evaluate_sample(sample, replay_compiler) for sample in dataset.samples]
    rule_records = [evaluate_sample(sample, LanguageCompiler()) for sample in dataset.samples]
    comparison = compare_engines(rule_records, llm_records)
    comparison.update(_summary_metadata(protocol, dataset_path, "blind"))
    comparison["llm_diagnostics"] = live.summary.get("llm_diagnostics")
    out_dir = _ensure_repo_output(repo_root().joinpath(*EXPERIMENT_DIR))
    _write_json(out_dir / "rule_results.json", rule_records)
    _write_json(out_dir / "llm_results.json", llm_records)
    _write_json(out_dir / "comparison.json", comparison)
    raw_file = _ensure_repo_output(artifacts_dir() / EXPERIMENT_ID / "blind" / "raw_responses.jsonl")
    write_records(raw_file, live.records)
    _write_json(artifacts_dir() / EXPERIMENT_ID / "blind" / "request_summary.json", live.summary)
    return comparison




def _run_repeatability(protocol: Mapping[str, Any], dataset_path: Path) -> dict[str, Any]:
    dataset = load_dataset(dataset_path)
    by_id = {sample.sample_id: sample for sample in dataset.samples}
    sample_ids = tuple(protocol.get("repeatability", {}).get("sample_ids", []))
    if not sample_ids:
        sample_ids = tuple(
            sample.sample_id
            for sample in dataset.samples
            if sample.e2e or sample.expected_compiler_status == "SUCCESS"
        )[:20]
    repeats = int(protocol.get("repeatability", {}).get("repeats", 3))
    compiler = _make_llm_compiler(protocol, _make_backend(protocol))
    records: list[dict[str, Any]] = []
    for sample_id in sample_ids:
        if sample_id not in by_id:
            raise SystemExit(f"repeatability sample not found in dataset: {sample_id}")
        for repeat in range(1, repeats + 1):
            record = evaluate_sample(by_id[sample_id], compiler)
            records.append({**record, "repeat": repeat})
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["sample_id"]), []).append(record)
    payload = {
        "schema_version": "1.0.0",
        "experiment_id": EXPERIMENT_ID,
        "protocol_sha256": protocol.get("_protocol_sha256"),
        "prompt_sha256": _sha256_file(resolve_repo_path(protocol["prompt"]["path"])),
        "dataset_sha256": _sha256_file(dataset_path),
        "repeats": repeats,
        "records": records,
        "groups": {
            sample_id: {
                "status_consistency": len({item["actual_status"] for item in items}) == 1,
                "ir_consistency": len(
                    {
                        json.dumps(item["actual_mission"], sort_keys=True, ensure_ascii=False)
                        for item in items
                    }
                )
                == 1,
                "latency_mean_s": mean(float(item["latency_s"]) for item in items),
                "latency_values_s": [float(item["latency_s"]) for item in items],
            }
            for sample_id, items in sorted(grouped.items())
        },
        "generated_at": utc_timestamp(),
    }
    out_dir = _ensure_repo_output(repo_root().joinpath(*EXPERIMENT_DIR))
    _write_json(out_dir / "repeatability.json", payload)
    raw_dir = _ensure_repo_output(artifacts_dir() / EXPERIMENT_ID / "repeatability" / "raw")
    for record in records:
        _write_json(raw_dir / f"{record['sample_id']}-r{record['repeat']}.json", record)
    return payload


def _runtime_for_mission(
    *,
    mission,
    protocol: Mapping[str, Any],
    runtime_protocol_path: str,
    evidence_root: Path,
    entry: str,
    provenance: Mapping[str, Any],
):
    runtime_protocol = load_runtime_protocol(runtime_protocol_path)
    executor = build_runtime_executor(
        protocol=runtime_protocol,
        recorder_root=evidence_root,
        provenance={**dict(provenance), "entry": entry},
    )
    return executor.run(mission, phase=f"llm-{entry}", write_evidence=True)


def _run_e2e(protocol: Mapping[str, Any], dataset_path: Path) -> dict[str, Any]:
    dataset = load_dataset(dataset_path)
    by_id = {sample.sample_id: sample for sample in dataset.samples}
    sample_ids = tuple(protocol.get("e2e_sample_ids", []))
    if not sample_ids:
        sample_ids = tuple(
            sample.sample_id for sample in dataset.samples if sample.e2e
        )
    out_dir = _ensure_repo_output(repo_root().joinpath(*EXPERIMENT_DIR))
    llm_results = {
        item["sample_id"]: item
        for item in json.loads((out_dir / "llm_results.json").read_text(encoding="utf-8"))
    }
    rule_results = {
        item["sample_id"]: item
        for item in json.loads((out_dir / "rule_results.json").read_text(encoding="utf-8"))
    }
    runtime_protocol_path = str(protocol.get("runtime_protocol", "configs/experiments/oracle_mission_runtime_001.yaml"))
    records: list[dict[str, Any]] = []
    for sample_id in sample_ids:
        sample = by_id[sample_id]
        llm_record = llm_results[sample_id]
        rule_record = rule_results[sample_id]
        expected = sample.expected_mission
        if expected is None:
            raise SystemExit(f"end-to-end sample {sample_id} has no expected mission")
        oracle_mission = oracle_mission_from_sample(expected, mission_id=f"oracle-{sample_id}")
        llm_mission = llm_record.get("actual_mission")
        rule_mission = rule_record.get("actual_mission")
        llm_ir = bool(
            llm_mission is not None
            and mission_equivalence(
                Mission.from_dict(llm_mission),
                oracle_mission,
            )["exact_match"]
        )
        rule_ir = bool(
            rule_mission is not None
            and mission_equivalence(
                Mission.from_dict(rule_mission),
                oracle_mission,
            )["exact_match"]
        )
        record: dict[str, Any] = {
            "sample_id": sample_id,
            "utterance": sample.utterance,
            "oracle_ir_hash": canonical_mission_hash(oracle_mission),
            "llm_ir_hash": canonical_mission_hash(llm_mission) if llm_mission else None,
            "rule_ir_hash": canonical_mission_hash(rule_mission) if rule_mission else None,
            "llm_ir_exact": llm_ir,
            "rule_ir_exact": rule_ir,
            "llm_execution_skipped": not llm_ir,
            "rule_execution_skipped": not rule_ir,
        }
        evidence_root = artifacts_dir() / EXPERIMENT_ID / "final" / "e2e" / sample_id
        _ensure_repo_output(evidence_root)
        oracle_result = _runtime_for_mission(
            mission=oracle_mission,
            protocol=protocol,
            runtime_protocol_path=runtime_protocol_path,
            evidence_root=evidence_root / "oracle",
            entry="oracle",
            provenance={"language_input": sample.utterance},
        )
        record["oracle"] = {
            "state": oracle_result.state,
            "simulation_steps_executed": oracle_result.simulation_steps_executed,
            "failure_type": oracle_result.failure_type,
        }
        if llm_ir:
            llm_result = _runtime_for_mission(
                mission=Mission.from_dict(llm_mission),
                protocol=protocol,
                runtime_protocol_path=runtime_protocol_path,
                evidence_root=evidence_root / "llm",
                entry="llm",
                provenance={"language_input": sample.utterance, "model": protocol["provider"]["model"]},
            )
            comparison = compare_runtime_results(llm_result, oracle_result)
            record["llm_runtime_equivalence"] = comparison["runtime_equivalent"]
            record["llm"] = {
                "state": llm_result.state,
                "simulation_steps_executed": llm_result.simulation_steps_executed,
                "failure_type": llm_result.failure_type,
            }
        else:
            record["llm_runtime_equivalence"] = False
            record["llm"] = None
        if rule_ir:
            rule_result = _runtime_for_mission(
                mission=Mission.from_dict(rule_mission),
                protocol=protocol,
                runtime_protocol_path=runtime_protocol_path,
                evidence_root=evidence_root / "rule",
                entry="rule",
                provenance={"language_input": sample.utterance, "compiler": "LanguageCompiler"},
            )
            comparison = compare_runtime_results(rule_result, oracle_result)
            record["rule_runtime_equivalence"] = comparison["runtime_equivalent"]
            record["rule"] = {
                "state": rule_result.state,
                "simulation_steps_executed": rule_result.simulation_steps_executed,
                "failure_type": rule_result.failure_type,
            }
        else:
            record["rule_runtime_equivalence"] = False
            record["rule"] = None
        records.append(record)
    payload = {
        "schema_version": "1.0.0",
        "experiment_id": EXPERIMENT_ID,
        "protocol_sha256": protocol.get("_protocol_sha256"),
        "samples": records,
        "summary": {
            "samples": len(records),
            "llm_ir_equivalence_rate": (
                sum(bool(item["llm_ir_exact"]) for item in records) / len(records)
                if records
                else None
            ),
            "llm_runtime_equivalence_rate": (
                sum(bool(item["llm_runtime_equivalence"]) for item in records) / len(records)
                if records
                else None
            ),
            "rule_ir_equivalence_rate": (
                sum(bool(item["rule_ir_exact"]) for item in records) / len(records)
                if records
                else None
            ),
            "zero_step_compliant": all(
                item.get("oracle", {}).get("simulation_steps_executed") == 0
                or item.get("llm", {}).get("simulation_steps_executed") == 0
                for item in records
                if item.get("llm") is not None
            ),
        },
        "generated_at": utc_timestamp(),
    }
    _write_json(out_dir / "execution_equivalence.json", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--workers", type=int, default=4)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--development", action="store_true")
    mode.add_argument("--blind", action="store_true")
    mode.add_argument("--repeatability", action="store_true")
    mode.add_argument("--e2e", action="store_true")
    args = parser.parse_args(argv)

    protocol, protocol_path = _load_protocol(args.protocol)
    if args.blind and not bool(protocol.get("frozen", False)):
        raise SystemExit("protocol is not frozen; refusing blind benchmark")
    dataset_path = resolve_repo_path(
        args.dataset
        or protocol["datasets"]["development" if args.development else "blind"]
    )
    try:
        if args.development:
            summary = _run_development(protocol, dataset_path)
        elif args.blind:
            summary = _run_blind(protocol, dataset_path)
        elif args.repeatability:
            summary = _run_repeatability(protocol, dataset_path)
        else:
            summary = _run_e2e(protocol, dataset_path)
    except BackendError as exc:
        print(f"BLOCKED: {exc.message} ({exc.reason})")
        return 3
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
