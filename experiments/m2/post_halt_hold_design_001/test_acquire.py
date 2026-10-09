"""M2.5A adapter contract tests. Every backend here is fake; zero physics."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import ast
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
spec_module = importlib.util.spec_from_file_location("m25a_acquire_under_test", HERE / "acquire.py")
acquire = importlib.util.module_from_spec(spec_module)
spec_module.loader.exec_module(acquire)
SPEC = json.loads((HERE / "protocol.json").read_text(encoding="utf8"))
M24 = json.loads((acquire.M24).read_text(encoding="utf8"))


def parent_result(*, normal=False, halt_status="HALT_SUCCEEDED", has_halt=True):
    if normal:
        return {"state": "SUCCESS", "mission_success": True, "physical_success": True,
                "completed_nodes": 3, "physical_halt": None, "nodes": [
                    {"skill": "walk_forward"}, {"skill": "turn"},
                    {"skill": "stop", "metrics": {"skill_status": "SUCCESS"}}]}
    return {"state": "FAILED", "mission_success": False, "failure_type": "TASK_ENVELOPE_VIOLATION",
            "failed_node": "s1", "physical_halt": None if not has_halt else {
                "status": halt_status, "skill_status": "SUCCESS" if halt_status == "HALT_SUCCEEDED" else "TIMEOUT",
                "checks": {"skill_success": halt_status == "HALT_SUCCEEDED"},
                "trace": [{"speed_mps": 0.3}] + [{"speed_mps": 0.1} for _ in range(500)]}}


class FakeBackend:
    def __init__(self, parent: dict, *, speeds=None, standing=True, fail_step=None,
                 fail_exception=RuntimeError, continuity_change=False,
                 reset_on_hold=False, parent_steps=7139, observer_enabled=True):
        self.parent = parent
        self.speeds = speeds or [0.05] * 1000
        self.standing, self.fail_step = standing, fail_step
        self.fail_exception = fail_exception
        self.continuity_change, self.reset_on_hold = continuity_change, reset_on_hold
        self.parent_steps = parent_steps
        self.observer_enabled = observer_enabled
        self.commands = []
        self.steps = 0
        self.witness = {"native_steps": parent_steps, "integrity_failure": None,
                        "budget_failure": None, "hold_command_calls": 0}
        self.snap = {"time_s": 14.278, "qpos": [0.0, 0.0, 0.8], "qvel": [0.0, 0.0, 0.0],
                     "ctrl": [0.0], "xfrc_applied": [[0.0]],
                     "controller_action": [0.0], "controller_target": [0.0], "controller_counter": 7000,
                     "session_identity": 1, "simulation_identity": 2, "controller_identity": 3,
                     "policy_identity": 4, "reset_calls": 2, "native_reset_calls": 2,
                     "keyframe_reset_calls": 0, "controller_reset_calls": 2,
                     "node_dispatches": 1, "executor_dispatches": 1,
                     "native_steps": parent_steps, "session_steps": parent_steps}
        self.terminal = {"stop_status": "SUCCESS", "stop_window_mean_mps": 0.1,
                         "stop_crossing_time_s": self.snap["time_s"],
                         "stop_poststep_speeds": [0.1] * 500,
                         "snapshot": deepcopy(self.snap),
                         "skill_return_snapshot": deepcopy(self.snap)}
        self.entered_hold = False

    @contextmanager
    def __call__(self, spec, m24, cell, run_dir, prior_native_steps):
        backend = self

        class Executor:
            last_graph = SimpleNamespace(to_dict=lambda: {"nodes": [{"node_id": "s1"}]})

            def run(self, mission, *, existing_session, phase):
                assert existing_session is session and phase == "m25a_parent"
                assert mission["mission_id"] in ("m2-open-loop-walk6-turn45-stop",
                                                  "m24-parent-turn45-walk6", "m2-safe-walk4-turn45-stop")
                return SimpleNamespace(to_dict=lambda: deepcopy(backend.parent))

        session = object()

        def snapshot():
            value = deepcopy(backend.snap)
            if backend.continuity_change and not backend.entered_hold and backend.steps == 0:
                value["qpos"][0] = 0.001
            return value

        def step_zero():
            assert backend.entered_hold
            backend.commands.append([0.0, 0.0, 0.0])
            backend.witness["hold_command_calls"] += 1
            if backend.fail_step == backend.steps:
                raise backend.fail_exception("synthetic backend fault")
            backend.steps += 1
            backend.witness["native_steps"] += 1
            backend.snap["native_steps"] += 1
            backend.snap["session_steps"] += 1
            backend.snap["controller_counter"] += 1
            backend.snap["time_s"] += 0.002
            if backend.reset_on_hold and backend.steps == 1:
                backend.snap["controller_reset_calls"] += 1
            return object()

        def row(state, index):
            return {"hold_step": index, "native_sequence": backend.witness["native_steps"],
                    "time_s": backend.snap["time_s"], "position_m": [0.0, 0.0, 0.8],
                    "speed_mps": backend.speeds[index - 1], "standing": backend.standing,
                    "fallen": False, "finite": True, "raw_finite": True,
                    "command_xyz_mps_radps": [0.0, 0.0, 0.0]}

        def journal(row):
            if backend.observer_enabled:
                with (run_dir / "hold_incremental.jsonl").open("a", encoding="utf8") as stream:
                    stream.write(json.dumps(row) + "\n")

        yield {"session": session, "executor": Executor(), "terminal": self.terminal,
               "witness": self.witness, "snapshot": snapshot,
               "verify_historical_parent": lambda: {"status": "EXACT_M24_PARENT_NATIVE_PREFIX_MATCH"},
               "begin_hold": lambda: setattr(self, "entered_hold", True),
               "step_zero": step_zero, "state_row": row, "raw_last": lambda: {"raw_finite": True},
               "guard": lambda: None, "journal_hold_row": journal}


def run_fake(tmp_path, backend, cell_index=0):
    cell = SPEC["cells_in_order"][cell_index]
    result = acquire.run_cell(SPEC, M24, cell, tmp_path, backend)
    return result


def test_import_has_no_simulator_or_policy_import():
    module = ast.parse((HERE / "acquire.py").read_text(encoding="utf8"))
    imported = []
    for statement in module.body:
        if isinstance(statement, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in statement.names)
        elif isinstance(statement, ast.ImportFrom) and statement.module:
            imported.append(statement.module.split(".")[0])
    assert not {"mujoco", "torch", "g1swarm"} & set(imported)
    assert SPEC["physics_authorized"] is False


def test_fresh_worker_pins_import_origin_to_this_checkout_without_live_import():
    code = (
        "import importlib.util,json,sys;"
        f"p={str(HERE / 'acquire.py')!r};"
        "s=importlib.util.spec_from_file_location('m25a_path_test',p);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "w=m.target_import_witness();"
        "print(json.dumps({'witness':w,'mujoco_loaded':'mujoco' in sys.modules,'torch_loaded':'torch' in sys.modules}))"
    )
    completed = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True,
                               text=True, check=True)
    result = json.loads(completed.stdout)
    assert result["witness"]["module_origins"]["g1swarm"] == (acquire.ROOT / "src/g1swarm/__init__.py").as_posix()
    assert result["witness"]["module_origins"]["scripts.run_oracle_missions"] == (acquire.ROOT / "scripts/run_oracle_missions.py").as_posix()
    assert not result["mujoco_loaded"] and not result["torch_loaded"]


def test_loaded_stale_editable_package_fails_closed(monkeypatch):
    stale = SimpleNamespace(__spec__=SimpleNamespace(origin="D:/work/other-checkout/src/g1swarm/__init__.py"))
    monkeypatch.setitem(sys.modules, "g1swarm", stale)
    with pytest.raises(acquire.IntegrityFailure, match="TARGET_CHECKOUT_IMPORT_ORIGIN_MISMATCH:g1swarm"):
        acquire.target_import_witness()


def test_loaded_stale_submodule_fails_closed(monkeypatch):
    stale = SimpleNamespace(__spec__=SimpleNamespace(origin="D:/work/other-checkout/src/g1swarm/mission/runtime.py"))
    monkeypatch.setitem(sys.modules, "g1swarm.mission.runtime", stale)
    with pytest.raises(acquire.IntegrityFailure, match="STALE_LOADED_G1SWARM_SUBMODULE"):
        acquire.target_import_witness()


def test_exact_1000_zero_command_continuation_and_parent_preservation(tmp_path):
    backend = FakeBackend(parent_result())
    outcome = run_fake(tmp_path, backend)
    assert outcome["status"] == "HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE"
    assert outcome["coverage"] == "COMPLETE_HOLD"
    assert backend.steps == backend.witness["hold_command_calls"] == 1000
    assert backend.snap["controller_counter"] == 8000
    assert len((tmp_path / "hold_incremental.jsonl").read_text().splitlines()) == 1000
    assert (tmp_path / "parent_result.json").is_file()
    entry = json.loads((tmp_path / "hold_entry.json").read_text())
    assert entry["terminal"]["snapshot"] == entry["pre_first_step"]
    assert len(entry["seed_speeds_mps"]) == 500


def test_fake_observer_ab_does_not_change_control_execution(tmp_path):
    """Offline seam check only; real MuJoCo observer equivalence remains unmeasured."""
    on_dir, off_dir = tmp_path / "on", tmp_path / "off"
    on_dir.mkdir()
    off_dir.mkdir()
    on, off = FakeBackend(parent_result(), observer_enabled=True), FakeBackend(parent_result(), observer_enabled=False)
    on_outcome, off_outcome = run_fake(on_dir, on), run_fake(off_dir, off)
    assert on.commands == off.commands == [[0.0, 0.0, 0.0]] * 1000
    assert on.steps == off.steps == 1000
    assert on.snap == off.snap
    assert on_outcome == off_outcome
    assert (on_dir / "hold_incremental.jsonl").exists()
    assert not (off_dir / "hold_incremental.jsonl").exists()


def test_normal_stop_control_can_enter_hold_without_failure_halt(tmp_path):
    backend = FakeBackend(parent_result(normal=True), parent_steps=5991)
    outcome = run_fake(tmp_path, backend, cell_index=2)
    assert outcome["status"] == "HOLD_SUCCEEDED_BOUNDED_IN_THIS_STATE"
    assert outcome["parent_halt_status"] is None


@pytest.mark.parametrize("parent,status", [
    (parent_result(has_halt=False), "HALT_NOT_REQUESTED_NO_HOLD"),
    (parent_result(halt_status="HALT_FAILED"), "HALT_FAILED_NO_HOLD"),
    (parent_result(normal=True) | {"completed_nodes": 2}, "CONTROL_FAILED_NO_HOLD"),
])
def test_no_qualifying_terminal_never_steps(tmp_path, parent, status):
    normal = bool(parent.get("mission_success"))
    backend = FakeBackend(parent, parent_steps=5991 if normal else 7139)
    outcome = run_fake(tmp_path, backend, cell_index=2 if normal else 0)
    assert outcome["status"] == status and backend.steps == 0
    assert not (tmp_path / "hold_entry.json").exists()


def test_unsafe_early_stop_is_scientific_failure_with_partial_rows(tmp_path):
    backend = FakeBackend(parent_result(), standing=False)
    outcome = run_fake(tmp_path, backend)
    assert outcome["status"] == "HOLD_FAILED"
    assert outcome["coverage"] == "PARTIAL_PHYSICAL_UNSAFE"
    assert backend.steps == 1


def test_complete_rolling_mean_failure_is_retained(tmp_path):
    backend = FakeBackend(parent_result(), speeds=[0.2] * 999 + [0.05])
    outcome = run_fake(tmp_path, backend)
    assert outcome["status"] == "HOLD_FAILED"
    assert not outcome["checks"]["rolling_mean"]
    assert outcome["checks"]["final_speed"]


def test_hold_path_is_independent_frozen_criterion():
    backend = FakeBackend(parent_result())
    rows = [{"speed_mps": 0.05, "position_m": [0.0003 * (index + 1), 0.0, 0.8],
             "finite": True, "raw_finite": True, "standing": True, "fallen": False}
            for index in range(1000)]
    scored = acquire.assess_hold(rows, [0.1] * 500, SPEC, backend.terminal)
    assert scored["status"] == "HOLD_FAILED"
    assert scored["checks"]["rolling_mean"] and scored["checks"]["final_speed"]
    assert not scored["checks"]["xy_path_length"]


def test_backend_error_is_technical_partial_and_no_retry(tmp_path):
    backend = FakeBackend(parent_result(), fail_step=4)
    outcome = run_fake(tmp_path, backend)
    assert outcome["status"] == "TECHNICAL_PARTIAL"
    assert outcome["hold_observed_steps"] == 4
    assert backend.witness["hold_command_calls"] == 5


@pytest.mark.parametrize("failure_type", [acquire.IntegrityFailure, acquire.BudgetFailure])
def test_integrity_or_budget_exception_cannot_be_censored_as_technical(tmp_path, failure_type):
    backend = FakeBackend(parent_result(), fail_step=0, fail_exception=failure_type)
    with pytest.raises(failure_type, match="synthetic backend fault"):
        run_fake(tmp_path, backend)
    assert backend.steps == 0
    assert not (tmp_path / "outcome.json").exists()


def test_mutated_terminal_is_integrity_failure_before_step(tmp_path):
    backend = FakeBackend(parent_result(), continuity_change=True)
    with pytest.raises(acquire.IntegrityFailure, match="TERMINAL_STOP_TO_HOLD_ENTRY_CHANGED"):
        run_fake(tmp_path, backend)
    assert backend.steps == 0


def test_controller_reset_during_hold_is_integrity_failure(tmp_path):
    backend = FakeBackend(parent_result(), reset_on_hold=True)
    with pytest.raises(acquire.IntegrityFailure, match="FORBIDDEN_RESET_OR_DISPATCH"):
        run_fake(tmp_path, backend)


def test_missing_first_crossing_seed_cannot_pass(tmp_path):
    backend = FakeBackend(parent_result())
    backend.terminal["stop_poststep_speeds"] = [0.1] * 499
    outcome = run_fake(tmp_path, backend)
    assert outcome["status"] == "INCONCLUSIVE_MISSING_EVIDENCE"
    assert outcome["coverage"] == "NO_HOLD"
    assert backend.steps == 0


def test_native_budget_refuses_unaffordable_hold_before_step(tmp_path):
    backend = FakeBackend(parent_result(), parent_steps=9900)
    backend.snap["native_steps"] = 9900
    backend.terminal["snapshot"]["native_steps"] = 9900
    backend.terminal["skill_return_snapshot"]["native_steps"] = 9900
    with pytest.raises(acquire.BudgetFailure, match="CELL_NATIVE_STEPS_CANNOT_FIT_HOLD"):
        run_fake(tmp_path, backend)
    assert backend.steps == 0


def test_reset_contract_allows_parent_controller_only():
    assert acquire.reset_permitted("simulation", "initialization", False)
    assert acquire.reset_permitted("native", "initialization", False)
    assert acquire.reset_permitted("controller", "parent", False)
    for phase in ("parent", "hold"):
        assert not acquire.reset_permitted("simulation", phase, False)
        assert not acquire.reset_permitted("native", phase, False)
    assert not acquire.reset_permitted("controller", "parent", True)
    assert not acquire.reset_permitted("controller", "hold", True)
    assert not acquire.reset_permitted("keyframe", "initialization", False)


def test_historical_prefix_is_exact_and_hash_checked(tmp_path):
    cell = SPEC["cells_in_order"][0]
    arm = cell["m24_state"] + "--" + cell["historical_arm"]
    member_name = "experiments/m2/cross_state_reliability_001/artifacts/" + arm + "/predecision_native_trace.json"
    observed = [{"time_s": 0.002, "qpos": [1], "qvel": [2], "ctrl": [3],
                 "xfrc_applied": [4], "controller": {"_counter": 1}}]
    payload = json.dumps(observed).encode()
    archive_dir = tmp_path / "experiments/m2/cross_state_reliability_archives_001"
    raw_dir = tmp_path / "experiments/m2/cross_state_reliability_analysis_001"
    archive_dir.mkdir(parents=True)
    raw_dir.mkdir(parents=True)
    archive_path = archive_dir / (arm + ".tar.gz")
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo(member_name)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    (archive_dir / "manifest.json").write_text(json.dumps({"archives": {archive_path.name: {
        "sha256": acquire.sha256(archive_path)}}}), encoding="utf8")
    (raw_dir / "raw_evidence_manifest.json").write_text(json.dumps({"files": {member_name: {
        "sha256": hashlib.sha256(payload).hexdigest()}}}), encoding="utf8")
    assert acquire.verify_historical_parent_native(cell, observed, root=tmp_path)["steps"] == 1
    with pytest.raises(acquire.IntegrityFailure, match="PREFIX_MISMATCH"):
        acquire.verify_historical_parent_native(cell, [observed[0] | {"qpos": [99]}], root=tmp_path)


def test_authority_gate_rejects_before_backend_or_output(tmp_path):
    output = tmp_path / "would_be_campaign"
    with pytest.raises(PermissionError, match="authorize-physics"):
        acquire.acquire(authorize_physics=False, readiness_sha256="0" * 64, output=output)
    assert not output.exists()


def test_external_supervisor_kills_blocked_nonphysics_worker(tmp_path):
    with pytest.raises(acquire.BudgetFailure, match="HARD_WALL_WATCHDOG"):
        acquire.supervise([sys.executable, "-c", "import time; time.sleep(10)"], tmp_path, 0.1)
    receipt = json.loads((tmp_path / "supervisor_timeout.json").read_text(encoding="utf8"))
    assert receipt["status"] == "PARTIAL_STOPPED" and receipt["no_retry"] is True


def test_campaign_stops_on_technical_partial_without_launching_next_cell(tmp_path, monkeypatch):
    output = tmp_path / "single_attempt_campaign"
    launched = []
    monkeypatch.setattr(acquire, "preflight", lambda readiness: (SPEC, M24, {}))

    def fake_supervise(command, run_dir, timeout_s):
        launched.append(run_dir.name)
        (run_dir / "outcome.json").write_text(json.dumps({
            "cell_id": run_dir.name, "status": "TECHNICAL_PARTIAL",
            "coverage": "PARTIAL_TECHNICAL"}), encoding="utf8")
        (run_dir / "witness.json").write_text(json.dumps({"native_steps": 0}), encoding="utf8")
        (run_dir / "native_incremental.jsonl").write_text("", encoding="utf8")

    monkeypatch.setattr(acquire, "supervise", fake_supervise)
    with pytest.raises(RuntimeError, match="CELL_TECHNICAL_PARTIAL_NO_RETRY"):
        acquire.acquire(authorize_physics=True, readiness_sha256="synthetic", output=output)
    assert launched == [SPEC["cells_in_order"][0]["id"]]
    receipt = json.loads((output / "campaign_receipt.json").read_text(encoding="utf8"))
    assert receipt["status"] == "PARTIAL_STOPPED" and receipt["no_retry"] is True
    assert receipt["completed_cells"][0]["status"] == "TECHNICAL_PARTIAL"


def test_between_cell_wall_expiry_writes_partial_receipt(tmp_path, monkeypatch):
    output = tmp_path / "campaign_wall"
    monkeypatch.setattr(acquire, "preflight", lambda readiness: (SPEC, M24, {}))
    ticks = iter((0.0, 0.0, 361.0))
    monkeypatch.setattr(acquire.time, "perf_counter", lambda: next(ticks))
    launched = []

    def fake_supervise(command, run_dir, timeout_s):
        launched.append(run_dir.name)
        (run_dir / "outcome.json").write_text(json.dumps({
            "cell_id": run_dir.name, "status": "HOLD_FAILED", "coverage": "COMPLETE_HOLD"}), encoding="utf8")
        (run_dir / "witness.json").write_text(json.dumps({"native_steps": 0}), encoding="utf8")
        (run_dir / "native_incremental.jsonl").write_text("", encoding="utf8")

    monkeypatch.setattr(acquire, "supervise", fake_supervise)
    with pytest.raises(acquire.BudgetFailure, match="CAMPAIGN_WALL_BUDGET_EXHAUSTED"):
        acquire.acquire(authorize_physics=True, readiness_sha256="synthetic", output=output)
    receipt = json.loads((output / "campaign_receipt.json").read_text(encoding="utf8"))
    assert receipt["status"] == "PARTIAL_STOPPED" and receipt["failed_cell"] == SPEC["cells_in_order"][1]["id"]
    assert launched == [SPEC["cells_in_order"][0]["id"]]
