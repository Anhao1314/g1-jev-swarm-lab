# Phase 2.3 Session 4 Audit — Final compiler benchmark validity

Audit verdict: **the frozen scores remain valid measurements of the complete guarded compiler on the frozen template distribution; they cannot identify LLM long-horizon degradation.** All 63 observed Final losses occur before a provider call. The horizon curve measures generator/Guard compatibility and selected conditional compiler correctness. No frozen result, source text, label, threshold, or protocol has been changed or re-scored.

## Evidence binding and method

The trusted Session 4 evidence commit is `5fabf3c050df4420f414a564dcdf5ce255a5b0fa`. The campaign execution code commit recorded in its evidence is `0205c4ce37c617d00610eb454082da54279a3725`; this is distinct from the commit that subsequently published the completed evidence. Freeze tag `phase2.3-final-protocol-freeze` resolves to `3b619e7f189cf632f03f0b68070671fb534aeb7d`.

| Binding | SHA-256 |
| --- | --- |
| Protocol | `32f035daef911b4a3d6c2dfef32f1d1387fe4e8bf7694894b1397262b60d388a` |
| Final language dataset | `1188cb31c40b7e968d11b9a31f3363eb96c30c09c743f0a8b90e6f6b1b592192` |
| Final canonical dataset | `ef856b9401b2be4eb8ca1c75d5f2d1c238246a3254c26dddd01943bf422ac7ac` |
| OOD dataset, separate from this curve | `6a04d5f2e40841fe18c89d72e1a4424f01779be1caa219a9f17e6ca4fb4f8f3e` |
| Freeze manifest | `4af7d7f4de2b2bfd03b67eeb8be3ebd668263a63e4b28083dda0629a3415a777` |
| Compiler prompt | `913346508791ab86f80247f2b6315d6e96f9b5066090299ada2196aeb0e3c110` |

Compiler provenance is `guarded_direct_llm_v1`, Structural Guard `2.2b.2`, model `deepseek-flash`, temperature `0.0`, maximum output `4096`, timeout `60 s`, and `max_2_network_retries_0.5s_backoff_429_500_502_503_504`. Source: `protocol.yaml:303–311` and `session4/compiler_results.json:3–37`.

The offline checks join all 306 frozen language rows to their existing result rows, count stored classifications, inspect literal source forms, and check provenance/hashes. Pure deterministic template reconstruction from existing canonical steps and frozen per-sample variants reproduces all 306 exact source texts. The checks do not invoke the Guard, compiler, provider, runtime, grammar self-check, or scorer. [benchmark_validity_checks.json](benchmark_validity_checks.json) records all 63 rejected sample IDs, source/result line locations, exact source text, variant, recorded Guard reason and provider absence. It also records 18 source file hashes and comparison against the trusted Git snapshot.

## The deterministic failure mechanisms

### L2: connectors are inserted twice

`src/g1swarm/longhorizon/corpus.py:274–276` defines middle-clause prefixes `再`, `接着`, `之后`. `_join_l2` prefixes each intermediate clause at `:350`, then joins those already prefixed clauses with `，然后`, `，接着`, or `，之后` at `:352–353`.

For variant 0 this produces `然后再`, which the Guard explicitly allows at `src/g1swarm/simplex/structural_guard.py:53–54`. Variant 1 produces `接着接着`; variant 2 produces `之后之后`. For every affected mission of horizon H >= 3, there are H − 2 literal repeated connector pairs. The Guard checks repeated equal connector tokens before other rules at `:145–153`; its recorded `REPEATED_CONNECTOR` decisions match all 58 affected frozen L2 rows.

Concrete chains:

| Frozen source | Source line | Recorded result | Result sample ID line |
| --- | ---: | --- | ---: |
| `lh-h3-03-s2-w8-x__L2`: `首先保持站立2秒，接着接着向前走8米，最终停下。` | `final/language_realizations_final.yaml:320` | `MALFORMED`, `REPEATED_CONNECTOR`, `GUARD_REJECT`, no provider, no Mission | `session4/compiler_results.json:12084` |
| `lh-h3-04-s5-w10-x__L2`: `一开始原地站立5秒，之后之后往前走10米，最后停下来。` | `final/language_realizations_final.yaml:338` | Same recorded outcome | `session4/compiler_results.json:12826` |

H1 L2 takes the single-step path at `corpus.py:345–346`, so it has no intermediate clause and no duplicated connector. Thus the L2 discontinuity starts at the first available multi-step horizon, H3; it is a change in template construction rather than an observed model limit. H2 is absent from the frozen design and no H2 claim is made.

Earlier structural-malformed corpora treat repeated connectors as defects, while these Final sources retain SUCCESS gold derived from their canonical missions. This is a benchmark/source-contract tension. It does not justify relabeling the Final examples or crediting the Guard with a scientific success against their existing labels. The official 58 false rejections remain unchanged.

