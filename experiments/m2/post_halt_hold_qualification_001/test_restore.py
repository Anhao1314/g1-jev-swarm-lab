"""Offline adversarial restoration checks; never imports acquisition machinery."""
import importlib.util
import json
from pathlib import Path
import stat
import zipfile

import pytest

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("m25a_restore_raw", HERE / "restore_raw.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(tmp_path, entries=None):
    entries = entries or [("case/trace.json", b'{"value": 1}\n'), ("receipt.txt", b"frozen\n")]
    archive = tmp_path / "campaign.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, payload in entries:
            bundle.writestr(name, payload)
    import hashlib
    files = {name: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()} for name, payload in entries}
    manifest = {"archive": {"path": archive.name, "bytes": archive.stat().st_size, "sha256": module.digest(archive)},
                "files": files, "raw_file_count": len(files), "raw_bytes": sum(v["bytes"] for v in files.values())}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest, archive


def test_lossless_and_no_overwrite(tmp_path):
    path, manifest, _ = fixture(tmp_path)
    output = tmp_path / "fresh"
    result = module.restore(path, output)
    assert result["status"] == "RAW_RESTORATION_PASS"
    for name, receipt in manifest["files"].items():
        assert module.digest(output / name) == receipt["sha256"]
    with pytest.raises(FileExistsError):
        module.restore(path, output)


def test_archive_tamper(tmp_path):
    path, _, archive = fixture(tmp_path)
    archive.write_bytes(archive.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="Archive bytes/hash"):
        module.restore(path, tmp_path / "fresh")
    assert not (tmp_path / "fresh").exists()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/drive", "a\\escape", "a/./b"])
def test_unsafe_paths(tmp_path, name):
    path, _, _ = fixture(tmp_path, [(name, b"bad")])
    with pytest.raises(ValueError, match="Unsafe"):
        module.restore(path, tmp_path / "fresh")
    assert not (tmp_path / "fresh").exists()


def test_duplicate_members(tmp_path):
    with pytest.warns(UserWarning, match="Duplicate name"):
        path, _, _ = fixture(tmp_path, [("same", b"first"), ("same", b"second")])
    with pytest.raises(ValueError, match="duplicate"):
        module.restore(path, tmp_path / "fresh")


def test_file_hash_tamper(tmp_path):
    path, manifest, _ = fixture(tmp_path)
    manifest["files"]["receipt.txt"]["sha256"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Restored file hash"):
        module.restore(path, tmp_path / "fresh")


def test_symlink_rejected(tmp_path):
    path, manifest, archive = fixture(tmp_path, [("link", b"target")])
    with zipfile.ZipFile(archive, "w") as bundle:
        member = zipfile.ZipInfo("link")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(member, b"target")
    manifest["archive"].update(bytes=archive.stat().st_size, sha256=module.digest(archive))
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="regular file"):
        module.restore(path, tmp_path / "fresh")
    assert not (tmp_path / "fresh").exists()


def test_real_campaign_lossless(tmp_path):
    manifest = HERE / "raw_manifest.json"
    if not manifest.exists():
        pytest.skip("Real campaign archive not yet sealed")
    receipts = json.loads(manifest.read_text(encoding="utf-8"))
    result = module.restore(manifest, tmp_path / "campaign_001")
    assert result["raw_file_count"] == 43
    assert result["raw_bytes"] == 64962438
    assert set(p.relative_to(tmp_path / "campaign_001").as_posix() for p in (tmp_path / "campaign_001").rglob("*") if p.is_file()) == set(receipts["files"])
    for name, receipt in receipts["files"].items():
        assert module.digest(tmp_path / "campaign_001" / name) == receipt["sha256"]
