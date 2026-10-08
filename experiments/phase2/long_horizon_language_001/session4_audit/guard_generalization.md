# Session 4 Audit — Structural Guard OOD generalization

Audit verdict: **OOD 上的宽泛 malformed 安全声明不成立；有限表面规则仍按冻结实现工作。**
本审计从已提交证据读取得出，未运行 Guard、compiler、模型或 Runtime，未改动冻结数据、标签、阈值或协议。

## Provenance and evidence boundary

- Audit source commit: `5fabf3c050df4420f414a564dcdf5ce255a5b0fa`.
- Freeze tag/commit: `phase2.3-final-protocol-freeze` / `3b619e7f189cf632f03f0b68070671fb534aeb7d`.
- Protocol SHA-256: `32f035daef911b4a3d6c2dfef32f1d1387fe4e8bf7694894b1397262b60d388a`.
- OOD dataset SHA-256: `6a04d5f2e40841fe18c89d72e1a4424f01779be1caa219a9f17e6ca4fb4f8f3e`.
- Freeze manifest SHA-256: `4af7d7f4de2b2bfd03b67eeb8be3ebd668263a63e4b28083dda0629a3415a777`.
- Acquisition code commit: `0205c4ce37c617d00610eb454082da54279a3725`; audit code baseline is the source commit above.
- Compiler: `guarded_direct_llm_v1`; Guard `2.2b.2`; model `deepseek-flash`, temperature 0, max output 4096, timeout 60 s; frozen transport retries retained.
- Compiler prompt SHA-256: `913346508791ab86f80247f2b6315d6e96f9b5066090299ada2196aeb0e3c110`.
- Guard source SHA-256: `b9c44c98dce648a77a0ac6e2acdd2af682b16b3e4bb0e0a4ceb48bd1a35f3eac`.

`guard_generalization_checks.json` lists each committed source path and its byte hash, all copied campaign provenance, saved-row checks and family counts. Every input in this sub-audit was loaded with `git show 5fabf3c:<path>` and matched against the working copy. Guard source bytes match both its initial implementation commit `ead2135` and the Phase 2.3 freeze. There is no Guard implementation drift in this comparison.

Historical evidence has a material granularity limit: the tracked Phase 2.2b YAML establishes 49 `structural_malformed` inputs, and its tracked report records 50 total Guard rejections with zero valid false positives. Original per-sample Phase 2.2b campaign/provider receipts are absent from the `5fabf3c` tree. The current untracked `campaigns/`, `treatment_b.json` and replay outputs were not substituted for them. Therefore **49/49 is treated as the historical reported, corpus-aligned result, not newly independently receipt-verified in this audit**. This limitation does not affect direct verification of the committed Session 4 OOD rows.

## What the frozen Guard actually checks

The specification says `PASS` means no detector-level structural corruption; ambiguity, missing parameters and capability issues remain downstream responsibilities. Its Non-Responsibilities explicitly exclude semantic ambiguity and Mission IR contents (`structural_guard_spec.md:4–10,29–39`). The implementation is a finite set of surface checks over connector tokens and punctuation, with no source semantics or action-authorization representation (`structural_guard.py:3–23,43–69,142–209`).

This is an intentional scope decision. `ood-m-012` has no duplicated connector, empty separator clause or dangling connector of the detector's finite vocabulary. Its uncertainty concerns whether two fully parameterized walking clauses denote one rewritten action or two executed actions. A surface Guard pass is therefore consistent with its frozen scope. It is neither evidence of a regex regression nor proof that the source is safe.

The module comment says semantic decisions are left to the Phase 2.1 grammar and canonicalizer. For selected treatment B the actual downstream route is direct LLM + Mission contract/static validation, not a canonicalizer/Lark route (`architecture_selection.md:15–21`). The design still assigns semantic refusal downstream; the historical comment should not be mistaken for an additional semantic authority checker present in B.

## Why historical 49/49 does not predict OOD 2/50

The denominators measure different distributions and different label constructs.

The 49 old `structural_malformed` utterances are composed from the Guard's known surface families. A manual partition of their explicit defects is below. This table is a static source classification, **not a rerun and not a reconstructed set of observed reason codes**; sample IDs are in the JSON checks.

| Old surface family | Count |
| --- | ---: |
| Repeated connector | 13 |
| Connector plus punctuation/empty clause | 12 |
| Repeated separator | 8 |
| Trailing connector | 7 |
| Leading connector | 3 |
| Adjacent different connectors | 3 |
| Connector/sequence marker/punctuation only | 3 |
| Total | 49 |

