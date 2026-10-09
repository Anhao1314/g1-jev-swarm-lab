# ROS Observation Bridge v0.1 (ROS-R0/R1)

**One Mission. Adaptive Execution. Verifiable Evidence.** This is an optional,
read-only adapter for an already completed G1 MuJoCo mission. It does not start
MuJoCo, infer a policy action, control motors, dispatch a Mission, or authorize
a person. Its first frozen input is the M2.3b `trusted_authorized` same-session
run, which contains a failed parent task, a bounded physical Halt, and a
TEST_ONLY authorized new Mission. This replay does not upgrade that historical
authorization or M2.4's `INCONCLUSIVE` verdict.

## Scope and acceptance levels

`ROS-R0` verifies the source hashes and model binding, then projects 528
historical samples and sanitized lifecycle events without requiring ROS 2.
`ROS-R1` requires a real ROS 2 publisher and a separate subscriber to receive
and check all messages. Unit tests with in-memory message doubles count only
as contract tests, never as ROS-R1. The [acceptance report](acceptance.md)
records which level the current host actually reached.

The replay exposes:

| Topic | Type | Meaning |
| --- | --- | --- |
| `/clock` | `rosgraph_msgs/msg/Clock` | Frozen MuJoCo simulation time, starting at zero. |
| `/g1/offline/joint_states` | `sensor_msgs/msg/JointState` | 12 verified leg hinge names, positions, velocities. Empty `effort`. |
| `/g1/offline/base_pose` | `geometry_msgs/msg/PoseStamped` | Pelvis free-base position and orientation in `mujoco_world`. |
| `/g1/offline/provenance` | `std_msgs/msg/String` | Per-sample index, exact source row and file hashes. |
| `/g1/offline/mission_events` | `std_msgs/msg/String` | Sanitized, time-ordered event facts with source locators. |

Only these five application observation publishers exist. The bridge defines
no command subscriptions, application services, actions, or links to the
Mission Runtime. ROS 2 itself may expose a read-only type-description service;
this is not a G1 control interface. Each source sample preserves its recorded
timestamp. Events between pose samples receive an exact-time `/clock` tick and
are published before the later pose; equal-time samples precede their events.
No interpolation, retiming, reset, or new robot execution occurs. DDS arrival
order across topics is not asserted; consumers correlate by simulation
timestamp and provenance sequence. `PoseStamped` names the parent world frame;
the `pelvis` body identity is carried in provenance. A single case is replayed
per ROS process. We do not publish an `Odometry`, `TF`,
hardware `LowState`, measured torque, geographic `map` frame, or `odom` frame
because the necessary definitions or measurements are absent from this input.
The pose and joints can be inspected by ROS observation tools, but no
`robot_description` or `/tf` tree is published, so a complete articulated
RViz robot display is outside v0.1 acceptance.

## Frozen source and model binding

The [protocol](protocol.json) seals the baseline commit, one run, file digests,
sample count, topic allowlist, and acceptance rules. The converter verifies the
M2.3b receipt and every one of its 12 artifact hashes, the source manifest,
the same-session state at Halt/handoff, increasing finite timestamps, and the
pose shape. The [joint map](joint_map.json) is bound to the official 12-DOF
Unitree RL Gym MJCF/URDF SHA-256 and the 91-file official asset receipt. It was
checked against a compiled MuJoCo model with **zero physics steps**. The
reproducible [compilation receipt](model_compilation_receipt.json) and
[`verify_compiled_map.py`](verify_compiled_map.py) document that check. The
free pelvis consumes `qpos[0:7]` and `qvel[0:6]`; named hinge joints occupy
`qpos[7:19]` and `qvel[6:18]`. MuJoCo `w,x,y,z` becomes ROS `x,y,z,w`.
This is an exact mapping for the frozen 12-DOF model, not a Unitree hardware
motor-index map. The historical `ctrl` array contains commands and is omitted
from `JointState.effort`.

The same-session source is
`experiments/m2/trusted_handoff_qualification_001/artifacts/trusted_authorized`.
The source receipt SHA-256 is
`cda9a983f897a3f913289fce3539d6c1d89c4d6fd29e59ebaccb7ad3e6a1a562`;
`poses.npz` SHA-256 is
`3812ff591c0fa61183a6c9e8cebf46518eba7d404b4b7fdfa505a7c50747029d`.
M2.0 trajectories are useful background but are not used for v0.1 joint
publication because their own source receipt does not seal the exact model
assets.

## Run the offline preflight

