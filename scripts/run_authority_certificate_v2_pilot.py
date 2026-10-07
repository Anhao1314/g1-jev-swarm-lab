"""Paired V2 acquisition from immutable V1 source/B evidence; no Runtime."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path

from scripts import run_source_authority_pilot as old
from scripts.package_authority_certificate_v2 import preserved_anchor
from g1swarm.authority_certificate_v2 import SourceAuthorityCertificateIssuer
from g1swarm.source_authority import apply_gate

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'experiments/phase2/source_authority_v2_001'
V1=ROOT/'experiments/phase2/source_authority_001'
read=old.read
write=old.write
sha=old.sha

def original_rows():
    expected=read(V1/'inputs.json')['populations'];out=[]
    for sample in expected:
        path=V1/'samples'/f"{sample['population']}--{sample['sample_id']}.json"
        row=read(path)
        if row['sample']!=sample:raise ValueError('V1 source/label binding changed')
        out.append((path,row))
    return out

def prepare():
    preserved_anchor(ROOT)
    rows=original_rows()
    bounded=read(V1/'bounded_control.json')
    write(BASE/'inputs.json',{'base_commit':'d06c61811c3ef41abf12c22a4a2618eabf28c495',
        'v1_input_sha256':sha((V1/'inputs.json').read_bytes()),
        'v1_summary_sha256':sha((V1/'summary.json').read_bytes()),
        'bounded_control_sha256':sha((V1/'bounded_control.json').read_bytes()),
        'rows':[{'population':r['sample']['population'],'sample_id':r['sample']['sample_id'],
            'source_sha256':sha(r['sample']['source'].encode('utf8')),
            'v1_sample_path':p.relative_to(ROOT).as_posix(),'v1_sample_sha256':sha(p.read_bytes())} for p,r in rows],
        'sample_count':len(rows),'eligible_B_candidates':sum(r['B']['score']['released'] for _,r in rows),
        'bounded_control_retained_records':len(bounded['records'])})
    print(json.dumps({'prepared':len(rows),'eligible':sum(r['B']['score']['released'] for _,r in rows)}))

def binding():
    paths=[Path(__file__),ROOT/'src/g1swarm/authority_certificate_v2.py',ROOT/'prompts/authority_certificate_v2.txt',
        BASE/'protocol.json',BASE/'inputs.json',BASE/'CONTRACT.md']
    return {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in paths}

def preflight(config,provider_binding):
    acquired=binding();backend=old.JournalBackend(config,BASE/'preflight/B')
    result=old.build_b(backend).compile('前进4米')
    prior=read(V1/'preflight.json')
    expected_config=prior['config'];actual_config={k:getattr(config,k) for k in expected_config}
    checks={'endpoint':config.base_url=='http://127.0.0.1:57321/v1',
        'provider_configuration':actual_config==expected_config,
        'model':result.diagnostics.get('model')==config.model=='deepseek-flash',
        'compiler_prompt':result.diagnostics.get('prompt_sha256')==prior['baseline_smoke']['diagnostics']['prompt_sha256'],
        'exact_B':result.success and old.shape(result.mission)==old.shape(prior['baseline_smoke']['mission']),
        'B_completed':bool(backend.responses and backend.responses[-1].get('provider_status')=='completed'),
        'retry_statuses':sorted(config.retry_statuses)==[429,500,502,503,504]}
    if not all(checks.values()):
        write(BASE/'preflight.json',backend.safe({'pass':False,'checks':checks,'acquisition_hashes':acquired,
            'provider_binding':provider_binding,'B':result.to_dict(),'B_evidence':backend.evidence()}))
        raise ValueError('provider drift: no scored V2 calls started')
    cert_backend=old.JournalBackend(config,BASE/'preflight/certificate')
    outcome=SourceAuthorityCertificateIssuer(cert_backend).issue_certificate('前进4米')
    checks['certificate_usable']=outcome.usable
    checks['certificate_exact']=bool(outcome.certificate and outcome.certificate.to_dict()['plan']==[['walk_forward',4.0]])
    checks['candidate_blind']=outcome.diagnostics.get('request_input_fields')==['source']
    passed=all(checks.values())
    write(BASE/'preflight.json',backend.safe({'pass':passed,'checks':checks,'provider_binding':provider_binding,
        'provider_config':actual_config,'acquisition_hashes':acquired,'B':result.to_dict(),
        'B_evidence':backend.evidence(),'certificate':outcome.to_dict(),'certificate_evidence':cert_backend.evidence(),
        'non_scored':True,'scored_calls_started':False}))
    if not passed:raise ValueError('non-scored certificate preflight unusable; no Pilot started')

def collect(workers,resume):
    preserved_anchor(ROOT);config,provider_binding=old.resolve_provider()
    acquired=binding();receipt=BASE/'preflight.json'
    if resume:
        prior=read(receipt)
        if not prior['pass'] or prior['acquisition_hashes']!=acquired or prior['provider_binding']!=provider_binding:
            raise ValueError('cannot resume with drift')
    else:preflight(config,provider_binding)
    frozen=read(BASE/'inputs.json')['rows'];rows=original_rows()
    by_key={(r['sample']['population'],r['sample']['sample_id']):(p,r) for p,r in rows}
    def one(item):
        key=(item['population'],item['sample_id']);path,prior=by_key[key]
        if sha(path.read_bytes())!=item['v1_sample_sha256']:raise ValueError('old candidate/evidence drift')
        output=BASE/'samples'/f"{item['population']}--{item['sample_id']}.json"
        if output.exists():
            if not resume:raise FileExistsError(output)
            if read(output)['input_binding']!=item:raise ValueError('saved V2 binding drift')
            return
        baseline=old.result_from(prior['B']['result']);source=prior['sample']['source']
        stage=old.durable_stage(BASE/'acquisition'/f"{item['population']}--{item['sample_id']}",config,
            lambda backend:apply_gate(source,baseline,SourceAuthorityCertificateIssuer(backend)))
        stage['score']=old.score(prior['sample'],old.result_from(stage['result']))
        write(output,old.JournalBackend(config).safe({'input_binding':item,'v2':stage}))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(one,item) for item in frozen]
        for done,future in enumerate(as_completed(futures),1):
            future.result()
            if done%20==0 or done==len(frozen):print(json.dumps({'completed':done,'total':len(frozen)}),flush=True)
    if binding()!=acquired:raise ValueError('V2 acquisition code/input changed')
    preserved_anchor(ROOT)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','collect']);parser.add_argument('--workers',type=int,default=4);parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    if args.stage=='prepare':prepare()
    else:collect(args.workers,args.resume)

if __name__=='__main__':main()
