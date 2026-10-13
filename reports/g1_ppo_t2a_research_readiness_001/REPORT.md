# T2a evidence-driven research readiness

**READY_FOR_OWNER_T2A_ACQUISITION** — nonphysical readiness only, not acquisition authority.

The experiment remains B0 / C0 / C256 on the frozen seen 4m case, seed 7. This work establishes an auditable entry to that comparison; **PIPELINE_PASS / LEARNING_GAIN_NOT_PROVEN** remains the scientific position. No result for PPO learning gain is claimed.

## Path selection and actual blocker

The retained candidate had 19 passing and 15 failing supervision cases. It conflated the input Readiness with its output execution Manifest, so even a legitimate Worker failed the real verification path. Cleanup also treated an unreaped zombie as completed cleanup. The original dirty worktree and scratch file were snapshotted and remain byte-identical.

We retained the simple single forked Worker and reused T1b's TERM→250ms→KILL→wait pattern. Reusing the entire T1b watchdog would not provide normal/crash escaped-descendant cleanup or full startup budgeting. A new delegation/authentication service adds no value to this trusted serial experiment. This selection follows the [project charter](https://github.com/Anhao1314/life-finds-a-way/blob/main/CHARTER.md): discriminate the actual blocker before choosing a route.

Changes are confined to run.py, supervision.py and their supervision tests. Input Readiness and output Manifest are distinct. The launcher requires a dedicated main-thread process with one native thread and no pre-existing child. Linux subreaper setup must succeed. Child cleanup includes zombie reaping; startup, verification, execution, cleanup and receipt share the entry-anchored 595/600-second limits. Cleanup failure remains failure even when emergency reap succeeds. Receipt failure emits a failure record to captured stderr and cannot produce launcher success.

There is no pipe handshake, token service, new dependency, new controller or authority framework. The existing small inherited launch record is a process-binding record, not an Owner credential. Seven focused regression cases were added; all 34 retained supervision cases and 65 classifier cases remain. Exact before/after line counts are in PUBLICATION_CHECKPOINT.json; no efficiency advantage is inferred from line count.

## Frozen execution identity

Use **C_exec**, not this documentation PR's final HEAD, for any subsequently authorized execution:

- C_exec: `81f9fa9c13c167f7163dfb695d419f4be27bb773`
- Execution tree: `/home/g1rl/g1-rl/worktrees/t2a-research-readiness-20261013` (clean)
- Git tree: `ba8fae0f3ab29498ced1160fa2ba19b431dd7fcc`
- Source SHA256: `a854a022224c567dd7a25dba04ecfc756a350931d0fc3a20705098c10821f185`
- Readiness SHA256: `1c78628fa49e8cfc535366939cc528abeb8d88b74d1a22ea5d164f7c1c3790b3`
- Protocol SHA256: `1181c673cf34c0886bedd68351ce6ee2baef25999097b7150a590bfba7d2e77c`

SOURCE.json binds 177 files including the 30 official assets used by this RL configuration. Readiness additionally binds 21,121 installed files, 30 package versions, the existing CPU Python executable and both unchanged checkpoint hashes. Full original Readiness bytes are in archive `task/READINESS.json`. No model/checkpoint was loaded; hashes only. **PR #29's old Readiness is inapplicable** and remains untouched.

## Real verification and retained failures

| Attempt | Result | Interpretation |
|---|---|---|
| initial harness | 1 pass / 33 errors | Missing parent for pytest basetemp; retained, not counted as source failure |
| original candidate baseline | 19 pass / 15 fail | Reproduced path-binding and cleanup defects |
| first patched attempt | 10 pass / 29 fail | Shared conftest creates 10 native BLAS threads; dedicated launcher correctly refuses |
| isolated standard-library suite | 39 pass | Same production guard, no shared conftest |
| audit correction | 41 pass + 65 pass | Outer cleanup exception/stall retention added |
| final LF C_exec | **41/41 + 65/65 pass** | 13.22s + 0.29s pytest time, native exit 0 |
| complete actual-root entry | **1 positive + 5 negative pass** | Full actual source/assets/environment; original verify twice; post-guard synthetic body only |

The final complete entry runs `main → original verify → fork Worker → original verify → synthetic body`. NumPy, Torch and MuJoCo are poisoned, making accidental heavy imports fail before any scientific execution. The real parent/Worker guard is not patched. Negative complete-entry cases reject wrong HEAD, source digest, protocol digest, Readiness digest and absent operator confirmation. Supervision tests additionally exercise direct Worker calls, copied old CLI flags, changed Manifest, replay, crash, signal, timeout, escaped descendants, unrelated child protection and stalled/throwing cleanup/receipt paths.

