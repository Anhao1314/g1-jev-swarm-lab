# Independent M2.4 scientific audit

Verdict: **INCONCLUSIVE**. Integrity: **PASS**. All seven planned arms completed once; 64787 native steps.

- seen_reference_walk6--authorized_new_mission: NEW_TASK_SUCCESS.
- seen_reference_walk6--authorization_refusals: AUTHORIZATION_REFUSALS.
- transition_turn45_walk6--authorized_new_mission: NEW_TASK_SUCCESS.
- transition_turn45_walk6--authorization_refusals: AUTHORIZATION_REFUSALS.
- push60_walk6--authorized_new_mission: NO_HALT_TRIGGER.
- push60_walk6--authorization_refusals: NO_HALT_TRIGGER.
- normal_control--unchanged_safe_mission: NORMAL_CONTROL_PASS.

The transition condition supports the bounded failure → successful halt → eligible exact state → registered TEST_ONLY complete-plan continuation chain. Its joint/control state differs beyond a world transform. The push parent succeeds under the frozen strict envelope, so its two cells have NO_HALT_TRIGGER and no issuance or dispatch; those cells are missing failure-chain coverage, never authorization or physical-stop PASS. Both eligible refusal arms reject six controls with zero incremental execution; deliberate stale-state steps are separate. Normal control retains ordinary success with no lifecycle.

Single seed-0 deterministic conditions, paired arms are copies. One newly reached failure/halt condition supports bounded chain; push passed strict parent and did not test failure/halt/assessment/authorization/new task. No production identity, hardware stopping, generalized restart or statistical reliability claim.

Raw source: raw_evidence_manifest.json; detailed per-stage metrics, margins and raw checks: audit.json. Provider calls/tokens: 0; model token usage unavailable. No physics, policy evaluation, retries or new cases in this audit. Stop: frozen matrix and independent saved-byte audit complete.
