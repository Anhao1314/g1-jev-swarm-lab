# Phase3A correction-origin selection, residual off

This independent experiment adds only the actual-origin/ideal-heading hybrid.
Historical actual/actual and planned/ideal treatments are replayed unchanged and
must reproduce retained reference-ablation results before interpretation.

The origin contrast is hybrid versus full-ideal, with commanded heading fixed.
Hybrid versus actual/actual supplies a conditional heading contrast. Three arms
do not identify a complete2×2 interaction or a linear decomposition of error.
Actual origin means the node-start position held fixed through that Walk, not
the continuously moving current pose. Planned heading is the unchanged commanded
heading recipe. Only the frame supplied to walking correction changes.

All locomotion weights, PD, correction gains/clamps/deadband, skill lifecycle,
actual-start measurements/envelopes, cases and existing metrics stay frozen.
Residual is off; old PPO reward/observation/network/window/budget sources remain
unmodified and no training runs. The inherited training hypothesis gate is copied
verbatim; the new candidate is hybrid. No envelope or label is redefined.

Primary26cases perarm=78records:16transitions,8primitives,2sequences. A separate
identical78-run pass tests repeatability and is not pooled with primary. These
are already-seen mechanism cases, not fresh blind generalization. Both retained
arms must match previous physical records; all primitive and repeated outcomes,
selected origins/headings, per-command feedback and per-physics correction
counters are inspectable. Local task failures are preserved independently of
global-route improvement.

Use the previously pinned local environment/assets from repository root:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/run_phase3a_origin.py --output-dir artifacts/origin_selection_ablation_001
```

Replication requires a new output-dir; existing campaigns refuse overwrite.
`freeze_phase3a_origin.py` is the one-time freeze creator, not a reproduction
step. Verify the retained history manifest:314 prior pilot/reference files plus
219 baseline source/asset pins. New source, protocol, inherited gate, cases and
checkpoint provenance accompany evidence. Every per-sample outcome and any
campaign exception is retained; no outcome-dependent retry or checkpoint choice.

Even if the hybrid gate passes, stop after reporting; a next PPO comparison
belongs to a separately authorized experiment. If conflict persists, preserve
the negative result and continue causal localization without editing envelopes.
Phase2.3 language Runtime remains BLOCKED; no Jev/Multi-Swarm is introduced.
