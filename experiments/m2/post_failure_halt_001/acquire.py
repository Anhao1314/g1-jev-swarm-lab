"""Predeclared M2.1 StopSkill feasibility from the M2.0 failed state.

The halt is a separate, explicitly authorized handling action. It is never a
Task Graph node, and the blocked mission stop node is never dispatched.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from g1swarm.config import load_yaml
from g1swarm.mission import LiveMissionSession, MissionExecutor, MissionValidator
from g1swarm.skills import SkillContext, SkillRequest
from scripts.run_oracle_missions import build_grounder, load_protocol
from experiments.m2.closed_loop_mission_001.acquire import PoseCollector

HERE = Path(__file__).resolve().parent
SOURCE_PATHS = (
    "configs/experiments/oracle_mission_runtime_001.yaml",
    "configs/missions/oracle_phase2_001.yaml",
    "experiments/m2/closed_loop_mission_001/protocol.json",
    "experiments/m2/closed_loop_mission_001/acquire.py",
    "experiments/m2/closed_loop_mission_001/source_manifest.json",
    "experiments/m2/closed_loop_mission_001/audit.json",
    "experiments/baselines/g1_skill_characterization_001/protocol.yaml",
    "experiments/baselines/g1_skill_characterization_001/summary.json",
    "src/g1swarm/mission/runtime.py",
    "src/g1swarm/mission/live_session.py",
    "src/g1swarm/mission/grounding.py",
    "src/g1swarm/boundary/envelope.py",
    "src/g1swarm/skills/basic.py",
    "src/g1swarm/simulation/g1_simulation.py",
    "src/g1swarm/state/robot_state.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")


def freeze() -> None:
    paths = (HERE / "protocol.json", HERE / "acquire.py", *(ROOT / p for p in SOURCE_PATHS))
    write_new(HERE / "source_manifest.json", {
        "status": "FROZEN_BEFORE_PHYSICS",
        "files": {p.relative_to(ROOT).as_posix(): digest(p) for p in paths},
    })


def verify_sources() -> None:
    frozen = json.loads((HERE / "source_manifest.json").read_text(encoding="utf-8"))
    for relative, expected in frozen["files"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"Frozen source changed: {relative}")


def angles(quaternion) -> tuple[float, float, float]:
    w, x, y, z = [float(value) for value in quaternion]
    roll = math.degrees(math.atan2(2 * (w*x + y*z), 1 - 2 * (x*x + y*y)))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w*y - z*x)))))
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, 1 - 2 * (x*x + y*y)))))
    return roll, pitch, tilt


def state_row(state) -> dict:
    roll, pitch, tilt = angles(state.base_orientation)
    return {
        "time_s": state.simulation_time,
        "position_m": list(state.base_position),
        "speed_mps": state.speed(),
        "base_height_m": state.base_position[2],
        "roll_deg": roll,
        "pitch_deg": pitch,
        "tilt_deg": tilt,
        "standing": state.standing,
        "fallen": state.fallen,
        "finite": state.is_finite(),
    }


class DeferredCloseSession(LiveMissionSession):
    """Keep the exact executor session alive until an independent halt request."""

    def close(self) -> None:
        pass

    def physical_close(self) -> None:
        super().close()


class HaltTrace:
    def __init__(self, simulation, poses: PoseCollector) -> None:
        self.simulation = simulation
        self.poses = poses
        self.rows = [state_row(simulation.get_robot_state())]
        self.path_length_m = 0.0

    def step(self, control=None):
        state = self.simulation.step(control)
        current = state_row(state)
        prior = self.rows[-1]
        self.path_length_m += math.dist(current["position_m"][:2], prior["position_m"][:2])
        self.rows.append(current)
        tick = round(self.simulation.simulation_time / self.simulation.timestep)
        if tick % 25 == 0:
            self.poses.capture(self.simulation)
        return state

    def __getattr__(self, name):
        return getattr(self.simulation, name)


def run_mission(mission: dict, *, run_dir: Path, robot: dict, protocol: dict,
                seed: int, manifest_sha: str) -> tuple[object, DeferredCloseSession, PoseCollector, object]:
    poses = PoseCollector()
    holder = {}

    def factory(session_seed):
        session = DeferredCloseSession(robot_config=robot, protocol=protocol,
                                       seed=session_seed, simulation_wrapper=poses.wrap)
        holder["session"] = session
        poses.capture(session.simulation)
        return session

    executor = MissionExecutor(
        validator=MissionValidator(), grounder=build_grounder(protocol),
        session_factory=factory, protocol=protocol,
        recorder_root=str(run_dir / "ledger"), seed=seed,
        provenance={"study": "post_failure_halt_001", "mode": "strict_feedback",
                    "source_manifest_sha256": manifest_sha},
        walk_strict_gate=True,
    )
    result = executor.run(mission, phase="m2_post_failure_halt", write_evidence=True)
    return result, holder["session"], poses, executor.last_graph


def run_halt(session: DeferredCloseSession, poses: PoseCollector, spec: dict) -> dict:
    before = session.state()
    trace = HaltTrace(session.simulation, poses)
    context = SkillContext(
        simulation=trace, controller=session.controller, robot_config=session.robot_config,
        max_steps=int(round(1200.0 / session.simulation.timestep)), seed=session.seed,
    )
    started = time.perf_counter()
    result = session.router.execute(SkillRequest("stop", spec["stop_skill_parameters"]), context)
    wall_s = time.perf_counter() - started
    after = session.simulation.get_robot_state()
    rows = trace.rows
    acceptance = spec["acceptance"]
    displacement = math.dist(before.base_position[:2], after.base_position[:2])
    checks = {
        "skill_success": result.status.value == acceptance["stop_skill_status"],
        "duration": after.simulation_time - before.simulation_time <= acceptance["max_duration_s"] + 1e-9,
        "final_speed": after.speed() <= acceptance["max_final_instantaneous_speed_mps"],
        "window_mean_speed": float(result.metrics.get("final_window_mean_speed_mps", math.inf)) <= acceptance["max_final_window_mean_speed_mps"],
        "displacement": displacement <= acceptance["max_post_block_planar_displacement_m"],
        "finite_throughout": all(row["finite"] for row in rows),
        "standing_throughout": all(row["standing"] for row in rows),
        "no_fall_throughout": not any(row["fallen"] for row in rows),
    }
    return {
        "request": "EXPLICIT_INDEPENDENT_PHYSICAL_HALT",
        "status": "HALT_SUCCEEDED" if all(checks.values()) else "HALT_FAILED",
        "skill_status": result.status.value, "skill_reason": result.reason,
        "skill_metrics": result.metrics, "checks": checks,
        "pre_halt_state": before.to_dict(), "final_state": after.to_dict(),
        "simulated_halt_duration_s": after.simulation_time - before.simulation_time,
        "wall_halt_duration_s": wall_s,
        "post_block_planar_displacement_m": displacement,
        "path_length_m": trace.path_length_m,
        "trace": rows,
    }


def acquire() -> None:
    verify_sources()
    spec = json.loads((HERE / "protocol.json").read_text(encoding="utf-8"))
    missions = json.loads((ROOT / spec["mission_source"]).read_text(encoding="utf-8"))
    protocol = load_protocol(spec["source_protocol"])
    robot = load_yaml(protocol["robot_config"])
    output = HERE / "artifacts"
    output.mkdir(exist_ok=True)
    manifest_sha = digest(HERE / "source_manifest.json")
    for case_name, run_name in ((spec["failure_case"], "failure_feasibility"),
                                (spec["safe_control"], "safe_control")):
        run_dir = output / run_name
        run_dir.mkdir()
        session = None
        try:
            result, session, poses, graph = run_mission(
                missions[case_name], run_dir=run_dir, robot=robot,
                protocol=protocol, seed=spec["seed"], manifest_sha=manifest_sha,
            )
            write_new(run_dir / "mission_result.json", result.to_dict())
            if run_name == "failure_feasibility":
                trigger = spec["trigger"]
                assert result.state == trigger["mission_state"]
                assert result.failure_type == trigger["failure_type"]
                assert result.failed_node == trigger["failed_node"]
                assert result.nodes[0]["feedback_decision"]["action"] == trigger["decision_action"]
                states = {node.node_id: node.state.value for node in graph.nodes}
                assert all(states[node_id] == "BLOCKED" for node_id in trigger["blocked_task_nodes"])
                halt = run_halt(session, poses, spec)
                write_new(run_dir / "halt.json", halt)
            else:
                assert result.state == "SUCCESS" and result.skill_invocations == 3
                write_new(run_dir / "control.json", {"halt_requested": False,
                                                       "skill_invocations": result.skill_invocations,
                                                       "mission_state": result.state})
            poses.save(run_dir / "poses.npz", session.simulation)
            write_new(run_dir / "receipt.json", {
                "run": run_name,
                "source_manifest_sha256": manifest_sha,
                "mission_result_sha256": digest(run_dir / "mission_result.json"),
                "halt_sha256": digest(run_dir / "halt.json") if run_name == "failure_feasibility" else None,
                "pose_sha256": digest(run_dir / "poses.npz"),
            })
        finally:
            if session is not None:
                session.physical_close()


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "freeze":
        freeze()
    elif len(sys.argv) == 2 and sys.argv[1] == "acquire":
        acquire()
    else:
        raise SystemExit("usage: acquire.py freeze|acquire")
