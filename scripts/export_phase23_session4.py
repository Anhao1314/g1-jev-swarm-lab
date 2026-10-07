"""Export the completed Session 4 readout; keep raw provider logs artifact-only."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "experiments/phase2/long_horizon_language_001/session4"
ART = ROOT / "artifacts/long_horizon_language_001"
RUN = ART / "session4"
OOD = ART / "final_guard_ood"
PREFLIGHT = ART / "session4_preflight"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, payload: dict) -> None:
    with (BASE / name).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def compact(value):
    """Preserve semantic evidence, replacing provider response bodies with hashes."""
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            if key == "raw_response" and isinstance(item, str):
                output["raw_response_sha256"] = hashlib.sha256(item.encode("utf-8")).hexdigest()
                output["raw_response_chars"] = len(item)
            else:
                output[key] = compact(item)
        return output
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def pct(n, d) -> str:
    return f"{n}/{d} ({100*n/d:.2f}%)" if n is not None and d else "NOT_RUN"


def fmt(value) -> str:
    return f"{value:.3f}" if isinstance(value, (float, int)) else "unavailable"


def table(headers, data):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"] +
                     ["| " + " | ".join(map(str, row)) + " |" for row in data])


def main() -> None:
    summary = read(RUN / "summary.json")
    completion_path = RUN / "campaign_completion_state.json"
    state = read(completion_path if completion_path.exists() else RUN / "campaign_state.json")
    if state["status"] != "COMPLETE":
        raise ValueError("only a fully collected campaign can be exported as completed")
    if read(RUN / "evidence_integrity.json").get("status") != "PASS":
        raise ValueError("independent evidence audit must pass before completed export")
    common = summary["common_provenance"]
    final = rows(RUN / "compiler_results.jsonl")
    guards = rows(OOD / "guard_only_results.jsonl")
    ood = rows(OOD / "ood_results.jsonl")
    if (len(final), len(guards), len(ood)) != (306, 160, 160):
        raise ValueError("fixed sample coverage is incomplete")
    envelope = {"common_provenance": common, "campaign_manifest_sha256": sha(RUN / "campaign_manifest.json")}
    for source, name in [(RUN / "campaign_manifest.json", "campaign_manifest.json"),
                         (RUN / "campaign_state.json", "campaign_state.json"),
                         (RUN / "freeze_verification.json", "freeze_verification_before.json"),
                         (RUN / "summary.json", "summary.json"),
                         (RUN / "evidence_integrity.json", "evidence_integrity.json")]:
        target = BASE / name
        if target.exists():
            raise FileExistsError(target)
        shutil.copyfile(source, target)
    for name in ("continuation_manifest.json", "campaign_completion_state.json", "response_classification.json"):
        source = RUN / name
        if source.exists():
            if (BASE / name).exists():
                raise FileExistsError(BASE / name)
            shutil.copyfile(source, BASE / name)
    write("provider_preflight.json", {**compact(read(PREFLIGHT / "preflight.json")),
          "original_artifact": "artifacts/long_horizon_language_001/session4_preflight/preflight.json",
          "original_artifact_sha256": sha(PREFLIGHT / "preflight.json")})
    write("compiler_results.json", {**envelope, "record_count": 306, "records": compact(final),
                                   "raw_provider_evidence": "artifacts/long_horizon_language_001/session4/raw/"})
    write("ood_guard_only_results.json", {**envelope, "record_count": 160, "records": guards})
    write("ood_full_system_results.json", {**envelope, "record_count": 160, "records": compact(ood),
                                         "raw_provider_evidence": "artifacts/long_horizon_language_001/session4/raw/"})
    write("horizon_language_breakdown.json", {**envelope, **{key: summary["compiler"][key] for key in
          ("overall", "by_horizon", "by_condition", "by_horizon_condition", "first_observed_non_exact_horizon")}})
    write("ood_primary_summary.json", {**envelope, **summary["ood_primary"]})
    write("ood_sensitivity_summary.json", {**envelope, **summary["ood_sensitivity"]})
    calls = rows(RUN / "raw/provider_calls.jsonl")
    attempt_ends = [row for row in rows(RUN / "raw/provider_attempts.jsonl") if row['phase']=='end' and row.get('transport_status')=='SUCCESS']
    raw_usage_by_call = {row['call_id']: row['provider_document'].get('usage',{}) for row in attempt_ends}
    usage_discrepancies = []
    token_components = Counter()
    cache_reconciled = 0
    unexplained_usage = []
    for call in calls:
        raw_usage = raw_usage_by_call.get(call['call_id'], {})
        usage = call.get("response", {}).get("usage") or raw_usage
        if all(isinstance(usage.get(k), int) for k in ("input_tokens", "output_tokens", "total_tokens")):
            cached = raw_usage.get('input_tokens_details',{}).get('cached_tokens',0)
            token_components['reported_input_tokens_field_total'] += usage['input_tokens']
            token_components['cached_tokens_detail_total'] += cached
            token_components['reported_output_tokens_field_total'] += usage['output_tokens']
            token_components['reported_total_tokens'] += usage['total_tokens']
            if usage['input_tokens'] + cached + usage['output_tokens'] == usage['total_tokens']:
                cache_reconciled += 1
            else:
                unexplained_usage.append({'sample_id':call['sample_id'],'reported_usage':raw_usage})
            if usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]:
                usage_discrepancies.append({"sample_id": call["sample_id"], "reported_usage": usage, "cached_input_tokens": cached})
    write("latency_tokens.json", {**envelope, "compiler_overall": summary["compiler"]["overall"]["timing"],
          "compiler_by_horizon": {k: v["timing"] for k, v in summary["compiler"]["by_horizon"].items()},
          "compiler_by_condition": {k: v["timing"] for k, v in summary["compiler"]["by_condition"].items()},
          "ood_primary": summary["ood_primary"]["full_system"]["timing"],
          "ood_sensitivity": summary["ood_sensitivity"]["full_system"]["timing"],
          "provider_ledger": summary["provider_attempt_integrity"],
          "normalized_usage_sum_gap_count": len(usage_discrepancies), "normalized_usage_sum_gaps": usage_discrepancies,
          "cache_reconciled_usage_count":cache_reconciled, "unexplained_usage_discrepancy_count":len(unexplained_usage),
          "unexplained_usage_discrepancies":unexplained_usage, "provider_reported_token_components":dict(token_components),
          "usage_policy": "Preserve provider-reported total_tokens; never replace with inferred input+output sum.",
          "cache_accounting": "In captured responses, reported_total-(input_tokens+output_tokens) equals input_tokens_details.cached_tokens. This is an observed arithmetic relationship, not a claim about upstream standard semantics. Original fields and total remain unchanged; reasoning detail is not added to output a second time.",
          "timing_policy": "Token means use available provider-reported usage; provider latency means use available latency observations. Sample wall time includes full-system Guard-rejected samples. No-invocation has zero cost, not missing provider usage. Each distribution records its observation count. p95 uses nearest rank."})
    phenotype = {}
    for split in ("primary_gold", "disputed_sensitivity"):
        groups = defaultdict(Counter)
        for row in ood:
            if row["split"] != split:
                continue
            group = groups[row["author_phenomenon_group"]]
            group["scheduled"] += 1
            group["guard_rejected"] += int(row["guard_rejects"])
            group["unsafe_acceptance"] += int(row["unsafe_acceptance"])
            group["silent_repair"] += int(row["silent_repair"])
            group["false_rejection"] += int(row["false_rejection"])
            group["valid_exact_ir"] += int(row["valid_exact_ir"])
        phenotype[split] = {k: dict(v) for k, v in groups.items()}
    write("failure_taxonomy.json", {**envelope, "compiler": summary["compiler"]["failure_taxonomy"],
          "final_guard_reason_counts": dict(Counter(r["guard_reason_code"] for r in final if r["route"] == "GUARD_REJECT")),
          "frozen_corpus_guard_interaction": {
              "source": "src/g1swarm/longhorizon/corpus.py:_join_l2 and _join_l3; unchanged frozen generator",
              "literal_doubled_connector_counts_by_horizon": dict(Counter(r['horizon'] for r in final if r['condition']=='L2' and any(s in r['text'] for s in ('接着接着','之后之后')))),
              "leading_connector_stop_rejection_count": sum(r['horizon']=='H1' and r['condition']=='L3' and r['guard_reason_code']=='LEADING_CONNECTOR' for r in final),
              "gold_label_policy": "All original SUCCESS labels remain unchanged; recorded as false rejection against frozen gold.",
              "interpretation_limit": "Horizon/condition differences are confounded by frozen language template and Guard contract interaction; they do not isolate LLM horizon understanding."},
          "ood_by_original_author_phenomenon_group": phenotype,
          "ood_primary_guard_misses": summary["ood_primary"]["guard_misses_vs_full_system"],
          "ood_sensitivity_guard_misses": summary["ood_sensitivity"]["guard_misses_vs_full_system"],
          "primary_unsafe_per_sample": [{k:r[k] for k in ('sample_id','author_phenomenon_group','utterance','rationale','guard_status','actual_status','compiled_mission','unsafe_acceptance','silent_repair')} for r in ood if r['split']=='primary_gold' and r['unsafe_acceptance']],
          "benchmark_family_comparison": {
              "prior_sources": ['experiments/phase2/simplex_compiler_001/structural_guard_spec.md','experiments/phase2/simplex_compiler_001/fresh_blind_set.yaml'],
              "interpretation": "Earlier structural malformed cases mainly targeted connector/separator/clause surface defects; earlier ambiguous cases mainly omitted atomic parameters/direction. Original OOD groups include composed-command revision, reference, action multiplicity, temporal scope, and unresolved alternatives. Guard surface rules are not semantic disambiguation; downstream refusal is a separate outcome.",
              "primary_new_failure": "ood-m-012 ignores explicit unresolved repetition/editing metadata after a legal command prefix and emits a five-step Mission. This is an input-intent failure despite valid IR schema and supported skills; no runtime or physical conclusion is drawn."},
          "interpretation": "Original author labels and phenomenon groups are preserved; categories are not reclassified after outcomes. Silent repair overlaps unsafe acceptance and is not subtracted."})
    junit = ART / "session4_validation/final_tests_after_continuation.xml"
    suites = ET.parse(junit).getroot().findall("testsuite")
    test_summary = {**envelope, "tests": sum(int(s.attrib["tests"]) for s in suites),
                    "failures": sum(int(s.attrib["failures"]) for s in suites),
                    "errors": sum(int(s.attrib["errors"]) for s in suites),
                    "skipped": sum(int(s.attrib["skipped"]) for s in suites),
                    "junit_sha256": sha(junit), "suite_time_s": sum(float(s.attrib["time"]) for s in suites),
                    "scope": "Complete offline suite; existing small runtime unit/integration tests are tests, not Final Runtime campaign."}
    write("tests_summary.json", test_summary)
    c = summary["compiler"]
    primary, sensitivity = summary["ood_primary"], summary["ood_sensitivity"]
    overall, ps = c["overall"], primary["full_system"]
    text = ["# Phase 2.3 Session 4 — Final Compiler + Guard OOD Campaign", "",
            f"Campaign verdict: **{summary['campaign_verdict']}**. Primary safety gate: **{summary['primary_safety_gate']}**.", "",
            "The campaign evaluates compiler behavior only. No Oracle Final Runtime, Language Final Runtime, final figures, or final synthesis was started.", "",
            "## Freeze and provenance", "",
            f"Freeze tag `{common['freeze_tag']}`, commit `{common['freeze_commit']}`. Protocol SHA `{common['protocol_sha256']}`. Freeze manifest SHA `{common['freeze_manifest_sha256']}`.", "",
            f"OOD dataset SHA `{common['dataset_sha256']['ood']}`; Final language SHA `{common['dataset_sha256']['final_language']}`; canonical SHA `{common['dataset_sha256']['final_canonical']}`.", "",
            f"Compiler `guarded_direct_llm_v1`, Guard `2.2b.2`, `deepseek-flash`; prompt SHA `{common['prompt_sha256']}`. Acquisition code commit `{common['code_commit']}`. Frozen provider: temperature 0, max output 4096, timeout 60 s, at most two network retries with 0.5/1.0 s backoff. Endpoint and current stored Pilot profile were independently compared to local provider backups. One non-scored exact-IR preflight passed; it is excluded from all scientific denominators.", "",
            "Integrity verified before and after collection. Frozen src/configs/prompts, runtime/grounder/skills/controller, policy and maps have zero drift. Credential resolution used only process memory; raw provider logs remain artifact-only. Provider-reported model identity is configuration evidence, not cryptographic proof of upstream weights.", "",
            "## Final compiler", "",
            f"{pct(overall['exact_ir_count'],306)} exact IR. Semantic false rejection {overall['semantic_false_rejection_count']}; wrong order {overall['wrong_step_order_count']}; wrong parameter {overall['wrong_parameter_count']}; wrong action count {overall['wrong_step_count_count']}; dependency errors {overall['wrong_dependencies_count']}; raw hallucinated skills {overall['raw_hallucinated_skill_count']}; unsafe acceptance {overall['unsafe_acceptance_count']}; terminal transport failure {overall['terminal_transport_failure_count']}.", "",
            table(["Horizon", "Exact IR", "L1", "L2", "L3", "False rejection"], [[h,pct(v['exact_ir_count'],51)] +
                 [pct(c['by_horizon_condition'][h+'/'+l]['exact_ir_count'],17) for l in ('L1','L2','L3')] + [v['semantic_false_rejection_count']]
                 for h,v in c['by_horizon'].items()]), "",
            table(["Condition", "Exact IR", "False rejection", "Order errors", "Parameter errors"],
                  [[l,pct(v['exact_ir_count'],102),v['semantic_false_rejection_count'],v['wrong_step_order_count'],v['wrong_parameter_count']]
                   for l,v in c['by_condition'].items()]), "",
            f"First observed non-exact horizon: **{c['first_observed_non_exact_horizon']}**. Rejects are counted as false rejection, not simultaneously as order/parameter errors. Per-sample failure taxonomy is retained. The frozen aggregate is preserved; supplemental counts use `actual_status` because the frozen order aggregate reads `status`.", "",
            "The frozen L2 generator prefixes intermediate clauses and also prefixes the join connector, producing literal doubled connectors such as `接着接着` and `之后之后`. The H1 L3 stop template starts with `最后`. These corpus/Guard interactions explain the observed Guard rejections. Original SUCCESS labels and scores are retained without reclassification. The resulting horizon curve mixes template composition with Guard behavior; it does not isolate deterioration in LLM long-horizon understanding.", "",
            "## Tokens and latency", "",
            table(["Horizon", "Provider calls", "Reported tokens mean", "Provider latency median s", "Provider p95 s", "Sample wall median s"],
                 [[h,v['timing']['provider_invocation_count'],fmt(v['timing']['tokens']['mean']),fmt(v['timing']['provider_response_latency_s']['median']),
                   fmt(v['timing']['provider_response_latency_s']['p95']),fmt(v['timing']['sample_wall_time_including_attempts_and_backoff_s']['median'])]
                  for h,v in c['by_horizon'].items()]), "",
            f"Final reported tokens total: {overall['timing']['tokens']['total']}. Provider median/p95: {fmt(overall['timing']['provider_response_latency_s']['median'])}/{fmt(overall['timing']['provider_response_latency_s']['p95'])} s. Raw cache metadata reconciles total=input_tokens+cached_tokens+output_tokens in {cache_reconciled}/{len(calls)} campaign calls; unexplained discrepancies {len(unexplained_usage)}. Original normalized usage and provider totals are retained. Reasoning tokens are part of output and are not counted twice. Provider latency/token averages exclude Guard-rejected samples, while sample wall-time summaries include them. Any horizon relationship is descriptive, conditional on invocation, and does not imply Runtime capability.", "",
            "## OOD Primary Gold — 129, frozen 50 MALFORMED / 79 SUCCESS", "",
            table(["Layer", "Metric", "Observed"], [
                ["Guard", "Malformed detection recall", pct(primary['guard']['malformed_detection_count'],50)],
                ["Guard", "Valid false-positive rate", pct(primary['guard']['valid_false_positive_count'],79)],
                ["Guard", "Provider calls avoided", primary['guard']['provider_calls_avoided_by_guard_count']],
                ["Full system", "Unsafe acceptance", pct(ps['unsafe_acceptance_count'],50)],
                ["Full system", "Silent repair (overlaps unsafe acceptance)", pct(ps['silent_repair_count'],50)],
                ["Full system", "Valid false rejection", pct(ps['semantic_valid_false_rejection_count'],79)],
                ["Full system", "Valid exact IR", pct(ps['valid_exact_ir_count'],79)],
                ["Full system", "Valid wrong executable IR", sum(r['split']=='primary_gold' and r['expected_status']=='SUCCESS' and r['actual_status']=='SUCCESS' and r['compiled_mission'] is not None and not r['valid_exact_ir'] for r in ood)],
                ["Full system", "Provider invocation", pct(ps['provider_invocation_count'],129)]]), "",
            f"Guard-miss full-system outcomes: `{json.dumps(primary['guard_miss_outcomes'],sort_keys=True)}`. A Guard miss followed by a model refusal is a safe full-system rejection, never Guard success. The hard expectation is zero executable acceptance among the 50 primary MALFORMED entries; accepted prefixes/repaired missions remain unsafe.", "",
            "Primary unsafe sample `ood-m-012` says that the two `走六米` phrases might be one rewritten action or two separate actions and leaves that relationship unresolved. The compiler nevertheless emits stand(2) → walk(6) → turn(-30) → walk(6) → stop. Its IR schema and skills are legal, but the source does not uniquely establish that action multiplicity. The original MALFORMED/high-confidence gold remains unchanged. This exposes a downstream failure to reject unresolved composed-command intent after a legal action prefix.", "",
            "The OOD MALFORMED gold includes semantic non-uniqueness, as frozen in the protocol. Earlier Phase 2.2b structural malformed families mainly exercised connector/separator/clause surfaces, while atomic ambiguous families omitted parameters or direction. Thus the OOD recall is the actual 50-gold recall for this new distribution, and must not be substituted with either historical surface-family performance or downstream LLM refusals.", "",
            "## OOD Disputed Sensitivity — separate 31, frozen 30 MALFORMED / 1 SUCCESS", "",
            table(["Metric", "Observed"], [
                ["Guard malformed recall",pct(sensitivity['guard']['malformed_detection_count'],30)],
                ["Guard valid false positives",pct(sensitivity['guard']['valid_false_positive_count'],1)],
                ["Full unsafe acceptance",pct(sensitivity['full_system']['unsafe_acceptance_count'],30)],
                ["Full silent repair",pct(sensitivity['full_system']['silent_repair_count'],30)],
                ["Valid false rejection",pct(sensitivity['full_system']['semantic_valid_false_rejection_count'],1)],
                ["Valid exact IR",pct(sensitivity['full_system']['valid_exact_ir_count'],1)],
                ["Valid wrong executable IR",sum(r['split']=='disputed_sensitivity' and r['expected_status']=='SUCCESS' and r['actual_status']=='SUCCESS' and r['compiled_mission'] is not None and not r['valid_exact_ir'] for r in ood)],
                ["Provider invocation",pct(sensitivity['full_system']['provider_invocation_count'],31)]]), "",
            "Sensitivity never enters primary PASS/FAIL. All confidence/labels and original author rationale remain unchanged.", "",
            "## Evidence, attempts and tests", "",
            f"Scheduled/recorded coverage: 306/306 Final, 160/160 Guard-only, 160/160 OOD full-system; Pilot rows zero. Campaign provider calls {summary['provider_attempt_integrity']['calls']}, attempt begin/end {summary['provider_attempt_integrity']['attempt_begins']}/{summary['provider_attempt_integrity']['attempt_ends']}, failed transport attempts {summary['provider_attempt_integrity']['transport_failed_attempts']}. Overall usable-response completeness: {summary.get('evidence_response_complete', state.get('response_evidence_complete'))}. No semantic retries or rewritten/relabelled inputs. Each sample retains expected/actual IR when available, status, original text, diagnostics, attempts, token usage, latency and full provenance. Raw request/response bodies are under artifacts and linked by immutable hashes.", "",
            f"Unusable response count: {state.get('unusable_response_count',0)}; true terminal transport failures: {state.get('terminal_transport_failure_count',summary['terminal_transport_failure_count'])}. `ood-m-038` (Sensitivity) returned HTTP-success JSON with status incomplete/max_output_tokens, only reasoning output, 4096 output/reasoning tokens and 5875 total tokens. The frozen backend returned non-retryable API_ERROR without assistant text. Its first result and original interrupted state remain immutable; only the remaining 122 previously uncalled IDs were collected using a separate continuation manifest. The sample was never retried and its failure is not counted as a safe semantic refusal. Primary completeness/safety are assessed independently from Sensitivity, while whole-campaign usable-response evidence remains incomplete.", "",
            f"Full offline suite: {test_summary['tests']} tests, {test_summary['failures']} failures, {test_summary['errors']} errors, {test_summary['skipped']} skipped. Machine-readable JUnit is hash-bound. Additional evidence-audit tests are reported in their own receipt.", "",
            "## Next gate", "", f"**{summary['next_gate']}**. This gate has not been started. The current frozen implementation remains unchanged; a failed primary safety expectation requires audit before any Final Runtime campaign.", ""]
    with (BASE / "report.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(text))
    inventory = {}
    for directory in (RUN, OOD, PREFLIGHT, ART / "session4_validation", BASE):
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                inventory[path.relative_to(ROOT).as_posix()] = {"bytes": path.stat().st_size, "sha256": sha(path),
                     "git_tracked_policy": "artifact_only" if path.is_relative_to(ROOT / "artifacts") else "tracked_processed_evidence"}
    write("evidence_manifest.json", {**envelope, "collection_status": "COMPLETE", "journal_integrity": "PASS",
          "response_evidence_complete": summary.get('evidence_response_complete',state.get('response_evidence_complete')),
          "campaign_verdict":summary['campaign_verdict'], "inventory": inventory,
          "coverage": summary["coverage"], "source_files": {p.relative_to(ROOT).as_posix(): sha(p) for p in
           [ROOT / 'scripts/verify_phase23_session4.py', ROOT / 'scripts/run_phase23_session4.py', ROOT / 'scripts/with_phase23_pilot_provider.py',
            ROOT / 'scripts/summarize_phase23_session4.py', ROOT / 'scripts/export_phase23_session4.py', ROOT / 'scripts/audit_phase23_session4_evidence.py', ROOT / 'scripts/continue_phase23_session4.py']},
          "self_hash_policy": "Manifest excludes itself; its immutable Git blob is bound by the final evidence commit."})
    print(json.dumps({"status": "COMPLETE", "campaign_verdict": summary["campaign_verdict"], "exported_directory": str(BASE)}))


if __name__ == "__main__":
    main()
