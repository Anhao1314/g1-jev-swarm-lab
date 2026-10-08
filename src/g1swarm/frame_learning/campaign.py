"""Fixed-budget training and separate fresh/regression same-frame evaluation."""
from __future__ import annotations

import gzip
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import subprocess
import time

import torch
from stable_baselines3 import PPO
from stable_baselines3.common.logger import configure

from ..heading_alignment.experiment import verify_history as verify_heading_history
from ..paths import repo_root, resolve_repo_path
from ..reference_ablation.experiment import sha, write_new, canonical_physics
from ..transition_learning.analysis import compare_results, summarize_results
from ..transition_learning.training import (EvidenceCallback, _append_jsonl, _write_json,
    _ppo_options, _save_checkpoint, _policy, policy_weight_sha, _canonical_replay)
from .cases import TRAIN_CASES, HELDOUT_CASES, REGRESSION_CASES
from .env import FrameEnv, replay_frame, arm_label, frame_alpha

DIRECTORY = "experiments/phase3a/frame_residual_learning_001"
ARTIFACT = "artifacts/frame_residual_learning_001"


def canonical_frame(value):
    if isinstance(value, dict):
        value = {k: canonical_frame(v) for k, v in value.items()
                 if k not in ("heading_alignment_alpha", "learned_policy_configured", "policy_decision_calls", "recorded_at")}
    elif isinstance(value, list):
        value = [canonical_frame(v) for v in value]
    return canonical_physics(value)


def verify_freeze():
    root = repo_root()
    prior = verify_heading_history()
    path = root / DIRECTORY / "protocol.json"
    protocol = json.loads(path.read_text(encoding="utf-8"))
    case_path = root / DIRECTORY / "case_manifest.json"
    history_path = root / DIRECTORY / "history_freeze.json"
    if not protocol.get("frozen") or protocol["alphas"] != [0.0, 0.5]:
        raise RuntimeError("Fixed-alpha frozen protocol required")
    if sha(case_path) != protocol["case_manifest_sha256"] or sha(history_path) != protocol["history_manifest_sha256"]:
        raise RuntimeError("Frozen split/history changed")
    manifest = json.loads(case_path.read_text(encoding="utf-8"))
    if manifest["training"] != list(TRAIN_CASES) or manifest["heldout"] != list(HELDOUT_CASES) or manifest["regression"] != list(REGRESSION_CASES):
        raise RuntimeError("Live split differs from frozen cases")
    pins = json.loads(history_path.read_text(encoding="utf-8"))
    for name, pin in pins["files"].items():
        file = root / name
        if not file.is_file() or sha(file) != pin["sha256"] or file.stat().st_size != pin["bytes"]:
            raise RuntimeError(f"Historical drift: {name}")
    old_path = root / "experiments/phase3a/transition_learning_001/protocol.json"
    old = json.loads(old_path.read_text(encoding="utf-8"))
    if sha(old_path) != protocol["pilot_protocol_sha256"]:
        raise RuntimeError("Original PPO protocol changed")
    for key in ("base_policy_sha256", "baseline_freeze_sha256", "baseline_protocol", "residual", "observation",
                "reward", "ppo", "torch_threads", "smoke_timesteps", "train_timesteps", "seeds",
                "checkpoint_interval", "checkpoint_selection", "transition_recovery_diagnostic"):
        if protocol[key] != old[key]:
            raise RuntimeError(f"Original training setting changed: {key}")
    return {"history": prior, "new_history_files_verified": len(pins["files"]),
            "new_case_counts": {"training": len(TRAIN_CASES), "heldout": len(HELDOUT_CASES), "regression": len(REGRESSION_CASES)},
            "protocol_sha256": sha(path), "case_manifest_sha256": sha(case_path), "history_manifest_sha256": sha(history_path)}


