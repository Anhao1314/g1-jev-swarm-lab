# Phase 2.3 Protocol Freeze Report (FREEZE_PENDING_OOD_DATASET)

Verdict: **FREEZE_PENDING_OOD_DATASET**. The main Phase 2.3 protocol, final
corpus, scoring, gates, provider policy and evidence schema are prepared and
versioned. The protocol deliberately remains `status: draft` / `frozen: false`
because the Guard OOD Safety Sidecar dataset must be authored by an
independent session that has not read the guard rules. The final campaign must
not start before that dataset exists and is hashed.

## 1. What is frozen (candidate)

- Final sample size: 17 missions per horizon, 102 canonical missions,
  306 language samples (L1/L2/L3). Selection = the remaining corpus after the
  18 pilot missions were permanently excluded; no re-sampling was performed
  and no decision depends on pilot outcome values.
- Final corpus files (versioned; hashes below) and their L1 frozen-Lark
  self-check (PASS; 102/102 L1 texts reproduce their canonical Mission IR).
- Main research variables: horizon = number of Mission IR steps (H1–H16),
  language conditions L1/L2/L3, nominal environment only (no push, friction,
  yaw perturbation or other disturbances).
- Comparison paths: O (Oracle IR → Runtime), L1/L2/L3 (text →
  `guarded_direct_llm_v1` → Runtime).
- Compiler provenance: `guarded_direct_llm_v1`, guard `2.2b.2`, prompt SHA-256
  `913346508791ab86f80247f2b6315d6e96f9b5066090299ada2196aeb0e3c110`,
  `deepseek-flash`, temperature 0.0, max output 4096, timeout 60 s, transport
  retry policy max 2 retries / 0.5 s backoff on 429/500/502/503/504.
- Retry policy: transport failures follow the frozen retry policy and must
  persist attempts / retry reason / terminal transport status; semantic
  failures (wrong IR, false rejection, malformed model response, wrong
  parameter, wrong order) are never retried — the first valid semantic
  response is the final result.
- Attempts persistence: `provider_attempts`, `retry_reason` and
  `terminal_transport_status` are required per provider sample; missing
  attempts is an evidence-completeness gate failure.
- Stages: A = 306 real compiler inputs (no scripted/replay/mock); B = 102
  oracle runtime missions (continuous in-mission execution, frozen reset
  semantics between missions); C = runtime only for exact-IR samples, wrong IR
  recorded as `NOT_RUN_COMPILER_NOT_EXACT`.
- Runtime equivalence invariant: grounding, execution mode, task graph, skill
  sequence, transition sequence, final status and simulation steps must match
  the paired oracle run; any discrepancy is `RUNTIME_CONTRADICTION` and stops
  the campaign for audit.
- Metrics and analysis questions are frozen in `protocol.yaml`
  (`freeze_candidate.metrics`, `freeze_candidate.analysis_questions`).
- Integrity gates are frozen: safety gates (malformed / ambiguous /
  unsupported reaching an executable mission = 0, hallucinated skill = 0) and
  evidence gates (protocol hash, corpus hash, no pilot contamination,
  attempts complete, runtime contradiction = 0, evidence completeness 100%).
- No arbitrary success-rate gates: Phase 2.3 is a characterization study; the
  scientific output is the degradation curve and failure boundary, not a
  pretty PASS threshold.

## 2. Hashes (this freeze candidate)

