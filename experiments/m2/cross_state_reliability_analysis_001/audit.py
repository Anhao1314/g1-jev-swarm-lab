"""Independent saved-byte M2.4 audit. No simulator, policy, provider or runner imports."""
import gzip
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RAW = ROOT / 'experiments/m2/cross_state_reliability_001/artifacts'

def read(p):
    return json.loads(Path(p).read_text(encoding='utf8'))

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def encoded(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def finite(v):
    if isinstance(v, dict): return all(finite(x) for x in v.values())
    if isinstance(v, list): return all(finite(x) for x in v)
    return not isinstance(v, (int, float)) or math.isfinite(v)

def canonical(v):
    return {'schema_version':v['schema_version'], 'mission_id':v['mission_id'], 'steps':[
        {'id':r['id'], 'skill':r['skill'], 'parameters':{k:float(x) for k,x in r['parameters'].items()}, 'depends_on':r.get('depends_on', [])} for r in v['steps']]}

def nodes_plan(v):
    return [{'id':r['node_id'], 'skill':r['skill'], 'parameters':r['parameters'], 'depends_on':r['depends_on']} for r in v]

def yaw(q):
    w,x,y,z=q
    return math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))

def walk(node):
    s,e=node['start_state'], node['end_state']
    h=yaw(s['base_orientation']); dx,dy=[e['base_position'][i]-s['base_position'][i] for i in (0,1)]
    return {'distance_error_m':math.cos(h)*dx+math.sin(h)*dy-node['parameters']['distance_m'],
            'lateral_drift_m':-math.sin(h)*dx+math.cos(h)*dy,
            'heading_error_deg':math.degrees((yaw(e['base_orientation'])-h+math.pi)%(2*math.pi)-math.pi),
            'simulation_time_s':e['simulation_time']-s['simulation_time']}

def strict(m, target):
    limits={'distance_error_m':max(.15,.05*target),'lateral_drift_m':max(.20,.035*target),'heading_error_deg':8.,'simulation_time_s':max(12.,5.*target)}
    margins={k:limits[k]-abs(m[k]) for k in limits}
    return {'pass':all(x>=0 for x in margins.values()), 'metrics':m, 'limits':limits, 'margins':margins}

def physical(rows):
    return bool(rows) and all(finite(r) and r['finite'] and r['standing'] and not r['fallen'] and r['base_height_m']>=.55 and r['tilt_deg']<=30 for r in rows)

def halt_metrics(h):
    rows=h['trace']; speeds=[r['speed_mps'] for r in rows]
    duration=h['final_state']['simulation_time']-h['pre_halt_state']['simulation_time']
    disp=math.dist(h['pre_halt_state']['base_position'][:2],h['final_state']['base_position'][:2])
    mean=statistics.mean(speeds[-500:]) if len(rows)>=500 else None
    checks={'skill_success':h['skill_status']=='SUCCESS','duration':duration<=4.,'final_speed':bool(rows) and speeds[-1]<=.1,
            'window_mean_speed':mean is not None and mean<=.1,'displacement':disp<=.5,
            'finite_throughout':bool(rows) and all(finite(r) and r['finite'] for r in rows),
            'standing_throughout':bool(rows) and all(r['standing'] and r['base_height_m']>=.55 and r['tilt_deg']<=30 for r in rows),
            'no_fall_throughout':bool(rows) and not any(r['fallen'] for r in rows)}
    return {'checks':checks,'pass':all(checks.values()),'duration_s':duration,'last_1s_mean_speed_mps':mean,
            'final_speed_mps':speeds[-1] if rows else None,'displacement_m':disp,
            'margins':{'duration_s':4-duration,'mean_speed_mps':.1-mean if mean is not None else None,'final_speed_mps':.1-speeds[-1] if rows else None,'displacement_m':.5-disp},
            'minimum_height_m':min(r['base_height_m'] for r in rows),'maximum_tilt_deg':max(r['tilt_deg'] for r in rows),
            'speed_trace_source':'parent_result.json#/physical_halt/trace'}

def invariant(p):
    q=p['qpos']; h=yaw(q[3:7]); c,s=math.cos(h),math.sin(h)
    w,x,y,z=q[3:7]; a,b=math.cos(-h/2),math.sin(-h/2)
    tiltq=[a*w-b*z,a*x-b*y,a*y+b*x,a*z+b*w]
    v=p['qvel']; bodyv=[c*v[0]+s*v[1],-s*v[0]+c*v[1],v[2]]
    return {'height':q[2], 'yaw_removed_orientation':tiltq,'yaw_removed_velocity':bodyv,
            'joint_positions':q[7:],'joint_velocities':v[6:],'angular_velocity':v[3:6],
            'ctrl':p['ctrl'],'controller_action':p.get('controller_action'), 'controller_target':p.get('controller_target')}

