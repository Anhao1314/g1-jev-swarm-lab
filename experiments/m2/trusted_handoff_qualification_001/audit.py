"""Independent read-only audit of saved M2.3b evidence; never runs physics.

The checks derive identity, continuity, outcomes and measurements from raw
artifacts rather than accepting the producer's qualification booleans.
"""
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FREEZE_COMMIT = "e8c13333111fe7f07b68d7012175fb9ccba9db8f"
SOURCE_PIN = "a2325d393c3ffc46eaf7252122b61179ea0e35cb"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf8")


def value_sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def canonical(mission):
    """Independent normalization for this already-frozen exact Mission IR."""
    return {"schema_version": mission["schema_version"],
            "mission_id": mission["mission_id"],
            "steps": [{"id": row["id"], "skill": row["skill"],
                       "parameters": {key: float(value) for key, value in row["parameters"].items()},
                       "depends_on": row.get("depends_on", [])}
                      for row in mission["steps"]]}


def rows(path):
    with gzip.open(path, "rt", encoding="utf8") as stream:
        return [json.loads(line) for line in stream]


def yaw(state):
    w, x, y, z = state["base_orientation"]
    return math.atan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z))


def walk_metrics(node):
    start, end = node["start_state"], node["end_state"]
    x, y = [end["base_position"][i] - start["base_position"][i] for i in range(2)]
    heading = yaw(start)
    return {"distance_error_m": math.cos(heading)*x + math.sin(heading)*y - node["parameters"]["distance_m"],
            "lateral_drift_m": -math.sin(heading)*x + math.cos(heading)*y,
            "heading_error_deg": math.degrees((yaw(end)-heading+math.pi) % (2*math.pi)-math.pi),
            "simulation_time_s": end["simulation_time"]-start["simulation_time"]}


def project_nodes(nodes):
    return [{"id": row["node_id"], "skill": row["skill"],
             "parameters": row["parameters"], "depends_on": row["depends_on"]}
            for row in nodes]


def finite(value):
    if isinstance(value, dict):
        return all(finite(item) for item in value.values())
    if isinstance(value, list):
        return all(finite(item) for item in value)
    return not isinstance(value, (float, int)) or math.isfinite(value)


