---
name: g1-fast-fix
description: Handle one clearly bounded G1 R0/R1 documentation or nonscientific implementation fix with minimal reading, focused verification and prompt closeout. Do not use for P1/R2, scientific criteria, safety, execution permissions or frozen evidence changes.
metadata:
  version: "0.1"
---

# G1 Fast-Fix v0.1

P0 is delivery priority, not permission or a lower scientific gate. Use this
instruction-only mode for one clear defect/edit with a known expected result.
Do not add a runner, scheduler, timer service or new execution authority.

## Admit or exit before changing files

- Load the existing [Research Ops entry](../g1-research-ops/SKILL.md) only if not
  already loaded. Use the reviewed interpreter; a missing environment is a
  blocker, not permission to install/copy one.
- Once per task, use `research_ops.py context` and
  `plan --kind implementation --paths AFFECTED_PATH...`. Record root, HEAD,
  scope and the specific expected result. Preserve unrelated changes and use an
  isolated branch if the current checkout is a frozen execution source.
- Continue only for CURRENT context, clear scope and R0/R1. Unknown scope or
  STALE context needs review; never refresh a scientific pointer automatically.
- **Exit Fast-Fix** for P1, R2, changed scientific criteria/thresholds/results,
  frozen evidence/provenance, safety claims, controller/Runtime behavior,
  release/authority/identity/permission gates or physical/model execution.
  This semantic veto applies even if a path-only plan says R0/R1. Follow the
  original protocol/independent review/Owner gates; `--p1` adds review, not speed
  permission. Clarifying an innocuous README typo is not a new scientific claim.

## Smallest useful loop

1. Search with `rg`, read the relevant implementation/caller and applicable
   contract once. Prefer retained locators; avoid broad history archaeology.
2. Make the smallest complete change. Do not refactor neighbors or fix extra
   findings. One owner works; no subagent by default. Delegate only genuinely
   disjoint work or a required review with a concrete benefit.
3. R0: inspect the diff/affected references. R1: choose the smallest meaningful
   affected check. Generic plan suggestions do not require unrelated full Ops,
   Console or scientific suites; applicable mandatory checks are never waived.
4. Reuse only if an existing successful unit receipt already covers the complete
   code/config/test closure, live environment and the **same actual invocation**:
   `reuse --receipt TASK.jsonl --check-id LABEL --paths INPUT... --gate unit --invocation-spec CHECK.json`.
   CHECK.json must declare nonsecret literal argv with an absolute executable.
   Missing/legacy/drifted/pending/failed receipts mean run the targeted check;
   do not build a reuse package when simply running once is cheaper.
5. Use `run --task ID --stage tests --label LABEL -- ...` to retain the real
   result. For reusable runs also declare bindings and matching invocation spec.
   A precheck/start failure is not a test PASS. Preserve failed logs and latest
   attempts; rerun only after a relevant change or a justified environment fix.
6. Use `closeout --base FULL_BASE --paths TASK_PATH...`, inspect/stage only the
   authorized diff, and satisfy the user's Git delivery request. Reference sealed
   historical receipts by fixed Git identity; do not copy old bundles again.

## Soft budget and stop

- At about **5 minutes**, give a brief checkpoint: completed evidence, remaining
  uncertainty, active command/progress and the next necessary step. Do not
  create a benchmark or restart work just to explain elapsed time.
- At about **8 minutes**, form a reviewable delivery or truthful blocker/partial
  statement. These are soft budgets: never drop required validation, interrupt a
  necessary running check, invent PASS, or weaken a gate to meet the clock.
- If required work remains, retain evidence, explain why and continue only the
  blocking work already authorized. An unavailable prerequisite means BLOCKED;
  a running check means pending, not a failed/successful completion certificate.
- When the expected result and mandatory checks are satisfied, stop. No polish
  loop, unrelated regression, extra agent, new experiment or follow-on stage.
  One bounded push attempt is enough; preserve REMOTE_PENDING on transport failure.
- Close with verdict, exact changes, actual checks/reuse and failures, Git state,
  limitations and stopping reason. Missing time/token/benefit data stays unknown.
  This Skill does not itself prove faster tasks or stable triggering by the client.
