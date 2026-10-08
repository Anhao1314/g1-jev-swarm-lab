# Authority-to-Execution Handoff Contract v0

## Scope and decision

Offline TEST_ONLY principal handoff; no production identity or Runtime integration. This contract closes the mutable-plan gap at a proposed pre-dispatch boundary. It does not upgrade any existing production gate. Existing bounded/source-unique release remains unchanged and is not yet integrated with handoff. CompilerResult.SUCCESS, diagnostics, JSON receipts and the old mutable B Mission are not handoff capabilities.

## Minimal interface

`OfflineHandoff.authorize(source, mission, context, authority, confirmation, allow_test_principal=True)` consumes the actual host request and registered confirmation, independently verifies it, snapshots the complete canonical Mission, and issues an opaque registered HandoffGrant. Invalid authorization produces no grant. No model/source verifier is consulted. Missing principal authentication remains TEST_ONLY; default calls fail closed.

`OfflineHandoff.consume(grant, source, mission, context, allow_test_principal=True)` is the offline pre-dispatch check. It rejects unregistered/copied/forged grants, altered bodies, mismatched source/request/plan, expired or revoked principal sessions, changed consent objects, changed semantics, and repeated/revoked grants. A valid registered consumption attempt burns the grant even if binding validation fails. A new confirmation and fresh host request are required to retry; there is no automatic fallback or renewal.

The return value is immutable UTF-8 canonical Mission bytes stored privately at issuance, not the caller's mutable Mission or an attribute re-read from the external grant. Full identity includes mission_id, schema, every step/id/skill/parameter/dependency and frozen interpretation digest. Human authorization origin, principal/session identity, source, full plan, request context, presentation and expiration remain independently bound. Original source uniqueness remains false; the grant scope is NEW_EXPLICIT_PLAN_INSTRUCTION_NOT_SOURCE_UNIQUENESS. TEST_ONLY assurance and production_authority=False cannot be promoted by editing the object or its serialized representation.

`revoke(grant)` invalidates an issued handoff before consumption. `revoke_session(session)` invalidates its outstanding handoffs. The principal authority performs a locked live identity check at consumption, including original confirmation/presentation sealed bodies, consumed-confirmation ledger state, exact original request identity, session revocation, monotonic expiry and semantics digest. Restart/new service refuses old capabilities. Expiration is monotonic and process-local; this is not a durable multi-host identity platform.

## Future Single-Agent Runtime boundary

The successful locked principal identity check during consume is the proposed dispatch linearization point. A future trusted adapter must immediately decode/use ONLY the returned canonical bytes; it must not substitute an earlier Mission, a newly edited plan, or fields from release diagnostics. No callback or executor is included in v0. The bytes are a snapshot, not reusable credentials, permanent permission or authorization to delay execution beyond this boundary. Any delayed dispatch must acquire and validate a new grant. Post-dispatch cancellation or continuous expiry enforcement during physical execution is not claimed. Revocation preceding the check blocks dispatch; revocation after dispatch cannot retroactively undo it.

A future production adapter requires credible principal authentication and trusted consent presentation plus a production authority issuer and execution integration. This prototype supplies none of them. Arbitrary trusted-host Python code compromise is outside the capability threat model. Python frozen dataclasses are convenience wrappers, not the security root; private issuer registration, sealed bodies and internally retained immutable bytes enforce tested boundaries.

## Compatibility and stopping boundary

No CompilerStatus, public apply_gate behavior, frozen source labels, thresholds or historical artifacts are rewritten. The existing human principal module gains only a read-only post-consumption revalidation method and includes handoff implementation in its semantics digest; old interpretation-bound consent deliberately becomes invalid across code changes. Existing simulations, training, model providers and Runtime remain untouched.

Verdict and exact regression results are in verification.json. The inherited ten failures remain classified in the previous human-principal report, with unchanged identities; no old expectations were changed. All preexisting scientific and prior closeout artifacts are hash-checked. This is an offline boundary result, not evidence of safe production execution. D011 and Language Runtime remain BLOCKED. Stop after tests, audit, historical integrity and Git closeout.
