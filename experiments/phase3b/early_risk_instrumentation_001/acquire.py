"""Frozen 3B.1b read-only paired acquisition; never imports or calls Jev.

Each arm is persisted immediately. An interruption or integrity failure keeps
all earlier files and never retries a case or alters frozen membership.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from observer import CHECKPOINTS, assert_equivalent, load_cases, replay_observed

HERE = Path(__file__).resolve().parent


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _save_once(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.write("\n")


def validate_freeze():
    """Refuse physics when frozen study code or source assets have drifted."""
    freeze = _read(HERE / "freeze_manifest.json")
    if freeze["schema"] != "phase3b1b_prephysics_freeze_v1" or freeze["physics_executions_at_freeze"] != 0:
        raise AssertionError("Prephysics freeze identity mismatch")
    for name, expected in freeze["study_assets"].items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != expected:
            raise AssertionError(f"Frozen study asset drift: {name}")
    source = _read(HERE / "source_manifest.json")
    repo = HERE.parents[2]
    for name, expected in source["sources"].items():
        if hashlib.sha256((repo / name).read_bytes()).hexdigest() != expected:
            raise AssertionError(f"Frozen source drift: {name}")


def validate_membership(protocol_path=HERE / "protocol.json"):
    protocol_path = Path(protocol_path).resolve()
    protocol = _read(protocol_path)
    if protocol["schema"] != "phase3b1b_early_risk_instrumentation_v1":
        raise AssertionError("Unexpected protocol")
    if (protocol["treatment"] != "frozen_baseline" or protocol["runner_simulation_seed"] != 0
            or protocol["snapshot_elapsed_s"] != list(CHECKPOINTS)
            or protocol["execution_matrix"] != ["observer_off", "observer_on"]
            or protocol["max_executions"] != 14):
        raise AssertionError("Frozen execution contract mismatch")
    cases = load_cases(protocol_path)
    if [c["id"] for c, _ in cases] != protocol["selected_case_order"]:
        raise AssertionError("Case order mismatch")
    cells = protocol["selected_nodes"]
    if len(cases) != 7 or len(cells) != 8 or len({x["cell_id"] for x in cells}) != len(cells):
        raise AssertionError("Selected cells changed")
    selected = {f"{case['id']}:node-{i}" for case, nodes in cases for i in nodes}
    if selected != {x["cell_id"] for x in cells}:
        raise AssertionError("Selected cells do not match case definitions")
    if any(case["nodes"][i]["skill"] != "walk_forward" for case, nodes in cases for i in nodes):
        raise AssertionError("Selected node is not a walk")
    repo = protocol_path.parents[3]
    benchmark = _read(repo / protocol["historical_cohort"])
    for path, sha in benchmark["source_hashes"].items():
        if hashlib.sha256((repo / path).read_bytes()).hexdigest() != sha:
            raise AssertionError(f"Historical source hash mismatch: {path}")
    historical = {x["cell_id"]: x for x in benchmark["cells"]}
    if not selected <= historical.keys():
        raise AssertionError("Cell outside frozen Phase 3B.1 cohort")
    prior_result = _read(repo / protocol["historical_results"])
    prior_by_cell = {cell_id: row for row in prior_result["rows"] if row["variant"] == "geometry_only"
                     for cell_id in row["source_cell_ids"]}
    for cell in cells:
        prior = prior_by_cell[cell["cell_id"]]
        actual_class = ("false_safe" if prior["false_safe"] else
                        "true_positive" if prior["strict_violation"] and prior["correct"] else
                        "true_safe" if not prior["strict_violation"] and prior["correct"] else "other")
        if actual_class != cell["prior_class"]:
            raise AssertionError(f"Prior Jev class drift: {cell['cell_id']}")
    return protocol, cases, historical


def validate_observation(case, selected_nodes, arm, historical):
    record = arm["record"]
    if record["case_id"] != case["id"] or record["treatment"] != "frozen_baseline":
        raise AssertionError("Replay case or treatment changed")
    if not arm["observer"]["observer_enabled"]:
        if arm["observer"]["snapshots"]:
            raise AssertionError("Off arm contains snapshots")
        return
    for index in selected_nodes:
        cell_id = f"{case['id']}:node-{index}"
        if index >= len(record["nodes"]):
            raise AssertionError(f"Selected node never executed: {cell_id}")
        node = record["nodes"][index]
        if node["skill"] != "walk_forward":
            raise AssertionError(f"Selected node was not walk: {cell_id}")
        if (not node["strict_success"]) != historical[cell_id]["strict_violation"]:
            raise AssertionError(f"Historical strict label drift: {cell_id}")
        for checkpoint in CHECKPOINTS:
            key = f"{index}:{checkpoint:g}"
            item = arm["observer"]["snapshots"].get(key)
            if item is None:
                raise AssertionError(f"Missing exact snapshot: {cell_id}@{checkpoint}")
            if abs(item["elapsed_s"] - checkpoint) > 1e-8 or checkpoint >= node["duration_s"]:
                raise AssertionError(f"Snapshot at/beyond outcome: {cell_id}@{checkpoint}")


def acquire(protocol_path=HERE / "protocol.json", artifact_dir=HERE / "artifacts"):
    validate_freeze()
    protocol, cases, historical = validate_membership(protocol_path)
    artifact_dir = Path(artifact_dir).resolve()
    if artifact_dir.exists() and any(artifact_dir.iterdir()):
        raise FileExistsError("Acquisition artifact directory is nonempty; refusing rerun")
    _save_once(artifact_dir / "started.json", {"status": "STARTED", "protocol_schema": protocol["schema"],
                                                "case_order": protocol["selected_case_order"]})
    completed = []
    try:
        for case, nodes in cases:
            off = replay_observed(case, nodes, enabled=False)
            _save_once(artifact_dir / f"{case['id']}.observer_off.json", off)
            validate_observation(case, nodes, off, historical)
            on = replay_observed(case, nodes, enabled=True)
            _save_once(artifact_dir / f"{case['id']}.observer_on.json", on)
            assert_equivalent(off, on)
            validate_observation(case, nodes, on, historical)
            completed.append(case["id"])
            _save_once(artifact_dir / f"{case['id']}.paired_pass.json", {"case_id": case["id"],
                "equivalence": "PASS", "historical_labels": "MATCH", "snapshots": "PRE_ENDPOINT_EXACT"})
    except BaseException as exc:
        _save_once(artifact_dir / "stopped.json", {"status": "PARTIAL_STOPPED", "completed_cases": completed,
            "failure_type": type(exc).__name__, "failure": str(exc)})
        raise
    _save_once(artifact_dir / "completed.json", {"status": "ACQUISITION_COMPLETE", "completed_cases": completed,
        "executions": 2 * len(completed), "selected_cells": len(protocol["selected_nodes"])})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, default=HERE / "protocol.json")
    parser.add_argument("--artifacts", type=Path, default=HERE / "artifacts")
    args = parser.parse_args()
    acquire(args.protocol, args.artifacts)
