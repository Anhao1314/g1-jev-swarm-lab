# Source Authority experiment execution discipline

Research runs should answer the declared scientific decision with enough preserved evidence to inspect it. Whole-population characterization is a separate deliverable: it may require more calls, but it must not silently become the reason to continue after the decision-critical question is settled.

This guide applies to future treatments. It does not amend the frozen protocols or authorize resuming the closed DG-serial treatment. That treatment is explicitly **PARTIAL_STOPPED**; its [stop receipt](../experiments/phase2/source_authority_serial_001/stop_receipt.json) and [report](../experiments/phase2/source_authority_serial_001/report.md) preserve the scope deviation and its limits.

## Define the decision before acquisition

Before any provider calls, record:

- The hypothesis, intended decision, and the one deliberately changed factor.
- Decision-critical cases, their immutable sources/candidates/labels, Primary or Sensitivity roles, and the fixed core denominator.
- The evidence required for semantic credit, distinct from usable output, host rejection, and provider availability.
- Which full-population measurements are required for the user's decision and which are secondary characterization.
- The planned population, dispatch order, time/call limits, stopping conditions, and the claims permitted after an incomplete run.

For future treatments, put the defined decision-critical cases first when that order is compatible with the comparison design. Freeze that order before calls and document its effect on pairing. Do not prioritize cases retrospectively or reorder an active treatment to recover a desired result. Historical order remains part of historical evidence.

Freeze the complete acquisition source, configuration, prompt, contract, inputs, host comparison, scoring, and preservation registry. Commit the exact source snapshot and binding before the first call. Verify their agreement once before launch; verify preservation at closeout. A preflight must remain fictional, non-scored, and confined to its declared purpose.

## Keep observation and interpretation separate

Preserve each raw first outcome and its transport-attempt journal. Use the frozen transport-only retry count/backoff; do not repair a semantic output, reissue its semantic call, normalize an invalid certificate, tune reasoning, or change concurrency/retries to chase PASS.

A usable, specific, independently correct rejection can receive semantic credit. Generic UNKNOWN and network, output-budget, or schema failures cannot. A false uniqueness claim, a usable false-unique certificate, and an actual unauthorized host release are three separate observations. An incidental parser rejection does not demonstrate correct authority reasoning.

Use explicit acquisition states:

- **COMPLETED**: a durable final stage outcome exists, including an observed terminal provider failure.
- **NOT_RUN**: no semantic call was started.
- **INTERRUPTED_UNOBSERVED**: a call was started but its final first outcome was not observed when execution stopped.

Never synthesize a refusal or provider failure for an unobserved call. Preserve available request and attempt records. Do not include NOT_RUN or INTERRUPTED_UNOBSERVED rows in completed-outcome or final-failure rates; report their counts against the unchanged planned denominator. Missing token usage is unknown, not zero.

## Stop when the declared purpose supports it

An early stop is justified when remaining calls cannot change the predeclared core verdict and the user's intended scope supports stopping. For example, a necessary all-core-cases correctness condition is already impossible after an observed semantic counterexample. An unresolved availability question can still require its remaining decision-critical calls; a single failure does not answer every question.

If the user still needs complete population measurements, continue that bounded acquisition or explicitly obtain a scope change. Do not describe an early negative core verdict as a completed experiment or complete global characterization. An optimistic prefix does not justify early acceptance. Any acceptance rule and its necessary coverage must be declared before acquisition.

When stopping, terminate the active collector and preserve all completed and interrupted evidence. Keep the original protocol, population, labels, thresholds, and planned denominator. Add a stop receipt and a partial report; do not replace the protocol with a smaller retrospective population. Closure does not authorize resume or another treatment.

The stop receipt should include status/reason, user-scope basis, UTC stop time, frozen protocol and acquisition commit/hash references, planned and completed sample/call counts, core-case completion, NOT_RUN and interrupted identities, observed attempt counts and first-response availability, preservation checks, and explicit future-collection authorization. Record Runtime and held-out call counts as well.

## Close out with bounded validation

Run the checks appropriate to the acquired scope: membership and byte bindings, first-response provenance, scheduling evidence, deterministic comparison/scoring replay, and independent semantic review of decision-critical outcomes. Report paired measurements on the same observed membership. Label whole-population coverage, retention, cost, and latency unavailable when acquisition is incomplete.

Once checks pass and the scientific decision is determined, write the report, commit/push the preserved evidence, and stop. Repeat checks only for new changes, failures, or unresolved integrity concerns. Do not prolong closure through monitoring loops, repeated broad validation, or extra live calls.

DG-serial illustrates the distinction: 150/528 rows and 74/291 eligible stages were completed, all six core OOD cases were observed, and one row was INTERRUPTED_UNOBSERVED. Its partial results cannot supply global serial statistics. Historical `ood-m-031` remains an actual unsafe release; the later serial parser rejection cannot erase that counterexample. The next authorized research step is mechanism design and offline validation, with no live treatment, Runtime, or fresh held-out acquisition implied by this guide.
