"""Frozen two-arm real MuJoCo handoff qualification; no replacement runs.

All instrumentation calls through existing execution without modifying inputs.
Only the root process may invoke acquisition after source/protocol freeze.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from g1swarm.config import load_yaml
from g1swarm.mission import LiveMissionSession, MissionExecutor, MissionValidator
from g1swarm.mission.ir import Mission
from g1swarm.mission.lifecycle import MissionLifecycle, mission_sha256
from g1swarm.mission.live_session import HaltMonitor
from g1swarm.mission.trusted_handoff import CONTINUATION_PERMISSION, TrustedMissionHandoff
from g1swarm.simulation.g1_simulation import G1Simulation
from g1swarm.trusted_handoff_v0 import (
    OfflineHandoff, TestPrincipalAuthority, full_plan_json, semantics_digest,
)
from scripts.run_oracle_missions import build_grounder, load_protocol
from experiments.m2.closed_loop_mission_001.acquire import PoseCollector
from experiments.m2.adaptive_mission_lifecycle_001.acquire import (
    digest, ledger_hashes, save_trace, verify_pose_prefix, write_new,
)

HERE = Path(__file__).resolve().parent


def sources(spec):
    """Explicit source membership comes from the independently reviewed freeze."""
    required = {HERE / "protocol.json", HERE / "acquire.py"}
    required.update(ROOT / name for name in spec["frozen_source_paths"])
    return sorted(required)


def freeze():
    spec = json.loads((HERE / "protocol.json").read_text(encoding="utf8"))
    write_new(HERE / "source_manifest.json", {
        "status": "FROZEN_BEFORE_FORMAL_M2_3B_PHYSICS",
        "files": {p.relative_to(ROOT).as_posix(): digest(p) for p in sources(spec)},
    })


def verify_sources():
    manifest = json.loads((HERE / "source_manifest.json").read_text(encoding="utf8"))
    spec = json.loads((HERE / "protocol.json").read_text(encoding="utf8"))
    if set(manifest["files"]) != {p.relative_to(ROOT).as_posix() for p in sources(spec)}:
        raise ValueError("Frozen source membership changed")
    for name, expected in manifest["files"].items():
        if digest(ROOT / name) != expected:
            raise ValueError("Frozen source mismatch: " + name)
    return manifest


@contextmanager
def execution_witness(*, maximum_steps, maximum_wall_s, mujoco_module=None):
    """Read-only call-through counters; a bounded guard runs before each step."""
    if mujoco_module is None:
        import mujoco as mujoco_module
    original_reset, original_step = G1Simulation.reset, G1Simulation.step
    original_node = LiveMissionSession.run_node
    original_reset_data = mujoco_module.mj_resetData
    original_reset_keyframe = mujoco_module.mj_resetDataKeyframe
    started = time.perf_counter()
    witness = {"reset_calls": 0, "reset_data_calls": 0, "reset_keyframe_calls": 0,
               "steps": 0, "node_calls": 0, "executor_calls": 0,
               "phase": "parent", "trace": [], "node_dispatches": [],
               "budget_failure": None, "last_progress_wall_s": 0.0}

    def guard(*, stepping=False):
        elapsed = time.perf_counter() - started
        if elapsed >= maximum_wall_s:
            witness["budget_failure"] = "WALL_TIME_BUDGET_EXHAUSTED"
            raise TimeoutError(witness["budget_failure"])
        if stepping and witness["steps"] >= maximum_steps:
            witness["budget_failure"] = "PHYSICS_STEP_BUDGET_EXHAUSTED"
            raise RuntimeError(witness["budget_failure"])
        if elapsed - witness["last_progress_wall_s"] >= 30.0:
            print(f"progress phase={witness['phase']} steps={witness['steps']} elapsed_s={elapsed:.1f}", flush=True)
            witness["last_progress_wall_s"] = elapsed

    def reset(simulation, *args, **kwargs):
        guard()
        witness["reset_calls"] += 1
        return original_reset(simulation, *args, **kwargs)

    def reset_data(*args, **kwargs):
        witness["reset_data_calls"] += 1
        return original_reset_data(*args, **kwargs)

    def reset_keyframe(*args, **kwargs):
        witness["reset_keyframe_calls"] += 1
        return original_reset_keyframe(*args, **kwargs)

    def step(simulation, control=None):
        guard(stepping=True)
        state = original_step(simulation, control)
        witness["steps"] += 1
        witness["trace"].append({"sequence": witness["steps"], "phase": witness["phase"],
                                 "active_skill": state.active_skill, **HaltMonitor._row(state)})
        return state

    def run_node(session, node, execution_mode):
        guard()
        witness["node_calls"] += 1
        witness["node_dispatches"].append({
            "node_id": node.node_id, "skill": node.skill.value,
            "parameters": deepcopy(node.parameters), "depends_on": list(node.depends_on),
            "execution_mode": execution_mode, "phase": witness["phase"],
            "simulation_time_s": float(session.simulation._data.time),
            "simulation_steps": witness["steps"],
        })
        return original_node(session, node, execution_mode)

    G1Simulation.reset, G1Simulation.step = reset, step
    LiveMissionSession.run_node = run_node
    mujoco_module.mj_resetData, mujoco_module.mj_resetDataKeyframe = reset_data, reset_keyframe
    try:
        yield witness
    finally:
        G1Simulation.reset, G1Simulation.step = original_reset, original_step
        LiveMissionSession.run_node = original_node
        mujoco_module.mj_resetData, mujoco_module.mj_resetDataKeyframe = original_reset_data, original_reset_keyframe


def snapshot(session, witness):
    data = session.simulation._data
    result = {
        "time_s": float(data.time), "qpos": data.qpos.tolist(),
        "qvel": data.qvel.tolist(), "ctrl": data.ctrl.tolist(),
        "state": session.simulation.get_robot_state().to_dict(),
        "session_steps": session.total_steps, "witness_steps": witness["steps"],
        "reset_calls": witness["reset_calls"], "reset_data_calls": witness["reset_data_calls"],
        "reset_keyframe_calls": witness["reset_keyframe_calls"],
        "node_calls": witness["node_calls"], "executor_calls": witness["executor_calls"],
        "session_identity": id(session), "simulation_identity": id(session.simulation),
        "controller_identity": id(session.controller),
    }
    for name in ("_action", "_target"):
        if hasattr(session.controller, name):
            result["controller" + name] = np.asarray(getattr(session.controller, name)).tolist()
    if hasattr(session.controller, "_counter"):
        result["controller_counter"] = int(session.controller._counter)
    return result


def trace_equal(rows, historical):
    import gzip
    with gzip.open(historical, "rt", encoding="utf8") as stream:
        frozen = [json.loads(line) for line in stream]
    return rows == frozen


def graph_plan(graph):
    return [{"id": row["node_id"], "skill": row["skill"],
             "parameters": row["parameters"], "depends_on": row["depends_on"]}
            for row in graph["nodes"]]


def canonical_entry_state_exact(pre_dispatch, entry_snapshot):
    if "executor_calls" not in pre_dispatch:
        return False
    expected = deepcopy(pre_dispatch)
    expected["executor_calls"] += 1
    return expected == entry_snapshot


def canonical_graph_plan(plan):
    return [{"id": row["id"], "skill": row["skill"],
             "parameters": row["parameters"], "depends_on": row.get("depends_on", [])}
            for row in plan["steps"]]


def event_at(session, witness, event, **payload):
    return {"event": event, "simulation_time_s": float(session.simulation._data.time),
            "simulation_steps": witness["steps"], "scope": "TEST_ONLY",
            "production_authority": False, **payload}


def approve(bridge, authority, handoff, *, source, mission, principal, events, session, witness):
    preparation = bridge.prepare(source=source, mission=mission)
    fixture = authority.create_test_session(principal)
    issued = Mission.from_dict(json.loads(preparation.canonical_mission))
    presentation = authority.present(source, issued, preparation.context, fixture)
    confirmation = authority.respond(fixture, presentation,
                                     displayed_sha256=presentation.display_sha256, action="CONFIRM")
    events.append(event_at(session, witness, "fixture_confirmation", principal_id=principal,
                           signed_plan_sha256=preparation.handoff_plan_sha256,
                           handoff_semantics_sha256=preparation.integration_epoch))
    grant = handoff.authorize(source=source, mission=issued, context=preparation.context,
                              authority=authority, confirmation=confirmation, allow_test_principal=True)
    events.append(event_at(session, witness, "fixture_handoff_issued", principal_id=principal,
                           signed_plan_sha256=grant.mission_sha256,
                           handoff_semantics_sha256=grant.semantics_sha256,
                           assurance=grant.assurance, authority_scope=grant.scope,
                           original_source_unique=grant.original_source_unique))
    return preparation, confirmation, grant


def dispatch(bridge, *, source, mission, approval):
    preparation, confirmation, grant = approval
    return bridge.dispatch(preparation=preparation, grant=grant, source=source,
                           mission=mission, context=preparation.context, confirmation=confirmation,
                           phase="m23b")


def denied_request(label, bridge, *, source, mission, approval, session, witness, requests, events):
    before = snapshot(session, witness)
    result = dispatch(bridge, source=source, mission=mission, approval=approval)
    after = snapshot(session, witness)
    requests.append({"request": label, "before": before, "after": after, "result": result})
    events.append(event_at(session, witness, "qualification_refusal", request=label,
                           status=result["status"], reason=result["reason"]))
    if result["status"] != "ESCALATE" or result["new_mission_result"] is not None or before != after:
        raise ValueError("Denied request changed execution: " + label)
    return result


def control_summary(request):
    before, after = request["before"], request["after"]
    return {"request": request["request"], "status": request["result"]["status"],
            "reason": request["result"]["reason"],
            "physics_steps_delta": after["witness_steps"] - before["witness_steps"],
            "node_calls_delta": after["node_calls"] - before["node_calls"],
            "reset_calls_delta": after["reset_calls"] - before["reset_calls"],
            "raw_state_unchanged": before == after}


def invalid_controls(bridge, authority, handoff, *, source, mission, principal,
                     display_only_principal, session, witness, requests, events):
    """The five frozen requests; deliberate separate issuances are not retries."""
    approvals = lambda name: approve(
        bridge, authority, handoff, source=source, mission=mission, principal=name,
        events=events, session=session, witness=witness)
    missing_preparation = bridge.prepare(source=source, mission=mission)
    denied_request("missing_grant", bridge, source=source, mission=mission,
                   approval=(missing_preparation, None, None), session=session, witness=witness,
                   requests=requests, events=events)
    copied = approvals(principal)
    denied_request("copied_registered_grant", bridge, source=source, mission=mission,
                   approval=(copied[0], copied[1], replace(copied[2])), session=session,
                   witness=witness, requests=requests, events=events)
    changed = approvals(principal)
    altered = deepcopy(mission.to_dict())
    altered["steps"][0]["parameters"]["distance_m"] = 6.0
    denied_request("changed_plan_distance_4_to_6", bridge, source=source, mission=Mission.from_dict(altered),
                   approval=changed, session=session, witness=witness, requests=requests, events=events)
    denied_request("replay_burned_plan_mismatch_grant", bridge, source=source, mission=mission,
                   approval=changed, session=session, witness=witness, requests=requests, events=events)
    denied_request("registered_display_only_principal_without_continuation_permission", bridge,
                   source=source, mission=mission, approval=approvals(display_only_principal),
                   session=session, witness=witness, requests=requests, events=events)


def new_task_physical_checks(new_result, rows, *, timestep, window_s=1.0):
    """The existing Runtime omits StopSkill's window metric; derive it read-only."""
    stop_rows = [row for row in rows if row["active_skill"] == "stop"]
    window_steps = int(round(window_s / timestep))
    complete_window = len(stop_rows) >= window_steps
    window_mean = float(np.mean([row["speed_mps"] for row in stop_rows[-window_steps:]])) if complete_window else None
    last_node = new_result["nodes"][-1] if new_result["nodes"] else {}
    checks = {"mission_success": new_result["mission_success"],
              "physical_success": new_result["physical_success"],
              "final_stop_node_success": last_node.get("skill") == "stop" and last_node.get("metrics", {}).get("skill_status") == "SUCCESS",
              "final_speed": bool(stop_rows) and stop_rows[-1]["speed_mps"] <= 0.1,
              "window_mean_speed": complete_window and window_mean <= 0.1,
              "finite_throughout": bool(rows) and all(row["finite"] for row in rows),
              "standing_throughout": bool(rows) and all(row["standing"] for row in rows),
              "no_fall_throughout": bool(rows) and not any(row["fallen"] for row in rows)}
    return checks, {"final_stop_instantaneous_speed_mps": stop_rows[-1]["speed_mps"] if stop_rows else None,
                    "final_stop_window_mean_speed_mps": window_mean,
                    "final_stop_window_s": window_s, "final_stop_window_steps": window_steps,
                    "complete_window": complete_window}


