---
name: g1-research-ops
description: Load current G1 research state, route verification, record task costs, and close bounded engineering or experiment tasks in g1-jev-swarm-lab.
---

Run `.venv/Scripts/python.exe scripts/research_ops.py context` from the repo before broad discovery. It reads pinned state anchors, not experiment history. If STALE/BLOCKED, inspect the named source; do not infer a new verdict or silently refresh pins. From a chat rooted elsewhere, read the repo's AGENTS.md and invoke these files explicitly.

Run `scripts/research_ops.py plan --kind implementation --paths PATH...` (same Python). Choose mechanism for a controlled scientific intervention, claim for safety/generalization/held-out/baseline adoption/formal scientific PASS or FAIL. Reporting an unchanged retained FAIL in a Console is implementation. Declare claim scope with `--claim`; mixed work takes the higher tier. Read [policy](../../../ops/verification-policy.md) only for experiment/claim routing or unclear scope. Plans are advice, never authorization to acquire or thaw.

Execute only affected checks. `check console` consolidates retained visual inventory, source exports, provenance and reusable browser QA identities without rendering or physics. It does not replace tests for changed code or new browser QA for changed UI. `closeout --base BASE --paths PATH...` checks a scoped diff and reports other changes; it never stages or commits. Commit only explicit task paths; use one bounded push attempt and verify remote SHA, or report remote pending.

For measurement, wrap commands with `run --task ID --stage tests --label LABEL -- COMMAND...`. Use `mark --task ID --stage reasoning --seconds N --label LABEL` for measured planning intervals. Logs are local under `.research_ops/`; `summary --task ID` distinguishes unmeasured phases from zero. Do not invent unavailable tokens. See `ops/README.md` for exact syntax and session import. For a visual evidence change, load `$g1-visual-evidence`.
