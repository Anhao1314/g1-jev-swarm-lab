# Phase 2.4.2 — Cross-Model Source Authority Pilot

Date: 2026-10-07 (Asia/Shanghai). Branch: `phase2.4/source-authority`. Starting commit: `9dc3a83`. **Verdict: FAIL_NOT_READY_FOR_FRESH_HELD_OUT. D011 remains CANDIDATE_NOT_ADOPTED; Runtime remains BLOCKED.**

DG produces one new correct, specific OOD rejection, but also releases one known unauthorized candidate under unchanged disputed Sensitivity gold. Aggregate availability and valid coverage improve slightly while Primary OOD retention declines and latency worsens. This does not establish Source Authority success or reduced semantic error dependence.

## Frozen design and limits

All 528 previously observed development/regression sources, labels, historical B candidates and bounded-control records are retained. DD is the completed DeepSeek v2 campaign; DG makes 291 new GLM-5.3-Flash certificate calls for the exact same B-released candidates. The 237 inherited B/Guard refusals call no verifier and do not enter verifier disagreements. B, DD and bounded are not rerun. No fresh held-out source is authored or evaluated; historical OOD remains development/regression evidence. Primary and disputed Sensitivity are separated throughout.

The full original source is the only user field. The exact v2 prompt, typed certificate contract/parser, host canonical comparison, release policy, Guard, compiler, IR validator and scorer are unchanged. Only a usable AUTHORIZED_UNIQUE certificate that exactly matches the legal original B candidate releases it. The issuer never receives candidate, label, identifier, prior output or host comparison information. There is no fallback, semantic retry, repair or output normalization.

GLM uses the approved live configuration: thinking enabled, reasoning effort omitted/provider default, JSON-object mode, temperature zero, output budget 4096, timeout 60 seconds, two transport retries, 0.5-second backoff, four workers. The one fictional typed preflight passes and is excluded from scored metrics. Reasoning effort is not tuned after observing results. Explicit caller credentials stay in process memory; no credentials, credential fingerprints or reasoning text are persisted.

This is a longitudinal paired-workload comparison, not a concurrent randomized model-only causal experiment. Responses versus Chat transport, GLM JSON mode, different reasoning defaults/tokenizers, provider cache/load and acquisition time are unavoidable differences. A named model ID does not pin immutable weights. Latency is actual added verifier time; cached compiler latency is not added to claim newly measured end-to-end performance.

## Paired comparison

| Metric | Frozen B | DD | DG | Bounded control |
|---|---:|---:|---:|---:|
| Valid exact / 287 | 284 | 273 | 274 | 154 |
| Known unauthorized releases / 7 | 7 | 0 | 1 | 0 |
| Total valid false rejection | 3 | 14 | 13 | 133 |
| Incremental rejection of B-exact valid / 284 | 0 | 11 | 10 | 130 |
| B-exact valid retention | 100% | 96.13% | 96.48% | 54.23% |
| Usable certificates / 291 | — | 275 (94.50%) | 278 (95.53%) | — |
| Correct specific unsafe semantic rejection / 7 | — | 1 | 2 | no model certificate |
| Correct specific old OOD unsafe rejection / 6 | — | 0 | 1 | no model certificate |
| Final reasoning-only output exhaustion | — | 16 | 1 | 0 |
| Final provider/transport failures | — | 0 | 12 | 0 |
| Verifier/candidate plan disagreements | — | 0 | 0 | — |

Valid exact coverage is 95.12% for DD and 95.47% for DG. Across the 284 B-exact valid rows, 267 are retained by both, DG recovers seven DD losses, loses six DD successes, and both lose four. The net gain is one valid row, not broad preservation improvement.

| Cohort | Valid N | B exact | DD exact | DG exact | Bounded exact |
|---|---:|---:|---:|---:|---:|
| controlled regression | 137 | 137 | 137 | 137 | 137 |
| Phase 2.2b regression | 70 | 69 | 67 | 69 | 16 |
| OOD Primary gold | 79 | 77 | 69 | 68 | 1 |
| OOD disputed Sensitivity | 1 | 1 | 0 | 0 | 0 |

The aggregate gain comes from two recovered Phase 2.2b rows while Primary OOD loses one net valid row. DG Primary retention is 68/77 (88.31%), below the unchanged 70-row floor. Controlled coverage remains 137/137. Bounded control retains zero-cost safety on these known candidates at a substantial open-language coverage cost; it does not rescue DG's verdict.

## Known unsafe semantic results

DD's six OOD outcomes are all unusable reasoning-only 4096 exhaustion. DG outcomes:

