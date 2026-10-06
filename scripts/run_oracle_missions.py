"""Run the Phase 2.0 oracle mission corpus through the deterministic runtime.

Structured Mission IR only: the runtime validates every mission, grounds it
against the frozen Phase 1.3 capability evidence, plans a task graph and
executes the existing skills. No language, no recovery, no replanning, no
segmentation.

Pilot (pre-flight subset, repeated for the determinism check)::

    python scripts/run_oracle_missions.py --pilot --repeat 2

Frozen benchmark (every valid mission + every rejection)::

    python scripts/run_oracle_missions.py --final

Pilot evidence stays under ``artifacts/oracle_mission_runtime_001/pilot``; the
frozen campaign writes ``benchmark_summary.json`` and ``transition_map.json``
under ``experiments/phase2/oracle_mission_runtime_001``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from g1swarm.config import load_yaml
from g1swarm.evidence import EnvironmentInfo, utc_timestamp
from g1swarm.mission import (
    CapabilityGrounder,
    LiveMissionSession,
    MissionExecutor,
    MissionValidator,
)
from g1swarm.mission.benchmark import (
    MissionRun,
    build_benchmark_summary,
    build_transition_map,
    load_corpus,
    mission_document,
    validate_benchmark_summary,
)
from g1swarm.paths import artifacts_dir, repo_root, resolve_repo_path

EXPERIMENT_ID = "oracle_mission_runtime_001"
DEFAULT_PROTOCOL = "configs/experiments/oracle_mission_runtime_001.yaml"
EXPERIMENT_DIR = ("experiments", "phase2", EXPERIMENT_ID)

# The pilot is a pre-flight: one short composition, one long composition, one
# grounding check (8 m must auto-select the closed-loop mode) and one rejection.
PILOT_MISSION_IDS = (
    "h3-walk4-turn45-stop",
    "h5-stand-walk4-turn45-walk4-stop",
    "h1-walk8",
    "n-negative-distance",
    "n-capability-unknown",
)

# Wall-clock fields are the only non-deterministic outputs of a mission run.
VOLATILE_KEYS = frozenset({"wall_time_s", "total_wall_time_s"})


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_protocol(path: str | Path) -> dict[str, Any]:
    resolved = resolve_repo_path(path)
    protocol = load_yaml(resolved)
    try:
        protocol_path = resolved.relative_to(repo_root()).as_posix()
    except ValueError:
        protocol_path = str(resolved)
    protocol["protocol_path"] = protocol_path
    protocol["_protocol_sha256"] = _sha256_file(resolved)
    return protocol


def build_grounder(protocol: Mapping[str, Any]) -> CapabilityGrounder:
    grounding = protocol["grounding"]
    evidence = grounding["evidence"]
    capability_map = evidence.get("capability_map")
    return CapabilityGrounder(
        risk_map_path=resolve_repo_path(evidence["risk_map"]),
        boundary_comparison_path=resolve_repo_path(evidence["boundary_comparison"]),
        capability_map_path=resolve_repo_path(capability_map) if capability_map else None,
        mode_preference=grounding["mode_preference"],
        historical_limits=grounding["historical"],
    )


def build_executor(
    protocol: Mapping[str, Any],
    *,
    robot_config: Mapping[str, Any],
    recorder_root: str | Path | None,
    provenance: Mapping[str, Any],
    seed: int,
) -> MissionExecutor:
    def session_factory(seed_value: int) -> LiveMissionSession:
        return LiveMissionSession(robot_config=robot_config, protocol=protocol, seed=seed_value)

    return MissionExecutor(
        validator=MissionValidator(),
        grounder=build_grounder(protocol),
        session_factory=session_factory,
        protocol=protocol,
        recorder_root=str(recorder_root) if recorder_root is not None else None,
        seed=seed,
        provenance=provenance,
    )


def select_entries(
    corpus: Mapping[str, Any], mission_ids: tuple[str, ...] | None
) -> list[tuple[dict[str, Any], bool]]:
    entries = [(entry, False) for entry in corpus["missions"]]
    entries += [(entry, True) for entry in corpus["negatives"]]
    if mission_ids is None:
        return entries
    by_id = {entry["mission_id"]: (entry, negative) for entry, negative in entries}
    missing = [mission_id for mission_id in mission_ids if mission_id not in by_id]
    if missing:
        known = ", ".join(sorted(by_id))
        raise SystemExit(f"unknown mission_id(s): {', '.join(missing)}\nknown: {known}")
    return [by_id[mission_id] for mission_id in mission_ids]


def expectation_checks(entry: Mapping[str, Any], result, *, negative: bool) -> dict[str, bool]:
    expected = entry.get("expected") or {}
    checks: dict[str, bool] = {}
    if expected.get("validation") == "VALID":
        checks["validation_valid"] = bool(result.validation.get("valid"))
    if expected.get("grounding") == "GROUNDED":
        checks["grounded"] = result.grounding.get("status") == "GROUNDED"
    if "default_mode" in expected:
        walk_modes = [
            grounding.get("execution_mode")
            for grounding in result.grounding.get("results", [])
            if grounding.get("skill") == "walk_forward"
        ]
        checks["default_mode"] = bool(walk_modes) and all(
            mode == expected["default_mode"] for mode in walk_modes
        )
    if expected.get("failure_type"):
        checks["failure_type"] = result.failure_type == expected["failure_type"]
    if negative:
        checks["zero_simulation_steps"] = result.simulation_steps_executed == 0
    return checks


def _strip_volatile(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _strip_volatile(item)
            for key, item in value.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_strip_volatile(item) for item in value]
    return value


def _node_record(node: Mapping[str, Any]) -> dict[str, Any]:
    metrics = node.get("metrics", {})
    return {
        "node_id": node["node_id"],
        "skill": node["skill"],
        "execution_mode": node["execution_mode"],
        "risk": node["risk"],
        "task_success": bool(metrics.get("task_success")),
        "physical_success": bool(metrics.get("physical_success")),
        "failure_type": metrics.get("failure_type"),
        "forward_displacement_m": metrics.get("forward_displacement_m"),
        "lateral_drift_m": metrics.get("lateral_drift_m"),
        "heading_error_deg": metrics.get("heading_error_deg"),
        "simulation_time_s": metrics.get("simulation_time_s"),
    }


def _print_run(record: Mapping[str, Any], node_records: list[dict[str, Any]]) -> None:
    modes = ",".join(mode for mode in record["grounded_modes"] if mode) or "-"
    print(
        f"[{record['mission_id']} r{record['repeat']}] state={record['state']} "
        f"success={record['mission_success']} nodes={record['completed_nodes']}/"
        f"{record['horizon_nodes']} steps={record['simulation_steps_executed']} "
        f"sim={record['total_simulation_time_s']:.2f}s modes={modes} "
        f"failure={record['failure_type']}"
    )
    for node in node_records:
        lateral = node["lateral_drift_m"]
        heading = node["heading_error_deg"]
        lateral_text = f"{lateral:+.3f}" if isinstance(lateral, (int, float)) else "n/a"
        heading_text = f"{heading:+.2f}" if isinstance(heading, (int, float)) else "n/a"
        print(
            f"    {node['node_id']} {node['skill']} mode={node['execution_mode']} "
            f"risk={node['risk']} task={node['task_success']} physical="
            f"{node['physical_success']} lateral={lateral_text} heading={heading_text}"
        )


def run_campaign(
    *,
    protocol: Mapping[str, Any],
    corpus: Mapping[str, Any],
    corpus_path: Path,
    campaign: str,
    mission_ids: tuple[str, ...] | None,
    repeats: int,
    seed: int,
) -> tuple[list[MissionRun], dict[str, Any]]:
    robot_config = load_yaml(protocol["robot_config"])
    environment = EnvironmentInfo.collect()
    corpus_sha = _sha256_file(corpus_path)
    provenance = {
        "git_commit": environment.git_commit,
        "environment": environment.to_dict(),
        "campaign": campaign,
        "corpus_path": str(corpus_path),
        "corpus_sha256": corpus_sha,
        "protocol_path": protocol.get("protocol_path"),
        "protocol_sha256": protocol.get("_protocol_sha256"),
    }
    entries = select_entries(corpus, mission_ids)
    runs: list[MissionRun] = []
    records: list[dict[str, Any]] = []
    canonical: dict[tuple[str, int], Any] = {}
    print(
        f"campaign={campaign} protocol={protocol.get('protocol_path')} "
        f"sha256={protocol.get('_protocol_sha256')[:12]} missions={len(entries)} "
        f"repeats={repeats} seed={seed}\n"
    )
    for repeat in range(1, repeats + 1):
        recorder_root = artifacts_dir() / EXPERIMENT_ID / campaign / "runs" / f"repeat-{repeat}"
        ensure_repo_output(recorder_root)
        executor = build_executor(
            protocol,
            robot_config=robot_config,
            recorder_root=recorder_root,
            provenance=provenance,
            seed=seed,
        )
        for entry, negative in entries:
            document = mission_document(entry, corpus["schema_version"])
            result = executor.run(document, phase=campaign, write_evidence=True)
            runs.append(MissionRun(entry=entry, negative=negative, result=result))
            checks = expectation_checks(entry, result, negative=negative)
            node_records = [_node_record(node) for node in result.nodes]
            record = {
                "mission_id": result.mission_id,
                "horizon": entry.get("horizon"),
                "negative": negative,
                "repeat": repeat,
                "state": result.state,
                "mission_success": result.mission_success,
                "physical_success": result.physical_success,
                "failure_type": result.failure_type,
                "failure_reason": result.failure_reason,
                "failed_node": result.failed_node,
                "completed_nodes": result.completed_nodes,
                "horizon_nodes": result.horizon,
                "simulation_steps_executed": result.simulation_steps_executed,
                "total_simulation_time_s": result.total_simulation_time_s,
                "total_wall_time_s": result.total_wall_time_s,
                "skill_invocations": result.skill_invocations,
                "transition_count": result.transition_count,
                "grounded_modes": [
                    grounding.get("execution_mode")
                    for grounding in result.grounding.get("results", [])
                ],
                "checks": checks,
                "nodes": node_records,
            }
            records.append(record)
            canonical[(result.mission_id, repeat)] = _strip_volatile(result.to_dict())
            _print_run(record, node_records)

    determinism: dict[str, Any] = {}
    if repeats > 1:
        for entry, _ in entries:
            mission_id = entry["mission_id"]
            payloads = [canonical[(mission_id, repeat)] for repeat in range(1, repeats + 1)]
            determinism[mission_id] = {
                "repeats": repeats,
                "identical": all(payload == payloads[0] for payload in payloads),
            }
    all_checks = all(
        all(check for check in record["checks"].values()) for record in records
    )
    zero_step_compliant = all(
        record["simulation_steps_executed"] == 0
        for record in records
        if record["negative"]
    )
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "campaign": campaign,
        "protocol_path": protocol.get("protocol_path"),
        "protocol_sha256": protocol.get("_protocol_sha256"),
        "corpus_path": str(corpus_path),
        "corpus_id": corpus.get("corpus_id"),
        "corpus_sha256": corpus_sha,
        "source_commit": environment.git_commit,
        "generated_at": utc_timestamp(),
        "seed": seed,
        "repeats": repeats,
        "environment": environment.to_dict(),
        "mission_ids": [entry["mission_id"] for entry, _ in entries],
        "all_expectation_checks_passed": all_checks,
        "rejections_zero_steps": zero_step_compliant,
        "determinism": determinism,
        "runs": records,
    }
    if repeats > 1:
        summary["determinism_all_identical"] = all(
            item["identical"] for item in determinism.values()
        )
    return runs, summary


def write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def ensure_repo_output(path: Path) -> Path:
    """Reject output redirection outside the repository workspace."""

    root = repo_root().resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise SystemExit(f"output path escapes repository: {resolved}")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    parser.add_argument("--corpus", default=None, help="override the protocol mission corpus")
    parser.add_argument("--missions", default=None, help="comma-separated mission_id subset")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="repeat each mission N times and record a determinism check (pilot only)",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pilot", action="store_true", help="run the pre-flight subset")
    mode.add_argument("--final", action="store_true", help="run the frozen benchmark corpus")
    args = parser.parse_args()

    if args.repeat < 1:
        raise SystemExit("--repeat must be >= 1")
    if args.final and args.repeat != 1:
        raise SystemExit("--repeat is pilot-only; the final campaign runs once per mission")
    if args.final and args.missions:
        raise SystemExit("--missions is pilot-only; final must run the complete frozen corpus")

    protocol = load_protocol(args.protocol)
    if args.final and not bool(protocol.get("frozen", False)):
        raise SystemExit("protocol is not marked frozen=True; refusing to run --final")
    corpus_path = resolve_repo_path(args.corpus or protocol["mission_corpus"])
    corpus = load_corpus(corpus_path)
    campaign = "final" if args.final else "pilot"
    mission_ids = (
        tuple(item.strip() for item in args.missions.split(",") if item.strip())
        if args.missions
        else (None if args.final else PILOT_MISSION_IDS)
    )

    runs, summary = run_campaign(
        protocol=protocol,
        corpus=corpus,
        corpus_path=corpus_path,
        campaign=campaign,
        mission_ids=mission_ids,
        repeats=args.repeat,
        seed=args.seed,
    )

    if args.final:
        expectation_failures = [
            record["mission_id"]
            for record in summary["runs"]
            if not all(record["checks"].values())
        ]
        benchmark = build_benchmark_summary(
            protocol=protocol,
            corpus=corpus,
            corpus_path=corpus_path,
            runs=runs,
            source_commit=summary["source_commit"],
            campaign="final",
        )
        benchmark["expectation_failures"] = expectation_failures
        benchmark["expectation_checks_passed"] = not expectation_failures
        benchmark["environment"] = summary["environment"]
        benchmark["seed"] = args.seed
        validate_benchmark_summary(benchmark)
        transition_map = build_transition_map(runs)
        out_dir = repo_root().joinpath(*EXPERIMENT_DIR)
        ensure_repo_output(out_dir)
        write_json(out_dir / "benchmark_summary.json", benchmark)
        write_json(out_dir / "transition_map.json", transition_map)
        write_json(out_dir / "protocol_frozen.json", protocol)
        print(
            "\n"
            + json.dumps(
                {
                    "out_dir": str(out_dir),
                    "valid": benchmark["valid"],
                    "rejections": benchmark["rejections"],
                    "mission_success_by_horizon": benchmark["mission_success_by_horizon"],
                    "failure_taxonomy": benchmark["failure_taxonomy"],
                    "expectation_failures": benchmark["expectation_failures"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if not benchmark["expectation_failures"] else 1

    out_dir = artifacts_dir() / EXPERIMENT_ID / campaign
    ensure_repo_output(out_dir)
    summary_path = write_json(out_dir / "pilot_summary.json", summary)
    print(
        "\n"
        + json.dumps(
            {
                "pilot_summary": str(summary_path),
                "all_expectation_checks_passed": summary["all_expectation_checks_passed"],
                "rejections_zero_steps": summary["rejections_zero_steps"],
                "determinism_all_identical": summary.get("determinism_all_identical"),
                "repeats": summary["repeats"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if summary["all_expectation_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
