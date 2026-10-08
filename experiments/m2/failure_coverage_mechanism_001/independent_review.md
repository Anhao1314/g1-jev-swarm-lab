# Independent saved-data mechanism review

Verdict: no blocking scientific or numerical error found in the final `report.md` and reviewed `analyze.py` / `derived/metrics.json`. This is a bounded independent review of descriptive accounting, not a new scientific PASS or replication campaign. M2.4 INCONCLUSIVE remains unchanged.

Independent checks performed by the reviewing subagent:

- Re-read raw parent native traces and recomputed endpoint yaw-frame velocity projections using a separate short calculation. Differences from saved heading/body-lateral integrals were at most 1.17e-15 m. Reported position closure is below 1.6e-13 m. The route-frame identity follows directly from planar rotations; it is not a causal separation.
- Reviewed parent Walk slicing: seen starts at native index 0 for 6468 steps; transition at 1122 for 6486; push at 0 for 6438. Actual entry state/yaw is used. Turn and Halt samples do not enter the Walk integrals, and new-mission trajectories are excluded.
- Independently re-read and compared seen/push saved rows: exactly 500 identical prefix rows; force-bearing indices exactly 500 through 599 (100 intervals). This supports the recorded deterministic pairing, not equality of unrecorded hidden state or general reliability.
- Independently verified all three first-poststep targets equal frozen default angles. The originally narrow action/counter boolean is now backed by a separate explicit target assertion. First reset PD reconstructions have zero error. Same reset target acting on different joint states cannot identify reset-alone causality; the report correctly states this limitation.
- Independently reconstructed all four parent halt first crossings: seen final/previous means 0.09996958151718828 / 0.10033663736499489 m/s at step 671; transition 0.09981605732160394 / 0.10020112993031954 at step 658. Earlier eligible windows all exceed threshold. The frozen instantaneous endpoint criterion is independently satisfied at 0.05603522601217542 and 0.0639899117815049 m/s, respectively. Original HALT_SUCCEEDED remains valid under its rule.

Final interpretation review:

The report correctly qualifies push effects as supported by this saved deterministic pairing. It does not assign the integrated body-lateral term entirely to direct external impulse, does not separate controller/contact/inertial causal shares, and does not recommend push as recovery. It distinguishes endpoint strict acceptance from a corridor maintained throughout the trajectory. It treats controller reset as observed source semantics and state reinitialization, while explicitly retaining the physical-state confound and absent reset-off control.

The halt interpretation is appropriately bounded: zero additional parent Halt samples after first qualification, no sustained-hold claim, no reinterpretation of later new-mission motion or one stale-state tick as hold evidence. Suggested next work is design-only, requires separate approval and frozen construction/budget, and does not silently acquire replacement failures or erase missing coverage.

Scope limits: review used saved data and source reads only; no simulator, controller, policy, or provider execution. The root analysis owns the 178-file seal verification; this reviewer independently checked the specific numeric claims above rather than duplicating a broad integrity campaign. No historical files modified. No remaining blocking issue identified; stop because the requested review is complete.
