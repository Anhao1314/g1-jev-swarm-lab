"""Exactly one residual-action composition intervention at frozen 14 s authority."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import functools
import gzip
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
OLD = ROOT / "experiments/phase3a/residual_authority_feasibility_001"
WINDOW_STUDY = ROOT / "experiments/phase3a/residual_authority_window_001"

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

old = load_module("authority_window_historical_study", OLD / "study.py")
controller = load_module("authority_window_isolated_controller", HERE / "controller.py")
from console.capture import CaptureSimulation, tensor_digest
from g1swarm.transition_learning.env import BOUNDS, PAIRS, WINDOW, QUANTUM_STEPS
sha, write_new = old.sha, old.write_new
RUN_PLAN = (("01--lateral14--primary", "lateral_only", 14.0, 0),
            ("02--lateral14--confirm", "lateral_only", 14.0, 1))

def validate_window(value):
    if value != 14.0:
        raise ValueError("Only frozen 14 s authority is allowed")
    return float(value)

def profile_action(probe_id, node_index, skill, decision_tick, window_s):
    window_s = validate_window(window_s)
    if probe_id != "lateral_only":
        raise ValueError("Only lateral-only action is declared")
    if node_index != 1 or skill != "walk_forward" or not 0 <= decision_tick < round(window_s / .1):
        return np.zeros(3, dtype=np.float64)
    return np.array([0., -1., 0.], dtype=np.float64)

def scientific(value):
    if isinstance(value, dict):
        return {k: scientific(v) for k, v in value.items()
                if k not in old.METADATA | {"authority_window_s", "observation_active"}}
    if isinstance(value, list):
        return [scientific(v) for v in value]
    return value

def verify_inputs(require_committed=False):
    protocol = json.loads((HERE / "protocol.json").read_text())
    pins = json.loads((HERE / "source_manifest.json").read_text())
    if protocol.get("frozen") is not True:
        raise RuntimeError("Protocol must be frozen before execution")
    if protocol["authority"]["window_s"] != 14.0 or WINDOW != 2.0 or QUANTUM_STEPS != 50:
        raise RuntimeError("Authority duration/cadence differs from predeclaration")
    if protocol["reference_alpha"] != .5 or protocol["authority"]["legacy_window_s"] != 2.0:
        raise RuntimeError("Fixed reference alpha or legacy observation window changed")
    expected_probe = [{"id": "lateral_only", "action": [0, -1, 0], "onset_s": 0.0, "end_s": 14.0}]
    if protocol["probes_in_order"] != expected_probe:
        raise RuntimeError("Fixed lateral-only profile changed")
    budget = protocol["budget"]
    if (budget["maximum_complete_case_executions"] != 2 or budget["control_runs"] != 0
        or budget["longer_window_primary_runs"] != 1 or budget["confirmation_runs"] != 1
        or budget["windows_tested_s"] != [14.0] or budget["window_scan"] or budget["alpha_scan"] or budget["action_scan"]
        or any(budget[key] != 0 for key in ("checkpoint_writes", "provider_calls", "training_steps"))
        or protocol["process_limits"]["maximum_campaign_wall_s"] != 180):
        raise RuntimeError("Frozen run budget differs")
    if not np.array_equal(BOUNDS, protocol["authority"]["physical_bounds"]):
        raise RuntimeError("Residual bounds differ")
    if sha(HERE / "case.json") != protocol["case_sha256"]:
        raise RuntimeError("Frozen case drift")
    if sha(HERE / "source_manifest.json") != protocol["source_manifest_sha256"]:
        raise RuntimeError("Frozen source manifest drift")
    for name, entry in pins["files"].items():
        expected = entry if isinstance(entry, str) else entry["sha256"]
        if sha(ROOT / name) != expected:
            raise RuntimeError(f"Frozen source drift: {name}")
    sources = ("controller.py", "study.py", "audit.py", "test_study.py", "protocol.json", "case.json", "source_manifest.json")
    actual_plan = tuple((row["id"], row["probe_id"], float(row["window_s"]), row["repetition"]) for row in protocol["run_plan"])
    if actual_plan != RUN_PLAN:
        raise RuntimeError("Frozen run plan differs from executable plan")
    if sha(WINDOW_STUDY / "protocol.json") != protocol["historical_source"]["combined14_protocol_sha256"]:
        raise RuntimeError("Retained 14 s comparison protocol drift")
    if require_committed:
        for name in sources:
            path = HERE / name
            committed = subprocess.check_output(["git", "show", "HEAD:" + path.relative_to(ROOT).as_posix()], cwd=ROOT)
            if hashlib.sha256(committed).hexdigest() != sha(path):
                raise RuntimeError(f"Acquisition input not committed before physics: {name}")
    return {"pinned_files_verified": len(pins["files"]), "historical_drift": False,
            "acquisition_sources_committed": require_committed}

class ProbeRunner(old.FrameRunner):
    """Use original action injection; additions only observe and select probes."""
    def __init__(self, case, probe_id, destination, deadline, *, window_s):
        self.authority_window_s = validate_window(window_s)
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
            action = profile_action(probe_id, self.index, self.skill, tick, self.authority_window_s)
            row = {"node_index": self.index, "skill": self.skill, "decision_tick": tick,
                   "time_s": self.sim.simulation_time, "elapsed_s": elapsed,
                   "active": elapsed < self.mask_window()-1e-9,
                   "observation_active": elapsed < WINDOW-1e-9,
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
            active = self.treatment == "learned" and eligible and elapsed < self.mask_window()-1e-9
            expected_action = profile_action(probe_id, self.index, self.skill, self.node_steps // QUANTUM_STEPS, self.authority_window_s) if active else np.zeros(3)
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

    def mask_window(self):
        return self.authority_window_s if self.index == 1 and self.skill == "walk_forward" else WINDOW

    def run(self):
        record = super().run()
        record["authority_window_s"] = self.authority_window_s
        return record

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


@contextmanager
def acquisition_adapter(window_s):
    """Reuse retained capture/export mechanics without editing their source."""
    original = old.ProbeRunner
    old.ProbeRunner = functools.partial(ProbeRunner, window_s=validate_window(window_s))
    try:
        with controller.isolated_controller():
            yield
    finally:
        old.ProbeRunner = original


def acquire(case, probe_id, run_id, repetition, destination, common, deadline, window_s):
    with acquisition_adapter(window_s):
        return old.acquire(case, probe_id, run_id, repetition, destination, common, deadline)


def retained(run_id):
    base = OLD / "evidence/runs" / run_id
    record = json.loads((base / "result.json").read_text())
    receipt = json.loads((base / "audit.json").read_text())
    trace = [json.loads(row) for row in gzip.decompress((base / "trace.jsonl.gz").read_bytes()).splitlines()]
    poses = dict(np.load(base / "poses.npz"))
    return record, trace, receipt, poses


def equality_gate(new, historical, *, zero=False):
    record, trace, decisions, poses, receipt = new
    old_record, old_trace, old_receipt, old_poses = historical
    checks = {"scientific_record": scientific(record) == scientific(old_record),
              "scientific_trace": scientific(trace) == scientific(old_trace),
              "full_step_physics": receipt["physics_state_sha256"] == old_receipt["physics_state_sha256"],
              "poses": poses.keys() == old_poses.keys() and all(np.array_equal(poses[k], old_poses[k], equal_nan=True) for k in poses)}
    names = ("commands", "torques", "base_observations", "base_actions")
    if not zero:
        names += ("residual_observations", "rewards")
    for name in names:
        checks["stream_" + name] = receipt["streams"][name] == old_receipt["streams"][name]
    for name in ("initial_tensors_sha256", "final_tensors_sha256", "rng_after_sha256", "physics_steps",
                 "full_step_authority_checks", "full_step_authority_violations", "optimizer_updates", "checkpoint_writes"):
        checks["receipt_" + name] = receipt[name] == old_receipt[name]
    checks["passed"] = all(checks.values())
    checks["zero_control_observation_active_and_reward_callbacks_exempt"] = zero
    return checks


def export(output, common):
    target = HERE / "evidence"
    target.mkdir(exist_ok=False)
    inventory = {}
    for source in sorted(output.rglob("*")):
        if not source.is_file():
            continue
        dest = target / source.relative_to(output)
        if source.suffix == ".jsonl":
            dest = dest.with_suffix(".jsonl.gz")
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = source.read_bytes()
        data = gzip.compress(raw, mtime=0) if source.suffix == ".jsonl" else raw
        with dest.open("xb") as handle:
            handle.write(data)
        inventory[dest.relative_to(ROOT).as_posix()] = {
            "raw_path": source.relative_to(ROOT).as_posix(), "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "sha256": sha(dest), "bytes": len(data), "encoding": "gzip" if source.suffix == ".jsonl" else "identity"}
    write_new(HERE / "evidence_manifest.json", {"provenance": common, "files": inventory, "negative_results_retained": True})


def run():
    import copy
    auditor = load_module("composition_offline_audit", HERE / "audit.py")
    protocol = json.loads((HERE / "protocol.json").read_text())
    integrity = verify_inputs(require_committed=True)
    from g1swarm.frame_learning.campaign import verify_freeze
    inherited = verify_freeze()  # Read-only hashes/configuration; no rollouts or training.
    case = json.loads((HERE / "case.json").read_text())
    old_off = retained("01--off--primary")
    for gate_name in ("historical_combined2_gate.json", "zero14_gate.json", "repeat_gate.json"):
        gate = json.loads((WINDOW_STUDY / "evidence" / gate_name).read_text())
        if gate.get("passed") is not True:
            raise RuntimeError(f"Retained comparison gate failed: {gate_name}")
    code_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in (HERE / name for name in ("study.py", "controller.py", "audit.py", "test_study.py", "protocol.json", "case.json", "source_manifest.json"))}
    common = {"experiment_id": protocol["experiment_id"], "protocol_sha256": sha(HERE / "protocol.json"),
              "case_sha256": protocol["case_sha256"], "source_manifest_sha256": protocol["source_manifest_sha256"],
              "contract_sha256": old_off[0]["provenance"]["contract_sha256"],
              "base_policy_sha256": old_off[0]["provenance"]["base_policy_sha256"],
              "code_commit": code_commit, "source_hashes": source_hashes, "seed": 0, "torch_threads": 1,
              "packages": {name: importlib.metadata.version(name) for name in ("mujoco", "torch", "numpy", "gymnasium")},
              "optimizer_updates": 0, "checkpoint_writes": 0, "PPO_training": False, "reference_alpha": .5}
    output = ROOT / "artifacts/residual_action_composition_001"
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "manifest.json", {"protocol": protocol, "provenance": common, "preflight": integrity, "inherited_freeze": inherited, "run_plan": RUN_PLAN})
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    budget = protocol.get("process_limits", {}).get("maximum_campaign_wall_s", 180)
    if budget != 180:
        raise RuntimeError("Only the fixed 180 s campaign budget is permitted")
    deadline = time.perf_counter() + budget
    records, runs, receipts = [], {}, {}
    try:
        for run_id, probe_id, window_s, repetition in RUN_PLAN:
            verify_inputs(require_committed=True)
            if time.perf_counter() > deadline:
                raise RuntimeError("Campaign wall budget exhausted before next run")
            print(json.dumps({"starting_run": run_id, "authority_window_s": window_s}), flush=True)
            run_common = {**common, "authority_window_s": window_s}
            data = acquire(case, probe_id, run_id, repetition, output / "runs" / run_id, run_common, deadline, window_s)
            record, traces, decisions, poses, receipt = data
            with (output / "results.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, allow_nan=False) + "\n")
            records.append(record)
            runs[run_id], receipts[run_id] = data, receipt
            per_run = copy.deepcopy(protocol)
            per_run["authority"]["window_s"] = window_s
            for profile in per_run["probes_in_order"]:
                profile["end_s"] = window_s
            check = auditor.audit_run(record, traces, decisions, receipt, per_run)
            write_new(output / "runs" / run_id / "independent_audit.json", check)
            if not check["passed"]:
                raise RuntimeError(f"Independent audit failed: {run_id}")
            if len(record["nodes"]) != len(case["nodes"]):
                raise RuntimeError(f"Incomplete sequence: {run_id}; preserve negative outcome")
            if scientific(record["nodes"][0]) != scientific(old_off[0]["nodes"][0]):
                raise RuntimeError("Pretreatment Stand differs")
            if record["nodes"][1]["start_state"] != old_off[0]["nodes"][1]["start_state"] or record["nodes"][1]["walking_reference"] != old_off[0]["nodes"][1]["walking_reference"]:
                raise RuntimeError("First Walk anchor/reference differs")
            print(json.dumps({"completed_run": run_id, "first_walk_local_lateral_m": record["nodes"][1]["lateral_drift_m"],
                              "nominal": record["task_success"], "strict": all(n["strict_success"] for n in record["nodes"]),
                              "physical": record["physical_success"], "endpoint_m": record["ideal_endpoint_error_m"]}), flush=True)
            if repetition == 0:
                preliminary = auditor.summarize(records, old_off[0], protocol)
                write_new(output / "primary_gate.json", preliminary)
                if not preliminary["runs"][0]["joint_qualifier"]:
                    break  # predeclared early stop: no confirmation of a failed joint gate
        if len(records) == 2:
            primary, repeat = runs[RUN_PLAN[0][0]], runs[RUN_PLAN[1][0]]
            gate = equality_gate(repeat, (primary[0], primary[1], primary[4], primary[3]))
            gate["decisions_exact"] = primary[2] == repeat[2]
            gate["receipt_exact"] = primary[4] == repeat[4]
            gate["passed"] = gate["passed"] and gate["decisions_exact"] and gate["receipt_exact"]
            gate["independent_seed_claim"] = False
            write_new(output / "repeat_gate.json", gate)
            if not gate["passed"]:
                raise RuntimeError("Lateral-only deterministic repeat differs")
        summary = auditor.summarize(records, old_off[0], protocol)
        write_new(output / "summary.json", summary)
        write_new(output / "integrity_after.json", verify_inputs(require_committed=True))
        write_new(output / "completion.json", {"completed_runs": len(records), "verdict": summary.get("verdict"),
                   "confirmation_exact": len(records) == 2, "confirmation_skipped_after_primary_joint_failure": len(records) == 1,
                   "provenance": common, "Phase3A5_started": False,
                   "controller_restored": controller.legacy._Controller is controller.ORIGINAL_CONTROLLER})
    except Exception as exc:
        write_new(output / "stopped.json", {"status": "STOPPED_ROOT_CAUSE_AUDIT", "error": repr(exc),
                   "completed_runs": len(records), "provenance": common,
                   "controller_restored": controller.legacy._Controller is controller.ORIGINAL_CONTROLLER})
        export(output, common)
        raise
    export(output, common)
    return {"verdict": summary.get("verdict"), "runs": len(records), "code_commit": code_commit,
            "protocol_sha256": common["protocol_sha256"]}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run() if args.run else verify_inputs(), indent=2))
