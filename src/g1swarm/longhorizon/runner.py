"""Phase 2.3 long-horizon benchmark runner.

Stage A compiles every language realization with the frozen Phase 2.2b
selected treatment (``guarded_direct_llm_v1``); Stage B executes only
exact-IR missions through the frozen Phase 2.0 runtime and pairs every
language run with its oracle run.

Nothing in this module modifies the frozen compiler, guard, prompts, runtime,
grounding evidence or scoring. ``--scripted`` exists for offline harness
validation only and must never be used for campaign evidence.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..config import load_yaml
from ..language.compiler import LanguageCompiler
from ..language.equivalence import (
    build_runtime_executor,
    load_runtime_protocol,
    mission_equivalence,
)
from ..language.errors import CompilerStatus
from ..language.result import CompilerResult
from ..llm.compiler import LLMMissionCompiler
from ..mission.ir import Mission
from ..paths import repo_root, resolve_repo_path
from ..simplex.structural_guard import StructuralGuard
from ..simplex.treatments import GuardedDirectLLMTreatment
from . import benchmark
from .corpus import EXPERIMENT_ID, build_corpus

DEFAULT_DIR = repo_root() / "experiments" / "phase2" / EXPERIMENT_ID
DEFAULT_PROTOCOL = DEFAULT_DIR / "protocol.yaml"


# ---------------------------------------------------------------------------
# Frozen treatment construction


def load_protocol(path: str | Path = DEFAULT_PROTOCOL) -> dict[str, Any]:
    resolved = resolve_repo_path(path)
    protocol = load_yaml(resolved)
    protocol["protocol_path"] = str(resolved.relative_to(repo_root()).as_posix())
    protocol["_protocol_sha256"] = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return protocol


def _make_backend(protocol: Mapping[str, Any]) -> Any:  # pragma: no cover - network path
    import os

    from ..language.llm import OpenAICompatibleBackend

    provider = protocol["provider"]
    base_url = os.environ.get(str(provider["base_url_env"])) or os.environ.get("OPENAI_BASE_URL")
    if not base_url:
        raise RuntimeError(f"environment variable {provider['base_url_env']} is not set")
    env_name = next(
        (str(name) for name in provider["api_key_envs"] if os.environ.get(str(name))),
        str(provider["api_key_envs"][0]),
    )
    return OpenAICompatibleBackend.from_env(
        model=str(provider["model"]),
        base_url=base_url,
        api_key_env=env_name,
        provider="deepseek-relay",
        timeout_s=float(provider["timeout_s"]),
        temperature=float(provider["temperature"]),
        max_output_tokens=int(provider["max_output_tokens"]),
        max_network_retries=int(provider["max_network_retries"]),
        retry_backoff_s=float(provider["retry_backoff_s"]),
    )


def build_frozen_treatment(
    protocol: Mapping[str, Any], *, backend: Any | None = None
) -> tuple[GuardedDirectLLMTreatment, dict[str, Any]]:
    """Construct the frozen selected architecture (B, guarded_direct_llm_v1)."""
    provider_backend = backend if backend is not None else _make_backend(protocol)
    direct = LLMMissionCompiler(
        backend=provider_backend,
        prompt_path=resolve_repo_path(protocol["prompt"]["direct"]),
        protocol=protocol,
    )
    treatment = GuardedDirectLLMTreatment(StructuralGuard(), direct)
    provenance = {
        "compiler_architecture": "guarded_direct_llm_v1",
        "selection_source": "phase2.2b",
        "selection_commit": "4662bef",
        "guard_version": StructuralGuard.version,
        "prompt_sha256": str(protocol["prompt"]["sha256"]),
        "protocol_sha256": protocol.get("_protocol_sha256"),
        "model": str(protocol["provider"]["model"]),
    }
    return treatment, provenance


class ScriptedOracleCompiler:
    """Offline harness stand-in: replays canonical IR for known texts.

    Used only by ``--scripted`` local validation. It bypasses the provider and
    must never be used to produce campaign evidence.
    """

    def __init__(self, answers: Mapping[str, tuple[str, Mapping[str, Any] | None]]) -> None:
        self.answers = dict(answers)
        self.model = "scripted-oracle"
        self.calls = 0

    def compile(self, text: str) -> CompilerResult:
        self.calls += 1
        status_name, mission = self.answers.get(text, ("MALFORMED", None))
        status = CompilerStatus(status_name)
        return CompilerResult(
            status=status,
            mission=Mission.from_dict(mission) if mission is not None else None,
            normalized_text=text,
            diagnostics={
                "route": "SCRIPTED_ORACLE",
                "llm_invocations": 0,
                "latency_s": 0.0,
                "scripted": True,
            },
        )


def scripted_answers_from_corpus(corpus: Mapping[str, Any]) -> dict[str, tuple[str, Mapping[str, Any] | None]]:
    answers: dict[str, tuple[str, Mapping[str, Any] | None]] = {}
    missions = {str(mission["mission_id"]): mission for mission in corpus["canonical_missions"]}
    for sample in corpus["language_samples"]:
        mission = missions[str(sample["mission_id"])]
        answers[str(sample["text"])] = ("SUCCESS", benchmark.mission_document(mission))
    for control in corpus["safety_controls"]:
        intended = control.get("intended_mission")
        if intended is not None:
            answers[str(control["text"])] = ("SUCCESS", intended)
        else:
            answers[str(control["text"])] = (str(control["expected_compiler_status"]), None)
    return answers


# ---------------------------------------------------------------------------
# L1 self-check (frozen Phase 2.1 grammar)


def verify_l1_realizations(corpus: Mapping[str, Any]) -> list[str]:
    """Compile every L1 text with the frozen Lark grammar and compare to the
    canonical mission. Returns a list of problems (empty means clean)."""
    missions = {str(mission["mission_id"]): mission for mission in corpus["canonical_missions"]}
    compiler = LanguageCompiler()
    problems: list[str] = []
    for sample in corpus["language_samples"]:
        if sample["condition"] != "L1":
            continue
        result = compiler.compile(str(sample["text"]))
        if not result.success or result.mission is None:
            problems.append(
                f"{sample['sample_id']}: frozen grammar rejected L1 text "
                f"({result.status.value}: {result.error_message})"
            )
            continue
        oracle = Mission.from_dict(benchmark.mission_document(missions[str(sample["mission_id"])]))
        comparison = mission_equivalence(result.mission, oracle)
        if not comparison["exact_match"]:
            problems.append(f"{sample['sample_id']}: L1 text compiled to a different mission IR")
    return problems


# ---------------------------------------------------------------------------
# Stage runners


def run_compiler_stage(
    corpus: Mapping[str, Any],
    compiler: Any,
    *,
    provenance: Mapping[str, Any],
    experiment_id: str = EXPERIMENT_ID,
) -> dict[str, Any]:
    missions = {str(mission["mission_id"]): mission for mission in corpus["canonical_missions"]}
    records = []
    for sample in corpus["language_samples"]:
        started = time.perf_counter()
        result = compiler.compile(str(sample["text"]))
        wall_time_s = time.perf_counter() - started
        records.append(
            benchmark.compiler_record(
                experiment_id=experiment_id,
                sample=sample,
                mission=missions[str(sample["mission_id"])],
                result=result,
                provenance=provenance,
                wall_time_s=wall_time_s,
            )
        )
    controls = []
    for control in corpus["safety_controls"]:
        started = time.perf_counter()
        result = compiler.compile(str(control["text"]))
        wall_time_s = time.perf_counter() - started
        record = benchmark.control_record(
            experiment_id=experiment_id,
            control=control,
            result=result,
            provenance=provenance,
        )
        record["wall_time_s"] = wall_time_s
        controls.append(record)
    return {
        "experiment_id": experiment_id,
        "stage": "compiler",
        "record_count": len(records),
        "control_count": len(controls),
        "records": records,
        "safety_controls": controls,
        "summary": benchmark.summarize_compiler(records),
    }


def run_oracle_stage(
    corpus: Mapping[str, Any],
    *,
    runtime_protocol_path: str | Path,
    seed: int = 0,
) -> dict[str, Any]:
    runtime_protocol = load_runtime_protocol(runtime_protocol_path)
    executor = build_runtime_executor(protocol=runtime_protocol, seed=seed)
    results: dict[str, Any] = {}
    for mission in corpus["canonical_missions"]:
        document = benchmark.mission_document(mission)
        result = executor.run(document, phase="final", write_evidence=False)
        results[str(mission["mission_id"])] = {
            "mission_id": result.mission_id,
            "horizon": str(mission["horizon"]),
            "mission_success": bool(result.mission_success),
            "state": result.state,
            "failure_type": result.failure_type,
            "failure_reason": result.failure_reason,
            "completed_nodes": int(result.completed_nodes),
            "failed_node": result.failed_node,
            "transition_count": int(result.transition_count),
            "controller_memory_resets": int(result.controller_memory_resets),
            "simulation_steps_executed": int(result.simulation_steps_executed),
            "path_length_m": float(result.path_length_m),
            "total_simulation_time_s": float(result.total_simulation_time_s),
            "total_wall_time_s": float(result.total_wall_time_s),
            "grounding": dict(result.grounding),
            "transitions": [dict(transition) for transition in result.transitions],
            "_result": result,
        }
    summary_success = sum(1 for entry in results.values() if entry["mission_success"])
    return {
        "experiment_id": EXPERIMENT_ID,
        "stage": "oracle_runtime",
        "mission_count": len(results),
        "success_count": summary_success,
        "results": results,
    }


def run_language_stage(
    compiler_stage: Mapping[str, Any],
    oracle_stage: Mapping[str, Any],
    *,
    runtime_protocol_path: str | Path,
    provenance: Mapping[str, Any],
    seed: int = 0,
) -> dict[str, Any]:
    runtime_protocol = load_runtime_protocol(runtime_protocol_path)
    executor = build_runtime_executor(protocol=runtime_protocol, seed=seed)
    oracle_results = {str(key): value["_result"] for key, value in oracle_stage["results"].items()}
    records: list[dict[str, Any]] = []
    for row in compiler_stage["records"]:
        if not row.get("exact_ir_match") or row.get("compiled_mission") is None:
            continue
        mission_doc = row["compiled_mission"]
        language_result = executor.run(mission_doc, phase="final", write_evidence=False)
        oracle_result = oracle_results[str(row["mission_id"])]
        records.append(
            benchmark.runtime_record(
                experiment_id=EXPERIMENT_ID,
                sample={
                    "sample_id": row["sample_id"],
                    "mission_id": row["mission_id"],
                    "horizon": row["horizon"],
                    "condition": row["condition"],
                    "text": row["text"],
                },
                compiler_row=row,
                language_result=language_result,
                oracle_result=oracle_result,
                provenance=provenance,
            )
        )
    return {
        "experiment_id": EXPERIMENT_ID,
        "stage": "language_runtime",
        "record_count": len(records),
        "records": records,
        "summary": benchmark.summarize_runtime(records),
    }


def summarize_stages(
    compiler_stage: Mapping[str, Any],
    runtime_stage: Mapping[str, Any],
    *,
    out_dir: str | Path,
) -> dict[str, Path]:
    """Write horizon_summary.json, transition_analysis.json,
    failure_taxonomy.json and latency_tokens.json."""
    root = Path(out_dir)
    compiler_records = list(compiler_stage["records"])
    runtime_records = list(runtime_stage["records"])
    horizon_summary = benchmark.build_horizon_summary(compiler_records, runtime_records)
    horizon_summary["degradation"] = benchmark.horizon_deltas(horizon_summary)
    outputs = {
        "horizon_summary": root / "horizon_summary.json",
        "transition_analysis": root / "transition_analysis.json",
        "failure_taxonomy": root / "failure_taxonomy.json",
        "latency_tokens": root / "latency_tokens.json",
    }
    write_json(outputs["horizon_summary"], horizon_summary)
    write_json(outputs["transition_analysis"], benchmark.transition_analysis(runtime_records))
    write_json(
        outputs["failure_taxonomy"],
        benchmark.failure_taxonomy_summary(runtime_records, compiler_stage.get("safety_controls", [])),
    )
    write_json(outputs["latency_tokens"], benchmark.latency_token_summary(compiler_records))
    return outputs


def write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def write_yaml(path: Path, payload: Mapping[str, Any]) -> Path:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(dict(payload), allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def strip_internal_results(stage: Mapping[str, Any]) -> dict[str, Any]:
    """Remove non-serializable ``_result`` handles before writing evidence."""
    if stage.get("stage") == "oracle_runtime":
        cleaned = dict(stage)
        cleaned["results"] = {
            key: {k: v for k, v in value.items() if k != "_result"}
            for key, value in stage["results"].items()
        }
        return cleaned
    return dict(stage)


def generate_corpus_files(
    *, per_horizon: int = 20, seed: int = 2300, out_dir: str | Path = DEFAULT_DIR
) -> dict[str, Path]:
    corpus = build_corpus(per_horizon=per_horizon, seed=seed)
    from .corpus import validate_corpus

    problems = validate_corpus(corpus)
    if problems:
        raise ValueError("corpus validation failed:\n" + "\n".join(problems))
    root = Path(out_dir)
    outputs = {
        "canonical_missions": write_yaml(
            root / "canonical_missions.yaml",
            {
                "schema_version": corpus["schema_version"],
                "corpus_id": f"{EXPERIMENT_ID}-{corpus['generator_version']}",
                "generator_seed": corpus["generator_seed"],
                "per_horizon": corpus["per_horizon"],
                "horizons": corpus["horizons"],
                "grounding_evidence": corpus["grounding_evidence"],
                "parameter_pool": corpus["parameter_pool"],
                "missions": corpus["canonical_missions"],
            },
        ),
        "language_realizations": write_yaml(
            root / "language_realizations.yaml",
            {
                "schema_version": corpus["schema_version"],
                "conditions": corpus["conditions"],
                "samples": corpus["language_samples"],
            },
        ),
        "safety_controls": write_yaml(
            root / "safety_controls.yaml",
            {"schema_version": corpus["schema_version"], "controls": corpus["safety_controls"]},
        ),
    }
    return outputs


# ---------------------------------------------------------------------------
# Pilot helpers (Session 2: selection, control-runtime check, budget estimate)


def build_pilot_corpus(
    corpus: Mapping[str, Any], selection: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    ids = {str(entry["mission_id"]) for entry in selection}
    return {
        "canonical_missions": [
            mission for mission in corpus["canonical_missions"] if str(mission["mission_id"]) in ids
        ],
        "language_samples": [
            sample for sample in corpus["language_samples"] if str(sample["mission_id"]) in ids
        ],
        "safety_controls": list(corpus["safety_controls"]),
    }


def write_pilot_files(
    corpus: Mapping[str, Any],
    selection: Sequence[Mapping[str, Any]],
    *,
    corpus_dir: Path,
    selection_path: Path,
) -> dict[str, Path]:
    from .corpus import PILOT_PROFILES

    pilot = build_pilot_corpus(corpus, selection)
    outputs = {
        "canonical_missions": write_yaml(
            corpus_dir / "canonical_missions.yaml",
            {
                "schema_version": corpus["schema_version"],
                "corpus_id": f"{EXPERIMENT_ID}-pilot",
                "pilot_only": True,
                "excluded_from_final": True,
                "missions": pilot["canonical_missions"],
            },
        ),
        "language_realizations": write_yaml(
            corpus_dir / "language_realizations.yaml",
            {
                "schema_version": corpus["schema_version"],
                "pilot_only": True,
                "conditions": corpus["conditions"],
                "samples": pilot["language_samples"],
            },
        ),
        "safety_controls": write_yaml(
            corpus_dir / "safety_controls.yaml",
            {
                "schema_version": corpus["schema_version"],
                "pilot_only": True,
                "controls": pilot["safety_controls"],
            },
        ),
        "pilot_selection": write_json(
            selection_path,
            {
                "experiment_id": EXPERIMENT_ID,
                "pilot": True,
                "excluded_from_final": True,
                "profile_order": list(PILOT_PROFILES),
                "selection_rules": {
                    "walk_dominant": "max walk count, then min turn count, id tie-break",
                    "turn_dense": "max turn count, then max turn ratio, id tie-break",
                    "mixed": "mixed mission with minimal composition imbalance, id tie-break",
                    "single_step_fallback": "H1 picks one primitive per profile deterministically",
                    "result_blind": True,
                },
                "missions": [dict(entry) for entry in selection],
            },
        ),
    }
    return outputs


def run_control_runtime_stage(
    compiler_stage: Mapping[str, Any],
    *,
    runtime_protocol_path: str | Path,
    seed: int = 0,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute safety controls that produced a mission (currently the
    capability-unknown control). Grounder rejection must be zero-step."""
    runtime_protocol = load_runtime_protocol(runtime_protocol_path)
    executor = build_runtime_executor(protocol=runtime_protocol, seed=seed)
    records: list[dict[str, Any]] = []
    for control in compiler_stage.get("safety_controls", []):
        mission_doc = control.get("compiled_mission")
        if mission_doc is None or control.get("expected_grounding") is None:
            continue
        result = executor.run(mission_doc, phase="final", write_evidence=False)
        grounding = dict(result.grounding or {})
        records.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "control_id": control["control_id"],
                "kind": control.get("kind"),
                "mission_id": result.mission_id,
                "state": result.state,
                "failure_type": result.failure_type,
                "grounding_status": grounding.get("status"),
                "expected_grounding": control.get("expected_grounding"),
                "grounding_match": grounding.get("status") == control.get("expected_grounding"),
                "simulation_steps_executed": int(result.simulation_steps_executed),
                "zero_step": int(result.simulation_steps_executed) == 0,
                "mission_success": bool(result.mission_success),
                "wall_time_s": float(result.total_wall_time_s),
                "provenance": dict(provenance or {}),
            }
        )
    return {
        "experiment_id": EXPERIMENT_ID,
        "stage": "safety_control_runtime",
        "record_count": len(records),
        "records": records,
    }


