# V2 thin byte-exact packaging

V2 is anchored to `d06c61811c3ef41abf12c22a4a2618eabf28c495`. Its immutable
V1 comparator payload is `3e21f9370fc37ee7d5ccbd619d8d17662f9574fa`. Frozen
B, the two V1 gates, bounded control, sources, labels, and raw provider evidence
remain in the unchanged V1 payload. This thin package references that payload
without copying its approximately 76 MB archive into a second experiment.

New modules, prompts, scripts, and tests use the `authority_certificate_v2`
namespace. This is a reproducibility requirement: V1 discovery matches
`source_author` filenames and V1 acquisition discovery matches
`source_authority_*.txt` prompts. New files must not enter either frozen V1
discovery set. The V2 experiment directory is separate from the V1 directory.
Neither V1 packaging code, manifest, evidence, nor attribute rules are edited.

## Commands

Run with Python 3.11 or later and Git in a complete repository checkout:

```text
python scripts/package_authority_certificate_v2.py prepare
python scripts/package_authority_certificate_v2.py freeze
python scripts/package_authority_certificate_v2.py check
```

`prepare` writes `dependency_inventory.json`. It pins the audit anchor, V1
payload, published V1 manifest/archive digests, raw-byte SHA-256 and Git blob
identity of every V1 package file, all pre-existing anchor blobs, and comparator
locations. It verifies the locally present V1 files against those references.
It does not copy their evidence bytes, call a provider, or run a Mission.
Rerunning prepare is idempotent and refuses to overwrite a changed inventory.

Every tracked path present at the audit anchor is protected against edits or
deletion. The sole exception is `.gitattributes`: its old rules must remain an
exact text prefix and appended rules must target only new V2 paths and specify
`-text`. Existing old source portability is checked using Git content
preservation, leaving old CRLF/LF-sensitive worktree byte pins untouched.
Published V1 package bytes already have scoped `-text` attributes, so their
dependency references are checked as exact raw bytes.

`freeze` must run only after final V2 results and report exist. It hashes raw
bytes of every new experiment file plus all `authority_certificate_v2` source,
script, test, and prompt paths. The immutable V1 packaging helper is included
as a small dependency; only its generic path, hashing, Git, attribute, and ZIP
functions are imported. Additional new paths can be specified with
`--include repository/relative/path` and require scoped `-text` attributes.
Temporary files, caches, ZIPs, and the content manifest itself are excluded.
No newline, Unicode, JSON, or YAML normalization occurs in content hashes.

The manifest does not hash itself. The archive includes that manifest and uses
the unchanged V1 ZIP policy: sorted member paths, no compression (`ZIP_STORED`),
1980-01-01 timestamps, Unix regular `0644` file attributes, and no extra metadata.
Default output is ignored
`artifacts/source-authority-v2/source-authority-v2.zip`; its external
`source-authority-v2.receipt.json` records archive, content-manifest, dependency
inventory, and external V1 archive digests. Keeping the receipt outside the
package avoids circular hashing. No credentials or environment variables are
collected. Keep validation receipts outside the payload until publication.

`check` verifies V2 raw file bytes, all referenced V1 bytes, immutable anchor
preservation, actual checkout attributes, external receipt, exact archive
reconstruction, safe member inventory, extraction hashes, and rebuilding the
same archive from extracted bytes. An extracted thin archive can be checked
with `--extracted-only`, which explicitly reports that external V1 bytes, Git
anchor preservation, and checkout attributes were not checked. Full reproduction
requires the pinned repository/V1 payload as well as the thin V2 package.

## Fresh checkout validation

After the final payload commit, create fresh checkouts with
`core.autocrlf=true` and `core.autocrlf=false`. In both, run V2 `freeze` and
`check`; compare manifest and archive digests with the original receipt and
confirm that freeze causes no tracked diff. Do not regenerate inventories to
hide a mismatch. Also rerun the unchanged V1 freezer and checker: its original
manifest and archive hashes must remain unchanged at the new commit. This
demonstrates that V2's namespace does not alter V1 discovery or invocability.

Stored latency is immutable evidence, not a promise that model or clock reruns
are deterministic. Packaging verification needs no model requests, Runtime,
Grounder, or skills. Byte equality establishes reproducibility of the stored
experiment, not semantic correctness or held-out generalization.
