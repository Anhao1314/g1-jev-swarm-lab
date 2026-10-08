"""Frozen three-run lifecycle study; no retry or replacement acquisition."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from g1swarm.config import load_yaml
from g1swarm.mission import LiveMissionSession, MissionExecutor, MissionValidator
from g1swarm.mission.lifecycle import MissionLifecycle, TestOnlyMissionAuthorizer, mission_sha256
from g1swarm.mission.live_session import HaltMonitor
from g1swarm.simulation.g1_simulation import G1Simulation
from scripts.run_oracle_missions import build_grounder, load_protocol
from experiments.m2.closed_loop_mission_001.acquire import PoseCollector

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")


def sources():
    paths = [HERE / "protocol.json", HERE / "acquire.py", HERE / "execution_deviation_001.json"]
    for directory in ("mission", "skills", "control", "simulation", "state", "boundary"):
        paths.extend(sorted((ROOT / "src/g1swarm" / directory).glob("*.py")))
    paths.extend(ROOT / p for p in (
        "configs/experiments/oracle_mission_runtime_001.yaml",
        "configs/robot/g1_locomotion_12dof.yaml",
        "scripts/run_oracle_missions.py",
        "src/g1swarm/config.py",
        "experiments/m2/closed_loop_mission_001/protocol.json",
        "experiments/m2/closed_loop_mission_001/acquire.py",
        "experiments/m2/post_failure_halt_001/protocol.json",
        "experiments/m2/post_failure_halt_integration_001/artifacts/failure_opt_in/result.json",
        "experiments/m2/post_failure_halt_integration_001/artifacts/failure_opt_in/poses.npz",
        "experiments/m2/post_failure_halt_integration_001/artifacts/safe_opt_in/result.json",
        "experiments/m2/post_failure_halt_integration_001/artifacts/safe_opt_in/poses.npz",
        "experiments/baselines/g1_closed_loop_correction_001/capability_map_v1_3.json",
        "experiments/baselines/g1_closed_loop_correction_001/risk_map_v1_3.json",
        "experiments/baselines/g1_closed_loop_correction_001/boundary_comparison.json",
        "third_party/unitree_rl_gym/resources/robots/g1_description/scene.xml",
        "third_party/unitree_rl_gym/resources/robots/g1_description/g1_12dof.xml",
        "third_party/unitree_rl_gym/deploy/pre_train/g1/motion.pt",
    ))
    return paths


def freeze():
    write_new(HERE / "source_manifest.json", {
        "status": "FROZEN_BEFORE_FORMAL_M2_2_PHYSICS",
        "files": {p.relative_to(ROOT).as_posix(): digest(p) for p in sources()},
    })


def verify_sources():
    manifest = json.loads((HERE / "source_manifest.json").read_text())
    for rel, expected in manifest["files"].items():
        if digest(ROOT / rel) != expected:
            raise ValueError(f"Frozen source mismatch: {rel}")


@contextmanager
def execution_witness():
    """Call-through counters and saved observations; no controller input edits."""
    original_reset, original_step = G1Simulation.reset, G1Simulation.step
    witness = {"reset_calls": 0, "steps": 0, "phase": "parent", "trace": []}

    def reset(simulation, *args, **kwargs):
        witness["reset_calls"] += 1
        return original_reset(simulation, *args, **kwargs)

    def step(simulation, control=None):
        state = original_step(simulation, control)
        witness["steps"] += 1
        witness["trace"].append({"sequence": witness["steps"], "phase": witness["phase"],
                                 "active_skill": state.active_skill, **HaltMonitor._row(state)})
        return state

    G1Simulation.reset, G1Simulation.step = reset, step
    try:
        yield witness
    finally:
        G1Simulation.reset, G1Simulation.step = original_reset, original_step


def snapshot(session, witness):
    data = session.simulation._data
    return {
        "time_s": float(data.time), "qpos": data.qpos.tolist(),
        "qvel": data.qvel.tolist(), "ctrl": data.ctrl.tolist(),
        "state": session.simulation.get_robot_state().to_dict(),
        "session_steps": session.total_steps, "witness_steps": witness["steps"],
        "reset_calls": witness["reset_calls"],
        "session_identity": id(session), "simulation_identity": id(session.simulation),
        "controller_identity": id(session.controller),
    }


def ledger_hashes(root):
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob("*")) if p.is_file()}


def verify_pose_prefix(poses, historical):
    with np.load(historical) as frozen:
        arrays = {"time_s": np.array(poses.times), "qpos": np.stack(poses.qpos),
                  "qvel": np.stack(poses.qvel), "ctrl": np.stack(poses.ctrl)}
        for key, actual in arrays.items():
            if not np.array_equal(actual, frozen[key]):
                raise ValueError(f"Retained prefix mismatch: {key}")


def save_trace(path, rows):
    with Path(path).open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as stream:
            for row in rows:
                stream.write((json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n").encode())


def acquire():
    verify_sources()
    spec = json.loads((HERE / "protocol.json").read_text())
    missions = json.loads((ROOT / spec["parent_mission_source"]).read_text())
    halt = json.loads((ROOT / spec["halt_contract_source"]).read_text())
    protocol = load_protocol(spec["source_protocol"])
    robot = load_yaml(protocol["robot_config"])
    if digest(ROOT / robot["controller"]["policy_path"]) != protocol["provenance"]["policy_sha256"]:
        raise ValueError("Policy identity mismatch")
    source_sha = digest(HERE / "source_manifest.json")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    output = HERE / "artifacts"
    output.mkdir(exist_ok=True)
    for run_name in spec["execution_order"]:
        run_dir = output / run_name
        run_dir.mkdir()  # refuse overwrite/retry
        session = None
        poses = PoseCollector()
        with execution_witness() as witness:
            try:
                session = LiveMissionSession(robot_config=robot, protocol=protocol,
                                             seed=spec["seed"], simulation_wrapper=poses.wrap)
                poses.capture(session.simulation)
                if witness["reset_calls"] != spec["acceptance"]["startup_reset_calls"]:
                    raise ValueError("Unexpected initial reset count")
                executor = MissionExecutor(
                    validator=MissionValidator(), grounder=build_grounder(protocol),
                    session_factory=lambda seed: (_ for _ in ()).throw(AssertionError("No new session allowed")),
                    protocol=protocol, recorder_root=str(run_dir / "ledger"), seed=spec["seed"],
                    provenance={"study": spec["experiment_id"], "run": run_name,
                                "source_commit": commit, "source_manifest_sha256": source_sha},
                    walk_strict_gate=True, physical_halt_contract=halt,
                )
                mission = missions["success_mission" if run_name == "normal_control" else "failure_mission"]
                parent = executor.run(mission, existing_session=session, phase="m22_parent")
                write_new(run_dir / "parent_result.json", parent.to_dict())
                poses.capture(session.simulation)
                retained = spec["comparators"]["historical_normal" if run_name == "normal_control" else "historical_halt_only"]
                verify_pose_prefix(poses, ROOT / retained / "poses.npz")
                if witness["reset_calls"] != 2:
                    raise ValueError("Reset after initialization")
                before = snapshot(session, witness)
                original_ledger = ledger_hashes(run_dir / "ledger")
                parent_graph = deepcopy(executor.last_graph.to_dict())
                parent_sha = digest(run_dir / "parent_result.json")
                results = []
                continuity = {"after_parent": before, "parent_graph_before": parent_graph,
                              "parent_ledger_before": original_ledger, "parent_result_sha256": parent_sha}
                if run_name != "normal_control":
                    lifecycle = MissionLifecycle(executor=executor, session=session, parent_result=parent,
                                                 session_id=run_name + "-same-session", parent_receipt_sha256=parent_sha)
                    assessment = lifecycle.assess(spec["new_mission"])
                    write_new(run_dir / "assessment.json", assessment)
                    authority = TestOnlyMissionAuthorizer(allowed_mission_sha256={mission_sha256(spec["new_mission"])})

                    def deny(label, mission_input, grant=None, authorizer=None):
                        pre = snapshot(session, witness)
                        result = lifecycle.dispatch(mission_input, authorization=grant, authorizer=authorizer)
                        post = snapshot(session, witness)
                        if result["status"] != "ESCALATE" or post != pre:
                            raise ValueError("Denied request changed execution state")
                        results.append({"request": label, "before": pre, "after": post, "result": result})

                    deny("missing_authorization", spec["new_mission"])
                    if run_name == "adaptive_authorized" and assessment["eligible"]:
                        deny("forged_authorization", spec["new_mission"], object(), authority)
                        probe_grant = authority.issue(lifecycle, spec["new_mission"])
                        mismatch = deepcopy(spec["new_mission"])
                        mismatch["mission_id"] = "m22-wrong-request-context"
                        deny("mismatched_mission", mismatch, probe_grant, authority)
                        grant = authority.issue(lifecycle, spec["new_mission"])
                        continuity["before_new_mission"] = snapshot(session, witness)
                        witness["phase"] = "new_mission"
                        new = lifecycle.dispatch(spec["new_mission"], authorization=grant, authorizer=authority)
                        results.append({"request": "matching_test_only_authorization", "result": new})
                        continuity["after_new_mission"] = snapshot(session, witness)
                        if new["new_mission_result"] is not None:
                            write_new(run_dir / "new_result.json", new["new_mission_result"])
                        witness["phase"] = "post_new_mission_no_dispatch"
                        deny("replayed_authorization", spec["new_mission"], grant, authority)
                    write_new(run_dir / "lifecycle_events.json", lifecycle.events)
                    continuity["parent_graph_after"] = lifecycle._parent_graph.to_dict()
                else:
                    continuity["parent_graph_after"] = executor.last_graph.to_dict()
                continuity["final"] = snapshot(session, witness)
                continuity["parent_ledger_after"] = {
                    p: digest(run_dir / "ledger" / p) for p in original_ledger
                }
                continuity["parent_result_sha256_after"] = digest(run_dir / "parent_result.json")
                if (continuity["parent_graph_after"] != parent_graph or
                    continuity["parent_ledger_after"] != original_ledger or
                    digest(run_dir / "parent_result.json") != parent_sha or witness["reset_calls"] != 2):
                    raise ValueError("Parent evidence or simulation reset continuity violated")
                write_new(run_dir / "requests.json", results)
                write_new(run_dir / "continuity.json", continuity)
                poses.save(run_dir / "poses.npz", session.simulation)
                save_trace(run_dir / "state_trace.jsonl.gz", witness["trace"])
                write_new(run_dir / "receipt.json", {
                    "run": run_name, "seed": spec["seed"], "source_commit": commit,
                    "source_manifest_sha256": source_sha, "python": platform.python_version(),
                    "reset_calls": witness["reset_calls"], "total_physics_steps": witness["steps"],
                    "parent_state": parent.state, "parent_halt": (parent.physical_halt or {}).get("status"),
                    "artifact_files": {p.name: digest(p) for p in sorted(run_dir.iterdir()) if p.is_file()},
                })
            except Exception as exc:
                write_new(run_dir / "acquisition_failure.json", {
                    "status": "PARTIAL_STOPPED", "type": type(exc).__name__, "reason": str(exc),
                    "source_commit": commit, "source_manifest_sha256": source_sha,
                    "reset_calls": witness["reset_calls"], "physics_steps": witness["steps"],
                })
                secondary = []
                try:
                    if session is not None and len(poses.times) > 1 and not (run_dir / "poses.npz").exists():
                        poses.save(run_dir / "poses.npz", session.simulation)
                except Exception as save_error:
                    secondary.append({"artifact": "poses.npz", "type": type(save_error).__name__,
                                      "reason": str(save_error)})
                try:
                    if not (run_dir / "state_trace.jsonl.gz").exists():
                        save_trace(run_dir / "state_trace.jsonl.gz", witness["trace"])
                except Exception as save_error:
                    secondary.append({"artifact": "state_trace.jsonl.gz", "type": type(save_error).__name__,
                                      "reason": str(save_error)})
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
