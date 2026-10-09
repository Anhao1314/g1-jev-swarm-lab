"""Write-once execution byte freeze; metadata/file reads only, never physics.

Commit executable code first. A later receipt/documentation commit contains this
manifest, so neither the manifest nor its owning commit is self-hashed. The exact
final checkout HEAD is independently supplied with future Owner authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import readiness

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def git_blob(head: str, name: str) -> bytes:
    return subprocess.check_output(["git", "show", head + ":" + name], cwd=ROOT)


def freeze(code_head: str) -> dict:
    readiness.clean_process()
    if len(code_head) != 40 or any(c not in "0123456789abcdef" for c in code_head):
        raise ValueError("Exact committed execution code HEAD required")
    if (HERE / "source_manifest.json").exists():
        raise FileExistsError("Source freeze is write-once; preserve the original")
    if subprocess.run(["git", "merge-base", "--is-ancestor", code_head, "HEAD"],
                      cwd=ROOT, check=False).returncode != 0:
        raise ValueError("Execution code HEAD is not in checkout history")
    environment = readiness.check_target(require_manifest=False)
    names = readiness.expected_source_paths(ROOT, HERE)
    tracked = set(subprocess.check_output(["git", "ls-tree", "-r", "--name-only", code_head],
                                         cwd=ROOT, text=True).splitlines())
    assets = {row["path"]: row["sha256"] for row in readiness.official_rows(ROOT)}
    files, domains = {}, {}
    for name in sorted(names):
        path = readiness.contained(ROOT, name)
        raw = path.read_bytes()
        files[name] = hashlib.sha256(raw).hexdigest()
        if name in tracked:
            original = git_blob(code_head, name)
            if raw == original:
                domain = "GIT_RAW_BYTES_EQUAL"
            elif raw == original.replace(b"\n", b"\r\n"):
                domain = "GIT_LF_TO_WINDOWS_CRLF_BYTES"
            else:
                raise ValueError("Uncommitted/source byte drift: " + name)
            domains[name] = {"domain": domain,
                             "git_blob_sha256": hashlib.sha256(original).hexdigest()}
        elif name in assets and files[name] == assets[name]:
            domains[name] = {"domain": "UNVERSIONED_OFFICIAL_ASSET_BYTES"}
        else:
            raise ValueError("Source not committed or asset not officially bound: " + name)
    code_files = sorted(name for name in names if name.startswith(
        "experiments/m2/unseen_halt_hold_readiness_001/") and name.endswith(".py"))
    if any(domains[name]["domain"] != "GIT_RAW_BYTES_EQUAL" for name in code_files):
        raise ValueError("New execution code must be exact committed LF bytes")
    manifest = {
        "status": "EXECUTION_BYTES_FROZEN_NO_PHYSICS_AUTHORITY",
        "physics_authorized": False,
        "design_head": readiness.DESIGN_HEAD,
        "execution_code_head": code_head,
        "execution_code_files": code_files,
        "design_protocol_sha256": readiness.digest(ROOT / readiness.DESIGN / "protocol.json"),
        "dependencies_sha256": readiness.digest(HERE / "dependencies.json"),
        "official_assets_receipt_sha256": readiness.digest(HERE / "assets_receipt.json"),
        "files": files,
        "byte_domains": domains,
        "domain_counts": {label: sum(d["domain"] == label for d in domains.values())
                          for label in ("GIT_RAW_BYTES_EQUAL", "GIT_LF_TO_WINDOWS_CRLF_BYTES",
                                        "UNVERSIONED_OFFICIAL_ASSET_BYTES")},
        "source_count": len(files),
        "dependency_count": environment["dependency_count"],
        "official_asset_count": environment["official_asset_count"],
        "meaning": "New execution closure; old 78 Git/85 CRLF/91 official receipts remain historical and unchanged.",
        "exact_final_execution_head": "Supplied externally and checked against live Git HEAD before any future worker; not self-hashed into its commit.",
    }
    with (HERE / "source_manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    readiness.clean_process()
    return {"status": "SOURCE_FREEZE_WRITTEN_NO_PHYSICS", "source_count": len(files),
            "source_manifest_sha256": readiness.digest(HERE / "source_manifest.json"),
            "execution_code_head": code_head, "domain_counts": manifest["domain_counts"],
            "physics_steps": 0, "policy_inferences": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-code-head", required=True)
    print(json.dumps(freeze(parser.parse_args().execution_code_head), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
