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
from typing import Any

if __package__:
    from .replay_ros2 import TOPICS, preflight
else:
    from replay_ros2 import TOPICS, preflight


def _stamp_ns(stamp: object) -> int:
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def _new_output_path(path: Path) -> Path:
    destination = path.resolve()
    historical = Path(__file__).resolve().parents[2] / "experiments" / "m2"
    if destination.is_relative_to(historical) or destination.exists():
        raise ValueError("output destination exists or is within historical experiment evidence")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    destination = _new_output_path(path)
    # Exclusive creation prevents a second invocation from replacing a receipt.
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def _fail(reason: str, *, receipt_path: Path | None = None, counts: dict[str, int] | None = None) -> int:
    payload: dict[str, Any] = {"status": "ROS2_ROUNDTRIP_FAILED", "reason": reason}
    if counts is not None:
        payload["topic_counts"] = counts
    if receipt_path is not None:
        try:
            _write_receipt(receipt_path, payload)
        except (OSError, ValueError) as exc:
            payload["receipt_error"] = str(exc)
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)
    return 2


def _expected_provenance(replay: Any, sample: Any) -> dict[str, Any]:
    """Independent subscriber-side reconstruction of the frozen projection."""
    return {
        "schema": "g1_ros_observation_replay_v0.1",
        "kind": "SAMPLE",
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
    }


def _expected_event(replay: Any, event: Any, index: int) -> dict[str, Any]:
    event_fields = {
        "kind": event.kind,
        "event_time_ns": event.event_time_ns,
        "simulation_step": event.simulation_step,
        "source_locator": event.source_locator,
        "source_sha256": event.source_sha256,
        "mission_id": event.mission_id,
        "mission_state": event.mission_state,
        "node_id": event.node_id,
        "skill": event.skill,
        "skill_status": event.skill_status,
        "feedback_action": event.feedback_action,
        "reason": event.reason,
        "source_sequence": event.source_sequence,
    }
    canonical = json.dumps(event_fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema": "g1_ros_observation_replay_v0.1",
        "kind": "MISSION_EVENT",
        "mission_id": event.mission_id,
        "parent_mission_id": replay.parent_mission_id,
        "new_mission_id": replay.mission_id,
        "run_name": replay.run_name,
        "event_index": index,
        "stamp_ns": event.event_time_ns,
        "source_sha256": event.source_sha256,
        "event_sha256": sha256(canonical.encode("utf-8")).hexdigest(),
        "event": event_fields,
    }


