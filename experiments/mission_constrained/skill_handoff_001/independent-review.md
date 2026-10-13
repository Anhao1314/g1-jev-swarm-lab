# Independent read-only design and component review

Reviewer: native Codex subagent `/root/handoff_design_review`.
No file edits, duplicate test runs, physical execution or model calls by reviewer.

**Final verdict: DESIGN_AND_OFFLINE_COMPONENT_FREEZE_NOT_ACQUISITION_READY.**
Design and offline components can be retained; no remaining necessary component
fix was identified. This is not a complete acquisition-entry review.

The reviewer independently recommended the historically exercised 0.25m/s lower
command rather than the initially considered 0.2m/s. The terminal 1m ramp is an
unverified prospective single profile. The experiment addresses the speed-schedule
package, not velocity as a unique mediator: duration, phase, posture and joint state
can also change. Two arms do not establish superiority to uniform slow speed.

The first implementation review found that the mean-speed helper accepted two
points spanning 0.5s, permitting interpolation across missing native observations.
The retained diagnostic returned 0.375m/s. The main agent froze a maximum native
gap of 0.002s plus 1e-9 timing tolerance and added sparse/single-missing tests.

Final read-only confirmation:

- The oversized-gap rejection covers the entire intersecting speed window.
- Two-point sparse and one-missing-native-sample tests are present; integral
  positives use dense samples, without weakening assertions.
- The final raw receipt reports 20 tests PASS; the reviewer did not rerun them.
- The pre-fix failure receipt is retained.
- Historical 20Hz evidence is explicitly insufficient for the native-window metric.
- Offline historical command calculation does not claim counterfactual physics.
- Original strict/physical gates, full Walk-to-Turn error-transfer checks and
  simultaneous physical/technical failure reporting remain intact.

The production `_Controller` AST test checks its actual local call statements with
a fake recording base. It does not verify a full collector or physical equivalence.
Real collector binding, native observation/raw audit, full Source/Readiness,
budget/cleanup and explicit Owner authorization remain outstanding. No scientific
success, complete Mission capability or acquisition permission is inferred.