def acquire():
    verify_sources()
    spec = json.loads((HERE / "protocol.json").read_text(encoding="utf8"))
    if spec["execution_order"] != ["trusted_authorized", "halt_only_invalid"] or spec["seed"] != 0:
        raise ValueError("Undeclared acquisition membership")
    missions = json.loads((ROOT / spec["parent_mission_source"]).read_text(encoding="utf8"))
    halt = json.loads((ROOT / spec["halt_contract_source"]).read_text(encoding="utf8"))
    protocol = load_protocol(spec["source_protocol"])
    robot = load_yaml(protocol["robot_config"])
    if digest(ROOT / robot["controller"]["policy_path"]) != protocol["provenance"]["policy_sha256"]:
        raise ValueError("Policy identity mismatch")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    source_sha = digest(HERE / "source_manifest.json")
    canonical = full_plan_json(Mission.from_dict(spec["new_mission"])).encode("utf8")
    signed_hash = hashlib.sha256(canonical).hexdigest()
    source = spec["source_text"]
    output = HERE / "artifacts"
    output.mkdir(exist_ok=True)
    for arm in spec["execution_order"]:
        print("arm=" + arm + " stage=starting", flush=True)
        run_dir = output / arm
        run_dir.mkdir()  # no retry, replacement or overwrite
        session = lifecycle = continuity = None
        poses = PoseCollector()
        requests, handoff_events, dispatch_entries = [], [], []
        external_factory_calls = [0]
        started = time.perf_counter()
        with execution_witness(maximum_steps=spec["maximum_physics_steps"][arm],
                               maximum_wall_s=spec["maximum_wall_time_s_per_arm"]) as witness:
            try:
                session = LiveMissionSession(robot_config=robot, protocol=protocol, seed=spec["seed"],
                                             simulation_wrapper=poses.wrap)
                poses.capture(session.simulation)
                if (witness["reset_calls"] != 2 or witness["reset_data_calls"] != 2
                        or witness["reset_keyframe_calls"] != 0):
                    raise ValueError("Unexpected startup reset count")

                def forbidden_factory(seed):
                    external_factory_calls[0] += 1
                    raise AssertionError("No new session allowed")

                executor = MissionExecutor(
                    validator=MissionValidator(), grounder=build_grounder(protocol),
                    session_factory=forbidden_factory, protocol=protocol,
                    recorder_root=str(run_dir / "ledger"), seed=spec["seed"],
                    provenance={"study": spec["experiment_id"], "run": arm,
                                "source_commit": commit, "source_manifest_sha256": source_sha},
                    walk_strict_gate=True, physical_halt_contract=halt,
                )
                parent = executor.run(missions["failure_mission"], existing_session=session, phase="m23b_parent")
                write_new(run_dir / "parent_result.json", parent.to_dict())
                poses.capture(session.simulation)
                comparator = ROOT / spec["comparators"]["historical_authorized" if arm == "trusted_authorized" else "historical_invalid"]
                retained_halt = ROOT / spec["comparators"]["historical_invalid"]
                verify_pose_prefix(poses, retained_halt / "poses.npz")
                if not trace_equal(witness["trace"], retained_halt / "state_trace.jsonl.gz"):
                    raise ValueError("Parent physics trace differs from retained M2.2")
                if parent.state != "FAILED" or (parent.physical_halt or {}).get("status") != "HALT_SUCCEEDED":
                    raise ValueError("Frozen failed parent or successful halt unavailable")
                print("arm=" + arm + " stage=halt_complete", flush=True)
                original_ledger = ledger_hashes(run_dir / "ledger")
                parent_graph = deepcopy(executor.last_graph.to_dict())
                parent_sha = digest(run_dir / "parent_result.json")
                continuity = {"after_parent": snapshot(session, witness), "parent_graph_before": parent_graph,
                              "parent_ledger_before": original_ledger, "parent_result_sha256": parent_sha}
                lifecycle = MissionLifecycle(executor=executor, session=session, parent_result=parent,
                                             session_id=arm + "-same-session", parent_receipt_sha256=parent_sha)
                mission = Mission.from_dict(deepcopy(spec["new_mission"]))
                assessment = lifecycle.assess(mission)
                write_new(run_dir / "assessment.json", assessment)
                if not assessment["eligible"]:
                    raise ValueError("Frozen same-session state is ineligible: " + ",".join(assessment["reasons"]))
                authority, handoff = TestPrincipalAuthority(), OfflineHandoff()
                bridge = TrustedMissionHandoff(
                    lifecycle=lifecycle, handoff=handoff, authority=authority,
                    permissions={(spec["fixture_principal"], signed_hash): {CONTINUATION_PERMISSION}},
                    allow_test_principal=True,
                )
                original_run = executor.run

                def observed_run(input_mission, **options):
                    observed = full_plan_json(input_mission).encode("utf8")
                    witness["executor_calls"] += 1
                    dispatch_entries.append({"canonical_mission": json.loads(observed),
                                             "canonical_plan_sha256": hashlib.sha256(observed).hexdigest(),
                                             "existing_session_is_original": options.get("existing_session") is session,
                                             "before": snapshot(session, witness)})
                    if observed != canonical or options.get("existing_session") is not session:
                        raise ValueError("Actual execution did not use signed canonical Mission/same session")
                    if not canonical_entry_state_exact(continuity.get("before_new_mission", {}), dispatch_entries[-1]["before"]):
                        raise ValueError("Raw state changed at actual canonical executor entry")
                    return original_run(input_mission, **options)

                executor.run = observed_run
                approvals = lambda principal: approve(
                    bridge, authority, handoff, source=source, mission=mission, principal=principal,
                    events=handoff_events, session=session, witness=witness)
                new_result = None
                if arm == "trusted_authorized":
                    approval = approvals(spec["fixture_principal"])
                    continuity["before_new_mission"] = snapshot(session, witness)
                    witness["phase"] = "new_mission"
                    print("arm=" + arm + " stage=canonical_dispatch", flush=True)
                    result = dispatch(bridge, source=source,
                                      mission=Mission.from_dict(mission.to_dict()), approval=approval)
                    continuity["after_new_mission"] = snapshot(session, witness)
                    requests.append({"request": "valid_registered_full_plan_grant", "result": result,
                                     "before": continuity["before_new_mission"],
                                     "after": continuity["after_new_mission"]})
                    new_result = result["new_mission_result"]
                    if new_result is not None:
                        write_new(run_dir / "new_result.json", new_result)
                    witness["phase"] = "post_new_mission_no_dispatch"
                    denied_request("same_grant_replay_after_completion", bridge, source=source, mission=mission,
                                   approval=approval, session=session, witness=witness,
                                   requests=requests, events=handoff_events)
                else:
                    invalid_controls(
                        bridge, authority, handoff, source=source, mission=mission,
                        principal=spec["fixture_principal"], display_only_principal=spec["display_only_principal"],
                        session=session, witness=witness, requests=requests, events=handoff_events)

                poses.capture(session.simulation)
                continuity["final"] = snapshot(session, witness)
                continuity["parent_graph_after"] = lifecycle._parent_graph.to_dict()
                continuity["parent_ledger_after"] = {p: digest(run_dir / "ledger" / p) for p in original_ledger}
                continuity["parent_result_sha256_after"] = digest(run_dir / "parent_result.json")
                write_new(run_dir / "requests.json", requests)
                write_new(run_dir / "lifecycle_events.json", lifecycle.events)
                handoff_events.extend(item for item in lifecycle.events if item["event"].startswith("trusted_handoff"))
                handoff_events.sort(key=lambda item: (item["simulation_time_s"], item["simulation_steps"]))
                write_new(run_dir / "handoff_events.json", handoff_events)
                write_new(run_dir / "dispatch_entries.json", dispatch_entries)
                write_new(run_dir / "node_dispatches.json", witness["node_dispatches"])
                write_new(run_dir / "continuity.json", continuity)
                poses.save(run_dir / "poses.npz", session.simulation)
                save_trace(run_dir / "state_trace.jsonl.gz", witness["trace"])

                checks = {
                    "parent_result_preserved": continuity["parent_result_sha256_after"] == parent_sha,
                    "parent_graph_preserved": continuity["parent_graph_after"] == parent_graph,
                    "original_failure_and_blocked_dependents": [(n["node_id"], n["state"]) for n in parent_graph["nodes"]] == [("s1", "FAILED"), ("s2", "BLOCKED"), ("s3", "BLOCKED")],
                    "parent_ledger_preserved": continuity["parent_ledger_after"] == original_ledger,
                    "two_startup_resets_only": witness["reset_calls"] == 2 and witness["reset_data_calls"] == 2 and witness["reset_keyframe_calls"] == 0,
                    "external_session_factory_unused": external_factory_calls[0] == 0,
                    "within_frozen_wall_budget": time.perf_counter() - started < spec["maximum_wall_time_s_per_arm"],
                    "denials_zero_execution": all(control_summary(row)["raw_state_unchanged"] for row in requests if row["request"] != "valid_registered_full_plan_grant"),
                    "declared_request_membership": [row["request"] for row in requests] == spec["positive_requests" if arm == "trusted_authorized" else "negative_requests"],
                }
                ledger_plan_hash = actual_plan_hash = None
                full_plan_exact = graph_plan_exact = None
                physical, stop_metrics = {}, {}
                ledger_document = None
                if new_result is not None:
                    manifest_path = run_dir / "ledger" / mission.mission_id / "mission_manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
                    ledger_plan = full_plan_json(Mission.from_dict(manifest["mission_input"])).encode("utf8")
                    ledger_document = json.loads(ledger_plan)
                    ledger_plan_hash = hashlib.sha256(ledger_plan).hexdigest()
                    actual_plan_hash = dispatch_entries[0]["canonical_plan_sha256"] if len(dispatch_entries) == 1 else None
                    full_plan_exact = ledger_plan == canonical and actual_plan_hash == signed_hash
                    graph = json.loads((manifest_path.parent / "task_graph.json").read_text(encoding="utf8"))
                    graph_plan_exact = graph_plan(graph) == canonical_graph_plan(json.loads(canonical))
                    new_rows = [row for row in witness["trace"] if row["phase"] == "new_mission"]
                    physical, stop_metrics = new_task_physical_checks(
                        new_result, new_rows, timestep=session.simulation.timestep,
                        window_s=protocol["skill_parameters"]["stop"]["window_s"])
                try:
                    verify_pose_prefix(poses, comparator / "poses.npz")
                    poses_exact = True
                except ValueError:
                    poses_exact = False
                observer = {"poses_exact": poses_exact,
                            "trace_exact": trace_equal(witness["trace"], comparator / "state_trace.jsonl.gz"),
                            "historical_source": comparator.relative_to(ROOT).as_posix(),
                            "scope": "Exact retained 20 Hz qpos/qvel/ctrl and per-step physical trace; single seed/controller, no generalization claim."}
                checks["observer_equivalence"] = observer["poses_exact"] and observer["trace_exact"]
                if arm == "trusted_authorized":
                    checks.update(canonical_plan_exact=full_plan_exact is True,
                                  complete_graph_plan_exact=graph_plan_exact is True,
                                  physical_node_plan_exact=graph_plan({"nodes": [n for n in witness["node_dispatches"] if n["phase"] == "new_mission"]}) == canonical_graph_plan(json.loads(canonical)),
                                  canonical_entry_state_exact=len(dispatch_entries) == 1 and canonical_entry_state_exact(
                                      continuity["before_new_mission"], dispatch_entries[0]["before"]),
                                  new_task_acceptance=bool(physical) and all(physical.values()),
                                  one_new_executor_dispatch=witness["executor_calls"] == 1)
                else:
                    checks["no_new_executor_dispatch"] = witness["executor_calls"] == 0
                qualification = {"evidence_kind": "REAL_MUJOCO_SAME_SESSION", "checks": checks,
                                 "canonical_plan": json.loads(canonical),
                                 "actual_dispatch_plan": dispatch_entries[0]["canonical_mission"] if len(dispatch_entries) == 1 else None,
                                 "ledger_canonical_plan": ledger_document,
                                 "signed_plan_sha256": signed_hash, "actual_dispatch_plan_sha256": actual_plan_hash,
                                 "ledger_plan_sha256": ledger_plan_hash, "full_plan_exact_match": full_plan_exact,
                                 "graph_plan_exact_match": graph_plan_exact,
                                 "handoff_semantics_sha256": semantics_digest(),
                                 "lifecycle_mission_sha256": mission_sha256(mission),
                                 "controls": [control_summary(row) for row in requests if row["request"] != "valid_registered_full_plan_grant"],
                                 "new_task_physical_checks": physical, "final_stop_metrics": stop_metrics,
                                 "observer_equivalence": observer}
                write_new(run_dir / "qualification.json", qualification)
                write_new(run_dir / "receipt.json", {
                    "run": arm, "arm": arm, "seed": spec["seed"], "source_commit": commit,
                    "source_manifest_sha256": source_sha, "python": platform.python_version(),
                    "mujoco": importlib.metadata.version("mujoco"), "numpy": np.__version__,
                    "torch": importlib.metadata.version("torch"), "wall_time_s": time.perf_counter() - started,
                    "reset_calls": witness["reset_calls"], "reset_data_calls": witness["reset_data_calls"],
                    "reset_keyframe_calls": witness["reset_keyframe_calls"], "total_physics_steps": witness["steps"],
                    "node_dispatch_count": witness["node_calls"], "new_executor_dispatch_count": witness["executor_calls"],
                    "external_session_factory_calls": external_factory_calls[0],
                    "parent_state": parent.state, "parent_halt": (parent.physical_halt or {}).get("status"),
                    "checks_passed": all(checks.values()), "budget_failure": witness["budget_failure"],
                    "artifact_files": {p.name: digest(p) for p in sorted(run_dir.iterdir()) if p.is_file()},
                })
                if not all(checks.values()) or witness["budget_failure"] is not None:
                    raise ValueError("Qualification checks failed: " + ",".join(key for key, value in checks.items() if not value))
                print("arm=" + arm + " stage=complete steps=" + str(witness["steps"]), flush=True)
            except Exception as exc:
                write_new(run_dir / "acquisition_failure.json", {
                    "status": "PARTIAL_STOPPED", "type": type(exc).__name__, "reason": str(exc),
                    "source_commit": commit, "source_manifest_sha256": source_sha,
                    "reset_calls": witness["reset_calls"], "reset_data_calls": witness["reset_data_calls"],
                    "reset_keyframe_calls": witness["reset_keyframe_calls"], "physics_steps": witness["steps"],
                    "budget_failure": witness["budget_failure"], "scope": "NO_REPLACEMENT_ACQUISITION",
                })
                secondary = []
                for name, save in (
                    ("requests.json", lambda: write_new(run_dir / "requests.json", requests)),
                    ("handoff_events.json", lambda: write_new(run_dir / "handoff_events.json", handoff_events)),
                    ("dispatch_entries.json", lambda: write_new(run_dir / "dispatch_entries.json", dispatch_entries)),
                    ("node_dispatches.json", lambda: write_new(run_dir / "node_dispatches.json", witness["node_dispatches"])),
                    ("lifecycle_events.json", lambda: write_new(run_dir / "lifecycle_events.json", lifecycle.events if lifecycle is not None else [])),
                    ("continuity.json", lambda: write_new(run_dir / "continuity.json", continuity or {})),
                    ("state_trace.jsonl.gz", lambda: save_trace(run_dir / "state_trace.jsonl.gz", witness["trace"])),
                    ("poses.npz", lambda: poses.save(run_dir / "poses.npz", session.simulation)),
                ):
                    try:
                        if not (run_dir / name).exists() and (name != "poses.npz" or session is not None and len(poses.times) > 1):
                            save()
                    except Exception as save_error:
                        secondary.append({"artifact": name, "type": type(save_error).__name__, "reason": str(save_error)})
                if secondary:
                    write_new(run_dir / "partial_artifact_errors.json", secondary)
                raise
            finally:
                if session is not None:
                    session.close()


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "freeze":
        freeze()
    elif len(sys.argv) == 2 and sys.argv[1] == "acquire":
        acquire()
    else:
        raise SystemExit("usage: acquire.py freeze|acquire")
