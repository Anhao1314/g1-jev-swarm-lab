"""Byte-exact additive Pilot bundle; old dependency bytes stay in Git."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import package_source_authority as helper

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = "experiments/phase2/source_authority_cross_model_001"
MANIFEST = f"{EXPERIMENT}/content_manifest.json"
EXCLUDED = {MANIFEST, f"{EXPERIMENT}/publication_validation.json"}
ARCHIVE = "artifacts/source-authority-cross-model/source-authority-cross-model.zip"


def paths(root: Path) -> list[str]:
    result = []
    for folder in (root / EXPERIMENT, root / "scripts", root / "tests"):
        for path in folder.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            name = path.relative_to(root).as_posix()
            if name in EXCLUDED or path.suffix in {".pyc", ".zip", ".tmp"} or ".pending." in name:
                continue
            if (name.startswith(EXPERIMENT + "/") or "cross_model_certificate" in path.name
                    or name in {"scripts/.gitattributes", "tests/.gitattributes"}):
                result.append(name)
    return sorted(result)


def make_manifest(root: Path) -> dict:
    records = []
    for name in paths(root):
        path = root / helper.safe_path(name)
        if path.is_symlink():
            raise helper.PackagingError("symlink in Pilot package")
        raw = path.read_bytes()
        records.append({"path": name, "bytes": len(raw), "sha256": helper.sha256(raw)})
    return {"schema": "cross_model_source_authority_content_manifest_v1",
            "byte_policy": "raw bytes, no Unicode/newline/JSON normalization",
            "dependency_policy": "external immutable starting Git snapshot pinned in inputs.json",
            "manifest_self_hash": "excluded",
            "publication_validation": "excluded to avoid circular receipt hashes",
            "files": records}


def verify(root: Path, manifest: dict) -> dict[str, bytes]:
    if manifest.get("schema") != "cross_model_source_authority_content_manifest_v1":
        raise helper.PackagingError("unsupported Pilot manifest")
    content = {}
    for record in manifest["files"]:
        name = helper.safe_path(record["path"])
        if name in EXCLUDED or name in content:
            raise helper.PackagingError("circular/duplicate Pilot manifest member")
        path = root / name
        if path.is_symlink():
            raise helper.PackagingError("symlink in Pilot package")
        raw = path.read_bytes()
        if len(raw) != record["bytes"] or helper.sha256(raw) != record["sha256"]:
            raise helper.PackagingError("Pilot raw-byte mismatch: " + name)
        content[name] = raw
    return content


def freeze(root: Path, archive: Path) -> dict:
    manifest = make_manifest(root)
    helper.byte_attributes_check(root, [*paths(root), MANIFEST])
    manifest_raw = helper.json_bytes(manifest)
    target = root / MANIFEST
    if target.exists() and target.read_bytes() != manifest_raw:
        raise helper.PackagingError("Pilot manifest already frozen; refusing replacement")
    target.write_bytes(manifest_raw)
    content = verify(root, manifest)
    content[MANIFEST] = manifest_raw
    raw = helper.deterministic_zip(content)
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists() and archive.read_bytes() != raw:
        raise helper.PackagingError("Pilot archive already frozen; refusing replacement")
    archive.write_bytes(raw)
    receipt = {"schema": "cross_model_source_authority_archive_receipt_v1",
               "archive_sha256": helper.sha256(raw), "archive_bytes": len(raw),
               "content_manifest_sha256": helper.sha256(manifest_raw),
               "members": len(content), "provider_calls": 0, "runtime_calls": 0}
    archive.with_suffix(".receipt.json").write_bytes(helper.json_bytes(receipt))
    return receipt


def check(root: Path, archive: Path) -> dict:
    manifest_raw = (root / MANIFEST).read_bytes()
    manifest = json.loads(manifest_raw)
    helper.byte_attributes_check(root, [*(x["path"] for x in manifest["files"]), MANIFEST])
    content = verify(root, manifest)
    content[MANIFEST] = manifest_raw
    raw = helper.deterministic_zip(content)
    if archive.read_bytes() != raw:
        raise helper.PackagingError("Pilot deterministic archive byte mismatch")
    receipt = json.loads(archive.with_suffix(".receipt.json").read_bytes())
    expected = {"schema": "cross_model_source_authority_archive_receipt_v1",
                "archive_sha256": helper.sha256(raw), "archive_bytes": len(raw),
                "content_manifest_sha256": helper.sha256(manifest_raw),
                "members": len(content), "provider_calls": 0, "runtime_calls": 0}
    if receipt != expected:
        raise helper.PackagingError("Pilot external archive receipt mismatch")
    return {"status": "PASS", "raw_byte_members_verified": len(content),
            "deterministic_archive_rebuild_equal": True, **expected}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["freeze", "check"])
    parser.add_argument("--archive", type=Path, default=ROOT / ARCHIVE)
    args = parser.parse_args()
    print(json.dumps((freeze if args.stage == "freeze" else check)(ROOT, args.archive)))


if __name__ == "__main__":
    main()