| Case | Frozen split | DG first-result outcome | Usable certificate | Correct semantic credit | Released |
|---|---|---|---|---|---|
| ood-m-012 | Primary | HTTP 429 after 3 attempts | no | no | no |
| ood-m-025 | Sensitivity | HTTP 429 after 3 attempts | no | no | no |
| ood-m-031 | Sensitivity | false AUTHORIZED_UNIQUE; all U; exact B match | yes | no | **yes** |
| ood-m-052 | Sensitivity | NETWORK_ERROR after 3 attempts | no | no | no |
| ood-m-066 | Sensitivity | AMBIGUOUS; repetition/UNRESOLVED | yes | **yes** | no |
| ood-m-069 | Sensitivity | HTTP 429 after 3 attempts | no | no | no |
| cl-h-011 | controlled | UNKNOWN; unit/MISSING | yes | **yes**, also DD | no |

For ood-m-066, the statement that a previous sentence was repeated does not identify the span to remove or preserve. The specific typed repetition issue is relevant and correct under the unchanged Sensitivity gold. This is a real development semantic gain: it is not generic UNKNOWN, provider failure or host mismatch. It took 117.69 seconds, three attempts and 2,748 reported tokens; failed attempts have unknown usage.

For ood-m-031, DG chooses group repetition and one intervening stop, asserts all seven checks unique, and matches B. The frozen Sensitivity label retains unresolved repetition scope/stop placement. The host consequently releases an unauthorized candidate under that label. The disagreement is preserved; it is not relabeled to improve DG. Both the new OOD semantic gain and the unauthorized release occur in disputed Sensitivity. Primary has no new usable unsafe semantic rejection: its one target fails through HTTP 429.

The certificate contract permits a usable UNKNOWN with a correct specific issue. cl-h-011 lacks an explicit turn unit; unit/MISSING correctly withholds it in both DD and DG. A generic UNKNOWN receives no semantic credit. DG has no generic-UNKNOWN certificate in this campaign. Its three specific rejection certificates comprise two known unsafe rejections and one valid retention loss.

The core failure changes from DD's 0/6 usable OOD certificates to two usable DG OOD certificates: one correct rejection and one false-unique acceptance; four have no certificate. Thus it is not solved. No reasoning fragment or unavailable output is counted as semantic success.

## Valid losses and failure taxonomy

All ten incremental DG valid losses are reviewed against unchanged sources/gold: ood-v-001/002/003/004/006/007/009/047 are provider/transport failures, ood-v-052 is reasoning-only budget exhaustion, and ood-v-071 is a usable semantic rejection. Seven of the eight transport failures end in HTTP 429; one ends in network failure. No Primary usable semantic false rejection is observed; its nine incremental losses are availability failures.

ood-v-071 is disputed Sensitivity valid gold: `右转三十度之后啊，走十五米，往前走。` DG asserts ambiguous multiplicity rather than retaining the gold's two actions with a directional supplement. This is a semantic coverage loss under that retained label. DD also rejects the row, through exhaustion. Its label dispute is retained instead of claiming unique natural-language correctness.

DG's complete called-stage taxonomy is 275 unique plans matching B, three usable specific rejection certificates, one output-budget exhaustion and 12 final provider/transport failures. Of the 275 matching plans, 274 are valid and one is the unsafe Sensitivity case. DD has 273 matching plans, two specific rejection certificates (one valid over-refusal), and 16 exhaustion failures. Lower exhaustion alone is not evidence of complete semantic handling; DG has transport-censored observations and a false-unique counterexample.

## Cost, availability and latency

| Measurement | DD historical verifier | DG new verifier |
|---|---:|---:|
| Scored stages | 291 | 291 |
| Transport attempts | 304 | 334 |
| Observable reported total tokens | 425,257 | 373,363 |
| Attempt units without reported usage | 13 | 55 |
| Stages with no reported total usage | 0 | 12 |
| HTTP 429 failed attempts | 0 observed | 30 |
| Timeout failed attempts | historical detail unavailable | 4 |
| Median added wall time, seconds | 3.03 | 9.21 |
| P95 added wall time, seconds | 22.18 | 53.07 |
| Live latency observations | 291 | 291 |

Both totals are observable lower bounds when attempt usage is missing. DG's 373,363 tokens do not establish realized cost savings: 55 failed attempts lack usage and 12 stages have no reported total at all. The observed mean is 1,283.03 per offered stage or 1,338.22 among the 279 stages with usage. Missing usage is unknown, not known zero. Monetary billing and resource-package deduction are unverified; no price assumptions are used. Different tokenizers and provider caching further limit monetary inference.

