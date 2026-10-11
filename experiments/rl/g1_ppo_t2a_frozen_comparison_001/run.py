"""Candidate T2a evaluator. Operator flag is a guard, not evidence of Owner authority.

A Worker runs only when it is spawned by this file's supervisor and consumes that
supervisor's private one-time delegation; a bare --worker-owner-approved argv flag,
environment self-report or caller-authored JSON never authorizes execution.
"""
import argparse,hashlib,importlib.metadata,importlib.util,json,os,subprocess,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
SUPERVISOR_CUTOFF_S=595.
SUPERVISOR_TOTAL_S=600.
sys.path.insert(0,str(HERE))
from comparison import classify,curves,matched_delta,lock_actor,frozen_action
import supervision

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(path,expected):
    if sha(path)!=expected:raise RuntimeError('readiness_mismatch')
    m=json.loads(Path(path).read_text())
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()!=m['execution_head']:
        raise RuntimeError('wrong_execution_head')
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT,text=True).strip():raise RuntimeError('dirty_source')
    if Path(sys.prefix).resolve()!=Path(m['venv']).resolve():raise RuntimeError('wrong_venv')
    if os.environ.get('G1SWARM_ROOT') or os.environ.get('PYTHONHOME'):raise RuntimeError('source_override')
    if Path(importlib.util.find_spec('g1swarm').origin).resolve()!=ROOT/'src/g1swarm/__init__.py':raise RuntimeError('import_source_drift')
    if sha(Path(sys.executable).resolve())!=m['python_executable_sha256']:raise RuntimeError('python_drift')
    for p,h in m['files'].items():
        if sha(ROOT/p)!=h:raise RuntimeError('source_asset_drift:'+p)
    for p,h in m['installed_files'].items():
        if sha(Path(sys.prefix)/p)!=h:raise RuntimeError('dependency_byte_drift:'+p)
    for n,v in m['dependencies'].items():
        if importlib.metadata.version(n)!=v:raise RuntimeError('dependency_version_drift:'+n)
    protocol=json.loads((HERE/'protocol.json').read_text())
    if sha(HERE/'protocol.json')!=m['protocol_sha256']:raise RuntimeError('protocol_drift')
    if protocol['groups']!=['B0','C0','C256'] or protocol['budgets']!={'total_native_steps':36000,'per_group_native_steps':12000,'wall_s':600,'supervisor_cutoff_s':595,'attempts_per_group':1}:raise RuntimeError('budget_or_membership_drift')
    for group,row in m['checkpoints'].items():
        if sha(row['path'])!=row['sha256'] or row['sha256']!=protocol['checkpoints'][group]['sha256']:raise RuntimeError('checkpoint_drift:'+group)
    return m

