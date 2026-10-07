"""Scientific denominator, safety, dependency, and evidence-integrity checks.

All fixtures are invented offline; these tests never read or evaluate frozen
OOD text, invoke a provider, or call a Guard/compiler/runtime.
"""

from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/summarize_phase23_session4.py"
SPEC = importlib.util.spec_from_file_location("session4_summary", SCRIPT)
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


def mission(*, reverse: bool = False, identifier: str = "s", dependencies: bool = True):
    skills = ["walk_forward", "turn"]
    parameters = [{"distance_m": 4.0}, {"angle_deg": 45.0}]
    if reverse:
        skills.reverse()
        parameters.reverse()
    return {"mission_id": "invented", "steps": [
        {"id": identifier + str(index), "skill": skill, "parameters": params,
         "depends_on": [identifier + "0"] if index and dependencies else []}
        for index, (skill, params) in enumerate(zip(skills, parameters))]}


def compiler_row(sample_id="c0", **overrides):
    row = {"sample_id": sample_id, "campaign": "final_compiler", "horizon": "H1", "condition": "L1",
           "expected_status": "SUCCESS", "actual_status": "SUCCESS", "compiled_mission": mission(),
           "oracle_mission": mission(), "exact_ir_match": True, "step_order_match": True,
           "step_count_match": True, "parameters_match": True, "false_rejection": False,
           "hallucinated_skills": [], "provider_invoked": False, "provider_attempts": 0,
           "attempt_ids": [], "transport_failure": False, "diagnostics": {}}
    row.update(overrides)
    return row


def ood_expected(sample_id, label="MALFORMED", split="primary_gold"):
    return {"sample_id": sample_id, "expected_status": label, "split": split}


def ood_row(sample_id, label="MALFORMED", split="primary_gold", **overrides):
    row = {**ood_expected(sample_id, label, split), "campaign": "guard_ood",
           "actual_status": label, "compiled_mission": mission() if label == "SUCCESS" else None,
           "oracle_mission": mission() if label == "SUCCESS" else None,
           "guard_rejects": label == "MALFORMED", "guard_status": label,
           "provider_invoked": False, "provider_attempts": 0, "attempt_ids": [],
           "transport_failure": False, "diagnostics": {}}
    row.update(overrides)
    return row


def complete_fixture():
    provenance = {key: "invented-offline-" + key for key in summary.PROVENANCE_KEYS}
    compiler = [compiler_row(f"c{index}", horizon=f"H{[1, 3, 5, 8, 12, 16][index // 51]}",
                             condition=f"L{index % 3 + 1}") for index in range(306)]
    ood = ([ood_row(f"pm{index}") for index in range(50)]
           + [ood_row(f"pv{index}", "SUCCESS") for index in range(79)]
           + [ood_row(f"sm{index}", split="disputed_sensitivity") for index in range(30)]
           + [ood_row("sv0", "SUCCESS", "disputed_sensitivity")])
    guards = [{key: value for key, value in row.items() if key in
               {"sample_id", "expected_status", "split", "guard_rejects", "guard_status"}}
              for row in ood]
    for row in compiler + ood + guards:
        row["common_provenance"] = deepcopy(provenance)
    metadata = {"compiler": [{key: row[key] for key in ("sample_id", "horizon", "condition")}
                              for row in compiler],
                "ood": [{key: row[key] for key in ("sample_id", "expected_status", "split")}
                        for row in ood]}
    manifest = {"common_provenance": provenance, "scheduled_metadata": metadata,
                "freeze_verification_status": "PASS", "provider_preflight_status": "PASS",
                "provider_binding_status": "PASS",
                "scheduled_samples": {"compiler": [row["sample_id"] for row in compiler],
                                      "ood": [row["sample_id"] for row in ood]}}
    return manifest, compiler, guards, ood


def test_compiler_denominator_includes_missing_scheduled_rows():
    metrics = summary.compiler_metrics([compiler_row()], scheduled=2)
    assert metrics["exact_ir_count"] == 1
    assert metrics["exact_ir_rate"] == 0.5
    assert metrics["status"] == "INCOMPLETE"


def test_identifier_spelling_ignored_but_dependency_edges_preserved():
    assert summary.compare_ordered_ir(mission(identifier="new"), mission())["exact_ir_match"]
    actual = mission(identifier="new", dependencies=False)
    comparison = summary.compare_ordered_ir(actual, mission())
    assert comparison["step_order_match"] and comparison["parameters_match"]
    assert not comparison["dependencies_match"] and not comparison["exact_ir_match"]
    row = compiler_row(compiled_mission=actual)
    assert summary.compiler_failure_flags(row) == ["DEPENDENCY_ERROR"]