Use Python 3.11+ with NumPy. On Windows, from the repository root:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python experiments/ros_observation_bridge_001/replay_ros2.py preflight
python -m pytest -q tests/test_ros_observation_core.py tests/test_ros_observation_ros2_adapter.py
```

The preflight prints hashes, counts, and `rclpy_discoverable`; it does not
start ROS or write to the frozen source. `verify_joint_map_sources` optionally
rechecks the official MJCF/URDF in an existing asset checkout. Those assets
are intentionally not copied into this PR.

## Qualify real ROS 2 delivery

The [ROS-R1 workflow](../../.github/workflows/ros-observation-r1.yml) uses a
disposable GitHub-hosted Ubuntu 24.04 runner with the official
`ros:jazzy-ros-base-noble` container. Its
[`run_r1_acceptance.sh`](run_r1_acceptance.sh) starts the subscriber and
publisher as separate processes, saves raw stdout/stderr, source hashes,
environment/package versions, process exit codes and the subscriber receipt,
then uploads the whole directory even on failure. No package is installed on
the Windows research host. A green workflow requires the real subscriber
receipt; an in-memory test cannot satisfy it.

For an already configured Ubuntu 24.04/Jazzy machine, source
`/opt/ros/jazzy/setup.bash` in **both** terminals and set:

```bash
export PYTHONPATH="$PWD/src"
export ROS_DOMAIN_ID=77
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
```

Start `python3 experiments/ros_observation_bridge_001/probe_ros2.py --timeout 90`
in one terminal, then
`python3 experiments/ros_observation_bridge_001/replay_ros2.py publish --rate 1`
in the other. Use a new receipt directory outside historical M2 evidence.

On a separate machine or environment **with a working ROS 2 installation**, use
Python 3.11+ with NumPy and the standard `rclpy`, `sensor_msgs`,
`geometry_msgs`, `rosgraph_msgs`, and `std_msgs` packages. Source that ROS
environment and expose this repository's `src` directory on `PYTHONPATH`.
Select an isolated domain ID (example `77`) and localhost-only discovery; keep
both terminals on the same settings.
Start the subscriber first:

```powershell
$env:ROS_DOMAIN_ID = '77'
$env:ROS_AUTOMATIC_DISCOVERY_RANGE = 'LOCALHOST'
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python experiments/ros_observation_bridge_001/probe_ros2.py --timeout 90
```

In the second terminal run:

```powershell
$env:ROS_DOMAIN_ID = '77'
$env:ROS_AUTOMATIC_DISCOVERY_RANGE = 'LOCALHOST'
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python experiments/ros_observation_bridge_001/replay_ros2.py publish --rate 1
```

The publisher refuses to start without an explicit isolated `ROS_DOMAIN_ID`
and `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`,
and refuses to publish when its five subscribers are absent. `--rate 1` retains
the recorded 26.256 s timeline. The probe must report
`ROS2_ROUNDTRIP_PASS` with all 528 messages per state topic, 529 `/clock`
messages (including the off-grid parent failure at 12.936 s), and the exact event
count; the publisher alone reports only `PUBLISHED_NOT_SUBSCRIBER_VERIFIED`.
Capture both outputs in a **new** acceptance artifact, never in a frozen M2
directory. A display consumer should set `use_sim_time=true` and use `/clock`.

## Interface sources and limitations

- ROS 2 [`JointState`](https://github.com/ros2/common_interfaces/blob/rolling/sensor_msgs/msg/JointState.msg), [`PoseStamped`](https://github.com/ros2/common_interfaces/blob/rolling/geometry_msgs/msg/PoseStamped.msg), [`Clock`](https://github.com/ros2/rcl_interfaces/blob/rolling/rosgraph_msgs/msg/Clock.msg), and [time design](https://design.ros2.org/articles/130_ros_time.html).
- Official Unitree [G1 model variants and DDS joint indices](https://github.com/unitreerobotics/unitree_mujoco/blob/main/unitree_robots/g1/g1_joint_index_dds.md) and [ROS 2 LowState](https://github.com/unitreerobotics/unitree_ros2/blob/master/cyclonedds_ws/src/unitree/unitree_hg/msg/LowState.msg). Hardware indices are variant-dependent, so they are not inferred from this MuJoCo replay.
- ROS 2 [QoS compatibility](https://docs.ros.org/en/jazzy/Concepts/Intermediate/About-Quality-of-Service-Settings.html): the prototype uses reliable, volatile observation QoS; a consumer requesting incompatible QoS may not receive it.

No robot/hardware safety qualification, production identity, Language Runtime
permission, or live telemetry integration is implied. The event stream is a
projection of historical evidence; the original records remain the authority.
