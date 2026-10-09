"""Experiment-only M2.5A acquisition adapter. Import and preflight do no physics.

The three frozen parent missions are executed once each. A qualifying terminal
StopSkill state is continued for exactly 1000 native steps with the existing
session/controller and the StopSkill torque helper. Neither this module nor its
offline tests grant permission to execute that future physical experiment.
"""

from __future__ import annotations

import argparse
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
READINESS = HERE / "readiness_manifest.json"
M24 = ROOT / "experiments/m2/cross_state_reliability_001/protocol.json"
REQUIRED_READINESS_FILES = {
    "experiments/m2/post_halt_hold_design_001/acquire.py",
    "experiments/m2/post_halt_hold_design_001/protocol.json",
    "experiments/m2/post_halt_hold_design_001/source_binding.json",
    "experiments/m2/cross_state_reliability_001/protocol.json",
    "src/g1swarm/skills/basic.py",
    "src/g1swarm/mission/live_session.py",
    "src/g1swarm/control/g1_locomotion.py",
    "src/g1swarm/simulation/g1_simulation.py",
}


def target_import_witness() -> dict:
    """Pin package resolution to this checkout without importing live modules.

    The frozen Windows virtualenv has historically used an editable install
    pointing at another worktree. Running its interpreter alone is therefore
    insufficient provenance for a new physical acquisition.
    """
    src = (ROOT / "src").resolve()
    root = ROOT.resolve()
    for path in (root, src):
        if str(path) in sys.path:
            sys.path.remove(str(path))
        sys.path.insert(0, str(path))
    expected = {
        "g1swarm": src / "g1swarm/__init__.py",
        "scripts.run_oracle_missions": root / "scripts/run_oracle_missions.py",
    }
    found = {}
    for name, path in expected.items():
        module = sys.modules.get(name)
        spec = module.__spec__ if module is not None else importlib.util.find_spec(name)
        origin = Path(spec.origin).resolve() if spec is not None and spec.origin else None
        if origin != path:
            raise IntegrityFailure("TARGET_CHECKOUT_IMPORT_ORIGIN_MISMATCH:" + name)
        found[name] = origin.as_posix()
    for name, module in tuple(sys.modules.items()):
        if not name.startswith("g1swarm.") or module is None:
            continue
        spec = getattr(module, "__spec__", None)
        origin = Path(spec.origin).resolve() if spec is not None and spec.origin else None
        if origin is not None and not origin.is_relative_to(src / "g1swarm"):
            raise IntegrityFailure("STALE_LOADED_G1SWARM_SUBMODULE:" + name)
    return {"status": "TARGET_CHECKOUT_IMPORT_PATHS_VERIFIED_NO_LIVE_IMPORT",
            "root": root.as_posix(), "source_root": src.as_posix(), "module_origins": found}


class IntegrityFailure(RuntimeError):
    """Source, state-continuity, evidence, or authority invariant failed."""


class BudgetFailure(RuntimeError):
    """Frozen per-cell or total resource bound was reached."""


class MissingEvidence(RuntimeError):
    """Required measured values were not present; no result may be imputed."""


