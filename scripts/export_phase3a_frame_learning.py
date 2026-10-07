"""Losslessly retain same-frame learning evidence, including negative checkpoints."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import shutil

from g1swarm.frame_learning.campaign import DIRECTORY, ARTIFACT, verify_freeze, verify_acquisition_sources
from g1swarm.frame_learning.analysis import analyze
from g1swarm.paths import repo_root
from g1swarm.reference_ablation.experiment import sha, write_new


def receipt(path):
    return {"sha256": sha(path), "bytes": path.stat().st_size}


if __name__ == "__main__":
    root = repo_root()
    source, directory = root / ARTIFACT, root / DIRECTORY
    if (source / "completion.json").is_file():
        status = json.loads((source / "completion.json").read_text(encoding="utf-8"))
    elif (source / "failure.json").is_file():
        status = json.loads((source / "failure.json").read_text(encoding="utf-8"))
    else:
        raise RuntimeError("Campaign still running or no terminal evidence")
    p = status["provenance"]
    history = verify_freeze()
    verify_acquisition_sources(p)
    if history["protocol_sha256"] != p["protocol_sha256"]:
        raise RuntimeError("Frozen protocol drift")
    records_path = source / "evaluation/results.jsonl"
    records = [json.loads(x) for x in records_path.read_text(encoding="utf-8").splitlines()] if records_path.exists() else []
    if any(r["provenance"] != p for r in records):
        raise RuntimeError("Evaluation provenance drift")
    primary = [r for r in records if r["phase"] == "primary"]
    if status["status"] == "COMPLETE":
        if len(primary) != 252 or len(records) != 288:
            raise RuntimeError("Evaluation coverage drift")
        analysis = analyze(primary)
    else:
        analysis = {"status": "INCOMPLETE", "verdict": "TRAINING_OR_INTEGRITY_FAILURE_RETAINED",
                    "primary_records": len(primary), "scientific_comparison_complete": False}
    write_new(directory / "analysis.json", {**analysis, "provenance": p})
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
            with path.open("rb") as inp, exported.open("xb") as out:
                with gzip.GzipFile(fileobj=out, mode="wb", filename="", mtime=0) as stream:
                    shutil.copyfileobj(inp, stream)
            if gzip.decompress(exported.read_bytes()) != path.read_bytes():
                raise RuntimeError("Lossy evidence export")
        else:
            shutil.copyfile(path, exported)
        inventory[exported.relative_to(root).as_posix()] = {
            "raw_path": path.relative_to(root).as_posix(), "raw": receipt(path),
            "exported": receipt(exported), "encoding": "gzip" if compressed else "identity"}
    write_new(directory / "evidence_manifest.json", {
        "experiment_id": "frame_residual_learning_001", "status": status["status"], "provenance": p,
        "inventory": inventory, "items": len(inventory), "primary_runs": len(primary),
        "repeatability_runs_separate": len(records) - len(primary), "history": history,
        "checkpoints_retained": [n for n in inventory if n.endswith(".zip")],
        "no_evaluation_checkpoint_selection": True, "all_failed_outcomes_retained": True,
        "export_producer_sha256": sha(Path(__file__).resolve()), "raw_artifacts_retained": True,
        "publication_binding": "Final Git commit binds postprocessing/audits/report; separate acquisition commit pins scientific sources"})
    print(json.dumps({"status": status["status"], "exported_files": len(inventory),
                      "checkpoint_files": sum(n.endswith(".zip") for n in inventory),
                      "bytes_exported": sum(v["exported"]["bytes"] for v in inventory.values())}))
