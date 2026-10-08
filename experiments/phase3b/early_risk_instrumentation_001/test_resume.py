"""No-physics tests for the amended one-time acquisition entrypoint."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("early_risk_resume", HERE / "resume.py")
resume_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume_module)


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_real_original_pair_is_equivalent_without_new_physics():
    if not (HERE / "artifacts" / "eval-ws-01.observer_off.json").exists():
        pytest.skip("local ignored partial evidence is unavailable in this checkout")
    _, cases, historical = resume_module.validate_membership()
    resume_module.validate_original_pair(*cases[0], historical, HERE / "artifacts")


def test_original_partial_hash_mismatch_refuses_resume(tmp_path):
    study = tmp_path / "study"
    artifacts = study / "artifacts"
    artifacts.mkdir(parents=True)
    _json(study / "freeze_manifest_v2.json", {
        "schema": "phase3b1b_comparator_amendment_freeze_v2", "study_assets": {}})
    _json(study / "source_manifest.json", {"sources": {}})
    _json(study / "amendment_001.json", {
        "schema": "phase3b1b_timing_comparator_amendment_v1",
        "original_freeze_commit": "0400c3f9eb62b519845213658f52098b6c8005da",
        "first_case_rerun": False, "scientific_contract_changed": False,
        "remaining_execution_cap": 12,
        "original_partial_artifact_sha256": {"stopped.json": "wrong"}})
    _json(artifacts / "stopped.json", {"status": "PARTIAL_STOPPED"})
    with pytest.raises(AssertionError, match="Original partial artifact drift"):
        resume_module.validate_resume_freeze(study)


def test_resume_refuses_unexpected_existing_artifacts(tmp_path, monkeypatch):
    study = tmp_path / "study"
    artifacts = study / "artifacts"
    artifacts.mkdir(parents=True)
    for name in ("started.json", "stopped.json", "eval-ws-01.observer_off.json",
                 "eval-ws-01.observer_on.json", "unexpected.json"):
        _json(artifacts / name, {})
    cases = [({"id": case_id}, {0}) for case_id in
             ["eval-ws-01", "eval-tw-01", "eval-tw-02", "eval-sw-02",
              "eval-sw-03", "primitive-walk-4", "sequence-mixed-12m"]]
    monkeypatch.setattr(resume_module, "validate_resume_freeze", lambda _: {
        "original_partial_artifact_sha256": {
            name: "hash" for name in ("started.json", "stopped.json",
              "eval-ws-01.observer_off.json", "eval-ws-01.observer_on.json")},
        "remaining_case_order": [case["id"] for case, _ in cases[1:]]})
    monkeypatch.setattr(resume_module, "validate_membership", lambda _: (
        {"selected_nodes": []}, cases, {}))
    monkeypatch.setattr(resume_module, "replay_observed", lambda *_args, **_kwargs:
                        pytest.fail("physics must not start"))
    with pytest.raises(FileExistsError, match="Unexpected acquisition artifact"):
        resume_module.resume(study)


def test_resume_stops_on_first_new_failure_without_running_later_case(tmp_path, monkeypatch):
    study = tmp_path / "study"
    artifacts = study / "artifacts"
    artifacts.mkdir(parents=True)
    originals = ("started.json", "stopped.json", "eval-ws-01.observer_off.json",
                 "eval-ws-01.observer_on.json")
    for name in originals:
        _json(artifacts / name, {"original": name})
    cases = [({"id": case_id}, {0}) for case_id in
             ["eval-ws-01", "eval-tw-01", "eval-tw-02", "eval-sw-02",
              "eval-sw-03", "primitive-walk-4", "sequence-mixed-12m"]]
    monkeypatch.setattr(resume_module, "validate_resume_freeze", lambda _: {
        "original_partial_artifact_sha256": {name: "hash" for name in originals},
        "remaining_case_order": [case["id"] for case, _ in cases[1:]]})
    monkeypatch.setattr(resume_module, "validate_membership", lambda _: (
        {"selected_nodes": [0]}, cases, {}))
    monkeypatch.setattr(resume_module, "validate_original_pair", lambda *_: None)
    calls = []

    def replay(case, _nodes, *, enabled):
        calls.append((case["id"], enabled))
        if enabled:
            raise AssertionError("mock observer failure")
        return {"record": {}, "observer": {}}

    monkeypatch.setattr(resume_module, "replay_observed", replay)
    monkeypatch.setattr(resume_module, "validate_observation", lambda *_: None)
    with pytest.raises(AssertionError, match="mock observer failure"):
        resume_module.resume(study)
    assert calls == [("eval-tw-01", False), ("eval-tw-01", True)]
    assert (artifacts / "eval-tw-01.observer_off.json").is_file()
    assert not (artifacts / "eval-tw-02.observer_off.json").exists()
    assert not (artifacts / "resumed_completed.json").exists()
    assert json.loads((artifacts / "stopped.json").read_text()) == {"original": "stopped.json"}
    assert json.loads((artifacts / "resumed_stopped.json").read_text())["status"] == "PARTIAL_STOPPED"
