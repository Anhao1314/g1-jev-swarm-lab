# Trusted Mission Handoff Integration — TEST_ONLY contract

This first-stage adapter connects reviewed Handoff v0 to the accepted M2.2
same-session lifecycle. It is an explicit trusted, serial experiment entry.
It does not authenticate human principals or upgrade Language Runtime/D011.

## Cross-branch compatibility

| Concern | Reviewed v0 capability | M2.3 bridge / unchanged M2.2 requirement |
| --- | --- | --- |
| Mission identity | Complete canonical IR, including all IDs, parameters and dependencies; overrides refused | Execute a new private parse of issuer-retained bytes only |
| Source authority | Registered TEST_ONLY principal confirms a new explicit plan | Original source uniqueness remains false; no compiler/verifier proposal becomes authority |
| Fixture identity | Exact registered session, presentation and confirmation; expiry/revocation rechecked | Exact configured issuer; no portable JSON or principal-name identity proof |
| Execution permission | Principal confirmation does not define a Runtime role | Copied host policy grants `TEST_ONLY_SAME_SESSION_NEW_MISSION` for a fixture principal plus full canonical-plan digest; strict boolean opt-in |
| Request | Exact registered host request, bound source/context | Preparation owns the request; dispatch requires the same context and source |
| Once-only use | v0 locks registered consumption, burns attempted mismatches | Bridge preparation also records consumption; no automatic retry/renewal or fallback |
| Physical condition | Not supplied by v0 | Actual lifecycle/session object plus exact halted state, raw execution fields, original result/graph and fresh assessment binding |
| Interpretation | v0 presentation semantics pin | Adapted pins include bridge, support, M2.2 lifecycle/runtime/live session and existing IR/Guard/skills/grounding |
| Parent history | Not supplied by v0 | Existing failed result/blocked graph stays failed; distinct new IDs/evidence directory, no reset or node resurrection |

The accepted baseline and reviewed source branch use byte-identical IR,
validator, canonicalizer, Guard and skill definitions. Their Runtime/lifecycle
history differs. The selective compatibility extraction avoids importing the
source branch's unrelated provider, certificate, bounded release and Compiler
status paths. Exact source blobs and adaptations are in
`src/g1swarm/trusted_handoff_v0/source_manifest.json`.

Two digest domains deliberately coexist: v0 `handoff_plan_sha256` hashes the
complete canonical document (including empty `depends_on`); M2.2
`lifecycle_mission_sha256` hashes `Mission.to_dict()`, which omits empty
dependencies. Both derive from the same private parsed plan. They are not
interchangeable credentials.

## Trusted entry sequence

1. A trusted experiment host constructs `TrustedMissionHandoff` with the
   exact existing `MissionLifecycle`, v0 issuer, principal issuer, copied
   principal/plan permission policy and `allow_test_principal=True`.
2. `prepare(source, mission)` parses a private Mission and checks the frozen
   plan permission envelope plus existing M2.2 eligibility. The registered
   preparation binds canonical bytes, request, actual owners, physical/parent
   assessment, policy and interpretation epoch.
3. The same fixture principal issuer presents the full plan and registers
   an explicit CONFIRM. `OfflineHandoff.authorize` independently checks and
   consumes that confirmation/request before issuing its registered grant.
4. `dispatch(...)` consumes that grant first. Plan/source/context/identity
   failures burn registered attempts; an expired/revoked grant cannot dispatch.
   It then checks registered preparation, owners, epoch, permission policy,
   full plan, principal continuation permission and fresh M2.2 state binding.
5. Only returned issuer-owned bytes are decoded into the executable Mission.
   The existing local TEST_ONLY authorizer and lifecycle perform their own
   binding and immediate assessment before the existing executor is called.
6. A refusal returns `ESCALATE`, its reason, consumption status and parent
   preservation status; no new task is executed. Positive and negative
   decisions are appended to bridge/lifecycle events for the experiment host
   to record. The adapter does not claim ESCALATE physically stops the robot.

`PreparedMissionHandoff` and `HandoffGrant` public fields are display/issuance
data. Reconstructed or edited dataclasses do not establish authority; private
issuer/preparation registration and retained bytes remain authoritative.

## Limits and experiment decision

The runtime seam is a trusted Python entry, not a universal enforcement layer.
The underlying executor remains callable. Simulated fixture sessions do not
establish Human Principal Authority; permission is explicit experiment host
configuration. A lock inside v0 proves one source-consumption boundary, not
atomic robot dispatch. Parallel/multi-process callers, persistent credentials,
host compromise, continuously enforced expiry/revocation and cancellation are
outside this stage. No new hardware or physical restart qualification follows.

No physical acquisition is necessary for this first-stage interface question:
the adapter leaves controller, simulator, Runtime, lifecycle and physical
criteria byte-identical. Retained M2.2 physics applies only to its previously
seen bounded same-session state. A future real handoff physics study would need
its own freeze and reviewed authorization; it is not launched here.
