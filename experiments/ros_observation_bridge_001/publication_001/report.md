# Accepted-Main ROS Observation Bridge publication

Decision: **`ROS_R1_PASS_BOUNDED_FROZEN_OFFLINE_REPLAY`**.
PR #15 was explicitly authorized by the owner, changed to Ready for Review and
merged using a merge commit. Accepted code/evidence commit:
`9e5461d182cf365a5ac272b3ce2bd8effe5990d1`, tree
`416a5a520c17d3c8033c08553c194cb67ca5e0a0`. Its parents are previous main
`0eff13a5cb523690cde31a742cc985e9ee0eaf03` and reviewed PR HEAD
`36ca3f6b777c20b7ccb2d8b175a13ab383c73661`. The merge tree is exactly the
reviewed HEAD tree. The separate [publication decision](../../../ops/decisions/ros-observation-main-publication.json)
records acceptance without replacing historical decisions or selecting a new
Research Ops baseline. This record is submitted and reviewed through its own PR.

## Retained acceptance and independent review

[CI 37893547455](https://github.com/Anhao1314/g1-jev-swarm-lab/actions/runs/37893547455)
completed successfully at executable HEAD
`8886679e56919b476f7c438d6286f9b4914d3af7`. Publisher, subscriber, artifact
upload and explicit real-communication gate all passed. Its executable files,
workflow, joint map and protocol are byte-identical at the final PR HEAD and
accepted main. Later changes only archived receipts/docs and protected raw
receipt bytes in Git attributes; no new live run is needed for that difference.

The accepted [real ROS-R1 report](../r1_runs/attempt_003/README.md) retains
Ubuntu 24.04.5/Jazzy environment details, publisher/probe exit codes 0, exact
source hashes and all 2,127 semantic callback records: 528 joint, 528 pose,
528 provenance, 14 task event and 529 clock messages. All 15 original archive
manifest entries match both the ZIP and accepted Git blobs. Attempts 001 and
002 remain intact as technical failures before DDS delivery.

The [GitHub post-execution independent review](https://github.com/Anhao1314/g1-jev-swarm-lab/pull/15#pullrequestreview-5466682628)
supports bounded publication and states its own remote review limits. This
publication's separate audit additionally reconstructed every callback from
frozen source values without using the publisher/probe comparison helpers:
timestamps, sequence indices, joint values/names, pose/quaternion, full
provenance, event bodies/locators/hashes all matched. No blocker was identified.
No ROS, physics, policy, provider or training execution was used for this audit.

## Main integrity and reproducibility

The [machine-readable main acceptance receipt](main_acceptance.json) binds
all 50 integrated paths to Git SHA-256. Of 2,526 paths on previous main, 2,525
are mode/blob-identical; the only changed preexisting path is `.gitattributes`,
whose additive rule protects new ROS raw receipts. No previous-main file was
deleted. M2.4 evidence/verdict, M2.5A PR #14, controllers, thresholds and
`ops/state.json` are unchanged. Research Ops remains CURRENT, 38/38 anchors.
Its retained design-only text does not supersede M2.4's independent accepted
`INCONCLUSIVE` publication record and is deliberately not refreshed here.

A newly created Windows worktree exposed an environment compatibility limit:
global `core.autocrlf=true` transformed the frozen joint-map LF bytes into CRLF.
The source guard correctly refused those bytes (9 failed / 20 passed). A
checkout-index attempt did not replace the cached materialization and produced
the same failure. Both full [failure logs](logs/) are retained. The accepted
Git blob itself had the correct frozen SHA-256; CRLF-to-LF comparison proved
the local transformation. All 50 integrated files were then restored directly
from the **same immutable accepted-main Git blobs**, with every hash verified.
No Git source, frozen hash, threshold or historical artifact was changed.
The byte-exact checkout passed **29/29** targeted offline tests (0.65 s), with
the [passing log](logs/byte_exact_git_blob_tests_pass.log) retained.

For a fresh reproduction, use Linux or create the Windows clone with
`git -c core.autocrlf=false clone ...` before checkout; verify the receipt's
source hashes, expose this checkout's `src` on `PYTHONPATH`, then run:

```text
python -m pytest -q tests/test_ros_observation_core.py tests/test_ros_observation_ros2_adapter.py
```

Git-tree reproduction checks:

```text
git show -s --format="%H %P %T" 9e5461d182cf365a5ac272b3ce2bd8effe5990d1
git diff --exit-code 36ca3f6b777c20b7ccb2d8b175a13ab383c73661 9e5461d182cf365a5ac272b3ce2bd8effe5990d1
git diff --name-status 0eff13a5cb523690cde31a742cc985e9ee0eaf03 9e5461d182cf365a5ac272b3ce2bd8effe5990d1
```

Research Ops measured three offline test commands, 3.1284 s total, including
the two failed checkout attempts. Other phase timings and token usage are
unmeasured/unavailable; they are not reported as zero. This publication did
not modify Research Ops.

## Research boundary and stopping condition

Acceptance is for one frozen M2.3b historical replay using separate real ROS 2
processes in the recorded CI environment. Selected RMW implementation was not
separately logged; latency/jitter, general DDS ordering, live streaming,
rosbag2/CDR captures, full articulated RViz rendering, control reliability,
production authorization and hardware safety remain unqualified. Windows
byte-preserving checkout is a documented reproducibility prerequisite.

M2.4 remains **`INCONCLUSIVE`**. This publication authorizes no ROS-R2,
new physics, policy/provider experiment, training or robot control. After this
independent publication PR is reviewed and merged by merge commit, verify its
actual main tree, preserve both merge histories, and stop.
