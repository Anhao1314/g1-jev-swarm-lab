"""Read-only Phase 2.3 Session 4 integrity verifier.

This module reads only frozen research files and Git metadata. It does not
import or invoke the Guard, compiler, provider, runtime, or credential code.
The optional output file is created exclusively; existing evidence is never
overwritten. Import ``verify`` from the campaign harness before evaluation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
BASE = Path("experiments/phase2/long_horizon_language_001")
FREEZE_TAG = "phase2.3-final-protocol-freeze"
FREEZE_COMMIT = "3b619e7f189cf632f03f0b68070671fb534aeb7d"
BRANCH = "phase2.3/long-horizon-language"
PROTOCOL_SHA = "32f035daef911b4a3d6c2dfef32f1d1387fe4e8bf7694894b1397262b60d388a"
OOD_SHA = "6a04d5f2e40841fe18c89d72e1a4424f01779be1caa219a9f17e6ca4fb4f8f3e"
MANIFEST_SHA = "4af7d7f4de2b2bfd03b67eeb8be3ebd668263a63e4b28083dda0629a3415a777"
PROMPT_SHA = "913346508791ab86f80247f2b6315d6e96f9b5066090299ada2196aeb0e3c110"
HORIZONS = {"H1": 1, "H3": 3, "H5": 5, "H8": 8, "H12": 12, "H16": 16}
CONDITIONS = ("L1", "L2", "L3")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, encoding="utf-8", stderr=subprocess.DEVNULL
    ).strip()


def verify(repo: str | Path | None = None) -> dict[str, Any]:
    """Return auditable integrity checks; never evaluate language or use secrets."""
    root = Path(repo).resolve() if repo is not None else ROOT
    base = root / BASE
    checks: list[dict[str, Any]] = []
    manifest_checks: list[dict[str, Any]] = []
    baseline_checks: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {
        "protocol_sha256": None,
        "dataset_sha256": None,
        "ood_dataset_sha256": None,
        "final_dataset_sha256": None,
        "canonical_dataset_sha256": None,
        "freeze_manifest_sha256": None,
        "freeze_tag": FREEZE_TAG,
        "freeze_commit": None,
        "compiler_provenance": None,
        "prompt_sha256": None,
        "code_commit": None,
        "source_commit": None,
    }
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "experiment_id": "long_horizon_language_001",
        "session": "Phase 2.3 Session 4",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "verification_scope": "offline integrity only; no Guard/compiler/provider/runtime invocation",
        "checks": checks,
        "manifest_hash_checks": manifest_checks,
        "baseline_file_checks": baseline_checks,
    }

    def check(category: str, name: str, actual: Any, expected: Any) -> None:
        checks.append({"category": category, "name": name, "expected": expected,
                       "actual": actual, "passed": actual == expected})

    def path_from_manifest(relative: str) -> Path:
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("frozen manifest path leaves repository")
        if resolved.name.lower() in {".env", "auth.json", "credentials.json"}:
            raise ValueError("credential file is outside verifier scope")
        return resolved

    try:
        manifest = _json(base / "freeze_manifest.json")
        protocol = _yaml(base / "protocol.yaml")
        audit = _json(base / "frozen_baseline_audit.json")
        branch = _git(root, "branch", "--show-current")
        commit = _git(root, "rev-parse", "HEAD")
        tag_commit = _git(root, "rev-parse", f"refs/tags/{FREEZE_TAG}^{{commit}}")
        tag_type = _git(root, "cat-file", "-t", f"refs/tags/{FREEZE_TAG}")
        report["branch"] = branch
        report["tag_object"] = _git(root, "rev-parse", f"refs/tags/{FREEZE_TAG}")
        provenance.update(
            protocol_sha256=_sha(base / "protocol.yaml"),
            freeze_manifest_sha256=_sha(base / "freeze_manifest.json"),
            ood_dataset_sha256=_sha(base / "ood/guard_ood_dataset.jsonl"),
            final_dataset_sha256=_sha(base / "final/language_realizations_final.yaml"),
            canonical_dataset_sha256=_sha(base / "final/canonical_missions_final.yaml"),
            freeze_commit=tag_commit,
            prompt_sha256=_sha(root / "prompts/llm_mission_compiler_v1.txt"),
            compiler_provenance=manifest["compiler_provenance"],
            code_commit=commit,
            source_commit=commit,
        )
        provenance["dataset_sha256"] = provenance["final_dataset_sha256"]
        check("git_binding", "branch", branch, BRANCH)
        check("git_binding", "annotated_tag", tag_type, "tag")
        check("git_binding", "resolved_freeze_commit", tag_commit, FREEZE_COMMIT)
        descendant = subprocess.run(
            ["git", "merge-base", "--is-ancestor", FREEZE_COMMIT, commit],
            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
        check("git_binding", "code_commit_descends_from_freeze", descendant, True)
        frozen_manifest = subprocess.check_output(
            ["git", "show", f"{FREEZE_COMMIT}:{BASE.as_posix()}/freeze_manifest.json"],
            cwd=root, stderr=subprocess.DEVNULL,
        )
        check("git_binding", "manifest_bytes_equal_freeze_commit",
              (base / "freeze_manifest.json").read_bytes() == frozen_manifest, True)
        for name, actual, expected in (
            ("protocol_sha256", provenance["protocol_sha256"], PROTOCOL_SHA),
            ("ood_dataset_sha256", provenance["ood_dataset_sha256"], OOD_SHA),
            ("freeze_manifest_sha256", provenance["freeze_manifest_sha256"], MANIFEST_SHA),
            ("prompt_sha256", provenance["prompt_sha256"], PROMPT_SHA),
            ("protocol_frozen", protocol["frozen"], True),
            ("protocol_status", protocol["status"], "frozen"),
            ("manifest_frozen", manifest["frozen"], True),
            ("manifest_status", manifest["freeze_status"], "FROZEN_READY_FOR_FINAL"),
            ("manifest_commit_ref", manifest["freeze_commit"], f"refs/tags/{FREEZE_TAG}"),
        ):
            check("frozen_identity", name, actual, expected)

        refs = [(key, manifest[key]["path"], manifest[key]["sha256"]) for key in
                ("protocol", "canonical_corpus", "language_corpus", "final_corpus_manifest",
                 "pilot_exclusion", "leakage_audit")]
        for group in ("evidence_files", "freeze_tooling"):
            refs.extend((group, path, digest) for path, digest in manifest[group].items())
        refs.extend(("validation_evidence", (BASE / path).as_posix(), digest)
                    for path, digest in manifest["validation_evidence"].items())
        refs.append(("frozen_baseline_audit", (BASE / "frozen_baseline_audit.json").as_posix(),
                     manifest["frozen_baseline_audit_sha256"]))
        for group, path, expected in refs:
            actual = _sha(path_from_manifest(path))
            manifest_checks.append({"group": group, "path": path, "expected_sha256": expected,
                                    "actual_sha256": actual, "passed": actual == expected})
            check("manifest_reference_hash", path, actual, expected)
        check("inventory", "manifest_reference_count", len(refs), 25)
        check("inventory", "baseline_file_count", len(audit["files"]), 143)
        check("baseline", "historical_drift_count", audit["drift_count"], 0)
        for path, frozen in audit["files"].items():
            actual_sha = _sha(path_from_manifest(path))
            actual_blob = _git(root, "hash-object", "--path", path, path)
            baseline_checks.append({"path": path, "expected_sha256": frozen["sha256"],
                                    "actual_sha256": actual_sha, "expected_git_blob": frozen["git_blob"],
                                    "actual_git_blob": actual_blob,
                                    "passed": actual_sha == frozen["sha256"] and actual_blob == frozen["git_blob"]})
            check("baseline_byte_hash", path, actual_sha, frozen["sha256"])
            check("baseline_git_blob", path, actual_blob, frozen["git_blob"])
        motion = audit["motion_policy"]
        check("baseline", "motion_policy_sha256", _sha(path_from_manifest(motion["path"])), motion["sha256"])
        for path, expected in audit["pinned_hash_checks"].items():
            check("baseline_pinned_hash", path, _sha(path_from_manifest(path)), expected)

        # Public scientific configuration only; endpoint/auth environment is never read.
        historical = _yaml(root / "configs/experiments/simplex_compiler_001.yaml")
        historical_protocol = _yaml(root / "experiments/phase2/simplex_compiler_001/protocol.yaml")
        check("compiler_provenance", "phase22b_config_frozen", historical["frozen"], True)
        check("compiler_provenance", "phase22b_protocol_frozen", historical_protocol["frozen"], True)
        provider_fields = ("type", "model", "base_url_env", "api_key_envs", "temperature",
                           "max_output_tokens", "timeout_s", "max_network_retries", "retry_backoff_s")
        for name in provider_fields:
            check("phase22b_provider_match", name, protocol["provider"][name], historical["provider"][name])
            check("phase22b_protocol_provider_match", name,
                  protocol["provider"][name], historical_protocol["provider"][name])
        check("compiler_provenance", "transport_retry_statuses",
              historical["provider"]["network_retry_statuses"], [429, 500, 502, 503, 504])
        check("compiler_provenance", "phase22b_prompt_sha256",
              historical["prompt"]["sha256"], PROMPT_SHA)
        check("compiler_provenance", "phase22b_protocol_prompt_sha256",
              historical_protocol["prompt"]["sha256"], PROMPT_SHA)
        check("compiler_provenance", "frozen_compiler_manifest_vs_protocol",
              manifest["compiler_provenance"], protocol["freeze_candidate"]["compiler_provenance"])
        check("compiler_provenance", "architecture", protocol["selection"]["compiler_architecture"],
              "guarded_direct_llm_v1")
        check("compiler_provenance", "guard_version", protocol["selection"]["guard_version"], "2.2b.2")

        canonical = _yaml(base / "final/canonical_missions_final.yaml")
        language = _yaml(base / "final/language_realizations_final.yaml")
        corpus_manifest = _json(base / "final/final_corpus_manifest.json")
        pilot = _json(base / "pilot_selection.json")
        pilot_language = _yaml(base / "ood/evidence/pilot_language_realizations.yaml")
        missions, samples = canonical["missions"], language["samples"]
        mission_ids = [mission["mission_id"] for mission in missions]
        sample_ids = [sample["sample_id"] for sample in samples]
        pilot_ids = {mission["mission_id"] for mission in pilot["missions"]}
        per_horizon = Counter(mission["horizon"] for mission in missions)
        per_condition = Counter(sample["condition"] for sample in samples)
        pairing: dict[str, Counter] = defaultdict(Counter)
        mission_map = {mission["mission_id"]: mission for mission in missions}
        for sample in samples:
            pairing[sample["mission_id"]][sample["condition"]] += 1
        pairing_errors = [mission_id for mission_id in mission_ids
                          if pairing[mission_id] != Counter({condition: 1 for condition in CONDITIONS})]
        orphan_samples = [sample["sample_id"] for sample in samples if sample["mission_id"] not in mission_map]
        horizon_errors = [sample["sample_id"] for sample in samples
                          if sample["mission_id"] in mission_map and
                          sample["horizon"] != mission_map[sample["mission_id"]]["horizon"]]
        ir_horizon_errors = [mission["mission_id"] for mission in missions
                             if len(mission["steps"]) != HORIZONS.get(mission["horizon"]) or
                             mission["ir_step_count"] != HORIZONS.get(mission["horizon"])]
        id_overlap = sorted(set(mission_ids) & pilot_ids)
        text_overlap = sorted({sample["text"].strip() for sample in samples} &
                              {sample["text"].strip() for sample in pilot_language["samples"]})
        report["final_membership"] = {"canonical_missions": len(missions), "language_inputs": len(samples),
                                     "per_horizon": dict(per_horizon), "per_condition": dict(per_condition),
                                     "pilot_missions_excluded": len(pilot_ids),
                                     "pilot_id_overlap_count": len(id_overlap),
                                     "pilot_text_overlap_count": len(text_overlap)}
        for name, actual, expected in (
            ("canonical_count", len(missions), 102), ("language_count", len(samples), 306),
            ("unique_canonical_ids", len(set(mission_ids)), 102),
            ("unique_language_ids", len(set(sample_ids)), 306),
            ("missions_per_horizon", dict(per_horizon), {h: 17 for h in HORIZONS}),
            ("inputs_per_condition", dict(per_condition), {c: 102 for c in CONDITIONS}),
            ("exact_three_condition_pairing", pairing_errors, []),
            ("orphan_language_samples", orphan_samples, []),
            ("paired_sample_horizon_errors", horizon_errors, []),
            ("canonical_ir_horizon_errors", ir_horizon_errors, []),
            ("pilot_count", len(pilot_ids), 18), ("pilot_exclusion_flag", pilot["excluded_from_final"], True),
            ("declared_pilot_exclusions", sorted(canonical["excluded_pilot_missions"]), sorted(pilot_ids)),
            ("pilot_final_id_overlap", id_overlap, []),
            ("pilot_final_text_overlap_count", len(text_overlap), 0),
            ("canonical_final_flag", canonical["final"], True),
            ("language_final_flag", language["final"], True),
            ("declared_language_conditions", language["conditions"], list(CONDITIONS)),
            ("manifest_canonical_count", corpus_manifest["missions"], 102),
            ("manifest_language_count", corpus_manifest["samples"], 306),
        ):
            check("final_membership", name, actual, expected)

        ood = _rows(base / "ood/guard_ood_dataset.jsonl")
        originals = _rows(base / "ood/authoring/guard_ood_candidates.jsonl")
        ood_manifest = _json(base / "ood/manifest.json")
        ood_ids = [row["candidate_id"] for row in ood]
        check("ood_membership", "total_count", len(ood), 160)
        check("ood_membership", "unique_candidate_ids", len(set(ood_ids)), 160)
        check("ood_membership", "original_candidate_count", len(originals), 160)
        check("ood_membership", "original_candidate_order", ood_ids,
              [row["candidate_id"] for row in originals])
        source_errors, confidence_errors = [], []
        for line, (row, source) in enumerate(zip(ood, originals), 1):
            if {key: row.get(key) for key in source} != source or row.get("source_line") != line:
                source_errors.append(row["candidate_id"])
            expected_split = {"high": "primary_gold", "low": "disputed_sensitivity"}.get(row["confidence"])
            if expected_split is None or row["split"] != expected_split:
                confidence_errors.append(row["candidate_id"])
        check("ood_membership", "original_fields_and_source_lines_preserved", source_errors, [])
        check("ood_membership", "confidence_only_split", confidence_errors, [])
        split_summary = {}
        expected_splits = {
            "primary_gold": {"count": 129, "labels": {"MALFORMED": 50, "SUCCESS": 79}, "confidence": "high", "hard_gate": True},
            "disputed_sensitivity": {"count": 31, "labels": {"MALFORMED": 30, "SUCCESS": 1}, "confidence": "low", "hard_gate": False},
        }
        for split, expected in expected_splits.items():
            rows = [row for row in ood if row["split"] == split]
            labels = dict(Counter(row["expected_status"] for row in rows))
            confidences = dict(Counter(row["confidence"] for row in rows))
            ids = [row["candidate_id"] for row in rows]
            frozen_split = ood_manifest["splits"][split]
            split_summary[split] = {"count": len(rows), "labels": labels, "confidence": confidences,
                                    "hard_gate": frozen_split["hard_gate"], "ids": ids}
            check("ood_membership", f"{split}_count", len(rows), expected["count"])
            check("ood_membership", f"{split}_labels", labels, expected["labels"])
            check("ood_membership", f"{split}_confidence", confidences, {expected["confidence"]: expected["count"]})
            check("ood_membership", f"{split}_manifest_membership", ids, frozen_split["ids"])
            check("ood_membership", f"{split}_manifest_count", frozen_split["count"], expected["count"])
            check("ood_membership", f"{split}_manifest_labels", frozen_split["labels"], expected["labels"])
            check("ood_membership", f"{split}_hard_gate", frozen_split["hard_gate"], expected["hard_gate"])
        report["ood_membership"] = {"total": len(ood), "splits": split_summary}
        check("ood_membership", "sensitivity_never_affects_primary",
              protocol["guard_ood_frozen_policy"]["disputed_sensitivity"]["affects_primary_pass_fail"], False)
        check("ood_membership", "ood_manifest_dataset_hash", ood_manifest["dataset_sha256"], OOD_SHA)
    except Exception as exc:
        # No exception payload is exposed: it could contain unreviewed source data.
        checks.append({"category": "verification_error", "name": "complete_verification",
                       "expected": "all reads/checks completed", "actual": type(exc).__name__, "passed": False})

    issues = [f"{row['category']}:{row['name']}" for row in checks if not row["passed"]]
    categories = Counter(row["category"] for row in checks)
    report.update(provenance)
    report.update(
        provenance=provenance, status="BLOCKED" if issues else "PASS",
        verdict="BLOCKED" if issues else "PASS", issues=issues,
        check_counts={"total": len(checks), "passed": len(checks) - len(issues),
                      "failed": len(issues), "by_category": dict(categories)},
        manifest_reference_count=len(manifest_checks), baseline_file_count=len(baseline_checks),
        baseline_drift_count=sum(not row["passed"] for row in baseline_checks),
        provider_preflight_included=False,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New JSON evidence path; must not already exist")
    args = parser.parse_args()
    result = verify()
    if args.output is not None:
        # Parents are intentionally not created, and the exclusive open prevents replacement.
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps({key: result[key] for key in
                      ("status", "issues", "check_counts", "freeze_commit", "protocol_sha256",
                       "freeze_manifest_sha256", "ood_dataset_sha256", "code_commit")}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
