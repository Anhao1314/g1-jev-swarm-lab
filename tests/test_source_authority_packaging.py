"""Raw-byte reproducibility and tamper rejection for the new Pilot package."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/package_source_authority.py"
SPEC = importlib.util.spec_from_file_location("source_authority_packaging", SCRIPT)
pack = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pack)


def write(root: Path, name: str, data: bytes) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def fixture_bundle(root: Path) -> Path:
    name = f"{pack.EXPERIMENT}/baseline_snapshot/compiler.txt"
    baseline_bytes = b"line one\r\nline two\n\xff\x00"
    write(root, name, baseline_bytes)
    baseline = {
        "audit_anchor_commit": pack.BASE_COMMIT,
        "protected_anchor_blobs": {},
        "snapshots": [
            {
                "package_path": name,
                "original_path": "compiler.txt",
                "git_blob": "0" * 40,
                "sha256": pack.sha256(baseline_bytes),
                "bytes": len(baseline_bytes),
            }
        ],
    }
    write(root, pack.BASELINE_MANIFEST, pack.json_bytes(baseline))
    write(root, f"{pack.EXPERIMENT}/results.json", b'{"result":"UNKNOWN"}\n')
    selected = [name, pack.BASELINE_MANIFEST, f"{pack.EXPERIMENT}/results.json"]
    manifest_raw = pack.json_bytes(pack.content_manifest(root, selected))
    write(root, pack.MANIFEST, manifest_raw)
    content = pack.verify_content(root, json.loads(manifest_raw))
    content[pack.MANIFEST] = manifest_raw
    archive = root / "artifacts/source-authority.zip"
    raw = pack.deterministic_zip(content)
    write(root, "artifacts/source-authority.zip", raw)
    archive.with_suffix(".receipt.json").write_bytes(
        pack.json_bytes(
            {
                "archive_sha256": pack.sha256(raw),
                "content_manifest_sha256": pack.sha256(manifest_raw),
            }
        )
    )
    return archive


def test_archive_is_deterministic_and_preserves_mixed_and_binary_bytes():
    content = {"b.txt": b"B\r\n", "a.txt": b"A\n", "binary.dat": b"\x00\xff"}
    expected = pack.deterministic_zip(content)
    assert expected == pack.deterministic_zip(dict(reversed(list(content.items()))))
    with zipfile.ZipFile(io.BytesIO(expected)) as archive:
        assert archive.namelist() == sorted(content)
        for info in archive.infolist():
            assert info.date_time == pack.ZIP_DATE
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.create_system == 3
            assert info.external_attr == (0o100644 << 16)
            assert archive.read(info) == content[info.filename]


def test_default_inventory_includes_all_new_package_modules_and_excludes_transients(tmp_path):
    write(tmp_path, "src/g1swarm/source_authority/__init__.py", b"package\n")
    write(tmp_path, "src/g1swarm/source_authority/verifier.py", b"verifier\n")
    write(tmp_path, "src/g1swarm/source_authority/__pycache__/verifier.pyc", b"cache")
    write(tmp_path, "scripts/run_source_authority_pilot.py", b"runner\n")
    write(tmp_path, "scripts/unrelated.py", b"existing\n")
    write(tmp_path, pack.MANIFEST, b"excluded self\n")
    write(tmp_path, f"{pack.EXPERIMENT}/report.md", b"report\n")
    write(tmp_path, f"{pack.EXPERIMENT}/output.zip", b"excluded ZIP")
    assert pack.default_paths(tmp_path) == [
        f"{pack.EXPERIMENT}/report.md",
        "scripts/run_source_authority_pilot.py",
        "src/g1swarm/source_authority/__init__.py",
        "src/g1swarm/source_authority/verifier.py",
    ]


@pytest.mark.parametrize("name", ["../outside", "/absolute", "C:/absolute", "a\\b", "a/../b", "a//b", ""])
def test_archive_rejects_unsafe_member_paths(name):
    with pytest.raises(pack.PackagingError, match="unsafe package path"):
        pack.deterministic_zip({name: b"content"})


def test_bundle_check_extracts_and_rebuilds_identical_bytes(tmp_path):
    archive = fixture_bundle(tmp_path)
    result = pack.check(tmp_path, archive, verify_git=False)
    assert result["status"] == "PASS"
    assert result["raw_byte_files_verified"]
    assert result["extraction_rebuild_byte_equal"]
    assert result["provider_calls"] == result["runtime_calls"] == 0


def test_newline_conversion_is_detected_as_raw_byte_change(tmp_path):
    archive = fixture_bundle(tmp_path)
    path = tmp_path / f"{pack.EXPERIMENT}/results.json"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(pack.PackagingError, match="raw byte mismatch"):
        pack.check(tmp_path, archive, verify_git=False)


def test_snapshot_tampering_cannot_be_hidden_by_refreshed_content_manifest(tmp_path):
    archive = fixture_bundle(tmp_path)
    path = tmp_path / f"{pack.EXPERIMENT}/baseline_snapshot/compiler.txt"
    path.write_bytes(b"compiler changed")
    old_manifest = json.loads((tmp_path / pack.MANIFEST).read_bytes())
    new_manifest = pack.content_manifest(tmp_path, (item["path"] for item in old_manifest["files"]))
    write(tmp_path, pack.MANIFEST, pack.json_bytes(new_manifest))
    with pytest.raises(pack.PackagingError, match="baseline snapshot differs"):
        pack.check(tmp_path, archive, verify_git=False)


def test_archive_metadata_change_fails_deterministic_reconstruction(tmp_path):
    archive = fixture_bundle(tmp_path)
    raw = archive.read_bytes()
    archive.write_bytes(raw + b"trailing-byte-tamper")
    with pytest.raises(pack.PackagingError, match="deterministic reconstruction"):
        pack.check(tmp_path, archive, verify_git=False)


def test_archive_receipt_change_fails_independent_digest_check(tmp_path):
    archive = fixture_bundle(tmp_path)
    receipt = json.loads(archive.with_suffix(".receipt.json").read_bytes())
    receipt["archive_sha256"] = "0" * 64
    archive.with_suffix(".receipt.json").write_bytes(pack.json_bytes(receipt))
    with pytest.raises(pack.PackagingError, match="receipt SHA-256 differs"):
        pack.check(tmp_path, archive, verify_git=False)


def test_manifest_cannot_hash_itself_or_list_duplicate_members(tmp_path):
    with pytest.raises(pack.PackagingError, match="cannot hash itself"):
        pack.content_manifest(tmp_path, [pack.MANIFEST])
    write(tmp_path, "a", b"a")
    manifest = pack.content_manifest(tmp_path, ["a"])
    manifest["files"].append(manifest["files"][0])
    with pytest.raises(pack.PackagingError, match="duplicate"):
        pack.verify_content(tmp_path, manifest)


def test_baseline_modification_rejected_but_new_layer_permitted(tmp_path, monkeypatch):
    write(tmp_path, "src/g1swarm/compiler.py", b"frozen")
    monkeypatch.setattr(pack, "anchor_tree", lambda *args: {"src/g1swarm/compiler.py": "blob"})
    monkeypatch.setattr(pack, "git", lambda *args: b"src/g1swarm/source_authority.py\0")
    assert pack.preserved_baseline(tmp_path) == {"src/g1swarm/compiler.py": "blob"}
    monkeypatch.setattr(pack, "git", lambda *args: b"src/g1swarm/compiler.py\0")
    with pytest.raises(pack.PackagingError, match="immutable baseline modified"):
        pack.preserved_baseline(tmp_path)


def test_manifest_path_must_have_actual_binary_git_attribute(tmp_path, monkeypatch):
    monkeypatch.setattr(pack, "git", lambda *args, **kwargs: b"new.py\0text\0unset\0")
    pack.byte_attributes_check(tmp_path, ["new.py"])
    monkeypatch.setattr(pack, "git", lambda *args, **kwargs: b"new.py\0text\0unspecified\0")
    with pytest.raises(pack.PackagingError, match="require scoped -text"):
        pack.byte_attributes_check(tmp_path, ["new.py"])


def test_prepare_rerun_adds_snapshots_without_overwriting_changed_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(pack, "SNAPSHOT_FILES", ("compiler.txt",))
    monkeypatch.setattr(pack, "SNAPSHOT_PREFIXES", ())
    monkeypatch.setattr(pack, "anchor_tree", lambda *args: {"compiler.txt": "blob"})
    monkeypatch.setattr(pack, "preserved_baseline", lambda *args: {})

    def fake_git(root, *args, **kwargs):
        if args[0] == "rev-parse":
            return (pack.BASE_COMMIT if args[1].endswith("^{commit}") else "blob").encode() + b"\n"
        if args[0] == "cat-file":
            return b"frozen compiler\r\n"
        raise AssertionError(args)

    monkeypatch.setattr(pack, "git", fake_git)
    prepared = pack.prepare(tmp_path)
    target = tmp_path / prepared["snapshots"][0]["package_path"]
    assert target.read_bytes() == b"frozen compiler\r\n"
    assert pack.prepare(tmp_path) == prepared
    target.write_bytes(b"changed evidence")
    with pytest.raises(pack.PackagingError, match="baseline snapshot differs"):
        pack.prepare(tmp_path)
    assert target.read_bytes() == b"changed evidence"


def test_fresh_checkout_with_both_autocrlf_modes_reproduces_raw_package(tmp_path):
    """A real Git round-trip verifies the new -text policy, not just ZIP logic."""
    original = tmp_path / "original"
    original.mkdir()

    def run(*args):
        subprocess.run(["git", *args], check=True, capture_output=True)

    run("init", str(original))
    run("-C", str(original), "config", "user.email", "packaging@example.invalid")
    run("-C", str(original), "config", "user.name", "Packaging test")
    run("-C", str(original), "config", "core.autocrlf", "true")
    write(original, ".gitattributes", b"bundle/** -text\n")
    payload = {"bundle/a.txt": b"A\r\nB\n", "bundle/b.txt": "完整 source\n".encode()}
    for name, raw in payload.items():
        write(original, name, raw)
    run("-C", str(original), "add", ".")
    run("-C", str(original), "commit", "-m", "raw-byte fixture")
    expected = pack.deterministic_zip(payload)
    for mode in ("true", "false"):
        clone = tmp_path / f"clone-{mode}"
        run("-c", f"core.autocrlf={mode}", "clone", "--no-local", str(original), str(clone))
        copied = {name: (clone / name).read_bytes() for name in payload}
        assert copied == payload
        assert pack.deterministic_zip(copied) == expected
