# Human Principal Authority — Contract & Offline Prototype

Verdict: PASS_TEST_ONLY_WITH_INHERITED_FAILURES. No production principal identity or execution permission has been established. D011 and Language Runtime remain BLOCKED.

## Contract decision

An ambiguous source cannot acquire uniqueness from a model proposal or from subsequent consent. An explicitly confirmed complete canonical Mission is a **new principal instruction**, separately recorded with origin EXPLICIT_PRINCIPAL_PLAN_AUTHORIZATION and scope NEW_EXPLICIT_PLAN_INSTRUCTION_NOT_SOURCE_UNIQUENESS. Original source authority remains UNKNOWN. Success in this prototype only releases original B through an explicitly enabled offline test boundary; runtime_authorized and production_authority_established are false.

Flow: legal immutable candidate -> host-owned one-shot request -> complete canonical presentation -> explicit principal response -> independent bound verification -> original B or no Mission. Human confirmation never consults a model/source authorizer. A prior gated result with no Mission must not be promoted: retain the original legal B proposal separately and begin a fresh request for confirmation.

Presentation includes raw source, full canonical Mission (mission_id, schema, every ordered step, IDs, parameters and dependencies), implicit Stand defaults, interpretation code digest, principal/session/request identity, revision and TEST_ONLY warning. Exact presentation bytes, full plan, source and context are bound. No abbreviated plan, implicit yes, default acceptance or model-supplied identity is an authority channel.

CONFIRM authorizes only the shown plan and request. REFUSE denies; MODIFY or CLARIFY withholds pending a new proposal and presentation. They revoke an unconsumed prior confirmation, including after request claim and before consent consumption. A replacement presentation supersedes the old revision. Any plan/source/context/semantics change invalidates approval; one-shot consumption, expiry, revoked session, replay, copied objects, mutated sealed bodies, forged JSON and cross-service/request use reject without fallback.

## Identity and threat boundary

create_test_session is a simulated fixture login; names are not authenticated humans. The prototype uses host-owned in-memory registered capabilities plus sealed body snapshots and monotonic expiry (maximum 300 seconds). Restart rejects old capabilities; it is not a distributed durable consent ledger. It does not prove actual display delivery, comprehension, external credential ownership or approval by a real person. Arbitrary code execution inside the trusted host is outside this capability threat model.

Production remains disabled. A future production adapter must independently authenticate the principal, verify their grant authority for the complete plan and execution scope, provide trusted full-plan presentation and affirmative consent, bind identity/source/plan/request/revision/semantics/expiry, and enforce durable replay prevention and cancellation ordering. These are unmet requirements, not an implemented production path. Mission data remains mutable after return; a future execution handoff must be immutable or revalidate the consent binding immediately before execution. No Runtime integration is supplied here.

## Compatibility

Existing default apply_gate call signatures/status enums remain compatible. Both public imports reference the same function. Bounded positive release still returns original B; model-only release remains rejected. Explicit principal kwargs select a separate path: invalid/missing confirmation never falls back to bounded derivation. Existing status semantics remain: malformed source/output, semantic ambiguity, backend failure, unresolved authority and explicit denial stay distinct.

One intentional narrowing: legacy principal fixture MAC receipts are rejected at the public boundary with PRINCIPAL_CONFIRMATION_CHANNEL_REQUIRED, because they lack principal identity, full displayed-plan binding and expiry. Frozen low-level authority_mechanism_001 fixture evaluation remains unchanged; legacy fixtures do not establish human authentication.

## Verification and retained negatives

Full related offline regression: 923 tests, 913 passed, 10 inherited failures; 66 new human-boundary tests passed; no new failure identities. verification.json and regression_final.xml retain exact outcomes and selection. verify_offline.py reproduces the same suite under network/physics guards and checks historical hashes. demo_offline.py prints a complete test presentation, confirmation, public-gate result and audit trace; demo_receipt.json retains one execution. No real human confirmation is claimed.

Inherited failures are classified in inherited_failures.json: one obsolete model-only release expectation; two historical acquisition/code-anchor checks; five historical whole-gate replay expectations; two Windows provenance/byte checks. Old expected values, acquisition artifacts and gold outcomes were not edited. These failures are retained rather than made green. The initial harness collection failure (missing repository import path, plus Windows text decoding) is retained in collection_attempt.xml; only the new offline runner setup was corrected.

12,090 preexisting experiments/prompts/configs/prior semantics-report files are byte-identical against history_before.json. Historical ood-m-031 unauthorized_release remains true. Provider/model calls=0, Runtime/physics calls=0, fresh held-out=0; guard attempts=0. No credential lookup or real authentication was performed.

Remaining blockers: credible production principal identity, trusted consent presentation, durable consent/replay infrastructure, and separately authorized execution integration. Stopping reason: contract, offline prototype, boundary regression and historical integrity are sufficient for this task; production authority and D011 are deliberately not unlocked.
