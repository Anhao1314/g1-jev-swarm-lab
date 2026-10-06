"""Run the Phase 1.1 G1 skill characterization campaign.

Pilot (harness gate)::

    python scripts/run_characterization.py --campaign pilot

Frozen final campaign (writes the committed summary and competence map)::

    python scripts/run_characterization.py --campaign final
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from g1swarm.characterization.runner import EXPERIMENT_ID, CharacterizationRunner
from g1swarm.paths import artifacts_dir, repo_root


def _default_summary_path(campaign: str) -> Path:
    if campaign == "final":
        return repo_root() / "experiments" / "baselines" / EXPERIMENT_ID / "summary.json"
    return artifacts_dir() / EXPERIMENT_ID / campaign / "summary.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        default="configs/experiments/g1_skill_characterization_001.yaml",
        help="protocol config path (relative to the repository root)",
    )
    parser.add_argument("--campaign", choices=["pilot", "final"], default="pilot")
    parser.add_argument("--summary-out", default=None)
    parser.add_argument("--competence-out", default=None)
    parser.add_argument("--skip-nominal", action="store_true")
    parser.add_argument("--skip-robustness", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    runner = CharacterizationRunner(args.protocol, campaign=args.campaign)
    if not args.skip_nominal:
        runner.run_nominal_suite()
    if not args.skip_robustness:
        runner.run_robustness_suite()

    if not args.quiet:
        for record in runner.results:
            metrics = record["metrics"]
            detail = ""
            if "forward_displacement_m" in metrics:
                detail = f" displacement={metrics['forward_displacement_m']:.3f}m"
            elif "actual_yaw_change_deg" in metrics:
                detail = f" turned={metrics['actual_yaw_change_deg']:.2f}deg"
            elif "time_to_stop_threshold_s" in metrics:
                detail = f" stop_time={metrics['time_to_stop_threshold_s']}"
            print(f"[{record['run_id']}] {record['failure_type']}{detail}")

    summary_path = (
        Path(args.summary_out) if args.summary_out else _default_summary_path(args.campaign)
    )
    competence_path: Path | None = None
    if args.competence_out:
        competence_path = Path(args.competence_out)
    elif args.campaign == "final":
        competence_path = (
            repo_root() / "experiments" / "baselines" / EXPERIMENT_ID / "competence_map.json"
        )

    summary = runner.write_outputs(summary_path=summary_path, competence_path=competence_path)
    successes = sum(1 for record in runner.results if record["success"])
    report = {
        "campaign": args.campaign,
        "runs": summary["runs_total"],
        "successes": successes,
        "success_rate": (successes / summary["runs_total"]) if summary["runs_total"] else None,
        "failure_taxonomy": summary["failure_taxonomy"],
        "summary_path": str(summary_path),
        "competence_map_path": str(competence_path) if competence_path else None,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