### L3: the stop-clause prefix becomes a leading connector at H1

All three L3 stop clause variants begin with `最后` at `corpus.py:330–334`. For multi-step missions, it serves as a final-clause marker. At H1, `_join_l3` returns that clause without a preceding action or wrapper at `:358–359`. The leading-connector expression includes `最后` at `structural_guard.py:68`; the recorded rejection is `LEADING_CONNECTOR` at `:197–201`.

The five frozen H1 stop missions are exactly `lh-h1-03-x__L3`, `lh-h1-07-x__L3`, `lh-h1-11-x__L3`, `lh-h1-15-x__L3`, and `lh-h1-19-x__L3`. Example `最后立即停止。` is at `final/language_realizations_final.yaml:20`; its stored `MALFORMED` / `GUARD_REJECT` / no-provider / null-Mission evidence is in the result record whose sample ID occurs at `compiler_results.json:623`. This accounts for every L3 loss. No other failure family occurs in the 306 Final result rows.

## Horizon and template confounding

Each horizon has 17 canonical missions and three language realizations per mission. The actual frozen L2 variant mixture is not balanced by horizon:

| Horizon | L2 variants 0 / 1 / 2 | Repeated pairs in each affected L2 input | L1 exact | L2 exact | L3 exact | Overall exact | Pre-provider losses |
| --- | --- | ---: | --- | --- | --- | --- | ---: |
| H1 | 5 / 5 / 7 | 0 | 17/17 | 17/17 | 12/17 | 46/51 | 5 |
| H3 | 7 / 4 / 6 | 1 | 17/17 | 7/17 | 17/17 | 41/51 | 10 |
| H5 | 3 / 5 / 9 | 3 | 17/17 | 3/17 | 17/17 | 37/51 | 14 |
| H8 | 6 / 8 / 3 | 6 | 17/17 | 6/17 | 17/17 | 40/51 | 11 |
| H12 | 5 / 9 / 3 | 10 | 17/17 | 5/17 | 17/17 | 39/51 | 12 |
| H16 | 6 / 6 / 5 | 14 | 17/17 | 6/17 | 17/17 | 40/51 | 11 |

The L2 curve for H3–H16 equals the count of variant 0 inputs, exactly. Non-monotonic aggregate variation is therefore explained by variant composition. The H1 effect instead reflects stop-skill composition: five stop missions versus four each of walk, turn and stand. The primary horizon variable is IR step count (`corpus.py:29–36`), not text length, token count, clause count or independent task difficulty.

Other scope effects matter: language variants jointly change connector vocabulary, numerical forms, colloquial wording and wrappers; canonical generation uses four skills with restricted grounded parameters and sequential tasks terminating in stop. Three language realizations of a mission are paired, not three independent task draws. There are 306 rows but 300 unique Final texts; repeated short commands further limit any interpretation as 306 independent source-authority trials. None of these observations alters the frozen denominator.

For this observed cohort, complete-system exactness equals the fraction of rows reaching the provider multiplied by stored conditional exactness: 243/306 × 243/243 = 243/306. The second term is selected by the Guard. It supplies no model outcome for the rejected 63, and it cannot justify a counterfactual claim that removing the Guard would make all 306 exact. Provider-only token and latency trends likewise concern the accepted subset; unconditional wall-time comparisons also mix immediate Guard rejections with real provider calls.

Supported: on the observed Guard-passing template cohort through H16, the frozen records contain no wrong order, parameter, dependency or hallucinated-skill failure. Unsupported: an isolated LLM degradation curve, an H16 generalization ceiling, broad language-condition robustness, source-authority safety, or any physical/runtime conclusion.

## Why Pilot 54/54 did not exercise these failures

The archived Pilot contains 54 samples and 54 stored exact outcomes. Its IDs and exact texts are disjoint from Final; these remain separate evidence populations. The Pilot H1 selection includes walk, turn and stand, with no stop. See `ood/evidence/pilot_language_realizations.yaml:8–52` and `pilot_selection.json:4–36`. Its L2 multi-step inputs use `先` / `然后再` / `最后`, e.g. `pilot_language_realizations.yaml:58–62` and `:103–107`; none contains the duplicated connectors.

Git history confirms that pre-freeze commit `c491d3a807130481d7deb6de790c4f2fd00b1725` expanded L1/L2 synonym and connector banks and added variant-dependent L2 joining. The prior `_join_l2` always used the variant 0 connector construction. The generator's stated version remained `2.3.0`. This was a pre-freeze benchmark change, not Session 4 implementation drift. It means the Pilot did not validate the newly expanded Final L2 surface forms.