def run():
    started = time.perf_counter()
    spec = read(HERE / "protocol.json")
    frozen = read(HERE / "source_manifest.json")
    preflight = read(HERE / "preflight_audit.json")
    robot = yaml.safe_load((ROOT / "configs/robot/g1_locomotion_12dof.yaml").read_text(encoding="utf8"))
    protocol = yaml.safe_load((ROOT / spec["source_protocol"]).read_text(encoding="utf8"))
    halt_contract = read(ROOT / spec["halt_contract_source"])
    findings = []

    def check(name, passed, *, arm=None, details=None):
        findings.append({"check": name, "passed": bool(passed),
                         **({"arm": arm} if arm else {}),
                         **({"details": details} if details is not None else {})})

    check("exact_frozen_source_membership", set(frozen["files"]) == set(spec["frozen_source_paths"]))
    changed = [path for path, expected in frozen["files"].items() if sha(ROOT/path) != expected]
    check("all_158_frozen_files_unchanged", len(frozen["files"]) == 158 and not changed, details=changed)
    check("preflight_review_pins_still_match", all(sha(ROOT/path) == expected
          for path, expected in preflight["reviewed_files_sha256"].items()))
    for name in ("protocol.json", "acquire.py", "source_manifest.json", "preflight_audit.json"):
        original = subprocess.check_output(["git", "show", FREEZE_COMMIT+":"+
                                           (HERE/name).relative_to(ROOT).as_posix()], cwd=ROOT)
        check("freeze_commit_exact_"+name, original == (HERE/name).read_bytes())
    extraction = read(ROOT / "src/g1swarm/trusted_handoff_v0/source_manifest.json")
    check("source_authority_pin_preserved", extraction["source_commit"] == spec["source_authority_pin"] == SOURCE_PIN)
    source_blobs = []
    for original in extraction["sources"]:
        blob = subprocess.check_output(["git", "rev-parse", SOURCE_PIN+":"+original["path"]], cwd=ROOT).decode().strip()
        content = subprocess.check_output(["git", "show", SOURCE_PIN+":"+original["path"]], cwd=ROOT)
        source_blobs.append(blob == original["git_blob"] and hashlib.sha256(content).hexdigest()
                            == original["git_blob_bytes_sha256"])
    check("all_seven_original_source_git_blobs_reverified", len(source_blobs) == 7 and all(source_blobs))
    required_scope = "NEW_EXPLICIT_PLAN_INSTRUCTION_NOT_SOURCE_UNIQUENESS"
    expected_canonical = canonical(spec["new_mission"])
    signed_hash = value_sha(expected_canonical)
    expected_lifecycle_hash = value_sha(spec["new_mission"])
    semantics_paths = ["src/g1swarm/mission/ir.py", "src/g1swarm/mission/validator.py",
        "src/g1swarm/mission/task_graph.py", "src/g1swarm/mission/grounding.py",
        "src/g1swarm/mission/runtime.py", "src/g1swarm/skills/basic.py",
        "src/g1swarm/simplex/canonical.py", "src/g1swarm/simplex/structural_guard.py",
        "src/g1swarm/mission/live_session.py", "src/g1swarm/mission/lifecycle.py",
        "src/g1swarm/mission/trusted_handoff.py", "src/g1swarm/trusted_handoff_v0/__init__.py",
        "src/g1swarm/trusted_handoff_v0/support.py", "src/g1swarm/trusted_handoff_v0/principal.py",
        "src/g1swarm/trusted_handoff_v0/handoff.py"]
    semantics_hash = value_sha({name: sha(ROOT/name) for name in semantics_paths})
    arms = {}
    observed_paths = {HERE / name for name in ("protocol.json", "source_manifest.json", "preflight_audit.json")}

    for arm in spec["execution_order"]:
        base = HERE / "artifacts" / arm
        receipt, continuous = read(base/"receipt.json"), read(base/"continuity.json")
        qualification, parent = read(base/"qualification.json"), read(base/"parent_result.json")
        requests, entries = read(base/"requests.json"), read(base/"dispatch_entries.json")
        dispatches, events = read(base/"node_dispatches.json"), read(base/"handoff_events.json")
        trace = rows(base/"state_trace.jsonl.gz")
        expected_artifacts = {path.name for path in base.iterdir() if path.is_file()} - {"receipt.json"}
        check("receipt_covers_every_raw_artifact", set(receipt["artifact_files"]) == expected_artifacts, arm=arm)
        mismatches = [name for name, expected in receipt["artifact_files"].items() if sha(base/name) != expected]
        check("raw_receipt_hashes_match", not mismatches, arm=arm, details=mismatches)
        check("formal_source_commit_and_manifest", receipt["source_commit"] == FREEZE_COMMIT
              and receipt["source_manifest_sha256"] == sha(HERE/"source_manifest.json"), arm=arm)
        check("frozen_budget_and_once_only_membership", receipt["seed"] == 0
              and receipt["total_physics_steps"] <= spec["maximum_physics_steps"][arm]
              and receipt["wall_time_s"] < spec["maximum_wall_time_s_per_arm"]
              and receipt["budget_failure"] is None and not (base/"acquisition_failure.json").exists(), arm=arm)
        check("continuous_trace_sequence_and_timestep", len(trace) == receipt["total_physics_steps"]
              and [row["sequence"] for row in trace] == list(range(1, len(trace)+1))
              and all(math.isclose(trace[i]["time_s"]-trace[i-1]["time_s"], 0.002,
                                   rel_tol=0, abs_tol=1e-12) for i in range(1, len(trace))), arm=arm)
        comparator = ROOT/spec["comparators"]["historical_authorized" if arm == "trusted_authorized" else "historical_invalid"]
        with np.load(base/"poses.npz", allow_pickle=False) as actual, np.load(comparator/"poses.npz", allow_pickle=False) as old:
            pose_equal = actual.files == old.files and all(np.array_equal(actual[key], old[key]) for key in actual.files)
        check("independently_compared_all_pose_arrays", pose_equal, arm=arm)
        check("independently_compared_every_physical_trace_row", trace == rows(comparator/"state_trace.jsonl.gz"), arm=arm)
        parent_dir = base/"ledger"/parent["mission_id"]
        parent_graph = read(parent_dir/"task_graph.json")
        check("parent_remains_failed_dependents_blocked", parent["state"] == "FAILED"
              and parent["mission_success"] is False and parent["failed_node"] == "s1"
              and [(node["node_id"], node["state"]) for node in parent_graph["nodes"]]
                  == [("s1", "FAILED"), ("s2", "BLOCKED"), ("s3", "BLOCKED")], arm=arm)
        check("parent_graph_unchanged_current_disk", parent_graph == continuous["parent_graph_before"]
              == continuous["parent_graph_after"], arm=arm)
        check("parent_result_original_bytes_preserved", sha(base/"parent_result.json")
              == continuous["parent_result_sha256"] == continuous["parent_result_sha256_after"], arm=arm)
        check("parent_ledger_every_original_file_hash_preserved", continuous["parent_ledger_before"]
              == continuous["parent_ledger_after"]
              and all(sha(base/"ledger"/name) == expected for name, expected in continuous["parent_ledger_before"].items()), arm=arm)
        checkpoints = [continuous[key] for key in ("after_parent", "before_new_mission", "after_new_mission", "final") if key in continuous]
        check("same_session_simulator_controller_all_boundaries", all(len({point[key] for point in checkpoints}) == 1
              for key in ("session_identity", "simulation_identity", "controller_identity")), arm=arm)
        check("raw_controller_memory_recorded_at_all_boundaries", all(
              all(key in point for key in ("controller_action", "controller_target", "controller_counter"))
              and finite(point) for point in checkpoints), arm=arm)
        check("zero_resets_after_two_startup_resets", all(point["reset_calls"] == point["reset_data_calls"] == 2
              and point["reset_keyframe_calls"] == 0 for point in checkpoints)
              and receipt["reset_calls"] == receipt["reset_data_calls"] == 2
              and receipt["reset_keyframe_calls"] == receipt["external_session_factory_calls"] == 0, arm=arm)
        halt = parent["physical_halt"]
        halt_rows = halt["trace"]
        halt_window = int(round(halt_contract["stop_skill_parameters"]["window_s"]/0.002))
        halt_mean = float(np.mean([row["speed_mps"] for row in halt_rows[-halt_window:]]))
        halt_displacement = math.dist(halt["pre_halt_state"]["base_position"][:2], halt["final_state"]["base_position"][:2])
        check("raw_halt_criteria_rederived", halt["status"] == "HALT_SUCCEEDED"
              and halt["skill_status"] == "SUCCESS" and len(halt_rows) >= halt_window
              and halt_rows[-1]["speed_mps"] <= halt_contract["acceptance"]["max_final_instantaneous_speed_mps"]
              and halt_mean <= halt_contract["acceptance"]["max_final_window_mean_speed_mps"]
              and halt["final_state"]["simulation_time"]-halt["pre_halt_state"]["simulation_time"]
                  <= halt_contract["acceptance"]["max_duration_s"]
              and halt_displacement <= halt_contract["acceptance"]["max_post_block_planar_displacement_m"]
              and all(finite(row) and row["standing"] and not row["fallen"] for row in halt_rows), arm=arm)
        check("fresh_assessment_exact_halt_endpoint", continuous["after_parent"]["state"] == halt["final_state"]
              and math.hypot(*continuous["after_parent"]["qvel"][:2]) <= spec["state_assessment"]["max_instantaneous_speed_mps"], arm=arm)
        expected_requests = spec["positive_requests" if arm == "trusted_authorized" else "negative_requests"]
        check("exact_frozen_request_membership", [item["request"] for item in requests] == expected_requests, arm=arm)
        denied = [item for item in requests if item["request"] != "valid_registered_full_plan_grant"]
        negative_details = [{"request": item["request"], "reason": item["result"]["reason"],
                             "physics_steps_delta": item["after"]["witness_steps"]-item["before"]["witness_steps"],
                             "node_calls_delta": item["after"]["node_calls"]-item["before"]["node_calls"],
                             "executor_calls_delta": item["after"]["executor_calls"]-item["before"]["executor_calls"],
                             "raw_state_equal": item["before"] == item["after"]} for item in denied]
        check("all_denials_zero_raw_state_time_node_executor_physics_change", all(
              item["result"]["status"] == "ESCALATE" and item["result"]["new_mission_result"] is None
              and item["before"] == item["after"] for item in denied), arm=arm, details=negative_details)
        check("denials_preserve_parent_and_have_explicit_reason", all(item["result"]["parent_preserved"] is True
              and isinstance(item["result"]["reason"], str) and item["result"]["reason"] for item in denied), arm=arm)
        issued = [item for item in events if item["event"] == "fixture_handoff_issued"]
        check("issuer_scope_and_semantics_not_production_identity", bool(issued) and all(
              item["production_authority"] is False and item["assurance"] == "TEST_ONLY_SIMULATED_PRINCIPAL"
              and item["authority_scope"] == required_scope and item["original_source_unique"] is False
              and item["signed_plan_sha256"] == signed_hash
              and item["handoff_semantics_sha256"] == semantics_hash for item in issued), arm=arm)
        check("separate_canonical_hash_domains_recomputed", qualification["signed_plan_sha256"] == signed_hash
              and qualification["lifecycle_mission_sha256"] == expected_lifecycle_hash
              and signed_hash != expected_lifecycle_hash
              and qualification["handoff_semantics_sha256"] == semantics_hash, arm=arm)

        metrics = {"parent_halt_last_1s_mean_speed_mps": halt_mean,
                   "parent_halt_endpoint_speed_mps": halt_rows[-1]["speed_mps"],
                   "parent_halt_displacement_m": halt_displacement,
                   "physics_steps": len(trace), "negative_requests": negative_details}
        if arm == "trusted_authorized":
            new = read(base/"new_result.json")
            new_dir = base/"ledger"/spec["new_mission"]["mission_id"]
            manifest, graph = read(new_dir/"mission_manifest.json"), read(new_dir/"task_graph.json")
            actual_entry = entries[0] if len(entries) == 1 else {}
            check("one_actual_canonical_executor_entry", len(entries) == 1
                  and actual_entry["existing_session_is_original"] is True
                  and canonical(actual_entry["canonical_mission"]) == expected_canonical
                  and actual_entry["canonical_plan_sha256"] == signed_hash, arm=arm)
            expected_entry = deepcopy(continuous["before_new_mission"])
            expected_entry["executor_calls"] += 1
            check("exact_raw_state_at_actual_executor_entry", actual_entry.get("before") == expected_entry
                  and continuous["after_parent"] == continuous["before_new_mission"], arm=arm)
            check("actual_manifest_complete_plan_matches_issuer", canonical(manifest["mission_input"]) == expected_canonical
                  and value_sha(canonical(manifest["mission_input"])) == signed_hash, arm=arm)
            check("actual_graph_and_dispatched_physical_nodes_match_complete_steps",
                  project_nodes(graph["nodes"]) == expected_canonical["steps"]
                  == project_nodes([item for item in dispatches if item["phase"] == "new_mission"]), arm=arm)
            check("new_ledger_distinct_original_and_three_nodes_succeed", new["mission_id"] != parent["mission_id"]
                  and new["state"] == "SUCCESS" and new["completed_nodes"] == 3
                  and [node["state"] for node in graph["nodes"]] == ["SUCCESS"]*3
                  and graph["execution_order"] == ["n1", "n2", "n3"], arm=arm)
            walk = walk_metrics(graph["nodes"][0])
            observed = new["nodes"][0]["feedback_decision"]["observed_metrics"]
            limits = new["nodes"][0]["feedback_decision"]["evaluation"]["limits"]
            check("strict_walk_metrics_rederived_from_actual_states", all(math.isclose(walk[key], observed[key], rel_tol=0, abs_tol=1e-10)
                  for key in walk), arm=arm)
            check("strict_walk_frozen_limits_pass", abs(walk["distance_error_m"]) <= limits["distance_error_max_m"]
                  and abs(walk["lateral_drift_m"]) <= limits["lateral_drift_max_m"]
                  and abs(walk["heading_error_deg"]) <= limits["heading_error_max_deg"]
                  and walk["simulation_time_s"] <= limits["timeout_max_s"], arm=arm, details=walk)
            new_rows = [item for item in trace if item["phase"] == "new_mission"]
            stop_rows = [item for item in new_rows if item["active_skill"] == "stop"]
            window_steps = int(round(protocol["skill_parameters"]["stop"]["window_s"]/0.002))
            stop_mean = float(np.mean([item["speed_mps"] for item in stop_rows[-window_steps:]]))
            final_speed = math.hypot(*continuous["final"]["qvel"][:2])
            check("final_stop_complete_window_rederived", len(stop_rows) >= window_steps == 500
                  and stop_mean <= spec["acceptance"]["new_task_final_stop_max_window_mean_speed_mps"]
                  and final_speed <= spec["acceptance"]["new_task_final_stop_max_instantaneous_speed_mps"]
                  and math.isclose(final_speed, stop_rows[-1]["speed_mps"], rel_tol=0, abs_tol=1e-14), arm=arm)
            check("new_task_standing_finite_without_fall", new["physical_success"] is True
                  and all(finite(item) and item["standing"] and not item["fallen"]
                          and item["base_height_m"] >= 0.55 and item["tilt_deg"] <= 30.0 for item in new_rows), arm=arm)
            check("new_steps_match_exact_counter_increment", len(new_rows) == new["simulation_steps_executed"]
                  == continuous["final"]["witness_steps"]-continuous["after_parent"]["witness_steps"] == 5989, arm=arm)
            metrics.update(new_task_nodes_completed=new["completed_nodes"], new_physics_steps=len(new_rows),
                           strict_walk_rederived=walk, final_stop_speed_mps=final_speed,
                           final_stop_last_500_mean_speed_mps=stop_mean)
        else:
            check("invalid_arm_has_no_new_mission_or_executor_entry", entries == []
                  and not (base/"new_result.json").exists()
                  and len(dispatches) == 1 and dispatches[0]["node_id"] == "s1"
                  and continuous["after_parent"] == continuous["final"], arm=arm)
            check("permission_control_is_independent_of_registered_principal", denied[-1]["result"]["reason"]
                  == "PRINCIPAL_CONTINUATION_PERMISSION_MISSING", arm=arm)
            check("failed_plan_mismatch_then_replay_remains_rejected", denied[2]["result"]["reason"] == "PLAN_CHANGED"
                  and denied[3]["result"]["reason"] == "UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF", arm=arm)
        arms[arm] = metrics
        observed_paths.update(path for path in base.rglob("*") if path.is_file())

    failed = [item for item in findings if not item["passed"]]
    return {"status": "PASS_INDEPENDENT_REAL_HANDOFF_AUDIT" if not failed else "FAIL_INDEPENDENT_AUDIT",
            "scientific_verdict_supported": "PASS_BOUNDED_REAL_MUJOCO_TRUSTED_HANDOFF" if not failed else "INCONCLUSIVE",
            "reviewer": "/root/m23b_independent_audit", "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
            "physics_executions_by_auditor": 0, "source_freeze_commit": FREEZE_COMMIT,
            "source_manifest_files_verified": len(frozen["files"]), "checks": findings,
            "failed_checks": failed, "arms": arms, "canonical_plan_sha256": signed_hash,
            "lifecycle_mission_sha256": expected_lifecycle_hash, "semantics_sha256": semantics_hash,
            "audit_wall_time_s": time.perf_counter()-started,
            "auditor_code_sha256": sha(Path(__file__)),
            "reviewed_evidence_sha256": {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted(observed_paths)},
            "limits": ["Previously seen deterministic seed-0 state and exact tasks, not independent-state generalization.",
                       "Trusted serial in-process TEST_ONLY fixtures, not production Human Principal Authority or concurrent atomicity.",
                       "Simulator continuation is qualified only for this saved bounded run; no hardware safety or autonomous recovery.",
                       "No Jev, Language Runtime/D011 unlock, model call, training or additional physics by audit."]}


if __name__ == "__main__":
    result = run()
    if sys.argv[1:] == ["--save"]:
        with (HERE/"audit.json").open("x", encoding="utf8", newline="\n") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
    elif sys.argv[1:]:
        raise SystemExit("usage: audit.py [--save]")
    print(json.dumps({"status": result["status"], "checks": len(result["checks"]),
                      "failed_checks": result["failed_checks"], "arms": result["arms"]}, indent=2))
    if result["failed_checks"]:
        raise SystemExit(1)
