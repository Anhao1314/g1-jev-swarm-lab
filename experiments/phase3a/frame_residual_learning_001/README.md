# Same-frame PPO residual experiment

This independent experiment keeps the first real pilot's observation, reward,
network, optimizer, rollout size, total training budget, residual bounds, 2s
window, locomotion policy, PD, skills and envelopes. Its only treatment factor
is correction heading alpha0 versus fixed alpha0.5, at actual node-start origin.

There are four treatment classes. Learned treatments are retained separately
for seeds11 and29, giving six evaluation arms. Every actor is compared only
against the residual-off baseline with its own alpha. A deterministic midpoint
gain is never attributed to PPO. No alpha, seed, budget or checkpoint search.

The original12 training cases are re-frozen unchanged. Sixteen prospectively
declared held-out cases use new distance/turn/stand/yaw combinations; old16
transitions,8 primitives and12m/16m sequences are explicitly seen regressions.
Nominal simulator seed does not randomize physics. The new held-out distribution
tests parameter interpolation within the same simulator, not new environments.
Do not simulate fresh held-out cases in tests or preflight before all four
final actor checkpoints are locked. The split manifest verifies parameter
tuples without executing them.

Execution is fixed: replay both old deterministic regression baselines; run an
independent512-step seed7 pipeline check for each frame; train four8192-step
actors in the declared order; lock every final checkpoint; then evaluate fresh
baselines and all learned arms. The same six selected cases are repeated across
all six arms for deterministic replay verification. Repeats and smoke episodes
never enter primary evaluation counts. Training-only checkpoint reload replay
never uses held-out data. Initial/intermediate/final and failed checkpoints are
all retained; evaluation uses the fixed final checkpoint exclusively.

The original61-feature observation and stateful dense/terminal reward functions
are inherited unchanged. Diagnostics never add reward calls. The original
transition masks, action decision period and total yaw bound remain unchanged.
Outside-window and primitive commands retain exactly zero residual. Model
configuration and actual invocation counts are recorded separately; inference
from a learned checkpoint is not optimization.

Analysis reports each frame and seed separately, including nominal and strict
corridors, task/physical failures, same-frame global and local error deltas,
transition geometry/time/stability, primitive identity and cross-seed direction
agreement. Zero baseline failures create a binary ceiling, not a learning gain.
Strict baseline failures remain visible. No new historical envelope or gate is
created to obtain a positive verdict; mixed and negative learning effects are
valid findings. With two seeds, consistency is a descriptive pilot result, not
a statistical robustness claim.

```powershell
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
.venv\Scripts\python.exe scripts/run_phase3a_frame_learning.py
.venv\Scripts\python.exe scripts/export_phase3a_frame_learning.py
```

Campaign output is exclusively created at `artifacts/frame_residual_learning_001`.
Every final source is committed before acquisition and checked by hash. Existing
Phase3A sources and evidence are pinned and remain untouched. Exports are
lossless and include checkpoints, decision/episode/update ledgers, traces,
split/protocol/source provenance and incomplete-budget tails. See `REPORT.md`,
`analysis.json`, `evidence_manifest.json`, and independent audit JSON after
publication. Language Runtime remains blocked. This session stops after tests,
audit, report and Git push; no Jev or Multi-Swarm follows.
