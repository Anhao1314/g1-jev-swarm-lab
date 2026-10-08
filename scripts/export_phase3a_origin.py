"""Preserve the origin experiment and apply the unchanged candidate gate."""
from __future__ import annotations
import gzip
import hashlib
import json
from pathlib import Path
import shutil

from g1swarm.paths import repo_root
from g1swarm.origin_ablation.experiment import MODES,HYBRID,verify_history
from g1swarm.reference_ablation.experiment import canonical_physics,write_new


def receipt(path):
    data=path.read_bytes()
    return {"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)}


def reduction(a,b):
    return (abs(a)-abs(b))/abs(a)*100 if a else None


if __name__ == "__main__":
    root=repo_root();source=root/"artifacts/origin_selection_ablation_001"
    directory=root/"experiments/phase3a/origin_selection_ablation_001"
    completion=json.loads((source/"completion.json").read_text(encoding="utf-8"))
    if completion["status"]!="COMPLETE" or completion["records"]!=156:
        raise RuntimeError("Incomplete origin campaign")
    history=verify_history()
    records=[json.loads(x) for x in (source/"results.jsonl").read_text(encoding="utf-8").splitlines()]
    primary=[r for r in records if r["phase"]=="primary"]
    arms={mode:{r["case_id"]:r for r in primary if r["reference_mode"]==mode} for mode in MODES}
    baseline=arms["actual_node_start"];candidate=arms[HYBRID]
    assert all(len(arm)==26 and set(arm)==set(baseline) for arm in arms.values())
    task_losses=[k for k in baseline if baseline[k]["task_success"] and not candidate[k]["task_success"]]
    physical_losses=[k for k in baseline if baseline[k]["physical_success"] and not candidate[k]["physical_success"]]
    primitives=[k for k in baseline if baseline[k]["group"]=="primitive"]
    primitive_identity={mode:{k:canonical_physics(arms[mode][k])==canonical_physics(baseline[k]) for k in primitives} for mode in MODES}
    sequences={}
    for key in baseline:
        if baseline[key]["group"]!="sequence":continue
        entry={}
        for mode in MODES:
            r=arms[mode][key];n=r["nodes"][-1];a=baseline[key];an=a["nodes"][-1]
            entry[mode]={"task_success":r["task_success"],"physical_success":r["physical_success"],
                "ideal_lateral_m":n["ideal_path_lateral_error_m"],"ideal_heading_deg":n["ideal_path_heading_error_deg"],
                "endpoint_error_m":r["ideal_endpoint_error_m"],"simulation_time_s":r["total_sim_time_s"],
                "lateral_absolute_reduction_vs_actual_percent":reduction(an["ideal_path_lateral_error_m"],n["ideal_path_lateral_error_m"]),
                "heading_absolute_reduction_vs_actual_percent":reduction(an["ideal_path_heading_error_deg"],n["ideal_path_heading_error_deg"]),
                "endpoint_reduction_vs_actual_percent":reduction(a["ideal_endpoint_error_m"],r["ideal_endpoint_error_m"]),
                "local_walks":[{"node_index":i,"target_m":v["parameters"]["target_distance_m"],
                                "local_lateral_m":v["lateral_drift_m"],"local_heading_deg":v["heading_error_deg"],
                                "task_success":v["task_success"],"violations":v["violations"],"envelope":v["envelope"]}
                               for i,v in enumerate(r["nodes"]) if v["skill"]=="walk_forward"]}
        sequences[key]=entry
    global_gain=all(abs(v[HYBRID][field])<abs(v["actual_node_start"][field]) for v in sequences.values() for field in ["ideal_lateral_m","ideal_heading_deg"])
    repeat=all(x["passed"] for x in completion["repeatability_identity"])
    historical=all(x["passed"] for x in completion["historical_arms_identity"])
    primitives_ok=all(all(v.values()) for v in primitive_identity.values())
    gate=global_gain and not task_losses and not physical_losses and repeat and historical and primitives_ok
    verdict="HYBRID_GLOBAL_GAIN_WITH_LOCAL_TASK_REGRESSION" if global_gain and task_losses else (
        "HYBRID_REFERENCE_SUPPORTED" if gate else "HYBRID_REFERENCE_NOT_CLEAN")
    decision={"verdict":verdict,"hybrid_training_gate":"PASS" if gate else "FAIL",
        "gate_inherited_without_change":True,"candidate":HYBRID,"hybrid_both_sequence_global_gain":global_gain,
        "hybrid_task_regression_ids":task_losses,"hybrid_physical_regression_ids":physical_losses,
        "primitive_exact_identity":primitive_identity,"historical_arms_exact":historical,"repeatability_exact":repeat,
        "primary_cases_per_arm":26,"repeatability_runs_separate":78,"sequence_metrics":sequences,
        "PPO_training_started":False,"envelopes_labels_or_scoring_changed":False,
        "inference_scope":"Origin effect conditional on ideal heading; heading effect at actual origin; no full2x2 or unseen-generalization claim",
        "language_Runtime_gate":"BLOCKED_UNCHANGED","Jev_or_MultiSwarm":False,"provenance":completion["provenance"],"history":history}
    write_new(directory/"decision.json",decision)
    target=directory/"evidence";target.mkdir(exist_ok=False);inventory={}
    for path in sorted(source.rglob("*")):
        if not path.is_file():continue
        exported=target/path.relative_to(source);compressed=path.suffix==".jsonl" and path.stat().st_size>200000
        if compressed:exported=exported.with_suffix(exported.suffix+".gz")
        exported.parent.mkdir(parents=True,exist_ok=True)
        if compressed:
            with exported.open("xb") as out:
                with gzip.GzipFile(fileobj=out,mode="wb",filename="",mtime=0) as stream:stream.write(path.read_bytes())
            assert gzip.decompress(exported.read_bytes())==path.read_bytes()
        else:shutil.copyfile(path,exported)
        inventory[exported.relative_to(root).as_posix()]={"raw_path":path.relative_to(root).as_posix(),
            "raw":receipt(path),"exported":receipt(exported),"encoding":"gzip" if compressed else "identity"}
    write_new(directory/"evidence_manifest.json",{"experiment_id":"origin_selection_ablation_001",
        "provenance":completion["provenance"],"inventory":inventory,"items":len(inventory),
        "primary_runs":78,"repeatability_runs":78,"raw_artifacts_retained":True,
        "export_producer":"scripts/export_phase3a_origin.py","export_producer_sha256":receipt(Path(__file__).resolve())["sha256"],
        "publication_binding":"Postprocessing source and manifest bound by final publication commit; acquisition commit separately pinned"})
    print(json.dumps({"verdict":verdict,"hybrid_gate":decision["hybrid_training_gate"],"hybrid_task_regressions":task_losses,
                      "exported_files":len(inventory),"bytes_exported":sum(v["exported"]["bytes"] for v in inventory.values())}))