def provenance():
    root = repo_root()
    checks = verify_freeze()
    p = json.loads((root / DIRECTORY / "protocol.json").read_text(encoding="utf-8"))
    result = {"code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
            **{k: checks[k] for k in ("protocol_sha256", "case_manifest_sha256", "history_manifest_sha256")},
            "pilot_protocol_sha256": p["pilot_protocol_sha256"], "base_policy_sha256": p["base_policy_sha256"],
            "baseline_freeze_sha256": p["baseline_freeze_sha256"],
            "source_hashes": {f.relative_to(root).as_posix(): sha(f) for f in sorted([
                *Path(__file__).parent.glob("*.py"), root / "scripts/run_phase3a_frame_learning.py"])},
            "package_versions": {n: importlib.metadata.version(n) for n in ("torch", "stable-baselines3", "gymnasium", "mujoco", "numpy")},
            "device": "cpu", "torch_threads": 1, "Language_Runtime": False, "Jev_or_MultiSwarm": False}
    for name, expected in result["source_hashes"].items():
        import hashlib
        committed = subprocess.check_output(["git", "show", f"HEAD:{name}"], cwd=root)
        if hashlib.sha256(committed).hexdigest() != expected:
            raise RuntimeError(f"Acquisition source is not frozen in HEAD: {name}")
    return result


def verify_acquisition_sources(common):
    for name, expected in common["source_hashes"].items():
        if sha(repo_root() / name) != expected:
            raise RuntimeError(f"Acquisition source changed: {name}")


def train_actor(output, alpha, seed, protocol, common, smoke=False):
    verify_acquisition_sources(common)
    destination = output / (f"smoke-alpha{alpha:g}" if smoke else arm_label(alpha, seed))
    destination.mkdir(exist_ok=False)
    steps = protocol["smoke_timesteps"] if smoke else protocol["train_timesteps"]
    p = {**common, "alpha": alpha, "seed": seed, "campaign": "independent_smoke" if smoke else "fixed_budget_PPO"}
    write_new(destination / "manifest.json", {"provenance": p, "protocol": protocol})
    started = time.perf_counter()
    env = None
    try:
        env = FrameEnv(list(TRAIN_CASES), alpha, seed=seed, decision_log_path=destination / "decisions.jsonl")
        model = PPO("MlpPolicy", env, **_ppo_options(protocol, seed))
        model.set_logger(configure(str(destination / "optimizer_logs"), ["json", "csv"]))
        initial = _save_checkpoint(model, destination, "initial")
        callback = EvidenceCallback(destination, env, p)
        model.learn(total_timesteps=steps, callback=callback, progress_bar=False)
        final = _save_checkpoint(model, destination, "smoke" if smoke else "final")
        changed = initial["policy_weight_sha256"] != final["policy_weight_sha256"]
        if not changed or callback.loss_count != steps // protocol["ppo"]["n_steps"]:
            raise RuntimeError("Training lacks complete real optimization evidence")
        tail = env.snapshot()
        write_new(destination / "partial_episode.json", {"record": tail, "budget_step": int(model.num_timesteps),
            "status": "BUDGET_INTERRUPTED_NOT_SCORED" if tail else "NO_IN_FLIGHT_EPISODE",
            "included_in_completed_episode_scores": False, "provenance": p})
        env.close()
        env = None
        reloaded = PPO.load(final["checkpoint"], device="cpu")
        equal = policy_weight_sha(reloaded) == final["policy_weight_sha256"]
        if not equal:
            raise RuntimeError("Checkpoint reload tensor drift")
        # Training-only replay proves saved actor behavior; no held-out case here.
        case = TRAIN_CASES[0]
        before = replay_frame(case, alpha, _policy(model), destination / "replay-before-load.jsonl")
        after = replay_frame(case, alpha, _policy(reloaded), destination / "replay-after-load.jsonl")
        replay_equal = _canonical_replay(before) == _canonical_replay(after)
        write_new(destination / "replay_check.json", {"weight_identity": equal, "replay_identity": replay_equal,
            "case_id": case["id"], "before": before, "after": after, "provenance": p})
        if not replay_equal:
            raise RuntimeError("Checkpoint physical reload drift")
        verify_freeze()
        verify_acquisition_sources(common)
        if sha(repo_root() / DIRECTORY / "protocol.json") != common["protocol_sha256"]:
            raise RuntimeError("Protocol changed during training")
        result = {"status": "COMPLETE", "alpha": alpha, "seed": seed, "num_timesteps": int(model.num_timesteps),
            "optimizer_updates": int(model._n_updates), "ppo_update_receipts": callback.loss_count,
            "completed_training_episodes": callback.episode_count, "partial_episode_retained": tail is not None,
            "partial_episode_scored": False, "initial_checkpoint": initial, "final_checkpoint": final,
            "weights_changed": changed, "checkpoint_reload_weight_identity": equal,
            "checkpoint_reload_replay_identity": replay_equal, "held_out_checkpoint_selection": False,
            "wall_time_s": time.perf_counter() - started, "provenance": p}
        write_new(destination / "training_summary.json", result)
        return result
    except Exception as exc:
        if "model" in locals() and not (destination / "failure-retained.zip").exists():
            _save_checkpoint(model, destination, "failure-retained")
        write_new(destination / "failure.json", {"status": "FAILED", "exception": type(exc).__name__, "message": str(exc), "provenance": p})
        raise
    finally:
        if env is not None:
            env.close()


