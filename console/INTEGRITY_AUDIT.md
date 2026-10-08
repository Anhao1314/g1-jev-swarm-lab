# Research Console v0.1 integrity audit

This console is a read-only explanation surface. The original Phase 3A evaluator and its frozen node records remain the scoring authority. A plotted instantaneous error is a diagnostic value, not a new task score.

## Fixed historical selection

Both arms use the pre-existing primary `sequence-mixed-16m` case in `frame_residual_learning_001`, with residual disabled. This case is already-seen mechanism/regression evidence, not a fresh held-out experiment. No learned actor, training run, failure retry, or best-of selection is introduced.

| Arm | Decoded evaluation JSONL line | Original duration | Endpoint error | Final global lateral | Final global heading |
| --- | ---: | ---: | ---: | ---: | ---: |
| `alpha0-residual-off` | 26 | 53.772 s | 1.840971814 m | -1.840337303 m | -6.348225198 deg |
| `alpha0.5-residual-off` | 52 | 53.806 s | 1.209069098 m | -1.111641569 m | -1.288572409 deg |

The source is `experiments/phase3a/frame_residual_learning_001/evidence/evaluation/results.jsonl.gz`. Its encoded SHA is `888245e4b897ef8d028ec15039094c322ee1f16296dd06edae6bfcb7909635b8`; its decoded SHA is `04d8d882371ee7186a8dbbe17ea7635457c9eb11da4f4f8b8ff3de692de446e9`. JSONL line locators are one-based and refer to decompressed UTF-8 lines. Node indices are zero-based JSON-array indices.

Both source records name acquisition commit `a4926973e01b65f98fc7c598d48ac982b47d6516`. The trusted publication anchor is `86d1883db84a53de57eacfab061234f2a118c94c`. The frozen protocol SHA is `df0529a7f9f542463eadf99a1b01c36346344bec184009b13b44eef688781afb`. The unchanged base `motion.pt` policy SHA is `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`; neither arm has a residual checkpoint.

The associated command traces contain 540 and 541 rows. Their decoded SHA values are `628237f5212b31fd2ba4616453b28e0570b72b036792f281a73c40dd75a5bd70` and `254f3487f8f211cf2d7a32f380d4971950c677fdc1ed90a96614adf3abc7ab47`. Export bytes, decompressed bytes, and retained acquisition raw files agree with the frozen evidence inventory. The recorded acquisition source hashes also match the working scientific source and that acquisition commit. Receipts are in `audit/source_export_identity.json`.

## Metric semantics

- Actual trajectory is the robot base position in the original world coordinates. It must not be rotated or translated to make the route appear more accurate.
- Local lateral error uses the actual node-start pose and heading, independently of the selected correction frame. This is the historical task contract.
- Global lateral error is the signed perpendicular projection of actual position minus planned origin onto the node-entry planned heading. It is not distance to the nearest ideal polyline segment.
- Planned origin advances by the full commanded walk distance only after a walk ends. Stand, turn, and stop translation does not rebase it. Planned heading advances by the commanded angle only after a turn ends.
- Global heading error during a turn compares actual yaw with planned heading plus the commanded turn angle. Other nodes compare with their planned heading. All angle differences are wrapped.
- Walking correction reference heading is defined for walks. Stand, turn, and stop have no walking-correction reference, so the UI must show an unavailable value.
- Command traces are sampled at command decisions, before the associated physics command. Stored robot poses and rendered frames have their own simulation-time locators. Playback must align by simulation time rather than ordinal frame, normalized progress, or wall-clock completion.
- A formal nominal/strict outcome comes from the frozen completed-node result. During playback, it must be labeled as the node's recorded result; a threshold crossing of a sampled diagnostic is not a freshly evaluated failure.

## Negative result retained

At the first 8 m Walk endpoint (node index 1), alpha 0 local lateral error is `-0.001682466450 m`. Alpha 0.5 local lateral error is `+0.372292344021 m`: nominal PASS against the unchanged `0.56 m` limit, strict FAIL against the unchanged `0.28 m` limit, with frozen reason `EXCESSIVE_DRIFT`. Its global improvement does not erase this local-contract conflict.

## Visual source and observer scope

Historical evidence contains base pose and velocities at command decisions, but its `joint_positions` and `joint_velocities` fields are null. It cannot directly reproduce the original joint-level robot motion. A new native MuJoCo rollout executed by the unchanged runner, with full poses captured for an isolated renderer, must be labeled **derived visualization replay**. It is not original acquisition capture and not playback of original acquired joint states.

Three distinct checks must be kept separate:

1. Historical replay equivalence: new replay results and command traces agree with the historical records, with only explicitly enumerated metadata and wall-time fields removed. This verifies the evidence that actually exists, not unavailable historical joint states.
2. Offline capture parity: newly executed capture-off and capture-on replays have identical physical state, command/decision evidence, RNG state, and outcome. This can establish the offline collector's noninterference.
3. Renderer isolation: rendering consumes frozen copied states in a separate process, never the scientific simulator or controller. Renderer/UI failure cannot alter the already-completed offline run.

No observer is being installed into the PPO training pipeline in this slice. Offline parity is not a claim of proved live-training observer, reward-stream, optimizer, checkpoint, or tensor noninterference. Those remain a gate for a future live-training integration.

The complete base TorchScript `state_dict` includes recurrent `hidden_state` and `cell_state` buffers. Its initial and final digests therefore differ during an ordinary rollout. The capture-off and capture-on executions have identical initial digests and identical final digests; the policy file remains byte-identical. This is execution-state parity, not a claim that recurrent memory remains constant or that PPO was trained.

## Historical preservation

Before implementation, `audit/scientific_snapshot_before.json` recorded hashes and byte sizes of 1,348 tracked source/config/test/Phase 1/2/3A evidence files. The existing freeze verifier passed all nested historical checks, including the 219-file locomotion baseline and the current 669-file Phase 3A history pins. A post-implementation check must establish no changed or missing file in this snapshot and rerun the original freeze verifier.

## Completion receipts

The independent audit completed with 777 original repository tests passing in 125.37 s (75 existing TorchScript deprecation warnings, no skips), and 16 dedicated integrity checks passing. Every saved 20 Hz pose sample was checked against the original node-start local frame and planned commanded frame; source-event values, times, raw JSONL pointers, and formal node statuses also agree. Both newly generated replays match the full original scientific records and every command-trace row. Capture-off/on receipts match all 26,886 / 26,903 physics steps, command/torque/action/observation streams, RNG states, and final policy execution states. The renderer uses 1,077 / 1,078 copied poses without a physics step.

The original 1,348 scientific files remained byte-identical and the chained frozen-baseline verifier passed again. These receipts are in `audit/final_integrity.json`. Server read-only tests and browser visual QA are recorded separately by the implementation's final validation report. This document explains the scientific interpretation and limits; it does not modify or replace original results.

The alpha 0 replay's first comparison certificate falsely failed because the comparator included elapsed wall time and the campaign's publication arm label. The initial certificate and capture manifest remain retained. The corrected comparison uses the same already-acquired physical/command streams, with explicit exclusions; no physics replay was retried to repair that comparator result.
