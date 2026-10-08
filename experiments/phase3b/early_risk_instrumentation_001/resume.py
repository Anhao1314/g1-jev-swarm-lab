"""One-time continuation of the frozen 3B.1b paired acquisition.

The first pair and its PARTIAL_STOPPED receipt are immutable. This entrypoint
accepts only amendment_001's remaining six cases; it never reruns a case or
uses a provider. The caller must freeze this file in freeze_manifest_v2 before
running it.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from acquire import HERE, _read, _save_once, validate_membership, validate_observation
from observer import assert_equivalent, replay_observed


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_resume_freeze(study_dir: Path = HERE) -> dict:
    """Check revised code freeze, pinned sources, and original partial bytes."""
    study_dir = Path(study_dir).resolve()
    freeze = _read(study_dir / "freeze_manifest_v2.json")
    if freeze["schema"] != "phase3b1b_comparator_amendment_freeze_v2":
        raise AssertionError("Revised freeze identity mismatch")
    for name, expected in freeze["study_assets"].items():
        if _sha(study_dir / name) != expected:
            raise AssertionError(f"Revised frozen study asset drift: {name}")
    source = _read(study_dir / "source_manifest.json")
    repo = study_dir.parents[2]
    for name, expected in source["sources"].items():
        if _sha(repo / name) != expected:
            raise AssertionError(f"Frozen source drift: {name}")
    amendment = _read(study_dir / "amendment_001.json")
    if (amendment["schema"] != "phase3b1b_timing_comparator_amendment_v1"
            or amendment["original_freeze_commit"] != "0400c3f9eb62b519845213658f52098b6c8005da"
            or amendment["first_case_rerun"] is not False
            or amendment["scientific_contract_changed"] is not False
            or amendment["remaining_execution_cap"] != 12):
        raise AssertionError("Unexpected resume amendment")
    for name, expected in amendment["original_partial_artifact_sha256"].items():
        if _sha(study_dir / "artifacts" / name) != expected:
            raise AssertionError(f"Original partial artifact drift: {name}")
    return amendment


def validate_original_pair(case, nodes, historical, artifact_dir: Path) -> None:
    off = _read(artifact_dir / f"{case['id']}.observer_off.json")
    on = _read(artifact_dir / f"{case['id']}.observer_on.json")
    validate_observation(case, nodes, off, historical)
    validate_observation(case, nodes, on, historical)
    assert_equivalent(off, on)


def resume(study_dir: Path = HERE) -> None:
    study_dir = Path(study_dir).resolve()
    amendment = validate_resume_freeze(study_dir)
    protocol, cases, historical = validate_membership(study_dir / "protocol.json")
    if [case["id"] for case, _ in cases[1:]] != amendment["remaining_case_order"]:
        raise AssertionError("Resume order does not match frozen membership")
    if len(cases) != 7 or cases[0][0]["id"] != "eval-ws-01":
        raise AssertionError("Original pair is not the first frozen case")
    artifact_dir = study_dir / "artifacts"
    expected_original = set(amendment["original_partial_artifact_sha256"])
    if {path.name for path in artifact_dir.iterdir()} != expected_original:
        raise FileExistsError("Unexpected acquisition artifact; refusing resume or rerun")
    validate_original_pair(*cases[0], historical, artifact_dir)
    completed = [cases[0][0]["id"]]
    try:
        for case, nodes in cases[1:]:
            off = replay_observed(case, nodes, enabled=False)
            _save_once(artifact_dir / f"{case['id']}.observer_off.json", off)
            validate_observation(case, nodes, off, historical)
            on = replay_observed(case, nodes, enabled=True)
            _save_once(artifact_dir / f"{case['id']}.observer_on.json", on)
            assert_equivalent(off, on)
            validate_observation(case, nodes, on, historical)
            completed.append(case["id"])
            _save_once(artifact_dir / f"{case['id']}.paired_pass.json", {
                "case_id": case["id"], "equivalence": "PASS",
                "historical_labels": "MATCH", "snapshots": "PRE_ENDPOINT_EXACT"})
    except BaseException as exc:
        _save_once(artifact_dir / "resumed_stopped.json", {
            "status": "PARTIAL_STOPPED", "completed_cases": completed,
            "failure_type": type(exc).__name__, "failure": str(exc)})
        raise
    _save_once(artifact_dir / "resumed_completed.json", {
        "status": "ACQUISITION_COMPLETE", "completed_cases": completed,
        "executions": 2 * len(completed),
        "new_executions": 2 * (len(completed) - 1),
        "selected_cells": len(protocol["selected_nodes"]),
        "original_partial_preserved": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--study-dir", type=Path, default=HERE)
    args = parser.parse_args()
    resume(args.study_dir)