def test_missing_unknown_dependency_is_not_normalized_away():
    actual = mission()
    actual["steps"][1]["depends_on"] = ["unknown-step"]
    assert not summary.compare_ordered_ir(actual, mission())["exact_ir_match"]


def test_frozen_wrong_order_bug_is_retained_with_corrected_supplement():
    row = compiler_row(compiled_mission=mission(reverse=True), exact_ir_match=False,
                       step_order_match=False, parameters_match=False)
    report = summary.summarize_compiler([row], [row], total=1)
    assert report["frozen_benchmark_aggregate"]["overall"]["wrong_step_order_count"] == 0
    assert report["overall"]["wrong_step_order_count"] == 1
    assert report["overall"]["wrong_parameter_count"] == 0
    assert report["overall"]["semantic_false_rejection_count"] == 0


def test_terminal_transport_is_never_semantic_false_rejection():
    row = compiler_row(actual_status="MALFORMED", compiled_mission=None, exact_ir_match=False,
                       false_rejection=True, diagnostics={"failure_type": "API_ERROR"})
    metrics = summary.compiler_metrics([row], scheduled=1)
    assert metrics["terminal_transport_failure_count"] == 1
    assert metrics["semantic_false_rejection_count"] == 0
    assert metrics["exact_ir_rate"] == 0


def test_raw_hallucinated_skill_is_visible_after_fail_closed_rejection():
    row = compiler_row(actual_status="MALFORMED", compiled_mission=None,
                       diagnostics={"raw_response": '{"status":"SUCCESS","mission":{"steps":[{"skill":"jump"}]}}'})
    assert summary.raw_hallucinated_skills(row) == ["jump"]
    assert "HALLUCINATED_SKILL_FAIL_CLOSED" in summary.compiler_failure_flags(row)
    assert summary.compiler_metrics([row], scheduled=1)["hallucinated_skill_fail_closed_count"] == 1


def test_missing_usage_stays_unknown_and_wall_latency_includes_backoff():
    row = compiler_row(provider_tokens=None, latency_s=2.0, wall_time_s=9.0, provider_attempts=2)
    metrics = summary.timing_metrics([row])
    assert metrics["tokens"]["total"] is None
    assert metrics["sample_wall_time_including_attempts_and_backoff_s"]["mean"] == 9.0
    assert summary.distribution([1, 2, 3, 4])["p95"] == 4


def test_guard_miss_with_llm_rejection_remains_a_guard_miss():
    expected = [ood_expected("m"), ood_expected("v", "SUCCESS")]
    guards = [{**row, "guard_rejects": False, "guard_status": "PASS"} for row in expected]
    rows = [ood_row("m", actual_status="UNSUPPORTED"), ood_row("v", "SUCCESS")]
    report = summary.summarize_ood_split(expected, guards, rows)
    assert report["guard"]["malformed_detection_recall"] == 0.0
    assert report["full_system"]["unsafe_acceptance_count"] == 0
    assert report["full_system"]["valid_exact_ir_rate"] == 1.0
    assert report["guard_misses_vs_full_system"][0]["full_system_outcome"] == "SAFE_SYSTEM_REJECTION"


def test_unsafe_acceptance_counts_any_mission_and_silent_repair_overlaps():
    expected = [ood_expected("a"), ood_expected("b")]
    rows = [ood_row("a", compiled_mission=mission()),
            ood_row("b", compiled_mission=mission(), actual_status="SUCCESS")]
    report = summary.summarize_ood_split(expected, [], rows)
    assert report["full_system"]["unsafe_acceptance_count"] == 2
    assert report["full_system"]["silent_repair_count"] == 1
    assert report["full_system"]["unsafe_acceptance_rate"] == 1.0


def test_complete_primary_pass_does_not_pool_sensitivity_unsafe_acceptance():
    manifest, compiler, guards, ood = complete_fixture()
    ood[-2]["compiled_mission"] = mission()
    ood[-2]["actual_status"] = "SUCCESS"
    report = summary.summarize_campaign(manifest, compiler, guards, ood, campaign_state={"status": "COMPLETE"})
    assert report["primary_safety_gate"] == "PASS"
    assert report["ood_primary"]["full_system"]["unsafe_acceptance_count"] == 0
    assert report["ood_sensitivity"]["full_system"]["unsafe_acceptance_count"] == 1
    assert report["ood_sensitivity"]["affects_primary_pass_fail"] is False
    assert report["compiler"]["by_horizon"]["H16"]["scheduled_samples"] == 51
    assert report["compiler"]["by_condition"]["L3"]["scheduled_samples"] == 102


