# Research Console v0.1 — native replay vertical slice

Implementation verdict: **PASS**. A real native MuJoCo G1 visual replay is
connected to synchronized retained-state diagnostics, world-coordinate routes,
and an Inspector that reaches the frozen original result and raw provenance.

Local address: **http://127.0.0.1:8765**. This is a read-only historical replay
workstation, with two residual-off arms on the fixed `sequence-mixed-16m` case.
It is not an active training stream. Phase3A.5 reward-alignment remains paused.

## Native visual gate and artifacts

Windows native GLFW offscreen rendering passed before frontend construction:
three separate contexts, 60 non-error frames, real official G1 meshes, unchanged
pose, median render 0.9223ms and p95 3.5369ms. The gate retains its actual PNG and
receipt in `renderer_gate/`. Cross-context RGB bit identity was false and is
reported as such; it is not a scoring criterion or a state identity claim.

Both full clips are 960×540 H.264 at 20fps, with explicit frame-to-simulation-time
maps and the exact final pose retained. There are 1,077 α=0 and 1,078 α=0.5 frames.
Each clip is about 4.3MB. Separate render processes load their own model/data/GL
context after physics acquisition finishes. They call `mj_forward` on restored
poses and **zero `mj_step` calls**. Camera and framebuffer changes affect only
that rendering clone. No controller, reward, gain, PD or physics change was made.

All clips are **`derived_visualization_replay`**, never original acquisition
recordings. The historical acquisition lacks full joint poses and video. The
newly authorized deterministic replay retains qpos/qvel/ctrl and its metadata;
the full scientific record and original command trace match exactly. Original
joint-pose equality cannot be claimed because those arrays were never recorded.

## Preserved scientific comparison

The selected records are the unique original primary rows, decoded JSONL lines
26 and 52, not selected for favorable appearance. Both use the same frozen
16m case: Stand10s → Walk8m → Turn−90° → Walk4m → Turn+90° → Walk4m → Stop.

| Original machine metric | α=0 residual off | α=0.5 residual off |
|---|---:|---:|
| Final ideal lateral error, m | −1.840337303 | −1.111641569 |
| Final ideal heading error, deg | −6.348225198 | −1.288572409 |
| Final endpoint error, m | 1.840971814 | 1.209069098 |
| First8m local lateral drift, m | −0.001682466 | +0.372292344 |
| Nominal case outcome | PASS | PASS |
| Physical case outcome | PASS | PASS |
| Strict case outcome | PASS | **FAIL — EXCESSIVE_DRIFT** |

These are existing research results displayed faithfully, not a new experiment
score or learned gain. The nominal first8m lateral limit is 0.56m and the strict
limit is 0.28m. Neither was edited. Case-level strict FAIL remains visible in
the video header even when the current Stop node itself has strict PASS.

At 20s the UI shows both correction references (−5.37° / −2.68°), actual headings
(−6.13° / −3.41°), local errors (−0.013m / +0.204m), and global errors
(−0.632m / −0.415m). The local measurement frame stays actual node start; the
correction reference is separate. Global error uses the original planned
axis/origin semantics; a Turn's commanded heading is its ideal target heading.
The actual path is never rotated or recentered to make a treatment look better.

## Provenance and Inspector chain

Scientific experiment: `frame_residual_learning_001`.

Scientific acquisition commit:
`a4926973e01b65f98fc7c598d48ac982b47d6516`.

Retained evidence publication commit:
`86d1883db84a53de57eacfab061234f2a118c94c`.

Frozen protocol SHA:
`df0529a7f9f542463eadf99a1b01c36346344bec184009b13b44eef688781afb`.

Official `motion.pt` SHA:
`cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`.

The captured producer bytes are reproducible from commit
`70e436f4e75a66c46e47e8a00506e786f600f9de`; the actual execution base commit remains
separately recorded as `86d1883`. Capture and comparison-validation byte hashes
are distinct where the initial comparison receipt was corrected. The α=0
initial producer source is retained in `console/archive/capture_initial.py.txt`.

