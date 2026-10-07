"""Offline integrity tests. OOD text is never passed to a system under test."""
import hashlib
import json
from pathlib import Path

import yaml

from g1swarm.mission.ir import Mission
from g1swarm.mission.validator import MissionValidator

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'experiments/phase2/long_horizon_language_001'
OOD = BASE / 'ood'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def rows(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_original_artifacts_and_frozen_evidence_are_byte_bound():
    original = read(OOD / 'authoring/candidate_hashes.json')
    for name, digest in original['sha256'].items():
        assert sha(OOD / 'authoring' / name) == digest
    for name, digest in read(OOD / 'hashes.json').items():
        assert sha(OOD / name) == digest
    manifest = read(BASE / 'freeze_manifest.json')
    for name, digest in manifest['evidence_files'].items():
        assert sha(ROOT / name) == digest
    assert sha(OOD / 'manifest.json') == manifest['ood']['manifest_sha256']
    assert sha(OOD / 'hashes.json') == manifest['ood']['hashes_sha256']
    assert sha(BASE / 'frozen_baseline_audit.json') == manifest['frozen_baseline_audit_sha256']
    for name, digest in manifest['freeze_tooling'].items():
        assert sha(ROOT / name) == digest
    mapping = read(OOD / 'mapping_provenance.json')
    assert sha(ROOT / mapping['script']) == mapping['script_sha256']


def test_no_candidate_edits_and_confidence_is_only_split_rule():
    original = rows(OOD / 'authoring/guard_ood_candidates.jsonl')
    frozen = rows(OOD / 'guard_ood_dataset.jsonl')
    manifest = read(OOD / 'manifest.json')
    assert len(original) == len(frozen) == 160
    for line, (source, row) in enumerate(zip(original, frozen), 1):
        assert {key: row[key] for key in source} == source
        assert row['source_line'] == line
        assert row['split'] == ('primary_gold' if source['confidence'] == 'high' else 'disputed_sensitivity')
        assert row['candidate_id'] in manifest['splits'][row['split']]['ids']
    primary = [r for r in frozen if r['split'] == 'primary_gold']
    disputed = [r for r in frozen if r['split'] == 'disputed_sensitivity']
    assert (len(primary), len(disputed)) == (129, 31)
    assert sum(r['expected_status'] == 'MALFORMED' for r in primary) == 50
    assert sum(r['expected_status'] == 'MALFORMED' for r in disputed) == 30
    assert manifest['splits']['disputed_sensitivity']['hard_gate'] is False


def test_mapping_reverse_recovers_author_steps_without_language_execution():
    total = 0
    for row in rows(OOD / 'guard_ood_dataset.jsonl'):
        if row['expected_status'] == 'MALFORMED':
            assert 'expected_mission' not in row and 'expected_steps' not in row
            continue
        mission = Mission.from_dict(row['expected_mission'])
        assert MissionValidator().validate(mission).valid
        recovered = []
        for i, step in enumerate(mission.steps, 1):
            assert step.step_id == f's{i}'
            assert step.depends_on == (() if i == 1 else (f's{i-1}',))
            author = {'action': step.skill.value, **step.parameters}
            if step.skill.value == 'turn':
                author['direction'] = 'left' if author['angle_deg'] > 0 else 'right'
                author['angle_deg'] = abs(author['angle_deg'])
            recovered.append(author)
        assert recovered == row['expected_steps']
        total += len(recovered)
    assert total == 228


def test_overlap_evidence_and_independence():
    audit = read(OOD / 'overlap_audit.json')
    assert len(audit['sources']) == 8
    for source in audit['sources'].values():
        assert sha(ROOT / source['path']) == source['sha256']
        assert source['text_count'] > 0
        assert source['exact_text_overlap_ids'] == source['id_overlap'] == []
    declaration = read(OOD / 'authoring/guard_ood_candidate_manifest.json')
    validation = read(OOD / 'independence_validation.json')
    assert all(declaration[k] is False for k in validation['validated_false_flags'])
    assert validation['candidate_changes'] == []
    for name, digest in validation['source_hashes'].items():
        assert sha(OOD / 'authoring' / name) == digest


def test_frozen_baseline_byte_hashes_and_primary_gate_policy():
    audit = read(BASE / 'frozen_baseline_audit.json')
    assert audit['drift_count'] == 0
    for name, record in audit['files'].items():
        assert sha(ROOT / name) == record['sha256']
    assert sha(ROOT / audit['motion_policy']['path']) == audit['motion_policy']['sha256']
    protocol = yaml.safe_load((BASE / 'protocol.yaml').read_text(encoding='utf-8'))
    policy = protocol['guard_ood_frozen_policy']
    assert policy['disputed_sensitivity']['affects_primary_pass_fail'] is False
    assert 'no hard threshold' in policy['metrics']['guard_malformed_recall']
    assert 'hard expectation count=0' in policy['metrics']['full_system_unsafe_acceptance']
    assert protocol['final_freeze']['campaign_started'] is False
