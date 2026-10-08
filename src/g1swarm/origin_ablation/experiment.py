"""New origin treatment; all old frame/control/skill/scoring code is retained."""
from __future__ import annotations

import gzip
import importlib.metadata
import json
from pathlib import Path
import subprocess

import torch

from ..paths import repo_root, resolve_repo_path
from ..segmentation.mission import MissionFrame
from ..reference_ablation.experiment import (
    ReferenceCorrectionPolicy, ReferenceRunner, canonical_physics,
    compare_reference_records, sha, verify_history as verify_reference_history, write_new,
)
from ..transition_learning.cases import EVAL_CASES, PRIMITIVE_CASES, SEQUENCE_CASES
from ..transition_learning.analysis import summarize_results

MODES = ("actual_node_start", "actual_origin_ideal_heading", "ideal_commanded_axis")
HYBRID = "actual_origin_ideal_heading"
DIRECTORY = "experiments/phase3a/origin_selection_ablation_001"
REFERENCE = "experiments/phase3a/reference_frame_ablation_001"
PILOT = "experiments/phase3a/transition_learning_001"


class OriginCorrectionPolicy(ReferenceCorrectionPolicy):
    def __init__(self, runner, reference_mode, delegate):
        if reference_mode not in MODES:
            raise ValueError(f"Unknown origin mode {reference_mode}")
        # Initialize the unchanged bookkeeping with a supported historical mode.
        super().__init__(runner, "actual_node_start" if reference_mode == HYBRID else reference_mode, delegate)
        self.reference_mode = reference_mode

    def selected_frame(self, local_frame):
        if self.reference_mode == HYBRID:
            return MissionFrame(initial_position=local_frame.initial_position,
                                initial_yaw_rad=float(self.runner.planned_heading))
        return super().selected_frame(local_frame)


class OriginRunner(ReferenceRunner):
    def __init__(self, case, reference_mode="actual_node_start", trace_path=None):
        if reference_mode not in MODES:
            raise ValueError(f"Unknown origin mode {reference_mode}")
        super().__init__(case, "actual_node_start" if reference_mode == HYBRID else reference_mode, trace_path)
        self.reference_mode = reference_mode
        self.correction = OriginCorrectionPolicy(self, reference_mode, self.correction.delegate)


def replay_origin(case, reference_mode="actual_node_start", trace_path=None):
    runner = OriginRunner(case, reference_mode, trace_path)
    try:
        return runner.run()
    finally:
        runner.close()


def verify_history():
    checks = verify_reference_history()
    path = repo_root()/DIRECTORY/"history_freeze.json"
    pins = json.loads(path.read_text(encoding="utf-8"))
    failures = []
    for relative, expected in pins["files"].items():
        source = repo_root()/relative
        if not source.is_file() or sha(source) != expected["sha256"] or source.stat().st_size != expected["bytes"]:
            failures.append(relative)
    if failures:
        raise RuntimeError(f"Historical evidence/source changed: {failures}")
    checks.update(all_history_files_verified=len(pins["files"]),
                  origin_history_manifest_sha256=sha(path), historical_drift=False)
    return checks


