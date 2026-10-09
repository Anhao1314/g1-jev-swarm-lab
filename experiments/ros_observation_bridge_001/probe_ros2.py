"""Independent ROS 2 subscriber acceptance probe for the frozen G1 replay.

Run in a second terminal before ``replay_ros2.py publish``. This program has
only observation subscriptions. A successful result requires actual rclpy
messages, not a call into the publisher's message-construction helpers.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time

from replay_ros2 import TOPICS, preflight


def _stamp_ns(stamp: object) -> int:
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def _fail(reason: str) -> int:
    print(json.dumps({"status": "ROS2_ROUNDTRIP_FAILED", "reason": reason}, sort_keys=True), file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--receipt", type=Path, help="optional new probe receipt path; never use a frozen evidence directory")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        return _fail("positive timeout required")
    domain = os.environ.get("ROS_DOMAIN_ID")
    if domain is None or not domain.isdecimal() or not 1 <= int(domain) <= 101:
        return _fail("explicit isolated ROS_DOMAIN_ID in [1, 101] required")
    if os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST":
        return _fail("ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST required for offline replay")
    try:
        replay, source = preflight()
    except Exception as exc:
        return _fail(f"source preflight failed: {exc}")
    try:
        import rclpy
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from geometry_msgs.msg import PoseStamped
        from rosgraph_msgs.msg import Clock
        from sensor_msgs.msg import JointState
        from std_msgs.msg import String
    except ImportError:
        return _fail("real ROS 2 rclpy and standard message packages unavailable")

    expected = len(replay.samples)
    expected_events = len(replay.events)
    expected_clock_stamps = sorted({sample.time_ns for sample in replay.samples} | {event.event_time_ns for event in replay.events})
    received: dict[str, list[object]] = defaultdict(list)
    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST, depth=32,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.VOLATILE,
    )
    rclpy.init(args=None)
    node = None
    try:
        node = rclpy.create_node("g1_frozen_observation_probe", enable_rosout=False)
        subscriptions = [
            node.create_subscription(Clock, TOPICS["clock"], lambda msg: received["clock"].append(msg), qos),
            node.create_subscription(JointState, TOPICS["joint_states"], lambda msg: received["joint_states"].append(msg), qos),
            node.create_subscription(PoseStamped, TOPICS["base_pose"], lambda msg: received["base_pose"].append(msg), qos),
            node.create_subscription(String, TOPICS["provenance"], lambda msg: received["provenance"].append(msg), qos),
            node.create_subscription(String, TOPICS["mission_events"], lambda msg: received["mission_events"].append(msg), qos),
        ]
        if len(subscriptions) != 5:
            return _fail("not all observation subscriptions were created")
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
            if len(received["clock"]) >= len(expected_clock_stamps) and all(len(received[key]) >= expected for key in ("joint_states", "base_pose", "provenance")) and len(received["mission_events"]) >= expected_events:
                break
        counts = {key: len(received[key]) for key in TOPICS}
        if counts["clock"] != len(expected_clock_stamps) or any(counts[key] != expected for key in ("joint_states", "base_pose", "provenance")) or counts["mission_events"] != expected_events:
            return _fail(f"message counts differ from frozen replay: {counts}")
        if [_stamp_ns(message.clock) for message in received["clock"]] != expected_clock_stamps:
            return _fail("/clock does not preserve merged source-time order")
        for index, sample in enumerate(replay.samples):
            joint, pose = (received[key][index] for key in ("joint_states", "base_pose"))
            try:
                provenance = json.loads(received["provenance"][index].data)
            except (ValueError, AttributeError):
                return _fail(f"invalid provenance message at {index}")
            if _stamp_ns(joint.header.stamp) != sample.time_ns or _stamp_ns(pose.header.stamp) != sample.time_ns:
                return _fail(f"source timestamps differ at {index}")
            if list(joint.name) != list(sample.joint_names) or list(joint.position) != list(sample.joint_position_rad) or list(joint.velocity) != list(sample.joint_velocity_rad_s) or list(joint.effort):
                return _fail(f"joint names/state differ at {index}")
            if joint.header.frame_id != "" or pose.header.frame_id != sample.frame_id:
                return _fail(f"frame contract differs at {index}")
            position = (pose.pose.position.x, pose.pose.position.y, pose.pose.position.z)
            orientation = (pose.pose.orientation.x, pose.pose.orientation.y, pose.pose.orientation.z, pose.pose.orientation.w)
            if position != sample.base_position_m or orientation != sample.base_quaternion_xyzw:
                return _fail(f"base pose differs at {index}")
            if provenance.get("sequence") != index or provenance.get("stamp_ns") != sample.time_ns or provenance.get("source_row_sha256") != sample.source_row_sha256 or provenance.get("pose_sha256") != replay.pose_sha256 or provenance.get("child_frame_id") != sample.child_frame_id:
                return _fail(f"provenance differs at {index}")
        for index, expected_event in enumerate(replay.events):
            try:
                item = json.loads(received["mission_events"][index].data)
            except (ValueError, AttributeError):
                return _fail(f"invalid event message at {index}")
            event = item.get("event", {})
            if item.get("event_index") != index or item.get("stamp_ns") != expected_event.event_time_ns or item.get("mission_id") != expected_event.mission_id or event.get("kind") != expected_event.kind or event.get("source_locator") != expected_event.source_locator:
                return _fail(f"mission event differs at {index}")
        receipt = {
            "status": "ROS2_ROUNDTRIP_PASS", "source_status": source["status"],
            "case_id": replay.run_name, "ros_domain_id": int(domain),
            "sample_count": expected, "event_count": expected_events,
            "topic_counts": counts, "pose_sha256": replay.pose_sha256,
            "joint_map_sha256": replay.joint_map_sha256,
            "first_stamp_ns": replay.samples[0].time_ns,
            "last_stamp_ns": replay.samples[-1].time_ns,
            "probe_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "physics_steps": 0, "policy_inferences": 0,
        }
        serialized = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        if args.receipt is not None:
            destination = args.receipt.resolve()
            if destination.exists() or "experiments\\m2" in str(destination).lower():
                return _fail("receipt destination exists or is within historical experiment evidence")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(serialized + "\n", encoding="utf-8")
        print(serialized)
        return 0
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
