# Tests

Deterministic boundary tests for the Phase 1 runtime. No test downloads data:
model-dependent tests skip when the pinned assets are not present in
`third_party/` (fetch them with `scripts/fetch_g1_models.ps1`).

| File | Covers |
| --- | --- |
| `test_robot_state.py` | creation, required fields, serialization round-trip, non-finite detection |
| `test_skills.py` | `SkillResult` status/success semantics, router valid / unavailable / precondition / invalid requests |
| `test_simulation_adapter.py` | model load, dimensions, repeatable reset, step advances time, invalid control rejected, closed simulation rejected |
| `test_control.py` | official policy wrapper produces finite torques and resets its recurrence state |
| `test_evidence.py` | manifest field completeness and evidence bundle layout |

Run with `python -m pytest -q` from the repository root (see README).
