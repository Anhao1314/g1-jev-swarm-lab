# M2.6A six-cell acquisition engineering readiness

**READY_FOR_OWNER_ACQUISITION_AUTHORIZATION — engineering only. Scientific result: UNMEASURED_NO_PHYSICS.**

This additive adapter consumes the reviewed PR #19 design at `d5f33bc5254abdb9775bde9a169e3b360dedb810`; no protocol field is changed. The design's historical `execution_adapter_implemented=false` records its design-stage status and remains immutable. The adapter is implemented in this separate readiness namespace. M2.4 stays INCONCLUSIVE, M2.5A retains its two-seen-seed0 bounded result, and Research Ops scientific selection remains unchanged.

## Execution identities and dependency

| Binding | Identity |
| --- | --- |
| Design HEAD | `d5f33bc5254abdb9775bde9a169e3b360dedb810` |
| Candidate design seal SHA-256 | `16c03d52623c705bae481ae512e9f9371f0d5bb246d7ec0eed3607e100f32ee5` |
| Committed executable code HEAD | `d465c2ad664154a16326649c616e643156734dd7` |
| Execution source manifest SHA-256 | `4e241c65ed13e64cd256c15fa755c3330ab57c82c5ff7485aa4ad031c1aad74c` |
| Readiness Manifest SHA-256 | `c052cb3b155a2182be0481f530b3c3dcbee4fa53c74c38313c8e8220923207eb` |
| Exact runnable checkout HEAD | Final engineering PR HEAD, published separately in the PR handoff; required to match live Git HEAD before any future worker |

The code commit precedes the manifest/receipt commit to avoid a commit hashing itself. The code commit alone does not contain the final manifest. Use the final published engineering checkout, whose code must match the pinned code commit and whose Readiness must match the hash above. Future Owner authorization must name **that exact final checkout HEAD**, this Readiness hash and the unchanged budget. An ancestry relationship alone is insufficient: full current-source hashes and the new Python Git blobs are checked. No future rebase or code repair is implicitly authorized by this delivery.

The independent engineering Draft PR depends on unmerged design PR #19 and targets its head branch. This is neither accepted-main publication nor a request to merge automatically.

## Implementation and qualification layers

`acquire.py` derives an execution view from the immutable six-cell design. It reuses the existing policy torque helper, Mission Runtime, controller, strict evaluator and physical Halt contract. Lazy live imports and session construction are reachable only after explicit future physics authorization, exact checkout identity and a complete Readiness check. Trusted serial TEST_ONLY invocation is the only supported execution surface; the flags are not production identity or concurrent atomic authorization.

- **Trigger:** original first Walk execution and strict endpoint outcome determine the existing graph/Halt route. Strict PASS continues the original parent graph without a fabricated failure Hold. TIMEOUT/physical failure lacking the strict trigger is preserved as unsupported/no-Halt coverage. Normal-control failure before Stop remains a control negative with no Hold.
- **Halt:** the original first complete 500-post-step mean crossing is retained. Fallen/nonfinite Stop rows cannot retrospectively create a successful crossing. Runtime acceptance is separately checked. A raw-proved physical failure remains a negative; swallowed Stop/observer exceptions without that physical evidence are technical interruptions and stop the campaign.
- **Hold:** only physically qualified, force-clear entries continue the same session/controller/policy with zero velocity commands for the frozen 1,000 native steps. No Stop redispatch, new mission, state injection or extra simulator reset occurs. The exact terminal state, seed window, controller counters, identities and command arguments are journaled.
- **Distinctness:** the independent auditor compares raw request and terminal states against all three sealed M2.5A references, applicable controls and the other primary. Global XY/yaw and metadata-only changes never confer novelty. Missing/nonfinite descriptors are unavailable, not invented. Aliases remain scored and retained; novelty never controls whether an otherwise eligible Hold runs.
- **Completion:** technical/partial metadata is separated from raw scientific evidence. A previously valid physical negative survives a later technical interruption. Missing witnesses, truncated journals and hard timeouts retain complete-row prefixes, file hashes and NOT_RUN cells. A clean final JSON newline does not prove absence of an in-flight step: abrupt termination remains UNKNOWN.

The frozen order, six conditions, ±60 N force vectors, 0.2 s windows at 1/4 s, seed 0, 2 s Hold and all physical/task thresholds are unchanged. Limits remain **30,000 native steps and 120 wall seconds per cell; 180,000 steps and 720 seconds per campaign; one attempt each**. Native guards, external subprocess supervision and measured cell/campaign receipts enforce the limits, including between-cell prefix checks. Scientific negatives continue in fixed order; integrity, budget, technical or required-evidence failure stops with partial evidence and no retry.

## Force, observer and evidence validation