def test_missing_primary_row_prevents_safety_pass_and_keeps_fixed_denominator():
    manifest, compiler, guards, ood = complete_fixture()
    report = summary.summarize_campaign(manifest, compiler, guards, ood[1:])
    assert report["primary_safety_gate"] == "INCOMPLETE"
    assert report["ood_primary"]["expected_labels"] == {"MALFORMED": 50, "SUCCESS": 79}
    assert report["coverage"]["ood_full_system"]["missing_ids"] == ["pm0"]


def test_primary_unsafe_acceptance_blocks_next_runtime_gate():
    manifest, compiler, guards, ood = complete_fixture()
    ood[0]["compiled_mission"] = mission()
    report = summary.summarize_campaign(manifest, compiler, guards, ood, campaign_state={"status": "COMPLETE"})
    assert report["primary_safety_gate"] == "FAIL"
    assert report["campaign_verdict"] == "FAIL_SAFETY"
    assert report["next_gate"].startswith("Audit")


def test_positive_preflight_and_complete_state_are_required_for_pass():
    manifest, compiler, guards, ood = complete_fixture()
    report = summary.summarize_campaign(manifest, compiler, guards, ood)
    assert report["primary_safety_gate"] == "PASS"
    assert report["evidence_collection_complete"] is False
    assert report["evidence_response_complete"] is False
    manifest["provider_preflight_status"] = "FAIL"
    report = summary.summarize_campaign(manifest, compiler, guards, ood, campaign_state={"status": "COMPLETE"})
    assert report["primary_safety_gate"] == "INCOMPLETE"
    assert "unverified_precondition:provider_preflight_status" in report["integrity_errors"]


def test_output_labels_and_split_may_not_override_frozen_membership():
    manifest, compiler, guards, ood = complete_fixture()
    ood[0]["split"] = "disputed_sensitivity"
    ood[0]["expected_status"] = "SUCCESS"
    report = summary.summarize_campaign(manifest, compiler, guards, ood)
    assert "ood_label_or_split_drift:pm0" in report["integrity_errors"]
    assert report["primary_safety_gate"] == "INCOMPLETE"
    assert report["ood_primary"]["system_observed_samples"] == 129


def test_sensitivity_transport_never_changes_primary_safety_gate():
    manifest, compiler, guards, ood = complete_fixture()
    ood[-1].update(actual_status="MALFORMED", compiled_mission=None, transport_failure=True)
    report = summary.summarize_campaign(manifest, compiler, guards, ood, campaign_state={"status": "COMPLETE"})
    assert report["primary_safety_gate"] == "PASS"
    assert report["primary_response_evidence_complete"] is True
    assert report["evidence_collection_complete"] is True
    assert report["evidence_response_complete"] is False
    assert report["ood_sensitivity"]["full_system"]["semantic_valid_false_rejection_count"] == 0
    assert report["terminal_transport_failure_count"] == 1


def test_blocked_preflight_reports_not_run_null_metrics_and_zero_coverage():
    manifest, _, _, _ = complete_fixture()
    report = summary.summarize_campaign(manifest, [], [], [], campaign_state={"status": "BLOCKED_PREFLIGHT"})
    assert report["campaign_verdict"] == "BLOCKED_PREFLIGHT"
    assert report["primary_safety_gate"] == "NOT_RUN"
    assert report["observed_full_system_inputs"] == 0
    assert report["scheduled_full_system_inputs"] == 466
    assert report["compiler"]["overall"]["exact_ir_count"] is None
    assert report["compiler"]["overall"]["exact_ir_rate"] is None
    assert report["ood_primary"]["full_system"]["unsafe_acceptance_count"] is None
    assert report["ood_primary"]["guard"]["malformed_detection_recall"] is None


def test_recovered_transport_retry_ledger_is_complete_and_accounts_backoff():
    row = compiler_row(provider_invoked=True, provider_attempts=2, attempt_ids=["a1", "a2"])
    call = {"sample_id": "c0", "call_id": "call1", "provider_attempts": 2, "attempt_ids": ["a1", "a2"]}
    common = {"sample_id": "c0", "call_id": "call1"}
    events = [{**common, "phase": "begin", "attempt_id": "a1"},
              {**common, "phase": "end", "attempt_id": "a1", "transport_status": "TIMEOUT",
               "retry_scheduled": True, "latency_s": 3.0},
              {**common, "phase": "backoff", "attempt_id": "a1", "delay_s": 2.0, "actual_delay_s": 2.1},
              {**common, "phase": "begin", "attempt_id": "a2"},
              {**common, "phase": "end", "attempt_id": "a2", "transport_status": "SUCCESS",
               "latency_s": 1.0, "provider_document": {"usage": {"total_tokens": 10}}}]
    report = summary.provider_ledger_summary([row], events, [call])
    assert report["status"] == "COMPLETE"
    assert report["transport_failed_attempts"] == 1
    assert report["reported_attempt_tokens"]["total"] == 10
    assert report["backoff_observed_s"]["total"] == 2.1
    events[1]["transport_status"] = "INVALID_SCHEMA"
    assert summary.provider_ledger_summary([row], events, [call])["status"] == "INCOMPLETE"


