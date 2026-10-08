"""M2.4 write-once acquisition adapter. Import/preflight never creates physics.

The injectable backend changes instrumentation resources, not stage orchestration.
Real acquisition needs both explicit authorization and an independently frozen receipt.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import platform
import math
import os
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
READINESS = ROOT / "experiments/m2/cross_state_reliability_readiness_001"
for import_root in (ROOT, ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf8", newline="\n") as stream:
        json.dump(evidence_value(value), stream, indent=2, allow_nan=False)
        stream.write("\n")


def evidence_value(value):
    """Lossless explicit nonfinite labels for evidence; never used for authority inputs."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": repr(value)}
    if isinstance(value, dict):
        return {key: evidence_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [evidence_value(item) for item in value]
    return value


def preflight(*, root=ROOT, here=HERE):
    """Verify every pinned source/asset/dependency without importing live modules."""
    root, here = Path(root), Path(here)
    manifest = json.loads((here / "source_manifest.json").read_text(encoding="utf8"))
    if not manifest.get("files") or not manifest.get("dependencies_sha256"):
        raise ValueError("Incomplete source/dependency freeze")
    required = {(here / name).relative_to(root).as_posix() for name in ("acquire.py", "protocol.json")}
    if not required <= set(manifest["files"]):
        raise ValueError("Adapter/protocol absent from freeze")
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or digest(path) != expected:
            raise ValueError("Frozen source/asset mismatch: " + name)
    dependency_path = root / "experiments/m2/cross_state_reliability_readiness_001/dependencies.json"
    if digest(dependency_path) != manifest["dependencies_sha256"]:
        raise ValueError("Dependency receipt changed")
    dependency_lock = json.loads(dependency_path.read_text(encoding="utf8"))
    if platform.python_version() != dependency_lock["python"] or Path(sys.executable).resolve() != Path(dependency_lock["executable"]).resolve():
        raise ValueError("Frozen interpreter mismatch")
    for package, expected in dependency_lock["packages"].items():
        if importlib.metadata.version(package) != expected:
            raise ValueError("Dependency mismatch: " + package)
    spec = json.loads((here / "protocol.json").read_text(encoding="utf8"))
    frozen_design = json.loads((root / "experiments/m2/cross_state_reliability_design_001/protocol.json").read_text(encoding="utf8"))
    if digest(root / "experiments/m2/cross_state_reliability_design_001/protocol.json") != manifest["design_protocol_sha256"]:
        raise ValueError("Frozen design protocol changed")
    for key in frozen_design:
        if key in ("experiment_id", "status", "physics_authorized", "required_before_future_acquisition"):
            continue
        if spec[key] != frozen_design[key]:
            raise ValueError("Frozen design membership changed: " + key)
    return {"status": "OFFLINE_PREFLIGHT_VERIFIED_NO_PHYSICS", "manifest_sha256": digest(here / "source_manifest.json"), "spec": spec}


def verify_readiness(readiness_sha256, *, here=HERE, readiness=READINESS, root=ROOT):
    path = Path(readiness) / "readiness_manifest.json"
    if not readiness_sha256 or digest(path) != readiness_sha256:
        raise ValueError("Exact immutable readiness binding required")
    receipt = json.loads(path.read_text(encoding="utf8"))
    if receipt.get("source_manifest_sha256") != digest(Path(here) / "source_manifest.json") or receipt.get("status") != "READY_FOR_FROZEN_ACQUISITION" or receipt.get("physics_authorized") is not False:
        raise ValueError("Readiness freeze unavailable or stale")
    for name, expected in receipt.get("files", {}).items():
        if digest(Path(root) / name) != expected:
            raise ValueError("Readiness evidence changed: " + name)
    return receipt


@contextmanager
def production_backend(spec, cell, run_dir, campaign):
    """Lazy real resources; never called by preflight or unapproved acquire."""
    import numpy as np
    import mujoco
    from g1swarm.config import load_yaml
    from g1swarm.mission import LiveMissionSession, MissionExecutor, MissionValidator
    from g1swarm.simulation.g1_simulation import G1Simulation
    from g1swarm.characterization.perturbations import DisturbanceProxy, PushSpec
    from scripts.run_oracle_missions import load_protocol, build_grounder
    from experiments.m2.trusted_handoff_qualification_001 import acquire as old
    protocol = load_protocol(spec["contracts"]["runtime_protocol"])
    robot = load_yaml(protocol["robot_config"])
    halt = json.loads((ROOT / spec["contracts"]["halt_contract"]).read_text(encoding="utf8"))
    state_spec = next((row for row in spec["states"] if row["id"] == cell["state_id"]), {})
    poses = old.PoseCollector()
    holder, pushes = {}, []
    original_step, original_node, original_reset = G1Simulation.step, LiveMissionSession.run_node, G1Simulation.reset
    original_native = mujoco.mj_step
    original_reset_data, original_keyframe = mujoco.mj_resetData, mujoco.mj_resetDataKeyframe
    original_halt = LiveMissionSession.run_failure_halt
    native_count = [0]
    initialized = [False]
    push = state_spec.get("push")
    first_walk = [None]
    raw_rows = []
    journal = (run_dir / "native_incremental.jsonl").open("x", encoding="utf8", newline="\n", buffering=1)

    def reset_data(*args, **kwargs):
        if initialized[0]:
            holder["integrity_failure"] = "POST_INITIALIZATION_NATIVE_RESET_FORBIDDEN"
            raise ValueError(holder["integrity_failure"])
        return original_reset_data(*args, **kwargs)

    def keyframe(*args, **kwargs):
        holder["integrity_failure"] = "KEYFRAME_RESET_FORBIDDEN"
        raise ValueError(holder["integrity_failure"])

    def halt_call(session, contract):
        if not np.all(session.simulation._data.xfrc_applied == 0):
            holder["integrity_failure"] = "FORCE_NOT_ZERO_BEFORE_HALT"
            raise ValueError(holder["integrity_failure"])
        return original_halt(session, contract)

    def reset(sim, *args, **kwargs):
        if initialized[0]:
            holder["integrity_failure"] = "POST_INITIALIZATION_RESET_FORBIDDEN"
            raise ValueError(holder["integrity_failure"])
        return original_reset(sim, *args, **kwargs)

    def native(*args, **kwargs):
        try:
            campaign.guard(cell, native_count[0], stepping=True)
        except (TimeoutError, RuntimeError) as exc:
            holder["native_budget_failure"] = str(exc)
            raise
        result = original_native(*args, **kwargs)
        native_count[0] += 1
        campaign.native_steps += 1
        data = args[1]
        controller = getattr(session, "controller", None)
        memory = {name: np.asarray(getattr(controller, name)).tolist() for name in ("_action", "_target", "_counter") if hasattr(controller, name)}
        raw_rows.append({"time_s": float(data.time), "qpos": data.qpos.tolist(), "qvel": data.qvel.tolist(), "ctrl": data.ctrl.tolist(), "xfrc_applied": data.xfrc_applied.tolist(), "controller": memory})
        journal.write(json.dumps(evidence_value(raw_rows[-1]), allow_nan=False) + "\n")
        return result

    def wrapper(monitor):
        proxy = None
        if push and first_walk[0] is not None:
            proxy = DisturbanceProxy(monitor, PushSpec(force_n=push["force_n"], direction=tuple(push["direction_world"]), duration_s=push["duration_s"], trigger_sim_time=first_walk[0] + push["relative_first_walk_trigger_s"]))
            pushes.append(proxy)
        return poses.wrap(proxy or monitor)

    def node(session, node, mode):
        if push and node.skill.value == "walk_forward" and first_walk[0] is None:
            first_walk[0] = float(session.simulation._data.time)
        try:
            return original_node(session, node, mode)
        finally:
            for proxy in pushes:
                proxy.release()
            session.simulation.clear_applied_forces()

    G1Simulation.reset, LiveMissionSession.run_node, mujoco.mj_step = reset, node, native
    mujoco.mj_resetData, mujoco.mj_resetDataKeyframe, LiveMissionSession.run_failure_halt = reset_data, keyframe, halt_call
    session = None
    try:
        with old.execution_witness(maximum_steps=cell["max_steps"], maximum_wall_s=cell["max_wall_s"]) as witness:
            session = LiveMissionSession(robot_config=robot, protocol=protocol, seed=spec["seed"], simulation_wrapper=wrapper)
            initialized[0] = True
            if witness["reset_calls"] != 2 or witness["reset_data_calls"] != 2 or witness["reset_keyframe_calls"]:
                raise ValueError("Startup reset witness mismatch")
            poses.capture(session.simulation)
            def forbidden_factory(seed):
                raise ValueError("EXTERNAL_SESSION_FACTORY_FORBIDDEN")
            executor = MissionExecutor(validator=MissionValidator(), grounder=build_grounder(protocol), session_factory=forbidden_factory, protocol=protocol, recorder_root=str(run_dir / "ledger"), seed=spec["seed"], provenance={"study": spec["experiment_id"], "source_manifest_sha256": digest(HERE / "source_manifest.json")}, walk_strict_gate=True, physical_halt_contract=halt)
            holder.update(session=session, executor=executor, witness=witness, helpers=old, poses=poses, protocol=protocol,
                          force_zero=lambda: bool(np.all(session.simulation._data.xfrc_applied == 0)), native_count=native_count, raw_rows=raw_rows, push_events=lambda: [event for proxy in pushes for event in proxy.events])
            yield holder
    finally:
        journal.close()
        if session is not None:
            session.simulation.clear_applied_forces()
            session.close()
        G1Simulation.reset, LiveMissionSession.run_node, mujoco.mj_step = original_reset, original_node, original_native
        mujoco.mj_resetData, mujoco.mj_resetDataKeyframe, LiveMissionSession.run_failure_halt = original_reset_data, original_keyframe, original_halt


class CampaignBudget:
    def __init__(self, spec):
        self.spec, self.started, self.arm_started, self.native_steps = spec, time.perf_counter(), time.perf_counter(), 0

    def guard(self, cell, arm_steps, *, stepping=False):
        now = time.perf_counter()
        if now - self.started >= 840 or now - self.arm_started >= 120:
            raise TimeoutError("HARD_WALL_BUDGET")
        if stepping and (arm_steps >= cell["max_steps"] or self.native_steps >= 270000):
            raise RuntimeError("HARD_NATIVE_STEP_BUDGET")


def run_arm(spec, cell, run_dir, backend, campaign, expected_predecision=None):
    """Shared production/fake orchestration, including conditional missing coverage."""
    from g1swarm.mission.ir import Mission
    from g1swarm.mission.lifecycle import MissionLifecycle
    from g1swarm.mission.trusted_handoff import TrustedMissionHandoff, CONTINUATION_PERMISSION
    from g1swarm.trusted_handoff_v0 import TestPrincipalAuthority, OfflineHandoff, full_plan_json
    requests, events, entries = [], [], []
    runtime = None
    lifecycle = None
    watchdog = None
    outcome = {"state_id": cell["state_id"], "arm": cell["arm"], "status": "PARTIAL_STOPPED", "coverage": "NOT_ISSUED"}
    campaign.arm_started = time.perf_counter()
    def hard_timeout():
        # Independent wall watchdog: also fires when policy/native code never returns.
        # Emergency evidence is a distinct append-only artifact, not a result rewrite.
        emergency = {"status": "PARTIAL_STOPPED", "reason": "HARD_WALL_WATCHDOG", "cell": cell, "outcome_at_timeout": outcome, "requests": requests, "dispatch_entries": entries}
        if runtime is not None:
            emergency["witness"] = runtime["witness"]
            emergency["native_state_trace"] = runtime.get("raw_rows", [])
            try:
                runtime["session"].simulation.clear_applied_forces()
                emergency["force_clear_attempted"] = True
                emergency["force_zero_after_clear"] = runtime["force_zero"]()
            except BaseException as exc:
                emergency["force_clear_error"] = str(exc)
        try:
            write_new(run_dir / "hard_watchdog_partial.json", emergency)
        finally:
            os._exit(124)
    if backend is production_backend:
        remaining = min(120, 840 - (time.perf_counter() - campaign.started))
        watchdog = threading.Timer(max(0.001, remaining), hard_timeout)
        watchdog.daemon = True
        watchdog.start()
    try:
        with backend(spec, cell, run_dir, campaign) as runtime:
            session, executor, witness, old = (runtime[key] for key in ("session", "executor", "witness", "helpers"))
            state_spec = next((row for row in spec["states"] if row["id"] == cell["state_id"]), None)
            parent_input = state_spec["parent_mission"] if state_spec else spec["normal_control"]
            parent = executor.run(deepcopy(parent_input), existing_session=session, phase="m24_parent")
            if runtime.get("integrity_failure"):
                raise ValueError("INTEGRITY_EXCEPTION_CAPTURED_BY_EXECUTOR:" + runtime["integrity_failure"])
            if witness.get("budget_failure") or runtime.get("native_budget_failure"):
                raise RuntimeError("BUDGET_EXCEPTION_CAPTURED_BY_EXECUTOR")
            runtime["poses"].capture(session.simulation)
            write_new(run_dir / "parent_result.json", parent.to_dict())
            parent_sha, graph = digest(run_dir / "parent_result.json"), deepcopy(executor.last_graph.to_dict())
            parent_document = deepcopy(parent.to_dict())
            write_new(run_dir / "parent_graph.json", graph)
            ledger = old.ledger_hashes(run_dir / "ledger")
            predecision = deepcopy(witness["trace"])
            write_new(run_dir / "predecision_trace.json", predecision)
            write_new(run_dir / "predecision_native_trace.json", deepcopy(runtime.get("raw_rows", [])))
            current_predecision = (run_dir / "predecision_trace.json").read_bytes() + (run_dir / "predecision_native_trace.json").read_bytes()
            if expected_predecision is not None and current_predecision != expected_predecision:
                raise ValueError("PAIRED_PREDECISION_TRACE_MISMATCH")
            write_new(run_dir / "halt_endpoint.json", old.snapshot(session, witness))
            if cell["state_id"] == "seen_reference_walk6":
                retained_spec = json.loads((ROOT / "experiments/m2/trusted_handoff_qualification_001/protocol.json").read_text(encoding="utf8"))
                comparator = ROOT / retained_spec["comparators"]["historical_invalid"]
                if not old.trace_equal(predecision, comparator / "state_trace.jsonl.gz"):
                    raise ValueError("SEEN_ANCHOR_TRACE_MISMATCH")
                old.verify_pose_prefix(runtime["poses"], comparator / "poses.npz")
            if not runtime["force_zero"]():
                raise ValueError("FORCE_NOT_ZERO_BEFORE_ASSESSMENT")
            if state_spec is None:
                normal_checks = {"mission_success": parent.to_dict()["mission_success"], "physical_success": parent.to_dict()["physical_success"], "three_nodes_completed": parent.to_dict()["completed_nodes"] == 3, "no_halt_requested": not parent.physical_halt}
                outcome.update(status="NORMAL_CONTROL" if all(normal_checks.values()) else "NORMAL_CONTROL_REGRESSION", normal_control_checks=normal_checks, parent=parent.to_dict(), coverage="NOT_APPLICABLE")
                return outcome
            halt = parent.physical_halt or {}
            if not halt:
                outcome.update(status="NO_HALT_TRIGGER", parent=parent.to_dict())
                return outcome
            if halt.get("status") != "HALT_SUCCEEDED":
                outcome.update(status="HALT_FAILED", parent=parent.to_dict())
                return outcome
            mission = Mission.from_dict(deepcopy(spec["new_mission"]))
            try:
                lifecycle = MissionLifecycle(executor=executor, session=session, parent_result=parent, session_id=cell["state_id"] + "--" + cell["arm"], parent_receipt_sha256=parent_sha)
                assessment = lifecycle.assess(mission)
            except (TypeError, ValueError, AttributeError) as exc:
                outcome.update(status="MISSING_EVIDENCE", decision="ESCALATE", reason=str(exc))
                return outcome
            write_new(run_dir / "assessment.json", assessment)
            if not assessment["eligible"]:
                outcome.update(status="INELIGIBLE", reasons=assessment["reasons"])
                return outcome
            canonical = full_plan_json(mission).encode("utf8")
            plan_sha = hashlib.sha256(canonical).hexdigest()
            if plan_sha != spec["expected_complete_plan_sha256"]:
                raise ValueError("CANONICAL_PLAN_MISMATCH")
            authority, handoff = TestPrincipalAuthority(), OfflineHandoff()
            principal, display = "m24-test-principal", "m24-display-only"
            bridge = TrustedMissionHandoff(lifecycle=lifecycle, handoff=handoff, authority=authority, permissions={(principal, plan_sha): {CONTINUATION_PERMISSION}}, allow_test_principal=True)
            original_run = executor.run
            before_dispatch = [None]
            def observed(input_mission, **options):
                witness["executor_calls"] += 1
                observed_plan = full_plan_json(input_mission).encode("utf8")
                entry = old.snapshot(session, witness)
                entries.append({"canonical_mission": json.loads(observed_plan), "before": entry})
                if observed_plan != canonical or options.get("existing_session") is not session or not old.canonical_entry_state_exact(before_dispatch[0] or {}, entry):
                    raise ValueError("ACTUAL_EXECUTOR_INPUT_OR_STATE_MISMATCH")
                return original_run(input_mission, **options)
            executor.run = observed
            def approval(name=principal):
                return old.approve(bridge, authority, handoff, source=spec["source_text"], mission=mission, principal=name, events=events, session=session, witness=witness)
            def denied(label, grant, requested=mission):
                return old.denied_request(label, bridge, source=spec["source_text"], mission=requested, approval=grant, session=session, witness=witness, requests=requests, events=events)
            if cell["arm"] == "authorized_new_mission":
                grant = approval()
                before_dispatch[0] = old.snapshot(session, witness)
                witness["phase"] = "new_mission"
                result = old.dispatch(bridge, source=spec["source_text"], mission=mission, approval=grant)
                if runtime.get("integrity_failure"):
                    raise ValueError("INTEGRITY_EXCEPTION_CAPTURED_BY_EXECUTOR:" + runtime["integrity_failure"])
                if witness.get("budget_failure") or runtime.get("native_budget_failure"):
                    raise RuntimeError("BUDGET_EXCEPTION_CAPTURED_BY_EXECUTOR")
                requests.append({"request": spec["positive_if_eligible"][0], "result": result})
                new_result = result["new_mission_result"]
                if new_result is None or len(entries) != 1:
                    raise ValueError("AUTHORIZED_DISPATCH_MISSING")
                write_new(run_dir / "new_result.json", new_result)
                manifest = json.loads((run_dir / "ledger" / mission.mission_id / "mission_manifest.json").read_text(encoding="utf8"))
                if full_plan_json(Mission.from_dict(manifest["mission_input"])).encode("utf8") != canonical:
                    raise ValueError("PERSISTED_PLAN_MISMATCH")
                child_graph = json.loads((run_dir / "ledger" / mission.mission_id / "task_graph.json").read_text(encoding="utf8"))
                if old.graph_plan(child_graph) != old.canonical_graph_plan(json.loads(canonical)):
                    raise ValueError("COMPLETE_CHILD_GRAPH_MISMATCH")
                checks, metrics = old.new_task_physical_checks(new_result, [row for row in witness["trace"] if row["phase"] == "new_mission"], timestep=session.simulation.timestep)
                outcome.update(status="NEW_TASK_SUCCESS" if all(checks.values()) else "NEW_TASK_FAILED", checks=checks, stop_metrics=metrics, child_halt=new_result.get("physical_halt"), coverage="DISPATCHED")
                denied(spec["positive_if_eligible"][1], grant)
            else:
                labels = spec["negative_requests_if_eligible_order"]
                prep = bridge.prepare(source=spec["source_text"], mission=mission)
                denied(labels[0], (prep, None, None))
                grant = approval()
                changed = mission.to_dict(); changed["steps"][0]["parameters"]["distance_m"] = 6.0
                denied(labels[1], grant, Mission.from_dict(changed))
                denied(labels[2], grant)
                denied(labels[3], approval(display))
                grant = approval()
                before = old.snapshot(session, witness)
                witness["phase"] = "deliberate_stale_state_step"
                current_ctrl = session.simulation._data.ctrl.copy()
                session.current_state = session.simulation.step(current_ctrl)
                session.total_steps += 1
                runtime["poses"].capture(session.simulation)
                after = old.snapshot(session, witness)
                if after["witness_steps"] - before["witness_steps"] != 1 or after["ctrl"] != before["ctrl"]:
                    raise ValueError("STALE_CONSTRUCTION_NOT_EXACTLY_ONE_UNCHANGED_CTRL_STEP")
                for key in before:
                    if key.startswith("controller") and before[key] != after[key]:
                        raise ValueError("STALE_STEP_EVALUATED_CONTROLLER")
                write_new(run_dir / "stale_state_step.json", {"before": before, "after": after, "refusal_physics_steps": 0, "deliberate_physics_steps": 1})
                denied(labels[4], grant); denied(labels[5], grant)
                outcome.update(status="AUTHORIZATION_REFUSALS", coverage="SIX_REQUESTS", controls=[old.control_summary(row) for row in requests])
            if digest(run_dir / "parent_result.json") != parent_sha or lifecycle._parent_graph.to_dict() != graph or {name: digest(run_dir / "ledger" / name) for name in ledger} != ledger:
                raise ValueError("PARENT_EVIDENCE_MUTATED")
            if any(row["node_id"] in {node["node_id"] for node in graph["nodes"]} for row in witness["node_dispatches"] if row["phase"] == "new_mission"):
                raise ValueError("OLD_NODE_RESURRECTION")
            return outcome
    finally:
        if watchdog is not None:
            watchdog.cancel()
        secondary = []
        def retain(name, action):
            try:
                action()
            except BaseException as exc:
                secondary.append({"artifact": name, "type": type(exc).__name__, "reason": str(exc)})
        retain("requests.json", lambda: write_new(run_dir / "requests.json", requests))
        retain("handoff_events.json", lambda: write_new(run_dir / "handoff_events.json", events))
        retain("dispatch_entries.json", lambda: write_new(run_dir / "dispatch_entries.json", entries))
        retain("lifecycle_events.json", lambda: write_new(run_dir / "lifecycle_events.json", lifecycle.events if lifecycle else []))
        if runtime is not None:
            old, witness = runtime["helpers"], runtime["witness"]
            retain("state_trace.jsonl.gz", lambda: old.save_trace(run_dir / "state_trace.jsonl.gz", evidence_value(witness["trace"])))
            retain("node_dispatches.json", lambda: write_new(run_dir / "node_dispatches.json", witness["node_dispatches"]))
            retain("witness.json", lambda: write_new(run_dir / "witness.json", {key: value for key, value in witness.items() if key != "trace"}))
            retain("push_events.json", lambda: write_new(run_dir / "push_events.json", runtime["push_events"]()))
            retain("native_state_trace.json", lambda: write_new(run_dir / "native_state_trace.json", runtime.get("raw_rows", [])))
            retain("poses.npz", lambda: runtime["poses"].save(run_dir / "poses.npz", runtime["session"].simulation))
            if witness["reset_calls"] != 2 or witness["reset_data_calls"] != 2 or witness["reset_keyframe_calls"]:
                secondary.append({"integrity": "RESET_COUNTS_MISMATCH"})
            if runtime.get("native_count", [witness["steps"]])[0] != witness["steps"]:
                secondary.append({"integrity": "NATIVE_AND_CALLTHROUGH_STEP_COUNTS_MISMATCH"})
            if 'parent_sha' in locals():
                parent_after_graph = lifecycle._parent_graph.to_dict() if lifecycle else executor.last_graph.to_dict()
                retain("parent_preservation.json", lambda: write_new(run_dir / "parent_preservation.json", {"result_unchanged": parent.to_dict() == parent_document, "graph_unchanged": parent_after_graph == graph, "parent_result_sha256": parent_sha, "ledger_before": ledger, "ledger_after": {name: digest(run_dir / "ledger" / name) for name in ledger}}))
                if digest(run_dir / "parent_result.json") != parent_sha or parent.to_dict() != parent_document or parent_after_graph != graph or {name: digest(run_dir / "ledger" / name) for name in ledger} != ledger:
                    secondary.append({"integrity": "PARENT_EVIDENCE_MUTATED"})
        retain("outcome.json", lambda: write_new(run_dir / "outcome.json", outcome))
        if secondary:
            write_new(run_dir / "partial_artifact_errors.json", secondary)
            if sys.exc_info()[0] is None:
                raise ValueError("Evidence/integrity finalization failed")


def supervise(command, *, run_dir, timeout_s, cwd=ROOT):
    """Hard external deadline; testable with a sleeping non-physics Python child."""
    with (Path(run_dir) / "worker.log").open("x", encoding="utf8") as log:
        process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
        try:
            returncode = process.wait(timeout=max(0.001, timeout_s))
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=10)
            write_new(Path(run_dir) / "supervisor_timeout.json", {"status": "PARTIAL_STOPPED", "reason": "HARD_WALL_WATCHDOG", "partial_native_journal": "native_incremental.jsonl", "no_retry": True})
            raise TimeoutError("HARD_WALL_WATCHDOG")
    if returncode:
        raise RuntimeError("Arm worker stopped with code " + str(returncode))


