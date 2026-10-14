# Reopen a completed Language-to-G1 mission

This additive, loopback-only viewer reopens a **previously captured** task after
the original Console process has stopped. It does not compile a new request,
restore a live Runtime, issue permission, render new frames, or dispatch a robot.
The current archive is the first Owner-authorized Stand2 → Walk4 → Stop mission.

## Start

From this repository, using the existing Python environment (with the retained
project dependencies), run:

```powershell
python -B console/language_v01/saved_results.py `
  --index D:\webcodex\mujoco-g1\evidence\language-first-real-6161176858\evidence-index.json `
  --index-sha256 c3e9a9b9726eaffd14bce07b025ea78c80cbbc5f78ab4811240d282504d99d48 `
  --request-id 5404feae6d3b449ab1e1dfbb53cdd387 `
  --port 8783
```

Open http://127.0.0.1:8783/. The same invocation after a process restart reopens
the same archived request/run; it does not create another request or consume a
grant. The index path and trusted SHA must be supplied explicitly. Never replace
the SHA with a newly calculated value just to make changed evidence pass.

The original indexed absolute paths must exist. A Git checkout alone does not
contain this Windows-local raw archive, model assets, or video. This version
does not claim portable archive restoration or public hosting. No model assets
are needed for viewing. Reusing the existing raw auditor imports NumPy indirectly;
Torch, MuJoCo, the physical backend and execution host are not imported.

## What is checked

Before startup and every result/video response, recheck the pinned index and
every indexed file; validate canonical request/preparation/Mission bindings,
the launch, completion, physical receipt, original result, raw counters, video
and pose byte identities, three process receipts and consumed request/comment.
The Owner source receipt hashes canonical JSON; the archive separately hashes
the formatted file bytes. Both checks remain in force.

The index is the operator's explicit trusted **evidence** anchor, not new
authority. This viewer does not independently certify arbitrary self-authored
archives or revalidate current GitHub permission. It never reads the mutable
execution-index to select a newer run. A changed/missing file fails closed;
there is no cached PASS fallback. Fixed GET routes serve only the result page,
its two static assets, `/api/result`, and `/video` (single byte ranges supported).
Write methods and execution endpoints are unavailable.

The page shows the original instruction, original skill metrics, a bound state
playback, consumed authorization and expandable provenance. Playback is not
live acquisition. Stop success is the original sliding-average criterion, not
immobility or a tested post-Stop Hold; local Walk error is not the world Mission
endpoint error. D011 and the general Language Runtime remain BLOCKED.

## Nonphysical validation

```powershell
$env:PYTHONPATH = "$PWD\src"
python -B -m pytest tests/test_language_saved_results.py -q
```

Tests use temporary synthetic archives and actual HTTP transport; they never
call a simulator or policy. Cover restored state, wrong request/index, missing
files, tampering after prior success, cross-binding errors, readonly methods,
Host/path restrictions, video ranges and a clean-process model-import guard.
Real archived bytes and desktop/narrow playback were additionally checked on
the Owner's device. See `validation/saved_results_20261014/REPORT.md` for receipts,
retained failures and limitations. Scientific scores and original execution
source remain unchanged.
