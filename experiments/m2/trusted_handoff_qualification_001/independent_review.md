# Independent M2.3b qualification review

**PASS_INDEPENDENT_REAL_HANDOFF_AUDIT.** Saved evidence supports
`PASS_BOUNDED_REAL_MUJOCO_TRUSTED_HANDOFF` for the predeclared, previously seen
seed-0 same-session TEST_ONLY task. No blocking integrity or interpretation
issue was found. This is a bounded simulator integration result, not production
identity, concurrent atomicity, generalized recovery or hardware safety.

The independent auditor executed no physics. `audit.py` recomputes 64 checks
from saved receipts, canonical documents, actual executor entries, Task Graphs,
physical node dispatch records, raw state snapshots, native pose arrays and
per-step physical traces. It does not accept the acquisition's qualification
booleans as proof. Exact reviewed evidence hashes and auditor-code hash are in
`audit.json`; the measured audit command is retained by Research Ops.

Protocol and runner were reviewed before physics. The preflight identified a
missing explicit raw-state comparison at actual executor entry; it was added
before source freeze, with only the observer's `executor_calls + 1` normalized.
The protocol, runner, source manifest and preflight audit bytes match freeze
commit `e8c13333111fe7f07b68d7012175fb9ccba9db8f`. All 158 frozen source/asset files
still match their byte hashes. The seven original Source Authority Git blobs
were reverified at `a2325d393c3ffc46eaf7252122b61179ea0e35cb`; this remains selective
compatibility extraction, not adoption of its whole branch or language release.

The authorized arm has 13,128 total physical steps: the unchanged failed
parent/halt prefix plus 5,989 new-task steps. The issuer-retained canonical
Mission, actual executor-entry Mission, recorded Mission manifest, Task Graph
steps and real dispatched skill nodes match completely. The two canonical
digest domains were independently recomputed: Handoff includes empty
dependencies; the lifecycle Mission encoding omits them. Their different hashes
correctly describe the same immutable plan. Session, simulator and controller
identity remain unchanged, and raw position/velocity/control/time/controller
memory at executor entry matches the predispatch snapshot exactly.

The new Walk4/Turn45/Stop task completes all three nodes. Independent projection
of actual node start/end states yields Walk distance error 0.000737766 m,
lateral drift -0.020910303 m, heading error 0.068284997 degrees and duration
8.65 s, within the unchanged strict limits. Final raw planar speed is
0.006407282 m/s; the complete final 500-step/1-second Stop window has mean
0.067645719 m/s. The new-task trace remains finite and standing with no fall.
The original parent remains FAILED, with `s1` FAILED and `s2`/`s3` BLOCKED;
its result bytes, graph and every original ledger-file hash remain unchanged.

The matched invalid arm has exactly 7,139 parent/halt steps and no new Mission
or executor entry. Its five predeclared controls retain the reasons
`UNTRUSTED_HANDOFF`, `UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF`, `PLAN_CHANGED`,
`UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF`, and
`PRINCIPAL_CONTINUATION_PERMISSION_MISSING`. Every request has zero incremental
physics, skill-node, executor or reset calls and exact unchanged raw state and
controller memory. Successful-arm replay is likewise refused with zero
incremental execution. These are six request-level controls across two runs,
not six independent physical-state samples.

Both arms contain the expected two initialization resets, including native
`mj_resetData` observations, and zero later resets or keyframe resets. Each
arm's complete saved pose arrays and every physical trace row are independently
equal to its corresponding retained M2.2 run. This supports observer equivalence
and unchanged physical execution for these exact tasks; normal-task evidence
is reused because the controller and Runtime are unchanged.

The parent halt's independently recomputed last-second mean speed is
0.099969582 m/s against the unchanged 0.10 m/s criterion, a narrow margin that
must remain visible. Simulated principal confirmation and host execution
permission are separate TEST_ONLY controls. No authenticated Human Principal
Authority, durable replay protection, concurrent consume-and-dispatch atomicity,
continuous revocation, hardware-safe stop or autonomous recovery is established.
Jev and Language Runtime/D011 remain blocked. Single-seed exact repeats provide
reproducibility evidence, not independent-state generalization.

The frozen question is answered without further sampling or threshold changes.
No additional physical experiment is justified for this delivery. Console and
Git closeout remain separate presentation/integration checks and cannot change
these scientific outcomes.
