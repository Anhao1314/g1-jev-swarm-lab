"""No-physics checks for M2.5A asset restoration and target preflight."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parent
MODULE_SPEC = importlib.util.spec_from_file_location("m25a_readiness", HERE / "readiness.py")
READINESS = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(READINESS)


def test_target_inherited_preflight_does_not_import_simulator_or_policy():
    before = {name: name in sys.modules for name in ("mujoco", "torch")}
    result = READINESS.check_target(require_new_source=False)
    assert result["status"] == "TARGET_INHERITED_PREFLIGHT_PASS_NO_PHYSICS"
    assert (result["inherited_source_count"], result["official_asset_count"], result["dependency_count"]) == (241, 91, 41)
    assert result["physics_steps"] == result["policy_inferences"] == 0
    assert {name: name in sys.modules for name in before} == before


def test_restore_verifies_source_before_copy_and_never_overwrites(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    name = "third_party/unitree_rl_gym/fixture.bin"
    original = b"verified-asset"
    path = source / name
    path.parent.mkdir(parents=True)
    path.write_bytes(original)
    row = {"path": name, "sha256": hashlib.sha256(original).hexdigest(), "bytes": len(original)}
    monkeypatch.setattr(READINESS, "official_asset_rows", lambda root: [row])
    receipt_source = target / "experiments/m2/cross_state_reliability_readiness_001/asset_restore.json"
    receipt_source.parent.mkdir(parents=True)
    receipt_source.write_text("{}", encoding="utf8")
    receipt = target / "receipt.json"
    result = READINESS.restore_assets(source, root=target, receipt_path=receipt)
    assert result["copied"] == 1 and result["physics_steps"] == 0
    assert (target / name).read_bytes() == original and receipt.exists()
    (target / name).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Existing asset mismatch"):
        READINESS.restore_assets(source, root=target)
    assert (target / name).read_bytes() == b"corrupt"


def test_restore_rejects_bad_source_without_target_write(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    name = "third_party/unitree_rl_gym/fixture.bin"
    path = source / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"wrong")
    monkeypatch.setattr(READINESS, "official_asset_rows", lambda root: [{
        "path": name, "sha256": hashlib.sha256(b"expected").hexdigest(), "bytes": len(b"expected")
    }])
    with pytest.raises(ValueError, match="Official asset source mismatch"):
        READINESS.restore_assets(source, root=target)
    assert not (target / name).exists()
