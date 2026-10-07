# DG-serial additive evidence and source freeze

This treatment retains historical DG4, DD, B and bounded-control files as external dependencies. All 11,551 pre-existing tracked paths are pinned to starting commit 42aa8cd by Git blob, raw checkout SHA and byte length in inputs.json. Historical ood-m-031's unsafe release is also pinned explicitly and remains a separate observation.

The source-only acquisition scaffold, protocol, inputs, source snapshot and all twenty bound file hashes were committed before the first provider call. pre_scored_freeze.json independently references that commit and its raw Git bytes. The runner compares its current source with the exact frozen snapshot before and after collection. No acquisition code, prompt, configuration or source data may change during the run. Analyzer, report and test additions are offline work outside that binding.

New experiment, scripts/serial_certificate_001 and tests/serial_certificate_001 each have their own scoped -text .gitattributes. No old attribute file or old packager is edited. New filenames avoid historical V1 package-discovery patterns. Existing DG4/authority packages and their manifests remain unchanged.

scripts/serial_certificate_001/package_evidence.py creates a thin raw-byte content manifest and deterministic ZIP. The manifest excludes itself; publication_validation.json is outside the bundle to avoid circular hashes. Old dependencies are not duplicated. Rebuild and check the new bundle in clean checkouts with autocrlf true/false using the actual checkout working directory and module ROOT recorded in the receipt.

The inherited all-file raw registry remains specific to the original acquisition checkout. Earlier publication established that pre-existing root attributes and some general text files change line endings under clean checkout settings. Record any such inherited registry failures separately from byte-exact new artifacts and unchanged old Git blobs. Do not normalize scientific hashes or repair old files to claim a complete portable snapshot.

Offline scripts/serial_certificate_001/analyze_pilot.py reconstructs payloads and requires each serial request document to equal historical DG4 bytes. It validates first responses, sanitized wire documents, usage and attempt ledgers; replays the unchanged gate and scorer; checks source/candidate/label binding; and audits non-overlapping one-worker timing and original order. It makes no provider or Runtime call. Report per-request latency separately from sequential campaign wall time and throughput.

Each eligible stage has one semantic output. Resume reuses its durable first response or records interrupted unavailability without a new call. Completed scientific evidence must never be overwritten to remove a previous failure. No Runtime, fresh held-out, extra concurrency/retry treatment or model treatment is part of this package.
