"""Byte-exact packaging for the source-authority Pilot; never executes Missions.

The historical freeze used worktree byte pins that cannot be recreated from
some Git blobs. This experiment instead snapshots anchor Git blobs explicitly,
hashes the new package's raw bytes, and uses a deterministic, uncompressed ZIP.
No provider, environment, network, or historical freeze-check helper is used.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

BASE_COMMIT = "624c8024c6587f7c502b1cc87b2b27797493af03"
EXPERIMENT = "experiments/phase2/source_authority_001"
MANIFEST = f"{EXPERIMENT}/content_manifest.json"
BASELINE_MANIFEST = f"{EXPERIMENT}/baseline_snapshot_manifest.json"
SNAPSHOT = f"{EXPERIMENT}/baseline_snapshot"
PROTECTED_PREFIXES = ("src/g1swarm/", "prompts/", "configs/", "experiments/phase2/")
SNAPSHOT_PREFIXES = ("src/g1swarm/", "prompts/", "configs/language/")
SNAPSHOT_FILES = (
    "pyproject.toml",
    "tests/conftest.py",
    "experiments/phase2/simplex_compiler_001/protocol.yaml",
    "experiments/phase2/simplex_compiler_001/hardening_development_set.yaml",
    "experiments/phase2/simplex_compiler_001/fresh_blind_set.yaml",
    "experiments/phase2/controlled_language_001/language_corpus.yaml",
    "experiments/phase2/llm_compiler_001/controlled_regression.json",
    "experiments/phase2/long_horizon_language_001/protocol.yaml",
    "experiments/phase2/long_horizon_language_001/final/canonical_missions_final.yaml",
    "experiments/phase2/long_horizon_language_001/final/language_realizations_final.yaml",
    "experiments/phase2/long_horizon_language_001/ood/guard_ood_dataset.jsonl",
    "experiments/phase2/long_horizon_language_001/session4/compiler_results.json",
    "experiments/phase2/long_horizon_language_001/session4/ood_full_system_results.json",
    "experiments/phase2/long_horizon_language_001/session4/ood_sensitivity_summary.json",
    "experiments/phase2/long_horizon_language_001/session4_audit/audit_summary.json",
    "experiments/phase2/long_horizon_language_001/session4_audit/D011_candidate.md",
)
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


class PackagingError(ValueError):
    """Unsafe paths, modified baselines, and content mismatches fail closed."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def safe_path(name: str) -> str:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or ":" in name
        or path.is_absolute()
        or ".." in path.parts
        or str(path) != name
    ):
        raise PackagingError(f"unsafe package path: {name!r}")
    return name


def git(root: Path, *args: str, input_data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=input_data, capture_output=True, check=False
    )
    if result.returncode:
        raise PackagingError(f"Git operation failed: {' '.join(args[:2])}")
    return result.stdout


def anchor_tree(root: Path, base: str = BASE_COMMIT) -> dict[str, str]:
    rows = git(root, "ls-tree", "-rz", "--full-tree", base).split(b"\0")
    tree = {}
    for row in rows:
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        mode, kind, object_id = metadata.split()
        if kind == b"blob":
            tree[name.decode("utf-8")] = object_id.decode("ascii")
    return tree


def preserved_baseline(root: Path, base: str = BASE_COMMIT) -> dict[str, str]:
    """Git's own filters compare logical tracked content without old byte pins.

    New files are permitted; every protected path present in the anchor must
    remain unchanged, including staged or unstaged edits and deletions.
    """
    tree = anchor_tree(root, base)
    protected = {
        path: object_id
        for path, object_id in tree.items()
        if path.startswith(PROTECTED_PREFIXES)
    }
    changed = {
        path.decode("utf-8")
        for path in git(root, "diff", "--name-only", "-z", base, "--").split(b"\0")
        if path
    }
    violations = sorted(changed.intersection(protected))
    if violations:
        raise PackagingError("immutable baseline modified: " + ", ".join(violations))
    # `git diff` omits a skip-worktree file; reject missing protected files as well.
    missing = [path for path in protected if not (root / path).is_file()]
    if missing:
        raise PackagingError("immutable baseline missing: " + ", ".join(sorted(missing)))
    return protected