The adapter's integer native-step force gate is tested at every relevant boundary. It records actual pelvis identity, world-frame vectors, pre/post native intervals, activation and clearance. Full early/late windows correspond to 100 intervals at offsets 500/2000. Normal return and RuntimeError/IntegrityFailure/BudgetFailure use the same force-release `finally` seam. A hard process kill cannot provide a force-clear witness and is never promoted to safe termination.

The read-only native observer and controller-command wrapper are shared by the real backend and fake tests. Tests preserve argument identity, commands, counters, states and exception propagation with recording on/off. They establish **source-seam non-mutation and fake execution equivalence**, not real-dynamics observer equivalence. Future acquisition must reproduce the sealed seen controls and actual pre-pulse paired prefixes before advancing; any drift stops the campaign without tuning or replacement.

`audit.py` imports no acquisition backend or simulator. It independently derives strict geometry from raw states, evaluates the Stop crossing/acceptance and every Hold rolling window, checks the path including entry-to-first-row displacement, recomputes force exposure and prefix pairing, and verifies continuity, commands, resets, budget/context bindings and operational state differences. It does not accept acquisition PASS labels as scientific truth. Actual observed Halt requests, independently scorable denominators and censoring are reported separately.

Safe ZIP restoration accepts only a new clean directory, the exact member set, regular contained paths and matching byte/hash seals. It rejects duplicate members, traversal, links and corrupted content. Three real historical reference states are read from the sealed M2.5A archive and checked per member; these remain seen reference evidence, not new acquisition.

## Target environment and freeze

Complete target checks passed without importing MuJoCo, Torch or the G1 execution package, compiling a model or running policy inference:

| Check | Recorded outcome |
| --- | --- |
| Execution/config/history/new-source closure | 363 exact file hashes |
| Byte domains | 148 Git raw-equal; 124 Git LF→Windows CRLF; 91 unversioned official asset bytes |
| Official assets | 91/91 locally copied only after full source verification; ignored assets, no download or overwrite |
| Dependencies | 41 exact package versions, interpreter/platform and non-importing module-origin checks |
| MJCF resources | 2 XML documents / 28 resource links; no model compilation |
| Frozen design | 8/8 sealed core files and exact reviewed protocol Git bytes |
| Target preflight | TARGET_PREFLIGHT_PASS_NO_PHYSICS |
| Actual adapter CLI preflight | TARGET_PREFLIGHT_PASS_NO_PHYSICS |
| Final combined offline tests | **111 PASS, 6.79 s**: adapter 50, independent raw audit 42, environment 19 |

The historical 78 Git matches / 85 CRLF conversions / 91 official asset receipts are untouched. The new 148/124/91 counts describe a larger, separately frozen closure; they are not rewritten historical receipts. All baseline Git mode/blob entries are preserved. Model and policy assets are byte-verified only, not newly executed. This is a target-Windows readiness result, not an environment portability or hardware guarantee.

Initial system-Python missing-pytest tooling failures are retained separately from scientific outcomes; testing used the existing pinned repository environment without installs or updates. Raw Research Ops logs retain staged checks and final passing receipts. Target preflight and independent review are recorded alongside the source/Readiness manifests. Reasoning duration and tokens not measured are marked unavailable, not zero. No scientific experiment stage occurred.

## Reproduction and acquisition boundary

Use `D:/work/g1-jev-swarm-lab/.venv/Scripts/python.exe` from the exact engineering checkout. The following commands are nonphysical:

```text
python -m pytest experiments/m2/unseen_halt_hold_readiness_001/test_acquire.py experiments/m2/unseen_halt_hold_readiness_001/test_audit.py experiments/m2/unseen_halt_hold_readiness_001/test_readiness.py -q
python experiments/m2/unseen_halt_hold_readiness_001/readiness.py --expected-sha c052cb3b155a2182be0481f530b3c3dcbee4fa53c74c38313c8e8220923207eb --execution-head <EXACT_PUBLISHED_ENGINEERING_HEAD>
python experiments/m2/unseen_halt_hold_readiness_001/acquire.py preflight --readiness-sha256 c052cb3b155a2182be0481f530b3c3dcbee4fa53c74c38313c8e8220923207eb
```

Assets must exist at their frozen ignored paths; `readiness.py --restore-from` supports copying only a fully hash-verified existing official source. No global environment setup, install, model load or inference is part of preflight. `freeze_sources.py` documents the write-once source-freeze procedure; do not rerun it over the accepted manifest.

There is **no acquisition authorization in this PR**. Do not invoke `acquire` or `worker` commands now. Required next gates are new independent/Owner review of this engineering delivery and a separate explicit physics authorization naming the final runnable HEAD and Readiness SHA. That authorization may permit only the already frozen six one-shot cells and budget, not fixes, retries or expanded conditions after outcomes. Jev, PPO, Multi-Swarm, ROS-R2, Language Runtime/D011 and hardware remain outside scope. Stop at this readiness handoff.
