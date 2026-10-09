# ROS-R1 attempt 001 — technical failure before DDS

- Run: [GitHub Actions 37893027808](https://github.com/Anhao1314/g1-jev-swarm-lab/actions/runs/37893027808)
- Exact PR head checked out: `8380d257f772a808538d01c8bdd8579fef6c3150`
- Target: GitHub `ubuntu-24.04`, official `ros:jazzy-ros-base-noble` container.
- Result: **TECHNICAL_FAILURE_BEFORE_DDS**, not a message-content or ROS-R1 scientific failure.
- Cause: the harness enabled Bash `nounset` before sourcing the official Jazzy
  setup script; `AMENT_TRACE_SETUP_FILES` was unset and sourcing stopped with
  `unbound variable`. No publisher or subscriber was started.
- Secondary receipt issue: Git reported dubious ownership inside the container,
  leaving `git_head` absent from `environment.log`. The checkout step itself
  verified the exact head above. The next harness revision uses command-scoped
  safe-directory and a container-correct `PYTHONPATH`.

The [original artifact ZIP](artifact.zip) is retained byte-for-byte (SHA-256
`c9591b09131a9c2dcd86f0f666ec71727882dcb183f2324f1a53440c93613436`).
Its extracted [environment log](raw/environment.log) and
[`ROS_R1_FAILED` verdict](raw/verdict.txt), plus the
[complete job log in gzip form](job.log.gz) (SHA-256
`6a94b6476b4c6d24e6cafcd0d53675be9da81f60f94ac53ec0d23e134172ca84`),
preserve the failed attempt. The artifact's package record shows Ubuntu
24.04.5, Python 3.12.3, NumPy 1.26.4 and ROS Jazzy `rclpy` 7.1.12.

This attempt contains **zero** G1 physics, policy inference, robot command or
ROS data-message delivery. It must not be counted as a successful ROS-R1 run.