def prepare(root: Path, base: str = BASE_COMMIT) -> dict[str, Any]:
    resolved = git(root, "rev-parse", f"{base}^{{commit}}").decode("ascii").strip()
    if resolved != BASE_COMMIT:
        raise PackagingError("this Pilot is anchored only to Session 4 audit 624c802")
    protected = preserved_baseline(root, resolved)
    prior_manifest = root / BASELINE_MANIFEST
    if prior_manifest.exists():
        # A rerun may add newly declared snapshot files, never repair evidence.
        snapshot_check(root, json.loads(prior_manifest.read_bytes()), verify_git=True)
    tree = anchor_tree(root, resolved)
    selected = sorted(
        {path for path in tree if path.startswith(SNAPSHOT_PREFIXES)} | set(SNAPSHOT_FILES)
    )
    entries = []
    for original in selected:
        if original not in tree:
            raise PackagingError(f"required anchor file missing: {original}")
        raw = git(root, "cat-file", "blob", tree[original])
        packaged = safe_path(f"{SNAPSHOT}/{original}")
        target = root / packaged
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != raw:
                raise PackagingError(f"existing snapshot differs; will not overwrite: {packaged}")
        else:
            target.write_bytes(raw)
        entries.append(
            {
                "original_path": original,
                "package_path": packaged,
                "git_blob": tree[original],
                "sha256": sha256(raw),
                "bytes": len(raw),
            }
        )
    payload = {
        "schema": "source_authority_baseline_snapshot_v1",
        "audit_anchor_commit": resolved,
        "session4_evidence_commit": "5fabf3c050df4420f414a564dcdf5ce255a5b0fa",
        "immutable_comparator": "guarded_direct_llm_v1",
        "historical_freeze_hashes_rewritten": False,
        "snapshot_origin": "raw Git blobs; not historical worktree byte pins",
        "protected_anchor_blobs": dict(sorted(protected.items())),
        "snapshots": entries,
    }
    (root / BASELINE_MANIFEST).write_bytes(json_bytes(payload))
    return payload


def snapshot_check(root: Path, manifest: dict[str, Any], *, verify_git: bool) -> None:
    if manifest.get("audit_anchor_commit") != BASE_COMMIT:
        raise PackagingError("baseline snapshot has a different audit anchor")
    if verify_git:
        current = preserved_baseline(root)
        if current != manifest.get("protected_anchor_blobs"):
            raise PackagingError("protected anchor inventory differs")
    for record in manifest["snapshots"]:
        name = safe_path(record["package_path"])
        raw = (root / name).read_bytes()
        if sha256(raw) != record["sha256"] or len(raw) != record["bytes"]:
            raise PackagingError(f"baseline snapshot differs: {name}")
        if verify_git:
            original = safe_path(record["original_path"])
            if git(root, "rev-parse", f"{BASE_COMMIT}:{original}").decode().strip() != record[
                "git_blob"
            ]:
                raise PackagingError(f"anchor blob identity differs: {original}")
            if git(root, "cat-file", "blob", record["git_blob"]) != raw:
                raise PackagingError(f"snapshot not equal to anchor Git bytes: {original}")


def default_paths(root: Path) -> list[str]:
    selected = []
    for folder in (root / EXPERIMENT, root / "src", root / "scripts", root / "tests", root / "prompts"):
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root).as_posix()
            if relative == MANIFEST or path.suffix in (".zip", ".pyc", ".tmp"):
                continue
            if (
                relative.startswith(f"{EXPERIMENT}/")
                or "source_author" in path.name.lower()
                or "source_authority" in path.parts
            ):
                selected.append(relative)
    return sorted(set(selected))


def content_manifest(root: Path, paths: Iterable[str]) -> dict[str, Any]:
    records = []
    for name in sorted(set(paths)):
        name = safe_path(name)
        if name == MANIFEST:
            raise PackagingError("content manifest cannot hash itself")
        path = root / name
        if path.is_symlink():
            raise PackagingError(f"symlinks cannot enter package: {name}")
        raw = path.read_bytes()
        records.append({"path": name, "bytes": len(raw), "sha256": sha256(raw)})
    return {
        "schema": "source_authority_content_manifest_v1",
        "audit_anchor_commit": BASE_COMMIT,
        "byte_policy": "raw bytes; no newline, Unicode, or JSON normalization",
        "checkout_policy": "every packaged repository path requires Git text=unset (-text)",
        "archive_policy": "ZIP_STORED; sorted paths; 1980-01-01; Unix regular 0644",
        "manifest_self_hash": "excluded to avoid circularity",
        "files": records,
    }


def byte_attributes_check(root: Path, names: Iterable[str]) -> None:
    """Require actual scoped -text attributes, independent of host Git defaults."""
    names = sorted(set(safe_path(name) for name in names))
    query = b"\0".join(name.encode("utf-8") for name in names) + b"\0"
    response = git(root, "check-attr", "--stdin", "-z", "text", input_data=query)
    fields = response.rstrip(b"\0").split(b"\0")
    if len(fields) != 3 * len(names):
        raise PackagingError("Git byte-attribute query returned an incomplete inventory")
    failures = []
    for offset in range(0, len(fields), 3):
        name, attribute, value = fields[offset : offset + 3]
        if attribute != b"text" or value != b"unset":
            failures.append(name.decode("utf-8"))
    if failures:
        raise PackagingError("package paths require scoped -text attributes: " + ", ".join(failures))


