# Research Ops v0.1

From the **g1-jev-swarm-lab** repo, begin with:

```powershell
.venv/Scripts/python.exe scripts/research_ops.py context
.venv/Scripts/python.exe scripts/research_ops.py plan --kind implementation --paths console/web/app.js
```

For retained visual evidence: `... research_ops.py check console`. For scoped Git
review: `... research_ops.py closeout --base HEAD --paths ops scripts/research_ops.py`.
These commands are read-only. They neither stage/commit nor acquire/render.
`closeout ... --retained-experiment` additionally validates/reuses the current
Phase3A.4d frozen protocol, retained artifact/export hashes, decision/blocker and
existing independent-review locators. It is explicitly a retained-schema adapter,
not a new experiment completion certificate or independent audit. New experiments
must use their own protocol-specific closeout; v0.1 does not generalize all schemas.
Use `.agents/skills/g1-research-ops` and, when needed, `g1-visual-evidence`.
Repo skill discovery works when Codex starts inside this repository. A chat
rooted in D:/work/mujoco must read this repo's AGENTS/skill explicitly or open a
chat here; this upgrade does not install user-global skills or change app settings.

`ops/state.json` stores reviewed source pointers, SHA-256 anchors and scope.
`context` generates branch/head/verdict/blocker/test commands at invocation;
it rejects changed/missing anchors and newer research files relative to the
selection commit. It never picks a decision by mtime or rewrites a verdict.
It reads a few small anchors and Git paths, not every experiment. Selection
changes need an authorized reviewed pointer update; a new scientific namespace
marks it stale, including uncommitted tracked changes. It is an embodied-line
entry, not an index of independently checked-out language-safety branches.

Task tiers and mandatory escalation are in [verification-policy.md](verification-policy.md).
Unknown paths need scope review. Scientific intent is explicit (`--kind claim`
or `--claim safety` etc.); path matching alone cannot identify prose claims.

For command timing (output retained in ignored `.research_ops/`):

```powershell
.venv/Scripts/python.exe scripts/research_ops.py run --task console-fix --stage tests --label console-tests -- .venv/Scripts/python.exe -m pytest console/tests/test_authority_replay.py -q
.venv/Scripts/python.exe scripts/research_ops.py mark --task console-fix --stage reasoning --seconds 30 --label measured-planning
.venv/Scripts/python.exe scripts/research_ops.py summary --task console-fix
```

Stages: context, reasoning, implementation, experiment, tests, browser_qa,
audit, git_closeout. Use measured intervals; omitted stages show unmeasured,
never zero. Labels must contain no credentials. Commands/arguments are not
copied into telemetry; command output stays local and may require redaction.
The wrapper records exit codes, output identities and elapsed seconds, not
model reasoning tokens or total task wall time. It adds overhead; use it at
phase boundaries, not for every tiny file read. It runs only your explicit command.

Optional sanitized retrospective import:

```powershell
.venv/Scripts/python.exe scripts/research_ops_session.py ROLLOUT.jsonl --start ORDINAL --end ORDINAL --output NEW.json
```

It extracts per-response usage records and parent call counts, retains ordinal
locators and source SHA, excludes raw messages and external paths. Stage/read
counts are explicitly heuristic/lower-bound. Review window selection before
using results. Unsupported/missing token telemetry stays unavailable.

Closeout: inspect explicit paths, run only required checks, commit explicit paths,
one bounded push (e.g. Git http.lowSpeedTime=30), then check remote SHA. A failed
network attempt is REMOTE_PENDING; do not spend more reasoning on repeated polls.
Do not omit mandatory delivery verification to improve benchmark numbers.
