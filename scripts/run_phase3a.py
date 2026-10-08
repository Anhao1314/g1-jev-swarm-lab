"""Retained Phase 3A baseline replay, independent smoke, PPO pilot and evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from g1swarm.paths import artifacts_dir
from g1swarm.transition_learning.training import DEFAULT_PROTOCOL, baseline, evaluate, smoke, train


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--output-root", type=Path,
        default=artifacts_dir() / "transition_learning_001",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("baseline", help="Replay both frozen baseline treatments before training")
    commands.add_parser("smoke", help="Independent 512-step optimizer/checkpoint/replay test")
    train_parser = commands.add_parser("train", help="Fixed-budget PPO pilot; no held-out selection")
    train_parser.add_argument("--seed", type=int, required=True)
    train_parser.add_argument("--timesteps", type=int, default=None)
    eval_parser = commands.add_parser("evaluate", help="Evaluate fixed final checkpoint(s)")
    eval_parser.add_argument("--checkpoint", nargs="+", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "baseline":
        result = baseline(args.protocol, args.output_root / "baseline")
    elif args.command == "smoke":
        result = smoke(args.protocol, args.output_root / "smoke")
    elif args.command == "train":
        result = train(
            args.seed, args.protocol, args.output_root / f"train-seed{args.seed}", args.timesteps,
        )
    else:
        result = evaluate(args.checkpoint, args.protocol, args.output_root / "evaluation")
    print(json.dumps({
        key: value for key, value in result.items()
        if key in {"status", "campaign", "seed", "num_timesteps", "optimizer_updates",
                   "runs_total", "weights_changed", "checkpoint_reload_weight_identity"}
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
