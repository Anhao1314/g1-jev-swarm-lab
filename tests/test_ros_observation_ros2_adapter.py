"""MOCK_CONTRACT_ONLY checks; these do not demonstrate actual ROS 2 delivery."""

from __future__ import annotations

from dataclasses import dataclass
import json
import itertools
from types import ModuleType, SimpleNamespace
import sys

import pytest

from experiments.ros_observation_bridge_001 import replay_ros2 as bridge
from experiments.ros_observation_bridge_001 import probe_ros2 as probe


class Stamp:
    sec = 0
    nanosec = 0


class Header:
    def __init__(self):
        self.stamp = Stamp()
        self.frame_id = ""


class Clock:
    def __init__(self):
        self.clock = Stamp()


class JointState:
    def __init__(self):
        self.header = Header()
        self.name = []
        self.position = []
        self.velocity = []
        self.effort = []


class PoseStamped:
    def __init__(self):
        self.header = Header()
        self.pose = SimpleNamespace(
            position=SimpleNamespace(x=None, y=None, z=None),
            orientation=SimpleNamespace(x=None, y=None, z=None, w=None),
        )


class String:
    def __init__(self):
        self.data = ""


@dataclass(frozen=True)
class Sample:
    index: int
    time_ns: int
    frame_id: str = "mujoco_world"
    child_frame_id: str = "pelvis"
    base_position_m: tuple = (1.0, 2.0, 0.8)
    base_quaternion_xyzw: tuple = (0.0, 0.0, 0.0, 1.0)
    joint_names: tuple = ("left_hip_pitch_joint", "right_hip_pitch_joint")
    joint_position_rad: tuple = (0.1, -0.1)
    joint_velocity_rad_s: tuple = (0.2, -0.2)
    source_locator: str = "poses.npz#frame=0"
    source_row_sha256: str = "a" * 64


@dataclass(frozen=True)
class Event:
    event_time_ns: int
    kind: str = "MISSION_COMPLETED"
    source_sha256: str = "a" * 64
    mission_id: str = "m2-test"
    mission_id: str = "m2-test"

    def to_dict(self):
        return {"event_time_ns": self.event_time_ns, "kind": self.kind, "mission_id": self.mission_id}


def replay():
    return SimpleNamespace(
        mission_id="m2-test", mission_state="SUCCESS", run_name="trusted_authorized",
        parent_mission_id="parent-failed",
        pose_sha256="b" * 64, result_sha256="c" * 64,
        receipt_sha256="d" * 64, source_manifest_sha256="e" * 64,
        joint_map_sha256="f" * 64,
        samples=(Sample(0, 0), Sample(1, 1_002_000_000)),
        events=(Event(1_002_000_000),),
    )


def test_real_frozen_preflight_is_non_ros_and_hash_bound():
    specimen, receipt = bridge.preflight()
    assert receipt["status"] == "OFFLINE_SOURCE_VERIFIED"
    assert receipt["case_id"] == "trusted_authorized"
    assert receipt["sample_count"] == 528
    assert receipt["event_count"] == 14
    assert receipt["physics_steps"] == 0
    assert receipt["policy_inferences"] == 0
    assert specimen.parent_state == "FAILED"
    assert specimen.mission_state == "SUCCESS"
    assert "rclpy" not in sys.modules


def test_message_projection_preserves_source_time_joint_alignment_and_frames():
    specimen = Sample(7, 2_001_000_003)
    messages = bridge._make_messages(
        specimen, replay(),
        {"Clock": Clock, "JointState": JointState, "PoseStamped": PoseStamped, "String": String},
    )
    assert (messages["clock"].clock.sec, messages["clock"].clock.nanosec) == (2, 1_000_003)
    joint = messages["joint_states"]
    assert (joint.header.stamp.sec, joint.header.stamp.nanosec) == (2, 1_000_003)
    assert joint.header.frame_id == ""  # no fabricated common articulated frame
    assert joint.name == list(specimen.joint_names)
    assert joint.position == list(specimen.joint_position_rad)
    assert joint.velocity == list(specimen.joint_velocity_rad_s)
    assert joint.effort == []  # no fabricated torque
    pose = messages["base_pose"]
    assert pose.header.frame_id == "mujoco_world"
    assert pose.pose.position.x == 1.0
    assert pose.pose.orientation.w == 1.0
    provenance = json.loads(messages["provenance"].data)
    assert provenance["sequence"] == 7
    assert provenance["stamp_ns"] == specimen.time_ns
    assert provenance["source_row_sha256"] == specimen.source_row_sha256
    assert provenance["child_frame_id"] == "pelvis"
    assert provenance["parent_mission_id"] == "parent-failed"
    assert provenance["new_mission_id"] == "m2-test"
    assert "mission_id" not in provenance


