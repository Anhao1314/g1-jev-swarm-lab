"""Adversarial raw-byte preservation and historical package isolation."""
import json
from pathlib import Path

import pytest

from scripts.serial_certificate_001 import package_evidence as pack


def fixture(root):
    path = root / pack.EXPERIMENT / "result.json"
    path.parent.mkdir(parents=True)
    path.write_bytes('{"source":"保持原始字节"}\r\n'.encode())
    return path, pack.make_manifest(root)


def test_newline_conversion_rejected_without_rehash(tmp_path):
    path, manifest = fixture(tmp_path)
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    with pytest.raises(pack.helper.PackagingError, match="raw-byte mismatch"):
        pack.verify(tmp_path, manifest)


def test_duplicate_escape_and_self_hash_rejected(tmp_path):
    _, manifest = fixture(tmp_path)
    manifest["files"].append(manifest["files"][0])
    with pytest.raises(pack.helper.PackagingError, match="duplicate"):
        pack.verify(tmp_path, manifest)
    manifest["files"][-1]["path"] = "../outside"
    with pytest.raises(pack.helper.PackagingError, match="unsafe"):
        pack.verify(tmp_path, manifest)
    manifest["files"][-1]["path"] = pack.MANIFEST
    with pytest.raises(pack.helper.PackagingError, match="circular"):
        pack.verify(tmp_path, manifest)


def test_only_new_serial_scope_discovered_and_external_receipt_excluded(tmp_path):
    _, manifest = fixture(tmp_path)
    (tmp_path / pack.MANIFEST).write_bytes(b"{}")
    (tmp_path / pack.EXPERIMENT / "publication_validation.json").write_bytes(b"{}")
    old = tmp_path / "scripts/run_cross_model_certificate_pilot.py"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old")
    assert pack.make_manifest(tmp_path) == manifest


def test_archive_rebuild_and_tampering(tmp_path, monkeypatch):
    fixture(tmp_path)
    monkeypatch.setattr(pack.helper, "byte_attributes_check", lambda *_: None)
    archive = tmp_path / "artifact.zip"
    first = pack.freeze(tmp_path, archive)
    assert pack.check(tmp_path, archive)["status"] == "PASS"
    assert pack.freeze(tmp_path, archive) == first
    archive.write_bytes(archive.read_bytes() + b"changed")
    with pytest.raises(pack.helper.PackagingError, match="deterministic byte mismatch"):
        pack.check(tmp_path, archive)


def test_old_V1_default_discovery_stays_exact():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "experiments/phase2/source_authority_001/content_manifest.json").read_bytes())
    assert pack.helper.default_paths(root) == sorted(r["path"] for r in manifest["files"])
