# ROS-R1 attempt 003 — real ROS 2 round trip

**Verdict: `ROS_R1_PASS` for read-only replay of one frozen M2.3b trajectory.**
This is a real publisher and an independent subscriber in ROS 2 Jazzy, not an
in-memory message double. The tested source-code head is
`8886679e56919b476f7c438d6286f9b4914d3af7`; later evidence-only
commits do not alter that executable code. The [GitHub Actions run](https://github.com/Anhao1314/g1-jev-swarm-lab/actions/runs/37893547455)
was successful (job `113699633290`). The runner was Ubuntu 24.04.5 with the
official `ros:jazzy-ros-base-noble` image (image digest
`sha256:066420e07f60aa18262f2479981def87ebcfcec42eefb0c0c57c4a46098348ca`),
Python 3.12.3, NumPy 1.26.4, Jazzy `rclpy` 7.1.12 and installed
`rmw_fastrtps_cpp` 8.4.4. `ROS_DOMAIN_ID=77` and localhost-only discovery
isolated the two processes. The selected RMW was not recorded separately;
`RMW_IMPLEMENTATION=DEFAULT` in the environment receipt is not an
implementation identification.

| Independent subscriber receipt | Count |
| --- | ---: |
| `/g1/offline/joint_states` | 528 |
| `/g1/offline/base_pose` | 528 |
| `/g1/offline/provenance` | 528 |
| `/g1/offline/mission_events` | 14 |
| `/clock` | 529 |

The publisher and probe both exited 0; their stderr logs are empty.
The probe returned `ROS2_ROUNDTRIP_PASS`, and the separate receipt validation
returned `EXACT_REAL_ROS2_ROUNDTRIP_PASS`. The 529th clock tick is the
off-grid parent strict-failure event at 12.936 s. The Halt event is at
14.278 s, and replay ends at 26.256 s. The publisher's own
`PUBLISHED_NOT_SUBSCRIBER_VERIFIED` status alone is not the acceptance gate.

## Original records and independent audit

The [original GitHub Actions artifact](artifact.zip) (artifact ID
`11599577187`) is retained byte-for-byte, SHA-256
`25a10d8c56e13268b3e1b6efd2f57be9d8229625f2a502b3077ee2b9163cd167`.
It contains the complete environment, publisher/probe stdout and stderr,
process exits, preflight, per-file hash manifest, receipt and all callback
records. The [complete job log](job.log.gz) is retained as gzip, SHA-256
`8f2bb4f1718ae64afa47ce64ba4dbce26d0fe5c2c05faa191f7583398f1176c7`.
The `received_messages.jsonl` transcript inside the ZIP has SHA-256
`a2bac4eb7ceff0e8d72d3153379e05e81f508a040ab4d617116bf838c7fbda80`.
This transcript is callback-delivered semantic JSONL, **not raw DDS/CDR
packets**. The extracted small [environment](raw/environment.log),
[subscriber receipt](raw/probe_receipt.json), [process exits](raw/process_status.txt),
[file hashes](raw/file_hashes.sha256) and [validation result](raw/receipt_validation.log)
are review conveniences; the ZIP is the complete original artifact. All 15
archived file hashes and all 15 corresponding staged Git blobs were checked
against `file_hashes.sha256`. The targeted offline bridge suite also passed
`29/29` tests with this branch's `src` on `PYTHONPATH`.

An independent read-only audit bypassed the probe's own PASS flag and checked
all 2,127 callback rows against the frozen replay source: exact topic counts,
contiguous per-topic sequence and arrival indices, simulation timestamps,
12 joint names and their positions/velocities, base position/quaternion,
empty effort, per-row source SHA, file/receipt hashes, and the 14 event
bodies, locators, steps and event hashes. The frozen receipt's 12 artifact
hashes and source manifest matched. There were no mismatches. In this run,
all 1,598 non-clock callbacks had the same source timestamp as the most
recently received clock callback. This is an observed run property, not a
general DDS cross-topic ordering guarantee. The callback transcript does
not measure delivery latency or jitter.

To recheck the archived bytes without starting ROS or physics, extract the
ZIP into a clean directory, run `sha256sum -c file_hashes.sha256` from its
artifact root, and inspect `probe_receipt.json`, `process_status.txt` and
`received_messages.jsonl`. The [acceptance harness](../../run_r1_acceptance.sh)
and [probe](../../probe_ros2.py) define the reproducible live gate. The
source pose hash is
`3812ff591c0fa61183a6c9e8cebf46518eba7d404b4b7fdfa505a7c50747029d`;
the joint-map hash is
`c4ab6c3bfe81399715ff63b4f5008d95cd31a9ae859547ed17141fd9ced1e56a`.

Attempts [001](../attempt_001/README.md) and [002](../attempt_002/README.md)
remain archived as technical failures before DDS delivery: respectively ROS
setup under Bash `nounset` and loss of ROS's Python path. Both were fixed
without changing the frozen trajectory, joint map or historical evidence.

## Boundary

This pass qualifies read-only ROS 2 communication of the frozen M2.3b replay.
It does not establish live MuJoCo streaming, general DDS delivery guarantees,
robot control, hardware safety, production authorization, or full RViz robot
rendering. This run used zero new physics steps, policy inferences, training
steps or robot commands. M2.4 remains `INCONCLUSIVE`; M2.5A readiness and all
Research Ops scientific selection pointers are unchanged.
