# Public release status semantics repair

Verdict: **PASS_WITH_INHERITED_REGRESSION_FAILURES**. This is an offline
boundary/compatibility repair, not a model experiment or a scientific release
qualification. D011 and Language Runtime remain **BLOCKED**.

The previous public `apply_gate()` mapped every non-AMBIGUOUS withheld result
to `MALFORMED / LLM_OUTPUT_INVALID`. Independent authority missing, invalid
receipts/contexts and provider failures consequently looked like malformed
model output. Classification now occurs after the unchanged release decision.

| Actual outcome | Existing CompilerStatus | Error code | `release_outcome` |
| --- | --- | --- | --- |
| Structural source failure | MALFORMED | LANGUAGE_PARSE_ERROR | SOURCE_MALFORMED |
| Invalid candidate/model certificate | MALFORMED | LLM_OUTPUT_INVALID | MODEL_OUTPUT_MALFORMED |
| Semantic ambiguity | AMBIGUOUS | AMBIGUOUS_COMMAND | SEMANTIC_AMBIGUITY |
| Backend failure | MALFORMED (legacy coarse bucket) | LLM_API_ERROR / LLM_TIMEOUT / LLM_CONFIGURATION_ERROR | BACKEND_FAILURE |
| Independent authority unresolved | AMBIGUOUS (uncertainty bucket) | **AUTHORITY_UNRESOLVED** | AUTHORITY_UNRESOLVED |
| Host authority release refused | UNSUPPORTED (release-policy refusal) | **AUTHORITY_DENIED** | AUTHORITY_DENIED |
| Independently authorized release | SUCCESS | None | AUTHORIZED_RELEASE |

`AUTHORITY_UNESTABLISHED_CLARIFICATION_REQUIRED` now returns
`AMBIGUOUS / AUTHORITY_UNRESOLVED`, `clarification_required=True`, and no
Mission. It is not a claim that the source was proven semantically ambiguous.
`AUTHORITY_DENIED` denotes an explicit host release refusal, including untrusted
or mismatched receipts/context, not a newly implemented human-principal denial
channel. The precise existing decision/reason remains in diagnostics.
Baseline unsupported-language rejection retains its original status/code and
is separately classified `SOURCE_UNSUPPORTED`.

Existing baseline failures retain status, error/message and no executable
Mission. Re-gating an unresolved/denied result preserves its distinct error,
outcome and clarification flag without invoking an authorizer. A successful
release still returns the **original B Mission object**, not a rebuilt plan.

## Compatibility and scope

Only two production files change: `language/errors.py` adds two error enum
members, and `source_authority/authorization.py` classifies final public results.
The result dataclass, signatures, four CompilerStatus tokens, permission checks,
source/complete-plan/context bindings and receipt consumption remain unchanged.

An error-only extension is necessary to avoid describing missing authority as
`AMBIGUOUS_COMMAND` or receipt refusal as unsupported language. Extending
CompilerStatus would change the dynamically derived frozen model status
allowlist, so it is deliberately avoided. Frozen model-emittable error codes
are an explicit allowlist: both new authority codes remain rejected as model
output. Prompt/config/Guard files are byte-identical to baseline.

The error enum vocabulary expands additively, including dataset/corpus
validators that enumerate that enum. Clients exhaustively interpreting error
codes should recognize the two new values; clients using `success`/Mission
presence remain fail-closed. The intentionally corrected public status/code
values and added diagnostic field may change exact result-dictionary comparisons.
Historical replay must continue using its original acquisition code epoch,
not rewrite saved results to match this boundary.

The existing release test's receipt writer now uses pytest temporary storage
instead of overwriting frozen `authority_release_001/fixture_results.json`.
The new tests exercise both public import paths; they remain the same function.

## Full related offline regression

Selection includes complete source-authority, bounded, certificate-v2,
independent mechanism/release suites; related pilot, analysis, preservation and
packaging suites; compiler/schema/scoring, corpus, canonicalization, Guard,
Mission IR/validation and Session4 historical evidence checks. Transport-server
and Runtime/simulation test suites are outside this boundary repair. No subset
of these selected files or individual failing tests was silently deselected.

| Run | Total | Pass | Fail |
| --- | ---: | ---: | ---: |
| Isolated unmodified baseline `6e76997` | 808 | 798 | 10 |
| Initial repaired boundary | 853 | 843 | 10 |
| Final repaired boundary, including re-gating checks | 857 | 847 | 10 |

All ten failing test identities match the isolated original baseline exactly;
there are **zero newly failing tests**. The complete release/mechanism suites
have **109 passing tests**, including all **49 new status-semantic tests**.
The broad regression is **not all green**. Its inherited failures cover the
old model-only release expectation, historical code/binding/replay epochs and
Windows LF/CRLF provenance assertions. They are listed without suppression in
`verification.json`, `baseline_diagnosis.json` and the retained JUnit receipts.
No historical fixture, threshold or package anchor was patched to obtain PASS.

Both final/current and baseline regression execution block socket connections,
provider HTTP requests and `G1Simulation.step`; blocked-attempt counts are zero.
Provider/model completions used in integration tests are in-memory fixtures or
replays only. **Actual provider calls=0, Runtime calls=0, fresh held-out=0.**

## Safety and historical integrity

All requested public invariants remain covered: model proposal alone cannot
release; independent source/complete canonical plan/request-context binding
holds; explicit invalid receipt never falls back; stale/replayed/forged context
refuses; concurrent context reuse yields at most one release; bounded positive
returns the unchanged B Mission. Backend/configuration/timeout failures and
malformed certificates remain distinct from clarification.

**12,082** pre-existing experiment/prompt/config/compiler files match the
before-change byte pins. Historical DG4 `ood-m-031` still records
`dg.score.unauthorized_release=True`. Its current replay is withheld by the
public independent gate; this does not erase or reclassify the historic unsafe
release. Previous serial stopping evidence is unchanged.

Changes and regression receipts are confined to the two production files,
release test files and this new report directory. No provider configuration,
Runtime, model acquisition, held-out campaign or scientific evaluator changes
are made. Relevant evidence is in `verification.json`,
`execution_receipt_final.json`, `regression_final.xml` and
`baseline_regression.xml`; `history_before.json` binds preservation inputs.

Stopping reason: the public semantic pollution is repaired, all current release
invariants and new result contracts pass, and full related regression introduces
no failures beyond the independently reproduced baseline. The inherited failures
remain explicit limitations; no broader cleanup, model experiment or Runtime
work follows this change.
