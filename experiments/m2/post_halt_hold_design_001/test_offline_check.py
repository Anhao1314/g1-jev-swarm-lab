"""Offline guardrails for the candidate M2.5A design; imports no simulation."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODULE_SPEC = importlib.util.spec_from_file_location("m25a_offline_check", HERE / "offline_check.py")
CHECK = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(CHECK)


def protocol():
    return json.loads((HERE / "protocol.json").read_text(encoding="utf-8"))


def test_candidate_has_no_physics_authority_and_exact_budget():
    CHECK.validate_contract(protocol())
    mutated = deepcopy(protocol())
    mutated["physics_authorized"] = True
    with pytest.raises(ValueError):
        CHECK.validate_contract(mutated)
    mutated = deepcopy(protocol())
    mutated["cells_in_order"][0]["max_native_steps"] -= 1
    with pytest.raises(ValueError):
        CHECK.validate_contract(mutated)


def test_hold_window_and_command_cannot_silently_change():
    for path, value in [
        (("hold", "native_steps"), 999),
        (("hold", "rolling_window_steps"), 499),
        (("hold", "command_xyz_mps_radps"), [0.0, 0.1, 0.0]),
        (("continuity_and_integrity", "controller_reset_calls_from_qualifying_step_through_hold"), 1),
    ]:
        mutated = deepcopy(protocol())
        mutated[path[0]][path[1]] = value
        with pytest.raises(ValueError):
            CHECK.validate_contract(mutated)


def test_offline_source_binding_rejects_tamper(tmp_path):
    (tmp_path / "protocol.json").write_bytes((HERE / "protocol.json").read_bytes())
    binding = json.loads((HERE / "source_binding.json").read_text(encoding="utf-8"))
    first = next(iter(binding["sha256"]))
    binding["sha256"][first] = "0" * 64
    (tmp_path / "source_binding.json").write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(ValueError, match="basic.py"):
        CHECK.validate_sources(root=ROOT, here=tmp_path)
