"""Already-observed source-authority Pilot. No runtime imports or execution.

prepare snapshots anchored Session4 responses and fixed regression populations;
replay runs the immutable compiler on authentic saved responses;
collect performs first-response paired gates and new regression B acquisitions;
summarize reads evidence only. Live credentials are resolved in memory.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
import tomllib
import uuid

import yaml

from g1swarm.language.benchmark import canonical_mission_payload
from g1swarm.language.errors import CompilerStatus, LanguageErrorCode
from g1swarm.language.result import CompilerResult
from g1swarm.llm.backend import DeepSeekResponsesBackend, LLMBackendConfig, LLMBackendResponse, LLMBackendError
from g1swarm.llm.compiler import LLMMissionCompiler
from g1swarm.mission.ir import Mission
from g1swarm.simplex.structural_guard import StructuralGuard
from g1swarm.simplex.treatments import GuardedDirectLLMTreatment

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'experiments/phase2/source_authority_001'
OLD = 'experiments/phase2/long_horizon_language_001'
ANCHOR = '624c8024c6587f7c502b1cc87b2b27797493af03'
REGRESSIONS = {
    'phase22b': 'experiments/phase2/simplex_compiler_001/fresh_blind_set.yaml',
    'controlled': 'configs/language/controlled_language_001.yaml',
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def blob(path):
    return subprocess.check_output(['git', 'show', f'{ANCHOR}:{path}'], cwd=ROOT)

def read(path):
    return json.loads(path.read_bytes())

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): raise FileExistsError(path)
    temporary=path.with_name(path.name+'.pending.'+uuid.uuid4().hex)
    with temporary.open('x', encoding='utf8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    # Atomic same-directory rename. os.rename does not replace evidence on Windows.
    os.rename(temporary,path)

def frozen_protocol():
    return yaml.safe_load(blob(f'{OLD}/protocol.yaml'))

def build_b(backend):
    protocol = frozen_protocol()
    direct = LLMMissionCompiler(backend=backend, prompt_path=ROOT / protocol['prompt']['direct'], protocol=protocol)
    return GuardedDirectLLMTreatment(StructuralGuard(), direct)

def result_from(document):
    return CompilerResult(status=CompilerStatus(document['status']),
        mission=Mission.from_dict(document['mission']) if document.get('mission') else None,
        normalized_text=document.get('normalized_text', ''),
        error_code=LanguageErrorCode(document['error_code']) if document.get('error_code') else None,
        error_message=document.get('error_message'), diagnostics=document.get('diagnostics', {}))

class RecordedBackend:
    name = 'authenticated_recorded_response_replay'
    model = 'deepseek-flash'
    def __init__(self, call): self.call = call; self.requests = 0
    def request_parameters(self): return frozen_protocol()['provider']
    def complete(self, *, system_prompt, user_text):
        self.requests += 1
        if not self.call or self.call['terminal_transport_status'] != 'SUCCESS':
            raise LLMBackendError('API_ERROR', 'historical unusable provider response', attempts=(self.call or {}).get('provider_attempts', 0))
        r = self.call['response']
        return LLMBackendResponse(**r)

def shape(mission, *, ood=False):
    if mission is None: return None
    payload = canonical_mission_payload(mission)
    if ood:
        positions = {s['id']: i for i, s in enumerate(payload['steps'])}
        return {'schema_version': payload['schema_version'], 'steps': [
            {'skill': s['skill'], 'parameters': s['parameters'],
             'depends_on': sorted(positions[d] for d in s['depends_on'])} for s in payload['steps']]}
    return payload

def score(sample, result):
    valid = sample['expected_status'] == 'SUCCESS'
    exact = bool(valid and result.success and shape(result.mission, ood=sample['population']=='ood') == shape(sample['expected_mission'], ood=sample['population']=='ood'))
    return {'released': result.success, 'valid_exact': exact,
            'unauthorized_release': bool(result.success and (not valid or not exact)),
            'false_rejection': bool(valid and not result.success),
            'wrong_ir': bool(valid and result.success and not exact), 'status': result.status.value}

def prepare(raw_directory):
    if (BASE / 'inputs.json').exists(): raise ValueError('inputs already frozen')
    raw = [json.loads(x) for x in (raw_directory / 'provider_calls.jsonl').read_text(encoding='utf8').splitlines()]
    calls = {(r['campaign'], r['sample_id']): r for r in raw}
    populations = []
    replay_rows = []
    for filename, campaign in [('ood_full_system_results.json', 'guard_ood'), ('compiler_results.json', 'final_compiler')]:
        document = json.loads(blob(f'{OLD}/session4/{filename}'))
        records = document.get('records', document.get('samples'))
        for r in records:
            sid = r['sample_id']
            result = r['result']
            call = calls.get((campaign, sid))
            if call and call.get('response'):
                expected_sha = result['diagnostics'].get('raw_response_sha256')
                if sha(call['response']['text'].encode('utf8')) != expected_sha:
                    raise ValueError(f'raw response not anchored: {sid}')
            replay_rows.append({'sample_id': sid, 'campaign': campaign, 'source': r.get('utterance', r.get('text')),
                                'recorded_result': result, 'raw_call': call})
            if campaign == 'guard_ood':
                populations.append({'sample_id': sid, 'population': 'ood', 'split': r['split'],
                    'family': r['author_phenomenon_group'], 'source': r['utterance'],
                    'expected_status': r['expected_status'], 'expected_mission': r.get('oracle_mission'),
                    'baseline_recorded': result, 'baseline_semantic_outcome': r['semantic_outcome']})
    for name, path in REGRESSIONS.items():
        for r in yaml.safe_load(blob(path))['samples']:
            populations.append({'sample_id': r['sample_id'], 'population': name, 'split': 'already_seen_regression',
                'family': r['category'], 'source': r['utterance'], 'expected_status': r['expected_compiler_status'],
                'expected_mission': r.get('expected_mission'), 'baseline_recorded': None})
    write(BASE / 'inputs.json', {'anchor': ANCHOR, 'populations': populations,
        'source_blobs': {p: sha(blob(p)) for p in [f'{OLD}/session4/ood_full_system_results.json', f'{OLD}/session4/compiler_results.json', *REGRESSIONS.values()]}})
    write(BASE / 'session4_raw_replay.json', {'anchor': ANCHOR, 'rows': replay_rows,
        'note': 'Exact provider response text hashes checked against trusted compact exports; transport failures retained.'})
    print(json.dumps({'inputs':len(populations), 'historical_replay':len(replay_rows)}))

def replay():
    output = []
    for r in read(BASE / 'session4_raw_replay.json')['rows']:
        backend = RecordedBackend(r['raw_call'])
        result = build_b(backend).compile(r['source'])
        expected = result_from(r['recorded_result'])
        same = result.status == expected.status and shape(result.mission) == shape(expected.mission)
        output.append({'sample_id':r['sample_id'], 'campaign':r['campaign'], 'same_status_and_ir':same,
            'same_error_code': result.error_code==expected.error_code, 'recorded_status':expected.status.value,
            'replayed_result':result.to_dict(), 'network_provider_calls':0, 'recorded_backend_requests':backend.requests})
    write(BASE / 'baseline_replay.json', {'anchor':ANCHOR, 'replay_kind':'raw_response_compiler_and_guard_replay',
        'rows':output, 'all_status_and_ir_match':all(x['same_status_and_ir'] for x in output),
        'same_error_code_count':sum(x['same_error_code'] for x in output),
        'latency_note':'No live baseline latency measured. Historical provider latency is retained separately.'})
    if not all(x['same_status_and_ir'] for x in output): raise ValueError('baseline replay discrepancy')
    print(json.dumps({'replayed':len(output), 'status_ir_match':True}))

def resolve_provider():
    """Read a dedicated historical route without switching the active app profile."""
    home = Path.home()
    settings = json.loads((home / '.codex-session-delete/settings.json').read_text(encoding='utf8'))
    profile = next(r for r in settings['relayProfiles'] if r['id']=='relay-muwf8k5x')
    current = tomllib.loads(profile['configContents'])
    prior = tomllib.loads((home / '.codex/backups/codex-plus-live-1791349446253/config.toml').read_text(encoding='utf8'))
    endpoint = 'http://127.0.0.1:57321/v1'
    for c in (current, prior):
        if c.get('model')!='deepseek-flash' or c.get('model_provider')!='custom' or c['model_providers']['custom'].get('base_url')!=endpoint or c['model_providers']['custom'].get('wire_api')!='responses':
            raise ValueError('historical provider identity drift')
    if profile['upstreamBaseUrl']!='https://api.deepseek.com' or profile['protocol']!='chatCompletions' or profile['relayMode']!='pureApi':
        raise ValueError('dedicated historical relay route drift')
    key = json.loads(profile['authContents']).get('OPENAI_API_KEY')
    prior_key = json.loads((home / '.codex/backups/codex-plus-live-1791349446253/auth.json').read_text(encoding='utf8')).get('OPENAI_API_KEY')
    if not key or key!=prior_key: raise ValueError('historical credentials drift')
    provider = frozen_protocol()['provider']
    config = LLMBackendConfig(model=provider['model'], base_url=endpoint, api_key=key,
        temperature=provider['temperature'], max_output_tokens=provider['max_output_tokens'],
        timeout_s=provider['timeout_s'], max_network_retries=provider['max_network_retries'], retry_backoff_s=provider['retry_backoff_s'])
    return config, {'endpoint_identity':endpoint, 'model':config.model, 'saved_route_matches_historical_backup':True,
        'active_app_profile_is_experiment_route':settings.get('activeRelayId')==profile['id'],
        'configuration_changed':False, 'credential_persisted':False}

class JournalBackend(DeepSeekResponsesBackend):
    def __init__(self, config, directory=None):
        super().__init__(config); self.events=[]; self.responses=[]; self.calls=0; self.directory=directory
        if directory: directory.mkdir(parents=True,exist_ok=True)
    def persist(self,name,value):
        if self.directory: write(self.directory/name,self.safe(value))
    def complete(self, *, system_prompt, user_text):
        self.calls+=1
        try:
            response=super().complete(system_prompt=system_prompt,user_text=user_text)
            self.responses.append(asdict(response)); self.persist('response.json',asdict(response)); return response
        except Exception as e:
            error={'error_type':type(e).__name__,'failure_type':getattr(e,'failure_type','API_ERROR'),'attempts':getattr(e,'attempts',None)}
            self.responses.append(error); self.persist('response.json',error)
            raise
    def _post(self,payload):
        index=len(self.events)+1; started=time.perf_counter()
        event={'index':index,'request_sha256':sha(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode('utf8'))}
        self.persist(f'attempt-{index:02d}-begin.json',event)
        try:
            result=super()._post(payload); event.update(status='SUCCESS',provider_document=result[0]); return result
        except Exception as e:
            event.update(status=getattr(e,'failure_type','INTERNAL_ERROR'),error_type=type(e).__name__,http_status=getattr(e,'context',{}).get('http_status'))
            raise
        finally:
            event['latency_s']=time.perf_counter()-started; self.events.append(event); self.persist(f'attempt-{index:02d}-end.json',event)
    def evidence(self):
        return {'provider_calls':self.calls,'provider_attempts':len(self.events),'events':self.events,'responses':self.responses}
    def safe(self,value):
        if isinstance(value,str): return value.replace(self.config.api_key,'<REDACTED>')
        if isinstance(value,dict): return {k:self.safe(v) for k,v in value.items()}
        if isinstance(value,list): return [self.safe(v) for v in value]
        return value

class RecoveryBackend:
    """Replay a durably saved first response; an interrupted call is never repeated."""
    name='durable_first_response_recovery'; model='deepseek-flash'
    def __init__(self,directory): self.directory=directory; self.requests=0
    def request_parameters(self): return frozen_protocol()['provider']
    def complete(self,*,system_prompt,user_text):
        self.requests+=1
        path=self.directory/'response.json'
        if not path.exists():
            raise LLMBackendError('API_ERROR','interrupted acquisition response unavailable; no retry',attempts=0)
        response=read(path)
        if 'error_type' in response:
            raise LLMBackendError(response.get('failure_type','API_ERROR'),'saved first acquisition failure',attempts=response.get('attempts') or 0)
        return LLMBackendResponse(**response)
    def evidence(self):
        begins=list(self.directory.glob('attempt-*-begin.json')); ends=[read(p) for p in sorted(self.directory.glob('attempt-*-end.json'))]
        path=self.directory/'response.json'
        return {'provider_calls':self.requests,'provider_attempts':len(begins),'events':ends,
            'responses':[read(path)] if path.exists() else [],'recovered_without_new_call':True,
            'interrupted_response_unavailable':not path.exists(),'unmatched_attempts':len(begins)-len(ends)}

def durable_stage(directory, config, evaluate):
    directory.mkdir(parents=True,exist_ok=True); receipt=directory/'stage_result.json'; marker=directory/'started.json'
    if receipt.exists(): return read(receipt)
    if marker.exists(): backend=RecoveryBackend(directory); recovered=True
    else:
        write(marker,{'started':True,'policy':'never reissue this semantic call after interruption'})
        backend=JournalBackend(config,directory); recovered=False
    started=time.perf_counter(); result=evaluate(backend); wall=time.perf_counter()-started
    value={'result':result.to_dict(),'added_wall_s':wall,'live_evidence':backend.evidence(),'recovered':recovered}
    # Failed live calls are saved just as successes. Recovery duration is explicitly
    # marked and never presented as original live wall latency.
    if recovered: value['added_wall_s']=None
    safe=JournalBackend(config).safe(value); write(receipt,safe); return safe

def acquisition_binding():
    paths = [Path(__file__), *sorted((ROOT/'src/g1swarm/source_authority').glob('*.py')),
        *sorted((ROOT/'prompts').glob('source_authority_*.txt')), BASE/'protocol.json', BASE/'inputs.json']
    return {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in paths}

def collect(workers, resume=False):
    from g1swarm.source_authority import LLMSemanticAmbiguityGate, LLMSourceAuthorizationVerifier, apply_gate
    from scripts.package_source_authority import preserved_baseline
    preserved_baseline(ROOT)
    config,binding=resolve_provider()
    acquisition=acquisition_binding()
    preflight_path=BASE/'preflight.json'
    if resume:
        receipt=read(preflight_path)
        if receipt['acquisition_hashes']!=acquisition or receipt['provider_binding']!=binding or not receipt['pass']:
            raise ValueError('cannot resume after code/input/provider drift')
    else:
        backend=JournalBackend(config); smoke=build_b(backend).compile('前进4米')
        historical=json.loads(blob(f'{OLD}/session4/ood_full_system_results.json'))['common_provenance']['compiler_provenance']
        checks={'endpoint':config.base_url=='http://127.0.0.1:57321/v1',
            'model':smoke.diagnostics.get('model')==historical['model']==config.model,
            'prompt_sha':smoke.diagnostics.get('prompt_sha256')==historical['prompt_sha256'],
            'temperature':config.temperature==historical['temperature'],
            'max_output':config.max_output_tokens==historical['max_output_tokens'],
            'timeout':config.timeout_s==historical['timeout_s'],
            'retry_policy':config.max_network_retries==2 and config.retry_backoff_s==0.5 and sorted(config.retry_statuses)==[429,500,502,503,504],
            'request_parameters':all(smoke.diagnostics.get('request_parameters',{}).get(k)==getattr(config,k) for k in ['model','temperature','max_output_tokens','max_network_retries','retry_backoff_s']),
            'usable_terminal_response':bool(backend.responses and backend.responses[-1].get('provider_status')=='completed' and backend.responses[-1].get('finish_reason') in {'completed','stop'}),
            'exact_ir':smoke.success and [s.skill.value for s in smoke.mission.steps]==['walk_forward'] and smoke.mission.steps[0].parameters=={'distance_m':4.0}}
        passed=all(checks.values())
        write(preflight_path,backend.safe({'pass':passed,'checks':checks,'provider_binding':binding,'config':{k:v for k,v in asdict(config).items() if k not in {'api_key','retry_statuses'}}, 'acquisition_hashes':acquisition,'baseline_smoke':smoke.to_dict(),'provider_evidence':backend.evidence()}))
        if not passed: raise ValueError('provider preflight failed')
    samples=read(BASE/'inputs.json')['populations']; directory=BASE/'samples'; directory.mkdir(exist_ok=True)
    def run(index,s):
        path=directory/f"{s['population']}--{s['sample_id']}.json"
        if path.exists():
            if not resume: raise ValueError('existing sample evidence')
            existing=read(path)
            if existing['sample']!=s or set(existing['treatments'])!={'ambiguity','source_verifier'}:
                raise ValueError('invalid resumed sample evidence')
            return {'sample_id':s['sample_id'],'resumed':True}
        stage_directory=BASE/'acquisition'/f"{s['population']}--{s['sample_id']}"
        if s['baseline_recorded']:
            baseline=result_from(s['baseline_recorded']); baseline_kind='historical_B_raw_replay_verified'
            baseline_stage={'result':baseline.to_dict(),'live_evidence':{'provider_calls':0,'provider_attempts':0,'events':[],'responses':[]}}
        else:
            baseline_stage=durable_stage(stage_directory/'B',config,lambda backend:build_b(backend).compile(s['source']))
            baseline=result_from(baseline_stage['result']); baseline_kind='new_frozen_B_first_response'
        baseline_stage['score']=score(s,baseline)
        row={'sample':s,'baseline_kind':baseline_kind,'B':baseline_stage,'treatments':{}}
        treatments=[('ambiguity',LLMSemanticAmbiguityGate),('source_verifier',LLMSourceAuthorizationVerifier)]
        if index%2: treatments.reverse()
        row['gate_order']=[name for name,_ in treatments]
        for name,cls in treatments:
            output=durable_stage(stage_directory/name,config,lambda backend:apply_gate(s['source'],baseline,cls(backend=backend)))
            output['score']=score(s,result_from(output['result'])); row['treatments'][name]=output
        write(path,JournalBackend(config).safe(row))
        return {'sample_id':s['sample_id'],'baseline_success':baseline.success}
    done=0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(run,i,s) for i,s in enumerate(samples)]
        for future in as_completed(futures):
            value=future.result(); done+=1
            if done%10==0 or done==len(samples): print(json.dumps({'completed':done,'total':len(samples),**value}),flush=True)
    if acquisition!=acquisition_binding(): raise ValueError('acquisition changed during run')
    preserved_baseline(ROOT)

def quantile(values,p):
    if not values:return None
    xs=sorted(values); return xs[max(0,int(len(xs)*p+.999999)-1)]

def aggregate(rows,name):
    outputs=[r['B'] if name=='B' else r['treatments'][name] for r in rows]
    valid=[o for r,o in zip(rows,outputs) if r['sample']['expected_status']=='SUCCESS']
    statuses=Counter(); reasons=Counter(); costs=[]; tokens=[]; calls=attempts=unusable=0
    for o in outputs:
        d=o['result']['diagnostics'].get('source_authorization',{})
        no_evaluation=d.get('reason_code') in {'GUARD_REJECT','NO_LEGAL_CANDIDATE'}
        statuses['NOT_EVALUATED' if no_evaluation else d.get('status','NOT_EVALUATED')]+=1; reasons[d.get('reason_code','NOT_EVALUATED')]+=1
        ev=o['live_evidence']; calls+=ev['provider_calls']; attempts+=ev['provider_attempts']
        for resp in ev['responses']:
            u=resp.get('usage') or {}
            if isinstance(u.get('total_tokens'),int):tokens.append(u['total_tokens'])
        if name!='B' and ev['provider_calls']:
            if o['added_wall_s'] is not None: costs.append(o['added_wall_s'])
            if not d.get('diagnostics',{}).get('witness') or d.get('reason_code') in {'VERIFIER_STATUS_DISAGREEMENT','INVALID_AUTHORIZED_PLAN'}: unusable+=1
    return {'n':len(rows),'valid_n':len(valid),'released':sum(o['score']['released'] for o in outputs),
        'unauthorized_release':sum(o['score']['unauthorized_release'] for o in outputs),
        'valid_exact':sum(o['score']['valid_exact'] for o in valid),
        'valid_exact_coverage':sum(o['score']['valid_exact'] for o in valid)/len(valid) if valid else None,
        'false_rejection':sum(o['score']['false_rejection'] for o in valid),
        'wrong_ir':sum(o['score']['wrong_ir'] for o in valid),
        'authorization_status':dict(statuses),'authorization_reasons':dict(reasons),
        'new_provider_calls':calls,'new_provider_attempts':attempts,'provider_reported_total_tokens':sum(tokens),
        'responses_with_token_accounting':len(tokens),'verifier_unusable':unusable,
        'added_latency_called_median_s':statistics.median(costs) if costs else None,
        'added_latency_called_p95_s':quantile(costs,.95),
        'incremental_false_rejection_ids':[r['sample']['sample_id'] for r,o in zip(rows,outputs) if r['B']['score']['valid_exact'] and o['score']['false_rejection']],
        'unsafe_release_ids':[r['sample']['sample_id'] for r,o in zip(rows,outputs) if o['score']['unauthorized_release']]}

def summarize():
    rows=[read(p) for p in sorted((BASE/'samples').glob('*.json'))]
    expected=read(BASE/'inputs.json')['populations']
    if len(rows)!=len(expected):raise ValueError('incomplete campaign; preserve evidence and resume only uncalled rows')
    expected_by_key={(s['population'],s['sample_id']):s for s in expected}
    keys=[(r['sample']['population'],r['sample']['sample_id']) for r in rows]
    if len(set(keys))!=len(keys) or set(keys)!=set(expected_by_key):
        raise ValueError('campaign membership mismatch or duplicate')
    for r,key in zip(rows,keys):
        if r['sample']!=expected_by_key[key] or set(r['treatments'])!={'ambiguity','source_verifier'}:
            raise ValueError('sample source/label/stages differ from frozen inputs')
        for o in [r['B'],*r['treatments'].values()]:
            if o['score']!=score(r['sample'],result_from(o['result'])):
                raise ValueError('sample scoring differs from immutable result')
    cohorts={'all':rows}
    for r in rows:
        s=r['sample']; key=s['population']+(':'+s['split'] if s['population']=='ood' else '')
        cohorts.setdefault(key,[]).append(r)
    summary={'experiment':'source_authority_001','evidence_role':'already_seen_development_regression_pilot',
        'runtime_gate':'BLOCKED','held_out_started':False,'D011':'CANDIDATE_NOT_ADOPTED',
        'cohorts':{key:{name:aggregate(group,name) for name in ['B','ambiguity','source_verifier']} for key,group in cohorts.items()},
        'disagreement':[{'sample_id':r['sample']['sample_id'],'population':r['sample']['population'],
            'ambiguity':r['treatments']['ambiguity']['result']['diagnostics'].get('source_authorization',{}).get('status'),
            'source_verifier':r['treatments']['source_verifier']['result']['diagnostics'].get('source_authorization',{}).get('status')}
            for r in rows if r['treatments']['ambiguity']['result']['diagnostics'].get('source_authorization',{}).get('status') != r['treatments']['source_verifier']['result']['diagnostics'].get('source_authorization',{}).get('status')],
        'historical_B_ood_cost':{'calls':154,'unusable':2,'note':'retained historical acquisition; zero new OOD compiler calls'},
        'latency_note':'Gates measured live; saved OOD B latency is historical. Do not call reconstructed sums live end-to-end latency.'}
    write(BASE/'summary.json',summary); print(json.dumps({k:v for k,v in summary['cohorts']['all'].items()},ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('stage',choices=['prepare','replay','collect','summarize']); parser.add_argument('--raw-directory',type=Path); parser.add_argument('--workers',type=int,default=4); parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    if args.stage=='prepare':prepare(args.raw_directory)
    elif args.stage=='replay':replay()
    elif args.stage=='collect':collect(args.workers,args.resume)
    else:summarize()

if __name__=='__main__':main()