def test_timestamp_and_protocol_fail_closed(monkeypatch):
    monkeypatch.delenv("ROS_DOMAIN_ID", raising=False)
    with pytest.raises(bridge.BridgeError, match="negative"):
        bridge._stamp(-1, Stamp())
    with pytest.raises(bridge.BridgeError, match="ROS_DOMAIN_ID"):
        bridge.publish_replay(replay())
    monkeypatch.setenv("ROS_DOMAIN_ID", "77")
    monkeypatch.delenv("ROS_AUTOMATIC_DISCOVERY_RANGE", raising=False)
    with pytest.raises(bridge.BridgeError, match="LOCALHOST"):
        bridge.publish_replay(replay())
    with pytest.raises(bridge.BridgeError, match="rate"):
        bridge.publish_replay(replay(), rate=0)
    with pytest.raises(bridge.BridgeError, match="rate"):
        bridge.publish_replay(replay(), rate=float("nan"))


def _install_mock_ros(monkeypatch, *, subscriber_count=1):
    """Minimal in-memory API double; deliberately not a ROS 2 integration test."""
    publications = []
    created_topics = []
    created_node = []

    class Publisher:
        def __init__(self, topic):
            self.topic = topic

        def get_subscription_count(self):
            return subscriber_count

        def publish(self, message):
            publications.append((self.topic, message))

    class Node:
        def create_publisher(self, message_type, topic, qos):
            created_topics.append(topic)
            return Publisher(topic)

        def destroy_node(self):
            pass

    class QoSProfile:
        def __init__(self, **kwargs):
            assert kwargs["depth"] == 32
            assert kwargs["reliability"] == "RELIABLE"

    rclpy = ModuleType("rclpy")
    rclpy.init = lambda args=None: None
    rclpy.shutdown = lambda: None
    rclpy.spin_once = lambda node, timeout_sec=0: None
    def create_node(*args, **kwargs):
        assert kwargs["use_global_arguments"] is False
        assert kwargs["start_parameter_services"] is False
        assert kwargs["enable_logger_service"] is False
        assert kwargs["enable_rosout"] is False
        node = Node()
        created_node.append(node)
        return node
    rclpy.create_node = create_node
    qos = ModuleType("rclpy.qos")
    qos.DurabilityPolicy = SimpleNamespace(VOLATILE="VOLATILE")
    qos.HistoryPolicy = SimpleNamespace(KEEP_LAST="KEEP_LAST")
    qos.ReliabilityPolicy = SimpleNamespace(RELIABLE="RELIABLE")
    qos.QoSProfile = QoSProfile
    for package, message_type in (
        ("geometry_msgs", PoseStamped), ("rosgraph_msgs", Clock),
        ("sensor_msgs", JointState), ("std_msgs", String),
    ):
        module = ModuleType(package)
        msg = ModuleType(package + ".msg")
        setattr(msg, message_type.__name__, message_type)
        module.msg = msg
        monkeypatch.setitem(sys.modules, package, module)
        monkeypatch.setitem(sys.modules, package + ".msg", msg)
    monkeypatch.setitem(sys.modules, "rclpy", rclpy)
    monkeypatch.setitem(sys.modules, "rclpy.qos", qos)
    return publications, created_topics