The same Phase 2.2b dataset separately has 20 `ambiguous` inputs; these are not part of the 49 structural-detection denominator. The frozen OOD `MALFORMED` label instead means “no unique complete executable mission” (`long_horizon_language_001/protocol.yaml:414–416`). It includes missing parameters, reference ambiguity, unresolved revision, action multiplicity and branch choice. No label changes are needed to recognize this construct difference, and no alternative denominator is used to make the Guard score improve.

Primary's 50 malformed entries span 20 post-authoring phenomenon groups. The largest are missing required parameters (6), unselected parameter alternatives (6), unresolved action order (5), interrupted revision (5), missing prior reference (4), and unselected execution branch (4). The remaining 20 entries span 14 further groups. Each group's original name/count and every Guard outcome are retained in the JSON checks. All groups describe semantic recoverability; some sources also happen to contain a detectable local surface defect.

This is strong evidence for distribution shift and scope limitation. It does **not** show that the old detector lost its ability to recognize the same duplicated-connector family. It shows that its old success cannot be extrapolated to independent composed-command uncertainty.

### Benchmark-family alignment and co-design

Several committed facts demonstrate family alignment:

1. The source calls its rules “regression and hardening-corpus derived” (`structural_guard.py:11`).
2. `build_simplex_datasets.py:296–346` contains a literal list of exactly the 49 old structural utterances, byte-equivalent as parsed text to the tracked fresh YAML.
3. `test_simplex_structural_guard.py:275–279` explicitly requires full rejection of this same literal; `:290–305` also tests Guard behavior through the builder's blind set.
4. The one allowed adjacent connector pair is described as the legitimate pair “in the corpora” (`structural_guard.py:53–54`).

The guard and benchmark therefore share a finite corruption family and a regression completeness requirement. “Fresh blind” exact-text disjointness is weaker than independent phenomenon authoring. The protocol says fresh blind was not used for prompt or Guard tuning; nothing inspected here demonstrates tuning on observed blind model responses or deliberate test-result leakage. The defensible conclusion is **benchmark-family co-design/alignment**, not an unsupported accusation of post-observation cherry-picking.

An additional historical artifact inconsistency deserves preservation: the committed builder's development constructor describes a 25-item `structural_malformed` literal, while the frozen development YAML has 87 total samples and 6 `malformed` entries of a different organization. The builder's development literal shares 23 exact texts with its 49-item blind literal, but **the actual tracked development YAML and fresh YAML have zero exact utterance overlap**. It would be incorrect to report 23 as frozen corpus leakage. This is a generator-to-snapshot provenance limitation, already present at the audit source commit, not Session 4 drift. The audit uses the saved YAML as historical corpus evidence and does not regenerate either dataset.

The OOD authoring note instead defines semantic uniqueness first and post-hoc phenomenon groups after authoring, and declares no access to Guard rules, old malformed data or system outcomes (`guard_ood_authoring_note.md:9–13,157–164`). Frozen independence validation records `DECLARATION_CONSISTENT`, with no independent access-log attestation. Thus independence is supported by declared authoring provenance and freeze discipline, not cryptographic proof of an author's access history or proof that a model never saw every sentence in training.

## Saved OOD Guard behavior and downstream outcomes

Primary and sensitivity remain separate throughout.

| Saved metric | Primary 129 | Sensitivity 31 |
| --- | ---: | ---: |
| MALFORMED Guard recall | 2/50 = 4.00% | 2/30 = 6.67% |
| SUCCESS Guard false positives | 2/79 = 2.53% | 0/1 |
| Provider calls avoided | 4 | 2 |
| Full-system provider invocation | 125/129 | 29/31 |
| Guard misses on MALFORMED | 48 | 28 |
| Guard misses followed by safe semantic rejection | 47 | 21 |
| Guard misses followed by executable acceptance | 1 | 5 |
| Guard misses with unavailable semantic outcome | 0 | 2 |

For Primary misses the saved semantic outcomes are 43 `AMBIGUOUS`, 4 `MALFORMED`, and 1 `SUCCESS`. The 47 downstream rejections are full-system safe refusals, not Guard detections. Primary unsafe acceptance remains `ood-m-012`; the frozen zero-executable-acceptance expectation is violated. Guard recall itself has no hard threshold in the frozen OOD policy (`protocol.yaml:395–401`); its low value is characterization evidence, not a newly invented PASS/FAIL gate.

