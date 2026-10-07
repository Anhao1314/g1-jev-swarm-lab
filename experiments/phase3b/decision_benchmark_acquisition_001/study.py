"""Predeclared, finite Phase 3B.0a matrix. Run only from a committed freeze."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import functools
import gzip
import hashlib
import importlib.metadata
import importlib.util
import json
import math
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
from console.capture import tensor_digest
from g1swarm.characterization.perturbations import DisturbanceProxy, PushSpec


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


YAW = load_module("phase3b0a_retained_yaw_study", ROOT / "experiments/phase3a/residual_yaw_component_001/study.py")
OLD = YAW.old
CONTROLLER = YAW.controller
ORACLE = load_module("phase3b0a_frozen_oracle", ROOT / "experiments/phase3b/decision_oracle_001/oracle.py")
MODES = ("CONTINUE", "LATERAL_RECOVERY", "YAW_RECOVERY", "COMBINED_RECOVERY")
FILES = ("cases.json", "protocol.json", "study.py", "test_study.py", "source_manifest.json", "amendment_attempt02.json")
HISTORICAL = ROOT / "experiments/phase3a/residual_yaw_component_001/component_analysis.json"
ATTEMPT01 = HERE / "evidence"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def write_new(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def declarations():
    protocol = json.loads((HERE / "protocol.json").read_text(encoding="utf-8"))
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    return protocol, cases


def amendment() -> dict:
    return json.loads((HERE / "amendment_attempt02.json").read_text(encoding="utf-8"))


def verify_attempt01() -> dict:
    amended = amendment()
    if amended["status"] != "FROZEN_BEFORE_ATTEMPT02_PHYSICS" or amended["new_output"] != {
            "raw": "artifacts/decision_benchmark_acquisition_001_attempt02",
            "export": "experiments/phase3b/decision_benchmark_acquisition_001/evidence_attempt02",
            "manifest": "experiments/phase3b/decision_benchmark_acquisition_001/evidence_manifest_attempt02.json"}:
        raise RuntimeError("Attempt02 amendment scope or output paths changed")
    first = amended["first_attempt"]
    manifest_path = ROOT / first["evidence_manifest"]
    completion_path = ROOT / first["completion"]
    subprocess.check_call(["git", "merge-base", "--is-ancestor", first["evidence_commit"], "HEAD"],
                          cwd=ROOT, stdout=subprocess.DEVNULL)
    committed_manifest = subprocess.check_output(["git", "show", first["evidence_commit"] + ":" + first["evidence_manifest"]], cwd=ROOT)
    if hashlib.sha256(committed_manifest).hexdigest() != first["evidence_manifest_sha256"]:
        raise RuntimeError("First attempt manifest does not match its retained commit")
    if digest(manifest_path) != first["evidence_manifest_sha256"] or digest(completion_path) != first["completion_sha256"]:
        raise RuntimeError("First attempt evidence manifest or completion drift")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for rel, receipt in manifest["files"].items():
        if digest(ROOT / rel) != receipt["sha256"]:
            raise RuntimeError(f"First attempt exported evidence drift: {rel}")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if (completion["stop_reason"] != "INCOMPLETE_OR_UNAUDITED_FOUR_ARM_MATRIX"
            or completion["completed_primary_cells"] != 4
            or set(completion["cell_status"]) != {"sequence-mixed-16m:first-walk-entry:alpha0.5:seed0"}
            or set(completion["cell_status"]["sequence-mixed-16m:first-walk-entry:alpha0.5:seed0"]) != set(MODES)
            or any(v != "AUDIT_FAILED" for v in completion["cell_status"]["sequence-mixed-16m:first-walk-entry:alpha0.5:seed0"].values())):
        raise RuntimeError("First attempt is not the declared nominal audit stop")
    return {"evidence_commit": first["evidence_commit"], "manifest_sha256": first["evidence_manifest_sha256"], "completion_sha256": first["completion_sha256"],
            "verified_exported_files": len(manifest["files"])}


def derive_case(source: dict, state_spec: dict) -> dict:
    if source["id"] != "sequence-mixed-16m" or source["nodes"][1]["parameters"]["target_distance_m"] != 8.0:
        raise ValueError("Source is not frozen Stand-to-Walk8m 16m case")
    case = copy.deepcopy(source)
    case["id"] = state_spec["case_id"]
    case["nodes"][0]["parameters"]["duration_s"] = state_spec["stand_duration_s"]
    if case["nodes"][0]["skill"] != "stand" or case["nodes"][1]["skill"] != "walk_forward":
        raise ValueError("Ineligible transition")
    return case


def action(mode: str, node_index: int, skill: str, tick: int, window_s: float):
    protocol, _ = declarations()
    if mode not in MODES or window_s != 14.0:
        raise ValueError("Undeclared recovery mode or authority window")
    if node_index != 1 or skill != "walk_forward" or not 0 <= tick < 140:
        return np.zeros(3, dtype=np.float64)
    return np.array(protocol["actions"][mode], dtype=np.float64, copy=True)


def preflight(*, require_committed: bool = False) -> dict:
    attempt01 = verify_attempt01()
    protocol, cases = declarations()
    if protocol["mode_order"] != list(MODES) or protocol["maximum_complete_case_executions"] != 16:
        raise RuntimeError("Frozen matrix changed")
    if protocol["fixed"] != {"reference_alpha": 0.5, "origin": "actual-start", "authority_window_s": 14.0,
                              "seed": 0, "torch_threads": 1, "first_walk": "Stand->Walk8m at node index 1",
                              "other_nodes": "Original 2s authority mask and frozen controller; no action outside node 1"}:
        raise RuntimeError("Fixed conditions changed")
    if len(cases["states"]) != 3 or [s["case_id"] for s in cases["states"]] != protocol["case_order"]:
        raise RuntimeError("State membership changed")
    expected_ids = ["sequence-mixed-16m:first-walk-entry:alpha0.5:seed0",
                    "phase3b0a-stand5-16m:first-walk-entry:alpha0.5:seed0",
                    "phase3b0a-push-y60-16m:first-walk-entry:alpha0.5:seed0"]
    if [s["state_id"] for s in cases["states"]] != expected_ids:
        raise RuntimeError("Predeclared state identifiers changed")
    if cases["states"][0]["stand_duration_s"] != 10.0 or cases["states"][0]["push"] is not None:
        raise RuntimeError("Historical nominal construction changed")
    if cases["states"][1]["stand_duration_s"] != 5.0 or cases["states"][1]["push"] is not None:
        raise RuntimeError("Stand5 construction changed")
    if cases["states"][2]["stand_duration_s"] != 10.0 or cases["states"][2]["push"] != {
            "force_n": 60.0, "direction": [0.0, 1.0, 0.0], "duration_s": 0.2, "trigger_sim_time": 9.5}:
        raise RuntimeError("Push construction changed")
    expected_actions = {"CONTINUE": [0.0, 0.0, 0.0], "LATERAL_RECOVERY": [0.0, -1.0, 0.0],
                        "YAW_RECOVERY": [0.0, 0.0, -1.0], "COMBINED_RECOVERY": [0.0, -1.0, -1.0]}
    if protocol["actions"] != expected_actions or not np.array_equal(YAW.BOUNDS, np.array([.1, .06, .12])):
        raise RuntimeError("Recovery actions or physical bounds changed")
    source_path = ROOT / cases["source_case"]
    if digest(source_path) != cases["source_case_sha256"]:
        raise RuntimeError("Historical case drift")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    for state in cases["states"]:
        derive_case(source, state)
    pins = json.loads((HERE / "source_manifest.json").read_text(encoding="utf-8"))
    for rel, expected in pins["files"].items():
        if digest(ROOT / rel) != expected:
            raise RuntimeError(f"Pinned source drift: {rel}")
    historical_sources = json.loads(HISTORICAL.read_text(encoding="utf-8"))["evidence_sources"]
    historical_off = json.loads((ROOT / historical_sources["off"]["result"]["path"]).read_text(encoding="utf-8"))
    current_packages = {name: importlib.metadata.version(name) for name in ("mujoco", "torch", "numpy", "gymnasium")}
    if current_packages != historical_off["provenance"]["packages"]:
        raise RuntimeError("Simulator/runtime package versions differ from fixed14s control")
    pointer_exception = None
    try:
        YAW.verify_inputs(require_committed=require_committed)
    except RuntimeError as exc:
        # Phase 3B.0 legitimately advanced the reviewed selection pointer after
        # 3A.4g. It is the sole drift in 4g's broad source manifest; never
        # exempt a scientific input, executable, model, evaluator or evidence.
        if str(exc) != "Frozen source drift: ops/state.json":
            raise
        retained_protocol = json.loads((YAW.HERE / "protocol.json").read_text())
        retained_pins = json.loads((YAW.HERE / "source_manifest.json").read_text())
        mismatches = [name for name, entry in retained_pins["files"].items()
                      if digest(ROOT / name) != (entry if isinstance(entry, str) else entry["sha256"])]
        if mismatches != ["ops/state.json"]:
            raise RuntimeError(f"Unexpected retained-source drift: {mismatches}")
        actual_plan = tuple((row["id"], row["probe_id"], float(row["window_s"]), row["repetition"])
                            for row in retained_protocol["run_plan"])
        if actual_plan != YAW.RUN_PLAN:
            raise RuntimeError("Retained executable run plan drift")
        if digest(YAW.WINDOW_STUDY / "protocol.json") != retained_protocol["historical_source"]["combined14_protocol_sha256"]:
            raise RuntimeError("Retained combined14 comparison drift")
        if digest(ROOT / "experiments/phase3a/residual_action_composition_001/protocol.json") != retained_protocol["historical_source"]["lateral14_protocol_sha256"]:
            raise RuntimeError("Retained lateral14 comparison drift")
        if require_committed:
            for name in ("controller.py", "study.py", "audit.py", "test_study.py", "protocol.json", "case.json", "source_manifest.json"):
                path = YAW.HERE / name
                rel = path.relative_to(ROOT).as_posix()
                committed = subprocess.check_output(["git", "show", "HEAD:" + rel], cwd=ROOT)
                if hashlib.sha256(committed).hexdigest() != digest(path):
                    raise RuntimeError(f"Uncommitted retained acquisition source: {rel}")
        pointer_exception = "Only reviewed ops/state.json selection pointer advanced after 3A.4g; all other retained pins verified"
    if require_committed:
        for name in FILES:
            path = HERE / name
            rel = path.relative_to(ROOT).as_posix()
            committed = subprocess.check_output(["git", "show", "HEAD:" + rel], cwd=ROOT)
            if hashlib.sha256(committed).hexdigest() != digest(path):
                raise RuntimeError(f"Uncommitted acquisition source: {rel}")
    return {"pinned_sources": len(pins["files"]), "committed_inputs": require_committed,
            "retained_chain_pointer_exception": pointer_exception,
            "historical_package_match": True,
            "attempt01": attempt01,
            "states": [s["state_id"] for s in cases["states"]], "mode_order": list(MODES)}


class AcquisitionRunner(YAW.ProbeRunner):
    def __init__(self, case, probe_id, destination, deadline, *, push_spec):
        super().__init__(case, probe_id, destination, deadline, window_s=14.0)
        self.destination = destination
        self.predecision = None
        self.push_proxy = None
        if push_spec is not None:
            self.push_proxy = DisturbanceProxy(self.sim, PushSpec(
                force_n=push_spec["force_n"], direction=tuple(push_spec["direction"]),
                duration_s=push_spec["duration_s"], trigger_sim_time=push_spec["trigger_sim_time"]))
            self.sim = self.push_proxy
        original_execute = self.router.execute

        def observed_execute(request, context):
            if self.index == 1 and self.skill == "walk_forward":
                data = self.sim._data
                force = np.asarray(data.xfrc_applied)
                self.predecision = {
                    "simulation_time_s": float(data.time),
                    "qpos": data.qpos.tolist(), "qvel": data.qvel.tolist(), "ctrl": data.ctrl.tolist(),
                    "robot_state": self.node_start.to_dict(),
                    "planned_origin": self.planned_origin.tolist(), "planned_heading_rad": float(self.planned_heading),
                    "walking_reference": self._frame_metadata(),
                    "policy_tensors_sha256": tensor_digest(self.base._policy),
                    "push_active": bool(self.push_proxy._active) if self.push_proxy else False,
                    "applied_force_clear": bool(np.array_equal(force, np.zeros_like(force))),
                }
            return original_execute(request, context)

        self.router.execute = observed_execute

    def run(self):
        try:
            return super().run()
        finally:
            if self.push_proxy:
                self.push_proxy.release()
            write_new(self.destination / "predecision.json", self.predecision)
            write_new(self.destination / "disturbance_events.json", self.push_proxy.events if self.push_proxy else [])


@contextmanager
def acquisition_adapter(push_spec):
    original_runner, original_action = OLD.ProbeRunner, YAW.profile_action
    OLD.ProbeRunner = functools.partial(AcquisitionRunner, push_spec=push_spec)
    YAW.profile_action = action
    try:
        with CONTROLLER.isolated_controller():
            yield
    finally:
        OLD.ProbeRunner, YAW.profile_action = original_runner, original_action


def same_predecision(a: dict, b: dict) -> bool:
    return a == b and a is not None and not a["push_active"] and a["applied_force_clear"]


def scientific(value):
    return YAW.scientific(value)


def outcome(record: dict, source: str) -> dict:
    if not record or not record.get("nodes"):
        raise ValueError("No observed skill outcome")
    final = record["final_state"]["base_position"]
    target = record["ideal_endpoint_reference_xy"]
    last = record["nodes"][-1]
    complete = len(record["nodes"]) == 7
    return {"nominal": complete and bool(record["task_success"]),
            "physical": complete and bool(record["physical_success"]),
            "all_strict": complete and all(n["strict_success"] for n in record["nodes"]),
            "final_world_x_error_m": final[0]-target[0], "final_world_y_error_m": final[1]-target[1],
            "final_lateral_error_m": last["ideal_path_lateral_error_m"],
            "final_heading_error_deg": last["ideal_path_heading_error_deg"],
            "endpoint_norm_m": record["ideal_endpoint_error_m"],
            "evidence_source": source + (";INCOMPLETE_ROUTE_NONCOMPARABLE_ENDPOINT" if not complete else "")}


def audit_cell(record: dict, traces: list[dict], decisions: list[dict], receipt: dict,
               case: dict, mode: str, predecision: dict | None, events: list[dict], push_spec) -> dict:
    """Independent local arithmetic check; physics-step authority is checked by retained adapter."""
    checks = {}
    checks["case_and_nodes"] = (record["case_id"] == case["id"] and 0 < len(record["nodes"]) <= len(case["nodes"])
                                and all(n["skill"] == spec["skill"] and n["parameters"] == spec["parameters"]
                                        for n, spec in zip(record["nodes"], case["nodes"])))
    checks["all_node_latches"] = all(record["nodes"][i]["start_state"] == record["nodes"][i-1]["end_state"]
                                  for i in range(1, len(record["nodes"])))
    checks["frozen_alpha_window_and_no_training"] = (record["heading_alignment_alpha"] == .5
              and record["authority_window_s"] == 14.0 and record["PPO_training"] is False)
    checks["full_step_authority_coverage"] = (receipt["full_step_authority_checks"] == receipt["physics_steps"]
                                              and receipt["full_step_authority_violations"] == 0)
    checks["policy_state_digests_recorded"] = all(
        isinstance(receipt.get(name), str) and len(receipt[name]) == 64 and
        all(ch in "0123456789abcdef" for ch in receipt[name])
        for name in ("initial_tensors_sha256", "final_tensors_sha256"))
    checks["no_optimizer"] = receipt["optimizer_updates"] == 0 and receipt["checkpoint_writes"] == 0
    checks["trace_action_schedule"] = all(np.array_equal(row["action"], action(mode, row["node_index"],
            row["skill"], round(row["elapsed_s"]/.1), 14.0) if row["active"] else np.zeros(3)) for row in traces)
    checks["decision_action_schedule"] = all(np.array_equal(row["proposed_action"], action(mode,
            row["node_index"], row["skill"], row["decision_tick"], 14.0)) for row in decisions)
    if push_spec is None:
        checks["disturbance_absent"] = events == []
    else:
        checks["disturbance_end_before_walk"] = (len(events) == 2
            and events[0]["event"] == "push_start" and events[1]["event"] == "push_end"
            and not events[1].get("released", False)
            and abs(events[0]["sim_time"]-9.5) <= .002+1e-8
            and abs(events[1]["sim_time"]-9.7) <= .002+1e-8
            and (predecision is None or (not predecision["push_active"] and predecision["applied_force_clear"])))
    if predecision is not None:
        checks["predecision_matches_result"] = (len(record["nodes"]) > 1
            and predecision["robot_state"] == record["nodes"][1]["start_state"]
            and predecision["walking_reference"] == record["nodes"][1]["walking_reference"])
    return {"checks": checks, "passed": all(checks.values()),
            "observed_terminal_failure": len(record["nodes"]) < len(case["nodes"]),
            "coverage": "retained adapter checks every physics step; this audit checks schedule, source outcome and perturbation release"}


def first_walk_sample(traces: list[dict]) -> dict:
    sample = next((row for row in traces if row["node_index"] == 1), None)
    if sample is None or sample["elapsed_s"] != 0.0:
        raise ValueError("Missing first-Walk entry trace")
    return sample


def decision_state(state_spec: dict, sample: dict) -> dict:
    reference = sample["walking_reference"]
    correction = sample["walking_correction_sample"]
    pose = sample["state_before_command"]["base_position"]
    planned = reference["planned_origin"]
    if sample["skill"] != "walk_forward" or sample["previous_skill"] != "stand":
        raise ValueError("Ineligible decision sample")
    state = {"state_id": state_spec["state_id"],
             "context": {"case_id": state_spec["case_id"], "seed": 0, "decision_epoch": "first_walk_entry",
                         "skill": "Walk8m", "transition": "Stand->Walk8m", "alpha": 0.5,
                         "origin": "actual-start", "reference_id": "midpoint_heading@alpha0.5",
                         "controller_id": "phase3a-frozen-frame-residual-controller",
                         "evaluator_id": "phase3a-original-nominal-strict-physical-and-paired-global",
                         "policy_id": "phase3a-inherited-frozen-unitree-g1-policy",
                         "residual_bounds_id": "vx0.1-vy0.06-yaw0.12",
                         "recovery_contract_id": ORACLE.CONTRACT_ID},
             "observables": {
                 "local_lateral_error_m": correction["lateral_error_m"],
                 "local_heading_error_deg": math.degrees(correction["heading_error_rad"]),
                 "route_x_error_m": pose[0]-planned[0], "route_y_error_m": pose[1]-planned[1],
                 "route_heading_error_deg": math.degrees(reference["measurement_heading_rad"]-reference["planned_heading_rad"]),
                 "reference_heading_deg": math.degrees(reference["control_heading_rad"]),
                 "instantaneous_strict_margin_m": 0.28-abs(correction["lateral_error_m"]),
                 "remaining_distance_m": 8.0, "previous_recovery": None}}
    ORACLE.validate_state(state)
    return state


def observed_differences(a: dict, b: dict) -> dict:
    """Diagnostics only: compare the frozen nine observables, never outcomes."""
    left, right = a["observables"], b["observables"]
    assert set(left) == set(right) == ORACLE.OBSERVABLE_FIELDS
    delta = {key: (None if left[key] is None else right[key]-left[key]) for key in sorted(left)}
    scale = {"route_xy_at_least_0p01m": math.hypot(delta["route_x_error_m"], delta["route_y_error_m"]) >= .01,
             "route_heading_at_least_1deg": abs(delta["route_heading_error_deg"]) >= 1.,
             "reference_heading_at_least_1deg": abs(delta["reference_heading_deg"]) >= 1.}
    return {"raw_right_minus_left": delta, "descriptive_scale_flags": scale,
            "role": "observability diagnostic only; no state membership or outcome gate"}


CONFIRMATION_KEYS = frozenset(("independent_audit", "scientific_record", "scientific_trace",
    "decisions_exact", "poses_exact", "full_step_physics", "predecision_exact"))


def confirmation_passed(checks_by_mode: dict) -> bool:
    return set(checks_by_mode) == set(MODES) and all(
        set(checks) == CONFIRMATION_KEYS and all(checks[key] is True for key in CONFIRMATION_KEYS)
        for checks in checks_by_mode.values())


def nominal_equivalence(mode: str, record: dict, trace: list[dict], receipt: dict,
                        snapshot: dict, historical: dict) -> dict:
    arm = {"CONTINUE": "off", "LATERAL_RECOVERY": "lateral", "YAW_RECOVERY": "yaw",
           "COMBINED_RECOVERY": "combined"}[mode]
    item = historical[arm]
    raw_result = ROOT / item["result"]["path"]
    old_record = json.loads(raw_result.read_text(encoding="utf-8"))
    with gzip.open(ROOT / item["trace"]["path"], "rt", encoding="utf-8") as handle:
        old_trace = [json.loads(line) for line in handle]
    old_receipt = json.loads((ROOT / item["result"]["path"].replace("result.json", "audit.json")).read_text())
    poses = np.load(ROOT / item["result"]["path"].replace("result.json", "poses.npz"))
    exact_time = np.flatnonzero(np.isclose(poses["time_s"], snapshot["simulation_time_s"], atol=1e-8))
    pose_match = len(exact_time) == 1 and np.array_equal(poses["qpos"][exact_time[0]], snapshot["qpos"]) and np.array_equal(poses["qvel"][exact_time[0]], snapshot["qvel"])
    checks = {"scientific_record": scientific(record) == scientific(old_record),
              "scientific_trace": scientific(trace) == scientific(old_trace),
              "full_step_physics": receipt["physics_state_sha256"] == old_receipt["physics_state_sha256"],
              "predecision_qpos_qvel": bool(pose_match),
              "predecision_reference": snapshot["walking_reference"] == old_record["nodes"][1]["walking_reference"],
              "predecision_robot_state": snapshot["robot_state"] == old_record["nodes"][1]["start_state"],
              "initial_policy_state": receipt["initial_tensors_sha256"] == old_receipt["initial_tensors_sha256"],
              "final_policy_state": receipt["final_tensors_sha256"] == old_receipt["final_tensors_sha256"]}
    return {"mode": mode, "checks": checks, "passed": all(checks.values()),
            "retained_result": item["result"], "retained_trace": item["trace"]}


def inherited_nominal(mode: str):
    """Load the SHA-verified first attempt; never rewrite its evidence."""
    run_id = f"01--sequence-mixed-16m--{mode.lower()}--primary"
    base = ATTEMPT01 / "runs" / run_id
    record = json.loads((base / "result.json").read_text(encoding="utf-8"))
    with gzip.open(base / "trace.jsonl.gz", "rt", encoding="utf-8") as handle:
        traces = [json.loads(line) for line in handle]
    with gzip.open(base / "decisions.jsonl.gz", "rt", encoding="utf-8") as handle:
        decisions = [json.loads(line) for line in handle]
    with np.load(base / "poses.npz") as archive:
        poses = {name: archive[name].copy() for name in archive.files}
    receipt = json.loads((base / "audit.json").read_text(encoding="utf-8"))
    snapshot = json.loads((base / "predecision.json").read_text(encoding="utf-8"))
    events = json.loads((base / "disturbance_events.json").read_text(encoding="utf-8"))
    return (record, traces, decisions, poses, receipt), snapshot, events


def evidence_source(state_index: int, case_id: str, mode: str, output: Path) -> str:
    run_id = f"{state_index+1:02d}--{case_id}--{mode.lower()}--primary"
    if state_index == 0:
        source = ATTEMPT01 / "runs" / run_id / "result.json"
        if not source.is_file():
            raise RuntimeError("Inherited nominal evidence source missing")
        checksum = digest(source)
    else:
        raw = output / "runs" / run_id / "result.json"
        if not raw.is_file():
            raise RuntimeError("New acquisition evidence source missing")
        source = HERE / "evidence_attempt02" / "runs" / run_id / "result.json"
        checksum = digest(raw)  # export copies JSON result bytes unchanged
    return f"{source.relative_to(ROOT).as_posix()}#sha256={checksum}"


def export(output: Path, common: dict) -> None:
    target = HERE / "evidence_attempt02"
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
        dest.write_bytes(data)
        inventory[dest.relative_to(ROOT).as_posix()] = {"raw_sha256": hashlib.sha256(raw).hexdigest(),
                                                          "sha256": digest(dest), "bytes": len(data),
                                                          "encoding": "gzip" if source.suffix == ".jsonl" else "identity"}
    write_new(HERE / "evidence_manifest_attempt02.json", {"provenance": common, "files": inventory,
                                                 "all_negative_and_censored_cells_retained": True})


def run():
    preflight(require_committed=True)
    protocol, cases = declarations()
    source = json.loads((ROOT / cases["source_case"]).read_text(encoding="utf-8"))
    historical = json.loads(HISTORICAL.read_text(encoding="utf-8"))["evidence_sources"]
    old_off = json.loads((ROOT / historical["off"]["result"]["path"]).read_text(encoding="utf-8"))
    from g1swarm.frame_learning.campaign import verify_freeze
    inherited = verify_freeze()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_hashes = {name: digest(HERE / name) for name in FILES}
    common = {"experiment_id": protocol["experiment_id"], "protocol_sha256": source_hashes["protocol.json"],
              "case_specs_sha256": source_hashes["cases.json"], "code_commit": commit,
              "audit_amendment_sha256": source_hashes["amendment_attempt02.json"],
              "inherited_attempt01_manifest_sha256": amendment()["first_attempt"]["evidence_manifest_sha256"],
              "source_hashes": source_hashes, "seed": 0, "reference_alpha": 0.5,
              "base_policy_sha256": old_off["provenance"]["base_policy_sha256"],
              "packages": {name: importlib.metadata.version(name) for name in ("mujoco", "torch", "numpy", "gymnasium")},
              "inherited_source_chain": "YAW.verify_inputs and verify_freeze traversed before physics; checkpoint, robot, simulation, controller and evaluator pins",
              "optimizer_updates": 0, "checkpoint_writes": 0, "PPO_training": False}
    output = ROOT / "artifacts/decision_benchmark_acquisition_001_attempt02"
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "manifest.json", {"protocol": protocol, "cases": cases, "provenance": common,
                                         "inherited_freeze": inherited,
                                         "inherited_nominal_evidence": amendment()["first_attempt"],
                                         "run_order": [[s["case_id"], m, "INHERIT_ATTEMPT01" if i == 0 else "EXECUTE_ATTEMPT02"]
                                                       for i, s in enumerate(cases["states"]) for m in MODES]})
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    deadline = time.perf_counter() + protocol["maximum_campaign_wall_s"]
    results, predecisions, cell_status, states, labels = {}, {}, {}, {}, {}
    raw_runs = {}
    stop_reason = None
    try:
        for state_index, state_spec in enumerate(cases["states"]):
            case = derive_case(source, state_spec)
            state_id = state_spec["state_id"]
            results[state_id], predecisions[state_id], cell_status[state_id] = {}, {}, {}
            for mode in MODES:
                preflight(require_committed=True)
                if time.perf_counter() > deadline:
                    stop_reason = "WALL_BUDGET_EXHAUSTED"
                    break
                run_id = f"{state_index+1:02d}--{case['id']}--{mode.lower()}--primary"
                destination = output / "runs" / run_id
                print(json.dumps({"inheriting_run" if state_index == 0 else "starting_run": run_id}), flush=True)
                try:
                    if state_index == 0:
                        data, inherited_snapshot, inherited_events = inherited_nominal(mode)
                    else:
                        with acquisition_adapter(state_spec["push"]):
                            data = OLD.acquire(case, mode, run_id, 0, destination, common, deadline)
                    record, traces, decisions, poses, receipt = data
                    results[state_id][mode] = record
                    predecisions[state_id][mode] = (inherited_snapshot if state_index == 0 else
                        json.loads((destination / "predecision.json").read_text()))
                    raw_runs[(state_id, mode)] = data
                    events = inherited_events if state_index == 0 else json.loads((destination / "disturbance_events.json").read_text())
                    audit = audit_cell(record, traces, decisions, receipt, case, mode,
                                       predecisions[state_id][mode], events, state_spec["push"])
                    write_new(destination / "independent_audit.json", audit)
                    if state_index == 0:
                        write_new(destination / "inherited_source.json", {"run_id": run_id,
                            "source": (ATTEMPT01 / "runs" / run_id).relative_to(ROOT).as_posix(),
                            "source_manifest_sha256": amendment()["first_attempt"]["evidence_manifest_sha256"],
                            "first_attempt_original_status": "AUDIT_FAILED",
                            "amendment": "policy_state_digests_recorded replaces false stationary-policy assertion"})
                    if predecisions[state_id][mode] is None:
                        cell_status[state_id][mode] = "PREDECISION_NOT_REACHED"
                    elif not audit["passed"]:
                        cell_status[state_id][mode] = "AUDIT_FAILED"
                    elif len(record["nodes"]) == len(case["nodes"]):
                        cell_status[state_id][mode] = "COMPLETE"
                    else:
                        cell_status[state_id][mode] = "OBSERVED_TERMINAL_NEGATIVE"
                    write_new(destination / "retained_status.json", {"status": cell_status[state_id][mode]})
                except Exception as exc:
                    cell_status[state_id][mode] = "CENSORED_EXECUTION_ERROR"
                    write_new(destination / "retained_status.json", {"status": "CENSORED_EXECUTION_ERROR",
                                                                       "error": repr(exc)})
                print(json.dumps({"completed_run": run_id, "status": cell_status[state_id][mode]}), flush=True)
            if stop_reason:
                break
            snapshots = predecisions[state_id]
            if set(snapshots) != set(MODES) or not all(same_predecision(snapshots["CONTINUE"], snapshots[m]) for m in MODES):
                stop_reason = "PREDECISION_STATE_MISMATCH_OR_NOT_REACHED"
                break
            initial_policy_digests = {raw_runs[(state_id, mode)][4]["initial_tensors_sha256"] for mode in MODES}
            if len(initial_policy_digests) != 1:
                stop_reason = "INITIAL_POLICY_STATE_MISMATCH"
                break
            if any(cell_status[state_id][m] in {"AUDIT_FAILED", "CENSORED_EXECUTION_ERROR", "PREDECISION_NOT_REACHED"} for m in MODES):
                stop_reason = "INCOMPLETE_OR_UNAUDITED_FOUR_ARM_MATRIX"
                break
            if state_index == 0:
                equivalence = []
                for mode in MODES:
                    record, traces, _, _, receipt = raw_runs[(state_id, mode)]
                    equivalence.append(nominal_equivalence(mode, record, traces, receipt,
                                                           snapshots[mode], historical))
                write_new(output / "nominal_execution_equivalence.json", {"arms": equivalence,
                    "passed": all(item["passed"] for item in equivalence)})
                if not all(item["passed"] for item in equivalence):
                    stop_reason = "NOMINAL_EXECUTION_EQUIVALENCE_FAILED"
                if stop_reason:
                    break
            off_trace = raw_runs[(state_id, "CONTINUE")][1]
            state = decision_state(state_spec, first_walk_sample(off_trace))
            for mode in MODES[1:]:
                compare_state = decision_state(state_spec, first_walk_sample(raw_runs[(state_id, mode)][1]))
                if state != compare_state:
                    stop_reason = "FIRST_TRACE_OBSERVABLE_MISMATCH"
                    break
            if stop_reason:
                break
            states[state_id] = state
            observed = {mode: outcome(results[state_id][mode],
                evidence_source(state_index, case["id"], mode, output)) for mode in MODES}
            entry = {"state_id": state_id, "context_fingerprint": ORACLE.context_fingerprint(state["context"]),
                     "state_fingerprint": ORACLE.state_fingerprint(state), "outcomes": observed}
            label = ORACLE.decide(state, entry)
            labels[state_id] = label
            write_new(output / f"{state_index+1:02d}--oracle_entry.json", {"state": state,
                "catalog_entry": entry, "oracle_label": label, "outcome_completeness": cell_status[state_id]})
            write_new(output / f"{state_index+1:02d}--state_gate.json", {"state_id": state_id,
                "all_four_observed": all(cell_status[state_id][m] in {"COMPLETE", "OBSERVED_TERMINAL_NEGATIVE"} for m in MODES),
                "same_predecision": True, "push_cleared": snapshots["CONTINUE"]["applied_force_clear"],
                "shared_initial_policy_tensors_sha256": next(iter(initial_policy_digests)),
                "shared_predecision_policy_tensors_sha256": snapshots["CONTINUE"]["policy_tensors_sha256"],
                "oracle_label": label})
        if not stop_reason and len(states) == 3:
            keys = list(states)
            diagnostic = {"nominal_to_stand5": observed_differences(states[keys[0]], states[keys[1]]),
                          "nominal_to_push60": observed_differences(states[keys[0]], states[keys[2]]),
                          "stand5_to_push60": observed_differences(states[keys[1]], states[keys[2]])}
            write_new(output / "observability_diagnostic.json", diagnostic)
            first_witness = next((spec for spec in cases["states"] if labels[spec["state_id"]].get("reason") == "UNIQUE_ADMISSIBLE_RECOVERY"), None)
            if first_witness:
                case = derive_case(source, first_witness)
                state_id = first_witness["state_id"]
                repeat_checks = {}
                for mode in MODES:
                    if time.perf_counter() > deadline:
                        stop_reason = "WALL_BUDGET_EXHAUSTED_DURING_CONFIRMATION"
                        break
                    run_id = f"confirm--{case['id']}--{mode.lower()}"
                    destination = output / "runs" / run_id
                    print(json.dumps({"starting_run": run_id}), flush=True)
                    try:
                        with acquisition_adapter(first_witness["push"]):
                            repeated = OLD.acquire(case, mode, run_id, 1, destination, common, deadline)
                        record, traces, decisions, poses, receipt = repeated
                        snapshot = json.loads((destination / "predecision.json").read_text())
                        events = json.loads((destination / "disturbance_events.json").read_text())
                        audit = audit_cell(record, traces, decisions, receipt, case, mode, snapshot,
                                           events, first_witness["push"])
                        write_new(destination / "independent_audit.json", audit)
                        primary = raw_runs[(state_id, mode)]
                        repeat_checks[mode] = {"independent_audit": audit["passed"],
                            "scientific_record": scientific(record) == scientific(primary[0]),
                            "scientific_trace": scientific(traces) == scientific(primary[1]),
                            "decisions_exact": decisions == primary[2],
                            "poses_exact": poses.keys() == primary[3].keys() and all(
                                np.array_equal(poses[k], primary[3][k], equal_nan=True) for k in poses),
                            "full_step_physics": receipt["physics_state_sha256"] == primary[4]["physics_state_sha256"],
                            "predecision_exact": same_predecision(predecisions[state_id][mode], snapshot)}
                        write_new(destination / "retained_status.json", {"status": "CONFIRMATION_COMPLETE",
                            "exact": all(repeat_checks[mode].values())})
                    except Exception as exc:
                        repeat_checks[mode] = {"censored": repr(exc)}
                        write_new(destination / "retained_status.json", {"status": "CENSORED_CONFIRMATION_ERROR", "error": repr(exc)})
                    print(json.dumps({"completed_run": run_id, "checks": repeat_checks[mode]}), flush=True)
                confirmed = confirmation_passed(repeat_checks)
                write_new(output / "conditional_confirmation.json", {"state_id": state_id,
                    "checks": repeat_checks, "passed": confirmed})
                if not confirmed and stop_reason is None:
                    stop_reason = "CONDITIONAL_CONFIRMATION_FAILED_OR_CENSORED"
        write_new(output / "primary_completion.json", {"cell_status": cell_status, "stop_reason": stop_reason,
            "completed_primary_cells": sum(len(x) for x in cell_status.values()),
            "oracle_labels": labels, "complete_labeled_states": len(states),
            "conditional_confirmation": "conditional_confirmation.json" if (output / "conditional_confirmation.json").exists() else None})
    finally:
        export(output, common)
    return {"stop_reason": stop_reason, "cell_status": cell_status, "code_commit": commit}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run() if args.run else preflight(), indent=2))