def test_mock_contract_only_publishes_allowlisted_observations(monkeypatch):
    monkeypatch.setenv("ROS_DOMAIN_ID", "77")
    monkeypatch.setenv("ROS_AUTOMATIC_DISCOVERY_RANGE", "LOCALHOST")
    publications, topics = _install_mock_ros(monkeypatch)
    ticks_ns = itertools.count(1_000_000_000_000, 2_000_000_000)
    ticks_s = itertools.count(1000.0, 1.0)
    monkeypatch.setattr(bridge.time, "monotonic_ns", lambda: next(ticks_ns))
    monkeypatch.setattr(bridge.time, "monotonic", lambda: next(ticks_s))
    outcome = bridge.publish_replay(replay(), rate=20, discovery_timeout_s=0.01)
    assert outcome["status"] == "PUBLISHED_NOT_SUBSCRIBER_VERIFIED"
    assert topics == list(bridge.TOPICS.values())
    assert all("cmd" not in topic and "dispatch" not in topic for topic in topics)
    assert [topic for topic, _ in publications] == [
        bridge.TOPICS["clock"], bridge.TOPICS["joint_states"],
        bridge.TOPICS["base_pose"], bridge.TOPICS["provenance"],
        bridge.TOPICS["clock"], bridge.TOPICS["joint_states"],
        bridge.TOPICS["base_pose"], bridge.TOPICS["provenance"],
        bridge.TOPICS["mission_events"],
    ]
    assert json.loads(publications[-1][1].data)["event_index"] == 0
    assert json.loads(publications[-1][1].data)["mission_id"] == "m2-test"


def test_parent_event_does_not_inherit_new_mission_identity():
    payload = json.loads(bridge._event_payload(
        replay(), Event(50, kind="PARENT_STRICT_FAILURE", mission_id="parent-failed"), 0
    ))
    assert payload["mission_id"] == "parent-failed"
    assert payload["event"]["mission_id"] == "parent-failed"


def test_no_discovered_subscriber_blocks_without_publishing(monkeypatch):
    monkeypatch.setenv("ROS_DOMAIN_ID", "77")
    monkeypatch.setenv("ROS_AUTOMATIC_DISCOVERY_RANGE", "LOCALHOST")
    publications, _ = _install_mock_ros(monkeypatch, subscriber_count=0)
    ticks_s = itertools.count(1000.0, 1.0)
    monkeypatch.setattr(bridge.time, "monotonic", lambda: next(ticks_s))
    with pytest.raises(bridge.BridgeError, match="subscribers absent"):
        bridge.publish_replay(replay(), discovery_timeout_s=0.01)
    assert publications == []


