"""Evidence bundle tests."""

from __future__ import annotations

import json

from g1swarm.evidence import MANIFEST_FIELDS, EnvironmentInfo, RunManifest, RunRecorder


def _manifest() -> RunManifest:
    return RunManifest(
        experiment_id="test-experiment",
        run_id="run-000",
        task="unit test",
        config={"value": 1},
        environment=EnvironmentInfo(
            os="test-os",
            python_version="3.11.9",
            mujoco_version="3.15.0",
            torch_version=None,
            cuda_version=None,
            gpu=None,
            git_commit="deadbeef",
        ),
        seed=0,
        g1_model_source="unitree",
        g1_model_commit="abc123",
        controller_source=None,
        controller_version=None,
    )


def test_manifest_contains_every_required_field() -> None:
    manifest = _manifest()
    manifest.validate()
    payload = manifest.to_dict()
    for field in MANIFEST_FIELDS:
        assert field in payload
    assert payload["result"] is None


def test_recorder_writes_bundle(tmp_path) -> None:
    recorder = RunRecorder("test-experiment", "run-000", root=tmp_path, manifest=_manifest())
    recorder.log_event("step", {"step": 1})
    recorder.finish({"status": "SUCCESS"}, {"metric": 1.5})

    manifest = json.loads((tmp_path / "test-experiment" / "run-000" / "manifest.json").read_text("utf-8"))
    metrics = json.loads((tmp_path / "test-experiment" / "run-000" / "metrics.json").read_text("utf-8"))
    events = (tmp_path / "test-experiment" / "run-000" / "events.jsonl").read_text("utf-8").strip().splitlines()

    assert manifest["result"]["status"] == "SUCCESS"
    assert "finished_at" in manifest
    assert metrics["metric"] == 1.5
    assert len(events) == 2
    assert json.loads(events[0])["event"] == "step"
