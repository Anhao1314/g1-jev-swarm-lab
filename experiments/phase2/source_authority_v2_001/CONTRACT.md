# Exploratory source-authority certificate v2

This amendment is a separate candidate-blind treatment. Original v1 outcomes,
prompts, implementation, acquisition receipts, B comparator, labels and frozen
evidence remain intact. Its pilot is development/regression evidence, with no
fresh-blind or Runtime claim.

The implementation is `src/g1swarm/authority_certificate_v2.py`, with prompt
`prompts/authority_certificate_v2.txt`; these paths avoid the frozen v1 globs.

`SourceAuthorityCertificateIssuer.issue_certificate(source)` accepts only full
original source and sends exactly `{"source": source}` to the provider. It never
reads or validates a compiler candidate. Its typed `CertificateOutcome` reports
status, usable, reason_code, certificate and diagnostics. `usable` separates a
valid semantic AMBIGUOUS/UNKNOWN certificate from a provider or schema failure
that also fails closed as UNKNOWN.

`authorize(source, candidate_ir)` issues that source-only certificate first,
even for an invalid candidate. Only afterward does a deterministic host build
the plan, validate it, validate the candidate and compare complete frozen
canonical semantics. `apply_gate` remains unchanged: frozen Guard pass, legal
unchanged B candidate and AUTHORIZED_UNIQUE are all necessary for release.

The certificate JSON has exactly `status`, `checks`, `plan`, `issues`.

| Field | Contract |
| --- | --- |
| status | AUTHORIZED_UNIQUE, AMBIGUOUS or UNKNOWN |
| checks | Seven U/A/? values: multiplicity, order, edit, repetition, reference, temporal, unresolved relations |
| plan | Ordered arrays `[skill, scalar]`, or `["stop"]`; null for rejection |
| issues | Compact `{relation, reason}` objects from the finite pair table; no prose |

An A check dominates ? and yields AMBIGUOUS. With no A, ? yields UNKNOWN.
AUTHORIZED_UNIQUE requires seven U checks, 1..32 legal actions and no issues.
Nonunique certificates require a null plan and at least one issue of their
overall semantic status. AMBIGUOUS may additionally contain unknown issues;
UNKNOWN cannot contain an ambiguous issue. Duplicate issue pairs are rejected.

Ambiguous issue pairs are `multiplicity/order/edit/repetition/reference/temporal/
unresolved` with `UNRESOLVED`, and `quantity` with `MISSING` or `VAGUE`. Unknown
pairs are `reference/MISSING_CONTEXT`, `temporal/UNREPRESENTABLE`,
`unresolved/UNREPRESENTABLE`, `unit/MISSING`, `unit/UNSUPPORTED`,
`quantity/INVALID`, `quantity/UNKNOWN`, `unsupported/UNSUPPORTED` and
`unknown/UNKNOWN`. Missing unit is UNKNOWN; required missing quantity and vague
quantity are AMBIGUOUS. Unsupported capabilities and unrepresentable temporal
relations are never approximated by legal skills.

Explicit supported distance/angle/time units are required for specified
quantities; certificate tuple field names never supply a missing unit. Unit,
quantity, unsupported and unknown issue families mark the seventh unresolved
relations check A or ? according to their issue status; no eighth dimension
is added.

Host plan construction creates s1, s2, ... and the existing exact predecessor
dependencies. Scalars map to stand duration_s (default 2.0 only when absent in
source), walk_forward distance_m, or turn angle_deg (left positive/right
negative). stop has no scalar. Static MissionValidator bounds remain unchanged;
there is no capability/risk inference. Comparison excludes mission_id but
includes schema, complete action count/order, all parameters, IDs and dependencies.
Thus a different noncanonical ID/dependency representation may be falsely rejected.

Only the first model output is used. The parser rejects duplicate JSON keys,
nonfinite or boolean scalar values, extra keys, wrong array sizes, inconsistent
checks/status/issues, invalid skills/parameters, excessive size and nonnull
rejection plans. Limits are 8192 source characters, 16384 response characters,
32 actions and 16 issues. A successful transport response must name exactly the
configured model and explicitly report completed status with a completion finish
reason. Existing transport-only retries remain permitted. No output repair or
automatic second semantic call occurs. Provider model/temperature/output-token
settings remain the declared deepseek-flash / 0 / 4096 configuration; this module
does not override or dynamically tune them.

The body omits source copies, offsets, explanations and confidence. Full original
source still reaches the provider, and raw response, response/request hashes,
usage, attempts, latency and completion/model provenance remain in diagnostics.
Compact checks are model assertions; they are not a formal source-interpretation
proof. Removing source-copy/rationale overhead may improve usability, but loses
the v1 verbatim coverage witness and explanatory audit detail. This tradeoff
must be measured without replacing the original v1 acquisition results.

Candidate-blind issuance removes direct candidate anchoring. It does not establish
statistical independence: the same model/provider can independently make the
same source-interpretation mistake as B, and matching plans can then falsely
authorize a candidate. Full-source omissions, mistaken edit/repetition scope,
premature all-U assertions and compact-certificate schema failures remain known
failure modes. A uniquely legal plan also does not establish Runtime readiness.
