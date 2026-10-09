"""Recompute bounded old/repaired P1 numerical examples; no live resources.

All generated rows are synthetic fault witnesses, not physical experiment
outcomes. Historical code is imported read-only, never patched or dispatched.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "experiments/m2/unseen_halt_hold_readiness_001"
DESIGN = ROOT / "experiments/m2/unseen_halt_hold_design_001/protocol.json"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def contrast():
    old = module("contrast_old_raw", OLD / "audit.py")
    new = module("contrast_repaired_raw", HERE / "audit.py")
    prior_acquire = module("contrast_old_acquisition", OLD / "acquire.py")
    repaired_acquire = module("contrast_repaired_acquisition", HERE / "acquire.py")
    spec = json.loads(DESIGN.read_text(encoding="utf-8"))
    entry = {"time_s": 1., "qpos": [0., 0., .8, 1., 0., 0., 0.] + [0.] * 12,
             "controller_counter": 500}

    def raw(index, speed=.05, x=0.):
        return {"sequence": 500+index, "phase": "hold", "time_s": 1.+index*.002,
                "qpos": [x,0.,.8,1.,0.,0.,0.]+[0.]*12,
                "qvel": [speed,0.,0.,0.,0.,0.]+[0.]*12,
                "ctrl": [0.]*12, "xfrc_applied": [[0.]*6], "raw_finite": True,
                "controller": {"_counter": 500+index, "_action": [0.]*12, "_target": [0.]*12}}

    cases = {}
    for name, seed, rows in (
        ("observed_rolling_breach_then_interruption", [.1]*500, [raw(1,speed=1.)]),
        ("observed_path_breach_then_interruption", [.05]*500, [raw(1,x=.21)]),
        ("partial_instant_speed_without_universal_breach", [.05]*500, [raw(1,speed=.15)]),
        ("complete_valid_hold", [.05]*500, [raw(i,x=.05*.002*i) for i in range(1,1001)]),
    ):
        logs = [{"hold_step": i, "native_sequence": row["sequence"],
                 "command_xyz_mps_radps": [0.,0.,0.]} for i,row in enumerate(rows,1)]
        before = old.hold_score(entry, rows, logs, seed, spec)
        after = new.hold_score(entry, rows, logs, seed, spec)
        cases[name] = {"old_status": before["status"], "repaired_status": after["status"],
                       "repaired_completion_status": after["completion_status"],
                       "observed_physical_failures": after["observed_physical_failures"],
                       "first_rolling_mean": after["rolling_means"][0],
                       "xy_path_length_m": after["xy_path_length_m"], "rows": len(rows)}
    assert cases["observed_rolling_breach_then_interruption"]["old_status"] == "TECHNICAL_PARTIAL"
    assert cases["observed_rolling_breach_then_interruption"]["repaired_status"] == "HOLD_FAILED"
    assert cases["observed_path_breach_then_interruption"]["repaired_status"] == "HOLD_FAILED"
    assert cases["partial_instant_speed_without_universal_breach"]["repaired_status"] == "TECHNICAL_PARTIAL"
    assert cases["complete_valid_hold"]["old_status"] == cases["complete_valid_hold"]["repaired_status"]

    # Compile the frozen error definitions without importing simulator/control.
    error_file = ROOT / "src/g1swarm/simulation/errors.py"
    error_scope = {"__name__": "g1swarm.simulation.errors"}
    exec(compile(ast.parse(error_file.read_text()), str(error_file), "exec"), error_scope)
    InvalidControl = error_scope["InvalidControlError"]
    witness = {"native_steps": 23, "phase": "parent", "stage": "parent_node:walk_forward"}
    records = []
    def invalid_control():
        raise InvalidControl("control contains non-finite values")
    observed = repaired_acquire.exception_observer(invalid_control, "simulation.step", witness,
        records.append, lambda: {"qpos": [0.,0.,.8,1.,0.,0.,0.]+[0.]*12, "qvel": [0.]*18})
    try:
        observed()
    except InvalidControl:
        pass
    assert witness["technical_failures"] == records and records[0]["native_steps"] == 23
    parent = {"mission_success": False, "failure_type": "UNSAFE", "failed_node": "s1",
              "failure_reason": "simulation safety stop: control contains non-finite values", "physical_halt": None}
    old_status = prior_acquire.entry_classification(parent, spec["cells_in_order"][1], None)[1]
    return {
        "status": "P1_SYNTHETIC_BEFORE_AFTER_CONTRAST_PASS",
        "meaning": "Synthetic arithmetic and source-seam error evidence only; not new scientific/physical samples.",
        "blocked_head": "98fa234e69a9a81867ed33a07579a3e0904f0758",
        "hold_cases": cases,
        "control_error": {"old_classification": old_status,
                          "repaired_exception_classification": records[0]["classification"],
                          "qualified_type": records[0]["qualified_type"],
                          "native_steps_before": 23, "native_steps_after": witness["native_steps"],
                          "technical_stop_required": bool(witness["technical_failures"]),
                          "traceback_retained": bool(records[0]["traceback"]),
                          "full_router_and_campaign_fault_injection": "See test_acquire.py; contrast does not construct a live session."},
        "source_sha256": {str(p.relative_to(ROOT)).replace("\\","/"): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (OLD/"acquire.py", OLD/"audit.py", HERE/"acquire.py", HERE/"audit.py", error_file, DESIGN)},
        "physics_steps": 0, "policy_inferences": 0, "provider_calls": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", type=Path)
    args = parser.parse_args()
    value = contrast()
    if args.write:
        with args.write.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
