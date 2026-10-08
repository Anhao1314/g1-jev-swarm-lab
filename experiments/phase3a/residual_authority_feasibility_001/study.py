"""One fixed-case deterministic authority gate; no optimizer or parameter search."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import random
import subprocess
import sys
import time

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))  # frozen console.capture observer, not the Web server
sys.path.insert(0, str(HERE))
from console.capture import CaptureSimulation, tensor_digest
from g1swarm.frame_learning.env import FrameRunner
from g1swarm.transition_learning.env import BOUNDS, PAIRS, WINDOW, QUANTUM_STEPS

DIRECTORY = HERE.relative_to(ROOT).as_posix()
OLD = "experiments/phase3a/correction_tradeoff_isolation_001"
PROTOCOL = json.loads((HERE / "protocol.json").read_text())
PROFILES = {p["id"]: p for p in PROTOCOL["probes_in_order"]}
METADATA = {"treatment", "treatment_label", "residual_enabled", "PPO_training",
            "heading_alignment_alpha", "alpha", "run_id", "phase", "repetition", "provenance",
            "observer_audit", "policy_decision_calls", "learned_policy_configured", "probe_id",
            "active", "wall_time_s", "elapsed_wall_time_s"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def scientific(value):
    """Exclude named routing/publication/wall metadata; preserve all science."""
    if isinstance(value, dict):
        return {k: scientific(v) for k, v in value.items() if k not in METADATA}
    if isinstance(value, list):
        return [scientific(v) for v in value]
    return value


def profile_action(probe_id, node_index, skill, decision_tick):
    if probe_id not in {"off", "zero", *PROFILES}:
        raise ValueError(f"Undeclared profile {probe_id}")
    if probe_id in {"off", "zero"} or node_index != 1 or skill != "walk_forward" or not 0 <= decision_tick < 20:
        return np.zeros(3, dtype=np.float64)
    p = PROFILES[probe_id]
    if decision_tick < round(p["onset_s"] / .1):
        return np.zeros(3, dtype=np.float64)
    if "action" in p:
        action = p["action"]
    else:
        action = p["action_first"] if decision_tick < round(p["switch_s"] / .1) else p["action_second"]
    return np.array(action, dtype=np.float64, copy=True)


def verify_inputs():
    pins = json.loads((HERE / "source_manifest.json").read_text())
    assert sha(HERE / "source_manifest.json") == PROTOCOL["source_manifest_sha256"]
    assert sha(HERE / "case.json") == PROTOCOL["case_sha256"]
    for name, expected in pins["files"].items():
        if sha(ROOT / name) != expected:
            raise RuntimeError(f"Frozen source drift: {name}")
    assert np.array_equal(BOUNDS, PROTOCOL["authority"]["physical_bounds"])
    assert WINDOW == PROTOCOL["authority"]["window_s"] and QUANTUM_STEPS == 50
    return {"pinned_files_verified": len(pins["files"]), "historical_drift": False}


class ProbeRunner(FrameRunner):
    """Use original action injection; additions only observe and select probes."""
    def __init__(self, case, probe_id, destination, deadline):
        self.probe_id, self.deadline = probe_id, deadline
        self.rows, self.decisions = [], []
        self.hashes = {k: hashlib.sha256() for k in
                       ("commands", "torques", "base_observations", "base_actions", "residual_observations", "rewards")}
        self.counts = dict.fromkeys(self.hashes, 0)
        self.full_step_authority_checks = 0
        self.decision_file = (destination / "decisions.jsonl").open("x", encoding="utf-8", newline="\n")

        def control(observation, reward):
            elapsed = self.sim.simulation_time-self.node_start.simulation_time
            tick = self.node_steps // QUANTUM_STEPS
            action = profile_action(probe_id, self.index, self.skill, tick)
            row = {"node_index": self.index, "skill": self.skill, "decision_tick": tick,
                   "time_s": self.sim.simulation_time, "elapsed_s": elapsed,
                   "active": elapsed < WINDOW-1e-9,
                   "reward": float(reward), "proposed_action": action.tolist(),
                   "observation_sha256": hashlib.sha256(observation.tobytes()).hexdigest()}
            self.decisions.append(row)
            self.decision_file.write(json.dumps(row, allow_nan=False)+"\n")
            self.decision_file.flush()
            return action

        super().__init__(case, .5, "deterministic_correction" if probe_id == "off" else "learned",
                         control=None if probe_id == "off" else control,
                         trace_path=destination / "trace.jsonl", optimizing=False)
        self.sim = CaptureSimulation(self.sim, self, True)
        original_torques, original_obs = self.base.compute_torques, self.base._build_observation

        def observed_torques(**kwargs):
            if self.full_step_authority_checks % 1000 == 0 and time.perf_counter() > deadline:
                raise RuntimeError("Campaign wall budget exhausted; preserve partial run")
            applied = np.asarray(kwargs["command"])
            corrected = self.last_nominal_command.copy()
            if self.skill == "walk_forward":
                corrected[2] = self.correction.last_sample["yaw_clipped"]
            eligible = self.index > 0 and (self.previous, self.skill) in PAIRS
            elapsed = self.sim.simulation_time-self.node_start.simulation_time
            active = self.treatment == "learned" and eligible and elapsed < WINDOW-1e-9
            expected_action = profile_action(probe_id, self.index, self.skill, self.node_steps // QUANTUM_STEPS) if active else np.zeros(3)
            expected = corrected + expected_action * BOUNDS
            expected[2] = np.clip(expected[2], -.6, .6)
            if not np.array_equal(self.action, expected_action) or not np.array_equal(applied, expected):
                raise RuntimeError("Original applied authority does not match frozen probe")
            self.full_step_authority_checks += 1
            self.audit_array("commands", applied)
            value = original_torques(**kwargs)
            self.audit_array("torques", value)
            self.audit_array("base_actions", self.base._action)
            return value

        def observed_obs(*args, **kwargs):
            value = original_obs(*args, **kwargs)
            self.audit_array("base_observations", value)
            return value

        self.base.compute_torques, self.base._build_observation = observed_torques, observed_obs

    def audit_array(self, name, value):
        self.hashes[name].update(np.asarray(value).tobytes())
        self.counts[name] += 1

    def observation(self, *args, **kwargs):
        value = super().observation(*args, **kwargs)
        self.audit_array("residual_observations", value)
        return value

    def dense_reward(self):
        value = super().dense_reward()  # original path, ignored by deterministic probe
        self.audit_array("rewards", np.array([value]))
        return value

    def trace(self, row):
        super().trace(row)
        self.rows.append(self.last_command_trace)
        self.trace_file.flush()


def acquire(case, probe_id, run_id, repetition, destination, common, deadline):
    destination.mkdir(parents=True, exist_ok=False)
    random.seed(0); np.random.seed(0); torch.manual_seed(0)
    runner = ProbeRunner(case, probe_id, destination, deadline)
    before_tensor = tensor_digest(runner.base._policy)
    result = None
    try:
        result = runner.run()
        result.update(run_id=run_id, probe_id=probe_id, repetition=repetition, phase="confirmation" if repetition else "primary", provenance=common)
        write_new(destination / "result.json", result)
    finally:
        if runner.sim.states[-1][0] != runner.sim.simulation_time:
            runner.sim.snapshot()
        fields = list(zip(*runner.sim.states))
        poses = dict(zip(("time_s", "qpos", "qvel", "ctrl", "node_index", "planned_origin", "planned_heading", "local_origin", "local_heading", "reference_heading"),
                         [np.asarray(v) for v in fields]))
        np.savez_compressed(destination / "poses.npz", **poses)
        audit = {"physics_state_sha256": runner.sim.hash.hexdigest(), "physics_steps": runner.sim.steps,
                 "streams": {k: {"sha256": v.hexdigest(), "count": runner.counts[k]} for k, v in runner.hashes.items()},
                 "initial_tensors_sha256": before_tensor, "final_tensors_sha256": tensor_digest(runner.base._policy),
                 "rng_after_sha256": hashlib.sha256(repr((random.getstate(), np.random.get_state(), torch.get_rng_state().tolist())).encode()).hexdigest(),
                 "reward_calls": runner.counts["rewards"], "optimizer_updates": 0, "checkpoint_writes": 0,
                 "full_step_authority_checks": runner.full_step_authority_checks, "full_step_authority_violations": 0,
                 "collector": "Frozen offline state observer; acquisition samples; no renderer/UI",
                 "actor_kind": "NONE" if probe_id == "off" else "DETERMINISTIC_BOUNDED_PROBE_NOT_TRAINED"}
        write_new(destination / "audit.json", audit)
        runner.decision_file.close()
        runner.close()
    return result, runner.rows, runner.decisions, poses, audit


def export(output, common):
    target = HERE / "evidence"
    target.mkdir(exist_ok=False)
    inventory = {}
    for path in sorted(output.rglob("*")):
        if not path.is_file():
            continue
        dest = target / path.relative_to(output)
        if path.suffix == ".jsonl":
            dest = dest.with_suffix(".jsonl.gz")
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = path.read_bytes()
        data = gzip.compress(raw, mtime=0) if path.suffix == ".jsonl" else raw
        with dest.open("xb") as handle:
            handle.write(data)
        inventory[dest.relative_to(ROOT).as_posix()] = {
            "raw_path": path.relative_to(ROOT).as_posix(), "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "sha256": sha(dest), "bytes": len(data), "encoding": "gzip" if path.suffix == ".jsonl" else "identity"}
    write_new(HERE / "evidence_manifest.json", {"provenance": common, "files": inventory, "negative_results_retained": True})


def run():
    from audit import audit_run, summarize
    from g1swarm.frame_learning.campaign import verify_freeze
    integrity = verify_inputs()
    inherited = verify_freeze()  # pins/assets/settings only, no rollouts
    case = json.loads((HERE / "case.json").read_text())
    old_records = [json.loads(line) for line in gzip.decompress((ROOT / OLD / "evidence/results.jsonl.gz").read_bytes()).splitlines()]
    original = next(r for r in old_records if r["run_id"] == "primary--alpha0.5--sequence-mixed-16m")
    code_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in (HERE/"study.py", HERE/"audit.py")}
    for name, digest in source_hashes.items():
        if hashlib.sha256(subprocess.check_output(["git", "show", f"HEAD:{name}"], cwd=ROOT)).hexdigest() != digest:
            raise RuntimeError("Acquisition code not committed before physics")
    common = {"experiment_id": PROTOCOL["experiment_id"], "protocol_sha256": sha(HERE/"protocol.json"),
              "case_sha256": PROTOCOL["case_sha256"], "contract_sha256": PROTOCOL["contract_sha256"],
              "base_policy_sha256": original["provenance"]["base_policy_sha256"], "source_manifest_sha256": PROTOCOL["source_manifest_sha256"],
              "code_commit": code_commit, "source_hashes": source_hashes, "seed": 0, "torch_threads": 1,
              "packages": {name: importlib.metadata.version(name) for name in ("mujoco", "torch", "numpy", "gymnasium")},
              "optimizer_updates": 0, "checkpoint_writes": 0, "PPO_training": False, "reference_alpha": .5}
    output = ROOT / "artifacts/residual_authority_feasibility_001"
    output.mkdir(parents=True, exist_ok=False)
    write_new(output/"manifest.json", {"protocol": PROTOCOL, "provenance": common, "preflight": integrity, "inherited_freeze": inherited})
    torch.set_num_threads(1); torch.use_deterministic_algorithms(True)
    records, receipts, runs = [], {}, {}
    deadline = time.perf_counter()+PROTOCOL["process_limits"]["maximum_campaign_wall_s"]

    def execute(probe_id, repetition=0):
        verify_inputs()
        for name, digest in source_hashes.items():
            if sha(ROOT/name) != digest:
                raise RuntimeError("Acquisition source changed")
        run_id = f"{len(records)+1:02d}--{probe_id}--{'repeat' if repetition else 'primary'}"
        record, traces, decisions, poses, receipt = acquire(case, probe_id, run_id, repetition, output/"runs"/run_id, common, deadline)
        # Persist before checks: unfavorable/invalid output can never vanish.
        with (output/"results.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, allow_nan=False)+"\n")
        records.append(record); receipts[run_id] = receipt; runs[run_id] = (record, traces, decisions, poses, receipt)
        if probe_id != "off":
            baseline = records[0]
            if scientific(record["nodes"][0]) != scientific(baseline["nodes"][0]):
                raise RuntimeError("Pretreatment Stand differs from same-reference baseline")
            if len(record["nodes"]) > 1 and (record["nodes"][1]["start_state"] != baseline["nodes"][1]["start_state"]
                or record["nodes"][1]["walking_reference"] != baseline["nodes"][1]["walking_reference"]):
                raise RuntimeError("First Walk anchor/reference differs before residual authority")
        check = audit_run(record, traces, decisions, receipt, PROTOCOL)
        write_new(output/"runs"/run_id/"independent_audit.json", check)
        if not check["passed"]:
            raise RuntimeError(f"Independent audit failed: {run_id}: {check}")
        print(json.dumps({"completed_run": run_id, "first_walk_local_lateral_m": record["nodes"][1]["lateral_drift_m"] if len(record["nodes"]) > 1 else None,
                          "nominal": record["task_success"], "strict": all(n["strict_success"] for n in record["nodes"]),
                          "physical": record["physical_success"], "endpoint_m": record["ideal_endpoint_error_m"]}), flush=True)
        return run_id

    try:
        off_id = execute("off")
        off, off_trace, _, _, off_audit = runs[off_id]
        if scientific(off) != scientific(original):
            raise RuntimeError("Current residual-off differs from frozen history")
        for name in ("commands", "torques", "base_observations", "base_actions", "residual_observations"):
            if off_audit["streams"][name] != original["observer_audit"]["streams"][name]:
                raise RuntimeError(f"Historical observer stream differs: {name}")
        if off_audit["physics_state_sha256"] != original["observer_audit"]["physics_state_sha256"]:
            raise RuntimeError("Historical full-step state hash differs")
        zero_id = execute("zero")
        zero, zero_trace, _, _, zero_audit = runs[zero_id]
        if scientific(zero) != scientific(off) or scientific(zero_trace) != scientific(off_trace):
            raise RuntimeError("Zero injection changes scientific execution")
        for name in ("commands", "torques", "base_observations", "base_actions"):
            if zero_audit["streams"][name] != off_audit["streams"][name]:
                raise RuntimeError(f"Zero injection changes {name}")
        if zero_audit["physics_state_sha256"] != off_audit["physics_state_sha256"]:
            raise RuntimeError("Zero injection changes physical state")
        write_new(output/"control_gate.json", {"passed": True, "off_matches_historical_science_and_full_step_streams": True,
                                               "zero_matches_off_science_commands_physics": True,
                                               "observation_active_flags_and_original_reward_calls_differ_by_design": True})
        witness = None
        for probe_id in PROFILES:
            run_id = execute(probe_id)
            candidate = summarize([runs[run_id][0]], off, PROTOCOL)
            if candidate["runs"][0]["joint_qualifier"]:
                witness = run_id
                break
        original_id = witness or next(r["run_id"] for r in records if r["probe_id"] == "combined_inward")
        repeat_id = execute(runs[original_id][0]["probe_id"], repetition=1)
        first, first_trace, _, first_poses, first_audit = runs[original_id]
        second, second_trace, _, second_poses, second_audit = runs[repeat_id]
        repeat_exact = (scientific(first) == scientific(second) and scientific(first_trace) == scientific(second_trace)
                        and first_audit == second_audit and all(np.array_equal(first_poses[k], second_poses[k], equal_nan=True) for k in first_poses))
        write_new(output/"repeat_gate.json", {"passed": bool(repeat_exact), "first": original_id, "repeat": repeat_id,
                                              "independent_seed_claim": False})
        if not repeat_exact:
            raise RuntimeError("Deterministic confirmation is not exact")
        summary = summarize(records, off, PROTOCOL)
        write_new(output/"summary.json", summary)
        write_new(output/"integrity_after.json", verify_inputs())
        write_new(output/"completion.json", {"completed_runs": len(records), "verdict": summary["verdict"],
                    "confirmation_exact": True, "unused_optional_probes": [p for p in PROFILES if not any(r["probe_id"] == p for r in records)],
                    "provenance": common, "Phase3A5_started": False})
    except Exception as exc:
        write_new(output/"stopped.json", {"status": "STOPPED_ROOT_CAUSE_AUDIT", "error": repr(exc),
                    "completed_runs": len(records), "provenance": common})
        export(output, common)
        raise
    export(output, common)
    return {"verdict": summary["verdict"], "runs": len(records), "code_commit": code_commit, "protocol_sha256": common["protocol_sha256"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run() if args.run else verify_inputs(), indent=2))
