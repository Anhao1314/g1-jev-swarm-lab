"""Preserve the completed pilot, including all checkpoints and negative records.

Large JSONL logs are losslessly gzipped with original and exported hashes.
This is an evidence export, not a new evaluator or a checkpoint selection tool.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from g1swarm.paths import repo_root
from g1swarm.transition_learning.analysis import summarize_results, compare_results
from g1swarm.transition_learning.training import verify_baseline_freeze, verify_case_manifest


def digest(path):
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def write(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def main():
    root = repo_root()
    source = root / "artifacts/transition_learning_001"
    destination = root / "experiments/phase3a/transition_learning_001"
    protocol = json.loads((destination / "protocol.json").read_text(encoding="utf-8"))
    verify_baseline_freeze()
    verify_case_manifest(protocol)
    statuses = {}
    for campaign in ["baseline", "smoke", "train-seed11", "train-seed29", "evaluation"]:
        summary = "training_summary.json" if campaign in ["smoke", "train-seed11", "train-seed29"] else "evaluation_summary.json"
        statuses[campaign] = json.loads((source / campaign / summary).read_text(encoding="utf-8"))["status"]
    if not all(x == "COMPLETE" for x in statuses.values()):
        raise RuntimeError(f"Incomplete campaign: {statuses}")
    target = destination / "evidence"
    target.mkdir(exist_ok=False)
    inventory = {}
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        exported = target / relative
        compressed = path.suffix == ".jsonl" and path.stat().st_size > 200000
        if compressed:
            exported = exported.with_suffix(exported.suffix+".gz")
        exported.parent.mkdir(parents=True, exist_ok=True)
        if compressed:
            with path.open("rb") as inp, exported.open("xb") as out:
                with gzip.GzipFile(fileobj=out, mode="wb", filename="", mtime=0) as encoded:
                    shutil.copyfileobj(inp, encoded)
            if gzip.decompress(exported.read_bytes()) != path.read_bytes():
                raise RuntimeError(f"Compression changed evidence: {relative}")
        else:
            shutil.copyfile(path, exported)
        inventory[exported.relative_to(root).as_posix()] = {
            "raw_artifact_path": path.relative_to(root).as_posix(), "raw": digest(path),
            "exported": digest(exported), "encoding": "gzip" if compressed else "identity"}
    records = []
    for campaign in ["baseline", "evaluation"]:
        records.extend(json.loads(row) for row in (source / campaign / "results.jsonl").read_text(encoding="utf-8").splitlines())
    expected_labels = {"frozen_baseline", "deterministic_correction", "train-seed11", "train-seed29"}
    labels = {record["treatment_label"] for record in records}
    if labels != expected_labels or len(records) != 104:
        raise RuntimeError("Frozen paired evaluation membership differs")
    write(destination / "summary.json", summarize_results(records))
    write(destination / "comparison.json", compare_results(records))
    write(destination / "evidence_manifest.json", {
        "schema_version": "phase3a-pilot-evidence-v1", "campaign_statuses": statuses,
        "protocol": digest(destination / "protocol.json"),
        "cases": digest(destination / "case_manifest.json"),
        "baseline_freeze": digest(destination / "baseline_freeze.json"),
        "base_policy_sha256": protocol["base_policy_sha256"],
        "acquisition_freeze_commit": "3b655ba", "acquisition_after_attribute_only_commit": "4f2ce5f",
        "export_code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "inventory": inventory, "inventory_count": len(inventory),
        "evaluation_runs": len(records), "checkpoint_selection": protocol["checkpoint_selection"],
        "original_artifacts_retained": True, "all_checkpoint_files_retained": True,
        "language_runtime_gate": "BLOCKED_UNCHANGED", "Jev_or_MultiSwarm_started": False,
        "scientific_configuration_changes_after_acquisition": False,
    })
    print(json.dumps({"exported_files": len(inventory), "evaluation_runs": len(records),
                      "bytes_exported": sum(x["exported"]["bytes"] for x in inventory.values())}))


if __name__ == "__main__":
    main()