The initial integrity helper also failed: it incorrectly expected the old PR29 Readiness to already contain the inherited PR30 classifier repair. The corrected helper checks those two inherited classifier files against exact PR32 Git blobs; they were not changed. Both helper versions and failure excerpt are retained. This audit assumption correction did not alter scientific code.

The raw logs, invocation arguments, source hashes, synthetic process receipts and initial dirty-source snapshot are in the archive. EVIDENCE_MANIFEST.json binds every retained member; ARCHIVE_RESTORE_RECEIPT.json records fresh-directory extraction and byte revalidation. Temporary fixture Git databases, bytecode and convenience symlinks are excluded explicitly. Historical PR31/32 records remain in Git ancestry and are not copied again.

## Reproduction without physics

At the clean C_exec worktree, run these as **separate** processes with the existing environment:

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 /home/g1rl/g1-rl/venvs/rl/bin/python -B -m pytest --noconftest -p no:cacheprovider tests/test_residual_rl_t2a_supervision.py -q
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 /home/g1rl/g1-rl/venvs/rl/bin/python -B -m pytest --noconftest -p no:cacheprovider tests/test_residual_rl_t2a.py -q
```

The first suite needs its local canonical fixture and hashes the retained T1b checkpoints; it does not load them. `--noconftest` avoids unrelated project imports creating native threads. Running both suites in one Python process can import numerical libraries before fork and is not the qualified invocation. This is not a guard bypass. The complete actual-root driver, poison modules, input variants, native output and process receipt are preserved in `synthetic-raw/complete-preflight/`. It always supplies a synthetic post-guard executor; do not use the unmodified production CLI for reproduction without a new Owner acquisition decision.

Archive verification is read-only: verify its SHA against EVIDENCE_MANIFEST.json, extract to a new directory, then recompute each member SHA. Source and Readiness exact hashes above bind those extracted documents. The source execution tree must stay at C_exec; publication-only descendants are not interchangeable execution identities.

## Independent review, provenance and limits

FINAL_INDEPENDENT_REVIEW.md contains the native independent auditor's full final review. The auditor independently read Git status/tree/diff, recomputed freeze/source hashes and checked final logs and the complete-entry driver, without duplicating tests. The original scientific execute body and original verify function match PR32 byte-for-byte. comparison.py, protocol.json, T1 watchdog, policy/checkpoints, historical failures and Research Ops selection pointers are unchanged.

This is a trusted same-machine serial Linux/WSL research launcher, not malicious same-user isolation, concurrency-safe authorization or production robot safety. The confirmation flag prevents accidental launch; it is **not** proof of Owner identity. Abrupt SIGKILL of the Supervisor, uninterruptible kernel blocking or unwritable storage are not qualified guarantees. Storage failure may retain its explicit failure on external stderr rather than disk. Synthetic scaled timeouts verify deadline mechanics, not a 600-second physical reliability run.

Research Ops reports CURRENT 38/38 and PASS_SCOPED_DIFF. These are retained pointers, not promotion of T2a science. Recorded test-command wall time including failed/intermediate attempts is 72.217s; complete-entry subprocess time is 6.846s. PUBLICATION_CHECKPOINT.json gives measured time since the preservation receipt, not the entire conversation. Reasoning/implementation token usage, API cost and a same-condition efficiency comparison are unavailable. Research Ops durations were imported with mark; its zero shell-command counters are not a claim that failed tests did not occur—the raw attempt table is authoritative. One native read-only auditor, zero additional paid API calls, no environment reinstall/download.

## Owner decision boundary and stopping point

The engineering gate has no outstanding blocker within the stated trusted Linux/WSL scope. Any actual acquisition still requires a new explicit Owner decision tied to C_exec + the new Readiness + unchanged Protocol, with B0/C0/C256 once each, 12,000 steps/group, 36,000 total, 595-second outer cutoff and 600-second total. No authorization is requested or issued by this report. The protocol continues to say OWNER_CONFIRMATION_PENDING and Readiness says acquisition_authorized=false.

MuJoCo steps **0**; policy inference **0**; optimizer updates **0**; GPU execution **0**. No PPO advantage has been measured. Draft only, no merge, no physics; stop after publication and await the Owner's separate decision.