def test_missing_real_ros_fails_before_node_or_publish(monkeypatch):
    monkeypatch.setenv("ROS_DOMAIN_ID", "77")
    monkeypatch.setenv("ROS_AUTOMATIC_DISCOVERY_RANGE", "LOCALHOST")
    for name in ("rclpy", "geometry_msgs", "rosgraph_msgs", "sensor_msgs", "std_msgs"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    if bridge.importlib.util.find_spec("rclpy") is None:
        with pytest.raises(bridge.BridgeError, match="unavailable"):
            bridge.publish_replay(replay())


def test_frozen_event_between_samples_is_emitted_before_later_pose():
    frozen, report = bridge.preflight()
    assert report["sample_count"] == 528
    assert report["event_count"] == 14
    timeline = list(bridge._timeline(frozen))
    assert len(timeline) == 529  # one off-grid failure event gets an exact /clock tick
    failure = next(index for index, (_, _, events) in enumerate(timeline) if any(event.kind == "PARENT_STRICT_FAILURE" for _, event in events))
    assert timeline[failure][0] == 12_936_000_000
    assert timeline[failure][1] is None
    assert timeline[failure - 1][0] < timeline[failure][0] < timeline[failure + 1][0]
    assert timeline[failure + 1][1] is not None
    assert [stamp for stamp, _, _ in timeline] == sorted(stamp for stamp, _, _ in timeline)


def test_parent_event_provenance_names_its_own_original_source():
    frozen, _ = bridge.preflight()
    parent = frozen.events[0]
    item = json.loads(bridge._event_payload(frozen, parent, 0))
    assert item["mission_id"] == frozen.parent_mission_id
    assert item["source_sha256"] == parent.source_sha256 == frozen.parent_result_sha256
    assert "source_result_sha256" not in item


def test_protocol_extra_source_digest_claims_are_enforced(monkeypatch):
    protocol = bridge._load_protocol(bridge.PROTOCOL)
    protocol["cases"][0]["continuity_sha256"] = "0" * 64
    monkeypatch.setattr(bridge, "_load_protocol", lambda path: protocol)
    with pytest.raises(bridge.BridgeError, match="continuity_sha256"):
        bridge.preflight()


def test_independent_probe_requires_every_provenance_and_event_field():
    frozen, _ = bridge.preflight()
    for sample in (frozen.samples[0], frozen.samples[286], frozen.samples[-1]):
        projected = json.loads(bridge._provenance_payload(frozen, sample))
        assert probe._expected_provenance(frozen, sample) == projected
        for field in ("receipt_sha256", "source_manifest_sha256", "joint_map_sha256", "source_locator", "frame_id"):
            altered = dict(projected)
            altered[field] = "tampered"
            assert altered != probe._expected_provenance(frozen, sample)
    for index, event in enumerate(frozen.events):
        projected = json.loads(bridge._event_payload(frozen, event, index))
        assert probe._expected_event(frozen, event, index) == projected
        for field in ("source_sha256", "event_sha256", "event"):
            altered = dict(projected)
            altered[field] = "tampered"
            assert altered != probe._expected_event(frozen, event, index)


def test_probe_failure_writes_exclusive_structured_receipt(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ROS_DOMAIN_ID", raising=False)
    path = tmp_path / "failed.json"
    assert probe.main(["--receipt", str(path)]) == 2
    first = json.loads(path.read_text(encoding="utf-8"))
    assert first["status"] == "ROS2_ROUNDTRIP_FAILED"
    assert "ROS_DOMAIN_ID" in first["reason"]
    assert probe.main(["--receipt", str(path)]) == 2
    assert json.loads(path.read_text(encoding="utf-8")) == first
    assert "receipt_error" in capsys.readouterr().err


def test_probe_rejects_receipt_inside_frozen_m2_evidence():
    historical = probe.Path(__file__).resolve().parents[1] / "experiments" / "m2" / "probe-forbidden.json"
    with pytest.raises(ValueError, match="historical"):
        probe._write_receipt(historical, {"status": "TEST"})
    assert not historical.exists()


def test_probe_transcript_projects_every_received_message_field(tmp_path):
    sample = Sample(0, 1_002_000_000)
    messages = bridge._make_messages(
        sample, replay(),
        {"Clock": Clock, "JointState": JointState, "PoseStamped": PoseStamped, "String": String},
    )
    assert probe._message_fields("clock", messages["clock"]) == {
        "clock": {"sec": 1, "nanosec": 2_000_000}
    }
    joint = probe._message_fields("joint_states", messages["joint_states"])
    assert joint == {
        "header": {"stamp": {"sec": 1, "nanosec": 2_000_000}, "frame_id": ""},
        "name": list(sample.joint_names),
        "position": list(sample.joint_position_rad),
        "velocity": list(sample.joint_velocity_rad_s),
        "effort": [],
    }
    pose = probe._message_fields("base_pose", messages["base_pose"])
    assert pose["header"] == {"stamp": {"sec": 1, "nanosec": 2_000_000}, "frame_id": "mujoco_world"}
    assert pose["pose"] == {
        "position": {"x": 1.0, "y": 2.0, "z": 0.8},
        "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
    }
    assert probe._message_fields("provenance", messages["provenance"]) == {"data": messages["provenance"].data}
    assert probe._message_fields("mission_events", String()) == {"data": ""}
    with pytest.raises(ValueError, match="unknown"):
        probe._message_fields("motor_command", String())
    candidate = tmp_path / "messages.jsonl"
    assert probe._new_output_path(candidate) == candidate.resolve()
    candidate.write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError, match="exists"):
        probe._new_output_path(candidate)
    historical = probe.Path(__file__).resolve().parents[1] / "experiments" / "m2" / "forbidden-transcript.jsonl"
    with pytest.raises(ValueError, match="historical"):
        probe._new_output_path(historical)
    assert not historical.exists()
