# Structural Guard Specification

The Structural Guard is the deterministic pre-model monitor for Phase 2.2b.
It is intentionally a surface-integrity check, not a semantic parser.

## Verdicts

- `PASS`: the source has no detector-level structural corruption. Semantic
  ambiguity, unsupported capability, missing parameters and capability
  boundaries remain downstream responsibilities.
- `MALFORMED`: reject before any model call; reason code is retained as
  evidence.

## Frozen Checks

1. Empty input, punctuation-only input and sequence-marker-only input.
2. Connector-only input.
3. Immediately repeated connector, such as `然后然后`.
4. Adjacent different connectors without a command between clauses, except the
   explicitly allowed compound `然后再`.
5. Connector immediately followed by punctuation, producing an empty clause.
6. Repeated comma-class separator with no clause between separators.
7. Repeated sequence marker, such as `先先`.
8. Leading dangling connector, except the adverbial `再`.
9. Trailing dangling connector.
10. Broken arrow/separator structures reduce to an empty clause under the same
    finite-state rules.

## Non-Responsibilities

The guard never decides:

- skill support;
- distance, angle or direction semantics;
- ambiguity or missing parameters;
- capability/risk admissibility;
- execution mode;
- Mission IR contents or validity.

A guard false positive is any non-`MALFORMED` source rejected as structurally
malformed. Guard precision and false-positive rate are reported separately for
every treatment and regression set.

## Evidence

Reason codes:
`INVALID_INPUT`, `EMPTY_INPUT`, `REPEATED_CONNECTOR`, `DUPLICATE_CONNECTOR`,
`EMPTY_CLAUSE`, `REPEATED_SEPARATOR`, `REPEATED_SEQUENCE_MARKER`,
`LEADING_CONNECTOR`, `TRAILING_CONNECTOR`, `CONNECTOR_ONLY`,
`SEQUENCE_MARKER_ONLY`, `PUNCTUATION_ONLY`.
