"""Run the Phase 1.2 failure-boundary campaign.

Pilot (harness gate, fixed subset)::

    python scripts/run_failure_boundary.py --campaign pilot

Frozen final campaign (writes summary + capability boundary map + risk map)::

    python scripts/run_failure_boundary.py --campaign final
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from g1swarm.boundary.capability import (
    build_capability_boundary_map,
    build_risk_map,
    validate_capability_boundary_map,
    validate_risk_map,
)
from g1swarm.boundary.runner import EXPERIMENT_ID, BoundaryRunner
from g1swarm.paths import artifacts_dir, repo_root


def _experiment_dir() -> Path:
    return repo_root() / "experiments" / "baselines" / EXPERIMENT_ID


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        default="configs/experiments/g1_failure_boundary_001.yaml",
        help="protocol config path (relative to the repository root)",
    )
    parser.add_argument("--campaign", choices=["pilot", "final"], default="pilot")
    parser.add_argument(
        "--experiments",
        nargs="*",
        default=None,
        help="subset of experiments for the final campaign (default: all)",
    )
    parser.add_argument("--summary-out", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    runner = BoundaryRunner(args.protocol, campaign=args.campaign)
    if args.campaign == "pilot":
        runner.run_pilot()
    else:
        keys = args.experiments or list(runner.protocol["experiments"])
        for key in keys:
            if key not in runner.protocol["experiments"]:
                raise SystemExit(f"unknown experiment: {key}")
            runner.run_experiment(key)

    if not args.quiet:
        for record in runner.records:
            metrics = record["metrics"]
            print(
                f"[{record['run_id']}] physical={metrics['physical_success']} "
                f"task={metrics['task_success']} "
                f"drift={metrics['lateral_drift_m']:+.3f}m "
                f"heading={metrics['heading_error_deg']:+.2f}deg "
                f"type={metrics['failure_type']}"
            )

    if args.summary_out:
        summary_path = Path(args.summary_out)
    elif args.campaign == "final":
        summary_path = _experiment_dir() / "summary.json"
    else:
        summary_path = artifacts_dir() / EXPERIMENT_ID / args.campaign / "summary.json"

    summary = runner.write_outputs(summary_path=summary_path)
    capability_path = _experiment_dir() / "capability_boundary_map.json"
    risk_path = _experiment_dir() / "risk_map.json"
    if args.campaign == "final":
        capability = build_capability_boundary_map(
            protocol=runner.protocol, summary=summary, source_commit=summary["source_commit"]
        )
        validate_capability_boundary_map(capability)
        capability_path.write_text(
            json.dumps(capability, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        risk_map = build_risk_map(
            protocol=runner.protocol, summary=summary, source_commit=summary["source_commit"]
        )
        validate_risk_map(risk_map)
        risk_path.write_text(
            json.dumps(risk_map, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    report = {
        "campaign": args.campaign,
        "runs": summary["runs_total"],
        "physical_successes": summary["physical_successes"],
        "task_successes": summary["task_successes"],
        "task_success_rate": summary["task_success_rate"],
        "failure_taxonomy": summary["failure_taxonomy"],
        "summary_path": str(summary_path),
        "capability_boundary_map": str(capability_path) if args.campaign == "final" else None,
        "risk_map": str(risk_path) if args.campaign == "final" else None,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
