# Phase 3B.1 — Jev offline strict-risk shadow

## Verdict

`JEV_RISK_ROLE_NOT_SUPPORTED` for progression to online shadow under this frozen contract. Jev returned usable typed responses for every offline request, but classified seven of eleven actual strict violations as safe in both paired state views. Those false-safe judgments had confidence from 0.84 to 0.96. No G1 command or Runtime decision used these outputs.

## Freeze and provenance

The non-scored synthetic preflight passed before scored acquisition: `/v1/models` returned HTTP 200 and listed `jev-latest`; the typed choice response parsed into probability and confidence, reported token usage, and identified `jev-1.13.0`. The preflight made two transport attempts (model listing and synthetic question), with approximately 0.829 s and 0.718 s latency. It contained no scientific benchmark state or label.

Benchmark, protocol, source hashes, client, runner, and scorer were committed at `d6db2ce` before scored calls. The primary target is future strict violation of the current `walk_forward` node under the Phase 3A frozen baseline. The 24 historical node cells yield 20 raw predecision states and 18 distinct model-visible assessment units per view (11 violation, 7 pass). All are previously seen development/regression evidence; there is no training split or fresh held-out claim. The primary view contains controller/decision epoch, previous skill, planned distance/speed, route-frame position and heading error, and the frozen strict limits. The paired secondary view adds route-frame planar velocity and yaw rate. Labels, family/case IDs, future states, and outcomes were excluded from requests. The fixed binary threshold was 0.5; confidence below 0.6 was only a descriptive flag.

## Results

| View | Available | Accuracy | False-safe | False-alarm | Brier | Median request latency | Reported tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Geometry only | 18/18 | 11/18 (61.1%) | 7/11 (63.6%) | 0/7 | 0.3600 | 0.828 s | 9,496 input / 790 output |
| Geometry + velocity/yaw-rate | 18/18 | 11/18 (61.1%) | 7/11 (63.6%) | 0/7 | 0.3467 | 0.9295 s | 10,924 input / 790 output |

All 36 calls completed, with one attempt each, no timeout, no provider failure, and no low-confidence flag. The resolved model was `jev-1.13.0` throughout. Both views made identical binary predictions. The same false-safe cells were `eval-tw-02`, `eval-sw-03`, `eval-sw-04`, `primitive-walk-4`, `primitive-walk-8`, and the first walk nodes of `sequence-mixed-12m` and `sequence-mixed-16m`. Their violation probabilities were only 0.02–0.08 in the primary view and 0.03–0.08 in the paired view. Four later sequence nodes were correctly identified as violations with probability 1.0; this does not repair the high-confidence misses at earlier decision points.

The observed accuracy merely equals an always-risk decision on this 11/18 risk-heavy set, whereas that trivial decision has zero false-safe. A constant prevalence probability has Brier about 0.238, below both Jev Brier values. These comparisons are descriptive in this tiny, correlated development cohort, not fitted baselines or generalization estimates. No P95 or stable calibration claim is made.

## Integrity and limits

The source files and nine frozen assets matched their recorded SHA-256 values. Raw request/response files are retained write-once in ignored local artifacts; their hashes are listed in `raw_manifest.json`. `result.json` retains all per-state typed probabilities, confidence, correctness, latency, attempts, and token usage. The API key came only from `JEV_API_KEY`; request records contain no authorization header or key field, and neither Git nor Research Ops telemetry contains the key. Preflight is excluded from the 36 scored calls.

The cohort is small and correlated: six failing source cells come from two sequence missions, and outcome differs sharply by task family. The view includes observable route/skill context but cannot establish independent-seed discrimination or calibration. These limits narrow the conclusion to this contract and evidence; they do not excuse the seven observed false-safe decisions or authorize a threshold, prompt, or state change after the result.

No new physics, robot actuation, PPO, recovery search, reward tuning, Multi-Swarm, Language Runtime integration, or online shadow occurred. The stopping rule is the predeclared 36-call completion plus a safety-relevant negative result; no follow-on model or state search is started.

Research Ops v0.1 routed this as a mechanism experiment. Measured stages were context 0.432 s, scored experiment 32.330 s, focused tests 0.385 s, and source-integrity audit 0.077 s. Preflight, reasoning, implementation, and independent agent review were performed but not timed by Research Ops; no token count is available, so none is imputed. The focused suite passed 19 tests. Scope closeout reported no tracked changes outside this study; unrelated untracked files were preserved.
