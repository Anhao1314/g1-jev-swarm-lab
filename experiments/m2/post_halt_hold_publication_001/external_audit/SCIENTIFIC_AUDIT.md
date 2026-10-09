# M2.5A Final Independent Scientific Audit

**Scientific Audit Verdict: CONFIRMED_BOUNDED_HOLD_QUALIFICATION_ONLY.**

PR14 frozen HEAD d7fcb76b1acabd166f9c279d75e4a6a53783e979 and PR17 evidence HEAD d0a04f46ac05f57abb85470905f021b139d485cd independently matched remote PR refs. No merge, baseline promotion, new physics, inference, training, tuning, or frozen evidence changes occurred. This audit is separately derived outside every repository. Existing earlier independent audit files were not used.

## Independent result, established before comparison

Only frozen protocol/design plus restored native qpos/qvel and acquisition witnesses were used. independent_result_before_comparison.json was written before reading the main report. Independent scientific subagent independently reached the same limited interpretation without reading that report.

| Cell | First Stop crossing step/time within Stop | Max 1000 rolling means m/s | Endpoint m/s | XY path m | Result |
|---|---:|---:|---:|---:|---|
| Seen failure/Halt | 671 / 1.342s | 0.099604884 | 0.086390810 | 0.135574498 | Bounded PASS |
| Turn45 failure/Halt | 658 / 1.316s | 0.099437391 | 0.090219608 | 0.136287493 | Bounded PASS |
| Normal Stop | 500 / 1.000s | 0.078349090 | 0.077928123 | 0.141010946 | Bounded PASS |

Crossing absolute simulation times: 14.278s / 16.532s / 11.982s. First means: 0.0999695815 / 0.0998160573 / 0.0706362819. Immediately prior eligible failure-Halt windows were 0.1003366374 / 0.1002011299, proving no earlier qualifying crossing. Normal Stop has only the first 500-sample eligible window. Stop speeds were matched directly against native qvel and terminal sample history, not accepted from saved metrics.

Each Hold includes exactly 1000 native post-step states with timestep0.002s, seeded by exactly the final500 Stop post-step speeds. Every one of the 3000 means was explicitly recomputed; path includes entry→firststep and all subsequent999 segments. All three finite/standing/no-fall gates pass. Minimum base height:0.773152 /0.773013 /0.773250m; max tilt:3.801895 /3.803956 /3.741391deg. The quaternion tilt formula and frozen0.45m/65deg fall and0.55m/30deg standing criteria were read from pinned code, without importing simulation.

Control continuity: Stop skill-return, terminal and Hold pre-firststep snapshots match exactly in recorded physical/control state and counters; parent last native state matches entry. Same recorded object IDs, no qualifying→Hold reset/dispatch delta, exactly1000 counter increments and all1000 commandszero in each cell. Hidden recurrent bytes were not captured: continuity is witnessed interface/state continuity, not direct hidden-memory byte proof. Whole-campaign reset counters include initialization/preceding skills and must not be mistaken for Hold resets.

## Source and evidence integrity

ZIP SHA256:780164d135b87975be8034fa6bc9db6ef8534f0041e9e41ef03a4494dfca876a, compressed14,873,025bytes. All43 original members, total64,962,438bytes, match ZIP member bytes, sizes and raw_manifest hashes; restored copies match too. Full per-file SHA table is raw_hash_verification.json. Protocol SHA256:ee2bb3746da537e843c63880d2130d5e1d488494ceeb8775f3273a19e248371a.

Independent provenance audit verified freeze/source/source-binding manifests and three historical parent archives/member bindings. The254 execution sources require three distinct categories:78 Git raw-byte matches;85 exactly explained by LF→CRLF checkout conversion;91 unversioned official assets matching present local bytes. Git blob provenance is not identical to execution checkout provenance. Detailed hashes and limitations are retained in integrity_agent.json and line_endings_integrity_agent.json. Dependency/environment/install/preflight witnesses are retained acquisition evidence; this offline audit did not rerun environment preflight, authenticate historical machine execution independently or reconstruct hidden policy memory.

## Differences against main PASS report

No numeric discrepancy: firstcrossing, speed/path/netdistance/peak match within1e-12; all3000 rolling means match exactly (maximum difference0). Main report's bounded title and explicit immobility/safety/authorization/reliability exclusions are appropriate; no material scientific overclaim found in that report.

Additional descriptive caution: instantaneous speed exceeded0.1m/s at198 /209 /248 Hold samples; peak0.144113 /0.145732 /0.142378m/s. Maximum joint velocity magnitude5.435620 /5.691045 /5.447257rad/s. This is ongoing active balancing/movement, not zero-motion. These are descriptive findings and do not alter frozen gate scoring.

The first two maximum Hold means are only0.000395116 /0.000562609m/s below threshold. These margins describe the observed traces, not robustness under perturbation. Normal Stop is unmatched control; comparing it causally to failure-Halt is invalid. Two seen deterministic seed0 states and one control, each one two-second rollout, provide no general reliability estimate. Finite/standing/no-fall are sampled physical proxies, not complete safety. Neither Halt nor Hold authorizes a new task, recovers the failed parent mission, resolves D011, or promotes M2.4 INCONCLUSIVE. No hypothesis about longer horizons or hardware is tested.

## Reproducibility and stop

Use standard Python (no project imports required):

```powershell
$py='D:/work/g1-jev-swarm-lab/.venv/Scripts/python.exe'
$audit='D:/work/g1-m25a-final-audit-20261009'
& $py "$audit/independent_recompute_v0.py"
& $py "$audit/compare_after_verdict.py"
& $py "$audit/integrity_agent.py"
& $py "$audit/continuity_integrity_agent.py"
```

restore_pinned.py --repo D:/work/g1-jev-swarm-lab --output <new-directory> restores verified bytes without overwriting; copy this audit's recompute script to that fresh directory and run it. Source-integrity scripts retain their pinned locators. Per-cell CSV exports contain all1000 individual recomputed windows. All outputs are separate derived assets; raw input bytes remain untouched.

Remaining blockers: none for this bounded offline verdict; production safety, general reliability and task authorization remain unproven. Stopping reason: protocol-derived verdict, complete hash/trajectory recomputation and main-report comparison are complete. No PR merge, scientific baseline promotion or next experiment is authorized.
