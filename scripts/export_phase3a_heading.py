"""Preserve fixed-alpha evidence and apply the inherited gate without rescoring."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import shutil

from g1swarm.heading_alignment.experiment import ALPHAS, MODE_BY_ALPHA, canonical_alignment, verify_history
from g1swarm.paths import repo_root
from g1swarm.reference_ablation.experiment import write_new


def receipt(path):
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def reduction(baseline, candidate):
    return (abs(baseline) - abs(candidate)) / abs(baseline) * 100 if baseline else None


if __name__ == "__main__":
    root = repo_root()
    source = root / "artifacts/heading_alignment_strength_001"
    directory = root / "experiments/phase3a/heading_alignment_strength_001"
    completion = json.loads((source / "completion.json").read_text(encoding="utf-8"))
    if completion["status"] != "COMPLETE" or completion["records"] != 156:
        raise RuntimeError("Incomplete fixed-alpha campaign")
    history = verify_history()
    protocol = json.loads((directory / "protocol.json").read_text(encoding="utf-8"))
    provenance = completion["provenance"]
    if receipt(directory / "protocol.json")["sha256"] != provenance["protocol_sha256"]:
        raise RuntimeError("Protocol changed")
    for name, expected in provenance["source_hashes"].items():
        if receipt(root / name)["sha256"] != expected:
            raise RuntimeError(f"Acquisition source changed: {name}")
    records = [json.loads(x) for x in (source / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    if len(records) != 156 or any(r["provenance"] != provenance for r in records):
        raise RuntimeError("Record count/provenance drift")
    primary = [r for r in records if r["phase"] == "primary"]
    repeat_records = [r for r in records if r["phase"] == "repeatability"]
    if len(primary) != 78 or len(repeat_records) != 78:
        raise RuntimeError("Primary/repeat partition drift")
    modes = tuple(MODE_BY_ALPHA[a] for a in ALPHAS)
    arms = {mode: {r["case_id"]: r for r in primary if r["reference_mode"] == mode} for mode in modes}
    baseline = arms[MODE_BY_ALPHA[0.0]]
    midpoint = MODE_BY_ALPHA[0.5]
    candidate = arms[midpoint]
    if not all(len(arm) == 26 and set(arm) == set(baseline) for arm in arms.values()):
        raise RuntimeError("Case coverage drift")
    task_losses = [k for k in baseline if baseline[k]["task_success"] and not candidate[k]["task_success"]]
    physical_losses = [k for k in baseline if baseline[k]["physical_success"] and not candidate[k]["physical_success"]]
    primitives = [k for k in baseline if baseline[k]["group"] == "primitive"]
    primitive_identity = {mode: {k: canonical_alignment(arms[mode][k]) == canonical_alignment(baseline[k])
                                 for k in primitives} for mode in modes}
    sequences = {}
    for key, anchor in baseline.items():
        if anchor["group"] != "sequence":
            continue
        entry = {}
        for mode in modes:
            r = arms[mode][key]
            n, an = r["nodes"][-1], anchor["nodes"][-1]
            entry[mode] = {
                "alpha": r["heading_alignment_alpha"], "task_success": r["task_success"],
                "physical_success": r["physical_success"], "failure_taxonomy": r["failure_taxonomy"],
                "ideal_lateral_m": n["ideal_path_lateral_error_m"],
                "ideal_heading_deg": n["ideal_path_heading_error_deg"],
                "endpoint_error_m": r["ideal_endpoint_error_m"], "simulation_time_s": r["total_sim_time_s"],
                "lateral_absolute_reduction_vs_actual_percent": reduction(an["ideal_path_lateral_error_m"], n["ideal_path_lateral_error_m"]),
                "heading_absolute_reduction_vs_actual_percent": reduction(an["ideal_path_heading_error_deg"], n["ideal_path_heading_error_deg"]),
                "endpoint_reduction_vs_actual_percent": reduction(anchor["ideal_endpoint_error_m"], r["ideal_endpoint_error_m"]),
                "local_walks": [{"node_index": i, "target_m": v["parameters"]["target_distance_m"],
                                 "local_lateral_m": v["lateral_drift_m"], "local_heading_deg": v["heading_error_deg"],
                                 "task_success": v["task_success"], "violations": v["violations"],
                                 "envelope": v["envelope"], "transition_metrics": v["transition_metrics"]}
                                for i, v in enumerate(r["nodes"]) if v["skill"] == "walk_forward"]}
        sequences[key] = entry
    global_gain = all(abs(v[midpoint][field]) < abs(v[MODE_BY_ALPHA[0.0]][field])
                      for v in sequences.values() for field in ("ideal_lateral_m", "ideal_heading_deg"))
    repeat = len(completion["repeatability_identity"]) == 78 and all(x["passed"] for x in completion["repeatability_identity"])
    historical = len(completion["anchor_identity"]) == 104 and all(x["passed"] for x in completion["anchor_identity"])
    primitives_ok = len(primitives) == 8 and all(all(v.values()) for v in primitive_identity.values())
    gate = global_gain and not task_losses and not physical_losses and repeat and historical and primitives_ok
    verdict = ("MIDPOINT_GLOBAL_GAIN_WITH_RESTORED_TASK_RELIABILITY" if gate else
               "MIDPOINT_GLOBAL_GAIN_WITH_LOCAL_TASK_REGRESSION" if global_gain and task_losses else
               "MIDPOINT_REFERENCE_NOT_CLEAN")
    decision = {
        "verdict": verdict, "midpoint_training_gate": "PASS" if gate else "FAIL", "candidate": midpoint,
        "fixed_alphas": list(ALPHAS), "no_alpha_search": True, "gate_inherited_without_change": True,
        "training_hypothesis_gate": protocol["training_hypothesis_gate"], "midpoint_both_sequence_global_gain": global_gain,
        "midpoint_task_regression_ids": task_losses, "midpoint_physical_regression_ids": physical_losses,
        "primitive_exact_identity": primitive_identity, "historical_endpoints_exact": historical, "repeatability_exact": repeat,
        "primary_cases_per_arm": 26, "repeatability_runs_separate": 78, "sequence_metrics": sequences,
        "PPO_training_started": False, "envelopes_labels_or_scoring_changed": False,
        "inference_scope": "Deterministic reference mechanism on previously seen cases; no optimal alpha or blind generalization claim",
        "next_gate": "Eligible for separately authorized same-frame-controlled PPO experiment" if gate else "PPO blocked; retain result without alpha scan",
        "language_Runtime_gate": "BLOCKED_UNCHANGED", "Jev_or_MultiSwarm": False,
        "provenance": provenance, "history": history}
    write_new(directory / "decision.json", decision)
    target = directory / "evidence"
    target.mkdir(exist_ok=False)
    inventory = {}
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        exported = target / path.relative_to(source)
        compressed = path.suffix == ".jsonl" and path.stat().st_size > 200000
        if compressed:
            exported = exported.with_suffix(exported.suffix + ".gz")
        exported.parent.mkdir(parents=True, exist_ok=True)
        if compressed:
            with exported.open("xb") as out:
                with gzip.GzipFile(fileobj=out, mode="wb", filename="", mtime=0) as stream:
                    stream.write(path.read_bytes())
            if gzip.decompress(exported.read_bytes()) != path.read_bytes():
                raise RuntimeError("Export loss")
        else:
            shutil.copyfile(path, exported)
        inventory[exported.relative_to(root).as_posix()] = {
            "raw_path": path.relative_to(root).as_posix(), "raw": receipt(path), "exported": receipt(exported),
            "encoding": "gzip" if compressed else "identity"}
    write_new(directory / "evidence_manifest.json", {
        "experiment_id": "heading_alignment_strength_001", "provenance": provenance,
        "inventory": inventory, "items": len(inventory), "primary_runs": 78, "repeatability_runs": 78,
        "raw_artifacts_retained": True, "export_producer": "scripts/export_phase3a_heading.py",
        "export_producer_sha256": receipt(Path(__file__).resolve())["sha256"],
        "publication_binding": "Postprocessing source and manifest bound by final publication commit; acquisition commit separately pinned"})
    print(json.dumps({"verdict": verdict, "midpoint_gate": decision["midpoint_training_gate"],
                      "task_regressions": task_losses, "exported_files": len(inventory),
                      "bytes_exported": sum(v["exported"]["bytes"] for v in inventory.values())}))
