"""Create new Phase3A baseline/case manifests without touching old artifacts."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from g1swarm.transition_learning.cases import TRAIN_CASES, EVAL_CASES, PRIMITIVE_CASES, SEQUENCE_CASES


def receipt(path):
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main():
    directory = ROOT / "experiments/phase3a/transition_learning_001"
    protected = []
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    prefixes = ("src/g1swarm/", "configs/robot/", "configs/experiments/g1_", "experiments/baselines/")
    for name in tracked:
        if name.startswith(prefixes) and not name.startswith("src/g1swarm/transition_learning/"):
            protected.append(ROOT / name)
    assets = ROOT / "third_party/unitree_rl_gym"
    protected.extend(p for p in (assets / "resources/robots/g1_description").rglob("*") if p.is_file())
    protected.append(assets / "deploy/pre_train/g1/motion.pt")
    manifest = {"experiment_id": "transition_learning_001", "baseline_source_anchor": "624c8024c6587f7c502b1cc87b2b27797493af03",
                "scope": "Existing sources/configs/historical baseline evidence plus exact official assets; no learned-policy weights included",
                "files": {p.relative_to(ROOT).as_posix(): receipt(p) for p in sorted(set(protected))}}
    with (directory / "baseline_freeze.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with (directory / "case_manifest.json").open("x", encoding="utf-8") as handle:
        json.dump({"train": TRAIN_CASES, "evaluation": EVAL_CASES, "primitive": PRIMITIVE_CASES,
                   "sequence": SEQUENCE_CASES, "nominal_seed_is_not_state_randomization": True}, handle, indent=2)
        handle.write("\n")
    protocol_path = directory / "protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["frozen"] = True
    protocol["baseline_freeze_sha256"] = receipt(directory / "baseline_freeze.json")["sha256"]
    protocol["case_manifest_sha256"] = receipt(directory / "case_manifest.json")["sha256"]
    protocol_path.write_text(json.dumps(protocol, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"baseline_files": len(manifest["files"]), "case_counts": [len(x) for x in [TRAIN_CASES,EVAL_CASES,PRIMITIVE_CASES,SEQUENCE_CASES]],
                      "protocol_sha256": receipt(protocol_path)["sha256"]}))


if __name__ == "__main__":
    main()
