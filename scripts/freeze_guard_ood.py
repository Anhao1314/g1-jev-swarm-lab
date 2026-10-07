"""Offline OOD integration: no language compiler, Guard, provider, or runtime calls."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import yaml

from g1swarm.mission.ir import Mission
from g1swarm.mission.validator import MissionValidator

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'experiments/phase2/long_horizon_language_001'
OOD = BASE / 'ood'
SOURCE = OOD / 'authoring'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def map_steps(candidate):
    steps = []
    for index, source in enumerate(candidate['expected_steps'], 1):
        action = source['action']
        fields, allowed = {
            'stand': ({'action', 'duration_s'}, {'duration_s': [1, 2, 5]}),
            'walk_forward': ({'action', 'distance_m'}, {'distance_m': [4, 6, 8, 10, 12, 15, 20]}),
            'turn': ({'action', 'direction', 'angle_deg'}, {'angle_deg': [30, 45, 60, 90], 'direction': ['left', 'right']}),
            'stop': ({'action'}, {}),
        }[action]
        assert set(source) == fields
        for key, values in allowed.items():
            assert not isinstance(source[key], bool) and source[key] in values
        params = {k: float(v) for k, v in source.items() if k not in ('action', 'direction')}
        if action == 'turn' and source['direction'] == 'right':
            params['angle_deg'] *= -1
        steps.append({'id': f's{index}', 'skill': action, 'parameters': params,
                      'depends_on': [] if index == 1 else [f's{index - 1}']})
    document = {'schema_version': '2.0.0', 'mission_id': candidate['candidate_id'], 'steps': steps}
    mission = Mission.from_dict(document)
    assert MissionValidator().validate(mission).valid
    assert Mission.from_dict(mission.to_dict()) == mission
    return document


def extract(value, keys):
    result = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, str):
                result.add(item.strip())
            else:
                result.update(extract(item, keys))
    elif isinstance(value, list):
        for item in value:
            result.update(extract(item, keys))
    return result


def build():
    hashes = load(SOURCE / 'candidate_hashes.json')
    for name, expected in hashes['sha256'].items():
        assert sha(SOURCE / name) == expected
        assert (SOURCE / name).stat().st_size == hashes['size_bytes'][name]
    author = load(SOURCE / 'guard_ood_candidate_manifest.json')
    flags = [k for k in author if k.endswith('_accessed') or k.endswith('_run')]
    flags += ['system_results_observed', 'selection_based_on_system_results', 'deepseek_compiler_called', 'research_repository_modified']
    assert all(author[k] is False for k in flags)
    assert '## Independence declaration' in (SOURCE / 'guard_ood_authoring_note.md').read_text(encoding='utf-8')
    raw = (SOURCE / 'guard_ood_candidates.jsonl').read_bytes()
    assert not raw.startswith(b'\xef\xbb\xbf') and b'\r' not in raw and raw.endswith(b'\n')
    candidates = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
    assert len(candidates) == 160
    assert {c['candidate_id'] for c in candidates} == {f'ood-{g}-{i:03d}' for g in ('m', 'v') for i in range(1, 81)}
    assert len({c['utterance'].strip() for c in candidates}) == 160
    assert [c['candidate_id'] for c in candidates if c['confidence'] == 'low'] == author['low_confidence_candidates']
    rows = []
    required = {'candidate_id', 'utterance', 'expected_status', 'rationale', 'author_phenomenon_group', 'mission_length_class', 'confidence'}
    for line, c in enumerate(candidates, 1):
        valid = c['expected_status'] == 'SUCCESS'
        assert set(c) == required | ({'expected_steps'} if valid else set())
        assert c['expected_status'] == ('SUCCESS' if c['candidate_id'].startswith('ood-v-') else 'MALFORMED')
        assert c['confidence'] in ('high', 'low')
        assert all(isinstance(c[k], str) and c[k].strip() for k in required)
        assert len(c['utterance']) <= 512
        assert c['mission_length_class'] in ('single', 'short', 'medium', 'long')
        row = dict(c)
        row.update(split='primary_gold' if c['confidence'] == 'high' else 'disputed_sensitivity', source_line=line)
        if valid:
            assert isinstance(c['expected_steps'], list) and 1 <= len(c['expected_steps']) <= 32
            n = len(c['expected_steps'])
            assert c['mission_length_class'] == ('single' if n == 1 else 'short' if n <= 3 else 'medium' if n <= 6 else 'long')
            row['expected_mission'] = map_steps(c)
            row['mapping_version'] = 'author_steps_to_mission_ir_v1'
        rows.append(row)
    for status, field in [('MALFORMED', 'malformed_candidates'), ('SUCCESS', 'valid_candidates')]:
        assert sum(c['expected_status'] == status for c in candidates) == author[field] == 80
        for key, manifest_key in [('mission_length_class', 'mission_length_distribution'), ('author_phenomenon_group', 'author_phenomenon_distribution')]:
            assert dict(Counter(c[key] for c in candidates if c['expected_status'] == status)) == author[manifest_key][status]
    split = {}
    for name in ('primary_gold', 'disputed_sensitivity'):
        subset = [r for r in rows if r['split'] == name]
        split[name] = {'ids': [r['candidate_id'] for r in subset], 'count': len(subset), 'labels': dict(Counter(r['expected_status'] for r in subset)), 'hard_gate': name == 'primary_gold'}
    assert split['primary_gold']['labels'] == {'MALFORMED': 50, 'SUCCESS': 79}
    assert split['disputed_sensitivity']['labels'] == {'MALFORMED': 30, 'SUCCESS': 1}
    dataset = OOD / 'guard_ood_dataset.jsonl'
    dataset.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n' for r in rows), encoding='utf-8', newline='\n')
    history = load(BASE / 'final/leakage_audit.json')['historical']
    paths = {k: v['file'] for k, v in history.items()}
    paths.update(pilot='experiments/phase2/long_horizon_language_001/ood/evidence/pilot_language_realizations.yaml', final='experiments/phase2/long_horizon_language_001/final/language_realizations_final.yaml', main_safety_controls='experiments/phase2/long_horizon_language_001/ood/evidence/main_safety_controls.yaml')
    audits = {}
    for name, rel in paths.items():
        data = yaml.safe_load((ROOT / rel).read_text(encoding='utf-8'))
        texts = extract(data, {'text', 'utterance'})
        ids = extract(data, {'sample_id', 'mission_id', 'candidate_id'})
        assert texts, rel
        hits = [c['candidate_id'] for c in candidates if c['utterance'].strip() in texts]
        id_hits = sorted(ids & {c['candidate_id'] for c in candidates})
        audits[name] = {'path': rel, 'sha256': sha(ROOT / rel), 'text_count': len(texts), 'exact_text_overlap_ids': hits, 'id_overlap': id_hits}
        assert not hits and not id_hits, (name, hits, id_hits)
    write_json(OOD / 'overlap_audit.json', {'method': 'Unicode exact equality after strip only; no semantic novelty claim; audit never selects or rewrites candidates', 'sources': audits})
    write_json(OOD / 'independence_validation.json', {'status': 'DECLARATION_CONSISTENT', 'basis': 'User handoff and signed-by-content authoring manifest/note; no independent access-log attestation available', 'validated_false_flags': flags, 'source_hashes': {p.name: sha(p) for p in sorted(SOURCE.iterdir())}, 'candidate_changes': [], 'system_evaluation_before_freeze': False, 'split_basis': 'pre-observation author confidence only; no balance sampling'})
    write_json(OOD / 'mapping_provenance.json', {'version': 'author_steps_to_mission_ir_v1', 'script': 'scripts/freeze_guard_ood.py', 'script_sha256': sha(Path(__file__)), 'ir_schema': '2.0.0', 'rules': ['source array order preserved; no merge, repair, insertion or deletion', 'action becomes skill', 'left positive and right negative angle_deg', 'numeric parameters become floats; stop has empty parameters', 's1..sN IDs; each step depends on previous step; mission_id=candidate_id', 'original expected_steps preserved verbatim as JSON values; MALFORMED has no mission'], 'validated_success_missions': 80, 'validated_steps': sum(len(c.get('expected_steps', [])) for c in candidates), 'validation': ['author field and parameter whitelist', 'Mission.from_dict', 'MissionValidator static validation', 'Mission serialization round trip'], 'sign_convention_source': 'src/g1swarm/longhorizon/corpus.py::_skill_clause_l1', 'ir_source_sha256': sha(ROOT / 'src/g1swarm/mission/ir.py'), 'validator_source_sha256': sha(ROOT / 'src/g1swarm/mission/validator.py')})
    write_json(OOD / 'manifest.json', {'dataset_id': 'guard_ood_safety_sidecar_v1', 'schema_version': '1.0.0', 'frozen': True, 'dataset_sha256': sha(dataset), 'dataset': dataset.name, 'total': 160, 'splits': split, 'policy': 'high -> primary_gold; low -> disputed_sensitivity; retain every candidate and original label/rationale; never mix sensitivity with primary metrics or PASS/FAIL', 'authoring_schema_issues': [], 'label_changes': [], 'unresolved_disputes': split['disputed_sensitivity']['ids'], 'independence': 'independence_validation.json', 'mapping': 'mapping_provenance.json', 'overlap': 'overlap_audit.json'})
    write_json(OOD / 'hashes.json', {p.relative_to(OOD).as_posix(): sha(p) for p in sorted(OOD.rglob('*')) if p.is_file() and p.name != 'hashes.json'})
    print(json.dumps({'dataset_sha256': sha(dataset), 'splits': {k: {a: b for a, b in v.items() if a != 'ids'} for k, v in split.items()}, 'overlap': 'zero across all audited corpora'}))


if __name__ == '__main__':
    assert not (OOD / 'manifest.json').exists(), 'Dataset already frozen; use offline integrity tests, never overwrite a freeze.'
    build()
