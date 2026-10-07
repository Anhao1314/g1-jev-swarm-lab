"""Additive raw-byte DG-serial package with externally pinned old evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import package_source_authority as helper

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = "experiments/phase2/source_authority_serial_001"
MANIFEST = f"{EXPERIMENT}/content_manifest.json"
EXCLUDED = {MANIFEST, f"{EXPERIMENT}/publication_validation.json"}
ARCHIVE = "artifacts/source-authority-serial/source-authority-serial.zip"
SCHEMA = "serial_certificate_content_manifest_v1"


def paths(root: Path) -> list[str]:
    result = []
    for name in (EXPERIMENT, "scripts/serial_certificate_001", "tests/serial_certificate_001"):
        for path in (root / name).rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root).as_posix()
            if relative in EXCLUDED or path.suffix in {".zip", ".pyc", ".tmp"} or ".pending." in relative:
                continue
            result.append(relative)
    return sorted(result)


def make_manifest(root: Path) -> dict:
    records = []
    for name in paths(root):
        path = root / helper.safe_path(name)
        if path.is_symlink():
            raise helper.PackagingError("serial package symlink")
        raw = path.read_bytes()
        records.append({"path": name, "bytes": len(raw), "sha256": helper.sha256(raw)})
    return {"schema": SCHEMA, "byte_policy": "raw bytes; no normalization",
            "external_dependencies": "starting Git tree and prior raw-byte registry in inputs.json",
            "self_hash": "excluded", "publication_validation": "excluded for noncircular receipt",
            "files": records}


def verify(root: Path, manifest: dict) -> dict[str, bytes]:
    if manifest.get("schema") != SCHEMA:
        raise helper.PackagingError("unsupported serial manifest")
    content = {}
    for record in manifest["files"]:
        name = helper.safe_path(record["path"])
        if name in EXCLUDED or name in content:
            raise helper.PackagingError("circular/duplicate serial member")
        path = root / name
        if path.is_symlink():
            raise helper.PackagingError("serial package symlink")
        raw = path.read_bytes()
        if len(raw) != record["bytes"] or helper.sha256(raw) != record["sha256"]:
            raise helper.PackagingError("serial raw-byte mismatch: " + name)
        content[name] = raw
    return content


def receipt(raw: bytes, manifest_raw: bytes, members: int) -> dict:
    return {"schema": "serial_certificate_archive_receipt_v1", "archive_sha256": helper.sha256(raw),
            "archive_bytes": len(raw), "content_manifest_sha256": helper.sha256(manifest_raw),
            "members": members, "provider_calls": 0, "runtime_calls": 0}


def freeze(root: Path, archive: Path) -> dict:
    manifest = make_manifest(root)
    helper.byte_attributes_check(root, [*paths(root), MANIFEST])
    manifest_raw = helper.json_bytes(manifest)
    target = root / MANIFEST
    if target.exists() and target.read_bytes() != manifest_raw:
        raise helper.PackagingError("serial manifest frozen; refusing replacement")
    target.write_bytes(manifest_raw)
    content = verify(root, manifest)
    content[MANIFEST] = manifest_raw
    raw = helper.deterministic_zip(content)
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists() and archive.read_bytes() != raw:
        raise helper.PackagingError("serial archive frozen; refusing replacement")
    archive.write_bytes(raw)
    saved = receipt(raw, manifest_raw, len(content))
    archive.with_suffix(".receipt.json").write_bytes(helper.json_bytes(saved))
    return saved


def check(root: Path, archive: Path) -> dict:
    manifest_raw = (root / MANIFEST).read_bytes()
    manifest = json.loads(manifest_raw)
    helper.byte_attributes_check(root, [*(r["path"] for r in manifest["files"]), MANIFEST])
    content = verify(root, manifest)
    content[MANIFEST] = manifest_raw
    raw = helper.deterministic_zip(content)
    if archive.read_bytes() != raw:
        raise helper.PackagingError("serial archive deterministic byte mismatch")
    saved = receipt(raw, manifest_raw, len(content))
    if json.loads(archive.with_suffix(".receipt.json").read_bytes()) != saved:
        raise helper.PackagingError("serial external receipt mismatch")
    return {"status": "PASS", "verified_root": str(root), "new_raw_byte_members_verified": len(content),
            "deterministic_archive_rebuild_equal": True, **saved}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["freeze", "check"])
    parser.add_argument("--archive", type=Path, default=ROOT / ARCHIVE)
    args = parser.parse_args()
    print(json.dumps((freeze if args.stage == "freeze" else check)(ROOT, args.archive)))


if __name__ == "__main__":
    main()
