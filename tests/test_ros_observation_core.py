"""Offline-only checks for the sealed M2.3b-to-ROS observation projection."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import struct

import numpy as np
import pytest

from g1swarm.ros_observation import EvidenceIntegrityError, load_frozen_replay


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "experiments/m2/trusted_handoff_qualification_001"
RUN = STUDY / "artifacts/trusted_authorized"
MAP = ROOT / "experiments/ros_observation_bridge_001/joint_map.json"
ASSET_RECEIPT = ROOT / "experiments/m2/cross_state_reliability_readiness_001/asset_restore.json"


def _copied_run(tmp_path: Path) -> tuple[Path, Path, Path]:
    study = tmp_path / "experiments/m2/trusted_handoff_qualification_001"
    destination = study / "artifacts/trusted_authorized"
    destination.mkdir(parents=True)
    receipt = json.loads((RUN / "receipt.json").read_text(encoding="utf-8"))
    for name in ("receipt.json", *receipt["artifact_files"]):
        shutil.copyfile(RUN / name, destination / name)
    shutil.copyfile(STUDY / "source_manifest.json", study / "source_manifest.json")
    asset = tmp_path / "experiments/m2/cross_state_reliability_readiness_001/asset_restore.json"
    asset.parent.mkdir(parents=True)
    shutil.copyfile(ASSET_RECEIPT, asset)
    joint_map = tmp_path / "experiments/ros_observation_bridge_001/joint_map.json"
    joint_map.parent.mkdir(parents=True)
    shutil.copyfile(MAP, joint_map)
    return destination, joint_map, asset


def test_only_sealed_same_session_run_projects():
    replay = load_frozen_replay(RUN, MAP)
    assert replay.run_name == "trusted_authorized"
    assert replay.parent_mission_id == "m2-open-loop-walk6-turn45-stop"
    assert replay.parent_state == "FAILED"
    assert replay.mission_id == "m22-new-walk4-turn45-stop"
    assert replay.mission_state == "SUCCESS"
    assert replay.pose_sha256 == "3812ff591c0fa61183a6c9e8cebf46518eba7d404b4b7fdfa505a7c50747029d"
    assert len(replay.samples) == 528
    assert len(replay.events) == 14
    assert [sample.index for sample in replay.samples] == list(range(528))
    assert replay.samples[0].time_ns == 0
    assert replay.samples[-1].time_ns == 26_256_000_000
    assert replay.samples[286].time_ns == 14_278_000_000
    assert all(b.time_ns > a.time_ns for a, b in zip(replay.samples, replay.samples[1:]))
    assert json.loads(json.dumps(replay.samples[0].to_dict()))["index"] == 0


def test_joint_pose_frame_and_source_row_digest_are_exact():
    replay = load_frozen_replay(RUN, MAP)
    with np.load(RUN / "poses.npz", allow_pickle=False) as raw:
        for index in (0, 259, 286, len(replay.samples) - 1):
            sample = replay.samples[index]
            qpos, qvel, ctrl, seconds = (
                raw["qpos"][index], raw["qvel"][index],
                raw["ctrl"][index], raw["time_s"][index],
            )
            assert sample.time_ns == round(float(seconds) * 1_000_000_000)
            assert sample.frame_id == "mujoco_world"
            assert sample.child_frame_id == "pelvis"
            assert sample.base_position_m == tuple(qpos[:3])
            assert sample.base_quaternion_xyzw == (qpos[4], qpos[5], qpos[6], qpos[3])
            assert sample.joint_position_rad == tuple(qpos[7:19])
            assert sample.joint_velocity_rad_s == tuple(qvel[6:18])
            assert len(sample.joint_names) == 12
            h = sha256(struct.pack("<q", index))
            for array in (np.asarray([seconds]), qpos, qvel, ctrl):
                h.update(np.asarray(array, dtype="<f8").tobytes(order="C"))
            assert sample.source_row_sha256 == h.hexdigest()
            assert sample.source_locator.endswith(f"poses.npz#frame={index}")


def test_failure_halt_authorization_and_rejection_keep_saved_order():
    replay = load_frozen_replay(RUN, MAP)
    failure, halt = replay.events[:2]
    assert (failure.kind, failure.event_time_ns, failure.simulation_step) == (
        "PARENT_STRICT_FAILURE", 12_936_000_000, 6468
    )
    assert failure.feedback_action == "STOP_DEPENDENTS"
    assert failure.mission_state == "FAILED"
    assert (halt.kind, halt.event_time_ns, halt.simulation_step) == (
        "HALT_SUCCEEDED", 14_278_000_000, 7139
    )
    assert [(event.kind, event.source_sequence) for event in replay.events[2:]] == [
        ("post_halt_assessment", 0), ("post_halt_assessment", 1),
        ("trusted_handoff_prepared", 2), ("post_halt_assessment", 3),
        ("post_halt_assessment", 4), ("test_only_authorization_issued", 5),
        ("trusted_handoff_verified", 6), ("post_halt_assessment", 7),
        ("new_mission_authorized", 8), ("new_mission_completed", 9),
        ("trusted_handoff_dispatch_completed", 10), ("trusted_handoff_rejected", 11),
    ]
    assert replay.events[10].event_time_ns == halt.event_time_ns
    assert replay.events[11].event_time_ns == replay.samples[-1].time_ns
    assert replay.events[11].mission_state == "SUCCESS"
    assert replay.events[-1].reason == "UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF"
    assert replay.events[-1].mission_state is None
    assert all(e.mission_state is None for e in replay.events[1:11])
    assert all(e.source_sha256 and e.source_locator for e in replay.events)
    assert all("token" not in json.dumps(e.to_dict()).lower() for e in replay.events)


@pytest.mark.parametrize("target", [
    "poses.npz", "parent_result.json", "new_result.json", "continuity.json",
    "lifecycle_events.json", "handoff_events.json", "qualification.json",
])
def test_all_frozen_artifact_hashes_reject_tampering(tmp_path, target):
    run, joint_map, asset = _copied_run(tmp_path)
    path = run / target
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(EvidenceIntegrityError, match="SHA256 mismatch"):
        load_frozen_replay(run, joint_map, asset_receipt_path=asset)


@pytest.mark.parametrize("target", ["receipt", "source_manifest", "joint_map", "asset_receipt"])
def test_independent_pins_reject_tampering(tmp_path, target):
    run, joint_map, asset = _copied_run(tmp_path)
    path = {
        "receipt": run / "receipt.json",
        "source_manifest": run.parents[1] / "source_manifest.json",
        "joint_map": joint_map,
        "asset_receipt": asset,
    }[target]
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(EvidenceIntegrityError, match="SHA256 mismatch"):
        load_frozen_replay(run, joint_map, asset_receipt_path=asset)


def test_unreviewed_run_and_missing_source_fail_closed(tmp_path):
    run, joint_map, asset = _copied_run(tmp_path)
    other = run.with_name("new_physics_or_retry")
    run.rename(other)
    with pytest.raises(EvidenceIntegrityError, match="reviewed M2.3b"):
        load_frozen_replay(other, joint_map, asset_receipt_path=asset)
    other.rename(run)
    (run / "poses.npz").unlink()
    with pytest.raises(EvidenceIntegrityError, match="required file missing"):
        load_frozen_replay(run, joint_map, asset_receipt_path=asset)
