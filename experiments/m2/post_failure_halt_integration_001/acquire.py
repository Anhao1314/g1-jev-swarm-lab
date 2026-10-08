"""Two-run M2.1 integrated physical-halt validation; freeze before physics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from g1swarm.config import load_yaml
from g1swarm.mission import LiveMissionSession, MissionExecutor, MissionValidator
from scripts.run_oracle_missions import build_grounder, load_protocol
from experiments.m2.closed_loop_mission_001.acquire import PoseCollector

HERE = Path(__file__).resolve().parent
SOURCE_PATHS = (
    "configs/experiments/oracle_mission_runtime_001.yaml",
    "configs/robot/g1_locomotion_12dof.yaml",
    "third_party/unitree_rl_gym/resources/robots/g1_description/scene.xml",
    "third_party/unitree_rl_gym/resources/robots/g1_description/g1_12dof.xml",
    "third_party/unitree_rl_gym/deploy/pre_train/g1/motion.pt",
    "experiments/m2/closed_loop_mission_001/protocol.json",
    "experiments/m2/closed_loop_mission_001/acquire.py",
    "experiments/m2/closed_loop_mission_001/artifacts/failure_mission--strict_feedback/result.json",
    "experiments/m2/closed_loop_mission_001/artifacts/failure_mission--strict_feedback/poses.npz",
    "experiments/m2/closed_loop_mission_001/artifacts/failure_mission--static_dispatch/result.json",
    "experiments/m2/closed_loop_mission_001/artifacts/success_mission--strict_feedback/result.json",
    "experiments/m2/closed_loop_mission_001/artifacts/success_mission--strict_feedback/poses.npz",
    "experiments/m2/post_failure_halt_001/protocol.json",
    "experiments/m2/post_failure_halt_001/source_manifest_v2.json",
    "experiments/m2/post_failure_halt_001/artifacts/failure_feasibility/halt.json",
    "experiments/m2/post_failure_halt_001/artifacts/failure_feasibility/mission_result.json",
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
        "status": "FROZEN_BEFORE_INTEGRATION_PHYSICS",
        "files": {p.relative_to(ROOT).as_posix(): digest(p) for p in paths},
    })


def verify_sources() -> None:
    frozen = json.loads((HERE / "source_manifest.json").read_text(encoding="utf-8"))
    for relative, expected in frozen["files"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"Frozen source changed: {relative}")


def acquire() -> None:
    verify_sources()
    spec = json.loads((HERE / "protocol.json").read_text(encoding="utf-8"))
    missions = json.loads((ROOT / spec["mission_source"]).read_text(encoding="utf-8"))
    halt_contract = json.loads((ROOT / spec["halt_contract_source"]).read_text(encoding="utf-8"))
    protocol = load_protocol(spec["source_protocol"])
    robot = load_yaml(protocol["robot_config"])
    if digest(ROOT / robot["controller"]["policy_path"]) != protocol["provenance"]["policy_sha256"]:
        raise ValueError("Actual policy asset differs from frozen protocol SHA-256")
    manifest_sha = digest(HERE / "source_manifest.json")
    output = HERE / "artifacts"
    output.mkdir(exist_ok=True)
    for run_name, case_name in (("failure_opt_in", spec["failure_case"]),
                                ("safe_opt_in", spec["safe_control"])):
        run_dir = output / run_name
        run_dir.mkdir()
        holder: dict = {}
        poses = PoseCollector()

        def factory(seed):
            session = LiveMissionSession(robot_config=robot, protocol=protocol,
                                         seed=seed, simulation_wrapper=poses.wrap)
            holder["session"] = session
            poses.capture(session.simulation)
            return session

        try:
            executor = MissionExecutor(
                validator=MissionValidator(), grounder=build_grounder(protocol),
                session_factory=factory, protocol=protocol,
                recorder_root=str(run_dir / "ledger"), seed=spec["seed"],
                provenance={"study": spec["experiment_id"], "run": run_name,
                            "source_manifest_sha256": manifest_sha},
                walk_strict_gate=True,
                physical_halt_contract=halt_contract,
            )
            result = executor.run(missions[case_name], phase="m2_post_failure_halt_integration",
                                  write_evidence=True)
            write_new(run_dir / "result.json", result.to_dict())
            if "session" in holder:
                poses.save(run_dir / "poses.npz", holder["session"].simulation)
            write_new(run_dir / "receipt.json", {
                "run": run_name, "mission_id": missions[case_name]["mission_id"],
                "source_manifest_sha256": manifest_sha,
                "result_sha256": digest(run_dir / "result.json"),
                "pose_sha256": digest(run_dir / "poses.npz") if (run_dir / "poses.npz").exists() else None,
                "state": result.state, "failure_type": result.failure_type,
                "skill_invocations": result.skill_invocations,
                "physical_halt_status": (result.physical_halt or {}).get("status"),
            })
        except Exception as exc:
            write_new(run_dir / "acquisition_failure.json", {
                "status": "ACQUISITION_FAILED", "run": run_name,
                "failure_type": type(exc).__name__, "failure_reason": str(exc),
                "source_manifest_sha256": manifest_sha,
                "result_sha256": digest(run_dir / "result.json") if (run_dir / "result.json").exists() else None,
                "pose_sha256": digest(run_dir / "poses.npz") if (run_dir / "poses.npz").exists() else None,
            })
            raise


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "freeze":
        freeze()
    elif len(sys.argv) == 2 and sys.argv[1] == "acquire":
        acquire()
    else:
        raise SystemExit("usage: acquire.py freeze|acquire")
