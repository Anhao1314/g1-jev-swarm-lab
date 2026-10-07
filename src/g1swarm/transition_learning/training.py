"""Small, retained PPO campaigns for the Phase 3A transition pilot.

Only the outer residual actor is optimized. The environment owns the frozen
locomotion policy, physics, skill contracts and deterministic correction.
Evaluation always uses the final fixed checkpoint; it never selects a model
using held-out scores. Every campaign directory is created exclusively.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.logger import configure

from ..paths import artifacts_dir, repo_root, resolve_repo_path
from .analysis import compare_results, summarize_results
from .cases import EVAL_CASES, PRIMITIVE_CASES, SEQUENCE_CASES, TRAIN_CASES
from .env import TransitionEnv, replay_case

DEFAULT_PROTOCOL = "experiments/phase3a/transition_learning_001/protocol.json"
BASELINE_FREEZE = "experiments/phase3a/transition_learning_001/baseline_freeze.json"
CASE_MANIFEST = "experiments/phase3a/transition_learning_001/case_manifest.json"


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _append_jsonl(path: Path, payload: Any) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(payload, sort_keys=True, default=_json_default, allow_nan=False)
            + "\n"
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_baseline_freeze() -> dict[str, Any]:
    """Read-only verification of all archived baseline source/asset byte pins."""
    freeze_path = resolve_repo_path(BASELINE_FREEZE)
    manifest = json.loads(freeze_path.read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    if not files:
        raise ValueError("baseline freeze manifest has no byte-pinned files")
    failures: list[dict[str, Any]] = []
    for relative_path, expected in files.items():
        path = resolve_repo_path(relative_path)
        if not path.is_file():
            failures.append({"path": relative_path, "reason": "MISSING"})
            continue
        observed = {"sha256": _file_sha(path), "bytes": path.stat().st_size}
        if observed["sha256"] != expected["sha256"] or observed["bytes"] != expected["bytes"]:
            failures.append({"path": relative_path, "expected": expected, "observed": observed})
    if failures:
        raise RuntimeError(f"frozen baseline drift: {json.dumps(failures, sort_keys=True)}")
    return {
        "baseline_freeze_sha256": _file_sha(freeze_path),
        "baseline_files_verified": len(files),
        "baseline_drift": False,
    }


def verify_case_manifest(protocol: dict[str, Any]) -> dict[str, Any]:
    """Bind the live case collections to the independently frozen split file."""
    path = resolve_repo_path(protocol.get("case_manifest_path", CASE_MANIFEST))
    expected_sha = protocol.get("case_manifest_sha256")
    observed_sha = _file_sha(path)
    if not expected_sha or observed_sha != expected_sha:
        raise RuntimeError("frozen case manifest hash mismatch")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    groups = manifest.get("cases", manifest.get("case_sets", manifest))
    live_groups = {
        "train": TRAIN_CASES,
        "eval": EVAL_CASES,
        "primitive": PRIMITIVE_CASES,
        "sequence": SEQUENCE_CASES,
    }
    aliases = {
        "train": ("train", "train_cases", "TRAIN_CASES", "training"),
        "eval": ("eval", "eval_cases", "EVAL_CASES", "evaluation"),
        "primitive": ("primitive", "primitive_cases", "PRIMITIVE_CASES", "primitives"),
        "sequence": ("sequence", "sequence_cases", "SEQUENCE_CASES", "sequences"),
    }
    verified: dict[str, int] = {}
    for name, cases in live_groups.items():
        key = next((alias for alias in aliases[name] if alias in groups), None)
        if key is None:
            raise RuntimeError(f"frozen case manifest is missing {name} split")
        serialized_live = json.loads(json.dumps(list(cases), default=_json_default))
        if groups[key] != serialized_live:
            raise RuntimeError(f"live {name} case collection differs from frozen manifest")
        verified[name] = len(cases)
    return {"case_manifest_sha256": observed_sha, "verified_case_counts": verified}


def policy_weight_sha(model: PPO) -> str:
    """Hash actor/critic tensor content, independent of checkpoint ZIP dates."""
    digest = hashlib.sha256()
    for name, tensor in sorted(model.policy.state_dict().items()):
        values = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(values.dtype).encode("ascii"))
        digest.update(json.dumps(list(values.shape)).encode("ascii"))
        digest.update(values.numpy().tobytes())
    return digest.hexdigest()


def _case_id(case: Any, index: int) -> str:
    if isinstance(case, dict):
        value = case.get("case_id", case.get("id", f"case-{index:03d}"))
    else:
        value = getattr(case, "case_id", getattr(case, "id", f"case-{index:03d}"))
    # IDs are evidence names, not an arbitrary filesystem path.
    result = str(value)
    if not result or any(character in result for character in '/\\:*?"<>|'):
        raise ValueError(f"invalid case identifier: {result!r}")
    return result


def _provenance(protocol_path: Path, protocol: dict[str, Any]) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root(), capture_output=True, text=True,
        check=True,
    ).stdout.strip()
    source_dir = Path(__file__).resolve().parent
    return {
        "protocol_sha256": _file_sha(protocol_path),
        "protocol_path": str(protocol_path),
        "code_commit": commit,
        "source_hashes": {
            str(path.relative_to(repo_root())): _file_sha(path)
            for path in sorted([*source_dir.glob("*.py"), repo_root() / "scripts/run_phase3a.py"])
        },
        "baseline_provenance": {
            "base_policy_sha256": protocol.get("base_policy_sha256"),
            "baseline_protocol": protocol.get("baseline_protocol"),
            "source_anchor": protocol.get("source_anchor"),
        },
        "torch_version": torch.__version__,
        "package_versions": {
            name: importlib.metadata.version(name)
            for name in ("stable-baselines3", "gymnasium", "mujoco", "numpy")
        },
        "device": "cpu",
        "torch_threads": 1,
        "held_out_checkpoint_selection": False,
        "language_compiler_invocations": 0,
    }


def _prepare(
    protocol_path: str | Path, output_dir: str | Path, campaign: str,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    path = resolve_repo_path(protocol_path)
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if protocol.get("frozen") is not True:
        raise ValueError("training requires a frozen pilot protocol")
    baseline_check = verify_baseline_freeze()
    if (
        not protocol.get("baseline_freeze_sha256")
        or baseline_check["baseline_freeze_sha256"] != protocol["baseline_freeze_sha256"]
    ):
        raise RuntimeError("baseline freeze manifest differs from frozen protocol pin")
    case_check = verify_case_manifest(protocol)
    destination = resolve_repo_path(output_dir)
    destination.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    provenance = _provenance(path, protocol)
    provenance.update(baseline_check)
    provenance.update(case_check)
    manifest = {
        "campaign": campaign,
        "started_at": _utc_now(),
        "provenance": provenance,
        "protocol": protocol,
        "output_dir": str(destination),
    }
    _write_json(destination / "manifest.json", manifest)
    return path, destination, protocol, provenance


def _ppo_options(protocol: dict[str, Any], seed: int) -> dict[str, Any]:
    supplied = dict(protocol.get("ppo", {}))
    options = {
        "learning_rate": float(supplied.get("learning_rate", supplied.get("lr", 3e-4))),
        "n_steps": int(supplied.get("n_steps", 512)),
        "batch_size": int(supplied.get("batch_size", 64)),
        "n_epochs": int(supplied.get("n_epochs", 5)),
        "gamma": float(supplied.get("gamma", 0.99)),
        "gae_lambda": float(supplied.get("gae_lambda", 0.95)),
        "clip_range": float(supplied.get("clip_range", 0.2)),
        "ent_coef": float(supplied.get("ent_coef", supplied.get("entropy", 0.0))),
        "policy_kwargs": supplied.get("policy_kwargs", {
            "net_arch": supplied.get("net_arch", [64, 64]),
        }),
        "device": "cpu",
        "seed": seed,
        "verbose": 0,
    }
    if options["n_steps"] % options["batch_size"]:
        raise ValueError("PPO batch size must divide the frozen rollout size")
    return options


def _save_checkpoint(model: PPO, directory: Path, name: str) -> dict[str, Any]:
    path = directory / f"{name}.zip"
    if path.exists():
        raise FileExistsError(path)
    model.save(path)
    receipt = {
        "checkpoint": str(path),
        "file_sha256": _file_sha(path),
        "policy_weight_sha256": policy_weight_sha(model),
        "num_timesteps": int(model.num_timesteps),
        "optimizer_updates": int(model._n_updates),
        "saved_at": _utc_now(),
    }
    _append_jsonl(directory / "checkpoints.jsonl", receipt)
    return receipt


class EvidenceCallback(BaseCallback):
    """Persist episode receipts and post-update optimization evidence."""

    def __init__(self, output_dir: Path, env: TransitionEnv, provenance: dict[str, Any]):
        super().__init__()
        self.output_dir = output_dir
        self.env = env
        self.provenance = provenance
        self.episode_count = 0
        self.loss_count = 0
        self._last_logged_update = 0
        self._saved_steps: set[int] = set()

    def _log_update(self) -> None:
        updates = int(self.model._n_updates)
        if updates <= self._last_logged_update:
            return
        losses = {
            key: float(value)
            for key, value in self.model.logger.name_to_value.items()
            if key.startswith("train/") and isinstance(value, (int, float, np.number))
        }
        if not losses or not all(math.isfinite(value) for value in losses.values()):
            raise RuntimeError("PPO update has missing or non-finite optimization evidence")
        _append_jsonl(self.output_dir / "ppo_updates.jsonl", {
            "num_timesteps": int(self.model.num_timesteps),
            "optimizer_updates": updates,
            "policy_weight_sha256": policy_weight_sha(self.model),
            "losses": losses,
            "provenance": self.provenance,
        })
        self._last_logged_update = updates
        self.loss_count += 1

    def _on_rollout_start(self) -> None:
        # on_rollout_end precedes PPO.train(); the following rollout start sees
        # the completed previous update and its logger fields.
        self._log_update()
        step = int(self.model.num_timesteps)
        if step and step % 2048 == 0 and step not in self._saved_steps:
            _save_checkpoint(self.model, self.output_dir, f"step-{step:08d}")
            self._saved_steps.add(step)

    def _on_step(self) -> bool:
        for done, info in zip(self.locals.get("dones", []), self.locals.get("infos", [])):
            if done:
                record = info.get("episode_record", getattr(self.env, "last_record", None))
                if record is None:
                    raise RuntimeError("terminal transition episode has no evidence receipt")
                self.episode_count += 1
                _append_jsonl(self.output_dir / "episodes.jsonl", {
                    "episode_index": self.episode_count,
                    "training_step": int(self.model.num_timesteps),
                    "record": record,
                    "provenance": self.provenance,
                })
        return True

    def _on_training_end(self) -> None:
        self._log_update()


def _policy(model: PPO) -> Callable[[np.ndarray], np.ndarray]:
    def predict(observation: np.ndarray) -> np.ndarray:
        action, _ = model.predict(observation, deterministic=True)
        return np.asarray(action, dtype=np.float32)
    return predict


def _canonical_replay(value: Any) -> Any:
    """Drop wall-clock and path metadata; retain every physical/reward metric."""
    if isinstance(value, dict):
        return {
            key: _canonical_replay(item)
            for key, item in value.items()
            if "wall" not in key
            and key not in {"generated_at", "started_at", "finished_at", "trace_path", "output_path"}
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_replay(item) for item in value]
    return value


def _train_campaign(
    *, seed: int, protocol_path: str | Path, output_dir: str | Path,
    smoke: bool, timesteps: int | None = None,
) -> dict[str, Any]:
    path, destination, protocol, provenance = _prepare(
        protocol_path, output_dir, "independent_smoke" if smoke else "ppo_pilot",
    )
    supplied = protocol.get("ppo", {})
    frozen_steps = int(
        protocol.get("smoke_timesteps", supplied.get("smoke_timesteps", 512))
        if smoke else protocol.get("train_timesteps", supplied.get("total_timesteps", 8192))
    )
    if timesteps is not None and int(timesteps) != frozen_steps:
        raise ValueError(f"requested timesteps differ from frozen pilot budget {frozen_steps}")
    if frozen_steps % int(supplied.get("n_steps", 512)):
        raise ValueError("pilot budget must contain a whole number of PPO rollouts")
    env: TransitionEnv | None = None
    started = time.perf_counter()
    try:
        env = TransitionEnv(
            cases=list(TRAIN_CASES), treatment="learned", seed=seed,
            decision_log_path=destination / "decisions.jsonl",
        )
        model = PPO("MlpPolicy", env, **_ppo_options(protocol, seed))
        model.set_logger(configure(str(destination / "optimizer_logs"), ["json", "csv"]))
        initial = _save_checkpoint(model, destination, "initial")
        callback = EvidenceCallback(destination, env, provenance)
        model.learn(total_timesteps=frozen_steps, callback=callback, progress_bar=False)
        final = _save_checkpoint(model, destination, "smoke" if smoke else "final")
        weights_changed = initial["policy_weight_sha256"] != final["policy_weight_sha256"]
        if not weights_changed or callback.loss_count == 0:
            raise RuntimeError("PPO did not produce retained parameter-update evidence")
        partial_episode = env.snapshot()
        _write_json(destination / "partial_episode.json", {
            "record": partial_episode,
            "budget_step": int(model.num_timesteps),
            "status": "BUDGET_INTERRUPTED_NOT_SCORED" if partial_episode else "NO_IN_FLIGHT_EPISODE",
            "included_in_completed_episode_scores": False,
            "provenance": provenance,
        })
        # Close the live training worker before loading/replaying fresh worlds.
        env.close()
        env = None
        reloaded = PPO.load(final["checkpoint"], device="cpu")
        reload_equal = policy_weight_sha(reloaded) == final["policy_weight_sha256"]
        if not reload_equal:
            raise RuntimeError("saved checkpoint does not reproduce trained tensor values")
        replay_check: dict[str, Any] = {"weight_identity": reload_equal}
        if smoke:
            case = list(TRAIN_CASES)[0]
            before = replay_case(
                case, "learned", policy=_policy(model),
                trace_path=destination / "replay-before-load.jsonl",
            )
            after = replay_case(
                case, "learned", policy=_policy(reloaded),
                trace_path=destination / "replay-after-load.jsonl",
            )
            replay_equal = _canonical_replay(before) == _canonical_replay(after)
            replay_check.update({
                "case_id": _case_id(case, 0), "replay_identity": replay_equal,
                "before": before, "after": after,
            })
            if not replay_equal:
                _write_json(destination / "replay_check.json", replay_check)
                raise RuntimeError("checkpoint reload changes deterministic physical replay")
        _write_json(destination / "replay_check.json", replay_check)
        if _file_sha(path) != provenance["protocol_sha256"]:
            raise RuntimeError("frozen protocol changed during campaign")
        baseline_check = verify_baseline_freeze()
        verify_case_manifest(protocol)
        if baseline_check["baseline_freeze_sha256"] != provenance["baseline_freeze_sha256"]:
            raise RuntimeError("baseline freeze manifest changed during campaign")
        result = {
            "status": "COMPLETE",
            "campaign": "independent_smoke" if smoke else "ppo_pilot",
            "seed": seed,
            "num_timesteps": int(model.num_timesteps),
            "optimizer_updates": int(model._n_updates),
            "ppo_update_receipts": callback.loss_count,
            "completed_training_episodes": callback.episode_count,
            "partial_episode_retained": partial_episode is not None,
            "partial_episode_scored": False,
            "initial_checkpoint": initial,
            "final_checkpoint": final,
            "weights_changed": weights_changed,
            "checkpoint_reload_weight_identity": reload_equal,
            "baseline_drift": baseline_check["baseline_drift"],
            "baseline_files_verified": baseline_check["baseline_files_verified"],
            "held_out_checkpoint_selection": False,
            "wall_time_s": time.perf_counter() - started,
            "provenance": provenance,
            "finished_at": _utc_now(),
        }
        _write_json(destination / "training_summary.json", result)
        return result
    except Exception as exc:
        _write_json(destination / "failure.json", {
            "status": "FAILED", "exception_type": type(exc).__name__,
            "message": str(exc), "provenance": provenance, "finished_at": _utc_now(),
        })
        raise
    finally:
        if env is not None:
            env.close()


def smoke(
    protocol_path: str | Path = DEFAULT_PROTOCOL, output_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _train_campaign(
        seed=7, protocol_path=protocol_path,
        output_dir=output_dir or artifacts_dir() / "transition_learning_001" / "smoke",
        smoke=True,
    )


def train(
    seed: int, protocol_path: str | Path = DEFAULT_PROTOCOL,
    output_dir: str | Path | None = None, timesteps: int | None = None,
) -> dict[str, Any]:
    protocol = json.loads(resolve_repo_path(protocol_path).read_text(encoding="utf-8"))
    seeds = protocol.get("seeds", protocol.get("ppo", {}).get("seeds", [11, 29]))
    if int(seed) not in list(seeds):
        raise ValueError(f"seed {seed} is outside frozen pilot seeds {seeds}")
    return _train_campaign(
        seed=int(seed), protocol_path=protocol_path,
        output_dir=output_dir or artifacts_dir() / "transition_learning_001" / f"train-seed{seed}",
        smoke=False, timesteps=timesteps,
    )


def _evaluation_cases() -> list[tuple[str, Any]]:
    return (
        [("unseen_transition", case) for case in EVAL_CASES]
        + [("primitive_regression", case) for case in PRIMITIVE_CASES]
        + [("unseen_sequence", case) for case in SEQUENCE_CASES]
    )


def _run_evaluation(
    *, protocol_path: str | Path, output_dir: str | Path,
    checkpoints: list[str | Path], include_baselines: bool,
) -> dict[str, Any]:
    path, destination, protocol, provenance = _prepare(
        protocol_path, output_dir, "frozen_baseline_replay" if include_baselines else "fixed_final_evaluation",
    )
    records: list[dict[str, Any]] = []
    treatments: list[tuple[str, str, Callable | None, dict | None]] = []
    if include_baselines:
        for treatment in ("frozen_baseline", "deterministic_correction"):
            treatments.append((treatment, treatment, None, None))
    for checkpoint in checkpoints:
        resolved = resolve_repo_path(checkpoint)
        expected_steps = int(protocol.get("train_timesteps", 8192))
        summary_path = resolved.parent / "training_summary.json"
        if resolved.name != "final.zip" or not summary_path.is_file():
            raise ValueError("held-out evaluation requires a retained fixed final pilot checkpoint")
        training_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if (
            training_summary.get("status") != "COMPLETE"
            or training_summary.get("num_timesteps") != expected_steps
            or training_summary["provenance"]["protocol_sha256"] != provenance["protocol_sha256"]
            or training_summary["final_checkpoint"]["file_sha256"] != _file_sha(resolved)
        ):
            raise ValueError("final checkpoint provenance/budget differs from frozen pilot")
        model = PPO.load(resolved, device="cpu")
        receipt = {
            "path": str(resolved), "file_sha256": _file_sha(resolved),
            "policy_weight_sha256": policy_weight_sha(model),
            "num_timesteps": int(model.num_timesteps),
        }
        label = resolved.parent.name
        treatments.append((label, "learned", _policy(model), receipt))
    if not treatments:
        raise ValueError("evaluation requires at least one treatment")
    identifiers: set[str] = set()
    try:
        for label, treatment, predict, receipt in treatments:
            for index, (evaluation_set, case) in enumerate(_evaluation_cases()):
                case_id = _case_id(case, index)
                name = f"{label}--{case_id}"
                if name in identifiers:
                    raise ValueError(f"duplicate evaluation evidence name: {name}")
                identifiers.add(name)
                trace_dir = destination / "traces"
                trace_dir.mkdir(exist_ok=True)
                record = replay_case(
                    case, treatment, policy=predict, trace_path=trace_dir / f"{name}.jsonl",
                )
                record = {
                    **record,
                    "evaluation_set": evaluation_set,
                    "treatment_label": label,
                    "checkpoint": receipt,
                    "provenance": provenance,
                }
                records.append(record)
                _append_jsonl(destination / "results.jsonl", record)
        if _file_sha(path) != provenance["protocol_sha256"]:
            raise RuntimeError("frozen protocol changed during evaluation")
        baseline_check = verify_baseline_freeze()
        verify_case_manifest(protocol)
        if baseline_check["baseline_freeze_sha256"] != provenance["baseline_freeze_sha256"]:
            raise RuntimeError("baseline freeze manifest changed during evaluation")
        result = {
            "status": "COMPLETE", "records": records, "runs_total": len(records),
            "baseline_drift": baseline_check["baseline_drift"],
            "baseline_files_verified": baseline_check["baseline_files_verified"],
            "provenance": provenance, "finished_at": _utc_now(),
        }
        _write_json(destination / "results_summary.json", summarize_results(records))
        comparison_records = list(records)
        if not include_baselines:
            baseline_results = destination.parent / "baseline" / "results.jsonl"
            if baseline_results.is_file():
                baseline_records = [
                    json.loads(line) for line in baseline_results.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                if any(
                    record.get("provenance", {}).get("protocol_sha256")
                    != provenance["protocol_sha256"] for record in baseline_records
                ):
                    raise RuntimeError("baseline comparison evidence uses a different frozen protocol")
                comparison_records = baseline_records + comparison_records
        _write_json(destination / "comparison.json", compare_results(comparison_records))
        _write_json(destination / "evaluation_summary.json", result)
        return result
    except Exception as exc:
        _write_json(destination / "failure.json", {
            "status": "FAILED", "completed_runs": len(records),
            "exception_type": type(exc).__name__, "message": str(exc),
            "provenance": provenance, "finished_at": _utc_now(),
        })
        raise


def baseline(
    protocol_path: str | Path = DEFAULT_PROTOCOL, output_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run_evaluation(
        protocol_path=protocol_path,
        output_dir=output_dir or artifacts_dir() / "transition_learning_001" / "baseline",
        checkpoints=[], include_baselines=True,
    )


def evaluate(
    checkpoints: list[str | Path], protocol_path: str | Path = DEFAULT_PROTOCOL,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _run_evaluation(
        protocol_path=protocol_path,
        output_dir=output_dir or artifacts_dir() / "transition_learning_001" / "evaluation",
        checkpoints=checkpoints, include_baselines=False,
    )
