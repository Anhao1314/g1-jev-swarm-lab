"""Read-only M2.5A candidate/provenance check. No simulator or policy imports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, label: str) -> None:
    if not condition:
        raise ValueError(label)


def validate_contract(spec: dict) -> None:
    require(spec["status"] == "CANDIDATE_FROZEN_FOR_INDEPENDENT_REVIEW", "design status changed")
    require(spec["physics_authorized"] is False, "physics authorization forbidden")
    require(spec["historical_scientific_verdict"] == "M2.4_INCONCLUSIVE", "historical verdict changed")
    require(spec["baseline_main_commit"] == "0eff13a5cb523690cde31a742cc985e9ee0eaf03", "baseline changed")
    cells = spec["cells_in_order"]
    require([(cell["id"], cell["historical_arm"]) for cell in cells] == [
        ("seen_failure_halt_hold", "authorization_refusals"),
        ("turn45_failure_halt_hold", "authorization_refusals"),
        ("normal_stop_hold_control", "unchanged_safe_mission"),
    ], "cell membership changed")
    require([cell["max_native_steps"] for cell in cells] == [10000, 12000, 8000], "cell budgets changed")
    require(all(cell["max_wall_s"] == 120 for cell in cells), "cell wall budget changed")
    require(all(cell["historical_pre_hold_native_steps"] + 1000 <= cell["max_native_steps"] for cell in cells), "hold exceeds cell budget")
    budget = spec["budget"]
    require(budget["maximum_cells"] == len(cells) == 3, "cell count changed")
    require(budget["attempts_per_cell"] == 1, "repeat forbidden")
    require(budget["maximum_native_steps_total"] == sum(cell["max_native_steps"] for cell in cells) == 30000, "total native budget changed")
    require(budget["maximum_wall_s_per_cell"] == 120, "per-cell wall budget changed")
    require(budget["maximum_wall_s_total"] == 360, "total wall budget changed")
    require(budget["no_result_driven_retries_or_state_replacement"] is True, "retry/replace forbidden")
    hold = spec["hold"]
    require(spec["fixed_config"]["native_timestep_s"] * hold["native_steps"] == hold["duration_s"] == 2.0, "hold duration changed")
    require(hold["command_xyz_mps_radps"] == [0.0, 0.0, 0.0], "zero command changed")
    require(hold["rolling_window_steps"] == 500, "rolling window changed")
    require(hold["acceptance"]["all_1000_rolling_means_at_most_mps"] == 0.1, "rolling threshold changed")
    require(hold["acceptance"]["final_instantaneous_speed_at_most_mps"] == 0.1, "endpoint speed threshold changed")
    require(hold["acceptance"]["hold_xy_path_length_at_most_m"] == 0.2, "hold path threshold changed")
    require(all(hold["acceptance"][key] is True for key in
                ("all_steps_finite", "all_steps_standing", "all_steps_no_fall")), "posture/finite checks changed")
    continuity = spec["continuity_and_integrity"]
    for key in ("post_initialization_simulator_resets", "controller_reset_calls_from_qualifying_step_through_hold",
                "policy_reset_memory_calls_from_qualifying_step_through_hold", "task_node_or_new_mission_dispatch_during_hold"):
        require(continuity[key] == 0, key)
    require(continuity["all_hold_commands_exactly_zero"] is True, "zero-command witness changed")
    require(continuity["all_hold_steps_journaled"] is True, "raw journal witness changed")


def validate_sources(root: Path = ROOT, here: Path = HERE) -> dict:
    binding = read_json(here / "source_binding.json")
    spec = read_json(here / "protocol.json")
    validate_contract(spec)
    require(binding["baseline_main_commit"] == spec["baseline_main_commit"], "source baseline mismatch")
    for name, expected in binding["sha256"].items():
        path = (root / name).resolve()
        require(path.is_relative_to(root.resolve()), name)
        require(sha256_file(path) == expected, name)

    raw_seal = read_json(root / spec["historical_inputs"]["m24_raw_seal"])
    archive_seal = read_json(root / "experiments/m2/cross_state_reliability_archives_001/manifest.json")
    historical_result = read_json(root / spec["historical_inputs"]["m24_result"])
    require(historical_result["verdict"] == "INCONCLUSIVE", "M2.4 scientific verdict changed")
    require(historical_result["integrity_verdict"] == "PASS", "M2.4 integrity verdict changed")
    require(len(raw_seal["files"]) == 178, "raw seal coverage changed")
    selected_members = binding["selected_raw_members"]
    verified_members = 0
    cells_by_arm = {f'{cell["m24_state"]}--{cell["historical_arm"]}': cell for cell in spec["cells_in_order"]}
    require(set(cells_by_arm) == set(selected_members), "source-to-cell mapping mismatch")
    for arm, members in selected_members.items():
        archive_name = arm + ".tar.gz"
        archive_path = root / "experiments/m2/cross_state_reliability_archives_001" / archive_name
        require(archive_seal["archives"][archive_name]["sha256"] == sha256_file(archive_path), archive_name)
        with tarfile.open(archive_path, "r:gz") as archive:
            def sealed_member(member_name: str) -> bytes:
                source_name = f"experiments/m2/cross_state_reliability_001/artifacts/{arm}/{member_name}"
                member = archive.extractfile(source_name)
                require(member is not None, source_name)
                with member:
                    data = member.read()
                    require(sha256_bytes(data) == raw_seal["files"][source_name]["sha256"], source_name)
                    return data

            for member_name, expected in members.items():
                data = sealed_member(member_name)
                verified_members += 1
                require(sha256_bytes(data) == expected, member_name)
                if member_name == "parent_result.json":
                    parent = json.loads(data)
                    if arm == "normal_control--unchanged_safe_mission":
                        require(parent["state"] == "SUCCESS" and parent["mission_success"] is True
                                and parent["physical_success"] is True and parent["completed_nodes"] == 3,
                                "normal control historical outcome mismatch")
                        final_node = parent["nodes"][-1]
                        require(final_node["node_id"] == "s3" and final_node["skill"] == "stop"
                                and final_node["metrics"]["skill_status"] == "SUCCESS",
                                "normal Stop historical outcome mismatch")
                    else:
                        require(parent["state"] == "FAILED" and parent["mission_success"] is False
                                and parent["failure_type"] == "TASK_ENVELOPE_VIOLATION"
                                and parent["failed_node"] == "s1", "failure cohort outcome mismatch")
                        halt_result = parent["physical_halt"]
                        require(halt_result["status"] == "HALT_SUCCEEDED"
                                and halt_result["skill_status"] == "SUCCESS"
                                and all(halt_result["checks"].values()), "failure cohort Halt mismatch")
            witness = json.loads(sealed_member("witness.json"))
            verified_members += 1
            deliberate_steps = 0
            if arm != "normal_control--unchanged_safe_mission":
                stale = json.loads(sealed_member("stale_state_step.json"))
                verified_members += 1
                require(stale["refusal_physics_steps"] == 0 and stale["deliberate_physics_steps"] == 1,
                        "refusal arm stale-state step mismatch")
                deliberate_steps = 1
            require(witness["steps"] - deliberate_steps == cells_by_arm[arm]["historical_pre_hold_native_steps"],
                    "historical pre-hold native budget premise mismatch")

    halt = read_json(root / spec["historical_inputs"]["first_crossing_analysis"])
    for arm, members in selected_members.items():
        if arm == "normal_control--unchanged_safe_mission":
            continue
        case = arm.split("--", 1)[0]
        row = next(item for item in halt["results"] if item["case"] == case and item["arm"] == "authorization_refusals")
        require(row["sha256"] == members["parent_result.json"], "first-crossing source mismatch")
        require(row["post_qualification_hold_steps"] == 0, "historical hold coverage changed")
        require(row["first_qualifying_step"] >= row["window_samples"] == 500, "first-crossing window mismatch")
        require(0 < row["margin_mps"] < 0.001, "first-crossing margin mismatch")

    freeze = read_json(here / "freeze_manifest.json")
    require(freeze["physics_authorized"] is False and freeze["baseline_main_commit"] == spec["baseline_main_commit"],
            "candidate freeze authority or base mismatch")
    for name, expected in freeze["sha256"].items():
        require(sha256_file(root / name) == expected, "candidate freeze mismatch: " + name)

    return {
        "status": "DESIGN_OFFLINE_PROVENANCE_PASS_NO_PHYSICS",
        "baseline_main_commit": binding["baseline_main_commit"],
        "cells": list(selected_members),
        "historical_raw_seal_entries": len(raw_seal["files"]),
        "source_files_verified": len(binding["sha256"]),
        "archive_members_verified": verified_members,
        "candidate_files_verified": len(freeze["sha256"]),
        "physics_authorized": False,
        "new_physics_executed": False,
    }


if __name__ == "__main__":
    print(json.dumps(validate_sources(), indent=2, sort_keys=True))