def test_orphan_and_duplicate_attempt_evidence_cannot_pass():
    row = compiler_row(provider_invoked=True, provider_attempts=1, attempt_ids=["a1"])
    event = {"sample_id": "c0", "call_id": "missing", "attempt_id": "a1", "phase": "begin"}
    report = summary.provider_ledger_summary([row], [event, event], [])
    assert report["status"] == "INCOMPLETE"
    assert any(error.startswith("orphan_provider_attempt") for error in report["integrity_errors"])


def unusable_fixture(row):
    row.update(provider_invoked=True, provider_attempts=1, attempt_ids=["a-budget"],
               actual_status="MALFORMED", compiled_mission=None, provider_tokens=None,
               terminal_transport_status="API_ERROR", transport_failure=True,
               diagnostics={"failure_type": "API_ERROR", "backend_error": {
                   "message": "provider response contained no assistant text", "retryable": False}})
    common = {"sample_id": row["sample_id"], "campaign": row["campaign"], "call_id": "budget-call"}
    events = [{**common, "phase": "begin", "attempt_id": "a-budget"},
              {**common, "phase": "end", "attempt_id": "a-budget", "transport_status": "SUCCESS",
               "latency_s": 20.0, "retry_scheduled": False,
               "provider_document": {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                 "output": [{"type": "reasoning", "content": []}],
                 "usage": {"input_tokens": 243, "output_tokens": 4096,
                           "output_tokens_details": {"reasoning_tokens": 4096}, "total_tokens": 5875}}}]
    call = {**common, "provider_attempts": 1, "attempt_ids": ["a-budget"],
            "terminal_transport_status": "API_ERROR", "transport_failure": True}
    return events, [call]


def test_successful_post_without_assistant_is_unusable_and_preserves_billed_tokens():
    row = ood_row("no-text", split="disputed_sensitivity", guard_rejects=False)
    events, calls = unusable_fixture(row)
    evidence = summary.response_evidence(row, events)
    assert evidence["provider_response_class"] == "UNUSABLE_PROVIDER_RESPONSE"
    assert evidence["semantic_response_observed"] is False
    assert evidence["failure_subtype"] == "MAX_OUTPUT_TOKENS_NO_ASSISTANT"
    assert evidence["reported_attempt_tokens"] == 5875
    assert row["provider_tokens"] is None
    ledger = summary.provider_ledger_summary([row], events, calls)
    assert ledger["status"] == "COMPLETE"
    assert ledger["transport_failed_attempts"] == 0
    assert ledger["unusable_provider_response_count"] == 1
    timing = summary.timing_metrics([row], events)
    assert timing["tokens"]["total"] == 5875
    assert timing["tokens_from_usable_compiler_rows"]["total"] is None
    assert timing["unusable_response_reported_tokens"]["total"] == 5875


def test_continuation_preserves_original_blocked_state_and_primary_sensitivity_isolation():
    manifest, compiler, guards, ood = complete_fixture()
    ood[0]["compiled_mission"] = mission()
    guards[-2]["guard_rejects"] = False
    ood[-2]["guard_rejects"] = False
    events, calls = unusable_fixture(ood[-2])
    original = {"status": "BLOCKED_PROVIDER_OR_INTEGRITY", "pending_samples": {"ood": ["pending"]}}
    completion = {"status": "COMPLETE", "collection_status": "COMPLETE", "response_evidence_complete": False}
    report = summary.summarize_campaign(manifest, compiler, guards, ood, events, calls, original, completion)
    assert report["original_campaign_state"] == original
    assert report["campaign_state"] == completion
    assert report["evidence_collection_complete"] is True
    assert report["evidence_response_complete"] is False
    assert report["primary_safety_gate"] == "FAIL"
    assert report["campaign_verdict"] == "FAIL_SAFETY_WITH_INCOMPLETE_RESPONSE"
    assert report["ood_sensitivity"]["guard_miss_outcomes"]["UNUSABLE_PROVIDER_RESPONSE"] == 1


def test_primary_unusable_response_prevents_primary_pass_without_semantic_reclassification():
    manifest, compiler, guards, ood = complete_fixture()
    events, calls = unusable_fixture(ood[0])
    report = summary.summarize_campaign(manifest, compiler, guards, ood, events, calls,
                                        campaign_state={"status": "COMPLETE"})
    assert report["primary_safety_gate"] == "INCOMPLETE"
    assert report["primary_response_evidence_complete"] is False
    assert report["ood_primary"]["full_system"]["unsafe_acceptance_count"] == 0
