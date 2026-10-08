# Phase 3B.1a — Temporal risk observability

## Decision

`STATE_INFORMATION_INSUFFICIENT`. This describes the retained evidence, not a proof that the robot's early execution state lacks predictive information. The exact Phase 3B.1 cohort has valid 0, 1, and 2 second samples before strict endpoint, but the historical per-step traces do not record the planar pose, heading, velocity, yaw rate, local tracking error, or reference error needed to test whether strict geometric risk becomes observable in that window. No early-execution Jev shadow protocol is justified by this study.

## Frozen scope and attribution

The source remains the 24 frozen-baseline walk-node cells and 18 distinct model-visible units from Phase 3B.1. Its result is unchanged: seven false-safe, four true-positive, and seven true-safe visible units. All seven false-safe units are early walks: two primitive first walks, three transition first walks, and the first walk of each 12m/16m sequence. All four true positives are later sequence walks, nodes 3 and 5. The grouped source cells are retained separately in `snapshots.json`; duplicate cells are not treated as independent units in this attribution.

The entry representation has no *exact* same-input/opposite-label conflict. Nearby stand-to-walk states do have opposite future labels: illustrative 1.5m pass/fail starts differ in lateral error about -0.053/-0.099m and heading about -2.17/-3.22 degrees; illustrative 3m starts differ about -0.064/-0.132m and -2.63/-3.92 degrees. These small, correlated comparisons establish neither a general boundary nor a missing-information cause. Primitive 4m/8m failures start at zero geometry/velocity; later sequence true positives start with large accumulated route/heading errors.

The added entry velocity/yaw-rate view in Phase 3B.1 changed no binary Jev decision. This demonstrates no gain from that exact input variant and model response. It does not prove velocity is intrinsically uninformative, nor that a short temporal trend would help. The pattern is consistent with early incipient and later accumulated-error situations, but the historical trace does not support assigning distinct physical failure mechanisms.

## Fixed historical snapshots

The protocol fixed elapsed node times at 0, 1, and 2 seconds before extraction. All 24 walk-node cells have exact recorded samples at each time, and the earliest strict endpoint is after 3.422 seconds. The 20 corresponding case traces provide only node/time, commands/actions, reset count, height, and tilt. They do not provide the requested geometric or velocity fields; endpoint states and aggregate node metrics were not substituted because that would leak future information.

Using one declared representative source cell per visible unit, the recorded physical channels overlap:

| Prior Jev class | Units | Tilt at 1s | Tilt at 2s | Height change 0–2s |
| --- | ---: | ---: | ---: | ---: |
| True-safe | 7 | 2.808–4.945° | 0.514–0.624° | -25.8 to -8.8 mm |
| False-safe | 7 | 3.533–4.687° | 0.559–0.593° | -25.8 to -8.3 mm |
| True-positive | 4 | 2.947–4.911° | 0.510–0.640° | -12.3 to -9.8 mm |

These are descriptive ranges, not a trained classifier. The predeclared height/absolute-tilt trend also overlaps; no threshold was selected from these data. Commands record what the controller requested, not the unrecorded lateral or heading response.

## Deterministic controls and limits

An always-risk control is correct on 11/18 units and has zero false-safe but seven false alarms. A **post-hoc, contract-derived descriptive control** that flags a state only when its *entry* heading or lateral error already exceeds the frozen strict limit is also correct on 11/18; it has seven false-safe and zero false alarms. Its binary results agree with all 18 prior Jev predictions. This agreement does not reveal Jev's internal reasoning, but it shows no demonstrated predictive gain over recognizing already-present strict-limit breaches in this cohort. The rule was not used to tune Phase 3B.1 or propose a new threshold.

The source and trace hashes, cell membership, exact sample times, and unavailable fields are retained in `snapshots.json`; `analysis.json` retains the per-unit controls and selected physical readings. This is previously seen, correlated development evidence, without fresh held-out data or a generalization claim. The Phase 3B.1 prompt, threshold, membership, state schema, negative result, and historical traces remain unchanged. No Jev API call, new physics, robot actuation, PPO, or controller intervention occurred.

The stopping reason is evidentiary: the fields required to test the central 1–2 second geometric-risk hypothesis were not recorded. Continuing with additional Jev fields or prompt changes on these traces would not answer it.

Research Ops v0.1 routed this as a mechanism study. Measured context validation took 0.288 s, historical snapshot reproducibility 0.116 s, two focused test runs 0.665 s total, and source/missingness audit 0.084 s. Reasoning, implementation, and independent review were performed but not separately timed; token usage is unavailable. Three focused tests passed. No telemetry value was inferred for an unmeasured stage.