def build_walltime_budget(
    *,
    oracle_stage: Mapping[str, Any],
    compiler_stage: Mapping[str, Any] | None = None,
    language_stage: Mapping[str, Any] | None = None,
    final_missions_per_horizon: int = 17,
) -> dict[str, Any]:
    buckets: dict[str, list[Mapping[str, Any]]] = {}
    for entry in oracle_stage.get("results", {}).values():
        buckets.setdefault(str(entry["horizon"]), []).append(entry)
    per_horizon: dict[str, Any] = {}
    projected_oracle_wall = 0.0
    projected_oracle_sim = 0.0
    for horizon, entries in sorted(buckets.items()):
        wall = [float(entry["total_wall_time_s"]) for entry in entries]
        sim = [float(entry["total_simulation_time_s"]) for entry in entries]
        mean_wall = statistics.fmean(wall)
        mean_sim = statistics.fmean(sim)
        scale = final_missions_per_horizon / max(1, len(entries))
        per_horizon[horizon] = {
            "pilot_runs": len(entries),
            "pilot_wall_total_s": sum(wall),
            "pilot_wall_mean_s": mean_wall,
            "pilot_wall_max_s": max(wall),
            "pilot_simulation_total_s": sum(sim),
            "projected_final_oracle_wall_s": mean_wall * final_missions_per_horizon,
            "projected_final_language_wall_max_s": mean_wall * final_missions_per_horizon * 3,
            "projected_final_oracle_simulation_s": mean_sim * final_missions_per_horizon,
        }
        projected_oracle_wall += mean_wall * final_missions_per_horizon
        projected_oracle_sim += mean_sim * final_missions_per_horizon
    payload: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "pilot_only": True,
        "assumption_final_missions_per_horizon": final_missions_per_horizon,
        "assumption_language_conditions": 3,
        "pilot_oracle": per_horizon,
        "projected_final": {
            "oracle_runs": final_missions_per_horizon * len(per_horizon),
            "language_runtime_runs_max": final_missions_per_horizon * len(per_horizon) * 3,
            "compiler_inputs": final_missions_per_horizon * len(per_horizon) * 3,
            "oracle_wall_total_s": projected_oracle_wall,
            "language_wall_total_s_max": projected_oracle_wall * 3,
            "oracle_simulation_total_s": projected_oracle_sim,
        },
    }
    if compiler_stage is not None:
        rows = list(compiler_stage.get("records", []))
        wall = [float(row["wall_time_s"]) for row in rows if row.get("wall_time_s") is not None]
        tokens = [int(row["provider_tokens"]) for row in rows if row.get("provider_tokens") is not None]
        payload["pilot_compiler"] = {
            "samples": len(rows),
            "wall_total_s": sum(wall) if wall else None,
            "wall_mean_s": statistics.fmean(wall) if wall else None,
            "wall_p95_s": None if not wall else sorted(wall)[max(0, int(round((len(wall) - 1) * 0.95)))],
            "wall_max_s": max(wall) if wall else None,
            "provider_tokens_total": sum(tokens) if tokens else None,
        }
        if wall:
            mean = statistics.fmean(wall)
            payload["projected_final"]["compiler_wall_total_s"] = (
                mean * payload["projected_final"]["compiler_inputs"]
            )
    else:
        payload["pilot_compiler"] = {"status": "not_measured_provider_unavailable"}
    if language_stage is not None:
        rows = list(language_stage.get("records", []))
        wall = [float(row["wall_time_s"]) for row in rows if row.get("wall_time_s") is not None]
        payload["pilot_language_runtime"] = {
            "runs": len(rows),
            "wall_total_s": sum(wall) if wall else None,
            "wall_mean_s": statistics.fmean(wall) if wall else None,
        }
    return payload
