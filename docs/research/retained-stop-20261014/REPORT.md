# Stop success: measured evidence coverage, not a Hold promise

**Verdict: retained-data diagnostic complete. Original Stop SUCCESS preserved;
post-success Hold and adaptive handoff qualification remain NOT_ESTABLISHED.**

I selected the gap between a user's stopping intent and the measured motion
postcondition. The saved-result product already exists in Draft PR #38. A portable
archive would improve access, but would not answer what another task can assume
after Stop. This priority is my engineering judgment; it is not a measured ranking
of all project obstacles. The broad language Runtime remains blocked independently.

The controlled grammar accepts `停止`, `停下`, and `立即停止` as the same Stop.
The first real request used `停止`, not an explicit Hold demand. Thus this analysis
does **not** assert that its original language contract failed. It makes the
existing success envelope and the missing future observations computable.

## What changed

Added a stdlib-only CLI, `scripts/analyze_retained_stop.py`, and 12 focused tests.
The CLI accepts only the explicitly pinned archive profile for this run. It
hash-checks all 49 indexed files, four relevant source contracts, the request /
preparation / Mission / physical-result bindings, native and policy sequences,
and agreement between native post-state and the state returned to each skill.
It computes from the same bytes that it verified. It never imports execution code.
Original evaluators, parser, thresholds, Runtime, authority and evidence are untouched.

The new capability is an executable explanation of a retained result: which
samples support its stopping criterion and how much evidence exists afterwards.
This is an offline operator tool, not new natural-language coverage, actuation,
Hold control, product deployment, or automatic adaptation.

## Verified results

Source run `e709447a946f45e1b91b25942319e178`, request
`5404feae6d3b449ab1e1dfbb53cdd387`, C_exec
`2faa98481e64b7a0289dff94884a8f7672902177`.
Full pins and unchanged original outcome are in [analysis.json](analysis.json).

| Observed quantity | Result |
| --- | --- |
| Original native steps / policy calls | 6030 / 603 |
| Stop samples / duration | 685 / 1.37 s |
| Full one-second mean windows observed | 186 |
| Windows meeting original <= 0.1 m/s mean | 1, at the final sample |
| Final / preceding window mean | 0.09991565538953033 / 0.10003703586394586 m/s |
| Final instantaneous speed | 0.10087112741017572 m/s |
| Final window samples above 0.1 m/s | 249 / 500 (49.8%) |
| Longest consecutive <= 0.1 m/s sample span in that window | 128 samples, 0.254 s |
| Path between first and last post samples in that window | 0.0995937477 m |
| Samples / observed time after success | 0 / 0 s |

The 500-sample criterion uses 0.002 s native steps. The first-to-last timestamp
span is 0.998 s (499 intervals); the criterion itself is unchanged. Consecutive
sample spans do not establish continuous-time guarantees. Instantaneous
exceedances describe variation within a valid mean window; they are not a new
failure criterion. There are no observations here that predict future Hold success
or failure. The record ends at the first passing mean, so temporal persistence is
unmeasured by this capture.

## Reproduce and audit

From the repository root with Python 3.11+, no installed dependencies required:

```powershell
.venv/Scripts/python.exe -B scripts/analyze_retained_stop.py --index D:/webcodex/mujoco-g1/evidence/language-first-real-6161176858/evidence-index.json
.venv/Scripts/python.exe -B -m unittest discover -s tests -p test_retained_stop_analysis.py -v
.venv/Scripts/python.exe -B docs/research/retained-stop-20261014/independent_audit.py
```

Tests: **12 passed**, final retained [test output](tests.txt). They include mixed
fast/slow samples with a passing mean, actual later observations, no crossing,
sample gaps, NaN/Inf/negative inputs, duplicate/missing counters, mismatched states,
wrong index and forbidden-import interception. The actual original archive also
completed under a fresh-process import guard rejecting `numpy`, `torch`, `mujoco`
and `g1swarm`; no robot dependencies were loaded. All 49 original hashes verified
again at final acceptance. Seven numerical fields were compared with the separate
audit, agreeing within 1e-12.

A separate agent independently calculated from raw native qvel and the ledger,
then reviewed the analyzer. Its [script](independent_audit.py),
[numeric receipt](independent-audit.json) and [review](independent-audit.md) are
retained. It also verified original source content against C_exec Git blobs,
recording raw CRLF versus Git LF hashes rather than changing archived bytes.

Local raw bytes remain required; this is not a portable evidence publication.
Synthetic tests run from this checkout alone. Browser QA and full physics /
regression suites were not run: no UI or execution contract changed. Research Ops
recorded three test commands totaling 2.3906 s; reasoning, audit and total wall time
are not fully measured, and token costs are unavailable.

## Failures and environment limitations retained

- Initial repo `.venv/Scripts/python.exe` was absent. The old main worktree's venv
  launcher also failed because its referenced Python 3.11.9 was missing. `py -0p`
  reported no registered Python. No dependency installation or download followed.
- Used the already installed Blender-bundled Python **as a Python interpreter**
  to create this repo's isolated `.venv` with `venv --without-pip` (Python 3.11.15).
  No Blender process, renderer, model, simulator or policy was invoked.
- `rg` was unavailable; bounded PowerShell reads replaced it. The first guessed
  `skills/stop.py` lookup failed; StopSkill is in `skills/basic.py`.
- The independent audit's first Git-byte comparison failed on CRLF versus LF.
  Raw archived hash passed; normalized source content matched the exact Git blob.
  This was an audit representation mismatch, not a physical result or erased FAIL.
- No test failures occurred in either of the 12-test runs. Historical negative
  evidence, including earlier environment / asset failures, is not relabeled.
- Local `git add` failed with `index.lock: Permission denied`: this worktree's
  Git metadata resides outside the writable root. No permission change or write
  to the original repository followed. A single connected GitHub `create_tree`
  attempt returned `MCP tool call requires approval, but approval policy is never`.
  No remote commit, branch write, push or Draft PR was created. Local files remain
  untracked in this worktree; the completed work is also retained as a patch.

## Boundary and stopping decision

Engineering inference: a future adaptive transition needs an explicit observed
handoff condition, or an explicit statement that first-mean Stop is its only
precondition. Do not silently reinterpret the current Stop as stable rest.
Designing that distinction can be nonphysical; actually measuring continued Hold,
reacquiring trajectories, running a next Mission, policy inference, training,
changing thresholds, unblocking D011 or merging main needs separate authorization.

The bounded question is answered with independent arithmetic and tests, so stop.
This work performed zero new native steps, zero policy calls and no training.
The consumed one-time authorization remains consumed. This research branch is
based on origin/main `4e2a51b`, not local main `c2fd276`, and does not import or merge
the pending product/governance branches. See the task closeout for remote delivery.
