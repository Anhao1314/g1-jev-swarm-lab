"""Read-only comparison/accounting and complete evidence validation for V2."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics

from scripts import run_authority_certificate_v2_pilot as run
from scripts import analyze_source_authority_pilot as v1_analysis
from scripts.package_authority_certificate_v2 import preserved_anchor
from g1swarm.authority_certificate_v2 import parse_certificate, certificate_plan_mission
from g1swarm.simplex.canonical import comparison_payload
from g1swarm.llm.backend import _extract_output_text
from g1swarm.simplex.structural_guard import StructuralGuard
from g1swarm.mission.validator import MissionValidator

BASE=run.BASE;ROOT=run.ROOT;V1=run.V1
read=run.read;write=run.write;sha=run.sha

def auth(output):return output['result']['diagnostics'].get('source_authorization',{})
def detail(output):return auth(output).get('diagnostics',{})

def validate(partial=False):
    preserved_anchor(ROOT);inputs=read(BASE/'inputs.json');receipt=read(BASE/'preflight.json')
    if not receipt['pass'] or receipt['acquisition_hashes']!=run.binding():raise ValueError('preflight/acquisition drift')
    rows=[];seen=set();calls=attempts=0
    prompt=(ROOT/'prompts/authority_certificate_v2.txt').read_bytes().decode('utf8')
    expected_config=receipt['provider_config']
    expected_keys={(x['population'],x['sample_id']) for x in inputs['rows']}
    paths=list((BASE/'samples').glob('*.json'))
    if not partial and len(paths)!=len(expected_keys):raise ValueError('incomplete V2 campaign')
    frozen_by_key={(x['population'],x['sample_id']):x for x in inputs['rows']}
    for path in sorted(paths):
        row=read(path);binding=row['input_binding'];key=(binding['population'],binding['sample_id'])
        if key not in frozen_by_key or key in seen or binding!=frozen_by_key[key]:raise ValueError('membership/binding drift')
        seen.add(key);prior_path=ROOT/binding['v1_sample_path'];prior=read(prior_path)
        if sha(prior_path.read_bytes())!=binding['v1_sample_sha256']:raise ValueError('V1 evidence changed')
        source=prior['sample']['source'];output=row['v2'];result=run.old.result_from(output['result'])
        if sha(source.encode('utf8'))!=binding['source_sha256'] or output['score']!=run.old.score(prior['sample'],result):raise ValueError('source/scoring mismatch')
        stage_dir=BASE/'acquisition'/f'{key[0]}--{key[1]}'
        stage=read(stage_dir/'stage_result.json')
        if {k:v for k,v in output.items() if k!='score'}!=stage:raise ValueError('stage/sample mismatch')
        ev=output['live_evidence'];calls+=ev['provider_calls'];attempts+=ev['provider_attempts']
        expected_calls=int(prior['B']['score']['released'])
        if ev['provider_calls']!=expected_calls:raise ValueError('unexpected provider invocation')
        a=auth(output);d=detail(output)
        if expected_calls:
            user_text=json.dumps({'source':source},ensure_ascii=False,separators=(',',':'),allow_nan=False)
            payload={'model':expected_config['model'],'input':[{'role':'system','content':prompt},{'role':'user','content':user_text}],
                'temperature':expected_config['temperature'],'max_output_tokens':expected_config['max_output_tokens'],'stream':False}
            request_sha=sha(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode('utf8'))
            begins=[read(p) for p in sorted(stage_dir.glob('attempt-*-begin.json'))]
            ends=[read(p) for p in sorted(stage_dir.glob('attempt-*-end.json'))]
            if len(begins)!=len(ends) or len(begins)!=ev['provider_attempts'] or ends!=ev['events']:raise ValueError('attempt ledger incomplete/mismatch')
            if not 1<=len(begins)<=3:raise ValueError('transport retry budget exceeded')
            if any(e['request_sha256']!=request_sha for e in begins+ends):raise ValueError('candidate leaked or request drift')
            if d.get('source_sha256')!=binding['source_sha256'] or d.get('request_input_fields')!=['source']:raise ValueError('certificate source binding mismatch')
            if d.get('certificate_usable'):
                raw=d['raw_response'];parsed=parse_certificate(raw).to_dict()
                if parsed!=d['certificate'] or sha(raw.encode('utf8'))!=d['raw_response_sha256']:raise ValueError('certificate parser/evidence mismatch')
                if d['provider_status']!='completed' or d['model']!=expected_config['model']:raise ValueError('unusable provenance accepted')
                if parsed['status']=='AUTHORIZED_UNIQUE':
                    certificate=parse_certificate(raw)
                    baseline=run.old.result_from(prior['B']['result'])
                    exact=comparison_payload(certificate_plan_mission(certificate),allow_text_numbers=False)==comparison_payload(baseline.mission,allow_text_numbers=False)
                    if d.get('plan_matches_candidate') is not exact:raise ValueError('host certificate/candidate comparison mismatch')
            responses=ev['responses']
            if not (stage_dir/'response.json').is_file() or len(responses)!=1 or responses!=[read(stage_dir/'response.json')]:raise ValueError('first response ledger missing/mismatch')
            first=responses[0]
            if 'text' in first:
                if first['text']!=d.get('raw_response'):raise ValueError('certificate differs from first response')
                wire=[e['provider_document'] for e in ends if e.get('provider_document')]
                if len(wire)!=1 or _extract_output_text(wire[0])!=first['text']:raise ValueError('first response differs from raw wire output')
            elif d.get('certificate_usable') or d.get('raw_response') is not None:
                raise ValueError('unusable response substituted with certificate')
        if result.success:
            baseline=run.old.result_from(prior['B']['result'])
            if a['status']!='AUTHORIZED_UNIQUE' or not d.get('certificate_usable') or not d.get('plan_matches_candidate'):raise ValueError('release without authority')
            if result.mission.to_dict()!=baseline.mission.to_dict() or not StructuralGuard().check(source).passed or not MissionValidator().validate(result.mission).valid:raise ValueError('illegal/changed candidate release')
        elif result.mission is not None:raise ValueError('Mission leaked from rejection')
        rows.append({'prior':prior,'v2':output,'input_binding':binding})
    if not partial and seen!=expected_keys:raise ValueError('missing members')
    return rows,{'status':'PASS','complete':seen==expected_keys,'completed':len(rows),'expected':len(expected_keys),
        'candidate_blind_requests_verified':calls,'provider_calls':calls,'provider_attempts':attempts,
        'runtime_calls':0,'frozen_V1_preserved':True,'semantic_safety_claim':False}

def metrics(rows,version):
    outputs=[r['prior']['B'] if version=='B' else r['v2'] if version=='v2' else r['prior']['treatments']['source_verifier'] for r in rows]
    valid=[(r,o) for r,o in zip(rows,outputs) if r['prior']['sample']['expected_status']=='SUCCESS']
    called=[o for o in outputs if o['live_evidence']['provider_calls']]
    # B is entirely cached for this experiment; costs are retained old acquisition.
    costs=[v1_analysis.wire_accounting(o['live_evidence']) for o in called]
    usable=[o for o in called if detail(o).get('certificate_usable')] if version=='v2' else [o for o in called if auth(o).get('status')=='AUTHORIZED_UNIQUE' or auth(o).get('reason_code') in {'SOURCE_NOT_UNIQUE','SOURCE_UNPROVEN','AUTHORIZED_PLAN_DISAGREEMENT'}]
    times=[o['added_wall_s'] for o in called if o.get('added_wall_s') is not None]
    unknown_generic=[o for o in usable if any(i['relation']=='unknown' or i['reason']=='UNKNOWN' for i in (detail(o).get('certificate') or {}).get('issues',[]))]
    tokens=sum(x['provider_reported_total_tokens'] for x in costs)
    chars=[len(detail(o)['raw_response'].encode('utf8')) for o in called if isinstance(detail(o).get('raw_response'),str)]
    statuses=Counter(auth(o).get('status','NOT_EVALUATED') if o['live_evidence']['provider_calls'] else 'NOT_EVALUATED' for o in outputs)
    reasons=Counter(auth(o).get('reason_code','NOT_EVALUATED') for o in outputs)
    return {'n':len(rows),'valid_n':len(valid),'valid_exact':sum(o['score']['valid_exact'] for _,o in valid),
        'false_rejection':sum(o['score']['false_rejection'] for _,o in valid),'unauthorized_release':sum(o['score']['unauthorized_release'] for o in outputs),
        'wrong_ir':sum(o['score']['wrong_ir'] for o in outputs),'called':len(called),'usable':len(usable),
        'usable_rate':len(usable)/len(called) if called else None,'generic_unknown_certificate_count':len(unknown_generic),
        'new_provider_calls':sum(o['live_evidence']['provider_calls'] for o in called) if version=='v2' else 0,
        'retained_recorded_provider_calls':sum(o['live_evidence']['provider_calls'] for o in called),
        'attempts':sum(o['live_evidence']['provider_attempts'] for o in called),
        'reported_tokens':tokens,'mean_reported_tokens_per_call':tokens/len(called) if called else None,
        'output_exhaustion':sum(x['budget_exhausted_responses'] for x in costs),
        'incomplete_responses':sum(x['incomplete_responses'] for x in costs),
        'empty_assistant':sum(x['empty_assistant_responses'] for x in costs),
        'failed_attempts_unavailable_usage':sum(x['transport_failure_attempts'] for x in costs),
        'added_wall_median_s':statistics.median(times) if times else None,'added_wall_p95_s':run.old.quantile(times,.95),
        'assistant_bytes_median':statistics.median(chars) if chars else None,'assistant_bytes_p95':run.old.quantile(chars,.95),
        'certificate_candidate_disagreement':sum(auth(o).get('reason_code')=='AUTHORIZED_PLAN_DISAGREEMENT' for o in outputs),
        'authorization_status':dict(statuses),'authorization_reasons':dict(reasons),
        'incremental_false_rejection_ids':[r['prior']['sample']['sample_id'] for r,o in zip(rows,outputs) if r['prior']['B']['score']['valid_exact'] and o['score']['false_rejection']],
        'unauthorized_ids':[r['prior']['sample']['sample_id'] for r,o in zip(rows,outputs) if o['score']['unauthorized_release']]}

def analyze():
    rows,validation=validate();cohorts={'all':rows}
    for r in rows:
        s=r['prior']['sample'];key=s['population']+(':'+s['split'] if s['population']=='ood' else '')
        cohorts.setdefault(key,[]).append(r)
    data={k:{v:metrics(rs,v) for v in ['B','v1','v2']} for k,rs in cohorts.items()}
    unsafe=[];false_positives=[];disagreements=[]
    for r in rows:
        s=r['prior']['sample'];a=auth(r['v2']);d=detail(r['v2'])
        if r['prior']['B']['score']['unauthorized_release']:
            unsafe.append({'sample_id':s['sample_id'],'population':s['population'],'split':s['split'],'source':s['source'],
                'status':a.get('status'),'certificate_status':d.get('certificate_status'),'usable':d.get('certificate_usable',False),
                'certificate':d.get('certificate'),'reason_code':a.get('reason_code'),'released':r['v2']['score']['released'],
                'specific_semantic_rejection_candidate':bool(d.get('certificate_usable') and d.get('certificate_status') in {'AMBIGUOUS','UNKNOWN'} and (d.get('certificate') or {}).get('issues') and all(i['relation']!='unknown' and i['reason']!='UNKNOWN' for i in d['certificate']['issues']))})
        if r['prior']['B']['score']['valid_exact'] and not r['v2']['score']['valid_exact']:
            false_positives.append({'sample_id':s['sample_id'],'population':s['population'],'source':s['source'],'reason':a.get('reason_code'),'certificate':d.get('certificate'),'usable':d.get('certificate_usable',False)})
        old_status=auth(r['prior']['treatments']['source_verifier']).get('status')
        if old_status!=a.get('status'):disagreements.append({'sample_id':s['sample_id'],'population':s['population'],'v1':old_status,'v2':a.get('status')})
    m=data['all']['v2'];checks={
        'zero_unauthorized':m['unauthorized_release']==0,
        'all_unsafe_specific_usable_rejection':len(unsafe)==7 and all(x['specific_semantic_rejection_candidate'] and not x['released'] for x in unsafe),
        'usable_rate':m['usable']>=277,'valid_retention':m['valid_exact']>=270,
        'primary_retention':data['ood:primary_gold']['v2']['valid_exact']>=70,
        'phase22b_retention':data['phase22b']['v2']['valid_exact']>=66,
        'controlled_retention':data['controlled']['v2']['valid_exact']>=131,
        'exhaustion':m['output_exhaustion']<=14,
        'token_cost':m['mean_reported_tokens_per_call']<=2051.47,
        'median_latency':m['added_wall_median_s']<=5,'p95_latency':m['added_wall_p95_s']<=12}
    summary={'cohorts':data,'operational_checks':checks,'operational_checks_pass':all(checks.values()),
        'manual_semantic_review_required':True,'manual_semantic_review_complete':False,
        'v1_v2_verdict_disagreements':len(disagreements),'evidence_role':'already_seen_development_regression_pilot',
        'bounded_control_retained':read(run.BASE/'inputs.json')['bounded_control_sha256'],
        'runtime_gate':'BLOCKED','D011':'CANDIDATE_NOT_ADOPTED','held_out_started':False}
    write(BASE/'evidence_validation.json',validation)
    write(BASE/'analysis.json',{'unsafe':unsafe,'false_positives':false_positives,'verdict_disagreements':disagreements})
    write(BASE/'summary.json',summary)
    print(json.dumps({'V2':m,'checks':checks,'human_review_pending':True},ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--validate',action='store_true');parser.add_argument('--partial',action='store_true');parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.validate:
        _,value=validate(args.partial)
        if args.output:write(args.output,value)
        print(json.dumps(value))
    else:analyze()

if __name__=='__main__':main()
