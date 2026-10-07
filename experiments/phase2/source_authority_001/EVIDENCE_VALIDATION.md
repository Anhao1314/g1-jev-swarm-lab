# Independent read-only evidence validation

`scripts/validate_source_authority_evidence.py` inspects stored data only. It does
not invoke a compiler, provider, Grounder, Runtime, or skills and does not modify
acquisition code, frozen inputs, results, protocol, or prompts. It uses the
unchanged Structural Guard and MissionValidator to recheck deterministic release
predicates. Its scoring, ledger inspection, assistant-text extraction, source
reconstruction, and token accounting are separate implementations from the
acquisition harness.

During collection:

```text
python scripts/validate_source_authority_evidence.py --partial --output artifacts/phase24-source-authority/evidence_validation.partial.json
```

After all 528 samples complete:

```text
python scripts/validate_source_authority_evidence.py --output artifacts/phase24-source-authority/evidence_validation.final.json
```

Once the separately labeled post-hoc `bounded_control.json` exists, add
`--bounded` to check its exact membership, raw baseline-file SHA links,
independent scores, release predicates, unchanged B candidates, full-source and
normalized-source hashes, parse-consumption witnesses, and zero provider cost.
This reads existing control outputs without rerunning the bounded parser.
Its original-language worktree hashes remain recorded provenance; immutable Git
anchor content checks preserve the old implementation without reasserting those
old checkout-dependent byte hashes as portable pins.

Outputs are required to remain outside this experiment directory during the
validation run. A partial PASS means the observed evidence checks passed;
`collection_status=INCOMPLETE_PARTIAL` and `final_acceptance_claim=false` remain
explicit. Active unmatched attempt begins can occur during collection. A final
PASS requires exact membership with no missing samples or integrity issues.

The validator reconstructs all 160 OOD, 179 Phase 2.2b, and 189 controlled inputs,
labels, and oracles from audit-anchor Git blobs. It checks frozen acquisition
hashes against the passing preflight, preserves the immutable B paths, and
verifies all 466 historical B replay sources/results and saved-response hashes.
For each finalized sample it independently scores release, exact coverage,
unauthorized release, false rejection, and wrong IR; compares the sample with its
durable stage receipt; and checks treatment order, first-response policy, request
hashes, contiguous transport attempts, saved assistant-text hashes, full-source
witness coverage, status agreement, IR legality, and unchanged B candidate.
UNKNOWN or AMBIGUOUS must have `mission=null`.

Token accounting uses every successful transport's `provider_document.usage`,
including incomplete reasoning-only responses that the backend represented as
an API error. `backend_response_tokens` is shown separately so omitted resource
cost cannot be mistaken for zero usage. Provider incomplete, empty assistant text,
and output-budget exhaustion are separate counts. They can overlap and must not
be summed as disjoint failure categories. Failed preflight/recovery artifacts
remain present and the passing preflight cost is reported separately.

Withheld release following resource-driven UNKNOWN is evidence of fail-closed
behavior, not evidence that the model recognized the source ambiguity. This
audit validates evidence consistency and bookkeeping; it does not establish
semantic truth, verifier independence, or new held-out generalization.
