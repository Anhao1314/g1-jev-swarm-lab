# Phase 2.3 Final Protocol Freeze

Verdict: **FROZEN_READY_FOR_FINAL**. Protocol `status: frozen`, `frozen: true`.
No OOD candidate has been evaluated by Structural Guard or Direct LLM compiler.
No Phase 2.3 campaign was run. Complete isolated tests were explicitly authorized.

## Dataset and independent provenance

All 160 independently authored candidates are retained in their original order.
The original four artifacts are preserved byte-for-byte in `ood/authoring/`.
Three supplied SHA-256 and byte sizes match; the hashes file has no self-hash,
and its independently computed SHA is anchored in the new evidence manifests.
The manifest and authoring-note independence declarations are consistent with
the user handoff. This is declaration-based provenance, not independently
verified access logs or a claim of human inter-annotator agreement.

| Set | MALFORMED | SUCCESS | Total | Primary hard gates |
| --- | ---: | ---: | ---: | --- |
| Primary Gold, original confidence=high | 50 | 79 | 129 | Yes |
| Disputed Sensitivity, original confidence=low | 30 | 1 | 31 | Never |

No balancing, selection, deletion, text edits, label changes, confidence edits,
or rationale changes were made. The original confidence is the sole split rule.
Known disputed labels remain sensitivity-only and cannot affect primary PASS/FAIL.

## Validation and interpretation

JSONL encoding, required/exclusive fields, exact ID coverage, duplicates,
allowed parameters, mission length classes, distribution counts and author
manifest consistency passed. All 80 SUCCESS utterance/author-step pairs and
50 high-confidence malformed utterances were reviewed without system output;
no objective label/schema correction was required. Known disputes remain intact.
Author MALFORMED means no unique complete executable mission, including semantic
ambiguity. A safe system AMBIGUOUS rejection is not unsafe acceptance.

All 80 SUCCESS entries (228 steps) map deterministically to Mission IR 2.0.0.
Left angles are positive, right angles negative; numeric parameters become
floats; original ordering, repeated steps and explicit stops are preserved.
Step IDs are s1..sN with predecessor dependencies. No implicit stop, action
merging, inferred repair or language compiler is used. Original expected_steps
remain in every SUCCESS row. Static parsing, validation, serialization round
trip and independent reverse-mapping checks pass. Mapping source and script
hashes are recorded in `ood/mapping_provenance.json`.

OOD exact text and ID overlap is zero against each of five historical corpora,
Pilot language data, Final language data and main safety controls (eight sources).
Exact means Unicode equality after trimming outer whitespace, with no semantic
normalization. Source paths, SHA, sizes in samples and zero-hit lists are in
`ood/overlap_audit.json`. The existing Pilot/Final ID and text exclusion remains
zero. The prior three Final-vs-Phase-2.1 short-command collisions remain disclosed
in `final/leakage_audit.json`; none involves OOD. Shared action sequences do not
constitute semantic novelty, and exact disjointness cannot prove model novelty.

Pilot (18 missions / 54 inputs), Final (102 missions / 306 inputs across H1-H16)
and OOD use separate membership and evidence scopes. Compact Pilot language and
safety-control snapshots are now tracked so exclusion checks do not depend on
ignored local artifacts. Pilot outcomes remain PILOT_ONLY.

Primary OOD metric denominators and definitions are frozen in
`guard_ood_frozen_policy` in the protocol: Guard malformed recall, Guard valid
false positives, full-system unsafe acceptance, silent repair, valid false
rejection, valid exact IR and provider invocation. Guard recall has no hard
threshold. Primary full-system unsafe acceptance count=0 is the hard safety
expectation. Sensitivity uses separate denominators (30/1/31), never pooled.
Transport failures must remain visible and cannot imply an incomplete safety PASS.

## Final hashes

| Artifact | SHA-256 |
| --- | --- |
| Author candidate JSONL | `3175a460b96827f2032938792a13b66d94d6fe5f6097d96cff059f575d43bea5` |
| Author hashes file | `07a09a2db52e3d64b51eaa97caff7e98e236cf48bf62e7352272072f960709d7` |
| Final OOD JSONL | `6a04d5f2e40841fe18c89d72e1a4424f01779be1caa219a9f17e6ca4fb4f8f3e` |
| OOD split manifest | `66da507735cc3afb149fe70c3d6302b8dbe87fb2e7414dacfb873d60361a62d7` |
| OOD hashes | `e0abf100868869871bce0d9bf7332d4073984b5ee31a77447fc6ab7447497c50` |
| Protocol | `32f035daef911b4a3d6c2dfef32f1d1387fe4e8bf7694894b1397262b60d388a` |
| Freeze manifest | `4af7d7f4de2b2bfd03b67eeb8be3ebd668263a63e4b28083dda0629a3415a777` |

## Baseline and tests

All tracked src/configs/prompts and baseline evidence were compared to handoff
commit `c491d3a807130481d7deb6de790c4f2fd00b1725` using Git clean-filter blobs;
zero drift. Their current byte hashes are also recorded. Original pinned
prompt, runtime config, robot config, capability maps and motion policy hashes
were verified. `frozen_baseline_audit.json` contains the complete inventory.
No frozen compiler/runtime/controller changes were made.

Complete suite: **577 passed, 0 failed, 0 skipped**, with 9 existing PyTorch
`torch.jit.load` deprecation warnings. Machine-readable JUnit and a compact
summary are tracked. OOD tests perform only offline integrity and static IR checks.

## Git binding and next gate

The annotated tag `phase2.3-final-protocol-freeze` binds the commit containing
this final manifest; resolve its commit and verify all hashes before evaluation.
This avoids the impossible requirement to embed a commit's own hash inside itself.
Frozen evidence paths disable automatic line-ending conversion to preserve hashes.
Existing unrelated untracked Phase 2.2b results are excluded from this commit.

Next gate: **Session 4 — Final Compiler + Guard OOD Campaign**.
It has not started. Provider preflight belongs to that next session.
