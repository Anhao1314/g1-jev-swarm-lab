"""Frozen four-run M2.0 MuJoCo comparison. Run only after protocol/source freeze."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from g1swarm.config import load_yaml
from g1swarm.mission import LiveMissionSession, MissionExecutor, MissionValidator
from scripts.run_oracle_missions import build_grounder, load_protocol

HERE = Path(__file__).resolve().parent
SOURCE_PATHS = (
    "configs/experiments/oracle_mission_runtime_001.yaml",
    "configs/missions/oracle_phase2_001.yaml",
    "experiments/baselines/g1_closed_loop_correction_001/boundary_comparison.json",
    "src/g1swarm/mission/runtime.py",
    "src/g1swarm/mission/live_session.py",
    "src/g1swarm/mission/grounding.py",
    "src/g1swarm/boundary/envelope.py",
    "src/g1swarm/skills/basic.py",
    "src/g1swarm/simulation/g1_simulation.py",
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


class PoseCollector:
    """Read-only view, fixed 20 Hz state capture. No policy/controller input changes."""

    def __init__(self) -> None:
        self.times: list[float] = []
        self.qpos: list[np.ndarray] = []
        self.qvel: list[np.ndarray] = []
        self.ctrl: list[np.ndarray] = []

    def capture(self, simulation) -> None:
        data = simulation._data
        time = float(data.time)
        if self.times and time <= self.times[-1]:
            return
        self.times.append(time)
        self.qpos.append(np.array(data.qpos, copy=True))
        self.qvel.append(np.array(data.qvel, copy=True))
        self.ctrl.append(np.array(data.ctrl, copy=True))

    def wrap(self, monitor):
        collector = self
        class View:
            def step(self, control=None):
                state = monitor.step(control)
                step_count = round(monitor._simulation.simulation_time / monitor._simulation.timestep)
                if step_count % 25 == 0:
                    collector.capture(monitor._simulation)
                return state

            def __getattr__(self, name):
                return getattr(monitor, name)
        return View()

    def save(self, path: Path, simulation) -> None:
        self.capture(simulation)
        if len(self.times) < 2 or any(np.diff(self.times) <= 0):
            raise ValueError("Invalid pose sample times")
        if path.exists():
            raise FileExistsError(path)
        np.savez_compressed(path, time_s=np.array(self.times), qpos=np.stack(self.qpos),
                            qvel=np.stack(self.qvel), ctrl=np.stack(self.ctrl))


def verify_sources() -> dict:
    frozen = json.loads((HERE / "source_manifest.json").read_text(encoding="utf-8"))
    for relative, expected in frozen["files"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"Frozen source changed: {relative}")
    return frozen


def acquire() -> None:
    frozen = verify_sources()
    spec = json.loads((HERE / "protocol.json").read_text(encoding="utf-8"))
    protocol = load_protocol(spec["source_protocol"])
    robot = load_yaml(protocol["robot_config"])
    out = HERE / "artifacts"
    out.mkdir(exist_ok=True)
    for case_name in ("success_mission", "failure_mission"):
        mission = spec[case_name]
        for mode, gate in (("static_dispatch", False), ("strict_feedback", True)):
            run_dir = out / f"{case_name}--{mode}"
            if run_dir.exists():
                raise FileExistsError(f"Write-once run already exists: {run_dir}")
            run_dir.mkdir()
            poses = PoseCollector()
            holder = {}
            def factory(seed):
                session = LiveMissionSession(robot_config=robot, protocol=protocol,
                                             seed=seed, simulation_wrapper=poses.wrap)
                holder["session"] = session
                poses.capture(session.simulation)
                return session
            executor = MissionExecutor(
                validator=MissionValidator(), grounder=build_grounder(protocol),
                session_factory=factory, protocol=protocol,
                recorder_root=str(run_dir / "ledger"), seed=spec["seed"],
                provenance={"study": spec["experiment_id"], "mode": mode,
                            "source_manifest_sha256": digest(HERE / "source_manifest.json")},
                walk_strict_gate=gate)
            result = executor.run(mission, phase="m2_closed_loop", write_evidence=True)
            write_new(run_dir / "result.json", result.to_dict())
            if "session" in holder:
                poses.save(run_dir / "poses.npz", holder["session"].simulation)
            write_new(run_dir / "receipt.json", {
                "case": case_name, "mode": mode, "mission_id": mission["mission_id"],
                "result_sha256": digest(run_dir / "result.json"),
                "pose_sha256": digest(run_dir / "poses.npz") if (run_dir / "poses.npz").exists() else None,
                "source_manifest_sha256": digest(HERE / "source_manifest.json"),
                "state": result.state, "failure_type": result.failure_type,
                "completed_nodes": result.completed_nodes,
                "simulation_steps": result.simulation_steps_executed,
            })
            print(json.dumps({"case": case_name, "mode": mode, "state": result.state,
                              "failure_type": result.failure_type,
                              "completed_nodes": result.completed_nodes}), flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "freeze":
        freeze()
    elif len(sys.argv) == 2 and sys.argv[1] == "acquire":
        acquire()
    else:
        raise SystemExit("usage: acquire.py freeze|acquire")
