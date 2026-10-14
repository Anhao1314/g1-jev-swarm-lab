# Post-crash recovery, 2026-10-14

Verdict: RETAINED_WORK_INTEGRITY_PASS. Crash root cause: UNKNOWN.

This is an additive recovery record. DELIVERY.md and ASTAR_EXECUTION_RESULT.md
retain their original publication failure statements; those describe the prior
session, not a new scientific result. No reset, clean, permission/ACL/security
change or evidence replacement was performed.

Windows booted at 14:32:02 +08. Kernel-Power 41 at 14:32:04 records an unclean
shutdown with BugcheckCode 0; it does not identify a cause. EventLog 6008 refers
to 13:39:49, while retained task files have later write times: the event timestamp
must not be treated as a precise freeze onset. Firmware frequency-limiting
Event 37 is present after boot (also after earlier boots); it is not proof of a
thermal or power cause. No recent bugcheck dump or relevant WHEA/disk/resource
exhaustion error was located in the bounded checks. No diagnosis of hardware
health or crash causality is claimed. Initial free memory was about 13.6 GiB;
C/D free space about 97.6/477.4 GiB, and a later CPU sample was 1 percent.

Private raw system events and resource snapshots are retained outside Git:
D:/webcodex/mujoco-g1/evidence/post-crash-recovery-20261014-1450/.
Only a sanitized summary and task hashes are published here.

Independent reviewer /root/recovery_review performed a read-only review:
- The analyzer bytes match the pre-crash SHA in analysis.json and prior review.
- All three Research Ops outputs match their retained hashes; tests.txt is
  byte-identical to the final pre-crash 12-test PASS output.
- The pinned evidence index and 49/49 source files match byte length and SHA256.
- All ten delivered task files match the retained additive patch after LF/CRLF
  normalization. ASTAR_EXECUTION_RESULT.md has no pre-crash hash/patch anchor.
- No independently timestamp-signed pre-crash byte inventory exists for every
  document. pre-write-files.json is a NEW post-reboot snapshot, not such a proof.
- The original Stop SUCCESS remains unchanged. Zero post-success samples mean
  NOT_OBSERVED, not Hold failure. No scientific integrity blocker was found.

One new, focused recovery test invocation was run using this worktree's Python:
`.venv/Scripts/python.exe -B -m unittest discover -s tests -p test_retained_stop_analysis.py -v`
Result: 12/12 PASS. Full output: recovery-tests.txt. Command elapsed 1.2262 s,
recorded by existing Research Ops in telemetry.jsonl. No full regression rerun.
Old logs and the original delivery patch remain untouched. A local worktree-add
attempt initially referred to a commit in another Git object database and was
rejected (invalid reference); it made no checkout. The independent UI worktree
was subsequently created from the correct repository, without rewriting either.

Next selected product task: source-bound Stop evidence interpretation in the
existing saved-result viewer. This is read-only product feedback, not a new
controller, authorization mechanism or physical qualification experiment.

Boundaries: 0 new physics steps, 0 policy inference, 0 training, 0 rendering,
0 model/provider calls, 0 merges. Consumed Owner permission is not reused;
Language Runtime/D011 and Research Ops selection pointers are unchanged.

References for system-event interpretation:
- https://learn.microsoft.com/en-us/troubleshoot/windows-client/performance/event-id-41-restart
- https://learn.microsoft.com/en-us/troubleshoot/windows-server/setup-upgrade-and-drivers/event-id-37-windows-kernel-processor-power

Publication checks: normal scoped Git staging now succeeds with the current
session permissions; no ACL/security change was necessary. Initial staging
would normalize CRLF in three retained diagnostics/receipts, so a directory-local
.gitattributes preserves their original bytes. All eleven original task files
and five local receipt/patch files remain byte-identical to the post-reboot
snapshot. The original summary's trailing blank line is retained deliberately;
its diff-check whitespace warning is not a scientific or code failure.