An actual route-point click on the midpoint's first8m end opened the Inspector
at original `lateral_drift_m = 0.37229234402137323` and bound it to:

`experiments/phase3a/frame_residual_learning_001/evidence/evaluation/results.jsonl.gz#decoded-line=52&pointer=/nodes/1/lateral_drift_m`.

The video shows its nearest captured frame at 27.10s, explicitly −0.012s from
the original node-end event at 27.112s. An instantaneous metric click at 20s
instead binds to `runs/alpha05-off/poses.npz#frame=400` and the derived JSON
`/raw/alpha05-off/derived-run#samples/400`. Original 10Hz trace context is kept
separate from the new 20Hz pose-derived diagnostic.

The original protocol, original result gzip, original trace gzip, evidence
manifest, derived capture/render manifests, state archive and parity certificate
are downloadable through verified allowlisted raw links. The actual browser
Inspector → full provenance JSON navigation was completed and checked. No
learned checkpoint is claimed; checkpoint and seed are explicitly not applicable.

## Observer and scientific integrity

Capture off/on paired offline executions compare every physics step:
26,886 steps for α=0, 26,903 for α=0.5. Commands, torques, actual base-policy
observations/actions, residual observations, qpos/qvel/ctrl/time, RNG states,
final recurrent policy tensors, outcomes and complete command traces are exact.
The audit wrappers are common to both executions; source record/trace matching
separately supports their noninterference. The official recurrent hidden/cell
state changes during execution normally; paired final state is identical and
the policy file remains unchanged.

Reward calls = 0, optimizer updates = 0, checkpoint writes = 0. This is a
residual-off capture certificate. **No future live PPO observer was added or
certified.** Rendering, encoding and browsing are absent from the physics
process; their latency or crash cannot block or change that completed execution.

The initial α=0 receipt incorrectly included wall-clock timing and an inherited
reference-mode publication label in its equality check. It is retained as
`initial_certificate_bug.json`; its physics/command/observation/RNG receipts were
already exactly equal. The comparator was corrected from saved records with
only those explicit exclusions. No scientific replay was retried for this
correction, and no historical score was changed.

The independent audit verified 1,348 tracked scientific/config/test/evidence
files byte-for-byte unchanged, plus chained frozen history checks including the
219-file foundation and 669-file current historical freeze.

## Validation

- Original full test suite: **777 PASS**, 75 existing TorchScript deprecation
  warnings, no skips.
- Console Python tests: **46 PASS** (30 backend, 16 independent integrity).
- Frontend retained-frame/data-contract tests: **6 PASS**.
- Native offscreen gate and both complete rendering receipts: PASS.
- Independent per-frame metrics, source events and final summary arithmetic: PASS.
- Actual HTTP tests: original rows26/52, all source/derived hashes and raw
  downloads, MP4 Range206 seeking, write-method rejection, denied unlisted
  training/evaluation paths and path traversal: PASS.
- Browser QA: real robot media decode, Play/Pause with advancing time, shared
  comparison, seek, exact final state, route marker → Inspector → raw provenance,
  derived metric → retained pose locator, treatment focus and strict failure
  distinction: PASS. The screenshots and receipt are under `console/qa/`.

A Windows download-abort transport exception was found by real HTTP testing and
fixed in the read-only server. It affects connection cleanup only, not evidence
or simulation. No browser error was substituted with a fake visual.

## Limits and stopping boundary

This slice covers one seen regression case and two deterministic residual-off
arms. It has no live training telemetry, learned progression, generic checkpoint
UI, complete dashboard, experiment controls, Jev or Multi-Swarm. Playback uses
20Hz decimated state; contact-force analysis requires original machine evidence.
Frozen results remain the sole scoring authority. All negative strict evidence
and the initial comparator diagnostic are retained. This implementation changes
no research gate and stops before any new training experiment.
