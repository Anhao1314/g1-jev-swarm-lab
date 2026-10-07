# Reproduce the stored Pilot

The publication package verifies stored evidence bytes without model calls.
It does not promise deterministic model reruns. Use Python 3.11.9 and the
versions in `environment.json` for the recorded local software environment.
Python/Git alone suffice for package hash checks; compiler replay also needs
the project dependencies. Keep the repository root and `src` on Python's
module search path.

1. In a fresh checkout, run `python scripts/package_source_authority.py freeze`
   and `python scripts/package_source_authority.py check`. The resulting archive
   and content-manifest hashes must match the publication receipt under
   `reports/source_authority_publication_validation.json`. Both `core.autocrlf`
   modes have independent checks. No historical freeze tag/hash is edited.
2. Run `python scripts/validate_source_authority_evidence.py --bounded --output
   artifacts/phase24-source-authority/evidence_validation.recheck.json` for the
   independent complete-population/first-response/release/accounting audit.
   This performs no provider or Runtime calls.
3. The 466 saved authentic responses in `session4_raw_replay.json` are replayed
   by `run_source_authority_pilot.py replay`. Stored `baseline_replay.json`
   already contains that replay and every status/IR matches the trusted export.
   The evidence writer intentionally refuses to overwrite existing output;
   re-acquisition/replay into new destinations requires a separately versioned
   experiment, not removal or mutation of this freeze.
4. `analyze_source_authority_pilot.py` is the authoritative accounting reader:
   it includes usage from reasoning-only and incomplete provider documents.
   The acquisition harness's legacy `aggregate`/`summarize` helper only has
   backend-response usage; it is not the publication cost estimator. The
   authoritative `summary.json` explicitly retains that naive total alongside
   independently corrected wire-response totals. Narrative `report.md` includes
   a subsequent independent scientific review; it is packaged as stored text.

The successful `preflight.json` binds the exact acquisition harness, original
model-gate modules/prompts, protocol and inputs. Those files were unchanged
through all 528 scored pairs. Frozen B is also compared against audit anchor
`624c802`. Per-stage `started`, attempt begin/end, response and result files
retain first responses. Recovery never reissues an observed/interrupted semantic
call. Unknown unavailable responses release no Mission.

The bounded control was added after resource failures were observed and is
explicitly post hoc. It uses the same immutable B candidates and no extra
provider calls. Its raw language-file hashes describe the original local
worktree; anchor Git-blob hashes in `baseline_snapshot_manifest.json` separately
identify portable publication bytes. Do not reinterpret the former as
cross-checkout byte pins or normalize historical hashes.

Live repetition is not part of this publication check. It requires the same
approved DeepSeek endpoint/profile/credentials plus a new non-scored preflight
and separately named outputs/protocol. Credentials are resolved from the local
saved historical profile in memory, never from this repository. Codex's GPT
development provider is separate from the frozen tested compiler provider.
Runtime remains BLOCKED, D011 remains candidate, and a new independent held-out
campaign has not started.
