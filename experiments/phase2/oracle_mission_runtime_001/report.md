# Phase 2.0 — Mission IR + Deterministic Task Runtime

Protocol: `configs/experiments/oracle_mission_runtime_001.yaml`, SHA-256
`c551833bb56fff2edc61d0651233ec950b2f573da00789629f72003dd484865e`, frozen
in commit `ddb1367`. Corpus: `configs/missions/oracle_phase2_001.yaml`, SHA-256
`a39fd930e48fa00d88e96a6c228ecb68a6aed387695e7af23e130c7ceb8458e3`.
Baseline provenance: Phase 1.3 at `bea645f13b6af9ee27f902c310148d72fa69a204`.
The measured campaign ran at source commit
`ddb13670ffde02ab48d9fb07a1536dc80b45cff8`.

## 1. Verdict

**PASS** for the frozen Oracle corpus. The deterministic runtime validated,
capability-grounded, planned and executed all 20 valid structured missions
across H1/H3/H5/H8, and rejected all 15 negative missions with zero simulation
steps. This is a structured-IR baseline only: no natural language, LLM, Jev,
swarm, perception or manipulation component was used.

## 2. Baseline provenance

- Phase 1.3 frozen HEAD: `bea645f13b6af9ee27f902c310148d72fa69a204`.
- Current branch: `phase2.0/mission-runtime`.
- Final campaign source commit: `ddb13670ffde02ab48d9fb07a1536dc80b45cff8`.
- Locomotion policy SHA-256:
  `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`
  (unchanged).
- Phase 1.3 map hashes used by the grounder:
  - `risk_map_v1_3`: `8be4b36aa8e10a5e37807a56310925754ba65e21484978d9b1a2983169431dc2`
  - `boundary_comparison`: `372f3fa8a69d1f1ddf43e791d9b43946e0504e82172a95eb58d70aeceae62d11`
  - `capability_map_v1_3`: `c5266802997dc4fa1f8e604342f51a637c2d1d76f9ecc2a9b364a76312768d10`

## 3. Mission IR

Schema version `2.0.0`. Supported skills are exactly `stand`, `walk_forward`,
`turn`, and `stop`. Steps have stable IDs, typed parameters, optional
dependencies and a validated experiment-only execution-mode override.
Unknown fields, unknown skills, malformed parameters and path-unsafe IDs are
rejected before a simulation session is created.

```json
{
  "schema_version": "2.0.0",
  "mission_id": "mission-001",
  "steps": [
    {"id": "s1", "skill": "walk_forward", "parameters": {"distance_m": 8.0}},
    {"id": "s2", "skill": "turn", "parameters": {"angle_deg": 45.0},
     "depends_on": ["s1"]},
    {"id": "s3", "skill": "stop", "parameters": {}, "depends_on": ["s2"]}
  ]
}
```

## 4. Validator

The validator performs static legality checks only:

- schema version and path-safe mission ID;
- non-empty mission and maximum 32 steps;
- unique step IDs, known dependencies, no cycles or forward dependencies;
- finite numeric parameters, positive walk distance and non-zero turn angle;
- schema sanity limits for turn and stand, explicitly not capability claims;
- no unknown top-level, step or parameter fields.

Capability rejection is deliberately separate: a schema-valid 25 m walk is
accepted by the validator and then rejected by grounding as `CAPABILITY_UNKNOWN`.

## 5. Capability grounding

The grounder reads the frozen Phase 1.3
`risk_map_v1_3.json`, `boundary_comparison.json` and
`capability_map_v1_3.json`. It uses no interpolation or extrapolation and never
automatically segments a long walk.

Selection rule: discard HIGH/UNKNOWN; prefer LOW over MEDIUM; within the same
risk level use `heading_lateral > heading_only > open_loop`. The Phase 1.3
correction is explicitly walk-only, so `turn` and `stand` ground to
`open_loop` rather than wrapping an in-place skill in the walking frame.

Observed final grounding: 33 `heading_lateral` walk nodes (all requested walk
distances 4–12 m), 52 `open_loop` nodes (turn, stand, stop), 84 LOW nodes and
one MEDIUM node (the 12 m extension-distance walk). A 25 m walk is
`CAPABILITY_UNKNOWN`; a HIGH-only walk would be `CAPABILITY_REJECTED` and is
covered by the unit test rather than the frozen corpus.

## 6. Task graph and runtime

The runtime converts grounded steps into a real dependent-node graph with
states `PENDING`, `READY`, `RUNNING`, `SUCCESS`, `FAILED`, and `BLOCKED`.
Execution order is deterministic insertion order after dependency checks. A
failed node blocks all descendants and stops the mission; there is no retry,
replanning, recovery or alternative skill. Skill dispatch is a static
whitelist (`SKILL_REGISTRY`) with no dynamic imports or arbitrary class paths.

## 7. Oracle benchmark

All 20 valid missions completed all required nodes.

| Horizon | Missions | Successes | Failures | Mean completed nodes | Mean simulated time |
| --- | ---: | ---: | ---: | ---: | ---: |
| H1 | 5 | 5 | 0 | 1.0 | 6.372 s |
| H3 | 5 | 5 | 0 | 3.0 | 14.672 s |
| H5 | 5 | 5 | 0 | 5.0 | 29.512 s |
| H8 | 5 | 5 | 0 | 8.0 | 44.124 s |

Campaign totals: 20/20 mission successes, 85 skill invocations, 65 recorded
transitions, 236,698 simulation steps, 473.396 s simulated time and about 33 s
wall time on this machine.

## 8. Horizon degradation

No degradation was observed on the frozen corpus: every horizon had success
rate 1.0. This is a statement about five distinct deterministic templates per
horizon, not a statistical generalization claim. The simulator and controller
are deterministic, so repeated identical templates were used only for the
pilot determinism check, not as independent benchmark samples.

