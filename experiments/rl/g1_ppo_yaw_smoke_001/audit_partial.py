"""Post-run read-only audit of the stopped T1 attempt. Never imports physics/Torch."""
import collections,hashlib,json,math,sys
from pathlib import Path

def audit(root):
    r=Path(root); failure=json.loads((r/'failure.json').read_text())
    reserved=[]; completed=[]
    for line in (r/'native.jsonl').open():
        x=json.loads(line); (reserved if 'reservation' in x else completed).append(x)
    events=[json.loads(line) for line in (r/'decisions.jsonl').open()]
    tests={}
    tests['reservation_sequence']=[x['reservation'] for x in reserved]==list(range(1,len(reserved)+1))
    tests['completion_sequence']=[x['completed'] for x in completed]==list(range(1,len(completed)+1))
    tests['no_missing_tail']=len(reserved)==len(completed)==failure['native_completed']==failure['native_reserved']
    tests['global_step_budget']=len(reserved)<=60000
    rows=lambda stage:[{k:v for k,v in x.items() if k not in ('completed','stage')} for x in completed if x['stage']==stage]
    tests['raw_B0_B1_exact']=rows('B0')==rows('B1') and bool(rows('B0'))
    tests['evaluator_exact']=json.loads((r/'b0.json').read_text())['evaluation']==json.loads((r/'b1.json').read_text())['evaluation']
    tests['zero_residual_exact']=all(x['applied_command']==x['deterministic_command'] for x in completed if x['stage'] in ('B0','B1'))
    tests['all_native_finite_no_fall']=all(not x['fallen'] and all(math.isfinite(v) for k in ('qpos','qvel','torques','target','applied_command') for v in x[k]) for x in completed)
    tests['yaw_authority']=all(x['active_skill']=='walk_forward' and x['applied_command'][:2]==x['deterministic_command'][:2] and abs(x['applied_command'][2])<=.6 and abs(x['applied_command'][2]-x['deterministic_command'][2])<=.120000000001 for x in completed)
    transitions=[x for x in events if x['kind']=='transition' and x['stage']=='train']
    tests['training_decision_budget']=len(transitions)<=256
    tests['observations_actions_rewards_valid']=all(len(x['observation'])==18 and all(math.isfinite(v) and abs(v)<=1 for v in x['observation']) and abs(x['info']['requested_action'][0])<=1 and len(x['info']['raw_observation'])==18 and len(x['info']['clipped'])==18 and math.isfinite(x['reward']) for x in transitions)
    tests['reward_sum']=all(abs(x['reward']-sum(x['info']['reward_terms'].values()))<1e-12 for x in transitions)
    tests['check_env_completed_before_train']=any(x['kind']=='check_env_pass' for x in events) and all(x['stage']!='train' for x in events[:next(i for i,x in enumerate(events) if x['kind']=='check_env_pass')+1])
    tests['no_optimizer_or_update']=not any(x['kind'] in ('optimizer_step','ppo_update') for x in events)
    tests['initial_checkpoint_only']=(r/'checkpoint-0.zip').is_file() and not (r/'checkpoint-128.zip').exists() and not (r/'checkpoint-256.zip').exists()
    tests['no_false_pass']=not (r/'result.json').exists() and failure['verdict']=='T1_BLOCKED_WITH_EXACT_EVIDENCE'
    proc=json.loads((r/'process-receipt.json').read_text())
    tests['stopped_on_exception']=proc['native_exitcode']==1 and proc['interrupted'] is None
    tests['wall_budget']=proc['elapsed_s']<1800 and failure['physical_wall_s']<1800
    train_start=json.loads((r/'training-start.json').read_text())['monotonic']
    # Exact training interval was not saved at exception; overall elapsed is a strict upper bound.
    tests['training_wall_upper_bound']=proc['elapsed_s']<600
    outcomes=[x['info']['outcome'] for x in transitions if x['terminated']]
    return {'integrity_verdict':'PASS' if all(tests.values()) else 'FAIL','scientific_verdict':'T1_BLOCKED_WITH_EXACT_EVIDENCE',
            'checks':tests,'check_count':len(tests),'native_by_stage':dict(collections.Counter(x['stage'] for x in completed)),
            'native_reserved':len(reserved),'native_completed':len(completed),'train_interactions':len(transitions),
            'optimizer_updates':0,'training_wall_exact':'NOT_RECORDED_ON_EXCEPTION','training_wall_upper_bound_s':proc['elapsed_s'],
            'initial_checkpoint_sha256':hashlib.sha256((r/'checkpoint-0.zip').read_bytes()).hexdigest(),
            'terminal_train_outcomes':outcomes,'failure':failure,'supervisor':proc}
if __name__=='__main__':
    value=audit(sys.argv[1]); print(json.dumps(value,indent=2)); raise SystemExit(0 if value['integrity_verdict']=='PASS' else 1)
