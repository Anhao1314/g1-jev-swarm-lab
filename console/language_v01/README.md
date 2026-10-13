# Language-to-G1 v0.1 — offline contract slice

**One Mission. Adaptive Execution. Verifiable Evidence.**

Enter a new controlled-Chinese instruction, inspect the real compiler's Mission
IR, original capability grounding, static Task Graph, source-bound request and
explicit authorization decision. Download its JSON and recheck binding. No
historical replay is attached to the request and no execution result is invented.

## Try locally

From this worktree, use the existing Windows environment (no model assets needed):

```powershell
& D:\work\g1-jev-swarm-lab\.venv\Scripts\python.exe -B console/language_v01/server.py --port 8780 --evidence-dir D:\work\mujoco\research-notes\language-v01-your-new-session
```

Open `http://127.0.0.1:8780/`. The evidence directory must be new. This is a
loopback development preview, not deployment. Stop with Ctrl+C. Every created
request is saved separately; restarting creates a new session and does not
restore or reinterpret prior requests as grants. No external network service,
language model, Torch, MuJoCo or policy asset is required by the preview.

Try `站立2秒，然后前进4米，最后停止`; also try `前进3米`, `往前走一点`,
and `拿起杯子`. Inputs are at most 512 characters. No free-form LLM fallback.

## Existing components reused

- `g1swarm.language.compiler.LanguageCompiler`: controlled Chinese, no model call.
- Mission IR and MissionValidator: original types, parameters and dependency rules.
- CapabilityGrounder: original Phase 1.3 tables and Phase 2 frozen historical
  limits. No default invented support, interpolation, segmentation or new risk map.
- TaskGraph: static PENDING nodes only; no refresh, mark-running or executor call.
- Research Console presentation conventions: separate source, proposal, evidence,
  and execution status. Existing Console server and media remain unchanged.

`src/g1swarm/language_v01/sources.json` pins 118 retained source/evidence files
to the inherited baseline. Service checks them before generation and rechecking.
An immutable canonical byte record binds original/normalized Chinese, complete
Mission, grounding, request/session context, source hashes and authorization
decision. Returned dictionaries cannot mutate stored records. The complete JSON
except its outer `contract_sha256` field is hashed with UTF-8, sorted keys,
compact separators, ensure_ascii=False and allow_nan=False. This is integrity
binding in a trusted local process, **not a signature or execution credential**.

All authorization results remain DENY: Language Runtime and D011 BLOCKED,
Owner authorization absent, live state not observed. Client fields claiming
Owner identity, approved status or TEST_ONLY principal are rejected. There is
no execute/approve endpoint or activation switch, and no grant issuer is built.
Test identities from M2.3 are deliberately not repurposed as product authority.

## Validation

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) src
& D:\work\g1-jev-swarm-lab\.venv\Scripts\python.exe -B -m pytest tests/test_language_v01.py -q
node --test console/language_v01/web/app.test.js
```

Fifteen Python tests cover actual compiler/grounder/graph, negative commands,
complete binding, mutation/replay isolation, source drift, real localhost HTTP,
forged claims and absent execution routes. A clean-process sentinel forbids
Torch/MuJoCo imports and simulator/controller/session/executor invocation. Seven
JS checks cover edit/in-flight isolation, rendering safety and input limits.
Actual browser QA covers success/ambiguous/unsupported/unknown capability,
binding DENY, JSON download, 390-pixel layout and console errors.

Known bounded limitations: capability support is historical and per skill, not
whole-Mission reliability or live-state qualification. Source hashes are not
owner authentication. Session storage is intentionally bounded to 256 requests.
No new physical state or motion video exists. The inherited comprehensive old
Console check requires motion.pt, absent in this isolated worktree; that blocker
is retained and does not justify installing assets or generating fake playback.

## Smallest next independently authorized demonstration

First review a **narrow controlled-grammar release contract** and its production
entry integration, preserving broad Language Runtime/D011 BLOCKED. An interface
confirmation or this JSON alone must never lift the gate. A new reviewed exact
execution source/readiness must bind the approved canonical Mission, evidence
maps, model/environment, session and fresh physical eligibility check.

Then request one Owner-authorized MuJoCo run of the same new command
`站立2秒，然后前进4米，最后停止`, seed 0, original policy/controller/scoring,
no training, tuning or extra scenarios. A candidate ceiling derived from existing
skill limits is 2 s + 24 s + 4 s = 30 simulated seconds, 15000 native steps at
0.002 s, 120 wall seconds, once without retry. The exact budget must also include
initialization/cleanup in the separately frozen adapter; any additional physical
step requires explicit review, not an implicit allowance.

Fail closed on source/authorization/state mismatch. Task or physical failure is
retained; freeze/exit the simulation rather than inventing an unapproved recovery.
Ending simulation is not proof of physical stopping. Save that request's actual
commands, task transitions, raw state trajectory, unchanged strict/physical
scores and source-bound visualization. Input, authorized canonical plan, executed
plan and returned evidence must agree. This proposal is **not acquisition-ready
and not permission to run**; no such adapter or release is enabled in v0.1.
