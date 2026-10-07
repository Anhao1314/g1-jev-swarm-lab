"""V2 byte portability, external dependency integrity, and V1 discovery tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("authority_certificate_v2_packaging", ROOT / "scripts/package_authority_certificate_v2.py")
pack = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pack)


def write(root: Path, name: str, raw: bytes):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def fixture_bundle(root: Path):
    inventory = {"schema": "authority_certificate_v2_dependency_inventory_v1",
        "audit_anchor_commit": pack.BASE_COMMIT, "v1_payload_commit": pack.V1_PAYLOAD_COMMIT,
        "v1_archive_sha256": "external-v1-digest", "v1_reference_files": []}
    write(root, pack.DEPENDENCIES, pack.v1.json_bytes(inventory))
    write(root, pack.HELPER, b"immutable generic dependency\r\n")
    write(root, f"{pack.EXPERIMENT}/results.json", b'{"status":"UNKNOWN"}\n')
    write(root, "src/g1swarm/authority_certificate_v2.py", "完整 source\r\nLF\n".encode())
    manifest = pack.content_manifest(root, pack.default_paths(root))
    raw_manifest = pack.v1.json_bytes(manifest)
    write(root, pack.MANIFEST, raw_manifest)
    content = pack.verify_content(root, manifest)
    content[pack.MANIFEST] = raw_manifest
    raw = pack.v1.deterministic_zip(content)
    archive = root / "artifacts/source-authority-v2/source-authority-v2.zip"
    write(root, "artifacts/source-authority-v2/source-authority-v2.zip", raw)
    receipt = {"archive_sha256": pack.v1.sha256(raw),
        "content_manifest_sha256": pack.v1.sha256(raw_manifest),
        "dependency_inventory_sha256": pack.v1.sha256(content[pack.DEPENDENCIES]),
        "external_v1_archive_sha256": inventory["v1_archive_sha256"]}
    archive.with_suffix(".receipt.json").write_bytes(pack.v1.json_bytes(receipt))
    return archive


def test_extracted_thin_bundle_checks_bytes_without_claiming_external_v1_verified(tmp_path):
    archive = fixture_bundle(tmp_path)
    result = pack.check(tmp_path, archive, extracted_only=True)
    assert result["status"] == "PASS"
    assert result["extraction_rebuild_byte_equal"]
    assert result["thin_package_requires_external_v1_payload"]
    assert not result["v1_reference_bytes_verified"]
    assert not result["all_preexisting_anchor_paths_preserved"]
    assert result["provider_calls"] == result["runtime_calls"] == 0


def test_raw_byte_conversion_fails_instead_of_normalizing_hash(tmp_path):
    archive = fixture_bundle(tmp_path)
    path = tmp_path / f"{pack.EXPERIMENT}/results.json"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(pack.PackagingError, match="raw-byte mismatch"):
        pack.check(tmp_path, archive, extracted_only=True)


def test_archive_byte_and_external_receipt_tampering_rejected(tmp_path):
    archive = fixture_bundle(tmp_path)
    original = archive.read_bytes()
    archive.write_bytes(original + b"changed")
    with pytest.raises(pack.PackagingError, match="deterministic byte reconstruction"):
        pack.check(tmp_path, archive, extracted_only=True)
    archive.write_bytes(original)
    receipt = json.loads(archive.with_suffix(".receipt.json").read_bytes())
    receipt["external_v1_archive_sha256"] = "changed"
    archive.with_suffix(".receipt.json").write_bytes(pack.v1.json_bytes(receipt))
    with pytest.raises(pack.PackagingError, match="external receipt differs"):
        pack.check(tmp_path, archive, extracted_only=True)


def test_dependency_inventory_and_helper_cannot_be_omitted(tmp_path):
    fixture_bundle(tmp_path)
    for excluded in (pack.DEPENDENCIES, pack.HELPER):
        names = [name for name in pack.default_paths(tmp_path) if name != excluded]
        manifest = pack.content_manifest(tmp_path, names)
        with pytest.raises(pack.PackagingError, match="omits dependency inventory"):
            pack.verify_content(tmp_path, manifest)


def test_manifest_rejects_circular_duplicate_unsafe_and_symlink_paths(tmp_path):
    fixture_bundle(tmp_path)
    with pytest.raises(pack.PackagingError, match="cannot hash itself"):
        pack.content_manifest(tmp_path, [pack.MANIFEST])
    with pytest.raises(pack.PackagingError, match="unsafe package path"):
        pack.content_manifest(tmp_path, ["../outside"])
    manifest = pack.content_manifest(tmp_path, pack.default_paths(tmp_path))
    manifest["files"].append(manifest["files"][0])
    with pytest.raises(pack.PackagingError, match="duplicate"):
        pack.verify_content(tmp_path, manifest)


def test_v2_default_discovery_excludes_v1_evidence_and_transients(tmp_path):
    fixture_bundle(tmp_path)
    write(tmp_path, "scripts/run_authority_certificate_v2_pilot.py", b"runner\n")
    write(tmp_path, "prompts/authority_certificate_v2.txt", b"prompt\n")
    write(tmp_path, "experiments/phase2/source_authority_001/samples/old.json", b"old\n")
    write(tmp_path, f"{pack.EXPERIMENT}/response.pending.abc", b"partial")
    write(tmp_path, f"{pack.EXPERIMENT}/output.zip", b"zip")
    names = pack.default_paths(tmp_path)
    assert "scripts/run_authority_certificate_v2_pilot.py" in names
    assert "prompts/authority_certificate_v2.txt" in names
    assert all("source_authority_001" not in name for name in names)
    assert not any("pending" in name or name.endswith(".zip") for name in names)
    assert pack.HELPER in names


def test_v2_names_leave_real_frozen_v1_default_discovery_unchanged():
    """Read-only inventory check catches the source_author filename trap."""
    manifest = json.loads((ROOT / f"{pack.V1_EXPERIMENT}/content_manifest.json").read_bytes())
    expected = sorted(record["path"] for record in manifest["files"])
    assert pack.v1.default_paths(ROOT) == expected
    assert not any("authority_certificate_v2" in name for name in expected)


def test_dependency_bytes_cannot_change_even_with_same_size(tmp_path, monkeypatch):
    inventory = {"v1_reference_files": [{"path": "old.txt", "bytes": 3,
        "sha256": pack.v1.sha256(b"old"), "git_blob": "blob"}]}
    monkeypatch.setattr(pack, "build_dependency_inventory", lambda root: inventory)
    monkeypatch.setattr(pack.v1, "byte_attributes_check", lambda *args: None)
    write(tmp_path, "old.txt", b"old")
    pack.verify_references(tmp_path, inventory)
    write(tmp_path, "old.txt", b"new")
    with pytest.raises(pack.PackagingError, match="dependency raw bytes differ"):
        pack.verify_references(tmp_path, inventory)


def test_dependency_inventory_must_equal_trusted_anchor_before_byte_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(pack, "build_dependency_inventory", lambda root: {"trusted": True})
    with pytest.raises(pack.PackagingError, match="differs from trusted Git anchor"):
        pack.verify_references(tmp_path, {"trusted": False})


def test_prepare_is_idempotent_and_refuses_changed_existing_inventory(tmp_path, monkeypatch):
    inventory = {"v1_reference_files": [], "audit_anchor_commit": pack.BASE_COMMIT}
    monkeypatch.setattr(pack, "build_dependency_inventory", lambda root: inventory)
    monkeypatch.setattr(pack, "verify_references", lambda *args: None)
    first = pack.prepare(tmp_path)
    assert pack.prepare(tmp_path) == first
    write(tmp_path, pack.DEPENDENCIES, b"changed evidence")
    with pytest.raises(pack.PackagingError, match="will not overwrite"):
        pack.prepare(tmp_path)
    assert (tmp_path / pack.DEPENDENCIES).read_bytes() == b"changed evidence"


def test_all_anchor_paths_protected_and_attributes_only_allow_new_v2_append(tmp_path, monkeypatch):
    write(tmp_path, "old.py", b"old\n")
    old_attributes = b"old/** -text\n"
    write(tmp_path, ".gitattributes", old_attributes + b"scripts/*authority_certificate_v2*.py -text\n")
    monkeypatch.setattr(pack.v1, "anchor_tree", lambda *args: {"old.py": "blob", ".gitattributes": "attrs"})
    monkeypatch.setattr(pack, "blob", lambda *args, **kwargs: old_attributes)
    monkeypatch.setattr(pack.v1, "git", lambda *args, **kwargs: b".gitattributes\0")
    assert "old.py" in pack.preserved_anchor(tmp_path)
    monkeypatch.setattr(pack.v1, "git", lambda *args, **kwargs: b"old.py\0")
    with pytest.raises(pack.PackagingError, match="anchor modified"):
        pack.preserved_anchor(tmp_path)
    monkeypatch.setattr(pack.v1, "git", lambda *args, **kwargs: b".gitattributes\0")
    write(tmp_path, ".gitattributes", old_attributes + b"old/** text\n")
    with pytest.raises(pack.PackagingError, match="exceeds new V2 scope"):
        pack.preserved_anchor(tmp_path)
    write(tmp_path, ".gitattributes", b"old/** text\n")
    with pytest.raises(pack.PackagingError, match="pre-existing Git attribute rules"):
        pack.preserved_anchor(tmp_path)


def test_real_git_fresh_checkout_both_newline_modes_rebuild_identical_thin_archive(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    archive = fixture_bundle(original)
    expected = archive.read_bytes()
    write(original, ".gitattributes", b"* -text\n")

    def run(*args):
        subprocess.run(["git", *args], check=True, capture_output=True)

    run("init", str(original))
    run("-C", str(original), "config", "user.email", "packaging@example.invalid")
    run("-C", str(original), "config", "user.name", "V2 packaging test")
    run("-C", str(original), "add", ".")
    run("-C", str(original), "commit", "-m", "thin exact-byte fixture")
    for mode in ("true", "false"):
        clone = tmp_path / f"clone-{mode}"
        run("-c", f"core.autocrlf={mode}", "clone", "--no-local", str(original), str(clone))
        cloned_archive = clone / "artifacts/source-authority-v2/source-authority-v2.zip"
        checked = pack.check(clone, cloned_archive, extracted_only=True)
        assert cloned_archive.read_bytes() == expected
        assert checked["archive_sha256"] == pack.v1.sha256(expected)
