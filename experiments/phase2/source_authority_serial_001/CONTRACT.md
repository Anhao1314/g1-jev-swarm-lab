# DG-serial concurrency-only development contract

The sole deliberately changed scored factor is verifier request concurrency: historical DG uses four workers, DG-serial uses one. Every full source, historical B candidate, gold label, input order, GLM model/provider setting, v2 prompt/parser, certificate contract, host comparison, Guard, IR validator, release policy and scoring rule remains unchanged. Compare all 528 previously observed development/regression rows; only the same 291 eligible B candidates call GLM. No compiler or historical comparator is rerun.

Serial means one semantic stage at a time, including its unchanged transport retries. It does not introduce added pacing, altered request ordering, a different timeout, retry count/backoff, thinking/reasoning setting, output budget, temperature, repair or fallback. Reasoning remains enabled with effort omitted; only final assistant content can become a certificate. No reasoning text, credential value or credential fingerprint is persisted.

Each serialized provider request must equal its historical DG4 request in full, including prompt and source-only JSON. No candidate-derived field, gold, sample ID or prior output enters the model request. The source-only typed contract and deterministic original-candidate release gate are reused without editing their implementation.

Retain every historical DG4 outcome, especially ood-m-031's false all-U AUTHORIZED_UNIQUE and unsafe release under disputed Sensitivity gold. A new result cannot overwrite or erase that counterexample. Keep Primary and disputed Sensitivity separate; no relabeling or threshold changes.

Semantic credit requires an independently correct specific typed rejection against the full unchanged source. A concrete correct UNKNOWN/unit-MISSING can receive credit; generic UNKNOWN, unavailable output, budget/transport failure and host plan mismatch cannot. Classify a false unique certificate separately from a host-withheld unique-plan mismatch; any unauthorized release blocks D011.

This is a longitudinal paired development experiment. Provider load, caching, acquisition time and named model drift remain uncontrolled. Describe observed availability changes with denominators; do not equate them to a statistically significant causal concurrency effect or claim blind generalization.

Prepare freezes all prior files, the new runner source snapshot, inputs and protocol. Confirm final code/test readiness and commit the acquisition scaffold before launch. Do not edit bound treatment files after that point. Resume can replay durable first output or fail closed on interruption; it must never reissue a started semantic call. Offline analyzer/report work may continue without changing acquisition behavior.

After this one treatment, audit, report, test and push, stop. No Runtime, fresh held-out, new model or further concurrency/retry treatment is authorized. If availability improves while semantic correctness remains insufficient, the research implication is to reconsider the release contract/authority mechanism in later work, not tune availability settings until a pass appears.
