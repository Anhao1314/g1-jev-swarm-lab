"""Prospective coarse alpha sensitivity; no historical implementation edits.

The only intervention is the correction reference angle. Original skill bodies,
PD, locomotion policy, correction arithmetic and scoring remain delegated.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import random
import subprocess

import numpy as np
import torch

from ..paths import repo_root
from ..segmentation.mission import MissionFrame
from ..reference_ablation.experiment import ReferenceRunner, ReferenceCorrectionPolicy
from ..frame_learning.campaign import verify_freeze as verify_prior

ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0)
CONTROL_ALPHAS = (0.0, 0.5, 1.0)
DIRECTORY = "experiments/phase3a/correction_tradeoff_isolation_001"
ARTIFACT = "artifacts/correction_tradeoff_isolation_001"
HISTORY_COMMIT = "eefe56189c511b9be8c6965fcdaa64fb57a81d77"
FRAME = "experiments/phase3a/frame_residual_learning_001"
HEADING = "experiments/phase3a/heading_alignment_strength_001"
CONSOLE = "experiments/research_console/vertical_slice_001"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def wrap(value):
    return math.atan2(math.sin(value), math.cos(value))


def validate_alpha(alpha):
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or alpha not in ALPHAS:
        raise ValueError("Only prospectively fixed coarse doses 0,.25,.5,.75,1 are allowed")
    return float(alpha)


class FixedAlphaCorrectionPolicy(ReferenceCorrectionPolicy):
    def __init__(self, runner, alpha, delegate):
        self.alpha = validate_alpha(alpha)
        super().__init__(runner, "actual_node_start", delegate)

    def selected_frame(self, local_frame):
        if self.alpha == 0:
            return local_frame  # Exact historical actual-frame recipe.
        heading = float(self.runner.planned_heading) if self.alpha == 1 else wrap(
            local_frame.initial_yaw_rad + self.alpha * wrap(
                float(self.runner.planned_heading) - local_frame.initial_yaw_rad))
        return MissionFrame(local_frame.initial_position, heading)


class TradeoffRunner(ReferenceRunner):
    def __init__(self, case, alpha, trace_path=None):
        # No policy callback. No actor, optimization, reward or skill changes.
        super().__init__(case, "actual_node_start", trace_path)
        self.alpha = validate_alpha(alpha)
        self.reference_mode = {0.: "actual_node_start", .5: "midpoint_heading",
                               1.: "actual_origin_ideal_heading"}.get(self.alpha, f"fixed_alpha_{self.alpha:g}")
        self.correction = FixedAlphaCorrectionPolicy(self, self.alpha, self.correction.delegate)
        self.rows = []
        self.reward_calls = 0
        self.hashes = {k: hashlib.sha256() for k in
                       ("commands", "torques", "base_observations", "base_actions", "residual_observations")}
        self.counts = dict.fromkeys(self.hashes, 0)
        # Reuse the frozen Console offline observer. It has no renderer or UI.
        from console.capture import CaptureSimulation
        self.sim = CaptureSimulation(self.sim, self, True)
        original_torques, original_obs = self.base.compute_torques, self.base._build_observation

        def audited_torques(**kwargs):
            self.audit("commands", kwargs["command"])
            value = original_torques(**kwargs)
            self.audit("torques", value)
            self.audit("base_actions", self.base._action)
            return value

        def audited_observation(*args, **kwargs):
            value = original_obs(*args, **kwargs)
            self.audit("base_observations", value)
            return value

        self.base.compute_torques, self.base._build_observation = audited_torques, audited_observation

    def audit(self, name, value):
        self.hashes[name].update(np.asarray(value).tobytes())
        self.counts[name] += 1

    def observation(self, *args, **kwargs):
        value = super().observation(*args, **kwargs)
        self.audit("residual_observations", value)
        return value

    def dense_reward(self):
        self.reward_calls += 1
        return super().dense_reward()

    def trace(self, row):
        super().trace(row)
        self.rows.append(self.last_command_trace)


def science_record(value):
    """Exclude only explicit experiment/publication metadata and wall clocks."""
    if isinstance(value, dict):
        excluded = {"alpha", "heading_alignment_alpha", "run_id", "phase", "repetition", "provenance",
                    "evaluation_set", "checkpoint", "recorded_at", "treatment_label", "observer_audit",
                    "policy_decision_calls", "learned_policy_configured"}
        return {k: science_record(v) for k, v in value.items()
                if k not in excluded and k not in ("wall_time_s", "elapsed_wall_time_s")}
    if isinstance(value, list):
        return [science_record(v) for v in value]
    return value


def verify_console():
    root = repo_root()
    manifest_path = root / CONSOLE / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for scope, paths in [(root / CONSOLE, manifest["files"]), (root, manifest["sources"])]:
        for name, pin in paths.items():
            path = scope / name
            if sha(path) != pin["sha256"] or path.stat().st_size != pin["bytes"]:
                raise RuntimeError(f"Frozen Console drift: {name}")
    return {"manifest_sha256": sha(manifest_path), "visual_files": len(manifest["files"]),
            "source_files": len(manifest["sources"])}


def freeze_experiment():
    root = repo_root()
    output = root / DIRECTORY
    output.mkdir(parents=True, exist_ok=True)
    if (output / "protocol.json").exists():
        raise FileExistsError("Protocol already frozen; no overwrite")
    prior, console = verify_prior(), verify_console()
    existing = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", HISTORY_COMMIT], cwd=root, text=True).splitlines()
    pins = {name: {"sha256": sha(root / name), "bytes": (root / name).stat().st_size} for name in existing}
    write_new(output / "history_freeze.json", {"source_commit": HISTORY_COMMIT, "files": pins,
               "scope": "Every existing tracked file, including all frozen Console code and visual assets"})
    original_cases = json.loads((root / FRAME / "case_manifest.json").read_text())
    chosen = [next(c for c in original_cases["regression"] if c["id"] == name)
              for name in ("sequence-mixed-16m", "primitive-walk-8")]
    write_new(output / "case_manifest.json", {"cases": chosen, "source_path": FRAME + "/case_manifest.json",
               "source_sha256": sha(root / FRAME / "case_manifest.json"), "seen_mechanism_cases": True})
    anchors = [(case["id"], alpha) for case in chosen for alpha in CONTROL_ALPHAS]
    novel = [(chosen[0]["id"], alpha) for alpha in (.25, .75)]
    schedule = [dict(case_id=name, alpha=alpha, repetition=rep,
                     phase="primary" if rep == 0 else "repeatability")
                for collection in (anchors, novel) for rep in (0, 1) for name, alpha in collection]
    write_new(output / "protocol.json", {
        "experiment_id": "correction_tradeoff_isolation_001", "session": "Phase 3A.4b", "frozen": True,
        "factor": "wrapped correction heading alignment strength; control heading AND lateral axes rotate together",
        "fixed_alphas": list(ALPHAS), "origin": "actual node start", "residual_enabled": False, "PPO_training": False,
        "reward_calls_expected": 0, "optimizer_updates": 0, "checkpoint_writes": 0,
        "case_manifest_sha256": sha(output / "case_manifest.json"), "history_manifest_sha256": sha(output / "history_freeze.json"),
        "prior_frame_protocol_sha256": prior["protocol_sha256"],
        "prior_heading_protocol_sha256": sha(root / HEADING / "protocol.json"),
        "baseline_freeze_sha256": prior["history"]["baseline"]["baseline_freeze_sha256"],
        "base_policy_sha256": json.loads((root / FRAME / "protocol.json").read_text())["base_policy_sha256"],
        "console": console, "schedule": schedule, "runs": 16, "primary_runs": 8, "repeatability_runs": 8,
        "seed": 0, "seed_meaning": "Stored deterministic reset seed; not randomized state or independent statistical trials",
        "device": "cpu", "torch_threads": 1, "timestep_s": .002, "pose_capture_hz": 20,
        "frozen_controls": ["motion.pt", "base controller/PD", "gains1.5/1.0", "yaw clamp0.6/deadband0.01",
             "skills/reset/termination", "original nominal/strict/physical envelopes", "case parameters", "no reward or observation change"],
        "stop_conditions": ["Historical full scientific record or trace mismatch", "Existing file/protocol/policy drift",
             "Command/scoring/frame reconstruction error", "Unexpected upstream Stand-state or null-control mismatch"],
        "novel_dose_gate": "All six historical primary anchors and their exact repeats must pass before alpha.25/.75",
        "semantic_failure_retry": False, "alpha_optimization": False, "fine_scan": False, "expand_cases": False,
        "analysis": {
             "numerical_audit_tolerance": 1e-10, "role": "roundoff audit, NOT a new task or stability threshold",
             "endpoint_rotation_identity": "y_local=x_local*tan(delta)+y_control/cos(delta); delta=wrap(ref-local)",
             "tracking_claim": "Report actual control-frame remainder relative to rotated projection and existing strict limit; identity alone is not evidence of good tracking",
             "heading_recursion": "e_walk_end=wrap((1-alpha)*e_start_global+e_control); Turn carries inherited error plus turn residual",
             "global_position_budget": "sum actual node displacements minus ideal Walk displacements equals endpoint error vector",
             "physical_stability": "Report original physical/fall/tilt/height/standing/oscillation/saturation; corridor departure alone is not physical instability",
             "strict_semantics": "Original endpoint actual-start lateral gate; sampled peak is a diagnostic only",
             "verdict": "Distinguish real local-contract/global precision conflict from physical instability and evaluator/implementation artifacts",
             "no_new_score_thresholds": True},
        "data_scope": "Seen mechanism/regression case interventions; no fresh blind/noise/generalization claim",
        "stop_after_completion": "No Phase3A.5; no Console UI change; no chosen best alpha"})
    return {"frozen": True, "history_files": len(pins), "protocol_sha256": sha(output / "protocol.json"),
            "case_sha256": sha(output / "case_manifest.json"), "console_verified": console}


def verify_experiment():
    root = repo_root()
    folder = root / DIRECTORY
    p = json.loads((folder / "protocol.json").read_text())
    for name, key in [("case_manifest.json", "case_manifest_sha256"), ("history_freeze.json", "history_manifest_sha256")]:
        if sha(folder / name) != p[key]:
            raise RuntimeError(f"New frozen manifest changed: {name}")
    if p["fixed_alphas"] != list(ALPHAS) or not p["frozen"] or len(p["schedule"]) != 16:
        raise RuntimeError("Frozen sensitivity schedule required")
    pins = json.loads((folder / "history_freeze.json").read_text())["files"]
    for name, pin in pins.items():
        path = root / name
        if not path.is_file() or sha(path) != pin["sha256"] or path.stat().st_size != pin["bytes"]:
            raise RuntimeError(f"Historical file drift: {name}")
    return {"history_files_verified": len(pins), "console": verify_console(), "prior": verify_prior()}


def source_anchor(case_id, alpha):
    root = repo_root()
    if alpha == 1:
        path = root / HEADING / "evidence/results.jsonl.gz"
        label = "actual_origin_ideal_heading"
        trace = root / HEADING / f"evidence/traces/primary--{label}--{case_id}.jsonl.gz"
        if not trace.exists():
            trace = trace.with_suffix("")
    else:
        path = root / FRAME / "evidence/evaluation/results.jsonl.gz"
        label = f"alpha{alpha:g}-residual-off"
        trace = root / FRAME / f"evidence/evaluation/traces/primary--{label}--{case_id}.jsonl.gz"
    rows = [json.loads(line) for line in gzip.decompress(path.read_bytes()).decode().splitlines()]
    selected = [(i + 1, row) for i, row in enumerate(rows)
                if row["case_id"] == case_id and row["treatment_label"] == label and row["phase"] == "primary"]
    if len(selected) != 1:
        raise RuntimeError("Historical anchor must be unique")
    line, record = selected[0]
    content = gzip.decompress(trace.read_bytes()) if trace.suffix == ".gz" else trace.read_bytes()
    return record, [json.loads(row) for row in content.decode().splitlines()], {
        "result_locator": path.relative_to(root).as_posix() + f"#decoded-line={line}",
        "trace_path": trace.relative_to(root).as_posix(), "result_sha256": sha(path), "trace_sha256": sha(trace)}


def tensor_digest(policy):
    digest = hashlib.sha256()
    for name, value in sorted(policy.state_dict().items()):
        digest.update(name.encode()); digest.update(value.detach().cpu().numpy().tobytes())
    return digest.hexdigest()


def acquire(case, alpha, trace):
    random.seed(0); np.random.seed(0); torch.manual_seed(0)
    runner = TradeoffRunner(case, alpha, trace)
    try:
        initial_tensors = tensor_digest(runner.base._policy)
        result = runner.run()
        if runner.sim.states[-1][0] != runner.sim.simulation_time:
            runner.sim.snapshot()
        fields = list(zip(*runner.sim.states))
        poses = dict(time_s=np.asarray(fields[0]), qpos=np.asarray(fields[1]), qvel=np.asarray(fields[2]),
             ctrl=np.asarray(fields[3]), node_index=np.asarray(fields[4]), planned_origin=np.asarray(fields[5]),
             planned_heading=np.asarray(fields[6]), local_origin=np.asarray(fields[7]),
             local_heading=np.asarray(fields[8]), reference_heading=np.asarray(fields[9]))
        audit = {"physics_state_sha256": runner.sim.hash.hexdigest(), "physics_steps": runner.sim.steps,
             "streams": {k: {"sha256": v.hexdigest(), "count": runner.counts[k]} for k, v in runner.hashes.items()},
             "initial_tensors_sha256": initial_tensors, "final_tensors_sha256": tensor_digest(runner.base._policy),
             "rng_after_sha256": hashlib.sha256(repr((random.getstate(), np.random.get_state(), torch.get_rng_state().tolist())).encode()).hexdigest(),
             "reward_calls": runner.reward_calls, "optimizer_updates": 0, "checkpoint_writes": 0,
             "collector": "Frozen Console offline CaptureSimulation; no live UI or renderer in physics process"}
        if runner.reward_calls != 0:
            raise RuntimeError("Unexpected reward call in residual-off replay")
        return result, runner.rows, poses, audit
    finally:
        runner.close()


def export_evidence(output, protocol_sha):
    root = repo_root(); target = root / DIRECTORY / "evidence"
    target.mkdir(exist_ok=False)
    inventory = {}
    for path in sorted(output.rglob("*")):
        if not path.is_file(): continue
        relative = path.relative_to(output)
        destination = target / relative
        if path.suffix == ".jsonl": destination = destination.with_suffix(".jsonl.gz")
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = path.read_bytes()
        data = gzip.compress(raw, mtime=0) if path.suffix == ".jsonl" else raw
        with destination.open("xb") as handle: handle.write(data)
        inventory[destination.relative_to(root).as_posix()] = {"raw_path": path.relative_to(root).as_posix(),
             "raw_sha256": hashlib.sha256(raw).hexdigest(), "sha256": sha(destination), "bytes": len(data),
             "encoding": "gzip" if path.suffix == ".jsonl" else "identity"}
    write_new(root / DIRECTORY / "evidence_manifest.json", {"protocol_sha256": protocol_sha,
         "files": inventory, "all_negative_results_retained": True, "retry": False})


def run_campaign(output_dir=ARTIFACT):
    root = repo_root(); folder = root / DIRECTORY; output = root / output_dir
    checks = verify_experiment(); protocol = json.loads((folder / "protocol.json").read_text())
    source_paths = [*Path(__file__).parent.glob("*.py"), root / "scripts/freeze_phase3a_tradeoff.py", root / "scripts/run_phase3a_tradeoff.py"]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    source_hashes = {p.relative_to(root).as_posix(): sha(p) for p in source_paths}
    for name, expected in source_hashes.items():
        if hashlib.sha256(subprocess.check_output(["git", "show", f"HEAD:{name}"], cwd=root)).hexdigest() != expected:
            raise RuntimeError(f"Acquisition source must be committed and exact: {name}")
    if hashlib.sha256(subprocess.check_output(["git", "show", f"HEAD:{DIRECTORY}/protocol.json"], cwd=root)).hexdigest() != sha(folder / "protocol.json"):
        raise RuntimeError("Protocol must be committed before any acquisition")
    common = {"code_commit": commit, "protocol_sha256": sha(folder / "protocol.json"),
         "case_manifest_sha256": sha(folder / "case_manifest.json"), "history_manifest_sha256": sha(folder / "history_freeze.json"),
         "base_policy_sha256": protocol["base_policy_sha256"], "source_hashes": source_hashes,
         "packages": {name: importlib.metadata.version(name) for name in ("mujoco", "numpy", "torch", "gymnasium")},
         "torch_threads": 1, "device": "cpu", "seed": 0, "PPO_training": False, "residual_enabled": False,
         "Console_UI_modified": False, "no_independent_seed_claim": True}
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.use_deterministic_algorithms(True)
    write_new(output / "manifest.json", {"protocol": protocol, "provenance": common, "integrity_before": checks})
    cases = {case["id"]: case for case in json.loads((folder / "case_manifest.json").read_text())["cases"]}
    records, traces, poses_by_run, anchor_checks = [], {}, {}, []
    try:
        for ordinal, spec in enumerate(protocol["schedule"]):
            for name, expected in common["source_hashes"].items():
                if sha(root / name) != expected:
                    raise RuntimeError(f"Committed acquisition source changed: {name}")
            if sha(folder / "protocol.json") != common["protocol_sha256"]:
                raise RuntimeError("Prospective protocol changed during acquisition")
            alpha, case_id, phase = spec["alpha"], spec["case_id"], spec["phase"]
            if ordinal == 12:
                if len(anchor_checks) != 12 or not all(row["passed"] for row in anchor_checks):
                    raise RuntimeError("Historical anchors/repeats did not authorize novel doses")
                starts = [row["nodes"][1]["start_state"] for row in records
                          if row["case_id"] == "sequence-mixed-16m"]
                if not all(state == starts[0] for state in starts):
                    raise RuntimeError("Upstream Stand-state mismatch; stop before novel doses")
                controls = [row["observer_audit"] for row in records if row["case_id"] == "primitive-walk-8"]
                if not all(audit == controls[0] for audit in controls):
                    raise RuntimeError("Zero-mismatch primitive control differed; stop before novel doses")
                write_new(output / "novel_dose_gate.json", {"passed": True, "anchor_checks": 12,
                     "shared_stand_state_exact": True, "primitive_physics_commands_obs_tensors_rng_exact": True,
                     "provenance": common})
            run_id = f"{phase}--alpha{alpha:g}--{case_id}"
            result, trace_rows, poses, audit = acquire(cases[case_id], alpha, output / "traces" / (run_id + ".jsonl"))
            result.update(alpha=alpha, run_id=run_id, phase=phase, repetition=spec["repetition"], provenance=common, observer_audit=audit)
            records.append(result); traces[run_id] = trace_rows; poses_by_run[run_id] = poses
            (output / "poses").mkdir(exist_ok=True)
            np.savez_compressed(output / "poses" / (run_id + ".npz"), **poses)
            with (output / "results.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(result, allow_nan=False) + "\n")
            if alpha in CONTROL_ALPHAS:
                old_record, old_trace, locator = source_anchor(case_id, alpha)
                passed = science_record(result) == science_record(old_record) and trace_rows == old_trace
                anchor_checks.append({"run_id": run_id, "passed": passed, **locator})
                if not passed: raise RuntimeError(f"Historical anchor mismatch: {run_id}")
            if spec["repetition"] == 1:
                primary = next(row for row in records if row["case_id"] == case_id and row["alpha"] == alpha and row["phase"] == "primary")
                if science_record(result) != science_record(primary) or audit != primary["observer_audit"]:
                    raise RuntimeError(f"Deterministic replay mismatch: {run_id}")
            from .analysis import audit_one_run, build_analysis
            interim = audit_one_run(result, trace_rows, poses)
            write_new(output / (run_id + "--audit.json"), {**interim, "provenance": common})
            if not interim["passed"]:
                raise RuntimeError(f"Mechanism/command audit failed: {interim.get('failures')}")
            print(json.dumps({"completed": ordinal + 1, "of": 16, "run_id": run_id,
                  "task": result["task_success"], "physical": result["physical_success"],
                  "strict": all(n["strict_success"] for n in result["nodes"])}), flush=True)
        analysis = build_analysis(records, traces, poses_by_run)
        if not analysis["all_audits_passed"]:
            raise RuntimeError(f"Cross-arm mechanism audit failed: {analysis.get('audit_failures_first_100')}")
        write_new(output / "analysis.json", {**analysis, "provenance": common})
        write_new(output / "anchor_checks.json", {"checks": anchor_checks, "all_passed": True, "provenance": common})
        for name, expected in common["source_hashes"].items():
            if sha(root / name) != expected:
                raise RuntimeError(f"Acquisition source drift after collection: {name}")
        write_new(output / "integrity_after.json", verify_experiment())
        write_new(output / "completion.json", {"status": "COMPLETE", "runs": len(records), "scientific_verdict": analysis["verdict"], "provenance": common})
    except Exception as exc:
        write_new(output / "stopped.json", {"status": "STOPPED_ROOT_CAUSE_AUDIT", "reason": str(exc),
                    "completed_and_retained_runs": len(records), "anchor_checks": anchor_checks, "provenance": common})
        export_evidence(output, common["protocol_sha256"])
        raise
    export_evidence(output, common["protocol_sha256"])
    return {"runs": len(records), "verdict": analysis["verdict"], "protocol_sha256": common["protocol_sha256"], "code_commit": commit}
