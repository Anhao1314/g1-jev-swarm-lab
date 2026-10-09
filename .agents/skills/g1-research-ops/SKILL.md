---
name: g1-research-ops
description: Load current G1 research state, route verification, record task costs, and close bounded engineering or experiment tasks in g1-jev-swarm-lab.
---

Run `.venv/Scripts/python.exe scripts/research_ops.py context` from the repo before broad discovery. It reads pinned state anchors, not experiment history. If STALE/BLOCKED, inspect the named source; do not infer a new verdict or silently refresh pins. From a chat rooted elsewhere, read the repo's AGENTS.md and invoke these files explicitly.

Run `scripts/research_ops.py plan --kind implementation --paths PATH...` (same Python). Choose mechanism for a controlled scientific intervention, claim for safety/generalization/held-out/baseline adoption/formal scientific PASS or FAIL. Reporting an unchanged retained FAIL in a Console is implementation. Declare claim scope with `--claim`; mixed work takes the higher tier. Read [policy](../../../ops/verification-policy.md) only for experiment/claim routing or unclear scope. Plans are advice, never authorization to acquire or thaw.

Use `--p1` for integrity repair and `--final-head` for the final identity check. Share `handoff --kind ... --paths ...` once with a bounded reviewer; do not re-read history or duplicate the owner's tests without new evidence. Independent P1/formal-claim reviews still inspect source/evidence themselves. A handoff is scope/context reuse, not an independent audit.

For a covered unit check, `run --bindings PATH... --gate unit --invocation-spec CHECK.json ...` records exact inputs, actual invocation identity and live environment metadata before/after. CHECK.json explicitly declares nonsecret literal argv with an absolute executable (schema nonsecret_test_invocation_v1). Actual command must match it. `reuse --receipt .research_ops/TASK.jsonl --check-id LABEL --paths PATH... --invocation-spec CHECK.json` rechecks the same invocation, latest attempt, inputs and raw log. Missing/old identity, changed selector/flags, failed prechecks/spawn or pending attempts require rerun. Complete coverage must be declared; uncertainty means rerun. `--gate protocol|independent|final-head` forbids reuse, even when hashes match. Never declare credential-bearing argv reusable.

Reference already sealed evidence with `evidence-ref --revision FULL_SHA --paths PATH...`; verify saved JSON with `evidence-ref --verify REF.json`. Git blob bytes are explicit and may differ from CRLF checkout bytes. New/untracked failures must first be retained normally. Do not replace scientific source manifests or any protocol's required raw closure with this management reference.

Execute only affected checks. `check console` consolidates retained visual inventory, source exports, provenance and reusable browser QA identities without rendering or physics. It does not replace tests for changed code or new browser QA for changed UI. `closeout --base BASE --paths PATH...` checks a scoped diff and reports other changes; it never stages or commits. Commit only explicit task paths; use one bounded push attempt and verify remote SHA, or report remote pending.

For measurement, wrap commands with `run --task ID --stage tests --label LABEL -- COMMAND...`. Use `mark --task ID --stage reasoning --seconds N --label LABEL` for measured planning intervals. Logs are local under `.research_ops/`; `summary --task ID` distinguishes unmeasured phases from zero. Do not invent unavailable tokens. See `ops/README.md` for exact syntax and session import. For a visual evidence change, load `$g1-visual-evidence`.

`begin --task ID --scope complete-task` at entry and `end --task ID` at closeout measure the task window; late starts use `observed-window`. `summary --session SANITIZED_SESSION.json` attaches actual parent-window usage, not child estimates. Measured command sums, task wall time, serialization bytes and model tokens are different metrics. Stop once mandatory evidence and delivery are complete.
