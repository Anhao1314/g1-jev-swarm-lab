"""Authoritative post-acquisition analysis including unusable-response token costs.

The acquisition observer's backend returns no usage when there is no assistant
text. The attempt journal still retains provider-reported usage. This reader
counts that usage once per wire response and never repairs semantic outputs.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import time

from scripts import run_source_authority_pilot as pilot

BASE=pilot.BASE

def wire_accounting(evidence):
    documents=[e['provider_document'] for e in evidence['events'] if e.get('provider_document')]
    usage=[d.get('usage') for d in documents if isinstance(d.get('usage'),dict)]
    # Only a fallback for historical/custom evidence without raw attempt docs.
    if not documents:usage=[r['usage'] for r in evidence['responses'] if isinstance(r.get('usage'),dict)]
    values=[u['total_tokens'] for u in usage if isinstance(u.get('total_tokens'),int) and not isinstance(u.get('total_tokens'),bool)]
    incomplete=sum(d.get('status')=='incomplete' for d in documents)
    exhausted=sum((d.get('incomplete_details') or {}).get('reason')=='max_output_tokens' for d in documents)
    def has_text(d):
        return any(isinstance(p.get('text'),str) and bool(p['text'].strip()) for o in d.get('output',[]) for p in o.get('content',[]) if p.get('type') in {'output_text','text'})
    empty=sum(not has_text(d) for d in documents)
    transport_failures=sum(e.get('status') not in {'SUCCESS',None} for e in evidence['events'])
    return {'provider_reported_total_tokens':sum(values),'responses_with_usage':len(values),
        'wire_responses':len(documents),'incomplete_responses':incomplete,'budget_exhausted_responses':exhausted,
        'empty_assistant_responses':empty,'transport_failure_attempts':transport_failures,
        'wire_responses_missing_token_accounting':len(documents)-len(values)}

def aggregate(rows,name):
    result=pilot.aggregate(rows,name)
    outputs=[r['B'] if name=='B' else r['treatments'][name] for r in rows]
    costs=[wire_accounting(o['live_evidence']) for o in outputs]
    result['backend_response_usage_only_tokens']=result['provider_reported_total_tokens']
    result['provider_reported_total_tokens']=sum(x['provider_reported_total_tokens'] for x in costs)
    for key in ['incomplete_responses','budget_exhausted_responses','empty_assistant_responses','transport_failure_attempts','wire_responses_missing_token_accounting']:
        result[key]=sum(x[key] for x in costs)
    result['responses_with_token_accounting']=sum(x['responses_with_usage'] for x in costs)
    calls=result['new_provider_calls']
    result['mean_tokens_per_called_stage']=result['provider_reported_total_tokens']/calls if calls else None
    valid_n=result['valid_n']
    result['false_rejection_rate']=result['false_rejection']/valid_n if valid_n else None
    if name=='B':
        values=[o.get('added_wall_s') for o in outputs if o['live_evidence']['provider_calls'] and o.get('added_wall_s') is not None]
        result['new_B_called_wall_median_s']=statistics.median(values) if values else None
        result['new_B_called_wall_p95_s']=pilot.quantile(values,.95)
    if name=='bounded':
        values=[o['added_wall_s'] for o in outputs]
        result['local_added_wall_median_s']=statistics.median(values)
        result['local_added_wall_p95_s']=pilot.quantile(values,.95)
    result['incremental_false_rejection_rate_among_B_exact']=len(result['incremental_false_rejection_ids'])/sum(r['B']['score']['valid_exact'] for r in rows) if any(r['B']['score']['valid_exact'] for r in rows) else None
    return result

def bounded_control(rows):
    from g1swarm.source_authority import apply_gate
    from g1swarm.source_authority_bounded import BoundedSourceAuthorizationVerifier
    result=[]
    for row in rows:
        source=row['sample']['source']; baseline=pilot.result_from(row['B']['result'])
        start=time.perf_counter(); gated=apply_gate(source,baseline,BoundedSourceAuthorizationVerifier())
        result.append({'population':row['sample']['population'],'sample_id':row['sample']['sample_id'],
            'baseline_evidence_sha256':hashlib.sha256((BASE/'samples'/f"{row['sample']['population']}--{row['sample']['sample_id']}.json").read_bytes()).hexdigest(),
            'result':gated.to_dict(),'score':pilot.score(row['sample'],gated),'added_wall_s':time.perf_counter()-start,
            'live_evidence':{'provider_calls':0,'provider_attempts':0,'events':[],'responses':[]}})
    pilot.write(BASE/'bounded_control.json',{'evidence_role':'post_hoc_exploratory_bounded_control','records':result})
    for row,control in zip(rows,result):row['treatments']['bounded']=control

def analyze(rows):
    expected=pilot.read(BASE/'inputs.json')['populations']
    expected_map={(s['population'],s['sample_id']):s for s in expected}
    keys=[(r['sample']['population'],r['sample']['sample_id']) for r in rows]
    if len(rows)!=len(expected) or len(set(keys))!=len(keys) or set(keys)!=set(expected_map):raise ValueError('incomplete/duplicate campaign membership')
    if any(r['sample']!=expected_map[k] for r,k in zip(rows,keys)):raise ValueError('source/labels changed')
    cohorts={'all':rows}
    for row in rows:
        s=row['sample'];key=s['population']+(':'+s['split'] if s['population']=='ood' else '')
        cohorts.setdefault(key,[]).append(row)
    names=['B','ambiguity','source_verifier','bounded']
    summary={'experiment_id':'source_authority_001','evidence_role':'already_seen_development_regression_pilot',
        'cohorts':{k:{name:aggregate(rs,name) for name in names} for k,rs in cohorts.items()},
        'cost_accounting':'Provider-reported total_tokens from each raw wire response, including budget-exhausted reasoning-only/incomplete responses; never add final backend-response usage a second time.',
        'runtime_gate':'BLOCKED','held_out_started':False,'D011':'CANDIDATE_NOT_ADOPTED',
        'all_samples':len(rows),'original_treatments_preregistered':True,'bounded_control_post_hoc':True}
    disagreement=[];false_positives=[];false_negatives=[];known=[]
    for row in rows:
        s=row['sample'];statuses={}
        for name in names[1:]:
            output=row['treatments'][name];auth=output['result']['diagnostics'].get('source_authorization',{})
            statuses[name]=auth.get('status')
            detail={'population':s['population'],'split':s['split'],'sample_id':s['sample_id'],'family':s['family'],
                'source':s['source'],'treatment':name,'authorization_status':auth.get('status'),'reason':auth.get('reason_code'),
                'baseline_exact':row['B']['score']['valid_exact'],'wire_accounting':wire_accounting(output['live_evidence'])}
            if row['B']['score']['valid_exact'] and output['score']['false_rejection']:false_positives.append(detail)
            if output['score']['unauthorized_release']:false_negatives.append(detail)
        if statuses['ambiguity']!=statuses['source_verifier']:
            disagreement.append({'population':s['population'],'sample_id':s['sample_id'],'statuses':statuses})
        if row['B']['score']['unauthorized_release']:
            known.append({'sample':s,'B':row['B']['score'],'treatments':{name:{'score':row['treatments'][name]['score'],'authorization':row['treatments'][name]['result']['diagnostics'].get('source_authorization'),'cost':wire_accounting(row['treatments'][name]['live_evidence'])} for name in names[1:]}})
    summary['model_gate_disagreement_count']=len(disagreement)
    summary['known_B_unsafe_cases']=len(known)
    analysis={'false_positives':false_positives,'false_negatives':false_negatives,'model_gate_disagreement':disagreement,'known_unsafe_cases':known}
    pilot.write(BASE/'analysis.json',analysis);pilot.write(BASE/'summary.json',summary)
    report(summary,analysis,rows)

def report(summary,analysis,rows):
    lines=['# Phase 2.4 source-authority Pilot','',
        'Date: 2026-10-07 (Asia/Shanghai). Branch: `phase2.4/source-authority`.',
        'Audit anchor `624c802`; Session 4 evidence anchor `5fabf3c`. D010 revisit remains triggered; D011 remains **candidate / not adopted**. Language Runtime remains **BLOCKED**. No Runtime or held-out campaign ran.','',
        'This report concerns already observed development/regression evidence. The old OOD is not fresh blind evidence. All source texts, labels, old results, historical thresholds, frozen compiler prompt, Guard, Runtime, Grounder and skills remain unchanged. The long-horizon corpus was not repaired.','',
        '## Design and provenance','',
        'The original comparison pairs immutable B candidates with a source-only semantic ambiguity gate and a source-aware authorization verifier. Both gates require exact complete-source coverage and seven scope/relation judgements. The source-aware gate additionally validates a source-derived full plan and deterministically compares count, skills, order, parameters and dependencies with B. Only `Guard pass ∧ IR legal ∧ AUTHORIZED_UNIQUE` releases the original candidate. There is no confidence-based release, candidate rewrite, semantic retry or automatic repair.','',
        'All 160 Session 4 OOD rows, 179 Phase 2.2b rows and 189 controlled rows were included. The 160 OOD candidates are frozen historical outputs; the 368 regression candidates are new first-response acquisitions from frozen B. Both gates share each candidate. Acquisition order alternates by fixed input index, with four concurrent sample workers. Original model gates and acquisition hashes were fixed before scored calls.','',
        '466 authentic historical compiler/Guard raw-response replays (160 OOD + 306 Final) reproduce all recorded statuses and canonical IR. Original response text SHA-256 matches the trusted compact exports. Historical transport/unusable responses remain unavailable; their original diagnostics are retained. This is an offline replay, not a new measurement of B latency. There is no new Final treatment campaign.','',
        'The relay initially returned 502 because its active default profile had an empty upstream URL. A runtime-only saved-profile selection repair restored the historical DeepSeek route. Saved profile/credentials match the historical backup; Codex config/auth remain unchanged. Failed and successful non-scored preflights are preserved. The successful preflight verifies endpoint `http://127.0.0.1:57321/v1`, model `deepseek-flash`, Direct prompt SHA `913346508791ab86f80247f2b6315d6e96f9b5066090299ada2196aeb0e3c110`, temperature 0, output budget 4096, timeout 60 seconds, and two transport retries with 0.5-second backoff/status set. GPT only develops and operates this experiment.','',
        'After seeing resource failures, an explicitly post-hoc bounded control was added. It uses the unchanged controlled-language full-source parser and deterministic candidate comparison, with zero provider calls. It is a grammar-bounded availability/safety comparison, not a replacement claim or independent held-out result. See `bounded_control_amendment.json` and the bounded module for normalization assumptions and restrictions.','',
        '## Paired outcomes','',
        '| Cohort | Treatment | N / valid N | Unauthorized releases | Valid exact | False rejects | A / AM / U / skipped |',
        '|---|---|---:|---:|---:|---:|---|']
    for cohort,arms in summary['cohorts'].items():
        if cohort=='all':continue
        for name,m in arms.items():
            st=m['authorization_status'];statuses='/'.join(str(st.get(s,0)) for s in ['AUTHORIZED_UNIQUE','AMBIGUOUS','UNKNOWN','NOT_EVALUATED'])
            lines.append(f"| {cohort} | {name} | {m['n']} / {m['valid_n']} | {m['unauthorized_release']} | {m['valid_exact']} | {m['false_rejection']} | {statuses} |")
    lines+=['','Unauthorized release includes an executable output on a frozen non-valid source or a wrong executable IR on a valid source. False rejection means a valid source releases no Mission; wrong IR is reported separately. OOD preserves the historical positional-dependency scoring (step ID spelling ignored); other regressions preserve canonical IR scoring. Model gate statuses are host-validated results. Inherited B refusals are skipped, not new model UNKNOWN judgements.','',
        '## Cost and unusable responses','',
        '| Treatment | New calls / attempts | Reported tokens | Mean tokens/call | Gate latency median / P95 s | Budget exhaustion | Empty assistant | Unusable gate responses |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,m in summary['cohorts']['all'].items():
        fmt=lambda v:'n/a' if v is None else f'{v:.2f}'
        lines.append(f"| {name} | {m['new_provider_calls']} / {m['new_provider_attempts']} | {m['provider_reported_total_tokens']} | {fmt(m['mean_tokens_per_called_stage'])} | {fmt(m['added_latency_called_median_s'])} / {fmt(m['added_latency_called_p95_s'])} | {m['budget_exhausted_responses']} | {m['empty_assistant_responses']} | {m['verifier_unusable']} |")
    lines+=['','Tokens include every provider-reported wire-response total, including reasoning-only responses that the frozen backend cannot return as assistant text. Component token sums are not substituted for provider totals, and successful final usage is not double-counted. `backend_response_usage_only_tokens` in summary exposes the naive undercount. No-token failed wire attempts are reported as missing accounting, never assigned zero known cost. Non-scored preflights are excluded. Historical OOD B acquisition had 154 calls and two unusable results; those costs are separate from the new calls above.','',
        'Gate wall latency is measured live under the declared concurrent schedule. Historical OOD B latency is not added and called live end-to-end latency. Regression B latency is measured separately in summary. The zero-call bounded control adds local parse/comparison time only; per-sample durations are retained.','',
        '## Known unauthorized candidates','',
        '| Case | Cohort | Ambiguity gate | Source verifier | Bounded control |',
        '|---|---|---|---|---|']
    for case in analysis['known_unsafe_cases']:
        s=case['sample'];parts=[]
        for name in ['ambiguity','source_verifier','bounded']:
            a=case['treatments'][name]['authorization'];parts.append(a['status']+' / '+a['reason_code'])
        lines.append(f"| {s['sample_id']} | {s['population']}:{s['split']} | {' | '.join(parts)} |")
    lines+=['','A resource-failure UNKNOWN demonstrates withholding by release policy. It does not demonstrate semantic detection of the unresolved relation. Raw reasoning fragments are not usable witnesses and receive no semantic-success credit. Blocking `m012` alone cannot establish safety or useful coverage. Every known unsafe case and its complete provider record remains inspectable.','',
        '## False positives, false negatives and disagreements','',
        f"Model gate verdict disagreements: {summary['model_gate_disagreement_count']}. They include availability differences, schema failures and semantic differences; disagreement is not proof of independence.",'',
        'Every incremental false rejection of a B-exact valid source is listed below; inherited B failures remain in the outcome table and per-sample evidence. `analysis.json` retains the original source, family, status, reason and resource classification for each one.','',
        '| Treatment | Incremental false rejection count | Case IDs |','|---|---:|---|']
    for name in ['ambiguity','source_verifier','bounded']:
        ids=summary['cohorts']['all'][name]['incremental_false_rejection_ids']
        lines.append(f"| {name} | {len(ids)} | {', '.join(ids) or 'none'} |")
    lines+=['','False-negative unauthorized releases are retained verbatim in `analysis.json`; zero observed releases is only a known-population finding. UNKNOWN availability losses are not reclassified as source ambiguity. Semantic false positives must be distinguished from incomplete source coverage, plan disagreement, provider incompleteness and transport failure.','',
        '## Dependency risk and known failure modes','',
        'Compiler and both model gates share deepseek-flash, model priors, language defaults, attention/scope omissions and transport. The verifier sees B in the same request; asking it to derive source-first cannot make that extraction statistically independent or prevent anchoring. Complete copied spans and unanimous UNIQUE labels can be semantically false. A schema-valid hallucinated source plan that equals B can still release an unauthorized Mission. Neither zero observed acceptance nor gate agreement establishes an independent safety guarantee.','',
        'The observed resource mechanism is exhaustion of the unchanged 4096-token output budget by reasoning and/or verbose evidence before a usable witness is emitted. This causes false rejection and real token/latency cost. Partial assistant output is rejected, never repaired. Other risks are over-expanding repetitions/restatements, over-refusing valid edits/references, numeric/temporal scope errors, and strict ID/dependency equality rejecting equivalent representation. The bounded control avoids model dependence but inherits parser/normalization conventions and sacrifices open-language coverage. Unsupported grammar is UNKNOWN, not proof the source is ambiguous.','',
        '## Reproducibility and evidence','',
        'See `CONTRACT.md`, `protocol.json`, `preflight.json`, `provider_recovery.json`, `baseline_replay.json`, `samples/`, `acquisition/`, `bounded_control.json`, `summary.json`, `analysis.json`, and `PACKAGING.md`. Per-stage begin/end/first-response receipts are durable. Resume reads completed stages, replays already saved first responses without network calls, or withholds unavailable interrupted responses; it never repeats an observed semantic call. Frozen inputs are joined by exact population and sample ID.','',
        'New paths have scoped -text Git attributes. Anchor snapshots are raw Git blobs with separate provenance, leaving old CRLF/LF pins/tags untouched. The content manifest hashes raw bytes and the deterministic ZIP has fixed metadata, sorted paths and no compression-version dependence. Fresh checkouts must independently reproduce manifest/archive hashes with autocrlf true and false. Stored timings are data, not a claim of deterministic model reruns.','',
        '## Decision','',
        'This Pilot can establish whether release policy withholds known unauthorized candidates and measure its coverage/cost tradeoff. Model resource failures cannot justify advancing D011 into a formal safety architecture decision. Keep D011 candidate and Runtime BLOCKED. The quantitative results and per-case reasons determine whether the next step is more development/resource design or a separately frozen independent held-out study. The latter requires independent authorship, development/calibration/held-out splits, no disclosure of verifier rules to the author, and first evaluation only after freeze. It has not begun.','']
    path=BASE/'report.md'
    with path.open('x',encoding='utf8',newline='\n') as handle:handle.write('\n'.join(lines))

def main():
    rows=[pilot.read(p) for p in sorted((BASE/'samples').glob('*.json'))]
    if len(rows)!=len(pilot.read(BASE/'inputs.json')['populations']):raise ValueError('original paired acquisition not complete')
    bounded_control(rows);analyze(rows)
    print(json.dumps({'complete_rows':len(rows),'summary':'summary.json','report':'report.md'}))

if __name__=='__main__':main()