| Artifact | SHA-256 |
| --- | --- |
| `protocol.yaml` | `8ffaea837a019e846bcbe3fad3fa5da2f4a674aab8066912a37605c1ce704df3` |
| `final/canonical_missions_final.yaml` | `ef856b9401b2be4eb8ca1c75d5f2d1c238246a3254c26dddd01943bf422ac7ac` |
| `final/language_realizations_final.yaml` | `1188cb31c40b7e968d11b9a31f3363eb96c30c09c743f0a8b90e6f6b1b592192` |
| `pilot_selection.json` | `8153e3384acb50eb1d34b5d7297979c4587db03e7676746e49cd3662e4ed36ff` |
| `final/leakage_audit.json` | `937265b91751081d3b5a611af2d171d9b0e7e90ee09fa09a286ad13f0c61aaff` |
| `freeze_manifest.json` | see file (records protocol/corpus/exclusion/maps/runtime hashes) |
| Risk map / boundary / capability map | `8be4b36a…` / `372f3fa8…` / `c5266802…` |
| Runtime protocol / robot config | `c551833b…` / `41903667…` |
| Motion policy | `cf668f75b90d1abf73d2b87612a6e76bccc61ff7e083b63582d3f6aaa3c1759d` |

## 3. Pilot exclusion

`pilot_selection.json` is frozen; all 18 pilot canonical mission IDs are
permanently excluded from the final corpus. Machine check:
`intersection(final, pilot) = 0` (IDs and exact language texts both empty).

## 4. Corpus leakage audit

Exact-text overlap of the 306 final language realizations against historical
corpora:

| Historical corpus | Exact-text overlap | Type |
| --- | ---: | --- |
| Phase 2.1 controlled | 3 | short controlled commands (e.g. `停止。`) |
| Phase 2.2 development | 0 | none |
| Phase 2.2 blind | 0 | none |
| Phase 2.2b development | 0 | none |
| Phase 2.2b fresh blind | 0 | none |

The three historical overlaps are unavoidable short-command collisions; per
the freeze rules these texts were **not** rewritten to force a zero overlap.
pilot/final exact-text overlap was separately reduced to **0** before freeze
by deterministic variant selection over the frozen synonym banks (the
canonical missions were not changed). Full evidence:
`final/leakage_audit.json`.

## 5. Provider / credential policy

Credential resolution is separated from scientific provider configuration:
resolution (where the key and endpoint come from) is an operational concern
and must not appear in evidence; the scientific record contains only the
provider interface, a safe endpoint/config fingerprint, the model ID,
non-secret parameters and the availability preflight result. Secrets are never
hashed into evidence, never written to Git, and historical session transcripts
are not scientific provenance. A provider preflight is mandatory before the
final campaign.

## 6. Guard OOD Safety Sidecar status

**Pending independent authoring.** The sidecar must be authored by a session
that has not read `structural_guard.py`, the guard reason codes or the
fresh-blind malformed set; the tested DeepSeek compiler and the current Codex
session are disqualified as authors. The protocol carries the full spec
(independence, authoring brief, separation, metrics, hard safety expectation,
freeze procedure). The sidecar has its own dataset SHA, manifest, results and
summary and never enters the H1–H16 curves.

Guard-level detection recall is a characterization metric (no invented hard
threshold); system-level unsafe acceptance = 0 remains a hard safety
expectation.

## 7. Deviations and limitations

- No implementation drift: guard, compiler, prompt, grammar, runtime,
  grounder, skills, controller/policy and Phase 1 maps were not modified.
- Pilot boundary is recorded as PILOT_ONLY: 54/54 pilot results demonstrate
  infrastructure readiness only; they are not an H16 ceiling, a
  generalization proof or a production safety proof.
- Open limitation: the sidecar dataset does not exist yet, so the protocol is
  a freeze candidate, not a frozen protocol; `freeze_manifest.json` records
  `freeze_status: pending_ood_sidecar`, `freeze_commit: null` and
  `ood_dataset_sha256: null`.

## 8. Remaining freeze procedure

1. Author the independent Guard OOD corpus (separate session, no guard-rule
   access) and label its malformed / valid-hard-negative splits.
2. Hash the dataset, integrate its manifest and metrics into `protocol.yaml`.
3. Set `status: frozen`, `frozen: true`; regenerate `freeze_manifest.json`
   with the OOD SHA and canonical protocol SHA; record the freeze commit.
4. The final campaign must reference that commit and hashes. Do not start the
   final campaign before this procedure completes.
