# M2.4 Acquisition Readiness — BLOCKED

The experiment-only adapter and engineering preflight are complete, but **final independent interpretation approval is outstanding**. Do not run physics. The independent reviewer stopped at the account usage limit before final code/freeze review; partial messages and its separately authored hash-audit program are retained. Root ran that read-only audit successfully, which does not substitute for missing final independent approval.

## Frozen scope

PR #8 design at be6947964dd97f036b41447868fbe781f95e8f57 is unchanged. The execution protocol is an exact byte copy. Seven cells, fixed state construction and authorization controls, seed, strict/halt/eligibility thresholds, policy/controller/PD/reference, maximum 270000 steps and 120s per arm /840s campaign remain frozen. Source package is experiments/m2/cross_state_reliability_001; design IDs remain original scientific provenance. No Runtime, config, historical evidence or Research Ops selection changed.

## Implemented adapter

Conditional NO_HALT_TRIGGER, HALT_FAILED, MISSING_EVIDENCE/INELIGIBLE and authorization refusal paths retain parent evidence and uncovered controls without grant issuance. Correct grants execute issuer-owned complete canonical Mission through the existing lifecycle. Child strict/physical failure remains a negative; normal control has explicit expected3/3/no-halt checks and a regression label. Parent result/graph/ledger integrity is checked on early returns too.

A fixed push uses the existing DisturbanceProxy, native first-Walk time +1.0..+1.2s, clearing force after the window/on error and checking zero before halt. Witnesses capture reset attempts, native/call-through steps, qpos/qvel/ctrl/forces/controller memory and exact paired prefix before handoff. The deliberately stale tick uses unchanged ctrl without policy evaluation and is counted separately from zero-dispatch refusals.

The external process supervisor enforces per-arm and remaining campaign wall budget even when worker native code blocks. Each cell runs once; no retry or overwrite is allowed. Per-native-step line-buffered journals preserve completed observations on termination. Partial receipts distinguish completed counters, persisted current-arm journal rows and unknown in-flight native work. Simulator closure and refusal are not physical safety claims.

## Asset / dependency / source freeze

91 official files copied from the previously verified local M2.3b worktree, each matching its retained SHA256; no downloads or asset commits. Unitree pin276801e46c5d433564f24658bac64f254b7d2d4b and policy SHA cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d unchanged. Pure XML parsing checked28 resource references; no MuJoCo model was built. 41 installed package versions plus Python/interpreter identity are locked without installation or dependency changes. These are version identities, not a byte-for-byte hash of every installed wheel binary. The source manifest hashes240 files including executable sources, inherited helpers, design/grounding/evidence inputs, official assets and independent checks. Execution uses this checkout/src, not the old editable source pointer.

## No-physics checks and limitations

Final guarded suite:23PASS. Actual Runtime/lifecycle/handoff are exercised with fake sessions; actual production witness/push hook assembly is exercised with Python simulator substitutes. Real simulator construction/reset/step/forward and policy loading are forbidden tripwires. Tests cover conditional failures, complete plan/refusal/replay/stale state, exact synthetic paired prefix, reset rejection, finite push boundaries/cleanup, budget exhaustion, supervised dummy blocked process and partial/no-retry/no-overwrite behavior. These do not prove new physical outcomes or real engine observer equivalence; the seen-state comparison remains an acquisition-time gate within the seven cells.

All attempts are retained: initial17PASS, a collection failure from a root patch indentation error, then corrected final23PASS. Engineering fixes reset the supervisor arm clock without resetting the campaign clock, grade normal control regression explicitly, and surface swallowed integrity violations. Historical tests/evidence were not rewritten.

The separately authored readonly_audit.py PASS verifies91 assets,41 versions,240 frozen files and zero historical tracked changes. Research Ops remains CURRENT38/38 with the original M2.3b bounded scientific conclusion; no M2.4 result or selection promotion. Measured test/audit telemetry is retained; unmeasured reasoning/implementation and tokens remain unavailable.

## Remaining gate / stop

One required blocker: a reviewer independent of implementation must review the final frozen source, production hook behavior, guarded receipts and interpretation and issue an explicit final readiness decision. BLOCKED readiness_manifest.json denies acquisition. Any subsequent readiness supersession must preserve this report and failed receipts. Even after READY, separate explicit physics authorization is required. PR #8 is not merged; this readiness PR is stacked on its frozen design, not a claim of main acceptance for M2.4.

This task performed zero real physics, policy loads/inferences, provider calls, training or experimental outcome acquisition. No Jev/PPO/Multi-Swarm/Language Runtime/D011. Stop after independent PR delivery, waiting for review and later physical authorization.
