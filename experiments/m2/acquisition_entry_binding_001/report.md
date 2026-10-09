# M2.6A Acquisition Entry Binding — nonphysical integration

**Verdict: `PASS_NONPHYSICAL_ACQUISITION_ENTRY_BINDING`. Physical acquisition remains BLOCKED.** This is an R2 engineering qualification, not a new scientific result or an Owner acquisition approval. M2.6A remains `UNMEASURED_NO_PHYSICS`; M2.4 remains `INCONCLUSIVE`. Scientific selection pointers, the six cells, thresholds, P1 failure classifications and historical negative evidence are unchanged.

## Identity and scope

- Reviewed base: Draft PR #22, `44d7a664e9d9ecca57661e98ea15200a216e5517`.
- Independent worktree: `D:/webcodex/mujoco-g1/acquisition-entry-binding`, branch `m2.6a/acquisition-entry-binding`. Original `main-codex` is untouched.
- Operational code HEAD: `7edf79fa78d95f2020ed11b597ac014d44646db3`.
- Qualification HEAD: `7976d33d8cc96eb5326256de43720a08d7ddf499`. Delivery adds evidence/documentation only; its exact final HEAD is published in the PR with a final clean-process preflight receipt. An external reviewer/Owner must pin that full HEAD; no self-hashing Git commit is claimed.
- Source Manifest SHA-256: `b91578f63bdeb1d87aeb0e3b8f7e02f49c6a1d7c9c8143a7235ad8a89382cac3` — 531 source entries.
- Readiness SHA-256: `8dd88843f4abd9b283076b4e42c73c317b0863336e861f41fd3bbbc663e282b0`.

The gate preserves all 2,842 PR22 baseline Git mode/blob identities, verifies the registered new worktree and Git common store, and allows additions only in this namespace. The PR22 Source/Readiness and complete 520-source closure are retained as immutable inputs. Original PR21 source/asset checks are reused after hashing its helper, without rewriting either prior manifest. The new environment receipt permits only the `g1swarm` origin relocation; the 41 dependency versions and external package origins remain pinned to `D:/work/g1-jev-swarm-lab/.venv/Scripts/python.exe`. Stale external editable metadata is byte bound and explicitly does not select the execution source.

Official resources were restored non-overwriting from the independently verified local `main-codex` resource set: 91/91 hashes pass. No old `.venv`, untracked experiment evidence, or raw artifacts were copied. XML references were parsed; no model was compiled.

## Entry contract

Use this namespace's `acquire.py`; the immutable old PR21 CLI is not a migrated alternate entry. Its old readiness still has its old source-origin contract. No automatic fallback is implemented.

Every new process follows:

1. Parse required full execution HEAD and Readiness SHA.
2. Check a clean process, fixed registered root, actual HEAD, preserved history, source/code Git pins, receipt hashes, dependency/asset identity and actual project/Oracle resolver origins.
3. For `acquire` or `worker`, check physical authorization **before** loading the frozen adapter. `preflight` loads no adapter and grants no physical authorization.
4. Load the byte-checked PR21 adapter only after the guard. Rebind only its new module instance's `HERE`/`READINESS` and preflight seam; retain its original file and all scoring/control functions unchanged.
5. The original supervisor builds worker commands using the new namespace. Every independent worker repeats the guard; the backend guard repeats it again immediately before original lazy live imports.

`--authorize-physics` is insufficient: `authorize_operation` deliberately rejects all physical operations in this engineering freeze, whose Owner binding is null. Neither caller-supplied hashes, an environment flag nor a caller-made authorization file can grant permission. A future acquisition requires independently reviewed Owner authorization and a newly explicit authorization binding/freeze; merely changing a CLI switch is insufficient. This is trusted serial experimental plumbing, not production identity, concurrent atomicity, an adversarial sandbox or a hardware safety mechanism.

The original P1 adapter remains responsible for raw retention, irreversible Hold negatives with technical incompletion, original control-error provenance, stop-on-technical/integrity/budget failure, pristine worker directories, prior-cell order, no retry and prefix audits. Its original native-step and wall guards are unchanged. The new read-only `audit.py` replaces only the source-binding seam; original raw scoring, normal-control qualification, complete historical comparison and classification functions remain the original function objects. Importing the read-only auditor does not dispatch a task.