## 9. Rejection benchmark

All 15 negatives were rejected before any robot simulation step:

- 14 `VALIDATION_FAILURE`: unsupported skill, negative distance, zero/absurd
  turn, NaN/Inf, unknown field/parameter, unknown override, duplicate ID,
  unknown dependency, cycle, empty mission and schema mismatch.
- 1 `CAPABILITY_UNKNOWN`: 25 m walk beyond the recorded evidence envelope.

`zero_step_compliant=true` and `expected_failure_types_ok=true`. The
`CAPABILITY_REJECTED` branch is implemented and unit-tested, but the frozen
corpus does not include a HIGH-only mission.

## 10. Transition map

The final map contains 65 observed skill transitions across the corpus. Every
recorded transition had a successful next node:

| Transition | Executions | Next-node successes | Next-node failures |
| --- | ---: | ---: | ---: |
| `stand -> stop` | 2 | 2 | 0 |
| `stand -> walk_forward` | 6 | 6 | 0 |
| `stop -> walk_forward` | 2 | 2 | 0 |
| `turn -> stop` | 7 | 7 | 0 |
| `turn -> walk_forward` | 17 | 17 | 0 |
| `walk_forward -> stand` | 1 | 1 | 0 |
| `walk_forward -> stop` | 7 | 7 | 0 |
| `walk_forward -> turn` | 23 | 23 | 0 |

The transition map records previous/next skill, previous end state, next start
state, position and heading deltas, and controller-memory reset information.
`deterministic=true` is reported only where repeated execution of the same
mission template produced identical deltas; heterogeneous contexts are marked
`null` with an explanatory note.

## 11. Physical vs mission success

All 20 valid missions were both physical successes and mission successes:
physical = 20/20, mission = 20/20. All rejected missions remained physically
unexecuted and therefore had no robot step, no fall and no controller failure.
No physical success was used to override a missing required node.

## 12. Failure attribution

Valid-mission failure taxonomy is empty: there were zero skill failures,
timeouts, transition failures, invalid states or internal errors. Rejection
attribution was 14 `VALIDATION_FAILURE` and one `CAPABILITY_UNKNOWN`. The
unsupported-skill negative is classified as a parse/validation failure because
the IR schema rejects it before a runtime skill request can be created; the
`UNSUPPORTED_SKILL` taxonomy entry remains available for a future runtime path
that receives an unsupported request after parsing.

## 13. Viewer sanity check

A real MuJoCo Viewer run of
`h5-stand-walk4-turn45-walk4-stop` completed 5/5 nodes in one continuous
simulation: stand, walk 4 m, turn +45°, walk 4 m, stop. It reported 22.06 s
simulated time, 11,029 steps, 8.78 m path length and four transitions, with no
crash or fatal error. The camera tracked the pelvis and the next walk followed
the post-turn heading. A viewer capture is retained at
`cache/viewer_verify/track_frame_2.png`; viewer runs are observation-only and
are not benchmark evidence.

## 14. Tests

```
185 passed, 0 failed, 8 benign torch.jit.load FutureWarnings
```

The suite includes IR, validator, grounding, task graph, runtime, benchmark
aggregation, zero-step rejection, transition evidence, determinism and
historical regression coverage. The viewer CLI was additionally exercised in
headless and real-window modes.

## 15. Security

The Codex Security `security-diff-scan` plugin was **not available** in this
session, so no official security PASS is claimed. A manual static review of
the Phase 2.0 diff found no high/medium issue: only `yaml.safe_load`, no
`eval`/`exec`/`pickle`/shell execution, static skill whitelist, bounded
missions, SHA-256-pinned protocol/corpus/maps, no secret patterns, and
rejections provably execute zero simulation steps. Three low-severity hardening
notes from the review were fixed before the final campaign: repository
containment for viewer evidence, rejection of Win32 reserved/trailing-dot
mission IDs, and JSON-safe sanitization before the first runtime event log.

## 16. Negative findings

- The frozen corpus has 15 negatives rather than the suggested 8–12; this is
  still a small baseline but broader rejection coverage than the minimum.
- No HIGH-only mission is present in the frozen corpus, so actual
  `CAPABILITY_REJECTED` execution is not part of these final numbers.
- The H1/H3/H5/H8 rates are 100% for five distinct deterministic templates
  each; they do not establish a general success probability or a horizon
  scaling law.
- The pilot exposed and fixed two integration issues before freezing:
  walking-frame correction was being applied to in-place turn/stand, and the
  mission event log could retain stale lines on a re-run. The frozen protocol
  and regression tests cover both fixes.
- The viewer is an observation tool with real-time pacing; wall time and HUD
  timing are not benchmark metrics.

## 17. Git

- Branch: `phase2.0/mission-runtime`.
- Baseline: `bea645f13b6af9ee27f902c310148d72fa69a204`.
- Commits: `ddf5b1b` (IR + validator), `35eb883` (grounding + task graph +
  runtime), `ddb1367` (pilot + frozen protocol + corpus + benchmark CLI +
  viewer + fixes).
- Final results commit: the commit that adds this report, the frozen copies of
  protocol/corpus, benchmark summary and transition map.
- Push is unavailable from this machine (no credentials):
  `git push -u origin phase2.0/mission-runtime`.

## 18. Next gate

**Route A — Phase 2.1 Controlled Language Compiler** is the appropriate next
gate: the Oracle structured runtime is reliable on the frozen corpus, so a
language compiler can now be evaluated against this deterministic baseline.
Do not start Phase 2.1 from this report; it requires a separate approved
task. **Route B — Phase 2.0b Runtime Repair** is not indicated by the final
results, although the HIGH-only rejection path should be exercised in any
future corpus expansion.
