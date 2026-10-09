# ROS-R0/R1 acceptance record — 2026-10-09

Baseline: `origin/main` `0eff13a5cb523690cde31a742cc985e9ee0eaf03`.
This is a new adapter branch; no historical artifact, controller, M2.5A PR #14,
or Research Ops selection pointer was edited. M2.4 remains `INCONCLUSIVE`.

| Gate | Result | Evidence |
| --- | --- | --- |
| Frozen M2.3b source and 12 artifact files | PASS | `offline_preflight_receipt.json`; receipt `cda9a983…`, pose `3812ff59…`, source manifest `0a60a24d…`. |
| Official 12-DOF joint names and addresses | PASS | `joint_map.json`, `model_compilation_receipt.json`; scene/MJCF/URDF hashes checked, MuJoCo model compiled with no `MjData` or step. |
| Offline projection | PASS / ROS-R0 | 528 finite ordered samples spanning 0–26.256 s; 14 sanitized events, including parent strict failure, Halt, TEST_ONLY handoff, completion and replay refusal. |
| Source-time ordering | PASS offline | The 12.936 s parent failure gets its own `/clock` tick before the later 12.95 s pose; total projected clock count 529. Equal-time sample precedes its event. DDS cross-topic delivery order still requires the subscriber check. |
| Targeted tests | PASS | `25 passed in 0.56s` for core and ROS adapter contract tests. Mock message classes prove formatting/allowlist only. |
| Genuine ROS 2 publisher/subscriber | **BLOCKED_TARGET_ENV / ROS-R1 NOT ACCEPTED** | Current host lacks ROS 2 CLI, `rclpy` and standard message packages. Both real publisher and probe exit code 2 before node creation or replay. No real ROS messages were transmitted. |

The [preflight receipt](offline_preflight_receipt.json) reports
`OFFLINE_SOURCE_VERIFIED`, 528 samples, 14 events, first stamp 0,
last stamp 26,256,000,000 ns and `rclpy_discoverable=false`. The
[model-compilation receipt](model_compilation_receipt.json) reports 19 `nq`,
18 `nv`, 12 `nu`, exact names and qpos/qvel addresses, `mjdata_created=false`,
`physics_steps=0`, `policy_inferences=0`. Official assets were read from an
already restored asset tree; they were not copied into this branch.

Environment inventory: Windows 11 Pro 10.0.26200, PowerShell 7.6.5, system
Python 3.11 and the existing G1 Python environment. `ros2`, `rclpy`,
`sensor_msgs`, Docker/Podman, Pixi and an installed WSL distribution are absent.
There is no configured ROS installation under the checked standard Windows
paths. No software was installed. The official [Jazzy Windows binary
guide](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Installation/Windows-Install-Binary.rst)
describes Windows 10 with a Pixi-based package layout; the [Rolling Windows 11
guide](https://github.com/ros2/ros2_documentation/blob/rolling/source/Get-Started/Installation/Windows-Install-Binary.rst)
offers nightly pre-release binaries. Neither is a currently working
target ROS 2 environment here. The [publisher](replay_ros2.py) and
[subscriber probe](probe_ros2.py) form the acceptance procedure for a later
environment that has ROS 2. Their existence does not satisfy ROS-R1.

Independent evidence review first found three projection defects: parent
samples mislabeled with the new Mission, an off-grid event emitted after a
later pose, and missing pelvis body identity. The adapter now carries both
Mission IDs without assigning a singular Mission to mixed-session samples,
uses event-specific Mission and source-file hashes, merges event/sample time,
and carries `child_frame_id=pelvis` in provenance. Protocol-declared hashes
for parent result, new result, continuity, and lifecycle are checked in
addition to the historical receipt. Regression tests cover the corrections.

This gate verifies source-backed observation only. It does not qualify robot
control, real-time execution, hardware safety, production identity, or the
historical TEST_ONLY handoff as general authorization. The next acceptance
step is a genuine ROS 2 subscriber round trip on a suitable environment,
using the unchanged frozen replay and probe, with its raw terminal receipts.
Complete articulated RViz rendering is also unverified because this adapter
does not publish `robot_description` or `/tf`.