def execute(root,manifest,expected,delegation=None):
    supervision.claim_execute(delegation,run_identity=root,manifest=manifest,readiness_sha256=expected,
        execution_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        protocol_sha256=sha(HERE/'protocol.json')) # one-shot, argument-bound permit before runtime imports
    m=verify(manifest,expected) # before Torch/MuJoCo or real policy imports
    import numpy as np
    import torch
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
    from g1swarm.residual_rl.environment import Ledger,make_stack,metrics,G1YawResidualEnv,PhysicalAbort
    from g1swarm.control.path_correction import CorrectingController
    from g1swarm.segmentation.mission import MissionFrame
    from g1swarm.skills.basic import WalkForwardSkill
    from g1swarm.skills.contract import SkillContext
    from g1swarm.residual_rl.ppo import AuditedPPO
    ledger=Ledger(root,limit=36000);results={};trajectories={};initials={};started=time.monotonic();sim=env=None;frame=None
    try:
        for group in ('B0','C0','C256'):
            ledger.stage=group;torch.manual_seed(7);np.random.seed(7)
            if time.monotonic()-started>=590:raise RuntimeError('wall_budget')
            if group=='B0':
                robot,sim,low,policy=make_stack(ledger,baseline=True)
                sim.reset(seed=7);frame=MissionFrame.from_state(sim.get_robot_state())
                ctrl=CorrectingController(low,policy,sim,frame)
                ctx=SkillContext(simulation=sim,controller=ctrl,robot_config=robot,parameters={'target_distance_m':4.,'speed_mps':.5,'max_duration_s':24.},max_steps=12000,seed=7)
                skill=WalkForwardSkill()
                if skill.check_preconditions(ctx):raise RuntimeError('B0_precondition_failed')
                initials[group]={'qpos':sim._data.qpos.tolist(),'simulator_resets':sim.resets}
                ledger.event('initial',**initials[group],controller_resets_before_skill=low.resets)
                skill_result=skill.run(ctx)
                record=metrics(sim,frame);record.update(skill_result=skill_result.to_dict(),target_reached=record['forward_displacement_m']>=4.)
                rows=sim.rows.copy()
            else:
                checkpoint=Path(m['checkpoints'][group]['path'])
                actor=AuditedPPO.load(checkpoint,device='cpu')
                actor.policy.set_training_mode(False)
                before={k:v.clone() for k,v in actor.policy.state_dict().items()}
                historical_updates=actor.optimizer_steps
                lock_actor(actor)
                env=G1YawResidualEnv(ledger);obs,info=env.reset(seed=7);sim=env.sim;frame=env.frame
                initials[group]={'qpos':sim._data.qpos.tolist(),'simulator_resets':sim.resets}
                if initials[group]!=initials['B0']:raise RuntimeError('initial_state_mismatch')
                if env.low.resets!=results['B0']['controller_resets_at_first_native']:raise RuntimeError('initial_controller_reset_mismatch')
                ledger.event('initial',**initials[group],controller_resets=env.low.resets,checkpoint_sha256=sha(checkpoint),historical_optimizer_steps=historical_updates)
                done=False;decisions=0
                while not done:
                    action=frozen_action(actor,obs)
                    ledger.event('actor_decision',decision=decisions+1,observation=obs.tolist(),action=action.tolist(),deterministic=True)
                    obs,_,terminated,truncated,info=env.step(action);decisions+=1;done=terminated or truncated
                    if decisions>240 or sim.episode_steps>12000:raise RuntimeError('group_budget')
                if actor.optimizer_steps!=historical_updates or not all(torch.equal(v,actor.policy.state_dict()[k]) for k,v in before.items()):raise RuntimeError('actor_weight_or_update_drift')
                record=metrics(sim,frame);record.update(actor_decisions=decisions,new_optimizer_steps=0,weights_unchanged=True,target_reached=record['forward_displacement_m']>=4.,termination_reason=info['termination_reason']);rows=sim.rows.copy()
            if not rows or rows[0]['controller_resets']!=2 or rows[0]['simulator_resets']!=2 or rows[0]['counter']!=1:raise RuntimeError('native_reset_or_cadence_mismatch')
            record['controller_resets_at_first_native']=rows[0]['controller_resets']
            trajectory=curves(rows,frame);trajectories[group]=trajectory['values']
            summary={k:v for k,v in trajectory.items() if k!='values'}
            results[group]={**record,**summary,'native_steps':len(rows)}
            (root/f'{group}.json').write_text(json.dumps(results[group],indent=2))
            (root/f'{group}-curves.json').write_text(json.dumps(trajectory,indent=2))
            ledger.event('group_completed',group=group,result=results[group])
            sim.close();sim=None;env=None
        if ledger.completed>36000 or time.monotonic()-started>=590:raise RuntimeError('final_budget')
        final={'verdict':classify(results),'interpretation':'single seen case; gates primary; continuous differences descriptive; no generalization',
               'groups':results,'pairs':{f'{a}_vs_{b}':matched_delta(trajectories[a],trajectories[b]) for a,b in (('B0','C0'),('B0','C256'),('C0','C256'))},
               'native_completed':ledger.completed,'native_reserved':ledger.reserved,'wall_s':time.monotonic()-started,'optimizer_updates':0,'readiness_sha256':sha(manifest)}
        (root/'result.json').write_text(json.dumps(final,indent=2));print(json.dumps(final))
    except BaseException as exc:
        physical=isinstance(exc,PhysicalAbort) and str(exc)=='inherited_fall_height_or_tilt'
        if physical and sim is not None and frame is not None:
            results[ledger.stage]=metrics(sim,frame)
            (root/f'{ledger.stage}-physical-failure.json').write_text(json.dumps(results[ledger.stage],indent=2))
        failure={'verdict':classify(results) if physical else 'INCONCLUSIVE','physical_failure_observed':physical,
                 'technical_incomplete':not physical,'groups_observed':results,'stage':ledger.stage,'reason':str(exc),'type':type(exc).__name__,
                 'traceback':traceback.format_exc(),'native_reserved':ledger.reserved,'native_completed':ledger.completed,'no_retry':True}
        (root/'failure.json').write_text(json.dumps(failure,indent=2));raise
    finally:ledger.close()

