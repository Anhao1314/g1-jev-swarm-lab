"""Strict, simulator-free projection of one sealed M2.3b same-session run.

This module does not acquire a robot state. Its only inputs are existing,
hash-pinned files and the separately reviewed official-model joint map. It
does not construct a simulation, run a controller, or write historical evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import struct
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


class EvidenceIntegrityError(ValueError):
    """Frozen evidence or its model binding cannot be safely projected."""


SOURCE_MANIFEST_SHA256 = "0a60a24d442af9023e51aa540f24e974e959035ba9f7213cab7fd44a61b02cfd"
ASSET_RECEIPT_SHA256 = "4b286abee7a035ac241d3811362215f7f17baff516f5f3c7f34257b83d4350e0"
MODEL_XML_SHA256 = "c4d41ea03c6059fde9b796033f9b15c146cfc5723fb774b4eb047a4846def02f"
MODEL_URDF_SHA256 = "52a0f729252cba764f610136f0772573e55694024b888da93abd5ad23aba0152"
JOINT_MAP_SHA256 = "c4ab6c3bfe81399715ff63b4f5008d95cd31a9ae859547ed17141fd9ced1e56a"
MODEL_XML_PATH = "third_party/unitree_rl_gym/resources/robots/g1_description/g1_12dof.xml"
MODEL_URDF_PATH = "third_party/unitree_rl_gym/resources/robots/g1_description/g1_12dof.urdf"
JOINT_NAMES = (
    "left_hip_pitch_joint", "left_hip_roll_joint", "left_hip_yaw_joint",
    "left_knee_joint", "left_ankle_pitch_joint", "left_ankle_roll_joint",
    "right_hip_pitch_joint", "right_hip_roll_joint", "right_hip_yaw_joint",
    "right_knee_joint", "right_ankle_pitch_joint", "right_ankle_roll_joint",
)
RUN_NAME = "trusted_authorized"
RUN_RECEIPT_SHA256 = "cda9a983f897a3f913289fce3539d6c1d89c4d6fd29e59ebaccb7ad3e6a1a562"
RUN_POSE_SHA256 = "3812ff591c0fa61183a6c9e8cebf46518eba7d404b4b7fdfa505a7c50747029d"
PARENT_MISSION_ID = "m2-open-loop-walk6-turn45-stop"
NEW_MISSION_ID = "m22-new-walk4-turn45-stop"
SOURCE_MODEL_FILES = {
    "configs/robot/g1_locomotion_12dof.yaml": "419036675b57be102ef4ba34839aa3a8675d3ffcff3a8f66d92be2f52d9d897e",
    "third_party/unitree_rl_gym/resources/robots/g1_description/scene.xml": "08d6297979ea3f62768212b6f115f342a9c4dcdde1968d33330c292a0238921f",
    MODEL_XML_PATH: MODEL_XML_SHA256,
    MODEL_URDF_PATH: MODEL_URDF_SHA256,
}


def _digest(path: Path) -> str:
    if not path.is_file():
        raise EvidenceIntegrityError(f"required file missing: {path}")
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _require_hash(path: Path, expected: str) -> None:
    if _digest(path) != expected:
        raise EvidenceIntegrityError(f"SHA256 mismatch: {path}")


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceIntegrityError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceIntegrityError(f"JSON object required: {path}")
    return value


def _project_root(run_dir: Path) -> Path:
    # Keep the bridge bounded to the reviewed M2.3b artifact path. This also
    # prevents accidentally treating an unrelated run with the same name as it.
    suffix = ("experiments", "m2", "trusted_handoff_qualification_001", "artifacts")
    if tuple(run_dir.parts[-5:-1]) != suffix:
        raise EvidenceIntegrityError("run must be under frozen M2.3b artifacts directory")
    return run_dir.parents[4]


def _load_joint_map(path: Path, asset_receipt_path: Path) -> dict[str, Any]:
    _require_hash(path, JOINT_MAP_SHA256)
    _require_hash(asset_receipt_path, ASSET_RECEIPT_SHA256)
    mapping = _json(path)
    receipt = _json(asset_receipt_path)
    official = {entry.get("path"): entry for entry in receipt.get("files", [])}
    for source_path, source_sha in (
        (MODEL_XML_PATH, MODEL_XML_SHA256),
        (MODEL_URDF_PATH, MODEL_URDF_SHA256),
    ):
        entry = official.get(source_path)
        if not isinstance(entry, dict) or entry.get("sha256") != source_sha:
            raise EvidenceIntegrityError(f"official asset receipt mismatch: {source_path}")
    expected = {
        "schema_version": "ros_observation_joint_map_v0.1",
        "joint_xml": MODEL_XML_PATH,
        "joint_xml_sha256": MODEL_XML_SHA256,
        "urdf": MODEL_URDF_PATH,
        "urdf_sha256": MODEL_URDF_SHA256,
        "official_asset_receipt_sha256": ASSET_RECEIPT_SHA256,
        "base_body": "pelvis",
        "world_frame": "mujoco_world",
        "variant": "g1_12dof",
        "model_dimensions": {"nq": 19, "nv": 18, "nu": 12},
        "jointstate_effort": "OMITTED_UNMEASURED",
        "unitree_hardware_lowstate_mapping": "NOT_ASSERTED",
        "physics_steps": 0,
        "policy_inferences": 0,
        "base_free_joint": {
            "name": "floating_base_joint",
            "qpos_position_indices": [0, 1, 2],
            "qpos_quaternion_wxyz_indices": [3, 4, 5, 6],
            "qvel_linear_indices": [0, 1, 2],
            "qvel_angular_indices": [3, 4, 5],
        },
    }
    for key, wanted in expected.items():
        if mapping.get(key) != wanted:
            raise EvidenceIntegrityError(f"joint map {key} does not match pinned official model")
    joint_rows = mapping.get("joints")
    expected_rows = [
        {"name": name, "joint_type": "hinge", "qpos_index": q, "qvel_index": v}
        for name, q, v in zip(JOINT_NAMES, range(7, 19), range(6, 18), strict=True)
    ]
    if joint_rows != expected_rows:
        raise EvidenceIntegrityError("joint names/addresses differ from pinned compiled model")
    return {
        "world_frame": mapping["world_frame"], "base_body": mapping["base_body"],
        "joint_names": list(JOINT_NAMES), "qpos_indices": list(range(7, 19)),
        "qvel_indices": list(range(6, 18)),
    }


def verify_joint_map_sources(
    joint_map_path: str | Path,
    xml_path: str | Path,
    urdf_path: str | Path,
    asset_receipt_path: str | Path,
) -> None:
    """Optional model-side audit; parses official assets without loading MuJoCo.

    The XML worldbody joint order establishes the free-base and hinge qpos/qvel
    addresses. The matching official URDF establishes ROS-visible joint names.
    A runtime without model assets can use the already pinned map and receipt.
    """

    xml_file, urdf_file = Path(xml_path), Path(urdf_path)
    mapping = _load_joint_map(Path(joint_map_path), Path(asset_receipt_path))
    _require_hash(xml_file, MODEL_XML_SHA256)
    _require_hash(urdf_file, MODEL_URDF_SHA256)
    try:
        xml = ET.parse(xml_file).getroot()
        urdf = ET.parse(urdf_file).getroot()
    except (OSError, ET.ParseError) as exc:
        raise EvidenceIntegrityError("official model XML/URDF cannot be parsed") from exc
    worldbody = xml.find("worldbody")
    if worldbody is None:
        raise EvidenceIntegrityError("official MJCF worldbody missing")
    joints = list(worldbody.iter("joint"))
    if len(joints) != 13 or joints[0].get("type") != "free":
        raise EvidenceIntegrityError("official MJCF is not one free base plus 12 hinges")
    if any(j.get("type", "hinge") != "hinge" for j in joints[1:]):
        raise EvidenceIntegrityError("official MJCF contains a non-hinge leg joint")
    mjcf_names = [j.get("name") for j in joints[1:]]
    urdf_names = [j.get("name") for j in urdf.iter("joint") if j.get("type") != "fixed"]
    if mjcf_names != mapping["joint_names"] or urdf_names != mapping["joint_names"]:
        raise EvidenceIntegrityError("official MJCF/URDF joint names differ from pinned map")


@dataclass(frozen=True)
class ReplaySample:
    index: int
    time_ns: int
    frame_id: str
    child_frame_id: str
    base_position_m: tuple[float, float, float]
    base_quaternion_xyzw: tuple[float, float, float, float]
    joint_names: tuple[str, ...]
    joint_position_rad: tuple[float, ...]
    joint_velocity_rad_s: tuple[float, ...]
    source_locator: str
    source_row_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "time_ns": self.time_ns,
            "frame_id": self.frame_id, "child_frame_id": self.child_frame_id,
            "base_position_m": list(self.base_position_m),
            "base_quaternion_xyzw": list(self.base_quaternion_xyzw),
            "joint_names": list(self.joint_names),
            "joint_position_rad": list(self.joint_position_rad),
            "joint_velocity_rad_s": list(self.joint_velocity_rad_s),
            "source_locator": self.source_locator,
            "source_row_sha256": self.source_row_sha256,
        }


@dataclass(frozen=True)
class ReplayEvent:
    kind: str
    event_time_ns: int
    simulation_step: int
    source_locator: str
    source_sha256: str
    mission_id: str
    mission_state: str | None
    node_id: str | None = None
    skill: str | None = None
    skill_status: str | None = None
    feedback_action: str | None = None
    reason: str | None = None
    source_sequence: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(vars(self))


@dataclass(frozen=True)
class FrozenReplay:
    mission_id: str
    mission_state: str
    parent_mission_id: str
    parent_state: str
    run_name: str
    pose_sha256: str
    result_sha256: str
    parent_result_sha256: str
    new_result_sha256: str
    receipt_sha256: str
    source_manifest_sha256: str
    joint_map_sha256: str
    samples: tuple[ReplaySample, ...]
    events: tuple[ReplayEvent, ...]


def _row_digest(index: int, time_s: np.float64, qpos: np.ndarray, qvel: np.ndarray, ctrl: np.ndarray) -> str:
    """SHA256 of index (little-endian int64) + four little-endian float64 arrays."""
    h = sha256(struct.pack("<q", index))
    for item in (np.asarray([time_s]), qpos, qvel, ctrl):
        h.update(np.asarray(item, dtype="<f8").tobytes(order="C"))
    return h.hexdigest()


def load_frozen_replay(
    run_dir: str | Path,
    joint_map_path: str | Path,
    *,
    asset_receipt_path: str | Path | None = None,
) -> FrozenReplay:
    """Load the sealed M2.3b same-session handoff, without physical execution."""

    directory = Path(run_dir).resolve()
    root = _project_root(directory)
    if directory.name != RUN_NAME:
        raise EvidenceIntegrityError("run is outside the reviewed M2.3b case")
    asset_receipt = (
        Path(asset_receipt_path)
        if asset_receipt_path is not None
        else root / "experiments/m2/cross_state_reliability_readiness_001/asset_restore.json"
    )
    map_file = Path(joint_map_path)
    mapping = _load_joint_map(map_file, asset_receipt)
    study = root / "experiments/m2/trusted_handoff_qualification_001"
    manifest_file = study / "source_manifest.json"
    receipt_file = directory / "receipt.json"
    pose_file = directory / "poses.npz"
    _require_hash(manifest_file, SOURCE_MANIFEST_SHA256)
    _require_hash(receipt_file, RUN_RECEIPT_SHA256)
    manifest, receipt = _json(manifest_file), _json(receipt_file)
    source_files = manifest.get("files")
    if not isinstance(source_files, dict) or any(
        source_files.get(path) != digest for path, digest in SOURCE_MODEL_FILES.items()
    ):
        raise EvidenceIntegrityError("M2.3b source freeze does not bind the official G1 model")
    if any((
        receipt.get("run") != RUN_NAME,
        receipt.get("arm") != RUN_NAME,
        receipt.get("source_manifest_sha256") != SOURCE_MANIFEST_SHA256,
        receipt.get("total_physics_steps") != 13128,
        receipt.get("node_dispatch_count") != 4,
        receipt.get("new_executor_dispatch_count") != 1,
        receipt.get("parent_state") != "FAILED",
        receipt.get("parent_halt") != "HALT_SUCCEEDED",
        receipt.get("checks_passed") is not True,
    )):
        raise EvidenceIntegrityError("M2.3b receipt contract differs from frozen run")
    artifact_hashes = receipt.get("artifact_files")
    if not isinstance(artifact_hashes, dict) or len(artifact_hashes) != 12:
        raise EvidenceIntegrityError("M2.3b artifact receipt is incomplete")
    required = {
        "poses.npz", "parent_result.json", "new_result.json", "continuity.json",
        "lifecycle_events.json", "handoff_events.json", "qualification.json",
    }
    if not required.issubset(artifact_hashes):
        raise EvidenceIntegrityError("required same-session evidence is absent")
    for name, digest in artifact_hashes.items():
        if not isinstance(name, str) or Path(name).name != name or not isinstance(digest, str):
            raise EvidenceIntegrityError("artifact receipt contains an unsafe path or digest")
        _require_hash(directory / name, digest)
    if artifact_hashes["poses.npz"] != RUN_POSE_SHA256:
        raise EvidenceIntegrityError("trajectory hash differs from frozen M2.3b run")
    parent_result = _json(directory / "parent_result.json")
    new_result = _json(directory / "new_result.json")
    continuity = _json(directory / "continuity.json")
    try:
        lifecycle = json.loads((directory / "lifecycle_events.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceIntegrityError("lifecycle event stream cannot be parsed") from exc
    if not isinstance(lifecycle, list) or len(lifecycle) != 12:
        raise EvidenceIntegrityError("lifecycle event stream differs from frozen run")
    halt = parent_result.get("physical_halt")
    after_parent = continuity.get("after_parent")
    before_new = continuity.get("before_new_mission")
    final = continuity.get("final")
    if not all(isinstance(x, dict) for x in (halt, after_parent, before_new, final)):
        raise EvidenceIntegrityError("same-session boundary evidence is incomplete")
    if any((
        parent_result.get("mission_id") != PARENT_MISSION_ID,
        parent_result.get("state") != "FAILED",
        parent_result.get("simulation_steps_executed") != 6468,
        halt.get("status") != "HALT_SUCCEEDED",
        new_result.get("mission_id") != NEW_MISSION_ID,
        new_result.get("state") != "SUCCESS",
        new_result.get("simulation_steps_executed") != 5989,
        after_parent.get("session_steps") != 7139,
        before_new.get("session_steps") != 7139,
        final.get("session_steps") != 13128,
        after_parent.get("reset_calls") != before_new.get("reset_calls"),
        before_new.get("reset_calls") != final.get("reset_calls"),
    )):
        raise EvidenceIntegrityError("parent/Halt/new mission records differ from frozen run")
    for key in ("time_s", "qpos", "qvel", "ctrl", "session_identity", "simulation_identity", "controller_identity"):
        if after_parent.get(key) != before_new.get(key):
            raise EvidenceIntegrityError(f"same-session handoff changed {key}")
    try:
        with np.load(pose_file, allow_pickle=False) as bundle:
            if set(bundle.files) != {"time_s", "qpos", "qvel", "ctrl"}:
                raise EvidenceIntegrityError("pose bundle arrays differ from frozen schema")
            time_s, qpos, qvel, ctrl = (np.array(bundle[key], copy=True) for key in ("time_s", "qpos", "qvel", "ctrl"))
    except (OSError, ValueError, EOFError) as exc:
        raise EvidenceIntegrityError("pose bundle cannot be read safely") from exc
    count = len(time_s)
    if count != 528 or time_s.shape != (count,) or qpos.shape != (count, 19) or qvel.shape != (count, 18) or ctrl.shape != (count, 12):
        raise EvidenceIntegrityError("pose bundle dimensions do not match official 12-DOF model")
    if any(a.dtype != np.float64 or not np.isfinite(a).all() for a in (time_s, qpos, qvel, ctrl)):
        raise EvidenceIntegrityError("pose bundle must contain finite float64 state")
    if time_s[0] != 0 or np.any(np.diff(time_s) <= 0):
        raise EvidenceIntegrityError("simulation timestamps are not strictly increasing from zero")
    norms = np.linalg.norm(qpos[:, 3:7], axis=1)
    if not np.all(np.abs(norms - 1.0) <= 1e-6):
        raise EvidenceIntegrityError("base quaternion is not a unit orientation")
    boundary_time = after_parent["time_s"]
    boundary_indices = np.flatnonzero(time_s == boundary_time)
    if len(boundary_indices) != 1:
        raise EvidenceIntegrityError("recorded handoff state is absent from pose stream")
    boundary_index = int(boundary_indices[0])
    if boundary_index != 286 or any(
        not np.array_equal(array[boundary_index], after_parent[field])
        for array, field in ((qpos, "qpos"), (qvel, "qvel"), (ctrl, "ctrl"))
    ):
        raise EvidenceIntegrityError("pose at handoff does not match unchanged physical state")
    if any(
        not np.array_equal(array[-1], final[field])
        for array, field in ((qpos, "qpos"), (qvel, "qvel"), (ctrl, "ctrl"))
    ):
        raise EvidenceIntegrityError("final pose does not match same-session receipt")
    samples: list[ReplaySample] = []
    previous_time_ns = -1
    for index, seconds in enumerate(time_s):
        time_ns = round(float(seconds) * 1_000_000_000)
        if time_ns <= previous_time_ns:
            raise EvidenceIntegrityError("nanosecond timestamps are not strictly increasing")
        previous_time_ns = time_ns
        quat = qpos[index, 3:7]
        samples.append(ReplaySample(
            index=index, time_ns=time_ns,
            frame_id=mapping["world_frame"], child_frame_id=mapping["base_body"],
            base_position_m=tuple(float(v) for v in qpos[index, :3]),
            base_quaternion_xyzw=tuple(float(v) for v in (quat[1], quat[2], quat[3], quat[0])),
            joint_names=tuple(mapping["joint_names"]),
            joint_position_rad=tuple(float(v) for v in qpos[index, mapping["qpos_indices"]]),
            joint_velocity_rad_s=tuple(float(v) for v in qvel[index, mapping["qvel_indices"]]),
            source_locator=f"experiments/m2/trusted_handoff_qualification_001/artifacts/{directory.name}/poses.npz#frame={index}",
            source_row_sha256=_row_digest(index, seconds, qpos[index], qvel[index], ctrl[index]),
        ))
    parent_time_ns = round(float(parent_result["total_simulation_time_s"]) * 1_000_000_000)
    halt_time_ns = round(float(boundary_time) * 1_000_000_000)
    final_time_ns = samples[-1].time_ns
    if not (0 < parent_time_ns < halt_time_ns < final_time_ns):
        raise EvidenceIntegrityError("parent/Halt/new mission timing is not ordered")
    if abs(round(float(halt["final_state"]["simulation_time"]) * 1_000_000_000) - halt_time_ns) > 1:
        raise EvidenceIntegrityError("Halt terminal time differs from continuity evidence")
    if abs(round(float(new_result["total_simulation_time_s"]) * 1_000_000_000) - (final_time_ns - halt_time_ns)) > 1000:
        raise EvidenceIntegrityError("new mission duration differs from same-session trajectory")
    parent_node = parent_result["nodes"][0]
    feedback = parent_node.get("feedback_decision")
    if not isinstance(feedback, dict) or feedback.get("action") != "STOP_DEPENDENTS":
        raise EvidenceIntegrityError("parent strict failure feedback missing")
    base_locator = f"experiments/m2/trusted_handoff_qualification_001/artifacts/{directory.name}"
    events: list[ReplayEvent] = [
        ReplayEvent(
            kind="PARENT_STRICT_FAILURE", event_time_ns=parent_time_ns,
            simulation_step=6468,
            source_locator=f"{base_locator}/parent_result.json#/nodes/0/feedback_decision",
            source_sha256=artifact_hashes["parent_result.json"],
            mission_id=PARENT_MISSION_ID, mission_state="FAILED", node_id=parent_node.get("node_id"),
            skill=parent_node.get("skill"), feedback_action="STOP_DEPENDENTS",
        ),
        ReplayEvent(
            kind="HALT_SUCCEEDED", event_time_ns=halt_time_ns,
            simulation_step=7139,
            source_locator=f"{base_locator}/parent_result.json#/physical_halt/status",
            source_sha256=artifact_hashes["parent_result.json"],
            mission_id=PARENT_MISSION_ID, mission_state=None,
        ),
    ]
    previous_lifecycle_ns = halt_time_ns
    for index, entry in enumerate(lifecycle):
        if not isinstance(entry, dict) or entry.get("sequence") != index:
            raise EvidenceIntegrityError("lifecycle event sequence is malformed")
        timestamp = entry.get("simulation_time_s")
        if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise EvidenceIntegrityError("lifecycle simulation timestamp is missing")
        event_ns = round(float(timestamp) * 1_000_000_000)
        if event_ns < previous_lifecycle_ns or event_ns > final_time_ns:
            raise EvidenceIntegrityError("lifecycle events are outside same-session ordering")
        previous_lifecycle_ns = event_ns
        kind = entry.get("event")
        if not isinstance(kind, str) or not kind:
            raise EvidenceIntegrityError("lifecycle event kind missing")
        mission_id = entry.get("new_mission_id") or PARENT_MISSION_ID
        if mission_id not in (PARENT_MISSION_ID, NEW_MISSION_ID):
            raise EvidenceIntegrityError("lifecycle event mission identity changed")
        simulation_step = entry.get("simulation_steps")
        if not isinstance(simulation_step, int) or not 7139 <= simulation_step <= 13128:
            raise EvidenceIntegrityError("lifecycle simulation step is out of bounds")
        events.append(ReplayEvent(
            kind=kind, event_time_ns=event_ns, simulation_step=simulation_step,
            source_locator=f"{base_locator}/lifecycle_events.json#/{index}",
            source_sha256=artifact_hashes["lifecycle_events.json"],
            mission_id=mission_id,
            mission_state="SUCCESS" if kind == "new_mission_completed" else None,
            reason=entry.get("reason"), source_sequence=index,
        ))
    if lifecycle[8].get("event") != "new_mission_authorized" or lifecycle[9].get("event") != "new_mission_completed":
        raise EvidenceIntegrityError("authorized mission lifecycle entries missing")
    if events[10].event_time_ns != halt_time_ns or events[11].event_time_ns != final_time_ns:
        raise EvidenceIntegrityError("authorized mission event times differ from physical boundaries")
    return FrozenReplay(
        mission_id=NEW_MISSION_ID, mission_state="SUCCESS",
        parent_mission_id=PARENT_MISSION_ID, parent_state="FAILED", run_name=directory.name,
        pose_sha256=RUN_POSE_SHA256,
        result_sha256=artifact_hashes["new_result.json"],
        parent_result_sha256=artifact_hashes["parent_result.json"],
        new_result_sha256=artifact_hashes["new_result.json"],
        receipt_sha256=RUN_RECEIPT_SHA256, source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        joint_map_sha256=_digest(map_file), samples=tuple(samples), events=tuple(events),
    )
