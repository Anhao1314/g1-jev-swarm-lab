"""Run the Phase 2.3 long-horizon language benchmark stages.

Subcommands (see ``experiments/phase2/long_horizon_language_001/protocol.yaml``):

- ``generate``  — build the canonical corpus, language realizations and the
  safety-control set; optionally verify L1 texts against the frozen Lark.
- ``compile``   — Stage A: compile every language realization with the frozen
  selected architecture (``--scripted`` is offline harness validation only).
- ``oracle``    — run the canonical missions through the frozen runtime.
- ``runtime``   — Stage B: execute exact-IR language missions and pair them
  with the oracle runs.
- ``summarize`` — write horizon/transition/failure/latency evidence files.

The pilot must run before the protocol is frozen; final campaign evidence is
written only from a frozen protocol.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from g1swarm.config import load_yaml
from g1swarm.longhorizon import corpus as lh_corpus
from g1swarm.longhorizon import runner
from g1swarm.paths import repo_root

EXPERIMENT_DIR = repo_root() / "experiments" / "phase2" / lh_corpus.EXPERIMENT_ID
PILOT_DIR = repo_root() / "artifacts" / lh_corpus.EXPERIMENT_ID / "pilot"


def _ensure_repo_output(path: Path) -> Path:
    root = repo_root().resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise SystemExit(f"output path escapes repository: {resolved}")
    return resolved


def _source_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip() or None
    except Exception:
        return None


def _load_corpus(out_dir: Path) -> dict[str, Any]:
    missions = load_yaml(out_dir / "canonical_missions.yaml")["missions"]
    samples = load_yaml(out_dir / "language_realizations.yaml")["samples"]
    controls = load_yaml(out_dir / "safety_controls.yaml")["controls"]
    return {
        "canonical_missions": missions,
        "language_samples": samples,
        "safety_controls": controls,
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"wrote {path.relative_to(repo_root())}")


def cmd_generate(args: argparse.Namespace) -> int:
    out_dir = _ensure_repo_output(Path(args.out_dir))
    outputs = runner.generate_corpus_files(per_horizon=args.per_horizon, seed=args.seed, out_dir=out_dir)
    for path in outputs.values():
        print(f"wrote {path.relative_to(repo_root())}")
    if args.check_l1:
        corpus = _load_corpus(out_dir)
        problems = runner.verify_l1_realizations(corpus)
        if problems:
            for problem in problems[:20]:
                print(f"L1 CHECK: {problem}", file=sys.stderr)
            raise SystemExit(f"L1 self-check failed with {len(problems)} problem(s)")
        print("L1 self-check: frozen grammar reproduces every canonical mission")
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    out_dir = _ensure_repo_output(Path(args.out_dir))
    corpus = _load_corpus(out_dir)
    protocol = runner.load_protocol(args.protocol)
    if args.scripted:
        compiler = runner.ScriptedOracleCompiler(runner.scripted_answers_from_corpus(corpus))
        provenance = {
            "compiler_architecture": "scripted_oracle",
            "selection_source": "offline_harness_validation",
            "guard_version": None,
            "prompt_sha256": None,
            "protocol_sha256": protocol.get("_protocol_sha256"),
            "source_commit": _source_commit(),
        }
    else:
        compiler, provenance = runner.build_frozen_treatment(protocol)
        provenance["source_commit"] = _source_commit()
    stage = runner.run_compiler_stage(corpus, compiler, provenance=provenance)
    _write(out_dir / "compiler_results.json", stage)
    return 0


def cmd_oracle(args: argparse.Namespace) -> int:
    out_dir = _ensure_repo_output(Path(args.out_dir))
    corpus = _load_corpus(out_dir)
    stage = runner.run_oracle_stage(
        corpus, runtime_protocol_path=args.runtime_protocol, seed=args.seed
    )
    _write(out_dir / "oracle_runtime_results.json", runner.strip_internal_results(stage))
    return 0


def cmd_runtime(args: argparse.Namespace) -> int:
    out_dir = _ensure_repo_output(Path(args.out_dir))
    corpus = _load_corpus(out_dir)
    protocol = runner.load_protocol(args.protocol)
    compiler_path = out_dir / "compiler_results.json"
    if not compiler_path.is_file():
        raise SystemExit("compiler_results.json missing; run the compile stage first")
    compiler_stage = json.loads(compiler_path.read_text(encoding="utf-8"))
    if compiler_stage.get("records") and compiler_stage["records"][0].get("provenance", {}).get(
        "compiler_architecture"
    ) == "scripted_oracle" and not args.allow_scripted:
        raise SystemExit(
            "compiler_results.json was produced with --scripted; rerun the compile stage "
            "with the frozen provider before Stage B (or pass --allow-scripted for harness checks)"
        )
    oracle_stage = runner.run_oracle_stage(
        corpus, runtime_protocol_path=args.runtime_protocol, seed=args.seed
    )
    provenance = dict(compiler_stage["records"][0]["provenance"]) if compiler_stage["records"] else {}
    provenance["protocol_sha256"] = protocol.get("_protocol_sha256")
    stage = runner.run_language_stage(
        compiler_stage,
        oracle_stage,
        runtime_protocol_path=args.runtime_protocol,
        provenance=provenance,
        seed=args.seed,
    )
    _write(out_dir / "language_runtime_results.json", stage)
    return 0


def cmd_summarize(args: argparse.Namespace) -> int:
    out_dir = _ensure_repo_output(Path(args.out_dir))
    compiler_stage = json.loads((out_dir / "compiler_results.json").read_text(encoding="utf-8"))
    runtime_path = out_dir / "language_runtime_results.json"
    if runtime_path.is_file():
        runtime_stage = json.loads(runtime_path.read_text(encoding="utf-8"))
    else:
        runtime_stage = {"records": []}
    outputs = runner.summarize_stages(compiler_stage, runtime_stage, out_dir=out_dir)
    for path in outputs.values():
        print(f"wrote {path.relative_to(repo_root())}")
    return 0


def cmd_select_pilot(args: argparse.Namespace) -> int:
    corpus = lh_corpus.build_corpus(per_horizon=args.per_horizon, seed=args.seed)
    problems = lh_corpus.validate_corpus(corpus)
    if problems:
        raise SystemExit("corpus validation failed: " + "; ".join(problems[:5]))
    selection = lh_corpus.select_pilot_missions(corpus["canonical_missions"])
    pilot_dir = _ensure_repo_output(Path(args.pilot_dir))
    selection_out = _ensure_repo_output(Path(args.selection_out))
    outputs = runner.write_pilot_files(
        corpus, selection, corpus_dir=pilot_dir, selection_path=selection_out
    )
    runner.write_json(
        pilot_dir / "pilot_selection.json",
        json.loads(selection_out.read_text(encoding="utf-8")),
    )
    for path in outputs.values():
        print(f"wrote {path.relative_to(repo_root())}")
    print(f"pilot missions: {len(selection)} (excluded_from_final=true)")
    return 0


def cmd_safety_controls(args: argparse.Namespace) -> int:
    from g1swarm.simplex.structural_guard import StructuralGuard

    out_dir = _ensure_repo_output(Path(args.out_dir))
    corpus = _load_corpus(out_dir)
    guard = StructuralGuard()
    guard_rows = []
    for control in corpus["safety_controls"]:
        verdict = guard.check(str(control["text"]))
        guard_rows.append(
            {
                "control_id": control["control_id"],
                "kind": control["kind"],
                "guard_status": verdict.status.value,
                "guard_reason_code": verdict.reason_code.value if verdict.reason_code else None,
                "expected_compiler_status": control["expected_compiler_status"],
                "guard_rejects": verdict.status.value == "MALFORMED",
                "provider_calls": 0 if verdict.status.value == "MALFORMED" else None,
            }
        )
    compiler_path = out_dir / "compiler_results.json"
    compiler_stage = json.loads(compiler_path.read_text(encoding="utf-8")) if compiler_path.is_file() else None
    synthetic: dict[str, Any] = {"safety_controls": []}
    sources: dict[str, str] = {}
    for control in corpus["safety_controls"]:
        mission_doc = None
        source = None
        if compiler_stage is not None:
            record = next(
                (
                    row
                    for row in compiler_stage.get("safety_controls", [])
                    if row["control_id"] == control["control_id"] and row.get("compiled_mission")
                ),
                None,
            )
            if record is not None:
                mission_doc = record["compiled_mission"]
                source = "compiled_mission"
        if mission_doc is None and control.get("intended_mission") is not None:
            mission_doc = control["intended_mission"]
            source = "intended_mission_direct_ir"
        if mission_doc is None or control.get("expected_grounding") is None:
            continue
        sources[control["control_id"]] = source
        synthetic["safety_controls"].append(
            {
                "control_id": control["control_id"],
                "kind": control["kind"],
                "expected_grounding": control["expected_grounding"],
                "compiled_mission": mission_doc,
            }
        )
    runtime_stage = (
        runner.run_control_runtime_stage(
            synthetic, runtime_protocol_path=args.runtime_protocol, seed=args.seed
        )
        if synthetic["safety_controls"]
        else {"records": []}
    )
    for record in runtime_stage["records"]:
        record["mission_source"] = sources.get(record["control_id"])
    payload = {
        "experiment_id": lh_corpus.EXPERIMENT_ID,
        "stage": "safety_controls",
        "status": "complete" if compiler_stage is not None else "partial_provider_unavailable",
        "guard_checks": guard_rows,
        "compiler_side": (
            compiler_stage.get("safety_controls") if compiler_stage is not None else "NOT_RUN_PROVIDER_UNAVAILABLE"
        ),
        "runtime_side": runtime_stage["records"],
        "notes": [
            "malformed controls are rejected by the guard before any provider call (provider_calls=0 by construction)",
            "ambiguous/unsupported controls require the frozen provider and are NOT_RUN when it is unavailable",
            "capability-unknown runtime checks use the compiled mission when available, otherwise the intended IR (direct-IR verification; compiler half not run)",
        ],
    }
    _write(out_dir / "safety_controls.json", payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(EXPERIMENT_DIR))
    parser.add_argument("--protocol", default=str(EXPERIMENT_DIR / "protocol.yaml"))
    parser.add_argument(
        "--runtime-protocol",
        default="configs/experiments/oracle_mission_runtime_001.yaml",
    )
    parser.add_argument("--seed", type=int, default=2300)
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate")
    generate.add_argument("--per-horizon", type=int, default=20)
    generate.add_argument("--seed", type=int, default=2300)
    generate.add_argument("--check-l1", action="store_true")
    generate.set_defaults(func=cmd_generate)

    pilot_cmd = sub.add_parser("select-pilot")
    pilot_cmd.add_argument("--per-horizon", type=int, default=20)
    pilot_cmd.add_argument("--seed", type=int, default=2300)
    pilot_cmd.add_argument("--pilot-dir", default=str(PILOT_DIR))
    pilot_cmd.add_argument(
        "--selection-out", default=str(EXPERIMENT_DIR / "pilot_selection.json")
    )
    pilot_cmd.set_defaults(func=cmd_select_pilot)

    compile_cmd = sub.add_parser("compile")
    compile_cmd.add_argument("--scripted", action="store_true")
    compile_cmd.set_defaults(func=cmd_compile)

    oracle = sub.add_parser("oracle")
    oracle.set_defaults(func=cmd_oracle)

    runtime = sub.add_parser("runtime")
    runtime.add_argument("--allow-scripted", action="store_true")
    runtime.set_defaults(func=cmd_runtime)

    summarize = sub.add_parser("summarize")
    summarize.set_defaults(func=cmd_summarize)

    safety = sub.add_parser("safety-controls")
    safety.set_defaults(func=cmd_safety_controls)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
