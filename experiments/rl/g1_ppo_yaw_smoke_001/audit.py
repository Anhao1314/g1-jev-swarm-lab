"""Independent read-only raw audit: no simulator, policy or Torch import."""
import hashlib,json,math,sys
from collections import Counter
from pathlib import Path

def audit(root):
    root=Path(root); result=json.loads((root/"result.json").read_text())
    reservations=[]; completions=[]; events=[]
    for line in (root/"native.jsonl").open():
        row=json.loads(line)
        (reservations if "reservation" in row else completions).append(row)
    events=[json.loads(x) for x in (root/"decisions.jsonl").open()]
    tests={}
    tests["native_reservation_sequence"]=[x["reservation"] for x in reservations]==list(range(1,len(reservations)+1))
    tests["native_completion_sequence"]=[x["completed"] for x in completions]==list(range(1,len(completions)+1))
    tests["no_missing_tail"]=len(reservations)==len(completions)==result["native_completed"]
    tests["global_steps"]=len(reservations)<=60000
    b0=[{k:v for k,v in x.items() if k not in ('completed','stage')} for x in completions if x["stage"]=='B0']
    b1=[{k:v for k,v in x.items() if k not in ('completed','stage')} for x in completions if x["stage"]=='B1']
    tests["raw_B0_B1_exact"]=b0==b1 and bool(b0)
    tests["native_finite_no_fall"]=all(not x["fallen"] and all(math.isfinite(v) for k in ('qpos','qvel','torques','target','applied_command') for v in x[k]) for x in completions)
    tests["command_authority"]=all(x['active_skill']=='walk_forward' and x['applied_command'][:2]==x['deterministic_command'][:2] and abs(x['applied_command'][2])<=.6 and abs(x['applied_command'][2]-x['deterministic_command'][2])<=.120000000001 for x in completions)
    transitions=[x for x in events if x['kind']=='transition' and x['stage']=='train']
    tests["256_train_interactions"]=len(transitions)==result['ppo_decisions']==256
    tests["actions_observations_rewards_finite"]=all(len(x['observation'])==18 and all(math.isfinite(v) and abs(v)<=1 for v in x['observation']) and abs(x['info']['requested_action'][0])<=1 and math.isfinite(x['reward']) for x in transitions)
    tests["reward_components_recompute"]=all(abs(sum(x['info']['reward_terms'].values())-x['reward'])<1e-12 for x in transitions)
    steps=[x for x in events if x['kind']=='optimizer_step']
    tests["optimizer_step_receipts"]=[x['step'] for x in steps]==list(range(1,result['optimizer_steps']+1)) and 0<result['optimizer_steps']<=8
    updates=[x for x in events if x['kind']=='ppo_update']
    tests["checkpoint_update_boundaries"]=[x['decisions'] for x in updates]==[128,256]
    tests["losses_finite"]=all(math.isfinite(v) for x in updates for v in x['metrics'].values())
    tests["checkpoint_bytes"]=all(hashlib.sha256((root/f'checkpoint-{n}.zip').read_bytes()).hexdigest()==h for n,h in result['checkpoint_sha256'].items())
    tests["wall_budgets"]=result['physical_wall_s']<1800 and result['training_wall_s']<600
    tests["external_cap_truncated"]=transitions[-1]['truncated'] or transitions[-1]['terminated']
    tests["checker_before_optimizer"]=next(i for i,x in enumerate(events) if x['kind']=='check_env_pass')<next(i for i,x in enumerate(events) if x['kind']=='optimizer_step')
    receipt=json.loads((root/'process-receipt.json').read_text())
    tests['supervisor_success']=receipt['native_exitcode']==0 and receipt['interrupted'] is None and receipt['elapsed_s']<1800
    return {'verdict':'PASS' if all(tests.values()) else 'FAIL','checks':tests,
            'stages_native':dict(Counter(x['stage'] for x in completions)),
            'terminal_train_outcomes':[x['info']['outcome'] for x in transitions if x['terminated']],
            'optimizer_updates':updates,'native_reservations':len(reservations)}
if __name__=='__main__':
    value=audit(sys.argv[1]); print(json.dumps(value,indent=2)); raise SystemExit(0 if value['verdict']=='PASS' else 1)