A second reproducibility qualification is recorded without changing the data: ten frozen per-sample variant values differ from the default ID-hash selection in `corpus.py:385`. The historical `protocol_freeze_report.md` at commit `c491d3a`, lines 88–91, documents deterministic variant selection before freeze for Pilot/Final text-overlap control. This does not establish the cause of every override: only one of the ten default texts overlaps Pilot, and per-override reasons and the complete selection procedure are not recoverable. All 306 frozen texts exactly match the pure template output when their frozen variant fields are supplied, so the text bodies require no undocumented semantic rewriting. The frozen variant fields are the actual campaign inputs; the generic ID-hash realizer alone lacks that full variant-selection recipe. One L3 override also means all three conditions of a mission do not invariably share the same numeric variant. The checks file lists the ten overrides explicitly.

The frozen validation covered canonical properties and membership (`corpus.py:499–552`) and L1 grammar compatibility (`tests/test_long_horizon_freeze.py:76–78`). It did not establish independent semantic validity or Guard compatibility of all L2/L3 variants. This is a missing benchmark construct check, not evidence that Session 4 scoring is erroneous.

## Recommended separate benchmark repair experiment — not implemented

Retain Session 4 unchanged as the negative complete-system result. In an independently named and newly versioned research branch, pre-register a revised source-generation experiment while holding the selected compiler, Guard, prompt, provider and scoring fixed. Have independent source reviewers validate unique executable intent before evaluation; do not use the tested Guard's acceptance as the definition of valid language.

Generate each canonical mission across a balanced, crossed set of realizations: connectors should be inserted once per boundary; a standalone stop should have a standalone clause. Balance connector and number/wrapper families across horizon and skill composition. Preserve duplicated/prefixed connector minimal pairs as a separately labeled robustness set, with author confidence and labels frozen before model results. Store the exact generation and overlap-selection recipe, generator code hash, source-to-IR alignment annotations, and byte-level dataset export hashes. Validation should cover every realization family and its single-step boundary cases, not only L1.

Report guarded-system exactness, Guard false rejection and provider coverage separately; analyze provider conditional exactness with its actual composition and pairing. Any additional direct-model diagnostic arm would require its own new protocol and would not constitute permission to execute missions that bypass safety gates. No repaired benchmark outcomes may overwrite or reinterpret the original 243/306 score as PASS.

This benchmark repair experiment is separate from the source-authority safety-hardening experiment. A cleaner corpus cannot resolve OOD unsafe acceptance or reopen the Runtime gate. Runtime remains blocked pending the safety architecture gate and a separately frozen valid runtime benchmark.

## Source integrity qualification and file hashes

All 18 inspected sources match the trusted Session 4 text snapshot after line-ending normalization, and every checked scientific file's current exact SHA matches frozen provenance. Six previously committed files have CRLF working bytes but LF Git blobs: canonical Final YAML, language Final YAML, Final corpus manifest, leakage audit, Pilot selection and Pilot manifest. Five are directly pinned by the freeze manifest; Pilot manifest is not. This predates this audit and was not changed here. Current-workspace scientific byte verification passes, while a fresh Git checkout with the current `-text` attributes fails to reproduce those five pinned hashes without reconstructing their serialization. The checks file preserves both hashes rather than claiming exact Git-byte equality. Default ID selection overrides are a separate generation-recipe reproducibility limitation. Neither changes the source/result join or rescoring policy in this audit.

| Inspected source | Exact working-byte SHA-256 |
| --- | --- |
| `src/g1swarm/longhorizon/corpus.py` | `d20386f4a80ccaafae6add1c9ec1e6e2c798a5d4a58103a840e2f54445548d54` |
| `src/g1swarm/simplex/structural_guard.py` | `b9c44c98dce648a77a0ac6e2acdd2af682b16b3e4bb0e0a4ceb48bd1a35f3eac` |
| `tests/test_long_horizon_freeze.py` | `94ce5d43e1cfabd3a17aa72f1528fbeb13cc3a5ca618ed907279a14fd94631af` |
| `session4/compiler_results.json` | `6e198daa5e77be1e48f0c7996290d697a77193d2aefdcff7f1add3add1262251` |
| `session4/independent_compiler_checks.json` | `87e401fbd84f7b34725ecb7d0712e407c1dcb609f78a304006c2a96e03ed2ebf` |
| `ood/evidence/pilot_language_realizations.yaml` | `42a570d998a458febdc31fb8530e5a956fd1161b8eae8b8e4c1f13b82e913910` |

Offline check result: **PASS** for membership, stored-count reconciliation, template-family exhaustiveness, provider non-invocation on every rejection, Pilot exclusion, frozen scientific hashes and freeze-tag resolution. No system behavior test was run by this sub-audit; the two reproducibility qualifications above remain explicitly reported.
