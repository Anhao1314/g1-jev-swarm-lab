"""One-time new experiment freeze: bind old evidence without rewriting it."""
import hashlib
import json
from pathlib import Path
import subprocess

from g1swarm.paths import repo_root


if __name__ == "__main__":
    root = repo_root()
    destination = root/"experiments/phase3a/reference_frame_ablation_001"
    tracked = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).splitlines()
    prefixes = ("experiments/phase3a/transition_learning_001/", "src/g1swarm/transition_learning/",
                "scripts/run_phase3a.py", "scripts/freeze_phase3a.py", "scripts/export_phase3a.py",
                "tests/test_transition_learning")
    files = {}
    for name in tracked:
        if name.startswith(prefixes):
            data = (root/name).read_bytes()
            files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    path = destination/"history_freeze.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump({"source_pilot_commit": "1088c725ed12842df9f54116ac1921be71f2a633", "files": files}, stream, indent=2, sort_keys=True)
        stream.write("\n")
    protocol_path = destination/"protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol.update(frozen=True, history_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with protocol_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(protocol, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"historical_files": len(files), "protocol_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest()}))
