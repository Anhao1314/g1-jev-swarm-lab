"""Read-only ROS 2 projection of one hash-verified historical G1 replay.

Importing this module does not import ROS 2, MuJoCo, a policy, or a controller.
Only ``publish`` creates a ROS node. The node has five observation publishers
and no subscriptions, services, actions, or command-capable imports.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

from g1swarm.ros_observation import EvidenceIntegrityError, load_frozen_replay


STUDY = Path(__file__).resolve().parent
PROTOCOL = STUDY / "protocol.json"
JOINT_MAP = STUDY / "joint_map.json"
TOPICS = {
    "clock": "/clock",
    "joint_states": "/g1/offline/joint_states",
    "base_pose": "/g1/offline/base_pose",
    "provenance": "/g1/offline/provenance",
    "mission_events": "/g1/offline/mission_events",
}
SCHEMA = "g1_ros_observation_replay_v0.1"


class BridgeError(RuntimeError):
    """The read-only replay contract or ROS environment is unavailable."""


def _digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_protocol(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError("frozen bridge protocol is unavailable or malformed") from exc
    if not isinstance(value, dict) or value.get("version") != "ROS-R0/R1-v0.1":
        raise BridgeError("unsupported bridge protocol")
    if value.get("authority") != "READ_ONLY_OFFLINE_REPLAY_ONLY":
        raise BridgeError("bridge authority boundary differs from frozen protocol")
    if value.get("ros_topics") != TOPICS:
        raise BridgeError("ROS topic allowlist differs from frozen protocol")
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != 1 or not isinstance(cases[0], dict):
        raise BridgeError("exactly one frozen replay case is required")
    return value


def preflight(
    *,
    protocol_path: Path = PROTOCOL,
    joint_map_path: Path = JOINT_MAP,
    asset_receipt_path: Path | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Verify frozen bytes and mapping without importing or starting ROS 2."""
    protocol = _load_protocol(protocol_path)
    case = protocol["cases"][0]
    root = protocol_path.resolve().parents[2]
    run_dir = root / case["root"]
    if not run_dir.is_dir():
        raise BridgeError("frozen replay directory is missing")
    if _digest(joint_map_path) != protocol.get("joint_map_sha256"):
        raise BridgeError("joint map SHA256 differs from frozen protocol")
    replay = load_frozen_replay(
        run_dir, joint_map_path, asset_receipt_path=asset_receipt_path
    )
    if replay.run_name != run_dir.name or len(replay.samples) != case.get("expected_samples"):
        raise BridgeError("replay identity or sample count differs from frozen protocol")
    expected = {
        "receipt_sha256": "receipt_sha256",
        "pose_sha256": "pose_sha256",
        "parent_result_sha256": "parent_result_sha256",
        "new_result_sha256": "new_result_sha256",
        "source_manifest_sha256": "source_manifest_sha256",
        "joint_map_sha256": "joint_map_sha256",
    }
    for case_key, replay_key in expected.items():
        expected_hash = case.get(case_key, protocol.get(case_key))
        if expected_hash is not None and getattr(replay, replay_key) != expected_hash:
            raise BridgeError(f"frozen {case_key} does not match projection")
    for case_key, filename in (
        ("parent_result_sha256", "parent_result.json"),
        ("new_result_sha256", "new_result.json"),
        ("continuity_sha256", "continuity.json"),
        ("lifecycle_events_sha256", "lifecycle_events.json"),
    ):
        expected_hash = case.get(case_key)
        if not isinstance(expected_hash, str) or _digest(run_dir / filename) != expected_hash:
            raise BridgeError(f"frozen {case_key} does not match source")
    report = {
        "status": "OFFLINE_SOURCE_VERIFIED",
        "case_id": case.get("id"),
        "run_name": replay.run_name,
        "sample_count": len(replay.samples),
        "event_count": len(replay.events),
        "first_stamp_ns": replay.samples[0].time_ns,
        "last_stamp_ns": replay.samples[-1].time_ns,
        "pose_sha256": replay.pose_sha256,
        "receipt_sha256": replay.receipt_sha256,
        "joint_map_sha256": replay.joint_map_sha256,
        "rclpy_discoverable": importlib.util.find_spec("rclpy") is not None,
        "physics_steps": 0,
        "policy_inferences": 0,
    }
    return replay, report


def _stamp(time_ns: int, stamp: Any) -> None:
    if time_ns < 0:
        raise BridgeError("negative simulation timestamp")
    stamp.sec, stamp.nanosec = divmod(time_ns, 1_000_000_000)


