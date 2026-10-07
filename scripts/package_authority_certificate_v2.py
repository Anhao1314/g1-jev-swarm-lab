"""Thin byte-exact V2 package with immutable, explicitly pinned V1 dependencies.

Only generic functions from the unchanged V1 packager are reused. All V2 paths,
schemas and manifests are separate; neither V1 package discovery nor V1 frozen
evidence is modified. The archive contains new evidence and dependency metadata,
not a second copy of the 76 MB V1 payload. No provider or Runtime is invoked.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from typing import Any, Iterable
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = "d06c61811c3ef41abf12c22a4a2618eabf28c495"
V1_PAYLOAD_COMMIT = "3e21f9370fc37ee7d5ccbd619d8d17662f9574fa"
V1_EXPERIMENT = "experiments/phase2/source_authority_001"
EXPERIMENT = "experiments/phase2/source_authority_v2_001"
MANIFEST = f"{EXPERIMENT}/content_manifest.json"
DEPENDENCIES = f"{EXPERIMENT}/dependency_inventory.json"
HELPER = "scripts/package_source_authority.py"
PUBLICATION = "reports/source_authority_publication_validation.json"
NEW_ATTRIBUTE_SCOPES = (
    "experiments/phase2/source_authority_v2_001/",
    "scripts/*authority_certificate_v2",
    "tests/*authority_certificate_v2",
    "src/g1swarm/*authority_certificate_v2",
    "src/g1swarm/authority_certificate_v2",
    "prompts/*authority_certificate_v2",
    "reports/authority_certificate_v2_publication_validation.json",
)

_SPEC = importlib.util.spec_from_file_location("immutable_v1_packaging_helpers", ROOT / HELPER)
v1 = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(v1)
PackagingError = v1.PackagingError


def blob(root: Path, name: str, *, commit: str = BASE_COMMIT) -> bytes:
    return v1.git(root, "show", f"{commit}:{v1.safe_path(name)}")


def preserved_anchor(root: Path) -> dict[str, str]:
    """Protect every pre-existing anchor blob, allowing only scoped attr append."""
    tree = v1.anchor_tree(root, BASE_COMMIT)
    changed = {
        path.decode("utf-8") for path in
        v1.git(root, "diff", "--name-only", "-z", BASE_COMMIT, "--").split(b"\0") if path
    }
    protected_edits = sorted((changed & set(tree)) - {".gitattributes"})
    if protected_edits:
        raise PackagingError("immutable V1/audit anchor modified: " + ", ".join(protected_edits))
    missing = [name for name in tree if not (root / name).is_file()]
    if missing:
        raise PackagingError("immutable V1/audit anchor missing: " + ", ".join(sorted(missing)))
    anchor_attributes = blob(root, ".gitattributes").replace(b"\r\n", b"\n")
    attributes = (root / ".gitattributes").read_bytes().replace(b"\r\n", b"\n")
    if not attributes.startswith(anchor_attributes):
        raise PackagingError("pre-existing Git attribute rules were changed")
    for line in attributes[len(anchor_attributes):].decode("utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        scope, *settings = line.split()
        if not scope.startswith(NEW_ATTRIBUTE_SCOPES) or "-text" not in settings:
            raise PackagingError("attribute append exceeds new V2 scope: " + scope)
    return tree


def build_dependency_inventory(root: Path) -> dict[str, Any]:
    tree = preserved_anchor(root)
    manifest_path = f"{V1_EXPERIMENT}/content_manifest.json"
    raw = blob(root, manifest_path)
    payload_raw = blob(root, manifest_path, commit=V1_PAYLOAD_COMMIT)
    if raw != payload_raw:
        raise PackagingError("V1 manifest differs between payload and audit anchor")
    manifest = json.loads(raw)
    publication_raw = blob(root, PUBLICATION)
    publication = json.loads(publication_raw)
    if publication["payload_commit"] != V1_PAYLOAD_COMMIT:
        raise PackagingError("V1 publication receipt references another payload")
    receipt = publication["archive_receipt"]
    if v1.sha256(raw) != receipt["content_manifest_sha256"]:
        raise PackagingError("V1 published content-manifest digest differs")
    references = []
    for record in [*manifest["files"], {"path": manifest_path, "bytes": len(raw), "sha256": v1.sha256(raw)}]:
        name = v1.safe_path(record["path"])
        if name not in tree:
            raise PackagingError(f"V1 package reference absent from audit anchor: {name}")
        references.append({**record, "git_blob": tree[name]})
    references.sort(key=lambda record: record["path"])
    return {
        "schema": "authority_certificate_v2_dependency_inventory_v1",
        "audit_anchor_commit": BASE_COMMIT,
        "v1_payload_commit": V1_PAYLOAD_COMMIT,
        "dependency_policy": "external immutable V1 payload; no duplicated evidence bytes",
        "v1_content_manifest_path": manifest_path,
        "v1_content_manifest_sha256": v1.sha256(raw),
        "v1_archive_sha256": receipt["archive_sha256"],
        "v1_archive_bytes": receipt["archive_bytes"],
        "v1_publication_receipt_path": PUBLICATION,
        "v1_publication_receipt_sha256": v1.sha256(publication_raw),
        "protected_anchor_git_blobs": dict(sorted(tree.items())),
        "v1_reference_files": references,
        "comparators": {
            "frozen_inputs": f"{V1_EXPERIMENT}/inputs.json",
            "frozen_B_and_v1_gate_outputs": f"{V1_EXPERIMENT}/samples/",
            "frozen_bounded_outputs": f"{V1_EXPERIMENT}/bounded_control.json",
            "v1_raw_provider_evidence": f"{V1_EXPERIMENT}/acquisition/",
        },
        "generic_packaging_dependency": HELPER,
        "credentials_collected": False,
    }


def verify_references(root: Path, inventory: dict[str, Any]) -> None:
    if inventory != build_dependency_inventory(root):
        raise PackagingError("V2 external dependency inventory differs from trusted Git anchor")
    names = [record["path"] for record in inventory["v1_reference_files"]]
    v1.byte_attributes_check(root, names)
    for record in inventory["v1_reference_files"]:
        name = v1.safe_path(record["path"])
        raw = (root / name).read_bytes()
        if len(raw) != record["bytes"] or v1.sha256(raw) != record["sha256"]:
            raise PackagingError(f"immutable V1 dependency raw bytes differ: {name}")


def prepare(root: Path) -> dict[str, Any]:
    inventory = build_dependency_inventory(root)
    verify_references(root, inventory)
    target = root / DEPENDENCIES
    raw = v1.json_bytes(inventory)
    if target.exists() and target.read_bytes() != raw:
        raise PackagingError("existing V2 dependency inventory changed; will not overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(raw)
    return {"status": "PASS", "audit_anchor_commit": BASE_COMMIT,
        "v1_reference_files": len(inventory["v1_reference_files"]),
        "v1_referenced_bytes": sum(record["bytes"] for record in inventory["v1_reference_files"]),
        "dependency_inventory_sha256": v1.sha256(raw), "v1_evidence_copied": False}


def default_paths(root: Path) -> list[str]:
    names = [HELPER]
    for folder in (root / EXPERIMENT, root / "src", root / "scripts", root / "tests", root / "prompts"):
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            name = path.relative_to(root).as_posix()
            if name == MANIFEST or path.suffix in {".zip", ".pyc", ".tmp"} or ".pending." in path.name:
                continue
            if name.startswith(f"{EXPERIMENT}/") or "authority_certificate_v2" in name:
                names.append(name)
    return sorted(set(names))


def content_manifest(root: Path, paths: Iterable[str]) -> dict[str, Any]:
    records = []
    for name in sorted(set(paths)):
        name = v1.safe_path(name)
        if name == MANIFEST:
            raise PackagingError("V2 content manifest cannot hash itself")
        path = root / name
        if path.is_symlink():
            raise PackagingError(f"symlink cannot enter V2 package: {name}")
        raw = path.read_bytes()
        records.append({"path": name, "bytes": len(raw), "sha256": v1.sha256(raw)})
    return {"schema": "authority_certificate_v2_content_manifest_v1",
        "audit_anchor_commit": BASE_COMMIT, "v1_payload_commit": V1_PAYLOAD_COMMIT,
        "byte_policy": "raw bytes; no newline, Unicode, or JSON normalization",
        "checkout_policy": "every packaged path has scoped Git text=unset (-text)",
        "archive_policy": "ZIP_STORED; sorted paths; 1980-01-01; Unix regular 0644",
        "manifest_self_hash": "excluded to avoid circularity",
        "external_dependencies": DEPENDENCIES, "files": records}


def verify_content(root: Path, manifest: dict[str, Any]) -> dict[str, bytes]:
    if manifest.get("schema") != "authority_certificate_v2_content_manifest_v1" or manifest.get("audit_anchor_commit") != BASE_COMMIT:
        raise PackagingError("unsupported V2 content manifest or anchor")
    content = {}
    for record in manifest["files"]:
        name = v1.safe_path(record["path"])
        if name == MANIFEST or name in content:
            raise PackagingError(f"circular or duplicate V2 manifest path: {name}")
        raw = (root / name).read_bytes()
        if len(raw) != record["bytes"] or v1.sha256(raw) != record["sha256"]:
            raise PackagingError(f"V2 raw-byte mismatch: {name}")
        content[name] = raw
    if DEPENDENCIES not in content or HELPER not in content:
        raise PackagingError("V2 manifest omits dependency inventory or immutable generic helper")
    return content


def freeze(root: Path, archive: Path, includes: Iterable[str] = ()) -> dict[str, Any]:
    inventory = json.loads((root / DEPENDENCIES).read_bytes())
    verify_references(root, inventory)
    names = default_paths(root) + [v1.safe_path(name) for name in includes]
    v1.byte_attributes_check(root, [*names, MANIFEST])
    manifest = content_manifest(root, names)
    manifest_raw = v1.json_bytes(manifest)
    (root / MANIFEST).write_bytes(manifest_raw)
    content = verify_content(root, manifest)
    content[MANIFEST] = manifest_raw
    raw = v1.deterministic_zip(content)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(raw)
    receipt = {"schema": "authority_certificate_v2_archive_receipt_v1",
        "archive": archive.name, "archive_sha256": v1.sha256(raw), "archive_bytes": len(raw),
        "content_manifest_sha256": v1.sha256(manifest_raw),
        "dependency_inventory_sha256": v1.sha256((root / DEPENDENCIES).read_bytes()),
        "external_v1_archive_sha256": inventory["v1_archive_sha256"],
        "packaged_files_including_manifest": len(content),
        "receipt_location": "outside package to avoid circular archive hash"}
    archive.with_suffix(".receipt.json").write_bytes(v1.json_bytes(receipt))
    return receipt


def check(root: Path, archive: Path, *, extracted_only: bool = False) -> dict[str, Any]:
    manifest_raw = (root / MANIFEST).read_bytes()
    manifest = json.loads(manifest_raw)
    content = verify_content(root, manifest)
    content[MANIFEST] = manifest_raw
    inventory = json.loads(content[DEPENDENCIES])
    if not extracted_only:
        verify_references(root, inventory)
        v1.byte_attributes_check(root, content)
    raw = archive.read_bytes()
    if v1.deterministic_zip(content) != raw:
        raise PackagingError("V2 archive differs from deterministic byte reconstruction")
    receipt = json.loads(archive.with_suffix(".receipt.json").read_bytes())
    for field, expected in {
        "archive_sha256": v1.sha256(raw), "content_manifest_sha256": v1.sha256(manifest_raw),
        "dependency_inventory_sha256": v1.sha256(content[DEPENDENCIES]),
        "external_v1_archive_sha256": inventory["v1_archive_sha256"],
    }.items():
        if receipt[field] != expected:
            raise PackagingError(f"V2 external receipt differs: {field}")
    with tempfile.TemporaryDirectory(prefix="authority-certificate-v2-package-") as temporary:
        extracted = Path(temporary)
        with zipfile.ZipFile(io.BytesIO(raw)) as zipped:
            if zipped.namelist() != sorted(content) or len(zipped.namelist()) != len(set(zipped.namelist())):
                raise PackagingError("V2 ZIP member inventory differs or repeats")
            for name in zipped.namelist():
                v1.safe_path(name)
                destination = extracted / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(zipped.read(name))
        copied = verify_content(extracted, manifest)
        copied[MANIFEST] = (extracted / MANIFEST).read_bytes()
        if v1.deterministic_zip(copied) != raw:
            raise PackagingError("V2 extracted bytes cannot reproduce archive")
    return {"status": "PASS", "archive_sha256": v1.sha256(raw),
        "content_manifest_sha256": v1.sha256(manifest_raw),
        "dependency_inventory_sha256": v1.sha256(content[DEPENDENCIES]),
        "files_checked": len(content), "extraction_rebuild_byte_equal": True,
        "all_preexisting_anchor_paths_preserved": not extracted_only,
        "v1_reference_bytes_verified": not extracted_only,
        "external_v1_reference_files": len(inventory["v1_reference_files"]),
        "checkout_byte_attributes_verified": not extracted_only,
        "thin_package_requires_external_v1_payload": True,
        "provider_calls": 0, "runtime_calls": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "freeze", "check"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--extracted-only", action="store_true")
    options = parser.parse_args()
    root = options.root.resolve()
    archive = options.archive or root / "artifacts/source-authority-v2/source-authority-v2.zip"
    try:
        if options.command == "prepare":
            result = prepare(root)
        elif options.command == "freeze":
            result = freeze(root, archive, options.include)
        else:
            result = check(root, archive, extracted_only=options.extracted_only)
    except (PackagingError, OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
