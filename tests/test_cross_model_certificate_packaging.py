"""Adversarial byte preservation and circular manifest checks."""
import json

import pytest

from scripts import package_cross_model_certificate as pack


def fixture(root):
    path = root / pack.EXPERIMENT / "result.json"
    path.parent.mkdir(parents=True)
    path.write_bytes('{"source":"原始来源"}\r\n'.encode())
    return path, pack.make_manifest(root)


def test_newline_rewrite_detected_without_normalization(tmp_path):
    path, manifest = fixture(tmp_path)
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    with pytest.raises(pack.helper.PackagingError, match="raw-byte mismatch"):
        pack.verify(tmp_path, manifest)


def test_duplicate_and_escaping_member_rejected(tmp_path):
    _, manifest = fixture(tmp_path)
    manifest["files"].append(manifest["files"][0])
    with pytest.raises(pack.helper.PackagingError, match="duplicate"):
        pack.verify(tmp_path, manifest)
    manifest["files"][-1]["path"] = "../outside"
    with pytest.raises(pack.helper.PackagingError, match="unsafe"):
        pack.verify(tmp_path, manifest)


def test_circular_manifest_excluded_and_old_evidence_not_discovered(tmp_path):
    _, manifest = fixture(tmp_path)
    for name in pack.EXCLUDED:
        (tmp_path / name).write_bytes(b"{}")
    old = tmp_path / "experiments/phase2/source_authority_v2_001/old.json"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old evidence")
    assert pack.make_manifest(tmp_path) == manifest
    manifest["files"].append({"path": pack.MANIFEST})
    with pytest.raises(pack.helper.PackagingError, match="circular"):
        pack.verify(tmp_path, manifest)


def test_deterministic_archive_rebuild_and_tamper(tmp_path, monkeypatch):
    fixture(tmp_path)
    monkeypatch.setattr(pack.helper, "byte_attributes_check", lambda *_: None)
    archive = tmp_path / "artifact.zip"
    first = pack.freeze(tmp_path, archive)
    assert pack.check(tmp_path, archive)["status"] == "PASS"
    assert pack.freeze(tmp_path, archive) == first
    archive.write_bytes(archive.read_bytes() + b"tamper")
    with pytest.raises(pack.helper.PackagingError, match="archive byte mismatch"):
        pack.check(tmp_path, archive)
