"""Lossless export and prospective decision for completed reference ablation."""
from __future__ import annotations
import gzip
import hashlib
import json
from pathlib import Path
import shutil

from g1swarm.paths import repo_root
from g1swarm.reference_ablation.experiment import canonical_physics, verify_history, write_new


def receipt(path):
    raw = path.read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def reduction(a, b):
    return (abs(a)-abs(b))/abs(a)*100 if a else None


if __name__ == "__main__":
    root = repo_root()
    source = root/"artifacts/reference_frame_ablation_001"
    directory = root/"experiments/phase3a/reference_frame_ablation_001"
    completion = json.loads((source/"completion.json").read_text(encoding="utf-8"))
    if completion["status"] != "COMPLETE" or completion["records"] != 104:
        raise RuntimeError("Incomplete ablation; preserve exception rather than publish a complete verdict")
    history = verify_history()
    records = [json.loads(x) for x in (source/"results.jsonl").read_text(encoding="utf-8").splitlines()]
    primary = [r for r in records if r["phase"] == "primary"]
    actual = {r["case_id"]: r for r in primary if r["reference_mode"] == "actual_node_start"}
    ideal = {r["case_id"]: r for r in primary if r["reference_mode"] == "ideal_commanded_axis"}
    if set(actual) != set(ideal) or len(actual) != 26:
        raise RuntimeError("Primary paired membership changed")
    task_losses = [k for k in actual if actual[k]["task_success"] and not ideal[k]["task_success"]]
    physical_losses = [k for k in actual if actual[k]["physical_success"] and not ideal[k]["physical_success"]]
    primitives = [k for k in actual if actual[k]["group"] == "primitive"]
    primitive_identity = {k: canonical_physics(actual[k]) == canonical_physics(ideal[k]) for k in primitives}
    sequences = {}
    for key in actual:
        if actual[key]["group"] != "sequence":
            continue
        a, b = actual[key], ideal[key]
        an, bn = a["nodes"][-1], b["nodes"][-1]
        entry = {"actual_task_success": a["task_success"], "ideal_task_success": b["task_success"],
                 "actual_physical_success": a["physical_success"], "ideal_physical_success": b["physical_success"]}
        for name in ["ideal_path_lateral_error_m", "ideal_path_heading_error_deg"]:
            av, bv = an[name], bn[name]
            entry[name] = {"actual": av, "ideal": bv, "absolute_reduction_percent": reduction(av, bv),
                           "improved": abs(bv) < abs(av)}
        entry["endpoint_error_m"] = {"actual": a["ideal_endpoint_error_m"], "ideal": b["ideal_endpoint_error_m"],
            "reduction_percent": reduction(a["ideal_endpoint_error_m"], b["ideal_endpoint_error_m"])}
        entry["simulation_time_s"] = {"actual": a["total_sim_time_s"], "ideal": b["total_sim_time_s"],
            "delta": b["total_sim_time_s"]-a["total_sim_time_s"]}
        entry["ideal_local_failures"] = [{"node_index": i, "skill": n["skill"],
            "lateral_drift_m": n["lateral_drift_m"], "heading_error_deg": n["heading_error_deg"],
            "violations": n["violations"], "envelope": n["envelope"]}
            for i, n in enumerate(b["nodes"]) if not n["task_success"]]
        sequences[key] = entry
    global_gain = all(v[name]["improved"] for v in sequences.values()
                      for name in ["ideal_path_lateral_error_m", "ideal_path_heading_error_deg"])
    repeat_ok = all(x["passed"] for x in completion["repeatability_identity"])
    history_ok = all(x["passed"] for x in completion["actual_historical_identity"])
    gate = global_gain and not task_losses and not physical_losses and all(primitive_identity.values()) and repeat_ok and history_ok
    decision = {"verdict": "GLOBAL_PRECISION_GAIN_WITH_LOCAL_TASK_REGRESSION" if task_losses else
                ("REFERENCE_HYPOTHESIS_SUPPORTED" if gate else "REFERENCE_HYPOTHESIS_NOT_READY"),
        "prospective_training_gate": "PASS" if gate else "FAIL", "PPO_training_started": False,
        "primary_cases_per_arm": 26, "repeatability_runs_separate": 52,
        "task_regression_ids": task_losses, "physical_regression_ids": physical_losses,
        "primitive_exact_identity": primitive_identity,
        "both_sequence_lateral_and_heading_gain": global_gain, "sequence_metrics": sequences,
        "historical_identity_pass": history_ok, "repeatability_pass": repeat_ok,
        "inference_scope": "Full origin+heading intervention on known cases; not heading-only causal isolation or fresh blind generalization",
        "no_new_task_threshold": True, "old_labels_and_envelopes_unchanged": True,
        "language_Runtime_gate": "BLOCKED_UNCHANGED", "Jev_or_MultiSwarm": False,
        "provenance": completion["provenance"], "history_verified": history}
    write_new(directory/"decision.json", decision)
    evidence = directory/"evidence"
    evidence.mkdir(exist_ok=False)
    inventory = {}
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        exported = evidence/path.relative_to(source)
        compressed = path.suffix == ".jsonl" and path.stat().st_size > 200000
        if compressed:
            exported = exported.with_suffix(exported.suffix+".gz")
        exported.parent.mkdir(parents=True, exist_ok=True)
        if compressed:
            with exported.open("xb") as out:
                with gzip.GzipFile(fileobj=out, mode="wb", filename="", mtime=0) as gz:
                    gz.write(path.read_bytes())
            assert gzip.decompress(exported.read_bytes()) == path.read_bytes()
        else:
            shutil.copyfile(path, exported)
        inventory[exported.relative_to(root).as_posix()] = {
            "raw_path": path.relative_to(root).as_posix(), "raw": receipt(path),
            "exported": receipt(exported), "encoding": "gzip" if compressed else "identity"}
    write_new(directory/"evidence_manifest.json", {"experiment_id": "reference_frame_ablation_001",
        "provenance": completion["provenance"], "inventory": inventory, "items": len(inventory),
        "raw_artifacts_retained": True, "primary_runs": 52, "repeatability_runs": 52,
        "export_producer": "scripts/export_phase3a_reference.py", "export_producer_sha256": receipt(Path(__file__).resolve())["sha256"],
        "self_binding": "Postprocessing helper and inventory are bound by final publication commit; acquisition source commit is separately pinned"})
    print(json.dumps({"verdict": decision["verdict"], "PPO_gate": decision["prospective_training_gate"],
                      "task_regressions": task_losses, "exported_files": len(inventory),
                      "bytes_exported": sum(x["exported"]["bytes"] for x in inventory.values())}))
