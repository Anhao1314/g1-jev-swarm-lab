"""Run Phase 1.2b: distance-boundary refinement and segmentation comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from g1swarm.boundary.runner import BoundaryRunner
from g1swarm.paths import artifacts_dir, repo_root
from g1swarm.segmentation.runner import (
    EXPERIMENT_ID,
    SegmentationRunner,
    build_distance_boundary,
    build_execution_strategy_map,
    build_risk_map_v1_2b,
    build_segmentation_comparison,
    validate_comparison,
    validate_distance_boundary,
    validate_execution_strategy,
    validate_risk_map_v1_2b,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol", default="configs/experiments/g1_distance_segmentation_001.yaml"
    )
    parser.add_argument("--campaign", choices=["pilot", "final"], default="pilot")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    runner = SegmentationRunner(args.protocol, campaign=args.campaign)
    boundary_runner = BoundaryRunner(
        args.protocol, campaign=args.campaign, experiment_id=EXPERIMENT_ID
    )
    boundary_payload = boundary_runner.run_experiment("A_distance")
    if args.campaign == "pilot":
        runner.run_pilot()
        out_dir = artifacts_dir() / EXPERIMENT_ID / args.campaign
    else:
        runner.run_final()
        out_dir = repo_root() / "experiments" / "baselines" / EXPERIMENT_ID
    out_dir.mkdir(parents=True, exist_ok=True)

    boundary = build_distance_boundary(runner.protocol, boundary_payload)
    comparison = build_segmentation_comparison(runner.protocol, runner.records)
    validate_distance_boundary(boundary)
    validate_comparison(comparison)
    runner.protocol["_protocol_sha256"] = runner.protocol_sha256

    summary = runner.summarize()
    summary["boundary_last_reliable_m"] = boundary["last_reliable_m"]
    summary["boundary_first_failure_m"] = boundary["first_failure_m"]
    summary["boundary_bracket_m"] = boundary["task_boundary_bracket_m"]
    summary["comparison"] = comparison
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if not args.quiet:
        for record in boundary_runner.records:
            metrics = record["metrics"]
            print(
                f"[boundary {record['value']:g} m] physical={metrics['physical_success']} "
                f"task={metrics['task_success']} drift={metrics['lateral_drift_m']:+.3f} "
                f"heading={metrics['heading_error_deg']:+.2f} type={metrics['failure_type']}"
            )
        for record in runner.records:
            metrics = record["metrics"]
            print(
                f"[{record['run_id']}] physical={metrics['physical_success']} "
                f"task={metrics['task_success']} drift={metrics['final_lateral_drift_m']:+.3f} "
                f"heading={metrics['final_heading_error_deg']:+.2f} "
                f"stops={metrics['stops']} resets={metrics['controller_memory_resets']} "
                f"time={metrics['total_simulation_time_s']:.2f}s"
            )

    if args.campaign == "final":
        (out_dir / "distance_boundary.json").write_text(
            json.dumps(boundary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (out_dir / "segmentation_comparison.json").write_text(
            json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        risk = build_risk_map_v1_2b(
            protocol=runner.protocol,
            boundary=boundary,
            comparison=comparison,
            source_commit=summary["source_commit"],
        )
        validate_risk_map_v1_2b(risk)
        (out_dir / "risk_map_v1_2b.json").write_text(
            json.dumps(risk, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        strategy = build_execution_strategy_map(
            protocol=runner.protocol, comparison=comparison, source_commit=summary["source_commit"]
        )
        validate_execution_strategy(strategy)
        (out_dir / "execution_strategy_map.json").write_text(
            json.dumps(strategy, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    report = {
        "campaign": args.campaign,
        "boundary_runs": len(boundary_runner.records),
        "mission_runs": len(runner.records),
        "last_reliable_m": boundary["last_reliable_m"],
        "first_failure_m": boundary["first_failure_m"],
        "bracket_m": boundary["task_boundary_bracket_m"],
        "dominant_failure_modes": boundary["dominant_failure_modes"],
        "out_dir": str(out_dir),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
