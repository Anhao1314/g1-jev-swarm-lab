# Stand5 paired mission reference acquisition candidate

This is a nonphysical engineering preparation. `protocol.json` and `rule.py`
are exact copies of the independently reviewed 2026-10-13 offline design.
No acquisition permission is conveyed by this code or its tests.

## Retained execution

The physical backend derives from Phase 3B.0a's Stand5 CONTINUE runner. It
retains the historical learned-interface **zero action callback**, 440 historical
observation/reward calls, deterministic seeds, controller and all original skill
termination/scoring. It does not load a PPO actor. At the first Walk entry it
selects once, preserving the `.5` correction object verbatim or using the existing
tradeoff-isolation `.25` reference formula. Mission world targets remain unchanged.

Order: selected reference (`.5` expected), then fixed `.25`. Each complete mission
has at most 40,000 native calls / 120 seconds; total 80,000 / 240 seconds. Reserve
two seconds for process cleanup and two seconds for parent closeout; this reduces
usable time, never enlarges the frozen ceiling. First arm's replay mismatch stops
before dispatching the second arm. Second arm's predecision mismatch stops after
the Stand prefix **before** its first Walk. Each arm is attempted once.

## Exact replay contract

Historical source:
`experiments/phase3b/decision_benchmark_acquisition_001/evidence_attempt02/runs/02--phase3b0a-stand5-16m--continue--primary`.

Compare every result, trace and decision field, predecision state, every ndarray
in poses, and all audit hashes/counts. Tolerance is **zero** for this same-environment
historical replay. Only top-level publication identifiers/provenance and fields
named `wall_time_s` or `elapsed_wall_time_s` are omitted. Non-Walk reference NaNs in
the retained pose format compare as identical sentinels; no numeric NaN is accepted
as a comparable scientific JSON result. `active`, alpha, scoring, reset counts,
command/torque/observation streams and RNG/policy state hashes are not omitted.

The separate prospective outcome contract retains its existing `1e-9` arithmetic
comparison tolerance and `0.01 m` minimum comparative effect. These are not new
physical success thresholds. All original ordered Walk/Turn targets are compared,
plus final absolute X/Y/heading components. Strict/physical labels remain original.

## Freeze and nonphysical reproduction

Use the retained Windows interpreter recorded in `environment.json`. No install
is required. `asset_restore.json` binds 91 byte-identical official assets copied
without overwriting their original directory. All 41 dependencies match the
retained Windows receipt. This does not prove physical replay equivalence.

After committing execution code, `run.py freeze --output NEW_DIRECTORY` writes
an immutable source manifest and Readiness with exact C_exec outside the source
tree; their hashes are subsequently recorded in the independent acceptance report.
`run.py preflight --readiness PATH --sha256 HASH` performs metadata/hash checks only.
`test_readiness.py`, `test_backend_contract.py` and
`verify_frozen.py READINESS NEW_EVIDENCE_DIRECTORY` are nonphysical tests.

The production worker is a single trusted local Python child. A Windows venv
redirector changes parent PID and survives direct-child-only termination. The
launcher therefore invokes the exact pinned base interpreter with the same venv
launcher identity, and uses process-tree termination on timeout. The final guard
test checks this exact path. This is not adversarial user authentication, a generic
descendant service, crash recovery, or permission to execute the experiment.

Owner must separately approve the exact C_exec, Readiness, two-arm order and budget
before `acquire` is used. Do not invoke worker directly, retry a failed arm, restore
simulator state at entry, relax replay matching or alter historical outputs.

Raw outcomes and technical exceptions are separate. Native attempts, confirmed
native returns and uncertain completion are distinct. Failed constructors or
archives retain per-operation errors where writable; missing status is a technical
stop, never success. Catastrophic host/disk failure cannot promise complete evidence.