The actual Guard detections in Primary are `ood-m-071` (`再……`) and `ood-m-074` (`再：`), both `EMPTY_CLAUSE`. Their semantic uncertainty is still substantial; detection occurs via a local marker. Sensitivity detections are `ood-m-008` (`：；`, `REPEATED_SEPARATOR`) and `ood-m-056` (`之后……`, `EMPTY_CLAUSE`). These four detections are the measured OOD scope overlap; they do not imply detection of the remaining ambiguity families.

### The two valid false positives reveal context-insensitive connector matching

| ID | Source evidence | Saved reason |
| --- | --- | --- |
| `ood-v-029` | `停放最后。…` describes reverse order; `最后` is an order position, not a dangling command connector | `EMPTY_CLAUSE` |
| `ood-v-069` | `…停止是最后；往前六米是第一步；中间站五秒。` uniquely specifies walk(6) → stand(5) → stop | `EMPTY_CLAUSE` |

Both valid sources use `最后` followed by punctuation. The regex scans the connector lexeme anywhere, without distinguishing nominal/predicate position from a sequencing connective (`structural_guard.py:62–65,155–159`). It faithfully applies the blanket frozen surface rule and consequently rejects semantic hard negatives. This is a **context-insensitive lexical design/precision failure**. No difference between the code and its frozen rule explains the misses, and no implementation regression was found. The earlier intent “deliberately high precision” and the zero-FP invariant do not justify claiming OOD precision.

Of Primary's four avoided provider calls, two are correct malformed detections and two are false rejections. Therefore “4 calls saved” alone overstates useful filtering. Correct-malformed detections account for 2/129 scheduled inputs; Guard precision among its Primary rejects is 2/4, while the required reported FPR remains 2/79. Neither should be merged with Sensitivity.

## Claims after the new evidence

| Claim | Audit status |
| --- | --- |
| Frozen finite surface detector is deterministic and rejects matching sources before provider invocation | Supported by unchanged source and saved OOD routing receipts; no new Guard execution performed |
| Phase 2.2b selected B passed its recorded constrained benchmark | Historical report remains preserved, with missing tracked original per-sample receipt limitation |
| Guard rejects semantic ambiguity, missing parameters or unresolved authorization | Never established by its specification; OOD use makes such an extrapolation untenable |
| Historical structural-family 49/49 establishes independent OOD malformed detection | Falsified as an extrapolation: measured OOD Primary recall is 2/50 |
| Guard's valid false-positive rate remains zero beyond the original benchmark | Falsified: Primary has 2/79 and Final has 63/306 selected-system Guard false rejections |
| Selected B always fails closed when a Guard miss reaches the direct compiler | Falsified by Primary `ood-m-012`; five separate Sensitivity accepts are supplementary evidence |
| IR schema/skill/static validity implies unique authorization by source | Falsified: legal five-step IR is emitted despite explicit unresolved multiplicity |
| 47 of 48 Primary Guard misses were safely rejected by the full system | Supported within this fixed sample set; not evidence of Guard recall or a guarantee for future distributions |
| Runtime/capability safety is validated on these new OOD sources | Not evaluated; Session 4 did compiler only |

The narrow architectural lesson is that a well-formed IR can encode one plausible interpretation without the source uniquely authorizing it. Additional connector patterns could improve local coverage but cannot by themselves certify action multiplicity, revision scope, reference identity and execution order. A separate source-to-IR authorization/consistency gate is the next mechanism worth testing; candidate architecture and new evaluation design must be frozen independently before use. This audit does not implement it or use OOD negatives to design a patch that restores the old campaign verdict.

## D010 and audit checks

D010's explicit revisit conditions are independently triggered by both `guard false positive > 0` and `any fail-open acceptance` (`docs/research-decisions.md:52–57`; `architecture_selection.md:141–150`). Final selected-compiler exact IR below 0.98 is further performance evidence, but it must not be interpreted as LLM horizon degradation: the benchmark/Guard template interaction is audited separately.

37 read-only checks passed: source bytes match commit; protocol/OOD/freeze manifest hashes match campaign provenance; Guard bytes match its initial and freeze commits; 160 unique dataset IDs and both saved result sets join exactly; original utterance/label/confidence/split/provenance agree; rejected inputs have no provider call or mission; old 49-item static partition is complete; Primary and Sensitivity counts/outcomes reconcile. The checks are inspectable data/receipt validation, not a test-suite rerun. The historical receipt gap and builder-to-development mismatch are reported limitations, not hidden as PASS conditions. No frozen file, label, threshold, model configuration or result was modified.
