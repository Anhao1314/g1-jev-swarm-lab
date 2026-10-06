"""Run Phase 1.3 closed-loop correction experiments.

Pilot sweeps (engineering gain selection, no final data)::

    python scripts/run_phase13.py --sweep heading
    python scripts/run_phase13.py --sweep lateral --k-heading 1.0

Final campaign (after the protocol is frozen)::

    python scripts/run_phase13.py --final
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from g1swarm.correction import (
    EXPERIMENT_ID,
    CorrectionRunner,
    build_boundary_comparison,
    build_capability_map_v1_3,
    build_correction_comparison,
    build_risk_map_v1_3,
    validate_boundary_comparison,
    validate_capability_map_v1_3,
    validate_correction_comparison,
    validate_risk_map_v1_3,
)
from g1swarm.paths import artifacts_dir, repo_root


def _experiment_dir() -> Path:
    return repo_root() / "experiments" / "baselines" / EXPERIMENT_ID


def _print_records(records: list[dict]) -> None:
    for record in records:
        metrics = record["metrics"]
        print(
            f"[{record['run_id']}] task={metrics['task_success']} "
            f"drift={metrics['lateral_drift_m']:+.3f} head={metrics['heading_error_deg']:+.2f} "
            f"rms={metrics['correction_rms']:.3f} sat={metrics['saturation_fraction']:.2f} "
            f"osc={metrics['control_oscillation_count']} t={metrics['simulation_time_s']:.2f}s "
            f"fail={metrics['failure_type']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol", default="configs/experiments/g1_closed_loop_correction_001.yaml"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sweep", choices=["heading", "lateral"])
    mode.add_argument("--final", action="store_true")
    parser.add_argument("--k-heading", type=float, default=None)
    args = parser.parse_args()

    if args.sweep is not None:
        runner = CorrectionRunner(args.protocol, campaign="pilot")
        records = runner.run_pilot_sweep(
            args.sweep,
            distances=[float(value) for value in runner.protocol["pilot"]["distances_m"]],
            k_heading=args.k_heading,
        )
        _print_records(records)
        summary = runner.write_outputs(
            summary_path=artifacts_dir() / EXPERIMENT_ID / "pilot" / f"sweep_{args.sweep}.json"
        )
        print(json.dumps({"sweep": args.sweep, "runs": summary["runs_total"]}, indent=2))
        return 0

    runner = CorrectionRunner(args.protocol, campaign="final")
    runner.run_final()
    _print_records(runner.records)
    runner.protocol["_protocol_sha256"] = runner.protocol_sha256
    summary = runner.summarize()
    summary_path = _experiment_dir() / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    comparison = build_correction_comparison(runner.protocol, summary)
    validate_correction_comparison(comparison)
    comparison["artifact_path"] = summary["artifact_path"]
    (_experiment_dir() / "correction_comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    boundary = build_boundary_comparison(runner.protocol, summary)
    validate_boundary_comparison(boundary)
    (_experiment_dir() / "boundary_comparison.json").write_text(
        json.dumps(boundary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    risk = build_risk_map_v1_3(runner.protocol, comparison, boundary, summary["source_commit"])
    validate_risk_map_v1_3(risk)
    (_experiment_dir() / "risk_map_v1_3.json").write_text(
        json.dumps(risk, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    capability = build_capability_map_v1_3(
        runner.protocol, comparison, boundary, summary["source_commit"]
    )
    validate_capability_map_v1_3(capability)
    (_experiment_dir() / "capability_map_v1_3.json").write_text(
        json.dumps(capability, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "runs": summary["runs_total"],
                "physical_successes": summary["physical_successes"],
                "task_successes": summary["task_successes"],
                "failure_taxonomy": summary["failure_taxonomy"],
                "boundary": boundary["treatments"],
                "expansion_m": boundary["reliable_distance_expansion_m"],
                "out_dir": str(_experiment_dir()),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