def reset_permitted(kind: str, phase: str, qualified_stop: bool) -> bool:
    """Parent skills may reset controller memory; the physical simulator may not."""
    if kind in {"simulation", "native"}:
        return phase == "initialization"
    if kind == "controller":
        return phase != "hold" and not qualified_stop
    if kind == "keyframe":
        return False
    raise ValueError("Unknown reset kind")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_safe(value: Any) -> Any:
    """Represent nonfinite original observations explicitly, without JSON NaN."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": repr(value)}
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(item) for item in value]
    return value


def write_new(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf8", newline="\n") as stream:
        json.dump(json_safe(value), stream, indent=2, allow_nan=False, sort_keys=True)
        stream.write("\n")


def preflight(readiness_sha256: str) -> tuple[dict, dict, dict]:
    """Target-environment integrity gate. It imports no simulator or policy."""
    if not readiness_sha256 or not READINESS.is_file() or sha256(READINESS) != readiness_sha256:
        raise IntegrityFailure("EXACT_READINESS_SHA256_REQUIRED")
    target_import_witness()
    receipt = json.loads(READINESS.read_text(encoding="utf8"))
    if receipt.get("status") != "READY_FOR_OWNER_ACQUISITION_AUTHORIZATION" or receipt.get("physics_authorized") is not False:
        raise IntegrityFailure("READINESS_NOT_ACCEPTED_OR_FALSE_AUTHORITY")
    files = receipt.get("sha256", {})
    if not isinstance(files, dict) or not files:
        raise IntegrityFailure("READINESS_RECEIPT_COVERAGE_INCOMPLETE")
    source_manifest = HERE / "source_manifest.json"
    if not source_manifest.is_file() or receipt.get("source_manifest_sha256") != sha256(source_manifest):
        raise IntegrityFailure("EXECUTION_SOURCE_MANIFEST_MISMATCH")
    source_files = json.loads(source_manifest.read_text(encoding="utf8")).get("files", {})
    if not REQUIRED_READINESS_FILES <= set(source_files):
        raise IntegrityFailure("READINESS_SOURCE_COVERAGE_INCOMPLETE")
    for name, expected in files.items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or sha256(path) != expected:
            raise IntegrityFailure("FROZEN_SOURCE_OR_ASSET_MISMATCH:" + name)
    # The target gate checks inherited 241 files, 91 assets, 41 dependencies,
    # XML resources, candidate provenance, and the new execution source closure.
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from readiness import check_target

    check_target(require_new_source=True)
    spec = json.loads((HERE / "protocol.json").read_text(encoding="utf8"))
    m24 = json.loads(M24.read_text(encoding="utf8"))
    if spec["physics_authorized"] is not False or len(spec["cells_in_order"]) != 3:
        raise IntegrityFailure("CANDIDATE_PROTOCOL_CHANGED")
    return spec, m24, receipt


def fixed_parent(m24: dict, cell: dict) -> dict:
    if cell["m24_state"] == "normal_control":
        return deepcopy(m24["normal_control"])
    state = next((row for row in m24["states"] if row["id"] == cell["m24_state"]), None)
    if state is None or state.get("push") is not None:
        raise IntegrityFailure("UNEXPECTED_OR_DISTURBED_PARENT_STATE")
    return deepcopy(state["parent_mission"])


def verify_historical_parent_native(cell: dict, observed: list[dict], *, root: Path = ROOT) -> dict:
    """Bind the newly replayed parent to its sealed M2.4 predecision prefix."""
    arm = cell["m24_state"] + "--" + cell["historical_arm"]
    archive_path = root / "experiments/m2/cross_state_reliability_archives_001" / (arm + ".tar.gz")
    raw_seal = json.loads((root / "experiments/m2/cross_state_reliability_analysis_001/raw_evidence_manifest.json").read_text(encoding="utf8"))
    archive_seal = json.loads((root / "experiments/m2/cross_state_reliability_archives_001/manifest.json").read_text(encoding="utf8"))
    if sha256(archive_path) != archive_seal["archives"][archive_path.name]["sha256"]:
        raise IntegrityFailure("HISTORICAL_ARCHIVE_HASH_MISMATCH")
    member_name = "experiments/m2/cross_state_reliability_001/artifacts/" + arm + "/predecision_native_trace.json"
    with tarfile.open(archive_path, "r:gz") as archive:
        member = archive.extractfile(member_name)
        if member is None:
            raise MissingEvidence("HISTORICAL_PARENT_NATIVE_TRACE_MISSING")
        with member:
            raw = member.read()
    if hashlib.sha256(raw).hexdigest() != raw_seal["files"][member_name]["sha256"]:
        raise IntegrityFailure("HISTORICAL_PARENT_NATIVE_TRACE_HASH_MISMATCH")
    historical = json.loads(raw)
    fields = ("time_s", "qpos", "qvel", "ctrl", "xfrc_applied", "controller")
    if len(historical) != len(observed):
        raise IntegrityFailure("HISTORICAL_PARENT_NATIVE_STEP_COUNT_MISMATCH")
    for index, (old, new) in enumerate(zip(historical, observed, strict=True)):
        if any(old.get(field) != new.get(field) for field in fields):
            raise IntegrityFailure("HISTORICAL_PARENT_NATIVE_PREFIX_MISMATCH_AT_STEP:" + str(index + 1))
    return {"status": "EXACT_M24_PARENT_NATIVE_PREFIX_MATCH", "arm": arm,
            "steps": len(observed), "historical_member_sha256": hashlib.sha256(raw).hexdigest()}


def entry_classification(parent: dict, cell: dict, terminal: dict | None) -> tuple[str | None, str]:
    """Return either frozen hold eligibility or an honest no-coverage status."""
    if cell["role"] == "failure_halt_qualification":
        if parent.get("mission_success") is True:
            return None, "PARENT_PASS_NO_HALT_NO_HOLD"
        if parent.get("failure_type") != "TASK_ENVELOPE_VIOLATION" or parent.get("failed_node") != "s1":
            return None, "INCONCLUSIVE_MISSING_EVIDENCE"
        halt = parent.get("physical_halt")
        if not halt:
            return None, "HALT_NOT_REQUESTED_NO_HOLD"
        if halt.get("status") != "HALT_SUCCEEDED":
            return None, "HALT_FAILED_NO_HOLD"
        if halt.get("skill_status") != "SUCCESS" or not halt.get("checks") or not all(halt["checks"].values()):
            return None, "INCONCLUSIVE_MISSING_EVIDENCE"
    elif cell["role"] == "ordinary_stop_measurement_control_not_matched_failure_state":
        nodes = parent.get("nodes") or []
        if not (parent.get("mission_success") is True and parent.get("physical_success") is True
                and parent.get("completed_nodes") == 3 and not parent.get("physical_halt")
                and nodes and nodes[-1].get("skill") == "stop"
                and nodes[-1].get("metrics", {}).get("skill_status") == "SUCCESS"):
            return None, "CONTROL_FAILED_NO_HOLD"
    else:
        raise IntegrityFailure("UNKNOWN_FROZEN_CELL_ROLE")
    if not terminal or terminal.get("stop_status") != "SUCCESS":
        return None, "INCONCLUSIVE_MISSING_EVIDENCE"
    return "ELIGIBLE", "HOLD_REQUIRED"


def verify_stop_seed(terminal: dict, parent: dict, cell: dict, *, window: int) -> list[float]:
    speeds = terminal.get("stop_poststep_speeds")
    if not isinstance(speeds, list) or len(speeds) < window:
        raise MissingEvidence("FIRST_CROSSING_WINDOW_MISSING")
    seed = [float(value) for value in speeds[-window:]]
    if not all(math.isfinite(value) for value in seed):
        raise MissingEvidence("FIRST_CROSSING_SPEED_NONFINITE")
    reported = terminal.get("stop_window_mean_mps")
    if reported is None or not math.isclose(sum(seed) / window, float(reported), rel_tol=0, abs_tol=1e-9):
        raise IntegrityFailure("STOP_SKILL_WINDOW_SEED_MISMATCH")
    if cell["role"] == "failure_halt_qualification":
        halt = parent["physical_halt"]
        rows = halt.get("trace")
        if not isinstance(rows, list) or len(rows) < window + 1:
            raise MissingEvidence("HALT_POSTSTEP_TRACE_MISSING")
        halt_seed = [float(row["speed_mps"]) for row in rows[-window:]]
        if seed != halt_seed:
            raise IntegrityFailure("HALT_TRACE_STOP_WINDOW_MISMATCH")
    return seed


def continuity_core(snapshot: dict) -> dict:
    keys = ("time_s", "qpos", "qvel", "ctrl", "xfrc_applied", "controller_action",
            "controller_target", "controller_counter", "session_identity",
            "simulation_identity", "controller_identity", "policy_identity",
            "reset_calls", "native_reset_calls", "keyframe_reset_calls",
            "controller_reset_calls", "node_dispatches", "executor_dispatches")
    if not all(key in snapshot for key in keys):
        raise MissingEvidence("CONTINUITY_SNAPSHOT_INCOMPLETE")
    return {key: snapshot[key] for key in keys}


def assess_hold(rows: list[dict], seed: list[float], spec: dict, terminal: dict) -> dict:
    """Apply only frozen criteria. A partial row set can never pass."""
    hold = spec["hold"]
    expected = hold["native_steps"]
    rolling = deque(seed, maxlen=hold["rolling_window_steps"])
    if len(rolling) != rolling.maxlen:
        raise MissingEvidence("HOLD_WINDOW_SEED_INCOMPLETE")
    means, path = [], 0.0
    previous = terminal["snapshot"]["qpos"][:2]
    for row in rows:
        speed = float(row["speed_mps"])
        rolling.append(speed)
        means.append(sum(rolling) / len(rolling))
        xy = row["position_m"][:2]
        path += math.dist(previous, xy)
        previous = xy
    acceptance = hold["acceptance"]
    checks = {
        "complete_1000_steps": len(rows) == expected,
        "rolling_mean": len(means) == expected and all(math.isfinite(value) and value <= acceptance["all_1000_rolling_means_at_most_mps"] for value in means),
        "final_speed": len(rows) == expected and math.isfinite(float(rows[-1]["speed_mps"])) and float(rows[-1]["speed_mps"]) <= acceptance["final_instantaneous_speed_at_most_mps"],
        "xy_path_length": math.isfinite(path) and path <= acceptance["hold_xy_path_length_at_most_m"],
        "finite_throughout": len(rows) == expected and all(row["finite"] and row["raw_finite"] for row in rows),
        "standing_throughout": len(rows) == expected and all(row["standing"] for row in rows),
        "no_fall_throughout": len(rows) == expected and not any(row["fallen"] for row in rows),
    }
    return {
        "status": "HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE" if all(checks.values()) else "HOLD_FAILED",
        "checks": checks,
        "measured_steps": len(rows),
        "xy_path_length_m": path,
        "last_speed_mps": rows[-1]["speed_mps"] if rows else None,
        "rolling_mean_speed_mps": means,
        "one_second_disjoint_means_mps": [sum(row["speed_mps"] for row in rows[start:start + 500]) / 500 for start in (0, 500)] if len(rows) == expected else None,
        "maximum_instantaneous_speed_mps": max((row["speed_mps"] for row in rows), default=None),
    }


def run_cell(spec: dict, m24: dict, cell: dict, run_dir: Path, backend, *, prior_native_steps: int = 0) -> dict:
    """Common production/fake stage order; no real imports in this function."""
    result = {"cell_id": cell["id"], "status": "PARTIAL_STOPPED", "coverage": "NOT_EVALUATED"}
    with backend(spec, m24, cell, run_dir, prior_native_steps) as rt:
        session, executor = rt["session"], rt["executor"]
        parent = executor.run(fixed_parent(m24, cell), existing_session=session, phase="m25a_parent")
        parent_dict = parent.to_dict()
        write_new(run_dir / "parent_result.json", parent_dict)
        if executor.last_graph is None:
            raise MissingEvidence("PARENT_GRAPH_MISSING")
        write_new(run_dir / "parent_graph.json", executor.last_graph.to_dict())
        terminal = rt["terminal"]
        result.update(parent_status=parent_dict.get("state"), parent_failure_type=parent_dict.get("failure_type"),
                      parent_halt_status=(parent_dict.get("physical_halt") or {}).get("status"))
        if rt["witness"].get("integrity_failure"):
            raise IntegrityFailure(rt["witness"]["integrity_failure"])
        if rt["witness"].get("budget_failure"):
            raise BudgetFailure(rt["witness"]["budget_failure"])
        try:
            prefix = rt["verify_historical_parent"]()
        except MissingEvidence as exc:
            result.update(status="INCONCLUSIVE_MISSING_EVIDENCE", coverage="NO_HOLD", reason=str(exc))
            rt["witness"]["outcome_status"] = result["status"]
            write_new(run_dir / "outcome.json", result)
            return result
        write_new(run_dir / "historical_parent_prefix.json", prefix)
        eligibility, reason = entry_classification(parent_dict, cell, terminal)
        if eligibility is None:
            result.update(status=reason, coverage="NO_HOLD")
            rt["witness"]["outcome_status"] = result["status"]
            write_new(run_dir / "outcome.json", result)
            return result
        assert terminal is not None
        try:
            seed = verify_stop_seed(terminal, parent_dict, cell, window=spec["hold"]["rolling_window_steps"])
            before = rt["snapshot"]()
            skill_return_core = continuity_core(terminal["skill_return_snapshot"])
            terminal_core = continuity_core(terminal["snapshot"])
            before_core = continuity_core(before)
        except (MissingEvidence, KeyError, TypeError) as exc:
            result.update(status="INCONCLUSIVE_MISSING_EVIDENCE", coverage="NO_HOLD", reason=str(exc))
            rt["witness"]["outcome_status"] = result["status"]
            write_new(run_dir / "outcome.json", result)
            return result
        if skill_return_core != terminal_core or terminal_core != before_core:
            raise IntegrityFailure("TERMINAL_STOP_TO_HOLD_ENTRY_CHANGED")
        crossing_time = terminal.get("stop_crossing_time_s")
        if crossing_time is None or not math.isclose(float(crossing_time), terminal_core["time_s"], rel_tol=0, abs_tol=1e-9):
            raise IntegrityFailure("HOLD_ENTRY_NOT_FIRST_STOP_CROSSING")
        if rt["witness"]["native_steps"] + spec["hold"]["native_steps"] > cell["max_native_steps"]:
            raise BudgetFailure("CELL_NATIVE_STEPS_CANNOT_FIT_HOLD")
        if prior_native_steps + rt["witness"]["native_steps"] + spec["hold"]["native_steps"] > spec["budget"]["maximum_native_steps_total"]:
            raise BudgetFailure("CAMPAIGN_NATIVE_STEPS_CANNOT_FIT_HOLD")
        write_new(run_dir / "hold_entry.json", {"terminal": terminal, "pre_first_step": before, "seed_speeds_mps": seed})
        rt["begin_hold"]()
        rows = []
        previous_time = float(before["time_s"])
        for index in range(spec["hold"]["native_steps"]):
            rt["guard"]()
            try:
                state = rt["step_zero"]()
            except (IntegrityFailure, BudgetFailure):
                raise
            except Exception as exc:
                if rt["witness"].get("integrity_failure"):
                    raise IntegrityFailure(rt["witness"]["integrity_failure"]) from exc
                if rt["witness"].get("budget_failure"):
                    raise BudgetFailure(rt["witness"]["budget_failure"]) from exc
                raw = rt["raw_last"]()
                if raw is not None and raw.get("raw_finite") is False:
                    result.update(status="HOLD_FAILED", coverage="PARTIAL_PHYSICAL_NONFINITE", reason="NONFINITE_PHYSICAL_STATE", observed_hold_steps=len(rows))
                    break
                result.update(status="TECHNICAL_PARTIAL", coverage="PARTIAL_TECHNICAL", reason=type(exc).__name__ + ": " + str(exc), observed_hold_steps=len(rows))
                break
            row = rt["state_row"](state, index + 1)
            if not math.isclose(float(row["time_s"]) - previous_time,
                                spec["fixed_config"]["native_timestep_s"], rel_tol=0, abs_tol=1e-8):
                raise IntegrityFailure("HOLD_NATIVE_TIME_DISCONTINUITY")
            previous_time = float(row["time_s"])
            rows.append(row)
            rt["journal_hold_row"](row)
            if not row["finite"] or not row["raw_finite"] or row["fallen"] or not row["standing"]:
                result.update(status="HOLD_FAILED", coverage="PARTIAL_PHYSICAL_UNSAFE", reason="EARLY_UNSAFE_STOP", observed_hold_steps=len(rows))
                break
        after = rt["snapshot"]()
        if after["session_identity"] != before["session_identity"] or after["simulation_identity"] != before["simulation_identity"] or after["controller_identity"] != before["controller_identity"] or after["policy_identity"] != before["policy_identity"]:
            raise IntegrityFailure("CONTROL_OBJECT_IDENTITY_CHANGED")
        for key in ("reset_calls", "native_reset_calls", "keyframe_reset_calls", "controller_reset_calls", "node_dispatches", "executor_dispatches"):
            if after[key] != before[key]:
                raise IntegrityFailure("FORBIDDEN_RESET_OR_DISPATCH_DURING_HOLD:" + key)
        if rt["witness"].get("integrity_failure"):
            raise IntegrityFailure(rt["witness"]["integrity_failure"])
        if rt["witness"].get("budget_failure"):
            raise BudgetFailure(rt["witness"]["budget_failure"])
        if len(rows) == spec["hold"]["native_steps"]:
            if after["controller_counter"] - before["controller_counter"] != len(rows):
                raise IntegrityFailure("CONTROLLER_COUNTER_NOT_ONE_PER_HOLD_STEP")
            if rt["witness"]["native_steps"] - before["native_steps"] != len(rows):
                raise IntegrityFailure("HOLD_NATIVE_STEP_COUNT_MISMATCH")
            if rt["witness"]["hold_command_calls"] != len(rows):
                raise IntegrityFailure("HOLD_ZERO_COMMAND_COUNT_MISMATCH")
            result.update(assess_hold(rows, seed, spec, terminal))
            result["coverage"] = "COMPLETE_HOLD"
        result.update(hold_terminal=after, hold_observed_steps=len(rows), native_steps=rt["witness"]["native_steps"],
                      reset_memory_observation="indirect: pinned controller reset is the only source call; hidden recurrent bytes not snapshotted")
        rt["witness"]["outcome_status"] = result["status"]
        write_new(run_dir / "hold_metrics.json", {"result": result, "rows": rows})
        write_new(run_dir / "outcome.json", result)
        return result


@contextmanager
def production_backend(spec: dict, m24: dict, cell: dict, run_dir: Path, prior_native_steps: int):
    """Lazy MuJoCo resources. This function is never entered during preparation."""
    import_witness = target_import_witness()
    import numpy as np
    import mujoco
    from g1swarm.config import load_yaml
    from g1swarm.mission import LiveMissionSession, MissionExecutor, MissionValidator
    from g1swarm.simulation.g1_simulation import G1Simulation
    from g1swarm.control.g1_locomotion import G1LocomotionController
    from g1swarm.skills.basic import StopSkill, _policy_torques
    from g1swarm.skills.contract import SkillContext
    from scripts.run_oracle_missions import load_protocol, build_grounder

    runtime_protocol = load_protocol(spec["fixed_config"]["runtime_protocol"])
    robot = load_yaml(runtime_protocol["robot_config"])
    halt = json.loads((ROOT / m24["contracts"]["halt_contract"]).read_text(encoding="utf8"))
    witness = {"attempt": 1, "target_import_witness": import_witness,
               "native_steps": 0, "reset_calls": 0, "native_reset_calls": 0,
               "keyframe_reset_calls": 0, "controller_reset_calls": 0,
               "node_dispatches": 0, "executor_dispatches": 0,
               "phase": "initialization", "qualified_stop": False,
               "integrity_failure": None, "budget_failure": None,
               "parent_native_steps": None, "hold_native_steps": 0,
               "hold_command_calls": 0, "outcome_status": "PARTIAL_STOPPED",
               "protocol_sha256": sha256(HERE / "protocol.json"),
               "readiness_sha256": sha256(READINESS),
               "source_manifest_sha256": sha256(HERE / "source_manifest.json"),
               "policy_reset_memory_witness": "indirect via pinned controller.reset call path; no direct hidden-memory bytes"}
    terminal = {}
    native_rows: list[dict] = []
    state_rows: list[dict] = []
    started = time.perf_counter()
    session = None
    original = {
        "sim_step": G1Simulation.step, "sim_reset": G1Simulation.reset,
        "mj_step": mujoco.mj_step, "mj_reset": mujoco.mj_resetData,
        "mj_keyframe": mujoco.mj_resetDataKeyframe,
        "controller_reset": G1LocomotionController.reset,
        "stop_run": StopSkill.run, "node": LiveMissionSession.run_node,
        "halt": LiveMissionSession.run_failure_halt,
    }
    journal = (run_dir / "native_incremental.jsonl").open("x", encoding="utf8", newline="\n", buffering=1)
    hold_journal = (run_dir / "hold_incremental.jsonl").open("x", encoding="utf8", newline="\n", buffering=1)

    def guard(*, stepping=False):
        elapsed = time.perf_counter() - started
        if elapsed >= cell["max_wall_s"]:
            witness["budget_failure"] = "CELL_WALL_BUDGET_EXHAUSTED"
            raise BudgetFailure(witness["budget_failure"])
        if stepping and (witness["native_steps"] >= cell["max_native_steps"] or
                         prior_native_steps + witness["native_steps"] >= spec["budget"]["maximum_native_steps_total"]):
            witness["budget_failure"] = "NATIVE_STEP_BUDGET_EXHAUSTED"
            raise BudgetFailure(witness["budget_failure"])

    def raw_snapshot() -> dict:
        if session is None:
            raise MissingEvidence("SESSION_NOT_AVAILABLE")
        sim, controller = session.simulation, session.controller
        data = sim._data
        return {
            "time_s": float(data.time), "qpos": data.qpos.tolist(), "qvel": data.qvel.tolist(),
            "ctrl": data.ctrl.tolist(), "xfrc_applied": data.xfrc_applied.tolist(),
            "controller_action": np.asarray(controller._action).tolist(),
            "controller_target": np.asarray(controller._target).tolist(),
            "controller_counter": int(controller._counter),
            "session_identity": id(session), "simulation_identity": id(sim),
            "controller_identity": id(controller), "policy_identity": id(controller._policy),
            "reset_calls": witness["reset_calls"], "native_reset_calls": witness["native_reset_calls"],
            "keyframe_reset_calls": witness["keyframe_reset_calls"],
            "controller_reset_calls": witness["controller_reset_calls"],
            "node_dispatches": witness["node_dispatches"], "executor_dispatches": witness["executor_dispatches"],
            "native_steps": witness["native_steps"], "session_steps": session.total_steps,
        }

    def sim_reset(obj, *args, **kwargs):
        witness["reset_calls"] += 1
        if not reset_permitted("simulation", witness["phase"], witness["qualified_stop"]):
            witness["integrity_failure"] = "POST_INITIALIZATION_SIM_RESET_FORBIDDEN"
            raise IntegrityFailure(witness["integrity_failure"])
        return original["sim_reset"](obj, *args, **kwargs)

    def mj_reset(*args, **kwargs):
        witness["native_reset_calls"] += 1
        if not reset_permitted("native", witness["phase"], witness["qualified_stop"]):
            witness["integrity_failure"] = "POST_INITIALIZATION_NATIVE_RESET_FORBIDDEN"
            raise IntegrityFailure(witness["integrity_failure"])
        return original["mj_reset"](*args, **kwargs)

    def mj_keyframe(*args, **kwargs):
        witness["keyframe_reset_calls"] += 1
        witness["integrity_failure"] = "KEYFRAME_RESET_FORBIDDEN"
        raise IntegrityFailure(witness["integrity_failure"])

    def controller_reset(obj, *args, **kwargs):
        witness["controller_reset_calls"] += 1
        if not reset_permitted("controller", witness["phase"], witness["qualified_stop"]):
            witness["integrity_failure"] = "CONTROLLER_RESET_AFTER_STOP_CROSSING"
            raise IntegrityFailure(witness["integrity_failure"])
        return original["controller_reset"](obj, *args, **kwargs)

    def mj_step(*args, **kwargs):
        guard(stepping=True)
        result = original["mj_step"](*args, **kwargs)
        witness["native_steps"] += 1
        data = args[1]
        raw = {"sequence": witness["native_steps"], "phase": witness["phase"],
               "time_s": float(data.time), "qpos": data.qpos.tolist(),
               "qvel": data.qvel.tolist(), "ctrl": data.ctrl.tolist(),
               "xfrc_applied": data.xfrc_applied.tolist(),
               "controller": {"_action": np.asarray(session.controller._action).tolist(),
                              "_target": np.asarray(session.controller._target).tolist(),
                              "_counter": int(session.controller._counter)} if session is not None else None,
               "raw_finite": bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all()
                                  and np.isfinite(data.ctrl).all() and np.isfinite(data.xfrc_applied).all()
                                  and (session is None or (np.isfinite(session.controller._action).all()
                                      and np.isfinite(session.controller._target).all())))}
        native_rows.append(raw)
        journal.write(json.dumps(json_safe(raw), allow_nan=False, sort_keys=True) + "\n")
        return result

    def sim_step(obj, control=None):
        state = original["sim_step"](obj, control)
        state_rows.append({"sequence": witness["native_steps"], "speed_mps": state.speed(),
                           "phase": witness["phase"]})
        if len(state_rows) != witness["native_steps"]:
            witness["integrity_failure"] = "SIM_NATIVE_STEP_COUNT_MISMATCH"
            raise IntegrityFailure(witness["integrity_failure"])
        return state

    def stop_run(obj, context):
        start = len(state_rows)
        result = original["stop_run"](obj, context)
        if terminal:
            witness["integrity_failure"] = "MULTIPLE_STOP_TERMINALS"
            raise IntegrityFailure(witness["integrity_failure"])
        terminal.update(stop_status=result.status.value,
                        stop_window_mean_mps=result.metrics.get("final_window_mean_speed_mps"),
                        stop_crossing_time_s=result.metrics.get("threshold_crossing_sim_time"),
                        stop_poststep_speeds=[row["speed_mps"] for row in state_rows[start:]],
                        skill_return_snapshot=raw_snapshot())
        witness["qualified_stop"] = result.status.value == "SUCCESS"
        return result

    def node(obj, target, mode):
        if witness["phase"] == "hold" or witness["qualified_stop"]:
            witness["integrity_failure"] = "TASK_NODE_DISPATCH_AFTER_STOP_CROSSING"
            raise IntegrityFailure(witness["integrity_failure"])
        witness["node_dispatches"] += 1
        result = original["node"](obj, target, mode)
        if target.skill.value == "stop" and terminal:
            terminal["snapshot"] = raw_snapshot()
        return result

    def halt_call(obj, contract):
        if witness["phase"] == "hold":
            witness["integrity_failure"] = "SECOND_HALT_DISPATCH_DURING_HOLD"
            raise IntegrityFailure(witness["integrity_failure"])
        if not np.all(obj.simulation._data.xfrc_applied == 0):
            witness["integrity_failure"] = "NONZERO_EXTERNAL_FORCE_BEFORE_HALT"
            raise IntegrityFailure(witness["integrity_failure"])
        result = original["halt"](obj, contract)
        if terminal:
            terminal["snapshot"] = raw_snapshot()
        return result

    G1Simulation.step, G1Simulation.reset = sim_step, sim_reset
    mujoco.mj_step, mujoco.mj_resetData, mujoco.mj_resetDataKeyframe = mj_step, mj_reset, mj_keyframe
    G1LocomotionController.reset, StopSkill.run = controller_reset, stop_run
    LiveMissionSession.run_node, LiveMissionSession.run_failure_halt = node, halt_call
    try:
        session = LiveMissionSession(robot_config=robot, protocol=runtime_protocol, seed=spec["fixed_config"]["seed"])
        if witness["reset_calls"] != 2 or witness["native_reset_calls"] != 2 or witness["keyframe_reset_calls"] != 0:
            raise IntegrityFailure("INITIALIZATION_RESET_COUNTS_MISMATCH")
        witness["phase"] = "parent"

        def forbidden_factory(seed):
            witness["integrity_failure"] = "NEW_SESSION_FACTORY_CALLED"
            raise IntegrityFailure(witness["integrity_failure"])

        executor = MissionExecutor(
            validator=MissionValidator(), grounder=build_grounder(runtime_protocol),
            session_factory=forbidden_factory, protocol=runtime_protocol,
            recorder_root=str(run_dir / "ledger"), seed=spec["fixed_config"]["seed"],
            provenance={"study": spec["experiment_id"], "cell": cell["id"],
                        "protocol_sha256": sha256(HERE / "protocol.json")},
            walk_strict_gate=True, physical_halt_contract=halt,
        )
        original_run = executor.run

        def observed_run(*args, **kwargs):
            if witness["phase"] == "hold":
                witness["integrity_failure"] = "NEW_MISSION_DISPATCH_DURING_HOLD"
                raise IntegrityFailure(witness["integrity_failure"])
            witness["executor_dispatches"] += 1
            return original_run(*args, **kwargs)

        executor.run = observed_run

        def begin_hold():
            if witness["phase"] != "parent" or not terminal.get("snapshot"):
                raise IntegrityFailure("NO_QUALIFYING_TERMINAL_STATE")
            if not np.all(session.simulation._data.xfrc_applied == 0):
                raise IntegrityFailure("NONZERO_EXTERNAL_FORCE_AT_HOLD_ENTRY")
            witness["parent_native_steps"] = witness["native_steps"]
            witness["phase"] = "hold"

        def step_zero():
            if witness["phase"] != "hold":
                raise IntegrityFailure("HOLD_NOT_STARTED")
            context = SkillContext(simulation=session.simulation, controller=session.controller,
                                   robot_config=session.robot_config, seed=session.seed)
            command = np.zeros(3, dtype=np.float64)
            if not np.array_equal(command, np.asarray(spec["hold"]["command_xyz_mps_radps"])):
                raise IntegrityFailure("HOLD_COMMAND_NOT_EXACT_ZERO")
            witness["hold_command_calls"] += 1
            torques = _policy_torques(context, command)
            state = session.simulation.step(torques)
            session.current_state = state
            session.total_steps += 1
            return state

        def state_row(state, index):
            raw = native_rows[-1]
            w, x, y, z = (float(value) for value in state.base_orientation)
            roll = math.degrees(math.atan2(2 * (w*x + y*z), 1 - 2 * (x*x + y*y)))
            pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w*y - z*x)))))
            tilt = math.degrees(math.acos(max(-1.0, min(1.0, 1 - 2 * (x*x + y*y)))))
            return {"hold_step": index, "native_sequence": raw["sequence"], "time_s": state.simulation_time,
                    "position_m": list(state.base_position), "speed_mps": state.speed(),
                    "base_height_m": state.base_position[2], "standing": state.standing,
                    "fallen": state.fallen, "finite": state.is_finite(), "raw_finite": raw["raw_finite"],
                    "orientation_wxyz": list(state.base_orientation),
                    "roll_deg": roll, "pitch_deg": pitch, "tilt_deg": tilt,
                    "controller_counter": session.controller._counter,
                    "controller_action": np.asarray(session.controller._action).tolist(),
                    "controller_target": np.asarray(session.controller._target).tolist(),
                    "contact_count": session.simulation.contact_count(),
                    "mujoco_warning": session.simulation.mujoco_warning(),
                    "command_xyz_mps_radps": [0.0, 0.0, 0.0]}

        yield {"session": session, "executor": executor, "terminal": terminal,
               "witness": witness, "snapshot": raw_snapshot, "begin_hold": begin_hold,
               "step_zero": step_zero, "state_row": state_row, "raw_last": lambda: native_rows[-1] if native_rows else None,
               "guard": guard,
               "verify_historical_parent": lambda: verify_historical_parent_native(cell, native_rows),
               "journal_hold_row": lambda row: hold_journal.write(json.dumps(json_safe(row), allow_nan=False, sort_keys=True) + "\n")}
    finally:
        try:
            try:
                journal.close()
                hold_journal.close()
                witness["native_journal_rows"] = len(native_rows)
                witness["hold_native_steps"] = len([row for row in native_rows if row["phase"] == "hold"])
                if witness["parent_native_steps"] is None:
                    witness["parent_native_steps"] = witness["native_steps"] - witness["hold_native_steps"]
                witness["hold_journal_rows"] = sum(1 for _ in (run_dir / "hold_incremental.jsonl").open(encoding="utf8"))
                witness["terminal_seen"] = bool(terminal)
                if session is not None:
                    witness["session_identity"] = id(session)
                    witness["simulation_identity"] = id(session.simulation)
                    witness["controller_identity"] = id(session.controller)
                    witness["policy_identity"] = id(session.controller._policy)
                    try:
                        witness["final_snapshot"] = raw_snapshot()
                    except Exception as exc:
                        witness["final_snapshot_error"] = type(exc).__name__ + ": " + str(exc)
                witness["terminal_snapshot"] = terminal.get("snapshot")
                write_new(run_dir / "witness.json", witness)
            finally:
                if session is not None:
                    session.close()
        finally:
            G1Simulation.step, G1Simulation.reset = original["sim_step"], original["sim_reset"]
            mujoco.mj_step, mujoco.mj_resetData, mujoco.mj_resetDataKeyframe = original["mj_step"], original["mj_reset"], original["mj_keyframe"]
            G1LocomotionController.reset, StopSkill.run = original["controller_reset"], original["stop_run"]
            LiveMissionSession.run_node, LiveMissionSession.run_failure_halt = original["node"], original["halt"]


def supervise(command: list[str], run_dir: Path, timeout_s: float) -> None:
    """External kill boundary also covers a blocked policy call."""
    with (run_dir / "worker.log").open("x", encoding="utf8") as log:
        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = child.wait(timeout=max(0.001, timeout_s))
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=10)
            write_new(run_dir / "supervisor_timeout.json", {"status": "PARTIAL_STOPPED", "reason": "HARD_WALL_WATCHDOG",
                                                             "inflight_native_step_count": "UNKNOWN", "no_retry": True})
            raise BudgetFailure("HARD_WALL_WATCHDOG")
    if code:
        raise IntegrityFailure("CELL_WORKER_EXIT:" + str(code))


def acquire(*, authorize_physics: bool, readiness_sha256: str, output: Path) -> dict:
    if not authorize_physics:
        raise PermissionError("Separate explicit --authorize-physics required")
    spec, _, _ = preflight(readiness_sha256)
    output = Path(output)
    output.mkdir()  # refuse a second campaign or overwrite, even if partial
    started = time.perf_counter()
    prior_steps, results = 0, []
    for index, cell in enumerate(spec["cells_in_order"]):
        run_dir = output / cell["id"]
        try:
            run_dir.mkdir()
            remaining = spec["budget"]["maximum_wall_s_total"] - (time.perf_counter() - started)
            if remaining <= 0:
                raise BudgetFailure("CAMPAIGN_WALL_BUDGET_EXHAUSTED")
            command = [sys.executable, str(HERE / "acquire.py"), "worker", "--authorize-physics",
                       "--readiness-sha256", readiness_sha256, "--output", str(output.resolve()),
                       "--cell-index", str(index), "--prior-native-steps", str(prior_steps)]
            supervise(command, run_dir, min(cell["max_wall_s"], remaining))
            result = json.loads((run_dir / "outcome.json").read_text(encoding="utf8"))
            witness = json.loads((run_dir / "witness.json").read_text(encoding="utf8"))
            observed = int(witness["native_steps"])
            rows = sum(1 for _ in (run_dir / "native_incremental.jsonl").open(encoding="utf8"))
            if observed != rows or observed > cell["max_native_steps"] or prior_steps + observed > spec["budget"]["maximum_native_steps_total"]:
                raise IntegrityFailure("NATIVE_JOURNAL_OR_BUDGET_MISMATCH")
            prior_steps += observed
            results.append(result)
            if result["status"] == "TECHNICAL_PARTIAL":
                raise RuntimeError("CELL_TECHNICAL_PARTIAL_NO_RETRY")
            if result["status"] == "PARTIAL_STOPPED":
                raise IntegrityFailure("CELL_INTEGRITY_PARTIAL_STOPPED")
        except BaseException as exc:
            write_new(output / "campaign_receipt.json", {"status": "PARTIAL_STOPPED", "reason": type(exc).__name__ + ": " + str(exc),
                                                       "completed_cells": results, "failed_cell": cell["id"],
                                                       "frozen_cells": [item["id"] for item in spec["cells_in_order"]],
                                                       "no_retry": True})
            raise
    receipt = {"status": "ACQUISITION_COMPLETE_NOT_SCIENTIFIC_VERDICT", "cells": results,
               "native_steps": prior_steps, "protocol_sha256": sha256(HERE / "protocol.json"),
               "readiness_sha256": readiness_sha256}
    write_new(output / "campaign_receipt.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "acquire", "worker"))
    parser.add_argument("--authorize-physics", action="store_true")
    parser.add_argument("--readiness-sha256")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cell-index", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--prior-native-steps", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.command == "preflight":
        spec, _, receipt = preflight(args.readiness_sha256)
        print(json.dumps({"status": "TARGET_PREFLIGHT_PASS_NO_PHYSICS", "cells": len(spec["cells_in_order"]),
                          "readiness_sha256": sha256(READINESS), "frozen_files": len(receipt["sha256"]),
                          "target_import_witness": target_import_witness()}))
    elif args.command == "acquire":
        if args.output is None:
            raise ValueError("Unique --output directory required")
        print(json.dumps(acquire(authorize_physics=args.authorize_physics,
                                 readiness_sha256=args.readiness_sha256, output=args.output)))
    else:
        if not args.authorize_physics or args.output is None or args.cell_index is None:
            raise PermissionError("Internal worker requires explicit acquisition authorization")
        spec, m24, _ = preflight(args.readiness_sha256)
        if not 0 <= args.cell_index < len(spec["cells_in_order"]):
            raise IntegrityFailure("CELL_INDEX_OUTSIDE_FROZEN_RUN_ORDER")
        cell = spec["cells_in_order"][args.cell_index]
        run_dir = args.output / cell["id"]
        if not run_dir.is_dir() or sorted(item.name for item in run_dir.iterdir()) != ["worker.log"]:
            raise IntegrityFailure("WORKER_DIRECTORY_NOT_PRISTINE")
        if (args.output / "campaign_receipt.json").exists():
            raise IntegrityFailure("CAMPAIGN_ALREADY_CLOSED")
        preceding = spec["cells_in_order"][:args.cell_index]
        observed_prior = 0
        for previous in preceding:
            previous_dir = args.output / previous["id"]
            if not (previous_dir / "outcome.json").is_file() or not (previous_dir / "witness.json").is_file():
                raise IntegrityFailure("PREVIOUS_FROZEN_CELL_NOT_COMPLETE")
            previous_outcome = json.loads((previous_dir / "outcome.json").read_text(encoding="utf8"))
            previous_witness = json.loads((previous_dir / "witness.json").read_text(encoding="utf8"))
            if previous_outcome.get("status") == "PARTIAL_STOPPED":
                raise IntegrityFailure("PREVIOUS_CELL_STOPPED")
            observed_prior += int(previous_witness["native_steps"])
        if observed_prior != args.prior_native_steps:
            raise IntegrityFailure("PRIOR_NATIVE_STEP_BUDGET_MISMATCH")
        if any((args.output / future["id"]).exists() for future in spec["cells_in_order"][args.cell_index + 1:]):
            raise IntegrityFailure("FUTURE_CELL_DIRECTORY_ALREADY_EXISTS")
        try:
            outcome = run_cell(spec, m24, cell, run_dir, production_backend,
                               prior_native_steps=args.prior_native_steps)
        finally:
            if (run_dir / "native_incremental.jsonl").exists() and not (run_dir / "witness.json").exists():
                rows = sum(1 for _ in (run_dir / "native_incremental.jsonl").open(encoding="utf8"))
                write_new(run_dir / "witness.json", {"native_steps": rows,
                                                     "native_journal_rows": rows,
                                                     "inflight_native_step_count": "UNKNOWN_IF_INTERRUPTED"})
        print(json.dumps(outcome))


if __name__ == "__main__":
    main()
