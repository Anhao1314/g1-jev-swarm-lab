# Residual authority mechanism replay — Console vertical slice

**Implementation verdict: complete.** The existing Console now defaults to the fixed residual-authority mechanism case, with residual-off, combined inward and forward/inward corner displayed together. The original two-arm reference slice remains selectable. This is an observer update, not a new control experiment. The source scientific verdict remains INCONCLUSIVE; Phase 3A.5 remains paused.

Open **http://127.0.0.1:8766/**. The task-owned localhost server is read-only and remains available for viewing. The previous server on 8765 was not stopped. If this viewer is later stopped:

```powershell
.venv\Scripts\python.exe console/server.py --data experiments/research_console/residual_authority_replay_001 --port 8766
```

## Observable mechanism

The default playhead is Walk-relative, with the original Stand→Walk boundary as 0s. The phase strip explicitly shows:

`0s → residual active → 2s authority ends → residual=0 → Walk completion`

Three native MuJoCo videos share requested simulation time. Each arm's presented retained frame drives its trajectory point, metrics and chart marker. At completion each video freezes at its own original Walk end, rather than a common percentage or another arm's completion. Full 16m playback remains available.

Local drift, correction-reference lateral, world distance to the original Walk8m commanded endpoint, and paired local effect versus residual-off are plotted over Walk time. The first 2s is shaded; the cutoff and playhead are marked. The route stays in world coordinates, with a common scale, the original fixed correction reference and local endpoint-corridor guides. The video camera follows each robot; calibrated displacement is read from the world route and evidence metrics, not inferred from camera-relative pixels.

The three visible key effects are computed by `console/build_authority_replay.py` from the retained experiment, not literal frontend numbers:

- Combined's early local difference uses the original boundary trace and independently audited projection minus its own residual-off baseline.
- Remaining local difference uses the two original formal Walk endpoint scores.
- Corner's remaining strict gap uses its original formal local endpoint and strict envelope limit.

Exact values and source locators are saved in `runs/*/run.json#/authority` and the validation receipt. They render approximately −115.123 mm at 2s, −2.640 mm at combined's endpoint, and 82.657 mm remaining for corner. Absolute endpoint drift and the source strict limit are shown together. All first-Walk strict FAIL / EXCESSIVE_DRIFT outcomes remain unchanged, alongside nominal/physical PASS. A small reference-frame error is not substituted for the local endpoint score.

## Time and frame integrity

All arms start their first Walk at original simulation 10s. The source 2s boundary is original simulation 12s, retained pose frame 240. These are original acquisition states, not an additional simulation step.

The exact source Walk completions differ. Their nearest retained frames are off −12 ms, combined +2 ms and corner −16 ms. Combined's nearest frame is already marked Turn; the UI preserves that captured identity while keeping first-Walk measurement, reference and commanded-heading axes fixed. Its Turn target cannot reset the displayed local error or fabricate a large Walk heading error. Formal endpoint metrics are separate from all nearest-frame readings. The Inspector shows both times and the signed sampling offset.

The state playback is 20Hz and is not continuous contact-force or corridor-safety evidence. Dashed strict limits are original endpoint guides; the browser does not rescore the curve. Shared playback does not claim bit-perfect simultaneous browser decoding: each arm reports its own exact presented frame, and paused event seeks align their explicit frame maps.

## Provenance and replay production

The source is `experiments/phase3a/residual_authority_feasibility_001`, original primary runs 01/05/06, with seed 0 and unchanged α=0.5. Original scientific code/protocol/case/policy and export hashes are verified. Run identity and probe identity are separately checked, because the source's legacy learned injection label does not identify a trained residual actor.

Original `poses.npz`, trace, decisions, per-run result, independent audit and summary are hash-bound by the new manifest. Inspector links reach these source files and their JSON/frame/decoded-line locators. Paired deltas list both source operands. The scientific actor is explicitly described as a deterministic bounded probe, with no new learned checkpoint.

The new renderer restores the saved qpos/qvel/ctrl/time in its own model/data and calls `mj_forward`; physics stepping is prohibited. The three clips contain 3,226 frames, rendered in 21.57s. All clips decode fully; representative frames passed visual checks. Each render receipt records zero `mj_step` calls, unchanged pose/velocity/control/time, source-state hashes and the exact frame map. There is no capture rerun, control callback, reward call or optimizer update in this Console task.

The original `vertical_slice_001` is unchanged. Its two replay runs were copied byte-for-byte into this new namespace, retaining their distinct derived-visualization provenance. Original scientific evidence, labels, thresholds, negative results and policy files were not edited. Only Console observer implementation and new derived display assets are changed.

## Validation and limitations

- 12 targeted builder/source-binding checks passed.
- 30 read-only server/provenance/transport checks passed.
- 8 frontend sample/time/frame checks passed, including first-Walk axes at a captured Turn frame.
- New server inventory: 58 derived files / 41 source files verified.
- Actual HTTP checks: three-arm catalog, original JSON identity, bound metrics/raw links and MP4 Range 206 passed.
- Actual browser checks: real three-way media decode, 2s seeking, advancing playback, each arm's completion, first-Walk/full-sequence toggle, old-slice selection, source Inspector and desktop/narrow layouts passed. Screenshots and browser receipt are under `console/qa/authority-*`.

The in-app browser refused direct navigation to the JSON API (`BLOCKED_BY_CLIENT`). The Inspector itself successfully fetches and displays the original result and provenance; the same HTTP endpoint is valid. This client navigation limitation is retained, not bypassed or represented as successful browser navigation.

No full scientific regression was run; this task does not change a scientific controller/evaluator or acquire new physics. New simulations, probes, PPO/optimizer updates, checkpoint writes, Jev and provider calls are all zero.

**Remaining blockers:** none for the requested mechanism replay. **Stopping reason:** the three retained arms, synchronized evidence views, original strict failures and provenance are observable and verified. No Phase 3A.5, training or additional control experiment follows this task.
