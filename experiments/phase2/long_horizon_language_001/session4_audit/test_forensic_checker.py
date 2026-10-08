"""Offline integrity perturbations in memory; no SUT/model/network invocation."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("session4_forensic_checker", HERE / "verify_safety_chain.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def packet():
    sid = "ood-m-012"
    source = next(x for _, x in checker.numbered(checker.BASE / "ood/guard_ood_dataset.jsonl") if x['candidate_id']==sid)
    guard = next(x for _, x in checker.numbered(checker.OOD / "guard_only_results.jsonl") if x['sample_id']==sid)
    result = next(x for _, x in checker.numbered(checker.OOD / "ood_results.jsonl") if x['sample_id']==sid)
    events = [x for _, x in checker.numbered(checker.RUN / "raw/provider_attempts.jsonl") if x['sample_id']==sid]
    begin = next(x for x in events if x['phase']=='begin')
    end = next(x for x in events if x['phase']=='end')
    call = next(x for _, x in checker.numbered(checker.RUN / "raw/provider_calls.jsonl") if x['sample_id']==sid)
    compact = next(x for x in json.loads((checker.BASE / 'session4/ood_full_system_results.json').read_text(encoding='utf-8'))['records'] if x['sample_id']==sid)
    prompt = (checker.ROOT / 'prompts/llm_mission_compiler_v1.txt').read_text(encoding='utf-8')
    return deepcopy([source, guard, result, begin, end, call, compact, prompt])


def test_saved_chain_is_consistent():
    assert all(checker.chain_checks(*packet()).values())


def test_request_must_include_ambiguity_tail():
    p=packet(); p[3]['request_payload']['input'][1]['content']=p[0]['utterance'].split('。')[0]+'。'
    assert not checker.chain_checks(*p)['full_source_in_request']


def test_legal_shape_does_not_override_recorded_unsafe_predicate():
    p=packet(); p[2]['unsafe_acceptance']=False
    assert p[2]['diagnostics']['validation']['valid']
    assert not checker.chain_checks(*p)['frozen_evaluator_predicate_consistency']


def test_wrong_call_link_is_detected():
    p=packet();p[5]['call_id']='call-unrelated'
    assert not checker.chain_checks(*p)['call_links']


def test_compact_response_hash_is_checked():
    p=packet();p[6]['diagnostics']['raw_response_sha256']='wrong'
    assert not checker.chain_checks(*p)['compact_raw_response_hash']


def test_empty_first_dependency_serialization_is_equivalent():
    p=packet();d=deepcopy(p[2]['compiled_mission']);del d['steps'][0]['depends_on']
    assert checker.mission_shape(d)==checker.mission_shape(p[2]['compiled_mission'])


def test_real_dependency_loss_is_not_equivalent():
    p=packet();p[2]['result']['mission']['steps'][2]['depends_on']=[]
    assert not checker.chain_checks(*p)['envelope_and_mission_links']


def test_split_or_confidence_drift_is_not_accepted():
    p=packet();p[0]['split']='disputed_sensitivity'
    assert not checker.chain_checks(*p)['split_confidence_consistency']
