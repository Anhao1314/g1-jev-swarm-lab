# Verification routing v0.1

| Tier | Actual scope | Required evidence |
| --- | --- | --- |
| implementation (Surgical) | UI, docs, bugfix, retained-data wiring, ops | Diff/affected contract; focused tests where behavior changed. Visual wiring also needs source/asset identities and relevant browser QA. No automatic scientific acquisition or full regression. |
| mechanism (Experimental) | Controlled intervention to answer one scientific question | Applicable protocol and budget frozen before acquisition, evidence/control completeness, source/config/policy identities, targeted measurement/interpretation audit. Existing mandatory protocol checks remain mandatory. |
| claim | New safety, generalization, held-out, baseline adoption, formal scientific PASS/FAIL | Mechanism requirements plus strict provenance, frozen thresholds/splits, appropriate baseline/controls, independent audit of evidence AND interpretation. Report PARTIAL/BLOCKED if a required gate is absent. |

Release is a delivery mode, not a scientific tier. Commit/push does not escalate a
documentation task; a formal baseline adoption escalates even without code changes.
Mixed tasks take the highest actual scope. Shared controller/evaluator/runtime changes
require affected contracts and relevant equivalence/regression even for a bugfix.
Displaying an existing FAIL is not issuing a new scientific FAIL claim.

`plan` uses explicit intent plus paths, not fragile keyword analysis of a prompt.
Unknown paths return NEEDS_SCOPE_REVIEW; they are never silently declared low risk.
The agent must declare scientific intent accurately. This router is advisory and
does not mechanically prevent a malicious/incorrect actor from running a command.
Explicit user boundaries and existing protocols override convenience routes.

Current task restrictions are emitted by `context`; they are not permanent grants.
Phase 3A.5 remains paused. No threshold, historical verdict/evidence, PPO, Jev,
Multi-Swarm, Language Runtime gate or official scientific acquisition is changed
by this upgrade. Changing pointers requires a separately authorized state update,
reviewed against new authoritative evidence; staleness never means permission.

Reuse tests only if code/config/environment and covered behavior still apply.
`check console` checks exact bytes of all artifacts in the retained validation
receipt, both visual inventories, and the scientific export inventory. It always
rehashes; no mtime-only cache. It does not rerun numeric audits or scientific tests.
Independent auditing cannot be replaced by a script that merely says hashes match.
