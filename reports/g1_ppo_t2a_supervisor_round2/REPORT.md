# T2a Supervisor Integration Repair Round 2

Verdict: **BLOCKED_WITH_EXACT_EVIDENCE**. This is an archived, rejected engineering attempt; do not use it for acquisition or merge it as an accepted fix.

Base Draft PR31: `f7398a6102b28ddb9ac36471ebce761de82e4ab1`. Functional attempt commit: `050a1f690cd1e49600f353d4ab3e9328ffa73b3a`. Only `run.py`, `supervision.py`, and `tests/test_residual_rl_t2a_supervision.py` changed (272 insertions,272 deletions). Ordinary source edits were produced by the actual DeepSeek Codex CLI; Main reviewed/tested and committed them without substituting implementation. The test write was interrupted and intentionally preserved rather than silently completed or reverted.

## Actual outcome

Missing subprocess import fixed. A Linux SIGALRM deadline, private preexec PID channel and cleanup diagnostics were attempted. They do **not** establish the required complete595/600 lifecycle. Scientific execute body, comparator, protocol, historical watchdog, controller, thresholds, models and checkpoints were not modified. Original Linux repo and PR31 worktree remain clean.

Final Main direct command (Linux CPU environment):
```text
PYTHONPATH=/home/g1rl/g1-rl/worktrees/t2a-supervisor-repair-round2/src PYTHONDONTWRITEBYTECODE=1 /home/g1rl/g1-rl/venvs/rl/bin/python -B -m pytest -p no:cacheprovider tests/test_residual_rl_t2a.py tests/test_residual_rl_t2a_supervision.py -q
```
**76 passed /8 failed /84 collected**, native exit1,19.688 seconds. Historical baseline **80 passed /18 failed /98 collected** remains retained. Fourteen cases were lost in the incomplete test rewrite; lower failure count is not a regression gain. All eight remaining failures report `delegation_transfer_timeout`; positive paths fail before successful execution. No retries of this final suite or third DeepSeek implementation were performed.

## Exact blockers

1. First execution-chain defect: supervision.py379-383 takes the readable result of `select.select([], [fd], [], remaining)` as ready. A writable pipe is therefore incorrectly reported as transfer timeout. This pre-existing defect was exposed after fixing the import.
2. run.py130 mkdir/once.claim and supervision.py551-553 setup are outside the interrupt scope. Cleanup609 and receipt623-626 also lack total-deadline interruption;595/600 constants alone are insufficient.
3. run.py137 ignores cleanup_complete when deciding exit0; failed descendant cleanup can be reported as successful Supervisor exit.
4. Ownership publication at supervision.py436-441 can itself be interrupted; unknown PID is treated as complete cleanup at451-454. No interrupted-after-spawn proof exists.
5. Required actual canonical Supervisor→Worker→post-guard synthetic positive was not implemented. Existing positives use the prior expected_parent_argv seam and injected verifier/Worker and fail.
6. Replay/single-use, stale, spawn/identity/transfer fault, watchdog descendant, normal-exit cleanup and preservation cases were removed by the partial write. They are preserved in PR31 history but are absent from the attempted final suite. Timing metadata also starts from supervise rather than the earlier Main start.

## Acceptance matrix

| Question | Actual evidence |
|---|---|
| Direct Worker without Supervisor context | Rejected; poison backend import remains absent |
| Copied CLI/environment flags | Rejected; no new bypass entry introduced |
| Old delegation/replay | Existing guards unchanged; final replay/stale regression coverage removed, NOT_PROVEN in this attempt |
| Wrong root/manifest/HEAD/protocol | Actual Readiness/HEAD preflight negatives pass; delegated mismatch helper tests fail at transfer before intended binding rejection |
| Supervisor normal/error/timeout descendant cleanup | NOT_QUALIFIED; required cases absent and ownership/false-success findings remain |
| Full start→spawn→transfer→verify→execution→reap deadline | NOT_QUALIFIED;595/600 scientific values unchanged |
| Genuine canonical positive | NOT_PROVEN; not implemented |

Both native Sentinel reviews rejected readiness. Atlas remained read-only. Main independently retained all8 process receipts and77 synthetic raw files; recorded owned Worker PIDs were absent at closeout. This observed cleanup snapshot does not prove the missing timeout/descendant scenarios.

## Frozen identities and evidence

SOURCE_ATTEMPT_MANIFEST SHA256: `e49087320375ef8eca24f7e471d105a2477c59e8ef437fb6e2b694956f18920c`. This manifest is **not a Source/Readiness qualification**. No qualified C_exec or new Readiness is issued. Old PR29 Readiness `cf0d476290a9e7bb5740f8503fc30fd29a3b1d309bf954fb666517f11564aadc` does not apply to changed source.

Unchanged protocol SHA256: `1181c673cf34c0886bedd68351ce6ee2baef25999097b7150a590bfba7d2e77c`. Comparator `457d4edc8c457246cd9247eddff14e8ef3606ffb2b0b370a103b514bc9271290`; historical watchdog `89472231a30e1e072f586803d39e0067319e23f805d8d993afbd5b7ba7158cde`.

Archive `engineering-evidence.tar.gz`: `6382b465f6de2c11f54da25c4dcf3edcc53afdfdb141474725a56e2d79419537`, 95 members. Verify archive hash, extract to empty directory, then verify every member against archive-receipt.json. Original JSONL includes actual CLI/tool executions; derived duplicate command lists and local credential plumbing drivers are intentionally omitted. Main test receipt is bound to exact invocation and source attempt. Historical PR31 failures remain in their original namespace.

Initial CLI completed499.234s with a design only; Main coordination failed to deliver review before120s gate. Final repair stopped600.375s; raw logs preserve Windows UNC patch failures, Windows206 command-length failure and two connection retry events. Initial usage:1025129 input/990976 cached/61981 output/54663 reasoning. Final usage and actual billed cost NOT_REPORTED; no efficiency advantage measured. Maximum reasoning used. Global Codex configuration bytes unchanged; an owned X: mapping created by CLI was verified and removed.

## Scientific boundary and stopping

MuJoCo native steps **0**, policy inference **0**, optimizer updates **0**, GPU execution **0**. Hash-only reuse of30 previously verified assets; no model/checkpoint load. No Owner authorization request, B0/C0/C256 execution, training, merge, main modification or scientific-pointer update.

Stopped after the one implementation/design invocation and one final repair. Remaining repair needs a separately authorized engineering round addressing the transfer defect, complete lifecycle/ownership and retained genuine positive/negative tests. This report does not request acquisition authorization.
