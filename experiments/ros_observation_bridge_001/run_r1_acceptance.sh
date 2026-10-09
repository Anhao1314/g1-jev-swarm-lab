#!/usr/bin/env bash
# Ephemeral Ubuntu 24.04/Jazzy real DDS qualification. No MuJoCo or policy calls.
set -uo pipefail

output_dir="${1:?new output directory required}"
mkdir -p "$output_dir"
chmod 700 "$output_dir"
study="experiments/ros_observation_bridge_001"
trap '(
  cd "$output_dir" || exit 0
  find . -type f ! -name file_hashes.sha256 -print0 | sort -z | xargs -0 sha256sum > file_hashes.sha256
)' EXIT

# Keep a receipt even when dependencies, discovery, publishing or the probe fail.
printf '%s\n' 'ROS_R1_FAILED' > "$output_dir/verdict.txt"
{
  printf 'requested_image=ros:jazzy-ros-base-noble\n'
  printf 'git_head='; git -c safe.directory="$PWD" rev-parse HEAD
  printf 'github_run_url=%s/%s/actions/runs/%s\n' "${GITHUB_SERVER_URL:-UNKNOWN}" "${GITHUB_REPOSITORY:-UNKNOWN}" "${GITHUB_RUN_ID:-UNKNOWN}"
  printf 'github_sha=%s\n' "${GITHUB_SHA:-UNKNOWN}"
  printf 'utc='; date -u +%Y-%m-%dT%H:%M:%SZ
  printf 'ROS_DOMAIN_ID=%s\n' "${ROS_DOMAIN_ID:-UNSET}"
  printf 'ROS_AUTOMATIC_DISCOVERY_RANGE=%s\n' "${ROS_AUTOMATIC_DISCOVERY_RANGE:-UNSET}"
  printf 'ROS_DISTRO=%s\n' "${ROS_DISTRO:-UNSET}"
  printf 'RMW_IMPLEMENTATION=%s\n' "${RMW_IMPLEMENTATION:-DEFAULT}"
  cat /etc/os-release
  python3 --version
  dpkg-query -W -f='${Package}=${Version}\n' 'ros-jazzy-rclpy' 'ros-jazzy-rosgraph-msgs' 'ros-jazzy-sensor-msgs' 'ros-jazzy-geometry-msgs' 'ros-jazzy-rmw-fastrtps-cpp' 'python3-numpy' 2>&1 || true
  sha256sum "$study/protocol.json" "$study/joint_map.json" "$study/replay_ros2.py" "$study/probe_ros2.py" \
    experiments/m2/trusted_handoff_qualification_001/artifacts/trusted_authorized/poses.npz
} > "$output_dir/environment.log" 2>&1

if ! test -f /opt/ros/jazzy/setup.bash; then
  printf '%s\n' 'ROS_JAZZY_SETUP_MISSING' > "$output_dir/blocker.txt"
  exit 0
fi
# ROS setup scripts expect a few variables to be unset; turn nounset off only
# while sourcing the official environment, then restore it for our harness.
set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash > "$output_dir/ros_setup.stdout.log" 2> "$output_dir/ros_setup.stderr.log"
setup_status=$?
set -u
if test "$setup_status" -ne 0; then
  printf 'ROS_SETUP_FAILED=%s\n' "$setup_status" > "$output_dir/blocker.txt"
  exit 0
fi
# Preserve the official ROS Python path added by setup.bash; only prepend the
# isolated repository converter. Replacing PYTHONPATH hides apt-installed rclpy.
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
printf 'sourced_ROS_DISTRO=%s\n' "${ROS_DISTRO:-UNSET}" >> "$output_dir/environment.log"
printf 'container_PYTHONPATH=%s\n' "$PYTHONPATH" >> "$output_dir/environment.log"
printf 'container_python3=%s\n' "$(command -v python3)" >> "$output_dir/environment.log"
python3 - <<'PY' > "$output_dir/ros_imports.log" 2>&1
import json, platform
import numpy, rclpy
from geometry_msgs.msg import PoseStamped
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import JointState
from std_msgs.msg import String
print(json.dumps({"python": platform.python_version(), "numpy": numpy.__version__,
                  "rclpy_file": rclpy.__file__, "messages_imported": True}, sort_keys=True))
PY
imports_status=$?
if test "$imports_status" -ne 0; then
  printf 'ROS_IMPORTS_FAILED=%s\n' "$imports_status" > "$output_dir/blocker.txt"
  exit 0
fi
python3 "$study/replay_ros2.py" preflight > "$output_dir/offline_preflight.stdout.json" 2> "$output_dir/offline_preflight.stderr.log"
preflight_status=$?
if test "$preflight_status" -ne 0; then
  printf 'OFFLINE_PREFLIGHT_FAILED=%s\n' "$preflight_status" > "$output_dir/blocker.txt"
  exit 0
fi

# The independent subscriber starts first; the publisher itself waits for all
# five discovered subscriptions. GNU timeout bounds both process lifetimes.
timeout 95s python3 "$study/probe_ros2.py" --timeout 85 --receipt "$output_dir/probe_receipt.json" --transcript "$output_dir/received_messages.jsonl" \
  > "$output_dir/probe.stdout.log" 2> "$output_dir/probe.stderr.log" &
probe_pid=$!
sleep 2
timeout 80s python3 "$study/replay_ros2.py" publish --rate 1 --discovery-timeout 20 \
  > "$output_dir/publisher.stdout.log" 2> "$output_dir/publisher.stderr.log" &
publisher_pid=$!
wait "$publisher_pid"
publisher_status=$?
wait "$probe_pid"
probe_status=$?
printf 'publisher_exit=%s\nprobe_exit=%s\n' "$publisher_status" "$probe_status" > "$output_dir/process_status.txt"

python3 - "$output_dir" <<'PY' > "$output_dir/receipt_validation.log" 2>&1
import json, pathlib, sys
out = pathlib.Path(sys.argv[1])
probe = json.loads((out / "probe_receipt.json").read_text())
publisher = json.loads((out / "publisher.stdout.log").read_text())
assert probe["status"] == "ROS2_ROUNDTRIP_PASS", probe
assert publisher["ros2"]["status"] == "PUBLISHED_NOT_SUBSCRIBER_VERIFIED", publisher
assert probe["sample_count"] == publisher["sample_count"] == 528
assert probe["event_count"] == publisher["event_count"] == 14
assert probe["topic_counts"] == {
    "clock": 529, "joint_states": 528, "base_pose": 528,
    "provenance": 528, "mission_events": 14,
}
assert publisher["ros2"]["clock_count"] == 529
assert probe["pose_sha256"] == publisher["pose_sha256"]
assert probe["joint_map_sha256"] == publisher["joint_map_sha256"]
print("EXACT_REAL_ROS2_ROUNDTRIP_PASS")
PY
validation_status=$?
if test "$publisher_status" -eq 0 && test "$probe_status" -eq 0 && test "$validation_status" -eq 0; then
  printf '%s\n' 'ROS_R1_PASS' > "$output_dir/verdict.txt"
else
  printf 'VALIDATION_FAILED=%s\n' "$validation_status" > "$output_dir/blocker.txt"
fi
exit 0
