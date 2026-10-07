# Byte-exact Pilot packaging

This experiment is anchored to Session 4 audit commit
`624c8024c6587f7c502b1cc87b2b27797493af03`; evidence provenance remains
`5fabf3c050df4420f414a564dcdf5ce255a5b0fa`. B remains
`guarded_direct_llm_v1`. No historical tag, freeze manifest, or pinned historical
byte hash is changed or reinterpreted as newly verified evidence.

The old Phase 2.3 audit found differences between historical worktree byte pins
and published Git blobs after CRLF/LF conversion. New snapshots explicitly use
the **raw Git blob bytes** of the audit anchor. Their manifest records both Git
blob identity and SHA-256, and identifies their provenance separately from the
old worktree byte pins. Old OOD inputs remain seen development/regression
evidence. Packaging does not repair or recalibrate the benchmark.

## Prepare, freeze, and check

Run from the repository root with Python 3.11 or later and Git available:

```text
python scripts/package_source_authority.py prepare
python scripts/package_source_authority.py freeze
python scripts/package_source_authority.py check
```

`prepare` writes anchor snapshots and `baseline_snapshot_manifest.json` under
this experiment. It snapshots the compiler, guard, prompts, Mission validator,
their supporting sources, regression inputs, and the historical results used
in replay. The anchored Phase 2.3 provider/compiler protocol is included alongside
the direct compiler prompt and implementation. A prepare rerun first verifies
all existing snapshots and only adds newly declared files; it never overwrites
a changed snapshot. It rejects changes or deletions to any pre-existing anchor path in
`src/g1swarm`, `prompts`, `configs`, and `experiments/phase2`. These preservation
checks use Git's content comparison; they do not call the legacy worktree-hash
freeze verifier. New architecture files are allowed. The snapshots are copied
as data only; no Runtime, Grounder, skill, network, or provider call occurs.

`freeze` checks the snapshots against anchor blobs, then writes
`content_manifest.json`. Each record hashes exact bytes and records byte length;
there is no newline, Unicode, YAML, or JSON normalization. The content set
includes all files under this experiment and new source,
script, test, and prompt files whose filename contains `source_author`, plus
all files in the new `src/g1swarm/source_authority` package.
Pass `--include repository/relative/path` for additional new protocol or report
files outside those defaults. The report must be complete before the final
freeze. A later edit requires a new freeze and check.
It also requires Git to report `text=unset` for every package path: an extra
included path must receive its own scoped `-text` attribute before freezing.

The ZIP includes the content manifest but the manifest does not hash itself.
It uses sorted member paths, `ZIP_STORED` (no zlib version dependency), a fixed
1980-01-01 timestamp, Unix regular-file `0644` attributes, and no extra metadata.
Default output is the ignored
`artifacts/phase24-source-authority/source-authority.zip`. Its SHA-256 receipt is
stored beside it as `source-authority.receipt.json`, outside the ZIP to avoid
a circular archive hash. The receipt also records the manifest SHA-256. Neither
receipt nor archive enters the content set; they can be independently regenerated.
Temporary files, Python caches, and ZIPs are excluded. Keep validation output
outside the experiment directory to avoid adding a self-dependent check result
to the next freeze. No environment variables or credentials are collected.

`check` verifies every raw file byte hash, snapshots, the receipt, exact ZIP
reconstruction, safe member paths, extracted file hashes, and a second ZIP built
from the extracted bytes. It independently checks each repository path's scoped
`-text` attribute. Any mismatch fails. `--extracted-only` permits checking
an extracted artifact without Git history; it still checks snapshot and content
hashes but explicitly reports that Git anchor preservation and checkout
attributes were not checked.

## Fresh checkout procedure

New artifacts use scoped `-text` attributes from their first commit. This makes
Git preserve their exact bytes regardless of `core.autocrlf`. Existing attribute
rules and historical artifacts are unchanged. The scoped policy is recorded in
this document, and the actual checkout attributes remain reviewable in Git.

After the final experiment commit, make two fresh checkouts with
`core.autocrlf=true` and `core.autocrlf=false`. In each checkout, regenerate the
archive by running `freeze`, then run `check`; compare both archive SHA-256 and
content-manifest SHA-256 against the original receipt. Do not run `prepare` in
these checkouts unless deliberately regenerating snapshots: existing committed
snapshots must first pass their raw-byte checks. Final validation should also
confirm that `freeze` causes no tracked content diff. Keep the validation receipt
outside the experiment package or publish it in a follow-up evidence artifact.

The packaging tests include a real Git commit/clone round-trip with both newline
modes, mixed line endings, binary bytes, deterministic ZIP metadata, unsafe paths,
manifest duplication, baseline edits, and independent tampering checks. A passing
package test demonstrates byte portability, not language safety or fresh blind
generalization. The package does not freeze elapsed-time reruns as deterministic:
stored Pilot timing evidence is immutable data and new runs can have different
timings. A fresh checkout verifies the stored experiment bytes without any model
calls or executable Mission release.