def main(argv=None,*,verifier=verify,worker_argv=None):
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('manifest');p.add_argument('sha256');p.add_argument('--execute-owner-approved',action='store_true')
    args=p.parse_args(argv)
    if not args.execute_owner_approved:raise SystemExit('OWNER_CONFIRMATION_REQUIRED_BEFORE_PHYSICS')
    # Flag only prevents accidental launch; trusted operator must separately hold the real Owner message.
    started=time.monotonic() # one entry-anchored clock: 595 s cutoff and 600 s total cover the whole lifecycle
    deadline=started+SUPERVISOR_CUTOFF_S;total_deadline=started+SUPERVISOR_TOTAL_S
    try: # synchronous preflight is bounded by the same deadline, not only checked after it returns
        with supervision.lifecycle_deadline(deadline):
            m=verifier(args.manifest,args.sha256) # HEAD/Readiness/source preflight before any run side effect
    except supervision.DeadlineInterrupt:
        raise RuntimeError('supervisor_cutoff_exhausted')
    if time.monotonic()>=deadline:raise RuntimeError('supervisor_cutoff_exhausted') # exhausted preflight leaves no campaign side effect
    root=Path(args.root);root.mkdir(exist_ok=False);(root/'once.claim').write_text('one separately Owner-confirmed T2a campaign; no retry\n')
    remaining=deadline-time.monotonic()
    if remaining<=0:raise RuntimeError('supervisor_cutoff_exhausted')
    command=list(worker_argv) if worker_argv is not None else [sys.executable,str(Path(__file__)),str(root),args.manifest,args.sha256,'--worker-owner-approved']
    result=supervision.supervise(command,root,remaining,run_identity=root,readiness_sha256=args.sha256,
                                 execution_head=m['execution_head'],protocol_sha256=m['protocol_sha256'],manifest=args.manifest,
                                 deadline_s=deadline,total_deadline_s=total_deadline)
    raise SystemExit(0 if result['native_exitcode']==0 and not result['interrupted'] else 1)

def worker(argv=None):
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('manifest');p.add_argument('sha256')
    p.add_argument('--worker-owner-approved',action='store_true');p.add_argument(supervision.FD_FLAG,dest='supervisor_fd',type=int)
    args=p.parse_args(argv)
    if not args.worker_owner_approved:raise SystemExit('worker_flag_required')
    if args.supervisor_fd is None:raise supervision.DelegationRefused('supervisor_delegation_required')
    trust=supervision.entry_trust(Path(__file__).resolve(),sys.argv) # pinned to this real file; CLI/env/JSON cannot override
    delegation=supervision.consume_delegation(args.supervisor_fd,trust,
        execution_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        protocol_sha256=sha(HERE/'protocol.json'))
    execute(Path(args.root),Path(args.manifest),args.sha256,delegation)

if __name__=='__main__':
    if '--worker-owner-approved' in sys.argv:
        try:worker(sys.argv[1:])
        except supervision.DelegationRefused as exc:
            print('WORKER_REFUSED:'+str(exc),file=sys.stderr);raise SystemExit(76)
    else:main()
