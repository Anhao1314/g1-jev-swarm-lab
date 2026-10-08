# D011 candidate — Source authorization before executable Mission release

Date: 2026-10-07 (Asia/Shanghai). Status: **CANDIDATE / NOT ADOPTED / NOT IMPLEMENTED**.

Trusted evidence anchor: `5fabf3c050df4420f414a564dcdf5ce255a5b0fa`.
Original D010 in `docs/research-decisions.md` is unchanged. The Phase 2.3
protocol, selected compiler, data, gold labels, thresholds and all Session 4
outcomes remain frozen. This document proposes future experiments only.

## D010 revisit finding

D010 explicitly requires revisit for any Guard false positive or fail-open
acceptance. Both are independently satisfied: Primary `ood-m-012` yields an
executable Mission for a source with unresolved action multiplicity, and
Primary valid `ood-v-029/069` are rejected by the Guard. Final also has 63
Guard false rejections against its frozen SUCCESS gold. The Final 79.41%
exact rate supplies an additional reason to re-examine D010's new-corpus
condition, with a strong template/Guard confound. The old 0.98 gate is not
imported into Phase 2.3, whose frozen interpretation remains characterization.

D010 was a supported selection among A/B/C/D on its historical benchmark.
These findings do not erase historical scores or establish that C/D would
pass this OOD set. They invalidate treating B as an already validated,
distribution-general fail-closed front end for Final Runtime.

## Candidate decision

Retain B as the immutable research comparator. Propose a rejection-capable
source-to-IR authorization check before any executable Mission is released.
Keep surface Guard and static IR validation as separate necessary checks.

Proposed release condition (not current code):

`release(M) = Guard_pass(source) AND IR_legal(M) AND source_authorization(source, M) == AUTHORIZED_UNIQUE`

The authority check must inspect the entire source, including amendments,
quoted fragments, temporal scope, reference, repetition and explicit unresolved
relations. It must be able to return AMBIGUOUS or UNKNOWN with no executable
Mission. Finding each action word/number in the source is insufficient:
`ood-m-012` contains both walk phrases but explicitly withholds their execution
relationship. An unsupported or missing authorization result is not SUCCESS.
Clarification, if studied later, belongs to a separately authorized interaction
protocol, not semantic retry or automatic rewriting of this source.

This is the minimum missing *functional contract*, not a proven smallest
implementation or a claim that one extra LLM call guarantees safety. A verifier
sharing the compiler's omissions can falsely agree. Its uncertainty and
complete-source coverage must therefore be independently tested; self-reported
confidence, back-translation or syntactic round-trip equality are not evidence
of unique source authorization.

## Alternatives and what each can establish

| Candidate | Contribution | What it leaves unresolved | Research priority |
| --- | --- | --- | --- |
| Broaden Structural Guard | Cheap explicit ambiguity/scope cues; can avoid model calls | Surface patterns cannot establish general semantic uniqueness; blocking every 最后/重复/reference risks valid-order FPs | Comparator/prefilter, not sufficient sole mechanism |
| Semantic ambiguity detector | Explicitly abstains on non-unique source interpretation | A false-negative detector still releases an unauthorized candidate; its label/confidence is not a source-to-IR proof | Useful ablation |
| Source-to-IR consistency verifier | Tests candidate count/order/parameters against all source constraints | Token-span overlap alone misses the unresolved metadata in m012; verifier dependence/cost remain empirical | Preferred minimal mechanism to investigate |
| Explicit uncertainty/authority layer | Prevents UNKNOWN/AMBIGUOUS from becoming executable SUCCESS | Requires a trustworthy source-consistency signal; attaching a confidence field alone adds no protection | Required release policy coupled to verifier |
| Constrained canonicalization / C or D bridge | Restricts executable syntax and can provide deterministic canonical IR construction | A model can select an unauthorized yet grammatical canonical sequence; Lark can validate that wrong choice | Comparator; not established replacement |
| Deterministic restricted semantic grammar | Can make authorization checkable inside a bounded language and reject out-of-scope input | May substantially reduce open-language coverage and require clarification | Baseline for a bounded safety contract |
| Human confirmation of unresolved relations | Supplies actual missing source authority | Additional interaction/latency; cannot silently assume confirmation or replay the original source | Separate future interaction study |

