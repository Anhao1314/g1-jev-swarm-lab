# Phase 3A.4b decision

Scientific verdict: **SUPPORTED_GEOMETRIC_LOCAL_CONTRACT_CONFLICT**.
Integrity verdict: **PASS_WITH_NONBLOCKING_INITIAL_OBSERVER_METADATA_GAP**.

The fixed sixteen executions are sufficient to answer this research question;
there are no further model runs, alpha scans, case expansion or optimization.

Alpha0.5 improves world-route precision by aligning the selected correction
heading toward the ideal mission axis. The lateral feedback axis rotates with
it. At the identical first Walk start, the actual heading is −5.367025° and
the selected axis rotates +2.683512°. The original endpoint corridor is still
measured along that actual-start heading. At measured forward progress8.000294m:

`0.372292m actual local drift = 0.374977m rotation component − 0.002685m tracking remainder`.

The real endpoint displacement exceeds the unchanged strict0.28m limit while
satisfying nominal0.56m. It is a genuine historical local-contract failure.
There is no detected frame-sign, command, scoring or historical replay artifact.
Small selected-frame tracking residuals, identical upstream state, intermediate
alpha interventions and identical zero-offset primitive controls support this
mechanism beyond the algebraic identity alone.

First-Walk physical evidence does not implicate upright instability. All16
executions have physical success and no falls. Whole-sequence tilt, height,
transition geometry and X endpoint error nevertheless change; they are retained
in the report and must not be described as unchanged or uniformly improved.

Three Walks attenuate the inherited yaw component by `(1-alpha)^3`. At alpha0.5
the Stand contribution changes from −5.367025° to −0.670878°; other measured
residuals total −0.617694°, yielding −1.288572° at the endpoint. Final world-Y
error improves0.728696m, principally through the first and last Walk, while
X error increases0.427170m. The endpoint norm still decreases0.631903m.

Alpha0.25 improves global precision and passes strict in this fixed case. This
refutes a universal claim that every nonzero correction must violate the local
corridor; it does not select a new operational alpha or demonstrate disturbed
reliability. Alpha0.75's nominal margin is only2.074mm. Alpha1's nominal and
strict failures remain retained.

No protocol, policy, reward, gains, PD, skill, historical threshold/result,
Console source or asset changed. All1519 pre-existing files remain byte-exact.
The first12 historical anchor/repeat checks passed before novel doses. All8
repeat pairs are exact; simulator seed0 does not imply independent randomized
trials. The46 targeted tests pass; the already evidenced historical full
regression was not rerun.

The six primitive initial t=0 pose samples have an unset reference heading
before first Walk setup. This authentic observer metadata gap is recorded in
`FINAL_INTEGRITY.json`; subsequent samples and every command are correct. It is
nonblocking for this question and was not fixed or rerun.

Acquisition code commit: `191b78ab2f6d1637cba39dec8148af8e9bfc56b4`.
Protocol SHA: `fa90b79f6c60e00e5cf18c3b21125ae947d40f15ff4d82eaafd12c2a613d570f`.
Cases SHA: `0799556722dc6a9c90841acf29e425f88e3c3c690eb5f1f3b4768d061ba961c9`.
Policy SHA: `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d`.

The full experiment report is `FINAL_AUDIT.md`; scored rows, traces,20Hz poses,
probe/anchor checks and completion receipts are in `evidence/`, with55 exports
bound to raw/encoded SHA values by `evidence_manifest.json`.

**Stop here. Phase3A.5 remains paused.** Any later work must first state how the
global reference objective and historical local-corridor contract should coexist;
this study does not authorize a scoring change, architecture patch, new training
run or Console extension.