def _provenance_payload(replay: Any, sample: Any) -> str:
    return _canonical({
        "schema": SCHEMA,
        "kind": "SAMPLE",
        # This trace spans parent failure, Halt, handoff, and the new mission.
        # Individual samples do not carry a frozen mission-owner label.
        "parent_mission_id": replay.parent_mission_id,
        "new_mission_id": replay.mission_id,
        "mission_phase": "SAME_SESSION_UNPARTITIONED",
        "run_name": replay.run_name,
        "sequence": sample.index,
        "stamp_ns": sample.time_ns,
        "frame_id": sample.frame_id,
        "child_frame_id": sample.child_frame_id,
        "source_locator": sample.source_locator,
        "source_row_sha256": sample.source_row_sha256,
        "pose_sha256": replay.pose_sha256,
        "receipt_sha256": replay.receipt_sha256,
        "source_manifest_sha256": replay.source_manifest_sha256,
        "joint_map_sha256": replay.joint_map_sha256,
    })


def _event_payload(replay: Any, event: Any, event_index: int) -> str:
    event_dict = event.to_dict()
    return _canonical({
        "schema": SCHEMA,
        "kind": "MISSION_EVENT",
        "mission_id": event.mission_id,
        "parent_mission_id": replay.parent_mission_id,
        "new_mission_id": replay.mission_id,
        "run_name": replay.run_name,
        "event_index": event_index,
        "stamp_ns": event.event_time_ns,
        "source_sha256": event.source_sha256,
        "event_sha256": sha256(_canonical(event_dict).encode("utf-8")).hexdigest(),
        "event": event_dict,
    })


def _make_messages(sample: Any, replay: Any, types: dict[str, Any]) -> dict[str, Any]:
    clock = types["Clock"]()
    joint = types["JointState"]()
    pose = types["PoseStamped"]()
    provenance = types["String"]()
    _stamp(sample.time_ns, clock.clock)
    _stamp(sample.time_ns, joint.header.stamp)
    _stamp(sample.time_ns, pose.header.stamp)
    # JointState names are model-verified, but there is no one physical frame
    # shared by all articulated joints. Leave its optional frame_id unset.
    joint.header.frame_id = ""
    joint.name = list(sample.joint_names)
    joint.position = list(sample.joint_position_rad)
    joint.velocity = list(sample.joint_velocity_rad_s)
    joint.effort = []  # historical torque estimates were not recorded
    pose.header.frame_id = sample.frame_id
    pose.pose.position.x, pose.pose.position.y, pose.pose.position.z = sample.base_position_m
    (
        pose.pose.orientation.x,
        pose.pose.orientation.y,
        pose.pose.orientation.z,
        pose.pose.orientation.w,
    ) = sample.base_quaternion_xyzw
    provenance.data = _provenance_payload(replay, sample)
    return {"clock": clock, "joint_states": joint, "base_pose": pose, "provenance": provenance}


def _timeline(replay: Any):
    """Merge exact sample and event times; sample wins an equal-time tie.

    An event between 20 Hz pose samples gets its own /clock tick and is emitted
    before the later sample. The original event stamp is never rounded to a
    pose stamp. Within one equal-time group, source event order is preserved.
    """
    events = replay.events
    if any(b.event_time_ns < a.event_time_ns for a, b in zip(events, events[1:])):
        raise BridgeError("source event timestamps are not ordered")
    event_index = 0
    for sample in replay.samples:
        while event_index < len(events) and events[event_index].event_time_ns < sample.time_ns:
            stamp = events[event_index].event_time_ns
            group = []
            while event_index < len(events) and events[event_index].event_time_ns == stamp:
                group.append((event_index, events[event_index]))
                event_index += 1
            yield stamp, None, tuple(group)
        group = []
        while event_index < len(events) and events[event_index].event_time_ns == sample.time_ns:
            group.append((event_index, events[event_index]))
            event_index += 1
        yield sample.time_ns, sample, tuple(group)
    if event_index != len(events):
        raise BridgeError("mission event occurs after final frozen sample")