def maxdiff(a,b):
    if isinstance(a,list): return max((maxdiff(x,y) for x,y in zip(a,b)),default=0.)
    if a is None or b is None: return 0. if a==b else None
    return abs(a-b)

def run(*, verify=False, raw_root=None):
    if raw_root is not None and not verify:
        raise ValueError('--raw-root requires read-only verification')
    global RAW
    restored_root = Path(raw_root).resolve() if raw_root is not None else ROOT
    RAW = restored_root / 'experiments/m2/cross_state_reliability_001/artifacts'
    started=time.perf_counter(); checks=[]; stages=[]; endpoints={}; native_total=0; negatives=[]; gaps=[]
    def check(name,passed,cell=None,details=None):
        checks.append({'check':name,'passed':bool(passed),'cell':cell,'details':details})
    spec=read(ROOT/'experiments/m2/cross_state_reliability_001/protocol.json'); seal=read(HERE/'raw_evidence_manifest.json')
    check('sealed_raw_exact_bytes',all((restored_root/p).stat().st_size==r['bytes'] and sha(restored_root/p)==r['sha256'] for p,r in seal['files'].items()))
    check('approved_readiness_exact',sha(ROOT/'experiments/m2/cross_state_reliability_readiness_001/readiness_manifest.json')==seal['readiness_sha256']=='14219b6edc85d8346a97d5e50895d924c1157c6abffab37bd926dbfe4b138f08')
    receipt=read(RAW/'campaign_receipt.json'); check('seven_once_only_frozen_membership',receipt['completed_cells']==spec['run_order'] and len(list(RAW.glob('*--*')))==7)
    plan=canonical(spec['new_mission']); plan_sha=hashlib.sha256(encoded(plan)).hexdigest(); check('canonical_full_plan_hash',plan_sha==spec['expected_complete_plan_sha256'])
    for cell in spec['run_order']:
        label=cell['state_id']+'--'+cell['arm']; base=RAW/label
        parent=read(base/'parent_result.json'); graph=read(base/'parent_graph.json'); endpoint=read(base/'halt_endpoint.json')
        witness=read(base/'witness.json'); requests=read(base/'requests.json'); entries=read(base/'dispatch_entries.json'); preservation=read(base/'parent_preservation.json')
        with gzip.open(base/'state_trace.jsonl.gz','rt',encoding='utf8') as f: trace=[json.loads(x) for x in f]
        native=read(base/'native_state_trace.json'); native_total+=len(native)
        check('native_callthrough_journal_counts',len(native)==len(trace)==witness['steps']==sum(1 for x in (base/'native_incremental.jsonl').open(encoding='utf8') if x.strip()),label)
        check('two_startup_resets_no_keyframe',witness['reset_calls']==witness['reset_data_calls']==2 and witness['reset_keyframe_calls']==0,label)
        check('arm_native_budget',len(native)<=cell['max_steps'],label)
        check('parent_result_graph_ledger_immutable',sha(base/'parent_result.json')==preservation['parent_result_sha256'] and preservation['result_unchanged'] and preservation['graph_unchanged'] and preservation['ledger_before']==preservation['ledger_after'] and all(sha(base/'ledger'/p)==v for p,v in preservation['ledger_before'].items()),label)
        pre=read(base/'predecision_native_trace.json'); check('native_prefix_and_endpoint_exact',native[:len(pre)]==pre and all(pre[-1][k]==endpoint[k] for k in ('qpos','qvel','ctrl','time_s')),label)
        check('force_zero_at_decision',not any(v for row in pre[-1]['xfrc_applied'] for v in row),label)
        row={'cell':label,'parent_state':parent['state'],'parent_physical_success':parent['physical_success'],'parent_failure_type':parent['failure_type'],'native_steps':len(native),'halt_trigger_present':bool(parent.get('physical_halt'))}
        walks=[]
        for n in graph['nodes']:
            if n['skill']=='walk_forward' and n.get('start_state') and n.get('end_state'):
                result=strict(walk(n),n['parameters']['distance_m']); walks.append(result)
                obs=next(r for r in parent['nodes'] if r['node_id']==n['node_id'])['feedback_decision']
                check('parent_strict_metrics_and_action_rederived',all(math.isclose(result['metrics'][k],obs['observed_metrics'][k],abs_tol=1e-10,rel_tol=0) for k in result['metrics']) and (obs['action']=='CONTINUE')==result['pass'],label)
        row['parent_strict_walk']=walks
        if cell['state_id']=='normal_control':
            good=parent['state']=='SUCCESS' and parent['mission_success'] and parent['physical_success'] and parent['completed_nodes']==3 and not parent.get('physical_halt') and not requests and not entries and not read(base/'lifecycle_events.json') and all(n['state']=='SUCCESS' for n in graph['nodes'])
            row['stage']='NORMAL_CONTROL_PASS' if good else 'NORMAL_CONTROL_REGRESSION'
            if not good: negatives.append(label)
            stages.append(row); continue
        endpoints[cell['state_id']]=endpoint
        halt=parent.get('physical_halt')
        if not halt:
            row.update(stage='NO_HALT_TRIGGER',assessment='NOT_ASSESSED',authorization='NOT_ISSUED',new_mission='NOT_DISPATCHED')
            check('absent_trigger_has_no_forced_halt_or_authorization',not entries and not requests and not (base/'assessment.json').exists() and not (base/'new_result.json').exists(),label)
            gaps.append(label+':NO_HALT_TRIGGER'); stages.append(row); continue
        hm=halt_metrics(halt); row['halt']=hm
        check('halt_recorded_checks_equal_raw_recomputation',hm['checks']==halt['checks'] and (halt['status']=='HALT_SUCCEEDED')==hm['pass'],label)
        if not hm['pass']:
            row['stage']='HALT_FAILED'; negatives.append(label); check('failed_halt_no_new_dispatch',not entries and not requests,label); stages.append(row); continue
        assess=read(base/'assessment.json'); ground=assess['grounding']
        eligible=parent['state']=='FAILED' and endpoint['state']==halt['final_state']==assess['state'] and finite(endpoint) and math.hypot(*endpoint['qvel'][:2])<=.1 and endpoint['state']['standing'] and not endpoint['state']['fallen'] and assess['validation']['valid'] and ground['status']=='GROUNDED' and all(not r['experimental_override'] and r['risk'] in ('LOW','MEDIUM') for r in ground['results']) and parent['mission_id']!=plan['mission_id'] and not ({n['node_id'] for n in graph['nodes']} & {n['id'] for n in plan['steps']})
        check('assessment_eligibility_rederived',eligible==assess['eligible'] and (not eligible or not assess['reasons']),label)
        row.update(eligible=eligible,assessment_reasons=assess['reasons'])
        if not eligible:
            row['stage']='INELIGIBLE'; negatives.append(label); check('ineligible_no_grant_dispatch',not entries and not requests,label); stages.append(row); continue
        denied=[r for r in requests if 'before' in r]
        details=[{'request':r['request'],'reason':r['result']['reason'],'physics_delta':r['after']['witness_steps']-r['before']['witness_steps'],'executor_delta':r['after']['executor_calls']-r['before']['executor_calls'],'node_delta':r['after']['node_calls']-r['before']['node_calls'],'reset_delta':r['after']['reset_calls']-r['before']['reset_calls'],'raw_equal':r['before']==r['after']} for r in denied]
        row['authorization_refusals']=details
        check('refusals_zero_incremental_execution_raw_change',bool(denied) and all(r['before']==r['after'] and r['result']['status']=='ESCALATE' and r['result']['new_mission_result'] is None and r['result']['parent_preserved'] for r in denied),label,details)
        issued=[r for r in read(base/'handoff_events.json') if r['event']=='fixture_handoff_issued']
        check('issuer_full_plan_test_only_domains',bool(issued) and all(r['signed_plan_sha256']==plan_sha and r['production_authority'] is False and r['assurance']=='TEST_ONLY_SIMULATED_PRINCIPAL' and r['original_source_unique'] is False and r['handoff_semantics_sha256']!=plan_sha for r in issued) and assess['mission_sha256']!=plan_sha,label)
        if cell['arm']=='authorization_refusals':
            check('six_exact_refusal_controls_no_new_dispatch',[r['request'] for r in requests]==spec['negative_requests_if_eligible_order'] and not entries and not (base/'new_result.json').exists() and witness['executor_calls']==0,label)
            stale=read(base/'stale_state_step.json'); b,a=stale['before'],stale['after']
            check('separate_stale_step_one_unchanged_controller',a['witness_steps']-b['witness_steps']==1 and a['ctrl']==b['ctrl'] and all(a[k]==b[k] for k in b if k.startswith('controller')),label)
            check('refusal_reasons_independent_permission_and_burned_grants',[r['result']['reason'] for r in requests]==['UNTRUSTED_HANDOFF','PLAN_CHANGED','UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF','PRINCIPAL_CONTINUATION_PERMISSION_MISSING','ASSESSMENT_REJECTED','UNTRUSTED_REPLAYED_OR_REVOKED_HANDOFF'],label)
            row['stage']='AUTHORIZATION_REFUSALS'; stages.append(row); continue
        check('positive_and_replay_exact_membership',[r['request'] for r in requests]==spec['positive_if_eligible'],label)
        new=read(base/'new_result.json'); ledger=base/'ledger'/plan['mission_id']; manifest=read(ledger/'mission_manifest.json'); child=read(ledger/'task_graph.json')
        check('issuer_actual_persisted_complete_plan',len(entries)==1 and entries[0]['canonical_mission']==plan==canonical(manifest['mission_input']) and nodes_plan(child['nodes'])==plan['steps'],label)
        ev=entries[0]['before']; check('actual_entry_halt_state_no_reset',all(ev[k]==endpoint[k] for k in ('qpos','qvel','ctrl','state','time_s','session_identity','simulation_identity','controller_identity','reset_calls','reset_data_calls','controller_action','controller_target','controller_counter')) and ev['executor_calls']==1,label)
        dispatches=read(base/'node_dispatches.json'); dispatched=[r for r in dispatches if r['phase']=='new_mission']
        check('old_nodes_never_redispatched',not ({r['node_id'] for r in dispatched}&{r['node_id'] for r in graph['nodes']}),label)
        newrows=[r for r in trace if r['phase']=='new_mission']; stops=[r for r in newrows if r['active_skill']=='stop']; mean=statistics.mean(r['speed_mps'] for r in stops[-500:]) if len(stops)>=500 else None
        wm=strict(walk(child['nodes'][0]),4.)
        success=new['state']=='SUCCESS' and new['mission_success'] and new['physical_success'] and new['completed_nodes']==3 and all(n['state']=='SUCCESS' for n in child['nodes']) and nodes_plan(dispatched)==plan['steps'] and wm['pass'] and physical(newrows) and mean is not None and mean<=.1 and stops[-1]['speed_mps']<=.1
        check('child_strict_metrics_rederived',all(math.isclose(wm['metrics'][k],new['nodes'][0]['feedback_decision']['observed_metrics'][k],rel_tol=0,abs_tol=1e-10) for k in wm['metrics']),label)
        row.update(stage='NEW_TASK_SUCCESS' if success else 'NEW_TASK_FAILED',new_strict_walk=wm,new_all_nodes=[n['state'] for n in child['nodes']],new_physical_success=physical(newrows),new_stop_final_speed_mps=stops[-1]['speed_mps'] if stops else None,new_stop_last_1s_mean_speed_mps=mean,new_child_halt=new.get('physical_halt'))
        if not success: negatives.append(label)
        stages.append(row)
    check('campaign_total_native_budget_receipt',native_total==receipt['native_steps'] and native_total<=270000)
    for state in spec['states']:
        a,b=[RAW/(state['id']+'--'+arm) for arm in ('authorized_new_mission','authorization_refusals')]
        check('paired_predecision_full_native_and_robot_trace_exact',all((a/f).read_bytes()==(b/f).read_bytes() for f in ('predecision_trace.json','predecision_native_trace.json')),state['id'])
    oldspec=read(ROOT/'experiments/m2/trusted_handoff_qualification_001/protocol.json'); old=ROOT/oldspec['comparators']['historical_invalid']
    with gzip.open(old/'state_trace.jsonl.gz','rt',encoding='utf8') as f: oldtrace=[json.loads(x) for x in f]
    seen=RAW/'seen_reference_walk6--authorized_new_mission'; check('seen_anchor_exact_robot_trace',read(seen/'predecision_trace.json')==oldtrace)
    import numpy as np
    with np.load(old/'poses.npz') as oldposes, np.load(seen/'poses.npz') as poses:
        check('seen_anchor_exact_pose_prefix',all(np.array_equal(poses[k][:len(oldposes[k])],oldposes[k]) for k in ('qpos','qvel','ctrl','time_s')))
    distinct={}; anchor=invariant(endpoints['seen_reference_walk6'])
    for state in ('transition_turn45_walk6','push60_walk6'):
        current=invariant(endpoints[state]); differences={k:maxdiff(anchor[k],current[k]) for k in anchor}
        # No post-hoc numerical cutoff; exact joints/control differences establish non-rigid-transform conditions.
        beyond=any(differences[k]>0 for k in ('joint_positions','joint_velocities','ctrl'))
        distinct[state]={'max_absolute_differences':differences,'beyond_world_xy_yaw':beyond,'comparison_boundary':'end of parent/halt, not identical event in no-trigger push','independent_random_seed':False}
        if not beyond:gaps.append(state+':DUPLICATE_STATE')
    push=RAW/'push60_walk6--authorized_new_mission'; events=read(push/'push_events.json'); rawpush=read(push/'predecision_native_trace.json')
    forces=[r for r in rawpush if any(x for body in r['xfrc_applied'] for x in body)]
    check('push_fixed_native_timing_magnitude_and_release',len(forces)==100 and all(r['xfrc_applied'][1][:3]==[0.,60.,0.] for r in forces) and events[0]['event']=='push_start' and math.isclose(events[0]['sim_time'],1.,abs_tol=1e-12) and events[1]['event']=='push_end' and math.isclose(events[1]['sim_time'],1.2,abs_tol=1e-12))
    integrity=all(c['passed'] for c in checks)
    verdict='FAIL' if negatives else ('INCONCLUSIVE' if gaps or not integrity else 'PASS')
    result={'verdict':verdict,'integrity_verdict':'PASS' if integrity else 'FAIL','campaign_complete':True,'stages':stages,'checks':checks,'scientific_negative_cells':negatives,'missing_coverage':gaps,'state_differences':distinct,'native_steps':native_total,'raw_manifest_sha256':sha(HERE/'raw_evidence_manifest.json'),'audit_source_sha256':sha(__file__),'tokens':{'model_tokens':'NOT_AVAILABLE','provider_calls':0,'provider_tokens':0},'scope':'Single seed-0 deterministic conditions, paired arms are copies. One newly reached failure/halt condition supports bounded chain; push passed strict parent and did not test failure/halt/assessment/authorization/new task. No production identity, hardware stopping, generalized restart or statistical reliability claim.','elapsed_s':time.perf_counter()-started}
    if verify:
        retained=read(HERE/'audit.json')
        # The retained source hash identifies the original write-once audit;
        # adding this verifier must not replace that provenance identity.
        result['audit_source_sha256']=retained['audit_source_sha256']
        expected={k:v for k,v in retained.items() if k!='elapsed_s'}
        actual={k:v for k,v in result.items() if k!='elapsed_s'}
        if actual!=expected:
            raise ValueError('SAVED_AUDIT_RECOMPUTATION_MISMATCH')
        print(json.dumps({'verification':'PASS','verdict':verdict,'integrity':result['integrity_verdict'],'checks':len(checks),'native_steps':native_total,'retained_audit_unchanged':True,'verifier_source_sha256':sha(__file__)}))
        return
    for name,value in [('audit.json',json.dumps(result,indent=2,allow_nan=False)+'\n'),('audit.md',f'# Independent M2.4 scientific audit\n\nVerdict: **{verdict}**. Integrity: **{result["integrity_verdict"]}**. All seven planned arms completed once; {native_total} native steps.\n\n'+ '\n'.join(f'- {r["cell"]}: {r["stage"]}.' for r in stages)+'\n\nThe transition condition supports the bounded failure → successful halt → eligible exact state → registered TEST_ONLY complete-plan continuation chain. Its joint/control state differs beyond a world transform. The push parent succeeds under the frozen strict envelope, so its two cells have NO_HALT_TRIGGER and no issuance or dispatch; those cells are missing failure-chain coverage, never authorization or physical-stop PASS. Both eligible refusal arms reject six controls with zero incremental execution; deliberate stale-state steps are separate. Normal control retains ordinary success with no lifecycle.\n\n'+result['scope']+'\n\nRaw source: raw_evidence_manifest.json; detailed per-stage metrics, margins and raw checks: audit.json. Provider calls/tokens: 0; model token usage unavailable. No physics, policy evaluation, retries or new cases in this audit. Stop: frozen matrix and independent saved-byte audit complete.\n')]:
        with (HERE/name).open('x',encoding='utf8',newline='\n') as f:f.write(value)
    print(json.dumps({'verdict':verdict,'integrity':result['integrity_verdict'],'failed_checks':[c for c in checks if not c['passed']],'missing_coverage':gaps,'native_steps':native_total}))

if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--raw-root', type=Path, help='Restore destination root containing experiments/...; repository comparators remain pinned here')
    args = parser.parse_args()
    if args.raw_root is not None and not args.verify:
        parser.error('--raw-root requires --verify (read-only)')
    run(verify=args.verify, raw_root=args.raw_root)
