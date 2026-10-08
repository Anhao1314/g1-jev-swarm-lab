# M2.3 first-stage trusted mission handoff — frozen offline protocol

Frozen before the first integration test campaign on 2026-10-08. This is a
claim-tier interface integration study, not physical acquisition or production
authority qualification. The question is whether issuer-verified immutable
canonical Mission bytes can enter the existing M2.2 lifecycle only when an
explicit TEST_ONLY permission and unchanged live lifecycle binding also hold.

## Baselines and scope

- Accepted embodied baseline: `e9db7a9c25eaf34ea248b34c23c67543c16294c1`
  (M2.2 PR #5, accepted research gate; not yet merged into main).
- Remote main at preparation: `571c0b06d5ff9661d197faed96073263099e14c0`.
- Reviewed Handoff v0 source: `a2325d393c3ffc46eaf7252122b61179ea0e35cb`.
- Independent integration branch/worktree: `m2.3/trusted-mission-handoff`.
- Extract only Handoff v0, simulated principal contract and narrow supporting
  value/request primitives, with an explicit adaptation/provenance manifest.
  Do not merge the Source Authority branch or its provider/release stack.
- Add a wrapper around unchanged `MissionLifecycle` and local TEST_ONLY
  authorizer. Keep Runtime, controller, physics, evaluator, thresholds, old
  scientific decisions and all historical artifacts unchanged.
- No physics, providers, Jev, training, recovery, Console behavior changes,
  Language Runtime/D011 unlock or production principal authority.

## Frozen integration contract

1. The registered v0 issuer binds source, complete canonical plan, actual
   host request, simulated principal confirmation, expiry and interpretation.
2. Bridge preparation binds the actual lifecycle/session owner, the existing
   lifecycle assessment/parent/raw-state binding, a host-frozen canonical-plan
   allowlist, strict boolean TEST_ONLY execution opt-in, and integration code
   epoch. Permission is experiment host policy, not a human identity claim.
3. Dispatch first attempts one-use consumption of the registered v0 grant;
   registered mismatches/refusals burn it. It then validates bridge binding,
   current permission, epoch and a fresh physical/lifecycle assessment.
4. The only execution input is a newly parsed private Mission from the
   issuer-owned immutable bytes returned by consumption. Never execute the
   caller's original mutable dict or Mission. The v0 canonical-plan digest
   and M2.2 `Mission.to_dict()` digest are different encodings and are checked
   in their respective domains, not compared directly.
5. On refusal, do not execute, reset, revive blocked nodes or write over
   parent evidence. Record explicit reason and keep original parent result,
   Task Graph and artifact bytes. ABSTAIN/ESCALATE is not a physical halt.
6. Trusted serial, in-process TEST_ONLY entry only. No claim of atomic robot
   dispatch, concurrent/durable replay defense, production permission,
   continuous revocation, cancellation or generalized physical safety.

## Frozen offline matrix

Use existing grounded new Oracle mission and M2.2 fake-session fixtures with
a forbidden simulator factory. Synthetic fixture outcomes are explicitly
offline evidence, not new physical successes. Existing M2.2 raw halt state
may be read as a labelled fixture if needed, without inventing controller
memory continuity. No new task/profile/state search.

- Positive: valid registered grant, detached equal plan, and caller mutation
  at the consumption boundary; prove complete executed plan equals retained
  issuer canonical bytes, same session used and parent evidence preserved.
- Plan negatives: parameters, identity, skill, dependencies/order/schema and
  experimental override changes; no partial-plan hash authorization.
- Credential/context negatives: missing/forged/copied/replayed/revoked grant,
  wrong source or request, unregistered/expired/revoked fixture principal.
- Permission negatives: missing/false/truthy opt-in and plan outside host
  frozen allowlist. A valid principal alone is insufficient.
- State negatives: another lifecycle/session with the same serialized ID,
  steps/time/raw qpos/qvel/ctrl/controller memory changes, moving/fallen or
  invalid state, failed/incomplete halt, changed parent result/graph,
  reused old mission/node ID and occupied evidence path.
- Interpretation negative: changed integration/lifecycle code epoch.
- Every dispatch negative checks no new task call/step/reset, retains reason
  and parent bytes; registered attempted consumption cannot later succeed.

Some duplicate lifecycle conditions can reuse existing affected offline tests;
identify reuse explicitly. No assertion of an all-inputs proof.

## Validation and stopping rule

Run the new offline bridge matrix and affected M2.2 lifecycle/halt/mission IR
tests, excluding the two real live-session tests by exact test names. Exercise
the adapted v0 principal/handoff contract without importing unrelated release
modules. Run Research Ops anchors/targeted Ops tests and historical byte audit.
Independent review covers implementation, negative evidence and interpretation.
Keep failed checks and corrections as separate receipts; do not overwrite them.

Stop when the canonical execution path and rejection matrix support a bounded
offline implementation verdict, or report BLOCKED/PARTIAL if they do not.
New physics is warranted only for a changed physical execution claim; the
wrapper leaves the existing execution/physical gate unchanged, so first-stage
offline compatibility does not itself require a new MuJoCo acquisition.
Deliver a separate reviewable PR, explicitly dependent on unmerged PR #5;
do not merge main or advance a scientific pointer automatically.
