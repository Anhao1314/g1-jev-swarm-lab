# Independent Authority Release Gate Integration

**Implementation verdict: the public Source Authority Mission-returning boundary is controlled by independent authority. D011 remains BLOCKED; this is not its acceptance evaluation.** No further mechanism design or acquisition is needed for this implementation step.

## Actual release boundary

Both `g1swarm.source_authority.apply_gate` and `g1swarm.source_authority.authorization.apply_gate` use the modified common boundary. There is no model-only legacy switch. Before returning unchanged B's Mission, that boundary requires an independent authority Decision with `allow=True`.

The existing Guard, static IR legality, execution-override refusal, detached candidate and mutation checks remain in place. The existing source-only v2 issuer runs once, with its unchanged prompt/model configuration and complete host proposal/B comparison. Its `AUTHORIZED_UNIQUE` result is retained under `proposal_authorization`, and is never sufficient for Mission release.

For v2 proposals, the final authority decision reuses the frozen `authority_mechanism_001.contract.evaluate_release`. The original source, full canonical plan and host request context must match a verified receipt. The shared default authority service has only existing bounded derivation enabled; it is not reconstructed per call. Receipt derivation reads source only. An explicit invalid receipt is never replaced by automatic bounded derivation.

The deterministic bounded-only control remains available: its unchanged full-source proof and common Guard/IR/candidate checks are followed by the same independent receipt verification. It has no model/provided uniqueness claim and makes zero provider calls. Generic/custom model authorizers cannot obtain Mission release by returning self-approved status or fabricated authority diagnostics.

The gate keeps original B's Mission object on success and returns `mission=None` on every refusal. It does not substitute the proposal or any alternative approved plan. It additionally checks that original B was not mutated across the proposal call.

## Request binding and replay

A host creates a one-shot context with `begin_release_request(source)`, before optionally deriving an explicit receipt. For the normal bounded path, `apply_gate` creates this context itself and derives authority from the original source. Model input remains exactly `{source}`; no context, candidate, receipt or trusted keys enter its request.

Context ownership is checked by registered object identity, original-source hash and atomic one-time claim. Copies of context fields are not capabilities. Reusing the context, including with a reconstructed AuthorityService, is refused before another proposal call. An old receipt used with a fresh context fails context binding. Across process restarts, no old contexts are registered; pending request recovery and persistent human-consent infrastructure are not implemented.

Once a valid context is claimed, that request is spent even if the proposal or authority fails. This is a conservative one-attempt lifecycle, not a semantic retry facility. Transport retries within the existing provider adapter are unchanged. Host configuration and keys remain trusted; arbitrary compromised host code is outside the guarantee.

For missing independent authority, the authority state is `UNKNOWN`, reason `AUTHORITY_UNESTABLISHED_CLARIFICATION_REQUIRED`, and `clarification_required=True`. The outer compiler result uses the existing withheld-result status with no Mission. This is unresolved authority, not a new MALFORMED dataset label or a correct specific semantic rejection.

## Saved necessary validation

All backend invocations in this step are in-memory fixtures or replays of previously acquired first responses. **Actual provider, fresh held-out, Runtime and new-model-treatment counts are zero.**

| Case through the actual boundary | Result |
|---|---|
| Historical legal DG4 `ood-m-031`, both public import paths | Usable all-U proposal and exact B match retained; no Mission; authority unresolved |
| Actual serial `031` | Original illegal `walk` parser failure retained; no semantic-correction credit |
| Unscored alias-only serial counterfactual | Legal false-unique proposal still receives no Mission without independent authority |
| Existing `controlled--cl-a-001`, host-default and explicit bounded receipt | Returns the same original B Mission |
| Missing receipt despite inherited release flags | Refuses; model/baseline diagnostics cannot supply authority |
| Forged MAC or signed source/complete-plan/context mismatch | Refuses; no fallback to a new receipt |
| Used context with reconstructed service; old receipt with fresh context; copied context object | Refuses; repeated context does not call the issuer |
| Concurrent use of one context | One Mission and one proposal invocation total |
| Generic model-only UNIQUE with fake authority diagnostics | Refuses |
| Guard failure, illegal/missing B, proposal/B disagreement | Refuses; precondition failures short-circuit where applicable |
| Same source, correct/wrong legal B | Identical candidate-blind requests; wrong B refused; both B records unchanged |
| Existing deterministic bounded-only control | Remains available with independent receipt |

The targeted integration file and existing bounded-control tests passed **59/59**, with no failures/skips. The saved JUnit file and `fixture_results.json` expose the actual Mission-returning outcomes. No full regression or population experiment was run.

An independent read-only review executed six necessary probes once and found no blocking bypass at this boundary. It also checked a test-only principal receipt: an allowed fixture retains `NEW_EXPLICIT_PLAN_INSTRUCTION_NOT_SOURCE_UNIQUENESS`, with original-source uniqueness false. This is not actual human approval or retrospective semantic correction.

## History and limitations

Historical `031` remains an actual unsafe release under its unchanged disputed/sensitivity label. DG-serial stays PARTIAL_STOPPED and D011 BLOCKED. Historical provider/network censoring, raw responses, labels, thresholds, scores and reports are untouched.

Only the pre-existing public boundary source file is intentionally modified. Its exact prior raw bytes are saved in `historical_boundary_snapshot.py`, with their original hash and baseline commit. The other 44 inputs bound by the previous mechanism study are unchanged, including v2, prompt, Guard, canonicalizer, bounded control, compiler and old evidence. The integrity receipt checks both facts.

Old research analyzers that replay the old policy through the current `apply_gate` will now see the new policy; their original source bindings deliberately do not describe this code epoch. Reproduction of historical claims must use their preserved Git/source/package context. There is no historical-policy bypass exposed on the current release API, and no old result is recomputed or overwritten here.

The guarantee is scoped to the public **Source Authority release boundary**. Frozen B/compiler outputs remain research candidates; this step does not change every Mission-producing component or connect to Runtime. Automatic authority still inherits the bounded language and normalization assumptions. Open-language inputs without trusted authority remain unresolved, so this work supplies no new open-language semantic gain or retention estimate.

Real principal identity, full-plan consent, key storage and persistent pending-request recovery are unbuilt. Their fixtures verify scope/bindings only. D011 readiness must be decided by a subsequent independently authorized gate/evaluation; this implementation does not lift it.

**Stopped:** the real boundary is connected, the fixed counterexample and necessary positive/negative checks pass, history is preserved, and no blocking implementation item remains. Further campaigns, Runtime work, model tuning or mechanism design are not started.