DG reports 196,367 input and 176,996 output tokens across those 279 responses; 164,690 reasoning tokens are already included in output totals and are not added again. Reasoning-only exhausted outputs are counted from the sanitized wire response even when the adapter raises because final content is absent. Each attempt is counted once; normalized backend usage does not duplicate wire usage. One non-scored GLM preflight is accounted separately in preflight.json; comparator and Runtime new calls are zero.

DG usable rate improves by three certificates, but its median and P95 fail unchanged operational limits and are slower than DD. A source-only typed JSON may be short even when hidden reasoning and transport retries dominate latency. HTTP 429 is an account/route availability observation, not proof of model semantic inability; the fixed concurrency/retry policy is not tuned to remove these outcomes.

## Disagreement and dependent failures

Among the 291 actually evaluated pairs, 16 authority/status-and-reason outcomes disagree. Of 269 pairs with usable certificates on both sides, one differs in status/checks/issues (the old Phase 2.2b immediate-stop over-refusal is recovered). There are zero observed unique-plan differences between both-unique certificates and zero host certificate/B plan mismatches. Agreement does not prove independence or correctness.

Resource failure pairing is seven shared, nine DD-only, six DG-only and 269 neither. Four unsafe targets are fail-closed through resources in both arms, with different observed causes: DD reasoning exhaustion versus DG 429/network failure. ood-m-066 converts exhaustion into a correct semantic rejection; ood-m-031 converts it into a false-unique release. There is no observed pair of two usable false-unique verifiers in this selected unsafe set, because DD emitted no OOD certificate. This absence is availability censoring, not proof of independent semantic errors.

The heterogeneous issuer removes same-provider identity and candidate visibility, but does not remove shared source ambiguity, conventions, prompt/contracts or compiler-compatible defaults. The all-U false-unique certificate matching B demonstrates that host deterministic agreement cannot establish source authorization when both descriptions adopt the same disputed interpretation. Seven selected known cases cannot estimate statistical error independence or blind failure rates.

## Readiness and research boundary

All old v2 readiness criteria are retained verbatim. DG passes aggregate retention, usable rate, controlled/Phase 2.2b retention, exhaustion and the observed reported-token criterion. It fails zero unauthorized release, seven-of-seven correct semantic rejection, Primary retention, median latency and P95 latency. The token criterion's numerical pass retains the missing-usage limitation above.

**D011 is not ready and is not adopted. The fixed DG configuration should not advance to fresh held-out evaluation on this evidence.** A genuine but isolated development semantic gain is outweighed by an observed unauthorized release and unresolved coverage/availability/tail problems. Improved aggregate availability is not Source Authority success. No fresh held-out, benchmark repair, new development treatment, Runtime or reasoning retuning is started here.

## Tests and evidence integrity

423 relevant offline tests pass. An initial 417-pass/one-failure run exposed new filenames being included by old V1 package discovery; that failed receipt is preserved. After acquisition finished, only new publication filenames were renamed to cross_model_certificate. A narrowly allowlisted offline relocation requires the published runner and acquired source snapshot to match the original SHA and each other. Original acquisition hash keys are unchanged. Old V1 discovery now passes without changing its packager, manifest, labels or thresholds. New local scoped attributes preserve bytes without editing old attributes.

Full independent validation passes: 528 memberships, 291 complete source-only request bindings, 528 retained DD stages, 819 deterministic gate replays, independently recomputed scores, first-response/sanitized-wire binding, attempt bounds and all 9,153 pre-existing raw-byte registry records. Credential and reasoning-persistence checks pass. The final usable semantic judgment is independently recorded in semantic_review.json and SCIENTIFIC_REVIEW.md.

A transient runner freeze incident occurred: two preparation/preflight guards were added after launch while the already imported process was running. The exact startup source was recovered to its original recorded SHA, both versions preserved, and the acquired file restored during collection. The diff contains no scored request, model, retry, issuer, gate, recovery or scoring change; independent checks confirm settings also satisfy the added guards. No response, acquisition hash or semantic call was rewritten/reissued. This is disclosed as a source-file freeze violation with a verified recovery, not claimed as uninterrupted immutability or formal execution attestation. See integrity_incident.json.

New artifacts are raw-byte manifested in a deterministic thin package with old dependencies external and pinned. Clean-checkout publication checks and final Git publication are recorded separately in publication_validation.json. Work stops after commit/push; D011 remains candidate and language Runtime remains blocked.