## Actual nonphysical verification

| Check | Actual result | Receipt |
| --- | --- | --- |
| New entry fault injection | Initial 38 PASS / 1 FAIL; corrected 39/39 PASS | `offline_test_receipt.json`, raw logs + XML in `receipts/` |
| Applicable P1 contracts | 12/12 PASS | `receipts/entry-binding-p1-tests.xml` |
| Clean-process actual CLI + live-import tripwires | 11/11 PASS, zero live-import tripwire hits | `entry_acceptance.json` and its complete raw log |
| Resource/dependency identity | 91 official assets / 41 dependencies; 531 sources | Correct CLI preflight in the same raw log |
| Independent code and saved-receipt review | See `independent_review.md` | Read-only; no duplicated historical testing |

The initial failure was a new test's assumption about quote formatting in `ast.unparse`; it is preserved and replaced by a structural AST check. It was not an acquisition failure or a scientific negative. No historical failure is relabelled.

The 11 real child CLI cases cover correct preflight, wrong HEAD, wrong Readiness, old PR22/PR21 Readiness, absent authorization flags, asserted flags without Owner authority for both supervisor entry and directly invoked worker, and wrong-HEAD acquire/worker. Import tripwires reject `mujoco`, `torch`, `numpy`, `g1swarm` and the live Oracle module if reached. Real temporary Git fixtures additionally reject source tampering even when the proposed hash is changed; resolver fault injection rejects old/other worktree origins. Those reduced temporary fixtures are not represented as full production source acceptance.

The positive physical dispatch ordering tests use **offline authority/gate doubles** and never enter a real backend. They prove seam order only, not a legitimate approved acquisition. Relevant P1 tests exercise partial Hold physical failure plus later technical interruption, actual Router control-error retention, complete historical corruption rejection and normal raw qualification. Other historical tests/reviews are referenced, not rerun or recopied. No full regression, physics, policy inference, provider call, training, new scientific verdict or merge occurred.

## Reproduce without physics

From the fixed worktree, with the pinned interpreter:

```powershell
$py = 'D:/work/g1-jev-swarm-lab/.venv/Scripts/python.exe'
$entry = 'experiments/m2/acquisition_entry_binding_001'
# Supply the externally reviewed exact full delivery HEAD, not a short SHA.
& $py "$entry/acquire.py" preflight --execution-head REVIEWED_FULL_HEAD `
  --readiness-sha256 8dd88843f4abd9b283076b4e42c73c317b0863336e861f41fd3bbbc663e282b0
& $py -m pytest "$entry/test_entry.py" -q -p no:cacheprovider
# Optional reproduction of only the frozen 11 nonphysical CLI assertions:
& $py "$entry/check_cli.py" --execution-head REVIEWED_FULL_HEAD `
  --readiness-sha256 8dd88843f4abd9b283076b4e42c73c317b0863336e861f41fd3bbbc663e282b0
```

The worktree must be clean and retain the exact assets and dependency paths. This identity does not apply to a different directory or the old `main-codex` root. The generic `freeze_sources.py` is a one-shot engineering preparation utility, not a readiness bypass or an acquisition command; it refuses to overwrite sealed metadata. Do not regenerate this freeze to approve physical collection.

## Reused evidence and stopping reason

The [PR22 independent review](https://github.com/Anhao1314/g1-jev-swarm-lab/pull/22#pullrequestreview-5471048148) and its committed 53-test receipts support the unchanged original migration helpers. Prior 154/161, 159/161 and blocked engineering receipts remain where originally sealed. Only this task's new receipts are archived here.

Research Ops initial context was CURRENT, 38/38; no pointer changed. `research_ops_telemetry.json` records measured command stages; reasoning/implementation intervals and token usage are unmeasured, not zero. This task makes no efficiency-gain claim.

The requested nonphysical entry/worker integration and applicable verification are complete. Remaining blockers are Owner authorization binding/independent final acquisition approval and all unmeasured physical qualifications. Current production, hardware safety, concurrent atomicity and hostile-process/TOCTOU guarantees remain unproved. Stop after the independent Draft PR; no physics or further mechanism work follows this task.
