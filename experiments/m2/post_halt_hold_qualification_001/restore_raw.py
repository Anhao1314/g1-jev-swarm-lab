"""Losslessly restore the independently archived M2.5A raw campaign; no physics."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def relative_name(name: str) -> str:
    parts = PurePosixPath(name).parts
    if (not name or "\\" in name or ":" in name or name.startswith("/")
            or any(part in ("", ".", "..") for part in name.split("/"))
            or not parts or str(PurePosixPath(name)) != name):
        raise ValueError(f"Unsafe archive path: {name!r}")
    return name


def restore(manifest_path: Path, output: Path) -> dict:
    manifest_path = manifest_path.resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest["files"]
    if not isinstance(files, dict) or len(files) != manifest["raw_file_count"]:
        raise ValueError("Manifest file count mismatch")
    for name, receipt in files.items():
        relative_name(name)
        if not isinstance(receipt["bytes"], int) or receipt["bytes"] < 0:
            raise ValueError("Invalid manifest size")
        if len(receipt["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in receipt["sha256"]):
            raise ValueError("Invalid manifest hash")
    if sum(item["bytes"] for item in files.values()) != manifest["raw_bytes"]:
        raise ValueError("Manifest total bytes mismatch")
    archive_receipt = manifest["archive"]
    archive = manifest_path.parent / relative_name(archive_receipt["path"])
    if archive.stat().st_size != archive_receipt["bytes"] or digest(archive) != archive_receipt["sha256"]:
        raise ValueError("Archive bytes/hash mismatch")
    # Validate the complete central directory before creating any output.
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        names = [relative_name(member.filename) for member in members]
        if len(set(names)) != len(names) or set(names) != set(files):
            raise ValueError("Archive member set mismatch or duplicate")
        for member in members:
            mode = member.external_attr >> 16
            if member.is_dir() or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                raise ValueError("Archive member is not a regular file")
            if member.file_size != files[member.filename]["bytes"]:
                raise ValueError("Archive member size mismatch")
        output = output.absolute()
        output.mkdir(parents=False, exist_ok=False)
        for member in members:
            destination = output.joinpath(*PurePosixPath(member.filename).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation: no overwrite, no extractall, bounded read.
            with bundle.open(member) as source, destination.open("xb") as target:
                value = hashlib.sha256()
                count = 0
                while block := source.read(1024 * 1024):
                    count += len(block)
                    if count > files[member.filename]["bytes"]:
                        raise ValueError("Member exceeded declared size")
                    value.update(block)
                    target.write(block)
            if count != files[member.filename]["bytes"] or value.hexdigest() != files[member.filename]["sha256"]:
                raise ValueError(f"Restored file hash mismatch: {member.filename}")
    return {"status": "RAW_RESTORATION_PASS", "archive_sha256": archive_receipt["sha256"],
            "manifest_sha256": digest(manifest_path), "raw_file_count": len(files),
            "raw_bytes": manifest["raw_bytes"], "output": str(output), "physics_calls": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("raw_manifest.json"))
    parser.add_argument("--output", type=Path, required=True, help="Fresh campaign directory; parent must exist")
    args = parser.parse_args()
    try:
        print(json.dumps(restore(args.manifest, args.output), sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "RAW_RESTORATION_FAIL", "error": str(exc), "physics_calls": 0}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