def verify_content(root: Path, manifest: dict[str, Any]) -> dict[str, bytes]:
    if manifest.get("schema") != "source_authority_content_manifest_v1":
        raise PackagingError("unsupported content manifest")
    content = {}
    for record in manifest["files"]:
        name = safe_path(record["path"])
        if name == MANIFEST or name in content:
            raise PackagingError(f"circular or duplicate manifest path: {name}")
        raw = (root / name).read_bytes()
        if len(raw) != record["bytes"] or sha256(raw) != record["sha256"]:
            raise PackagingError(f"raw byte mismatch: {name}")
        content[name] = raw
    return content


def deterministic_zip(content: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(content):
            safe_path(name)
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (0o100644 << 16)
            info.internal_attr = 0
            info.flag_bits = 0
            info.extra = b""
            info.comment = b""
            archive.writestr(info, content[name])
    return stream.getvalue()


def freeze(root: Path, archive: Path, includes: Iterable[str] = ()) -> dict[str, Any]:
    baseline = json.loads((root / BASELINE_MANIFEST).read_bytes())
    snapshot_check(root, baseline, verify_git=True)
    paths = default_paths(root) + [safe_path(name) for name in includes]
    byte_attributes_check(root, paths + [MANIFEST])
    manifest = content_manifest(root, paths)
    manifest_raw = json_bytes(manifest)
    (root / MANIFEST).write_bytes(manifest_raw)
    content = verify_content(root, manifest)
    content[MANIFEST] = manifest_raw
    raw = deterministic_zip(content)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(raw)
    receipt = {
        "schema": "source_authority_archive_receipt_v1",
        "archive": archive.name,
        "archive_sha256": sha256(raw),
        "archive_bytes": len(raw),
        "content_manifest_sha256": sha256(manifest_raw),
        "packaged_files_including_manifest": len(content),
        "receipt_location": "outside package to avoid circular archive hash",
    }
    archive.with_suffix(".receipt.json").write_bytes(json_bytes(receipt))
    return receipt


def check(root: Path, archive: Path, *, verify_git: bool = True) -> dict[str, Any]:
    manifest_raw = (root / MANIFEST).read_bytes()
    manifest = json.loads(manifest_raw)
    content = verify_content(root, manifest)
    content[MANIFEST] = manifest_raw
    if verify_git:
        byte_attributes_check(root, content)
    baseline = json.loads((root / BASELINE_MANIFEST).read_bytes())
    snapshot_check(root, baseline, verify_git=verify_git)
    expected = deterministic_zip(content)
    received = archive.read_bytes()
    if received != expected:
        raise PackagingError("archive differs from deterministic reconstruction")
    receipt = json.loads(archive.with_suffix(".receipt.json").read_bytes())
    if receipt["archive_sha256"] != sha256(received):
        raise PackagingError("archive receipt SHA-256 differs")
    if receipt["content_manifest_sha256"] != sha256(manifest_raw):
        raise PackagingError("content manifest receipt SHA-256 differs")
    with tempfile.TemporaryDirectory(prefix="source-authority-package-") as temporary:
        extracted = Path(temporary)
        with zipfile.ZipFile(io.BytesIO(received)) as zipped:
            names = zipped.namelist()
            if names != sorted(content) or len(names) != len(set(names)):
                raise PackagingError("archive paths differ or repeat")
            for name in names:
                safe_path(name)
                destination = extracted / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(zipped.read(name))
        checked = verify_content(extracted, manifest)
        checked[MANIFEST] = (extracted / MANIFEST).read_bytes()
        snapshot_check(extracted, baseline, verify_git=False)
        if deterministic_zip(checked) != received:
            raise PackagingError("extracted package cannot reproduce archive bytes")
    return {
        "status": "PASS",
        "archive_sha256": sha256(received),
        "content_manifest_sha256": sha256(manifest_raw),
        "files_checked": len(content),
        "raw_byte_files_verified": True,
        "extraction_rebuild_byte_equal": True,
        "baseline_anchor_preserved": verify_git,
        "checkout_byte_attributes_verified": verify_git,
        "provider_calls": 0,
        "runtime_calls": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "freeze", "check"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--extracted-only", action="store_true")
    options = parser.parse_args(argv)
    root = options.root.resolve()
    archive = options.archive or root / "artifacts/phase24-source-authority/source-authority.zip"
    try:
        if options.command == "prepare":
            result = prepare(root)
            result = {"status": "PASS", "snapshots": len(result["snapshots"]), "base": BASE_COMMIT}
        elif options.command == "freeze":
            result = freeze(root, archive, options.include)
        else:
            result = check(root, archive, verify_git=not options.extracted_only)
    except (PackagingError, OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