def same_frame_comparisons(records):
    comparisons = {}
    for alpha in (0.0, 0.5):
        matching = [r for r in records if r["heading_alignment_alpha"] == alpha]
        adapted = [{**r, "treatment_label": "deterministic_correction" if r["checkpoint"] is None else r["treatment_label"]}
                   for r in matching]
        c = compare_results(adapted)
        c.update(baseline_treatment=arm_label(alpha), heading_alignment_alpha=alpha,
                 delta_convention="learned minus its own same-frame residual-off baseline; no cross-frame learning gain")
        comparisons[str(alpha)] = c
    return comparisons


def run_campaign(output_dir=ARTIFACT):
    root = repo_root()
    protocol = json.loads((root / DIRECTORY / "protocol.json").read_text(encoding="utf-8"))
    common = provenance()
    output = resolve_repo_path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    write_new(output / "manifest.json", {"protocol": protocol, "provenance": common, "history_before": verify_freeze()})
    records, repeats, trained = [], [], []
    def status(stage, **fields):
        event = {"stage": stage, "primary_records": len(records), "repeat_records": len(repeats),
            "completed_actors": len(trained), "provenance": common,
            "recorded_at": datetime.now(timezone.utc).isoformat(), **fields}
        _append_jsonl(output / "stage_ledger.jsonl", event)
        _write_json(output / "progress.json", event)
        print(json.dumps({"stage": stage, **fields}), flush=True)
    def evaluate_one(case, alpha, model=None, checkpoint=None, seed=None, phase="primary"):
        label = arm_label(alpha, seed)
        trace = output / "evaluation/traces" / f"{phase}--{label}--{case['id']}.jsonl"
        record = replay_frame(case, alpha, _policy(model) if model is not None else None, trace)
        record.update(phase=phase, evaluation_set="fresh_heldout" if case in HELDOUT_CASES else "seen_regression",
                      treatment_label=label, checkpoint=checkpoint, provenance=common,
                      recorded_at=datetime.now(timezone.utc).isoformat())
        (records if phase == "primary" else repeats).append(record)
        _append_jsonl(output / "evaluation/results.jsonl", record)
        return record
    try:
        status("seen_baseline_replay")
        prior_path = root / "experiments/phase3a/heading_alignment_strength_001/evidence/results.jsonl.gz"
        old = [json.loads(x) for x in gzip.decompress(prior_path.read_bytes()).decode().splitlines()]
        anchors = {(r["case_id"], r["heading_alignment_alpha"]): r for r in old if r["phase"] == "primary"}
        anchor_checks = []
        for alpha in protocol["alphas"]:
            for case in REGRESSION_CASES:
                record = evaluate_one(case, alpha)
                match = canonical_frame(record) == canonical_frame(anchors[(case["id"], alpha)])
                anchor_checks.append({"case_id": case["id"], "alpha": alpha, "passed": match})
                if not match:
                    raise RuntimeError("Same-frame deterministic historical anchor changed")
        for alpha in protocol["alphas"]:
            status("independent_smoke", alpha=alpha)
            train_actor(output, alpha, 7, protocol, common, smoke=True)
        for alpha in protocol["alphas"]:
            for seed in protocol["seeds"]:
                status("training", alpha=alpha, seed=seed)
                trained.append(train_actor(output, alpha, seed, protocol, common))
                status("actor_complete", alpha=alpha, seed=seed)
        # Lock every final tensor/file before the first fresh physics evaluation.
        lock = [{"alpha": r["alpha"], "seed": r["seed"], "checkpoint": r["final_checkpoint"]} for r in trained]
        write_new(output / "final_checkpoint_lock.json", {"all_actors_complete": True, "actors": lock, "provenance": common,
            "locked_at": datetime.now(timezone.utc).isoformat()})
        status("fresh_heldout_baselines")
        for alpha in protocol["alphas"]:
            for case in HELDOUT_CASES:
                evaluate_one(case, alpha)
        status("fixed_final_evaluation")
        for receipt in lock:
            cp = receipt["checkpoint"]
            if sha(Path(cp["checkpoint"])) != cp["file_sha256"]:
                raise RuntimeError("Final checkpoint changed")
            model = PPO.load(cp["checkpoint"], device="cpu")
            if policy_weight_sha(model) != cp["policy_weight_sha256"]:
                raise RuntimeError("Final checkpoint tensor changed")
            for case in (*HELDOUT_CASES, *REGRESSION_CASES):
                evaluate_one(case, receipt["alpha"], model, cp, receipt["seed"])
        status("deterministic_repeatability")
        repeat_ids = set(protocol["repeat_case_ids"])
        repeat_cases = [c for c in (*HELDOUT_CASES, *REGRESSION_CASES) if c["id"] in repeat_ids]
        for alpha in protocol["alphas"]:
            for case in repeat_cases:
                evaluate_one(case, alpha, phase="repeatability")
        for receipt in lock:
            model = PPO.load(receipt["checkpoint"]["checkpoint"], device="cpu")
            for case in repeat_cases:
                evaluate_one(case, receipt["alpha"], model, receipt["checkpoint"], receipt["seed"], phase="repeatability")
        primary_index = {(r["treatment_label"], r["case_id"]): r for r in records}
        identity = [{"case_id": r["case_id"], "arm": r["treatment_label"],
            "passed": _canonical_replay({k:v for k,v in r.items() if k not in ("phase", "recorded_at")}) == _canonical_replay(
                {k:v for k,v in primary_index[(r["treatment_label"],r["case_id"])].items() if k not in ("phase", "recorded_at")})} for r in repeats]
        if len(records) != 252 or len(repeats) != 36 or not all(v["passed"] for v in identity):
            raise RuntimeError("Evaluation membership/repeatability drift")
        if sha(root / DIRECTORY / "protocol.json") != common["protocol_sha256"]:
            raise RuntimeError("Protocol drift after evaluation")
        history = verify_freeze()
        verify_acquisition_sources(common)
        write_new(output / "evaluation/summary.json", summarize_results(records))
        write_new(output / "evaluation/same_frame_comparison.json", same_frame_comparisons(records))
        completion = {"status": "COMPLETE", "primary_runs": len(records), "repeatability_runs": len(repeats),
            "actors": trained, "anchor_identity": anchor_checks, "repeatability_identity": identity,
            "history_after": history, "provenance": common, "final_checkpoint_selection": "fixed_final_only"}
        write_new(output / "completion.json", completion)
        status("COMPLETE")
        return {"status": "COMPLETE", "primary_runs": len(records), "repeatability_runs": len(repeats), "actors": len(trained)}
    except Exception as exc:
        write_new(output / "failure.json", {"status": "FAILED", "exception": type(exc).__name__, "message": str(exc),
            "primary_records": len(records), "actors_complete": len(trained), "provenance": common})
        raise