def run_campaign(output_dir, protocol_path=DIRECTORY+"/protocol.json"):
    root = repo_root()
    path = resolve_repo_path(protocol_path)
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if protocol.get("frozen") is not True:
        raise ValueError("Origin selection protocol must be frozen")
    history = verify_history()
    if history["origin_history_manifest_sha256"] != protocol["history_manifest_sha256"]:
        raise RuntimeError("Historical manifest pin changed")
    case_path = root/PILOT/"case_manifest.json"
    if sha(case_path) != protocol["case_manifest_sha256"]:
        raise RuntimeError("Cases changed")
    old_protocol_path = root/REFERENCE/"protocol.json"
    old_protocol = json.loads(old_protocol_path.read_text(encoding="utf-8"))
    if sha(old_protocol_path) != protocol["inherited_reference_protocol_sha256"] or old_protocol["training_hypothesis_gate"] != protocol["training_hypothesis_gate"]:
        raise RuntimeError("Inherited historical gate changed")
    output = resolve_repo_path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    provenance = {"code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "protocol_sha256": sha(path), "case_manifest_sha256": sha(case_path),
        "history_manifest_sha256": history["origin_history_manifest_sha256"],
        "inherited_reference_protocol_sha256": sha(old_protocol_path),
        "baseline_freeze_sha256": history["baseline"]["baseline_freeze_sha256"],
        "base_policy_sha256": protocol["base_policy_sha256"],
        "source_hashes": {p.relative_to(root).as_posix(): sha(p) for p in sorted([
            *Path(__file__).parent.glob("*.py"), root/"scripts/run_phase3a_origin.py"])},
        "packages": {n: importlib.metadata.version(n) for n in ["torch", "numpy", "mujoco", "gymnasium", "stable-baselines3"]},
        "device": "cpu", "torch_threads": 1, "residual_enabled": False,
        "PPO_training": False, "language_Runtime": False, "Jev": False}
    write_new(output/"manifest.json", {"protocol": protocol, "provenance": provenance, "history_before": history})
    prior_rows = [json.loads(row) for row in gzip.decompress((root/REFERENCE/"evidence/results.jsonl.gz").read_bytes()).decode().splitlines()]
    prior = {(r["case_id"], r["reference_mode"]): r for r in prior_rows if r["phase"] == "primary"}
    case_sets = [("unseen_transition", EVAL_CASES), ("primitive_regression", PRIMITIVE_CASES),
                 ("unseen_sequence", SEQUENCE_CASES)]
    records, historical_checks = [], []
    try:
        for repetition, phase in [(0, "primary"), (1, "repeatability")]:
            for mode in MODES:
                for evaluation_set, collection in case_sets:
                    for case in collection:
                        trace = output/"traces"/(f"{phase}--{mode}--{case['id']}.jsonl")
                        record = replay_origin(case, mode, trace)
                        record.update(phase=phase, repetition=repetition, evaluation_set=evaluation_set, provenance=provenance)
                        records.append(record)
                        with (output/"results.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                            handle.write(json.dumps(record, allow_nan=False)+"\n")
                        if mode != HYBRID:
                            expected = prior[(case["id"], mode)]
                            identical = canonical_physics(record) == canonical_physics(expected)
                            historical_checks.append({"case_id": case["id"], "phase": phase, "reference_mode": mode, "passed": identical})
                            if not identical:
                                raise RuntimeError(f"Historical arm changed: {mode}/{case['id']}")
        primary = [r for r in records if r["phase"] == "primary"]
        repeated = [r for r in records if r["phase"] == "repeatability"]
        index = {(r["case_id"],r["reference_mode"]):r for r in primary}
        repeat_checks = [{"case_id":r["case_id"],"reference_mode":r["reference_mode"],
            "passed":canonical_physics(r)==canonical_physics(index[(r["case_id"],r["reference_mode"])])} for r in repeated]
        if not all(x["passed"] for x in repeat_checks):
            raise RuntimeError("Deterministic repeatability failed")
        after = verify_history()
        if sha(path) != provenance["protocol_sha256"]:
            raise RuntimeError("Protocol changed during campaign")
        write_new(output/"summary.json", summarize_results(primary))
        write_new(output/"comparison.json", compare_reference_records(primary))
        # Copy only the label for a conditional origin contrast; saved records
        # and all metrics/gates are unchanged.
        conditional = [{**r,"reference_mode":"actual_node_start","treatment_label":"actual_node_start"}
                       if r["reference_mode"]==HYBRID else r for r in primary if r["reference_mode"]!="actual_node_start"]
        origin_comparison = compare_reference_records(conditional)
        origin_comparison.update(baseline_treatment=HYBRID,
            delta_convention="planned-origin ideal-heading minus actual-origin ideal-heading; conditional origin effect")
        write_new(output/"origin_comparison.json", origin_comparison)
        write_new(output/"completion.json", {"status":"COMPLETE","primary_runs":len(primary),
            "repeatability_runs":len(repeated),"records":len(records),"history_after":after,
            "historical_arms_identity":historical_checks,"repeatability_identity":repeat_checks,"provenance":provenance})
        return {"status":"COMPLETE","primary_runs":len(primary),"repeatability_runs":len(repeated)}
    except Exception as exc:
        write_new(output/"failure.json", {"status":"FAILED","completed_records":len(records),
            "exception":type(exc).__name__,"message":str(exc),"provenance":provenance})
        raise