def publish_replay(replay: Any, *, rate: float = 1.0, discovery_timeout_s: float = 10.0) -> dict[str, Any]:
    """Use a real rclpy publisher; require observation subscribers before replay.

    The source timeline is not resampled. DDS cannot promise cross-topic arrival
    order, so every data pair carries a source timestamp and a sequence number.
    """
    if not math.isfinite(rate) or not math.isfinite(discovery_timeout_s) or rate <= 0 or rate > 20 or discovery_timeout_s <= 0:
        raise BridgeError("rate must be in (0, 20] and discovery timeout positive")
    domain = os.environ.get("ROS_DOMAIN_ID")
    if domain is None or not domain.isdecimal() or not 1 <= int(domain) <= 101:
        raise BridgeError("explicit isolated ROS_DOMAIN_ID in [1, 101] is required")
    if os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST":
        raise BridgeError("ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST is required for offline replay")
    try:
        import rclpy
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from geometry_msgs.msg import PoseStamped
        from rosgraph_msgs.msg import Clock
        from sensor_msgs.msg import JointState
        from std_msgs.msg import String
    except ImportError as exc:
        raise BridgeError("real ROS 2 rclpy and standard messages are unavailable") from exc
    types = {"Clock": Clock, "JointState": JointState, "PoseStamped": PoseStamped, "String": String}
    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=32,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.VOLATILE,
    )
    rclpy.init(args=[])
    node = None
    try:
        node = rclpy.create_node(
            "g1_frozen_observation_replay",
            use_global_arguments=False,
            enable_rosout=False,
            start_parameter_services=False,
            enable_logger_service=False,
        )
        publishers = {
            "clock": node.create_publisher(Clock, TOPICS["clock"], qos),
            "joint_states": node.create_publisher(JointState, TOPICS["joint_states"], qos),
            "base_pose": node.create_publisher(PoseStamped, TOPICS["base_pose"], qos),
            "provenance": node.create_publisher(String, TOPICS["provenance"], qos),
            "mission_events": node.create_publisher(String, TOPICS["mission_events"], qos),
        }
        deadline = time.monotonic() + discovery_timeout_s
        while any(pub.get_subscription_count() < 1 for pub in publishers.values()):
            if time.monotonic() >= deadline:
                raise BridgeError("observation subscribers absent; no replay published")
            rclpy.spin_once(node, timeout_sec=0.05)
        start_ns = time.monotonic_ns()
        origin_ns = replay.samples[0].time_ns
        clock_count = 0
        event_count = 0
        for stamp_ns, sample, event_group in _timeline(replay):
            target_ns = start_ns + round((stamp_ns - origin_ns) / rate)
            while time.monotonic_ns() < target_ns:
                remaining_s = (target_ns - time.monotonic_ns()) / 1_000_000_000
                rclpy.spin_once(node, timeout_sec=min(remaining_s, 0.05))
            if sample is None:
                clock = Clock()
                _stamp(stamp_ns, clock.clock)
                publishers["clock"].publish(clock)
            else:
                messages = _make_messages(sample, replay, types)
                for name in ("clock", "joint_states", "base_pose", "provenance"):
                    publishers[name].publish(messages[name])
            clock_count += 1
            for event_index, source_event in event_group:
                event = String()
                event.data = _event_payload(replay, source_event, event_index)
                publishers["mission_events"].publish(event)
                event_count += 1
            rclpy.spin_once(node, timeout_sec=0)
        # Allow reliable DDS delivery to progress before destroying publishers.
        end_wait = time.monotonic() + min(discovery_timeout_s, 2.0)
        while time.monotonic() < end_wait:
            rclpy.spin_once(node, timeout_sec=0.05)
        return {
            "status": "PUBLISHED_NOT_SUBSCRIBER_VERIFIED",
            "sample_count": len(replay.samples),
            "clock_count": clock_count,
            "event_count": event_count,
            "ros_domain_id": int(domain),
            "rate": rate,
            "topics": TOPICS,
            "physics_steps": 0,
            "policy_inferences": 0,
        }
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "publish"))
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--joint-map", type=Path, default=JOINT_MAP)
    parser.add_argument("--asset-receipt", type=Path)
    parser.add_argument("--rate", type=float, default=1.0)
    parser.add_argument("--discovery-timeout", type=float, default=10.0)
    args = parser.parse_args(argv)
    try:
        replay, report = preflight(
            protocol_path=args.protocol,
            joint_map_path=args.joint_map,
            asset_receipt_path=args.asset_receipt,
        )
        if args.mode == "publish":
            report["ros2"] = publish_replay(
                replay, rate=args.rate, discovery_timeout_s=args.discovery_timeout
            )
        print(_canonical(report))
        return 0
    except (BridgeError, EvidenceIntegrityError, OSError, KeyError, TypeError) as exc:
        print(_canonical({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
