# Phase3A heading alignment strength

This independent deterministic ablation changes only walking correction heading
selection, with origin fixed at the actual node-start position. Residual is off.
The prospectively fixed treatments are alpha=0, 0.5, and 1. No other alpha is
permitted, and a failed midpoint will not trigger parameter scanning.

The reference is `wrap(actual + alpha * wrap(commanded - actual))`, with
`wrap(x)=atan2(sin(x),cos(x))`. Exact historical endpoint recipes preserve
floating-point identity: alpha=0 is the old actual frame; alpha=1 is the retained
actual-origin/ideal-heading hybrid. The midpoint follows the wrapped short arc.
The selected orientation rotates both lateral and heading correction axes.
Gains, clamp, policy, PD, skill bodies, termination, resets and settling remain
unchanged. Original actual-start local measurements and task envelopes continue
to determine success; control-frame error never substitutes for local scoring.

The same 26 mechanism cases are run per arm: 16 transitions, eight primitives,
and the 12m/16m sequences. These cases have been examined before. The legacy
evaluation-set identifiers do not imply fresh blind generalization. Primary
78 runs and a separate predeclared 78-run identical repeatability pass are kept
distinct; repeated nominal dynamics are not independent samples.

History is pinned by `history_freeze.json`: 492 earlier source/evidence files,
with the inherited 219 baseline asset/source pins checked separately. The case
manifest, official motion.pt and inherited reference protocol are also pinned.
All 104 alpha=0/1 endpoint runs must reproduce the earlier origin experiment;
all 78 repeated physical records must match. The original training hypothesis
gate is copied without changing criteria or thresholds, with midpoint as the
candidate. Both sequences must improve absolute ideal lateral and heading
errors, without task/physical regression, primitive changes or integrity loss.
Endpoint norm, local drift, transition geometry, durations and stability are
retained diagnostics and cannot erase a gate failure.

Run from the repository's existing environment:

```powershell
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
.venv\Scripts\python.exe scripts/run_phase3a_heading.py
```

The campaign creates `artifacts/heading_alignment_strength_001` exclusively;
outcome retries and overwriting are prohibited. `scripts/export_phase3a_heading.py`
exports the retained results with raw and encoded hashes. See `REPORT.md`,
`decision.json`, `evidence_manifest.json`, `mechanism_audit.json`, and
`independent_results_audit.json` after publication.

Even a passing deterministic gate only supports a subsequent, independently
authorized PPO experiment with matched same-frame residual-off controls. No
PPO, Jev, Multi-Swarm, or language Runtime campaign is run in this study. The
Phase2.3 language Runtime gate remains blocked. This session stops after audit,
report, tests and Git publication.