def _message_fields(topic_key: str, message: Any) -> dict[str, Any]:
    """Capture the message actually delivered by rclpy, without reparsing it."""
    if topic_key == "clock":
        return {"clock": {"sec": int(message.clock.sec), "nanosec": int(message.clock.nanosec)}}
    if topic_key == "joint_states":
        return {
            "header": {
                "stamp": {"sec": int(message.header.stamp.sec), "nanosec": int(message.header.stamp.nanosec)},
                "frame_id": message.header.frame_id,
            },
            "name": list(message.name),
            "position": list(message.position),
            "velocity": list(message.velocity),
            "effort": list(message.effort),
        }
    if topic_key == "base_pose":
        return {
            "header": {
                "stamp": {"sec": int(message.header.stamp.sec), "nanosec": int(message.header.stamp.nanosec)},
                "frame_id": message.header.frame_id,
            },
            "pose": {
                "position": {
                    "x": float(message.pose.position.x),
                    "y": float(message.pose.position.y),
                    "z": float(message.pose.position.z),
                },
                "orientation": {
                    "x": float(message.pose.orientation.x),
                    "y": float(message.pose.orientation.y),
                    "z": float(message.pose.orientation.z),
                    "w": float(message.pose.orientation.w),
                },
            },
        }
    if topic_key in ("provenance", "mission_events"):
        return {"data": message.data}
    raise ValueError(f"unknown observation topic: {topic_key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--receipt", type=Path, help="optional new probe receipt path; never use a frozen evidence directory")
    parser.add_argument("--transcript", type=Path, help="exclusive JSONL path for every received ROS message in callback arrival order")
    args = parser.parse_args(argv)
    if args.receipt is not None and args.transcript is not None and args.receipt.resolve() == args.transcript.resolve():
        return _fail("receipt and transcript must use distinct paths", receipt_path=args.receipt)
    if args.timeout <= 0:
        return _fail("positive timeout required", receipt_path=args.receipt)
    domain = os.environ.get("ROS_DOMAIN_ID")
    if domain is None or not domain.isdecimal() or not 1 <= int(domain) <= 101:
        return _fail("explicit isolated ROS_DOMAIN_ID in [1, 101] required", receipt_path=args.receipt)
    if os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST":
        return _fail("ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST required for offline replay", receipt_path=args.receipt)
    try:
        replay, source = preflight()
    except Exception as exc:
        return _fail(f"source preflight failed: {exc}", receipt_path=args.receipt)
    try:
        import rclpy
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from geometry_msgs.msg import PoseStamped
        from rosgraph_msgs.msg import Clock
        from sensor_msgs.msg import JointState
        from std_msgs.msg import String
    except ImportError:
        return _fail("real ROS 2 rclpy and standard message packages unavailable", receipt_path=args.receipt)

    expected = len(replay.samples)
    expected_events = len(replay.events)
    expected_clock_stamps = sorted({sample.time_ns for sample in replay.samples} | {event.event_time_ns for event in replay.events})
    received: dict[str, list[object]] = defaultdict(list)
    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST, depth=32,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.VOLATILE,
    )
    transcript_stream = None
    if args.transcript is not None:
        try:
            transcript_stream = _new_output_path(args.transcript).open("x", encoding="utf-8")
        except (OSError, ValueError) as exc:
            return _fail(f"transcript could not be created: {exc}", receipt_path=args.receipt)
    try:
        rclpy.init(args=[])
    except Exception as exc:
        if transcript_stream is not None:
            transcript_stream.close()
        return _fail(f"ROS initialization failed: {type(exc).__name__}: {exc}", receipt_path=args.receipt)
    node = None
    arrival_index = 0

    def receive(topic_key: str):
        def callback(message: Any) -> None:
            nonlocal arrival_index
            topic_sequence = len(received[topic_key])
            received[topic_key].append(message)
            if transcript_stream is not None:
                row = {
                    "arrival_index": arrival_index,
                    "topic": TOPICS[topic_key],
                    "topic_sequence": topic_sequence,
                    "fields": _message_fields(topic_key, message),
                }
                transcript_stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                transcript_stream.flush()
            arrival_index += 1
        return callback

    try:
        node = rclpy.create_node("g1_frozen_observation_probe", enable_rosout=False)
        subscriptions = [
            node.create_subscription(Clock, TOPICS["clock"], receive("clock"), qos),
            node.create_subscription(JointState, TOPICS["joint_states"], receive("joint_states"), qos),
            node.create_subscription(PoseStamped, TOPICS["base_pose"], receive("base_pose"), qos),
            node.create_subscription(String, TOPICS["provenance"], receive("provenance"), qos),
            node.create_subscription(String, TOPICS["mission_events"], receive("mission_events"), qos),
        ]
        if len(subscriptions) != 5:
            return _fail("not all observation subscriptions were created", receipt_path=args.receipt)
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
            if len(received["clock"]) >= len(expected_clock_stamps) and all(len(received[key]) >= expected for key in ("joint_states", "base_pose", "provenance")) and len(received["mission_events"]) >= expected_events:
                break
        # A bounded drain catches late duplicate traffic before a count-based
        # PASS. It does not assume ordering between distinct DDS topics.
        if all(len(received[key]) >= count for key, count in {
            "clock": len(expected_clock_stamps),
            "joint_states": expected,
            "base_pose": expected,
            "provenance": expected,
            "mission_events": expected_events,
        }.items()):
            drain_deadline = min(deadline, time.monotonic() + 0.5)
            while time.monotonic() < drain_deadline:
                rclpy.spin_once(node, timeout_sec=0.05)
        counts = {key: len(received[key]) for key in TOPICS}
        if counts["clock"] != len(expected_clock_stamps) or any(counts[key] != expected for key in ("joint_states", "base_pose", "provenance")) or counts["mission_events"] != expected_events:
            return _fail("message counts differ from frozen replay", receipt_path=args.receipt, counts=counts)
        if [_stamp_ns(message.clock) for message in received["clock"]] != expected_clock_stamps:
            return _fail("/clock does not preserve merged source-time order", receipt_path=args.receipt, counts=counts)
        for index, sample in enumerate(replay.samples):
            joint, pose = (received[key][index] for key in ("joint_states", "base_pose"))
            try:
                provenance = json.loads(received["provenance"][index].data)
            except (ValueError, AttributeError):
                return _fail(f"invalid provenance message at {index}", receipt_path=args.receipt, counts=counts)
            if _stamp_ns(joint.header.stamp) != sample.time_ns or _stamp_ns(pose.header.stamp) != sample.time_ns:
                return _fail(f"source timestamps differ at {index}", receipt_path=args.receipt, counts=counts)
            if list(joint.name) != list(sample.joint_names) or list(joint.position) != list(sample.joint_position_rad) or list(joint.velocity) != list(sample.joint_velocity_rad_s) or list(joint.effort):
                return _fail(f"joint names/state differ at {index}", receipt_path=args.receipt, counts=counts)
            if joint.header.frame_id != "" or pose.header.frame_id != sample.frame_id:
                return _fail(f"frame contract differs at {index}", receipt_path=args.receipt, counts=counts)
            position = (pose.pose.position.x, pose.pose.position.y, pose.pose.position.z)
            orientation = (pose.pose.orientation.x, pose.pose.orientation.y, pose.pose.orientation.z, pose.pose.orientation.w)
            if position != sample.base_position_m or orientation != sample.base_quaternion_xyzw:
                return _fail(f"base pose differs at {index}", receipt_path=args.receipt, counts=counts)
            if provenance != _expected_provenance(replay, sample):
                return _fail(f"provenance differs at {index}", receipt_path=args.receipt, counts=counts)
        for index, expected_event in enumerate(replay.events):
            try:
                item = json.loads(received["mission_events"][index].data)
            except (ValueError, AttributeError):
                return _fail(f"invalid event message at {index}", receipt_path=args.receipt, counts=counts)
            if item != _expected_event(replay, expected_event, index):
                return _fail(f"mission event differs at {index}", receipt_path=args.receipt, counts=counts)
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
            try:
                _write_receipt(args.receipt, receipt)
            except (OSError, ValueError) as exc:
                return _fail(f"receipt could not be saved: {exc}", counts=counts)
        print(serialized)
        return 0
    except Exception as exc:
        counts = {key: len(received[key]) for key in TOPICS}
        return _fail(
            f"ROS subscriber or transport failed: {type(exc).__name__}: {exc}",
            receipt_path=args.receipt,
            counts=counts,
        )
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()
        if transcript_stream is not None:
            transcript_stream.close()


if __name__ == "__main__":
    raise SystemExit(main())
