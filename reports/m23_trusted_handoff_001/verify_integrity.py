"""Read-only offline byte/branch audit; snapshot is explicit and never refreshed."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = "e9db7a9c25eaf34ea248b34c23c67543c16294c1"
SOURCE = "a2325d393c3ffc46eaf7252122b61179ea0e35cb"


def git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def snapshot():
    target = HERE / "history_before.json"
    if target.exists():
        raise SystemExit("Refusing to overwrite frozen history snapshot")
    paths = git("ls-tree", "-r", "--name-only", BASE).decode().splitlines()
    missing = [p for p in paths if not (ROOT / p).is_file()]
    if missing:
        raise SystemExit("Baseline tracked files missing: " + repr(missing))
    value = {
        "base": BASE, "source_commit": SOURCE,
        "source_tree": git("rev-parse", SOURCE + "^{tree}").decode().strip(),
        "working_bytes_sha256": {p: sha(ROOT / p) for p in paths},
        "baseline_git_blobs": git("ls-tree", "-r", BASE).decode().splitlines(),
        "original_workspace": "D:/work/g1-jev-swarm-lab",
        "original_workspace_status": git("status", "--porcelain=v1", cwd="D:/work/g1-jev-swarm-lab").decode(),
        "source_workspace_status": git("status", "--porcelain=v1", cwd="D:/work/g1-source-authority").decode(),
        "protocol_sha256": sha(HERE / "PROTOCOL.md"),
    }
    save(target, value)
    print(json.dumps({"snapshot": "FROZEN", "baseline_files": len(paths),
                      "protocol_sha256": value["protocol_sha256"]}))


def check():
    value = json.loads((HERE / "history_before.json").read_text(encoding="utf-8"))
    mismatches = [p for p, digest in value["working_bytes_sha256"].items()
                  if not (ROOT / p).is_file() or sha(ROOT / p) != digest]
    original_unchanged = git("status", "--porcelain=v1", cwd=value["original_workspace"]).decode() == value["original_workspace_status"]
    source_unchanged = git("status", "--porcelain=v1", cwd="D:/work/g1-source-authority").decode() == value["source_workspace_status"]
    tree_unchanged = git("rev-parse", SOURCE + "^{tree}").decode().strip() == value["source_tree"]
    protocol_unchanged = sha(HERE / "PROTOCOL.md") == value["protocol_sha256"]
    diff = git("diff", BASE, "--name-only", "--diff-filter=MDRT").decode().splitlines()
    receipt = {"status": "PASS" if not mismatches and original_unchanged and source_unchanged
               and tree_unchanged and protocol_unchanged and not diff else "FAIL",
               "baseline_files_verified": len(value["working_bytes_sha256"]),
               "changed_baseline_working_bytes": mismatches,
               "modified_deleted_renamed_baseline_paths": diff,
               "original_workspace_status_unchanged": original_unchanged,
               "source_workspace_status_unchanged": source_unchanged,
               "source_tree_unchanged": tree_unchanged,
               "protocol_unchanged": protocol_unchanged,
               "new_physics": 0, "provider_calls": 0}
    save(HERE / "integrity.json", receipt)
    print(json.dumps(receipt))
    if receipt["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["snapshot", "check"])
    args = parser.parse_args()
    snapshot() if args.mode == "snapshot" else check()
