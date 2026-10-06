"""Pilot runs for individual Phase 1 skills (currently: turn).

Stand and walk are exercised by Baseline-001; this entry point exists for the
remaining Phase 1 target skill so that each skill has its own measured status
instead of an assumed one.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from g1swarm.config import build_controller, build_simulation, load_yaml
from g1swarm.evidence import RunRecorder
from g1swarm.paths import repo_root, resolve_repo_path
from g1swarm.skills import SkillContext, SkillRequest, SkillRouter, StandSkill, StopSkill, TurnSkill

from exp_common import manifest_for


def run_turn(robot: dict, config: dict, seed: int) -> dict:
    skill_params = config.get("turn", {})
    run_id = f"{config.get('experiment_id', 'g1_turn_pilot')}-run-{seed:03d}"
    simulation = build_simulation(robot, seed=seed)
    controller = build_controller(robot)
    router = SkillRouter([StandSkill(), TurnSkill(), StopSkill()])
    context = SkillContext(
        simulation=simulation,
        controller=controller,
        robot_config=robot,
        max_steps=int(round(60.0 / simulation.timestep)),
        seed=seed,
    )
    recorder = RunRecorder(
        "skill-pilot",
        run_id,
        manifest=manifest_for(
            experiment_id=str(config.get("experiment_id", "g1_turn_pilot")),
            run_id=run_id,
            task=str(config.get("task", "turn pilot")),
            robot=robot,
            experiment=config,
            seed=seed,
        ),
    )
    started = time.perf_counter()
    simulation.reset(seed=seed)
    stand = router.execute(
        SkillRequest("stand", {"duration_s": float(skill_params.get("stand_duration_s", 1.5))}),
        context,
    )
    recorder.log_event("skill_result", stand.to_dict())
    turn = router.execute(SkillRequest("turn", dict(skill_params)), context)
    recorder.log_event("skill_result", turn.to_dict())
    stop = router.execute(SkillRequest("stop", {}), context)
    recorder.log_event("skill_result", stop.to_dict())
    success = bool(stand.ok and turn.ok)
    metrics = {
        "run_id": run_id,
        "seed": seed,
        "success": success,
        "completion_status": "SUCCESS" if success else "FAILURE",
        "elapsed_wall_time_s": time.perf_counter() - started,
        "turned_deg": turn.metrics.get("turned_deg"),
        "heading_error_deg": turn.metrics.get("heading_error_deg"),
        "fallen": bool(stand.metrics.get("fallen") or turn.metrics.get("fallen")),
        "stand": stand.to_dict(),
        "turn": turn.to_dict(),
        "stop": stop.to_dict(),
    }
    recorder.finish({"status": metrics["completion_status"], "success": success}, metrics)
    simulation.close()
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", choices=["turn"], default="turn")
    parser.add_argument("--config", default="configs/experiments/g1_turn_pilot.yaml")
    parser.add_argument("--seeds", type=int, nargs="*", default=None)
    parser.add_argument("--summary-out", default=None)
    args = parser.parse_args()
    config = load_yaml(args.config)
    robot = load_yaml(config["robot"])
    seeds = args.seeds if args.seeds is not None else list(config.get("seeds", [0]))
    results = [run_turn(robot, config, int(seed)) for seed in seeds]
    for result in results:
        print(
            f"[{result['run_id']}] status={result['completion_status']}"
            f" turned={result['turned_deg']}deg error={result['heading_error_deg']}deg"
        )
    successes = sum(1 for result in results if result["success"])
    summary = {
        "experiment_id": str(config.get("experiment_id", "g1_turn_pilot")),
        "task": str(config.get("task", "turn pilot")),
        "runs": len(results),
        "successes": successes,
        "success_rate": (successes / len(results)) if results else None,
        "turned_mean_deg": (
            sum(float(r["turned_deg"] or 0.0) for r in results) / len(results) if results else None
        ),
        "falls": sum(1 for result in results if result["fallen"]),
        "artifact_path": str(Path("artifacts") / "skill-pilot"),
    }
    out_path = (
        resolve_repo_path(args.summary_out)
        if args.summary_out
        else repo_root() / "experiments" / "baselines" / "g1_turn_pilot" / "summary.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"summary written to {out_path}")
    return 0 if successes == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