The structural-guarantee scope of guided generation is described by
[Willard and Louf (2023)](https://arxiv.org/abs/2307.09702v4). Robot uncertainty
and selective help are studied by
[KnowNo (2023)](https://arxiv.org/abs/2307.01928v2) and
[IntroPlan (2025 revision)](https://arxiv.org/abs/2402.06529v4).
These primary sources motivate candidate designs; none verifies this project's
Chinese source-to-IR authority check or transfers a safety guarantee to its OOD
distribution. The proposed minimal contract is an inference from local evidence.

## Two independent research branches — proposed, not created

**A. Safety architecture hardening experiment.** Use the existing six accepted
OOD sources, two unusable responses and valid-order hard negatives only as
already-seen development/regression diagnostics. Do not present them as a new
blind success rate or rerun Session 4. Pre-register baseline B versus a semantic
ambiguity gate and the source-aware release gate; optional surface-Guard or
canonicalization controls can test whether extra complexity earns useful safety.
Independently author and freeze a *new* confidence-separated held-out distribution
without exposing current detector rules or observed failures to the author.
Include ambiguous and uniquely resolved commands across multiplicity, edit scope,
reference, temporal order and prefix/completion relations. Use separate development,
calibration and held-out evidence when calibration is needed. Keep Primary and
Sensitivity separate and preserve all attempts and first semantic responses.

Primary endpoints should include unauthorized executable acceptance, valid exact
coverage, false rejection, ambiguity/unknown outcomes and source-constraint
violations. Report per-family transfer, verifier-added latency/tokens/provider
calls, unusable responses and failure dependence. Register any new thresholds
before collecting held-out outcomes; do not change old thresholds or tune on the
current OOD. The existing zero unauthorized-acceptance expectation is a suitable
proposed safety gate, not evidence that a new mechanism has passed it.

**B. Benchmark validity/repair experiment.** Keep B's implementation and scientific
provider configuration fixed; use a newly versioned corpus and campaign identity.
Preserve the original 306 texts/scores and exclude Pilot outcomes. Repair the
realization construction in that new experiment, specify the variant-selection
and overlap-resolution procedure, independently inspect semantic uniqueness and
balance realization families across horizon/condition. Freeze all new outputs
before testing; do not generate a prettier old curve. Measure Guard acceptance
separately from conditional compiler exactness. A pre-registered direct-LLM
ablation on the *new* corpus may identify understanding performance without
pretending to know the uncalled 63 Session 4 counterfactuals. Register exclusions,
paired canonical IR and byte serialization before observation.

The branches should remain independent: changing architecture and text templates
together would make any improvement unattributable. No Git research branch,
new dataset, detector, verifier, prompt or campaign was created in this audit.

## Runtime gate

**BLOCKED.** The decisive blocker is Primary unauthorized acceptance. The Final
curve's construct confound and the five frozen hash pins that do not match fresh
Git LF blobs are additional validity/publication issues. Packaging repair, if
authorized later, must preserve the old tag/data/result and use a separately
versioned byte-exact publication procedure; it must not silently normalize old
evidence or change its hashes.

Runtime is not a test of language-source uniqueness: a perfectly executed wrong
Mission would not resolve the safety failure. Reopening the language Final Runtime
gate requires an adopted decision, independently evaluated source-authority safety,
interpretable frozen benchmark evidence, complete declared response accounting and
byte-reproducible freeze verification. Oracle Runtime remains unstarted in this
session and is not proposed as a workaround for the blocked language gate.
