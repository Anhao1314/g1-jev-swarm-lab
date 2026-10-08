"""Change only walking correction's reference; retain original task semantics.

The old EpisodeRunner and all archived Phase3A data remain unmodified. Planned
axis construction is exactly its existing planned_origin/planned_heading. Local
skill termination, observation, reward and envelope metrics still use self.frame.
No residual actor is supplied and no PPO training is performed.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import subprocess

import torch
import numpy as np

from ..paths import repo_root, resolve_repo_path
from ..segmentation.mission import MissionFrame
from ..control.path_correction import CorrectionTracker
from ..transition_learning.env import EpisodeRunner
from ..transition_learning.cases import EVAL_CASES, PRIMITIVE_CASES, SEQUENCE_CASES
from ..transition_learning.training import verify_baseline_freeze, verify_case_manifest
from ..transition_learning.analysis import summarize_results, compare_results

MODES = ("actual_node_start", "ideal_commanded_axis")
DIRECTORY = "experiments/phase3a/reference_frame_ablation_001"
PILOT = "experiments/phase3a/transition_learning_001"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


class ReferenceCorrectionPolicy:
    def __init__(self, runner, reference_mode, delegate):
        if reference_mode not in MODES:
            raise ValueError(f"Unknown walking reference mode {reference_mode}")
        self.runner, self.reference_mode, self.delegate = runner, reference_mode, delegate
        self.config = delegate.config
        self.trackers = {}
        self.last_sample = None

    def selected_frame(self, local_frame):
        if self.reference_mode == "actual_node_start":
            return local_frame
        r = self.runner
        return MissionFrame(
            initial_position=(float(r.planned_origin[0]), float(r.planned_origin[1]),
                              float(local_frame.initial_position[2])),
            initial_yaw_rad=float(r.planned_heading))

    def compute(self, state, frame, nominal_command, *, sim_time_s):
        selected = self.selected_frame(frame)
        command, sample = self.delegate.compute(state, selected, nominal_command, sim_time_s=sim_time_s)
        tracker = self.trackers.setdefault(self.runner.index, CorrectionTracker(
            oscillation_threshold_radps=self.config.oscillation_threshold_radps))
        tracker.add(sample)
        self.last_sample = {**sample.to_dict(),
            "heading_component_radps": -self.config.k_heading*sample.heading_error_rad,
            "lateral_component_radps": -self.config.k_lateral*sample.lateral_error_m}
        return command, sample


class ReferenceRunner(EpisodeRunner):
    def __init__(self, case, reference_mode="actual_node_start", trace_path=None):
        if reference_mode not in MODES:
            raise ValueError(f"Unknown walking reference mode {reference_mode}")
        # Same treatment in the frozen runner: only its correction frame differs.
        super().__init__(case, "deterministic_correction", control=None, trace_path=trace_path)
        self.reference_mode = reference_mode
        self.correction = ReferenceCorrectionPolicy(self, reference_mode, self.correction)

    def _frame_metadata(self):
        local = self.frame
        selected = self.correction.selected_frame(local)
        return {"measurement_origin": list(local.initial_position),
                "measurement_heading_rad": local.initial_yaw_rad,
                "control_origin": list(selected.initial_position),
                "control_heading_rad": selected.initial_yaw_rad,
                "planned_origin": self.planned_origin.tolist(),
                "planned_heading_rad": self.planned_heading}

    def trace(self, row):
        row = dict(row)
        row["reference_mode"] = self.reference_mode
        row["walking_reference"] = self._frame_metadata() if self.skill == "walk_forward" else None
        row["walking_correction_sample"] = self.correction.last_sample if self.skill == "walk_forward" else None
        state = self.sim.get_robot_state()
        row["state_before_command"] = state.to_dict()
        super().trace(row)

    def _node_record(self, result):
        # This computes all historical local gates before any new diagnostics.
        record = super()._node_record(result)
        record["reference_mode"] = self.reference_mode
        record["walking_reference"] = self._frame_metadata() if self.skill == "walk_forward" else None
        if self.skill == "walk_forward":
            record["walking_correction_stats"] = self.correction.trackers[self.index].summary() if self.index in self.correction.trackers else None
            control_frame = self.correction.selected_frame(self.frame)
            state = self.sim.get_robot_state()
            forward, lateral = control_frame.project(state.base_position)
            record["control_frame_diagnostics"] = {
                "forward_m": forward, "lateral_m": lateral,
                "heading_error_deg": control_frame.heading_error_deg(state),
                "task_gate_role": "NONE; historical actual-start gate preserved"}
        return record

    def run(self):
        record = super().run()
        record.update(reference_mode=self.reference_mode, treatment_label=self.reference_mode,
                      residual_enabled=False, PPO_training=False)
        offset = np.array(self.sim.get_robot_state().base_position[:2])-self.planned_origin
        record["ideal_endpoint_error_m"] = float(np.linalg.norm(offset))
        record["ideal_endpoint_reference_xy"] = self.planned_origin.tolist()
        return record


def replay_reference(case, reference_mode="actual_node_start", trace_path=None):
    runner = ReferenceRunner(case, reference_mode, trace_path)
    try:
        return runner.run()
    finally:
        runner.close()


def canonical_physics(value):
    """Strip only new annotations/provenance and wall time for replay identity."""
    if isinstance(value, dict):
        excluded = {"reference_mode", "walking_reference", "control_frame_diagnostics",
                    "treatment_label", "provenance", "checkpoint", "evaluation_set",
                    "residual_enabled", "PPO_training", "phase", "repetition"}
        excluded.update({"walking_correction_stats", "ideal_endpoint_error_m", "ideal_endpoint_reference_xy"})
        return {k: canonical_physics(v) for k, v in value.items()
                if k not in excluded and "wall" not in k}
    if isinstance(value, list):
        return [canonical_physics(x) for x in value]
    return value


def compare_reference_records(records):
    """Reuse the frozen arithmetic with an explicit non-mutating label adapter."""
    adapted = [{**r, "treatment_label": "deterministic_correction"
                if r["reference_mode"] == "actual_node_start" else r["treatment_label"]}
               for r in records]
    comparison = compare_results(adapted)
    comparison["baseline_treatment"] = "actual_node_start"
    comparison["delta_convention"] = "candidate minus actual_node_start; frozen metric arithmetic unchanged"
    comparison["label_adapter"] = "Only copied baseline label maps to the old helper's fixed label; saved records and all scores unchanged"
    return comparison


def verify_history():
    root = repo_root()
    protocol = json.loads((root / PILOT / "protocol.json").read_text(encoding="utf-8"))
    checks = {"baseline": verify_baseline_freeze(), "cases": verify_case_manifest(protocol)}
    pins = json.loads((root / DIRECTORY / "history_freeze.json").read_text(encoding="utf-8"))
    failures = []
    for relative, expected in pins["files"].items():
        path = root / relative
        if not path.is_file() or sha(path) != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            failures.append(relative)
    if failures:
        raise RuntimeError(f"Historical Phase3A changed: {failures}")
    checks.update(history_files_verified=len(pins["files"]), historical_drift=False,
                  history_manifest_sha256=sha(root / DIRECTORY / "history_freeze.json"))
    return checks


def run_campaign(output_dir, protocol_path=DIRECTORY+"/protocol.json"):
    root = repo_root()
    path = resolve_repo_path(protocol_path)
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if protocol.get("frozen") is not True:
        raise ValueError("Reference experiment must be frozen before acquisition")
    history = verify_history()
    if history["history_manifest_sha256"] != protocol["history_manifest_sha256"]:
        raise RuntimeError("History manifest differs from frozen reference protocol")
    old_case = root / PILOT / "case_manifest.json"
    if sha(old_case) != protocol["case_manifest_sha256"]:
        raise RuntimeError("Evaluation membership changed")
    output = resolve_repo_path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    provenance = {"code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "protocol_sha256": sha(path), "case_manifest_sha256": sha(old_case),
        "history_manifest_sha256": history["history_manifest_sha256"],
        "baseline_freeze_sha256": history["baseline"]["baseline_freeze_sha256"],
        "base_policy_sha256": protocol["base_policy_sha256"],
        "source_hashes": {p.relative_to(root).as_posix(): sha(p) for p in sorted([
            *Path(__file__).parent.glob("*.py"), root/"scripts/run_phase3a_reference.py"])},
        "packages": {n: importlib.metadata.version(n) for n in ["torch", "numpy", "mujoco", "gymnasium", "stable-baselines3"]},
        "device": "cpu", "torch_threads": 1, "residual_enabled": False,
        "PPO_training": False, "language_Runtime": False, "Jev": False}
    write_new(output / "manifest.json", {"protocol": protocol, "provenance": provenance, "history_before": history})
    # Already-seen fixed evaluation cases, never a new blind generalization set.
    case_sets = [("unseen_transition", EVAL_CASES), ("primitive_regression", PRIMITIVE_CASES),
                 ("unseen_sequence", SEQUENCE_CASES)]
    reference_file = root / PILOT / "evidence/baseline/results.jsonl.gz"
    prior_rows = [json.loads(row) for row in gzip.decompress(reference_file.read_bytes()).decode().splitlines()]
    prior = {r["case_id"]: r for r in prior_rows if r["treatment_label"] == "deterministic_correction"}
    records, identity_checks = [], []
    try:
        for repetition, phase in [(0, "primary"), (1, "repeatability")]:
            for mode in MODES:
                for evaluation_set, collection in case_sets:
                    for case in collection:
                        name = f"{phase}--{mode}--{case['id']}"
                        trace = output / "traces" / (name+".jsonl")
                        record = replay_reference(case, mode, trace)
                        record.update(phase=phase, repetition=repetition, evaluation_set=evaluation_set,
                                      provenance=provenance)
                        records.append(record)
                        with (output / "results.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                            handle.write(json.dumps(record, allow_nan=False)+"\n")
                        if mode == "actual_node_start":
                            identical = canonical_physics(record) == canonical_physics(prior[case["id"]])
                            identity_checks.append({"case_id": case["id"], "phase": phase, "passed": identical})
                            if not identical:
                                raise RuntimeError(f"Actual reference failed historical exact replay: {name}")
        primary = [r for r in records if r["phase"] == "primary"]
        repeated = [r for r in records if r["phase"] == "repeatability"]
        index = {(r["case_id"], r["reference_mode"]): r for r in primary}
        repeat_checks = [{"case_id": r["case_id"], "reference_mode": r["reference_mode"],
                          "passed": canonical_physics(r) == canonical_physics(index[(r["case_id"],r["reference_mode"])])}
                         for r in repeated]
        if not all(x["passed"] for x in repeat_checks):
            raise RuntimeError("Repeatability changed deterministic physical result")
        after = verify_history()
        if sha(path) != provenance["protocol_sha256"]:
            raise RuntimeError("Frozen protocol changed during campaign")
        write_new(output / "summary.json", summarize_results(primary))
        write_new(output / "comparison.json", compare_reference_records(primary))
        write_new(output / "completion.json", {"status": "COMPLETE", "primary_runs": len(primary),
            "repeatability_runs": len(repeated), "records": len(records), "history_after": after,
            "actual_historical_identity": identity_checks, "repeatability_identity": repeat_checks,
            "provenance": provenance})
        return {"status": "COMPLETE", "primary_runs": len(primary), "repeatability_runs": len(repeated)}
    except Exception as exc:
        write_new(output / "failure.json", {"status": "FAILED", "completed_records": len(records),
                   "exception": type(exc).__name__, "message": str(exc), "provenance": provenance})
        raise