def acquire(*, authorize_physics=False, readiness_sha256=None, backend=None, output=None):
    if not authorize_physics:
        raise PermissionError("Explicit --authorize-physics required; readiness does not authorize acquisition")
    checked = preflight()
    verify_readiness(readiness_sha256)
    spec = checked["spec"]
    output = Path(output or HERE / "artifacts")
    output.mkdir()  # refuse rerun, including previously partial campaigns
    budget, paired, completed = CampaignBudget(spec), {}, []
    for cell in spec["run_order"]:
        run_dir = output / (cell["state_id"] + "--" + cell["arm"])
        run_dir.mkdir()
        # Parent supervisor has its own campaign clock; arm time must restart.
        budget.arm_started = time.perf_counter()
        known_before = budget.native_steps
        try:
            budget.guard(cell, 0)
            if backend is None:
                command = [sys.executable, str(HERE / "acquire.py"), "acquire", "--authorize-physics", "--readiness-sha256", readiness_sha256, "--internal-arm-index", str(spec["run_order"].index(cell)), "--output", str(output.resolve())]
                remaining = min(120, 840 - (time.perf_counter() - budget.started))
                supervise(command, run_dir=run_dir, timeout_s=remaining)
                witness = json.loads((run_dir / "witness.json").read_text(encoding="utf8"))
                budget.native_steps += witness["steps"]
                if budget.native_steps > 270000:
                    raise ValueError("TOTAL_NATIVE_BUDGET_EXCEEDED")
            else:
                run_arm(spec, cell, run_dir, backend, budget, paired.get(cell["state_id"]))
            if cell["state_id"] != "normal_control":
                trace = (run_dir / "predecision_trace.json").read_bytes()
                trace += (run_dir / "predecision_native_trace.json").read_bytes()
                if cell["state_id"] in paired and trace != paired[cell["state_id"]]:
                    raise ValueError("PAIRED_PREDECISION_TRACE_MISMATCH")
                paired[cell["state_id"]] = trace
            completed.append(dict(cell))
        except BaseException as exc:
            journal = run_dir / "native_incremental.jsonl"
            journal_rows = sum(1 for line in journal.read_text(encoding="utf8").splitlines() if line.strip()) if journal.exists() else None
            partial = {"status": "PARTIAL_STOPPED", "type": type(exc).__name__, "reason": str(exc), "known_native_steps_before_arm": known_before, "known_counter_steps_currently_recorded": budget.native_steps, "current_arm_persisted_journal_rows": journal_rows, "inflight_native_step_count": "UNKNOWN_ON_FORCED_TERMINATION", "no_retry": True}
            write_new(run_dir / "acquisition_failure.json", partial)
            write_new(output / "campaign_receipt.json", {**partial, "failed_cell": cell, "completed_cells": completed, "frozen_planned_cells": spec["run_order"]})
            raise
    write_new(output / "campaign_receipt.json", {"status": "ACQUISITION_COMPLETE_NOT_SCIENTIFIC_VERDICT", "completed_cells": completed, "native_steps": budget.native_steps, "source_manifest_sha256": checked["manifest_sha256"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "acquire"))
    parser.add_argument("--authorize-physics", action="store_true")
    parser.add_argument("--readiness-sha256")
    parser.add_argument("--internal-arm-index", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.command == "preflight":
        result = preflight(); result.pop("spec")
        print(json.dumps(result))
    else:
        if args.internal_arm_index is not None:
            if not args.authorize_physics:
                raise PermissionError("Explicit authorization missing")
            checked = preflight()
            verify_readiness(args.readiness_sha256)
            spec = checked["spec"]
            cell = spec["run_order"][args.internal_arm_index]
            run_dir = args.output / (cell["state_id"] + "--" + cell["arm"])
            if not run_dir.is_dir() or any(run_dir.iterdir()) and set(p.name for p in run_dir.iterdir()) != {"worker.log"}:
                raise ValueError("Worker directory not pristine")
            expected = None
            if cell["arm"] == "authorization_refusals":
                sibling = args.output / (cell["state_id"] + "--authorized_new_mission")
                expected = (sibling / "predecision_trace.json").read_bytes() + (sibling / "predecision_native_trace.json").read_bytes()
            run_arm(spec, cell, run_dir, production_backend, CampaignBudget(spec), expected)
        else:
            acquire(authorize_physics=args.authorize_physics, readiness_sha256=args.readiness_sha256, output=args.output)


if __name__ == "__main__":
    main()
