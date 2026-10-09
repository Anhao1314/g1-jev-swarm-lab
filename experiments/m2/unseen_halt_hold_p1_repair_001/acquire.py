"""Experiment-only M2.6A acquisition adapter. Import and preflight do no physics.

The six frozen conditions are executed once each. A qualifying terminal
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
import traceback
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
READINESS = HERE / "readiness_manifest.json"
M24 = ROOT / "experiments/m2/cross_state_reliability_001/protocol.json"
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


class ExperimentTechnicalError(RuntimeError):
    """A retained original control/adapter error forbids further dispatch."""


def exception_observer(original, operation, witness, emit, raw_evidence):
    """Retain the original exception before the unchanged Router can erase type.

    No arguments, results, exception identity or normal-path control are changed.
    Only a newly completed native step with measured nonfinite qpos/qvel and the
    simulation-state exception is a physical negative; InvalidControlError and
    controller output failures are always technical, even if control is NaN.
    """
    def call(*args, **kwargs):
        before = witness["native_steps"]
        try:
            return original(*args, **kwargs)
        except (IntegrityFailure, BudgetFailure):
            raise
        except BaseException as exc:
            try:
                raw, raw_error = raw_evidence(), None
            except BaseException as capture_exc:
                raw, raw_error = None, type(capture_exc).__name__ + ": " + str(capture_exc)
            def finite_tree(values):
                if isinstance(values, (list, tuple)):
                    return all(finite_tree(value) for value in values)
                return isinstance(values, (int, float)) and math.isfinite(values)
            qualified = type(exc).__module__ + "." + type(exc).__qualname__
            physical = (operation == "simulation.step"
                and qualified == "g1swarm.simulation.errors.SimulationStateError"
                and witness["native_steps"] > before and isinstance(raw, dict)
                and all(key in raw for key in ("qpos", "qvel"))
                and not all(finite_tree(raw[key]) for key in ("qpos", "qvel")))
            causes, cause, seen = [], exc.__cause__ or exc.__context__, {id(exc)}
            while cause is not None and id(cause) not in seen:
                seen.add(id(cause))
                causes.append({"qualified_type": type(cause).__module__ + "." + type(cause).__qualname__, "message": str(cause)})
                cause = cause.__cause__ or cause.__context__
            record = {"operation": operation, "qualified_type": qualified, "message": str(exc),
                "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                "cause_chain": causes, "phase": witness.get("phase"), "stage": witness.get("stage"),
                "native_steps_before_call": before, "native_steps": witness["native_steps"],
                "sequence_next": before + 1,
                "classification": "OBSERVED_NATIVE_PHYSICAL_NONFINITE" if physical else "TECHNICAL_CONTROL_OR_ADAPTER_ERROR",
                "raw_evidence": raw, "raw_evidence_error": raw_error}
            witness.setdefault("exception_records", []).append(record)
            if not physical:
                witness.setdefault("technical_failures", []).append(record)
            emit(record)
            raise
    return call


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


DESIGN = ROOT / "experiments/m2/unseen_halt_hold_design_001/protocol.json"


def preflight(readiness_sha256: str) -> tuple[dict, dict, dict]:
    """Delegated immutable target gate; no live module/resource imports."""
    if not readiness_sha256 or not READINESS.is_file() or sha256(READINESS) != readiness_sha256:
        raise IntegrityFailure("EXACT_READINESS_SHA256_REQUIRED")
    target_import_witness()
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from readiness import check_target
    receipt = check_target(expected_sha=readiness_sha256)
    if receipt.get("status") not in {"READY_FOR_OWNER_ACQUISITION_AUTHORIZATION", "TARGET_PREFLIGHT_PASS_NO_PHYSICS"}:
        raise IntegrityFailure("TARGET_PREFLIGHT_NOT_READY")
    spec = json.loads(DESIGN.read_text(encoding="utf8"))
    m24 = json.loads(M24.read_text(encoding="utf8"))
    if spec["physics_authorized"] is not False or len(spec["cells_in_order"]) != 6:
        raise IntegrityFailure("FROZEN_DESIGN_CHANGED")
    return spec, m24, receipt


def fixed_parent(m24: dict, cell: dict) -> dict:
    return deepcopy(cell["mission"])


def require_execution_head(expected: str) -> None:
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not expected or len(expected) != 40 or actual != expected:
        raise IntegrityFailure("OWNER_EXECUTION_HEAD_MISMATCH")


def warning_counters(data) -> list[dict]:
    if not hasattr(data, "warning"):
        raise MissingEvidence("NATIVE_WARNING_COUNTERS_MISSING")
    return [{"index": i, "number": int(w.number), "lastinfo": int(w.lastinfo)}
            for i, w in enumerate(data.warning)]


def observe_native(data, controller, *, sequence: int, phase: str) -> dict:
    """Read-only seam shared by real hook and fake equivalence checks."""
    row = {"sequence": sequence, "phase": phase, "time_s": float(data.time),
           "qpos": data.qpos.tolist(), "qvel": data.qvel.tolist(), "ctrl": data.ctrl.tolist(),
           "xfrc_applied": data.xfrc_applied.tolist(), "warnings": warning_counters(data),
           "controller": {"_action": controller._action.tolist(), "_target": controller._target.tolist(),
                          "_counter": int(controller._counter)} if controller is not None else None}
    def finite(v):
        if isinstance(v, list):
            return all(finite(x) for x in v)
        return isinstance(v, (int, float)) and math.isfinite(v)
    row["raw_finite"] = all(finite(row[k]) for k in ("qpos","qvel","ctrl","xfrc_applied")) and (controller is None or (finite(row["controller"]["_action"]) and finite(row["controller"]["_target"])))
    return row


def call_with_cleanup(operation, cleanup):
    """Always release experiment force after a normal or abnormal Walk exit."""
    try:
        return operation()
    finally:
        cleanup()


def observed_call(original, emit):
    """Record command without copying/mutating arguments passed to controller."""
    def call(*args, **kwargs):
        command = kwargs.get("command")
        if command is None:
            raise MissingEvidence("CONTROLLER_COMMAND_ARGUMENT_MISSING")
        emit(command.tolist())
        return original(*args, **kwargs)
    return call


def force_at_pre_step(push: dict | None, pre_index: int) -> list[float]:
    if not push:
        return [0.0, 0.0, 0.0]
    start = push["native_pre_step_start_index"]
    if start <= pre_index < start + push["native_intervals_if_walk_reaches_window_end"]:
        return [float(push["force_n"]) * float(v) for v in push["direction_world"]]
    return [0.0, 0.0, 0.0]


def entry_classification(parent: dict, cell: dict, terminal: dict | None, *, explicit_raw_unsafe: bool = False) -> tuple[str | None, str]:
    """Separate trigger, Halt and Hold, without inventing unsupported routing."""
    halt = parent.get("physical_halt")
    if cell["id"] == "normal_stop_control":
        nodes = parent.get("nodes") or []
        if not (parent.get("mission_success") is True and parent.get("physical_success") is True
                and parent.get("completed_nodes") == 3 and not halt and nodes
                and nodes[-1].get("skill") == "stop"
                and nodes[-1].get("metrics", {}).get("skill_status") == "SUCCESS"):
            return None, "CONTROL_FAILED_NO_HOLD"
    elif parent.get("failure_type") != "TASK_ENVELOPE_VIOLATION" or parent.get("failed_node") != "s1":
        if halt:
            raise IntegrityFailure("HALT_REQUESTED_OUTSIDE_FROZEN_STRICT_TRIGGER")
        return None, ("NO_HALT_TRIGGER" if parent.get("mission_success") is True
                      else "PARENT_SKILL_OR_PHYSICAL_FAILURE_NO_HALT_NO_HOLD")
    else:
        if not halt:
            raise IntegrityFailure("INTEGRITY_FAILURE_TRIGGER_ROUTING")
        if halt.get("status") != "HALT_SUCCEEDED":
            if halt.get("failure_stage") == "stop_skill_or_observer" and not explicit_raw_unsafe:
                return None, "TECHNICAL_PARTIAL"
            return None, "HALT_FAILED_NO_HOLD"
        if halt.get("skill_status") != "SUCCESS" or not halt.get("checks") or not all(halt["checks"].values()):
            raise IntegrityFailure("HALT_SUCCESS_WITHOUT_ALL_ACCEPTANCE_CHECKS")
    if not terminal or terminal.get("stop_status") != "SUCCESS":
        raise MissingEvidence("TERMINAL_STOP_EVIDENCE_MISSING")
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
    if cell["id"] != "normal_stop_control":
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
    hold = spec["layer3_hold"]["contract"]
    expected = hold["native_steps"]
    rolling = deque(seed, maxlen=hold["rolling_window_steps"])
    if len(rolling) != rolling.maxlen:
        raise MissingEvidence("HOLD_WINDOW_SEED_INCOMPLETE")
    means, path, observed_failures = [], 0.0, []
    previous = terminal["snapshot"]["qpos"][:2]
    for row in rows:
        speed = float(row["speed_mps"])
        rolling.append(speed)
        means.append(sum(rolling) / len(rolling))
        xy = row["position_m"][:2]
        path += math.dist(previous, xy)
        previous = xy
        acceptance = hold["acceptance"]
        violations = {
            "rolling_mean": not math.isfinite(means[-1]) or means[-1] > acceptance["all_1000_rolling_means_at_most_mps"],
            "xy_path_length": not math.isfinite(path) or path > acceptance["hold_xy_path_length_at_most_m"],
            "finite_throughout": not row["finite"] or not row["raw_finite"],
            "standing_throughout": not row["standing"], "no_fall_throughout": row["fallen"],
        }
        for criterion, failed in violations.items():
            if failed and not any(item["criterion"] == criterion for item in observed_failures):
                observed_failures.append({"criterion": criterion, "step": len(means),
                    "value": means[-1] if criterion == "rolling_mean" else path if criterion == "xy_path_length" else False})
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
        "status": ("HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE" if all(checks.values()) else
                   "HOLD_FAILED" if len(rows) == expected or observed_failures else "TECHNICAL_PARTIAL"),
        "checks": checks,
        "measured_steps": len(rows),
        "xy_path_length_m": path,
        "last_speed_mps": rows[-1]["speed_mps"] if rows else None,
        "rolling_mean_speed_mps": means,
        "one_second_disjoint_means_mps": [sum(row["speed_mps"] for row in rows[start:start + 500]) / 500 for start in (0, 500)] if len(rows) == expected else None,
        "maximum_instantaneous_speed_mps": max((row["speed_mps"] for row in rows), default=None),
        "completion_status": "COMPLETE" if len(rows) == expected else "TECHNICAL_PARTIAL",
        "observed_physical_failures": observed_failures,
        "observed_hold_failure": bool(observed_failures),
    }


def run_cell(spec: dict, m24: dict, cell: dict, run_dir: Path, backend, *, prior_native_steps: int = 0) -> dict:
    """Common production/fake stage order; no real imports in this function."""
    result = {"cell_id": cell["id"], "status": "PARTIAL_STOPPED", "coverage": "NOT_EVALUATED"}
    with backend(spec, m24, cell, run_dir, prior_native_steps) as rt:
        session, executor = rt["session"], rt["executor"]
        parent = executor.run(fixed_parent(m24, cell), existing_session=session, phase="m26a_parent")
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
        if rt["witness"].get("technical_failures"):
            result.update(status="TECHNICAL_PARTIAL", completion_status="TECHNICAL_PARTIAL",
                coverage="PARTIAL_TECHNICAL", reason="RETAINED_CONTROL_OR_ADAPTER_EXCEPTION",
                technical_failures=deepcopy(rt["witness"]["technical_failures"]), halt="TECHNICAL_UNASSESSED")
            rt["witness"]["outcome_status"] = result["status"]
            write_new(run_dir / "outcome.json", result)
            return result
        try:
            prefix = {"status": "DEFERRED_TO_INDEPENDENT_NATIVE_PREFIX_GATE_BEFORE_NEXT_CELL"}
        except MissingEvidence as exc:
            result.update(status="INCONCLUSIVE_MISSING_EVIDENCE", coverage="NO_HOLD", reason=str(exc))
            rt["witness"]["outcome_status"] = result["status"]
            write_new(run_dir / "outcome.json", result)
            return result
        write_new(run_dir / "historical_parent_prefix.json", prefix)
        raw_last = rt["raw_last"]()
        eligibility, reason = entry_classification(parent_dict, cell, terminal,
            explicit_raw_unsafe=raw_last is not None and raw_last.get("raw_finite") is False)
        if eligibility is None:
            result.update(status=reason, coverage="PARTIAL_TECHNICAL" if reason == "TECHNICAL_PARTIAL" else "NO_HOLD")
            if reason == "TECHNICAL_PARTIAL":
                result["technical_failure"] = deepcopy(parent_dict.get("physical_halt"))
            rt["witness"]["outcome_status"] = result["status"]
            write_new(run_dir / "outcome.json", result)
            return result
        assert terminal is not None
        try:
            seed = verify_stop_seed(terminal, parent_dict, cell, window=spec["layer3_hold"]["contract"]["rolling_window_steps"])
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
        if rt["witness"]["native_steps"] + spec["layer3_hold"]["contract"]["native_steps"] > cell["max_native_steps"]:
            raise BudgetFailure("CELL_NATIVE_STEPS_CANNOT_FIT_HOLD")
        if prior_native_steps + rt["witness"]["native_steps"] + spec["layer3_hold"]["contract"]["native_steps"] > spec["budget"]["maximum_native_steps_total"]:
            raise BudgetFailure("CAMPAIGN_NATIVE_STEPS_CANNOT_FIT_HOLD")
        write_new(run_dir / "hold_entry.json", {"terminal": terminal, "pre_first_step": before, "seed_speeds_mps": seed})
        rt["begin_hold"]()
        rows = []
        previous_time = float(before["time_s"])
        for index in range(spec["layer3_hold"]["contract"]["native_steps"]):
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
                if rt["witness"].get("technical_failures"):
                    result.update(status="TECHNICAL_PARTIAL", completion_status="TECHNICAL_PARTIAL",
                        coverage="PARTIAL_TECHNICAL", reason="RETAINED_CONTROL_OR_ADAPTER_EXCEPTION",
                        technical_failures=deepcopy(rt["witness"]["technical_failures"]), observed_hold_steps=len(rows))
                    break
                raw = rt["raw_last"]()
                if raw is not None and raw.get("raw_finite") is False:
                    result.update(status="HOLD_FAILED", coverage="PARTIAL_PHYSICAL_NONFINITE", reason="NONFINITE_PHYSICAL_STATE", observed_hold_steps=len(rows))
                    break
                result.update(status="TECHNICAL_PARTIAL", coverage="PARTIAL_TECHNICAL", reason=type(exc).__name__ + ": " + str(exc), observed_hold_steps=len(rows))
                break
            row = rt["state_row"](state, index + 1)
            if not math.isclose(float(row["time_s"]) - previous_time,
                                spec["fixed"]["native_timestep_s"], rel_tol=0, abs_tol=1e-8):
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
        if len(rows) == spec["layer3_hold"]["contract"]["native_steps"]:
            if after["controller_counter"] - before["controller_counter"] != len(rows):
                raise IntegrityFailure("CONTROLLER_COUNTER_NOT_ONE_PER_HOLD_STEP")
            if rt["witness"]["native_steps"] - before["native_steps"] != len(rows):
                raise IntegrityFailure("HOLD_NATIVE_STEP_COUNT_MISMATCH")
            if rt["witness"]["hold_command_calls"] != len(rows):
                raise IntegrityFailure("HOLD_ZERO_COMMAND_COUNT_MISMATCH")
            result.update(assess_hold(rows, seed, spec, terminal))
            result["coverage"] = "COMPLETE_HOLD"
        else:
            observed = assess_hold(rows, seed, spec, terminal)
            result.update(observed_physical_failures=observed["observed_physical_failures"],
                observed_hold_failure=observed["observed_hold_failure"],
                hold_physical_status="HOLD_FAILED" if observed["observed_hold_failure"] else "UNASSESSED_INCOMPLETE")
            result.setdefault("completion_status", "TECHNICAL_PARTIAL" if result["status"] == "TECHNICAL_PARTIAL" else "EARLY_PHYSICAL_TERMINATION")
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
    from g1swarm.skills import basic as skill_basic
    from g1swarm.skills.contract import SkillContext
    from scripts.run_oracle_missions import load_protocol, build_grounder

    runtime_protocol = load_protocol(spec["fixed"]["runtime_protocol"])
    robot = load_yaml(runtime_protocol["robot_config"])
    halt = json.loads((ROOT / m24["contracts"]["halt_contract"]).read_text(encoding="utf8"))
    witness = {"attempt": 1, "target_import_witness": import_witness,
               "native_steps": 0, "reset_calls": 0, "native_reset_calls": 0,
               "keyframe_reset_calls": 0, "controller_reset_calls": 0,
               "node_dispatches": 0, "executor_dispatches": 0,
               "phase": "initialization", "qualified_stop": False,
               "stage": "initialization", "technical_failures": [], "exception_records": [],
               "integrity_failure": None, "budget_failure": None,
               "parent_native_steps": None, "hold_native_steps": 0,
               "hold_command_calls": 0, "outcome_status": "PARTIAL_STOPPED",
               "protocol_sha256": sha256(DESIGN),
               "readiness_sha256": sha256(READINESS),
               "source_manifest_sha256": sha256(HERE / "source_manifest.json"),
               "policy_reset_memory_witness": "indirect via pinned controller.reset call path; no direct hidden-memory bytes"}
    terminal = {}
    first_walk = {"active": False, "started": False, "pre_index": 0}
    native_rows: list[dict] = []
    state_rows: list[dict] = []
    started = time.perf_counter()
    session = None
    original = {
        "sim_step": G1Simulation.step, "sim_reset": G1Simulation.reset,
        "mj_step": mujoco.mj_step, "mj_reset": mujoco.mj_resetData,
        "mj_keyframe": mujoco.mj_resetDataKeyframe,
        "controller_reset": G1LocomotionController.reset, "compute_torques": G1LocomotionController.compute_torques,
        "policy_torques": _policy_torques,
        "stop_run": StopSkill.run, "node": LiveMissionSession.run_node,
        "halt": LiveMissionSession.run_failure_halt,
    }
    journal = (run_dir / "native_incremental.jsonl").open("x", encoding="utf8", newline="\n", buffering=1)
    hold_journal = (run_dir / "hold_incremental.jsonl").open("x", encoding="utf8", newline="\n", buffering=1)
    force_journal = (run_dir / "force_incremental.jsonl").open("x", encoding="utf8", newline="\n", buffering=1)
    event_journal = (run_dir / "lifecycle_events.jsonl").open("x", encoding="utf8", newline="\n", buffering=1)
    command_journal = (run_dir / "command_incremental.jsonl").open("x", encoding="utf8", newline="\n", buffering=1)
    exception_journal = (run_dir / "exceptions_incremental.jsonl").open("x", encoding="utf8", newline="\n", buffering=1)

    def emit_exception(record):
        exception_journal.write(json.dumps(json_safe(record), allow_nan=False, sort_keys=True) + "\n")
        exception_journal.flush()

    def exception_raw():
        value = raw_snapshot()
        value["last_completed_native_row"] = deepcopy(native_rows[-1]) if native_rows else None
        return value

    def event(kind, **fields):
        event_journal.write(json.dumps(json_safe({"event": kind, "snapshot": raw_snapshot(), **fields}), allow_nan=False, sort_keys=True) + "\n")

    def guard(*, stepping=False):
        if witness["technical_failures"]:
            raise ExperimentTechnicalError("RETAINED_TECHNICAL_EXCEPTION_FORBIDS_FURTHER_EXECUTION")
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
            "time_s": float(data.time), "qpos": data.qpos.tolist(), "qvel": data.qvel.tolist(), "warnings": warning_counters(data),
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
        data = args[1]
        force = force_at_pre_step(cell.get("push"), first_walk["pre_index"]) if first_walk["active"] else [0.0, 0.0, 0.0]
        if session is not None:
            if first_walk["active"]:
                session.simulation.clear_applied_forces()
                if any(force):
                    session.simulation.apply_base_force(np.asarray(force, dtype=np.float64))
            elif not np.all(data.xfrc_applied == 0):
                raise IntegrityFailure("NONZERO_FORCE_OUTSIDE_FIRST_WALK")
        force_journal.write(json.dumps(json_safe({"sequence_next": witness["native_steps"] + 1,
            "pre_time_s": float(data.time), "first_walk_pre_index": first_walk["pre_index"] if first_walk["active"] else None,
            "force_vector": force, "body_index": session.simulation._base_body_id if session is not None else None, "body_name": witness.get("force_body_name"), "xfrc_before": data.xfrc_applied.tolist()}), allow_nan=False, sort_keys=True) + "\n")
        result = original["mj_step"](*args, **kwargs)
        if first_walk["active"]:
            first_walk["pre_index"] += 1
        witness["native_steps"] += 1
        data = args[1]
        raw = observe_native(data, session.controller if session is not None else None,
                             sequence=witness["native_steps"], phase=witness["phase"])
        native_rows.append(raw)
        journal.write(json.dumps(json_safe(raw), allow_nan=False, sort_keys=True) + "\n")
        return result

    def sim_step(obj, control=None):
        state = exception_observer(original["sim_step"], "simulation.step", witness, emit_exception, exception_raw)(obj, control)
        state_rows.append({"sequence": witness["native_steps"], "speed_mps": state.speed(),
                           "phase": witness["phase"]})
        if len(state_rows) != witness["native_steps"]:
            witness["integrity_failure"] = "SIM_NATIVE_STEP_COUNT_MISMATCH"
            raise IntegrityFailure(witness["integrity_failure"])
        return state

    def stop_run(obj, context):
        witness["stage"] = "failure_halt_stop" if witness.get("halt_requested") else "normal_stop"
        start = len(state_rows)
        event("stop_start")
        result = original["stop_run"](obj, context)
        event("stop_return", status=result.status.value)
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
        if witness["technical_failures"]:
            raise ExperimentTechnicalError("TECHNICAL_EXCEPTION_FORBIDS_NEXT_TASK_NODE")
        witness["stage"] = "parent_node:" + target.skill.value
        if witness["phase"] == "hold" or witness["qualified_stop"]:
            witness["integrity_failure"] = "TASK_NODE_DISPATCH_AFTER_STOP_CROSSING"
            raise IntegrityFailure(witness["integrity_failure"])
        witness["node_dispatches"] += 1
        event("node_start", node_id=target.node_id, skill=target.skill.value)
        is_first = target.skill.value == "walk_forward" and not first_walk["started"]
        if is_first:
            first_walk.update(active=True, started=True)
            event("first_walk_start")
        def cleanup_walk():
            if is_first:
                first_walk["active"] = False
                obj.simulation.clear_applied_forces()
                event("force_clear_walk_exit", emitted_intervals=first_walk["pre_index"])
        result = call_with_cleanup(lambda: original["node"](obj, target, mode), cleanup_walk)
        event("node_end", node_id=target.node_id, skill=target.skill.value,
              skill_status=result.metrics.get("skill_status"), execution_status=result.status)
        if is_first:
            event("first_walk_end", skill_status=result.status if hasattr(result, "status") else None)
        if target.skill.value == "stop" and terminal:
            terminal["snapshot"] = raw_snapshot()
        return result

    def halt_call(obj, contract):
        if witness["technical_failures"]:
            raise ExperimentTechnicalError("TECHNICAL_EXCEPTION_FORBIDS_HALT_DISPATCH")
        witness["halt_requested"] = True
        witness["stage"] = "failure_halt"
        if witness["phase"] == "hold":
            witness["integrity_failure"] = "SECOND_HALT_DISPATCH_DURING_HOLD"
            raise IntegrityFailure(witness["integrity_failure"])
        if not np.all(obj.simulation._data.xfrc_applied == 0):
            witness["integrity_failure"] = "NONZERO_EXTERNAL_FORCE_BEFORE_HALT"
            raise IntegrityFailure(witness["integrity_failure"])
        event("halt_request")
        result = original["halt"](obj, contract)
        if terminal:
            terminal["snapshot"] = raw_snapshot()
        return result

    G1Simulation.step, G1Simulation.reset = sim_step, sim_reset
    mujoco.mj_step, mujoco.mj_resetData, mujoco.mj_resetDataKeyframe = mj_step, mj_reset, mj_keyframe
    def emit_command(command):
        command_journal.write(json.dumps({"sequence_next": witness["native_steps"] + 1,
            "phase": witness["phase"], "command_xyz_mps_radps": command}, allow_nan=False, sort_keys=True) + "\n")
    G1LocomotionController.compute_torques = exception_observer(
        observed_call(original["compute_torques"], emit_command), "controller.compute_torques",
        witness, emit_exception, exception_raw)
    skill_basic._policy_torques = exception_observer(original["policy_torques"],
        "control._policy_torques", witness, emit_exception, exception_raw)
    G1LocomotionController.reset, StopSkill.run = controller_reset, stop_run
    LiveMissionSession.run_node, LiveMissionSession.run_failure_halt = node, halt_call
    try:
        session = LiveMissionSession(robot_config=robot, protocol=runtime_protocol, seed=spec["fixed"]["seed"])
        if witness["reset_calls"] != 2 or witness["native_reset_calls"] != 2 or witness["keyframe_reset_calls"] != 0:
            raise IntegrityFailure("INITIALIZATION_RESET_COUNTS_MISMATCH")
        body_name = mujoco.mj_id2name(session.simulation._model, mujoco.mjtObj.mjOBJ_BODY, session.simulation._base_body_id)
        if body_name != "pelvis":
            raise IntegrityFailure("FORCE_BODY_MAPPING_NOT_PELVIS")
        witness["force_body_name"] = body_name
        witness["force_body_index"] = int(session.simulation._base_body_id)
        witness["phase"] = "parent"

        def forbidden_factory(seed):
            witness["integrity_failure"] = "NEW_SESSION_FACTORY_CALLED"
            raise IntegrityFailure(witness["integrity_failure"])

        executor = MissionExecutor(
            validator=MissionValidator(), grounder=build_grounder(runtime_protocol),
            session_factory=forbidden_factory, protocol=runtime_protocol,
            recorder_root=str(run_dir / "ledger"), seed=spec["fixed"]["seed"],
            provenance={"study": spec["experiment_id"], "cell": cell["id"],
                        "protocol_sha256": sha256(DESIGN)},
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
            witness["stage"] = "post_halt_hold"

        def step_zero():
            if witness["phase"] != "hold":
                raise IntegrityFailure("HOLD_NOT_STARTED")
            context = SkillContext(simulation=session.simulation, controller=session.controller,
                                   robot_config=session.robot_config, seed=session.seed)
            command = np.zeros(3, dtype=np.float64)
            if not np.array_equal(command, np.asarray(spec["layer3_hold"]["contract"]["command_xyz_mps_radps"])):
                raise IntegrityFailure("HOLD_COMMAND_NOT_EXACT_ZERO")
            witness["hold_command_calls"] += 1
            torques = skill_basic._policy_torques(context, command)
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
               "verify_historical_parent": lambda: None,
               "journal_hold_row": lambda row: hold_journal.write(json.dumps(json_safe(row), allow_nan=False, sort_keys=True) + "\n")}
    finally:
        try:
            try:
                if session is not None:
                    session.simulation.clear_applied_forces()
                    event("force_clear_backend_exit")
                journal.close()
                hold_journal.close()
                force_journal.close()
                event_journal.close()
                command_journal.close()
                exception_journal.close()
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
                write_new(run_dir / "terminal_stop.json", terminal)
                write_new(run_dir / "witness.json", witness)
            finally:
                if session is not None:
                    session.close()
        finally:
            G1Simulation.step, G1Simulation.reset = original["sim_step"], original["sim_reset"]
            mujoco.mj_step, mujoco.mj_resetData, mujoco.mj_resetDataKeyframe = original["mj_step"], original["mj_reset"], original["mj_keyframe"]
            G1LocomotionController.reset, StopSkill.run = original["controller_reset"], original["stop_run"]
            G1LocomotionController.compute_torques = original["compute_torques"]
            skill_basic._policy_torques = original["policy_torques"]
            LiveMissionSession.run_node, LiveMissionSession.run_failure_halt = original["node"], original["halt"]


def wall_fields(started: float, *, ended=None) -> dict:
    ended = time.perf_counter() if ended is None else ended
    return {"wall_started_monotonic_s": started, "wall_ended_monotonic_s": ended,
            "wall_elapsed_s": ended - started}


def supervise(command: list[str], run_dir: Path, timeout_s: float) -> None:
    """External child watchdog; receipt persists on success, fault and hardkill."""
    started, code, status = time.perf_counter(), None, "SUPERVISOR_TECHNICAL_PARTIAL"
    try:
        with (run_dir / "worker.log").open("x", encoding="utf8") as log:
            child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = child.wait(timeout=max(0.001, timeout_s))
            except subprocess.TimeoutExpired:
                status = "HARD_WALL_WATCHDOG"
                child.kill()
                code = child.wait(timeout=10)
                write_new(run_dir / "supervisor_timeout.json", {"status": "PARTIAL_STOPPED", "reason": status,
                    "inflight_native_step_count": "UNKNOWN", "no_retry": True})
                raise BudgetFailure(status)
        status = "WORKER_COMPLETED" if code == 0 else "WORKER_EXIT_FAILURE"
        if code:
            raise IntegrityFailure("CELL_WORKER_EXIT:" + str(code))
    finally:
        write_new(run_dir / "supervisor_receipt.json", {"status": status, "worker_exit_code": code,
            "allocated_wall_bound_s": timeout_s, "no_retry": True, **wall_fields(started)})


def cell_wall_guard(started: float, cell: dict, *, clock=None) -> None:
    clock = time.perf_counter if clock is None else clock
    if clock() - started >= cell["max_wall_s"]:
        raise BudgetFailure("CELL_WALL_BUDGET_EXHAUSTED_INCLUDING_PREFIX_AUDIT")


def campaign_wall_guard(started: float, spec: dict, *, clock=None) -> None:
    clock = time.perf_counter if clock is None else clock
    if clock() - started >= spec["budget"]["maximum_wall_s_total"]:
        raise BudgetFailure("CAMPAIGN_WALL_BUDGET_EXHAUSTED")


def acquire(*, authorize_physics: bool, readiness_sha256: str, output: Path, execution_head: str) -> dict:
    if not authorize_physics:
        raise PermissionError("Separate explicit --authorize-physics required")
    spec, _, _ = preflight(readiness_sha256)
    require_execution_head(execution_head)
    output = Path(output)
    output.mkdir()  # refuse a second campaign or overwrite, even if partial
    started = time.perf_counter()
    bindings = {"execution_head": execution_head, "readiness_sha256": readiness_sha256,
                "source_manifest_sha256": sha256(HERE / "source_manifest.json"), "protocol_sha256": sha256(DESIGN),
                "frozen_budget": deepcopy(spec["budget"])}
    prior_steps, results = 0, []
    for index, cell in enumerate(spec["cells_in_order"]):
        run_dir = output / cell["id"]
        cell_started = time.perf_counter()
        try:
            run_dir.mkdir()
            remaining = spec["budget"]["maximum_wall_s_total"] - (time.perf_counter() - started)
            if remaining <= 0:
                raise BudgetFailure("CAMPAIGN_WALL_BUDGET_EXHAUSTED")
            command = [sys.executable, str(HERE / "acquire.py"), "worker", "--authorize-physics",
                       "--readiness-sha256", readiness_sha256, "--output", str(output.resolve()),
                       "--cell-index", str(index), "--prior-native-steps", str(prior_steps), "--execution-head", execution_head]
            supervise(command, run_dir, min(cell["max_wall_s"], remaining))
            campaign_wall_guard(started, spec)
            result = json.loads((run_dir / "outcome.json").read_text(encoding="utf8"))
            witness = json.loads((run_dir / "witness.json").read_text(encoding="utf8"))
            observed = int(witness["native_steps"])
            rows = sum(1 for _ in (run_dir / "native_incremental.jsonl").open(encoding="utf8"))
            if observed != rows or observed > cell["max_native_steps"] or prior_steps + observed > spec["budget"]["maximum_native_steps_total"]:
                raise IntegrityFailure("NATIVE_JOURNAL_OR_BUDGET_MISMATCH")
            prior_steps += observed
            results.append(result)
            if (result["status"] in {"TECHNICAL_PARTIAL", "INCONCLUSIVE_MISSING_EVIDENCE"}
                    or result.get("completion_status") == "TECHNICAL_PARTIAL"
                    or witness.get("technical_failures")):
                raise RuntimeError("CELL_TECHNICAL_PARTIAL_NO_RETRY")
            if result["status"] == "PARTIAL_STOPPED":
                raise IntegrityFailure("CELL_INTEGRITY_PARTIAL_STOPPED")
            campaign_wall_guard(started, spec)
            from audit import verify_acquisition_prefix
            verify_acquisition_prefix(output, cell["id"])
            campaign_wall_guard(started, spec)
            cell_wall_guard(cell_started, cell)
            write_new(run_dir / "cell_wall_receipt.json", {"status": "CELL_COMPLETE_WITHIN_FROZEN_BOUND",
                "allocated_wall_bound_s": cell["max_wall_s"], "includes_prefix_audit": True, **wall_fields(cell_started)})
        except BaseException as exc:
            if run_dir.is_dir() and not (run_dir / "cell_wall_receipt.json").exists():
                write_new(run_dir / "cell_wall_receipt.json", {"status": "CELL_PARTIAL_STOPPED",
                    "allocated_wall_bound_s": cell["max_wall_s"], "includes_prefix_audit": True, "reason": type(exc).__name__ + ": " + str(exc), **wall_fields(cell_started)})
            write_new(output / "campaign_receipt.json", {"status": "PARTIAL_STOPPED", "reason": type(exc).__name__ + ": " + str(exc),
                                                       "completed_cells": results, "failed_cell": cell["id"],
                                                       "frozen_cells": [item["id"] for item in spec["cells_in_order"]],
                                                       "no_retry": True, **bindings, **wall_fields(started)})
            raise
    if time.perf_counter() - started >= spec["budget"]["maximum_wall_s_total"]:
        write_new(output / "campaign_receipt.json", {"status": "PARTIAL_STOPPED", "reason": "CAMPAIGN_WALL_BUDGET_EXHAUSTED", "completed_cells": results, "no_retry": True, **bindings, **wall_fields(started)})
        raise BudgetFailure("CAMPAIGN_WALL_BUDGET_EXHAUSTED")
    receipt = {"status": "ACQUISITION_COMPLETE_NOT_SCIENTIFIC_VERDICT", "cells": results,
               "native_steps": prior_steps, **bindings, **wall_fields(started)}
    write_new(output / "campaign_receipt.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "acquire", "worker"))
    parser.add_argument("--authorize-physics", action="store_true")
    parser.add_argument("--readiness-sha256")
    parser.add_argument("--execution-head")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cell-index", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--prior-native-steps", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.command == "preflight":
        spec, _, receipt = preflight(args.readiness_sha256)
        print(json.dumps({"status": "TARGET_PREFLIGHT_PASS_NO_PHYSICS", "cells": len(spec["cells_in_order"]),
                          "readiness_sha256": sha256(READINESS), "frozen_files": len(receipt.get("sha256", {})),
                          "target_import_witness": target_import_witness()}))
    elif args.command == "acquire":
        if args.output is None:
            raise ValueError("Unique --output directory required")
        print(json.dumps(acquire(authorize_physics=args.authorize_physics,
                                 readiness_sha256=args.readiness_sha256, output=args.output, execution_head=args.execution_head)))
    else:
        if not args.authorize_physics or args.output is None or args.cell_index is None:
            raise PermissionError("Internal worker requires explicit acquisition authorization")
        spec, m24, _ = preflight(args.readiness_sha256)
        require_execution_head(args.execution_head)
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
            if (previous_outcome.get("status") in {"PARTIAL_STOPPED", "TECHNICAL_PARTIAL", "INCONCLUSIVE_MISSING_EVIDENCE"}
                    or previous_outcome.get("completion_status") == "TECHNICAL_PARTIAL"
                    or previous_witness.get("technical_failures")):
                raise IntegrityFailure("PREVIOUS_CELL_STOPPED")
            observed_prior += int(previous_witness["native_steps"])
        if observed_prior != args.prior_native_steps:
            raise IntegrityFailure("PRIOR_NATIVE_STEP_BUDGET_MISMATCH")
        if any((args.output / future["id"]).exists() for future in spec["cells_in_order"][args.cell_index + 1:]):
            raise IntegrityFailure("FUTURE_CELL_DIRECTORY_ALREADY_EXISTS")
        try:
            outcome = run_cell(spec, m24, cell, run_dir, production_backend,
                               prior_native_steps=args.prior_native_steps)
        except BaseException as exc:
            if not (run_dir / "outcome.json").exists():
                write_new(run_dir / "outcome.json", {"cell_id": cell["id"], "status": "PARTIAL_STOPPED" if isinstance(exc, (IntegrityFailure, BudgetFailure)) else "TECHNICAL_PARTIAL", "reason": type(exc).__name__ + ": " + str(exc)})
            raise
        finally:
            if (run_dir / "native_incremental.jsonl").exists() and not (run_dir / "witness.json").exists():
                rows = sum(1 for _ in (run_dir / "native_incremental.jsonl").open(encoding="utf8"))
                write_new(run_dir / "witness.json", {"native_steps": rows,
                                                     "native_journal_rows": rows,
                                                     "inflight_native_step_count": "UNKNOWN_IF_INTERRUPTED"})
        print(json.dumps(outcome))


if __name__ == "__main__":
    main()
