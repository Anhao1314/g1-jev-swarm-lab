"""Create an exclusive, prospective same-frame PPO split and protocol.

This script performs no simulation, policy loading or optimization. It binds
prior tracked evidence at the declared source anchor and refuses overwriting a
freeze. The sixteen fresh tuples are fixed in source, never selected by outcome.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import subprocess

from g1swarm.paths import repo_root
from g1swarm.frame_learning.cases import (
    TRAIN_CASES, HELDOUT_CASES, REGRESSION_CASES, REPEAT_CASE_IDS,
)
from g1swarm.transition_learning.cases import TRAIN_CASES as PILOT_TRAIN_CASES


SOURCE_ANCHOR = "1726d74111abe8084a0f509edafb8c16b1b3ad01"
DIRECTORY = "experiments/phase3a/frame_residual_learning_001"
PILOT = "experiments/phase3a/transition_learning_001"
HEADING = "experiments/phase3a/heading_alignment_strength_001"
OLD_NAMESPACES = (
    "src/g1swarm/transition_learning/", "src/g1swarm/reference_ablation/",
    "src/g1swarm/origin_ablation/", "src/g1swarm/heading_alignment/",
)
OLD_TESTS = (
    "tests/test_transition_learning", "tests/test_reference_ablation",
    "tests/test_origin_ablation", "tests/test_heading_alignment",
)
PRESERVED_KEYS = (
    "base_policy_sha256", "baseline_freeze_sha256", "baseline_protocol",
    "residual", "observation", "reward", "ppo", "torch_threads",
    "smoke_timesteps", "train_timesteps", "seeds", "checkpoint_interval",
    "checkpoint_selection", "transition_recovery_diagnostic",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()


def _old_history(root: Path) -> dict:
    resolved = _git(root, "rev-parse", SOURCE_ANCHOR + "^{commit}")
    if resolved != SOURCE_ANCHOR:
        raise RuntimeError("Historical source anchor does not resolve exactly")
    tracked = _git(root, "ls-tree", "-r", "--name-only", SOURCE_ANCHOR).splitlines()
    names = sorted(name for name in tracked if (
        name.startswith("experiments/phase3a/")
        or name.startswith(OLD_NAMESPACES)
        or (name.startswith("scripts/") and "phase3a" in Path(name).name)
        or name.startswith(OLD_TESTS)
    ))
    dirty = set(_git(root, "diff", "--name-only", SOURCE_ANCHOR).splitlines())
    changed_history = sorted(set(names) & dirty)
    if changed_history:
        raise RuntimeError(f"Prior tracked scientific files are dirty: {changed_history}")
    # .gitattributes is intentionally outside these historical namespaces;
    # adding rules for the new namespace therefore does not poison old pins.
    if not names:
        raise RuntimeError("No prior tracked history found")
    files = {}
    for name in names:
        raw = (root / name).read_bytes()
        files[name] = {"sha256": _sha(raw), "bytes": len(raw)}
    return {
        "source_anchor": SOURCE_ANCHOR,
        "scope": "Prior tracked Phase3A evidence, old namespaces, helpers and tests at the anchor; new/untracked files excluded",
        "files": files,
    }


def _signature(case, *, ignore_yaw: bool = False) -> str:
    value = {"nodes": case["nodes"]}
    if not ignore_yaw:
        value["initial_yaw_deg"] = case.get("initial_yaw_deg", 0.0)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _primary_pair(nodes) -> tuple:
    """Detect replayed task tuples even if IDs or auxiliary defaults differ."""
    parameter = {"stand": "duration_s", "walk_forward": "target_distance_m",
                 "turn": "target_angle_deg"}
    return tuple((node["skill"], float(node["parameters"][parameter[node["skill"]]])
                  if node["skill"] in parameter else None) for node in nodes)


def _case_manifest(root: Path) -> dict:
    if TRAIN_CASES is not PILOT_TRAIN_CASES:
        raise RuntimeError("Training tuple must retain the original object identity")
    if (len(TRAIN_CASES), len(HELDOUT_CASES), len(REGRESSION_CASES)) != (12, 16, 26):
        raise RuntimeError("Declared split size changed")
    families = Counter(case["transition"] for case in HELDOUT_CASES)
    if families != {"walk_to_turn": 4, "turn_to_walk": 4,
                    "walk_to_stop": 4, "stand_to_walk": 4}:
        raise RuntimeError("Fresh family grid changed")
    collections = (*TRAIN_CASES, *HELDOUT_CASES, *REGRESSION_CASES)
    ids = [case["id"] for case in collections]
    if len(set(ids)) != len(ids):
        raise RuntimeError("Split case identifiers overlap")
    history = (*TRAIN_CASES, *REGRESSION_CASES)
    full_overlap = set(map(_signature, HELDOUT_CASES)) & set(map(_signature, history))
    yaw_agnostic_overlap = {
        _signature(case, ignore_yaw=True) for case in HELDOUT_CASES
    } & {_signature(case, ignore_yaw=True) for case in history}
    # Reject fresh adjacent task tuples occurring anywhere in old sequences,
    # not only matches against two-node whole-case signatures.
    prior_pairs = {_primary_pair(case["nodes"][i:i + 2]) for case in history
                   for i in range(len(case["nodes"]) - 1)}
    pair_overlap = {_primary_pair(case["nodes"]) for case in HELDOUT_CASES} & prior_pairs
    if full_overlap or yaw_agnostic_overlap or pair_overlap:
        raise RuntimeError("Fresh physics tuples overlap original train or seen regression")
    if len(set(map(_signature, HELDOUT_CASES))) != 16:
        raise RuntimeError("Fresh full task signatures are not unique")
    known_ids = {case["id"] for case in (*HELDOUT_CASES, *REGRESSION_CASES)}
    if len(REPEAT_CASE_IDS) != 6 or not set(REPEAT_CASE_IDS) <= known_ids:
        raise RuntimeError("Repeatability membership changed")
    old_manifest = json.loads((root / PILOT / "case_manifest.json").read_text(encoding="utf-8"))
    if old_manifest["train"] != list(TRAIN_CASES):
        raise RuntimeError("Old frozen training payload differs from the live training tuple")
    return {
        "training": list(TRAIN_CASES), "heldout": list(HELDOUT_CASES),
        "regression": list(REGRESSION_CASES), "repeat_case_ids": list(REPEAT_CASE_IDS),
        "source_case_file_sha256": _sha((root / "src/g1swarm/frame_learning/cases.py").read_bytes()),
        "split_checks": {
            "original_train_tuple_identity": True,
            "original_training_payload_exact": True,
            "fresh_full_signatures_unique": 16,
            "fresh_families": dict(sorted(families.items())),
            "train_regression_full_signature_overlap": 0,
            "train_regression_overlap_ignoring_initial_yaw": 0,
            "fresh_pair_overlap_with_all_old_adjacent_node_pairs": 0,
            "no_model_or_physics_case_selection": True,
            "nominal_seed_is_not_state_randomization": True,
        },
        "scope": {
            "heldout": "New fixed transition tuples; first physics evaluation only after every final actor checkpoint is locked",
            "regression": "All old26 cases remain seen; primitives8 and sequences12m/16m are never called new held-out evidence",
            "training": "Original12 cases reused identically in every frame/seed, without new curriculum",
            "repeatability": "Four first held-out family cases plus old12m/16m; determinism only, never pooled as independent samples",
        },
    }


def _protocol(root: Path, history_raw: bytes, cases_raw: bytes) -> dict:
    pilot_path = root / PILOT / "protocol.json"
    heading_path = root / HEADING / "protocol.json"
    pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    heading = json.loads(heading_path.read_text(encoding="utf-8"))
    result = {key: copy.deepcopy(pilot[key]) for key in PRESERVED_KEYS}
    if (result["smoke_timesteps"], result["train_timesteps"], result["seeds"],
        result["checkpoint_interval"]) != (512, 8192, [11, 29], 2048):
        raise RuntimeError("Original fixed PPO budget/seed/checkpoint setting drift")
    result.update({
        "experiment_id": "frame_residual_learning_001",
        "phase": "Independent same-frame residual PPO comparison",
        "source_anchor": SOURCE_ANCHOR, "alphas": [0.0, 0.5],
        "factor": "Walking correction reference alpha only; all inherited training settings retained",
        "frame_recipe": heading["interpolation"],
        "frame_scope": heading["frame_scope"],
        "pilot_protocol_sha256": _sha(pilot_path.read_bytes()),
        "heading_protocol_sha256": _sha(heading_path.read_bytes()),
        "heading_history_manifest_sha256": heading["history_manifest_sha256"],
        "history_manifest_sha256": _sha(history_raw),
        "case_manifest_sha256": _sha(cases_raw),
        "inherited_case_manifest_sha256": pilot["case_manifest_sha256"],
        "smoke_seed": 7, "smoke_per_alpha": True,
        "paired_initialization": {
            "same_seed_actor_tensor_hash_equal_across_frames": True,
            "same_seed_case_rng_procedure": True,
            "checkpoint_zip_bytes_need_not_be_identical": True,
            "episode_counts_not_forced_equal": "Fixed decision budget is retained; all actual case exposures and interrupted tails are recorded",
        },
        "training_order": [{"alpha": alpha, "seed": seed}
                           for alpha in [0.0, 0.5] for seed in [11, 29]],
        "repeat_case_ids": list(REPEAT_CASE_IDS),
        "evaluation_schedule": {
            "seen_baseline_first": {"cases_per_alpha": 26, "alphas": 2, "records": 52},
            "independent_smoke": {"decisions_per_alpha": 512, "alphas": 2, "scored_in_primary": False},
            "train_before_fresh": {"actors": 4, "decisions_per_actor": 8192},
            "final_checkpoint_lock": "All4 final file/tensor hashes locked before the first fresh physics call, including residual-off fresh baselines",
            "post_lock_evaluation": {"fresh_residual_off": 32, "learned_fresh_and_regression": 168, "records": 200},
            "primary_totals": {"all_records": 252, "fresh_heldout": 96, "seen_regression": 156},
            "separate_repeatability": {"case_ids": list(REPEAT_CASE_IDS), "arms": 6, "records": 36, "independent_samples": False},
            "zero_and_smoke_episodes_in_primary": False,
            "heldout_cases_in_tests_preflight_smoke_reload_or_training": False,
        },
        "same_frame_comparison": "Each learned seed versus residual-off at its own alpha; never credit a cross-frame difference as PPO learning gain",
        "prospective_analysis": {
            "frozen_task_scores": "Original nominal/physical success and original strict diagnostics remain separate; no new historical success gate",
            "fresh_denominators": "16 fresh cases per arm, four per family; report old26 only as seen regression",
            "target_skill_metrics": "For fresh pairs, use the second skill for family precision/time/stability; retain unchanged-prefix and whole-case evidence",
            "directions": "Higher task/physical/strict success; lower absolute local/global lateral and heading, endpoint error, Turn translation norm, completion duration, tilt/falls; larger minimum height",
            "pareto": "Describe same-frame metric tradeoffs and seed11/29 directions separately; no aggregate weighted score or new historical PASS threshold",
            "recovery_null": "Missing/null recovery remains unavailable evidence, never zero or success",
            "negative_findings": "Keep failures, geometry tradeoffs, strict losses, reward/objective mismatch and unchanged/no-gain results",
            "optimization_return": "Training return is not held-out learning gain; differing episode composition remains visible",
            "strict_scope": "Midpoint prior qualification was nominal only; its retained16m first8m strict failure is a mandatory regression diagnostic, not erased or added retroactively to the old gate",
        },
        "no_alpha_scan": True, "no_seed_scan": True,
        "no_semantic_or_outcome_retry": True, "no_evaluation_checkpoint_selection": True,
        "no_post_evaluation_reward_observation_or_budget_change": True,
        "scope_exclusions": copy.deepcopy(pilot["scope_exclusions"]),
        "language_Runtime_gate": "BLOCKED_UNCHANGED", "Jev_or_MultiSwarm": False,
        "frozen": True,
    })
    return result


def main() -> int:
    root = repo_root()
    destination = root / DIRECTORY
    outputs = [destination / name for name in ("history_freeze.json", "case_manifest.json", "protocol.json")]
    if any(path.exists() for path in outputs):
        raise FileExistsError("A frame-learning freeze already exists; no replacement permitted")
    # Finish all read-only validation before creating any frozen output.
    history = _old_history(root)
    cases = _case_manifest(root)
    history_raw, cases_raw = _json_bytes(history), _json_bytes(cases)
    protocol_raw = _json_bytes(_protocol(root, history_raw, cases_raw))
    destination.mkdir(parents=True, exist_ok=True)
    for path, raw in zip(outputs, [history_raw, cases_raw, protocol_raw]):
        with path.open("xb") as stream:
            stream.write(raw)
    print(json.dumps({"historical_files": len(history["files"]),
                      "training_cases": 12, "fresh_heldout_cases": 16, "seen_regression_cases": 26,
                      "history_manifest_sha256": _sha(history_raw),
                      "case_manifest_sha256": _sha(cases_raw),
                      "protocol_sha256": _sha(protocol_raw)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
