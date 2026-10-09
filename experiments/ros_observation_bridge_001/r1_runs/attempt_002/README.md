# ROS-R1 attempt 002 — Python path failure before DDS

- Run: [GitHub Actions 37893336668](https://github.com/Anhao1314/g1-jev-swarm-lab/actions/runs/37893336668)
- Exact PR head checked out: `0f11fe3c89dc6038f434afe6543f19bbedd20e8b`
- Target: Ubuntu 24.04.5, official `ros:jazzy-ros-base-noble` container,
  Python 3.12.3, NumPy 1.26.4, apt `ros-jazzy-rclpy` 7.1.12.
- Result: **TECHNICAL_FAILURE_BEFORE_DDS**. The official ROS setup sourced,
  but the harness then replaced its `PYTHONPATH` with the repository `src`
  path. `rclpy` could not be imported although it was installed. No publisher
  or subscriber was started.
- Fix for the next attempt: prepend `src` to ROS's existing `PYTHONPATH`;
  retain the full resulting value and Python executable path in the environment
  receipt.

The [original artifact ZIP](artifact.zip) is retained byte-for-byte (SHA-256
`d29dda0ca602779479755d5e4e803e9d1f3b70759f91e18aac759f2def0ad43d`).
The [extracted logs](raw/) include `ros_imports.log`, `blocker.txt`, package
versions, SHA-256 source hashes and `ROS_R1_FAILED`. The
[complete job log in gzip form](job.log.gz) has SHA-256
`12472557e55efa296c89c9ca91047e65df0ac423a3d6ecdd66b9fce1f2e03488`.
No G1 physics, policy inference, robot command or ROS data-message delivery
occurred. This run is retained and excluded from a ROS-R1 PASS claim.
