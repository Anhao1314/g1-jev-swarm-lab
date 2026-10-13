"""Read sealed inputs; evaluate the rule on historical states, NOT trajectories.
No model imports, counterfactual dynamics, or simulator execution.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from handoff import speed

HERE=Path(__file__).resolve().parent

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--raw-root',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    refs=json.loads((HERE/'inputs.json').read_text())
    for item in refs['raw']:
        path=args.raw_root/item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],str(path)
    for item in refs['source']:
        path=HERE.parents[2]/item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],str(path)
    result=json.loads((args.raw_root/'fixed/result.json').read_text())
    nodes=result['nodes'][:3]
    assert [n['skill'] for n in nodes]==['stand','walk_forward','turn']
    assert all(n['strict_success'] and n['physical_success'] for n in nodes)
    walk,turn=nodes[1:]
    origin=walk['start_state']['base_position']
    w,x,y,z=walk['start_state']['base_orientation']
    yaw=math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
    rows=[json.loads(line) for line in (args.raw_root/'fixed/trace.jsonl').read_text().splitlines()]
    schedule=[]
    for r in rows:
        if r['node_index']!=1: continue
        s=r['state_before_command']; p=s['base_position']
        progress=math.cos(yaw)*(p[0]-origin[0])+math.sin(yaw)*(p[1]-origin[1])
        vx=speed(progress,'terminal_schedule')
        if progress<=7: assert vx==r['applied_command'][0]==.5
        schedule.append({'historical_time_s':s['simulation_time'],'progress_m':progress,
                         'historical_applied_vx_mps':r['applied_command'][0],
                         'rule_on_historical_state_vx_mps':vx})
    poses=np.load(args.raw_root/'fixed/poses.npz',allow_pickle=False)
    end=walk['end_state']; t=end['simulation_time']
    # Retained 20Hz samples for context only. New protocol requires native samples.
    samples=[(float(ti),float(v[0]),float(v[1])) for ti,v,i in zip(poses['time_s'],poses['qvel'],poses['node_index']) if i==1 and ti<t]
    samples.append((t,*end['linear_velocity'][:2]))
    out={'status':'OFFLINE_RULE_AND_RETAINED_INPUT_CHECK_PASS',
         'counterfactual_physical_outcome':'NOT_COMPUTED',
         'historical_prefix_nodes':[{k:n[k] for k in ('skill','parameters','strict_success','physical_success','start_state','end_state','duration_s')} for n in nodes],
         'baseline_context':{'exit_speed_mps':math.hypot(*end['linear_velocity'][:2]),
           'last_half_second_native_mean_speed':'NOT_AVAILABLE_FROM_20HZ_HISTORY',
           'historical_pose_max_gap_s':max(b[0]-a[0] for a,b in zip(samples,samples[1:])),
           'mean_speed_limitation':'No interpolation of sparse retained poses into the required native measurement. Both new arms require complete native window evidence.',
           'walk_waypoint_norm_m':math.hypot(end['base_position'][0]-8,end['base_position'][1]),
           'turn_waypoint_norm_m':math.hypot(turn['end_state']['base_position'][0]-8,turn['end_state']['base_position'][1]),
           'prefix_sim_time_s':turn['end_state']['simulation_time']},
         'hypothetical_commands_on_retained_states':schedule,
         'physics_steps':0,'policy_inferences':0,'training_steps':0}
    with args.output.open('x',encoding='utf-8') as f: json.dump(out,f,indent=2,allow_nan=False)
    print(json.dumps({'status':out['status'],'sampled_walk_commands':len(schedule),'baseline_context':out['baseline_context']}))

if __name__=='__main__': main()
