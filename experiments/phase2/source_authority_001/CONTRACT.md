# Source authority contract v1

This Phase 2.4 research module wraps the immutable `guarded_direct_llm_v1`
comparator. It does not replace the compiler, change Structural Guard 2.2b.2,
repair a candidate, or execute a Mission.

`source_authorization(source, candidate_ir, authorizer=...)` returns a typed
`AuthorizationResult`: `AUTHORIZED_UNIQUE`, `AMBIGUOUS`, or `UNKNOWN`, plus a
reason and inspectable evidence. `apply_gate` returns the original executable
candidate only when Guard passes, MissionValidator reports legal IR, and the
authorization result is `AUTHORIZED_UNIQUE`. Every other result contains no
Mission. Unsupported, exceptional, malformed, missing or contradictory
authorization is `UNKNOWN`, never a default success.

`AUTHORIZED_UNIQUE` asserts that the **entire original source** uniquely
authorizes one materially distinct executable interpretation, and, for the
source-aware verifier, that the immutable candidate exactly implements it.
`AMBIGUOUS` means a material competing interpretation or explicitly unresolved
relation. `UNKNOWN` means inability to establish authority, including unsupported
relations, missing context, source/candidate mismatch, incomplete evidence and
unusable provider output. A clear mismatch is distinguished by its reason code
even though the public three-status interface maps it to `UNKNOWN`.

Both treatments inspect action multiplicity, action order, correction/edit
scope, repetition scope, reference resolution, temporal relations, and explicit
unresolved relations. Every dimension requires a judgement and explanation.
Evidence segments must concatenate to the exact original source, including
punctuation, whitespace and suffixes. Copying complete source does **not** prove
complete semantic consideration; this is an auditable contract constraint.

The semantic ambiguity ablation sees source only. Its `AUTHORIZED_UNIQUE`
assertion concerns source uniqueness and cannot establish candidate fidelity.
The source-aware treatment is instructed to derive a source plan before comparing
the visible candidate; it must provide that complete plan, which the host parses,
validates, and compares deterministically. IDs are s1…sN and dependencies form
the explicit linear predecessor chain. Candidate identity (`mission_id`) is
ignored. Count, skill, parameter, order and dependency differences reject. This
adds strict canonical chain consistency; it may reject legal B candidates with
different identifiers or sparse dependencies and must be reported as availability
loss, not improved source semantics.

The declared language convention permits implicit stand duration 2.0 seconds;
explicitly vague duration remains unresolved. Numeric conversions and turn signs
retain existing language semantics. Runtime capability, grounding and physical
risk are outside this layer. Legal commands outside capability evidence are not
rejected for that reason. No confidence score grants authority.

Provider first responses are retained. No failed semantic response is repaired
or retried. Frozen transport retries remain visible in the journal. Gates do not
run on B refusals, so `NOT_EVALUATED` is separate from `UNKNOWN`; unavailable
historical B responses are also retained explicitly.

This is a rejection-capable empirical verifier, not a semantic proof system.
All three model-dependent components share `deepseek-flash`. Candidate anchoring,
common language defaults, omitted scope and false unanimous uniqueness remain
possible. A schema-valid false witness can pass. The paired Pilot measures that
risk on already observed evidence and cannot establish distributional safety.

Runtime stays **BLOCKED**. D011 stays **candidate** pending separately designed,
independently authored development/calibration/held-out evaluation after a new
freeze. The author must not see verifier rules. This session does not start that
campaign or alter the old long-horizon benchmark.
