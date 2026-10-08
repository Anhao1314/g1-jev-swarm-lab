"""Read saved M2.4 bytes; compute planar kinematic identities, never execute a policy."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = '8d80b7a5c24020a4f4664beb6158aad299bfa7f1'
STATES = ['seen_reference_walk6', 'transition_turn45_walk6', 'push60_walk6']
LABELS = ['Seen Walk6', 'Turn45 -> Walk6', '+Y 60N push']


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def yaw(q):
    w, x, y, z = np.asarray(q).T
    return np.arctan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z))


def wrapped(a):
    return np.arctan2(np.sin(a), np.cos(a))


def run(raw_root, out):
    out.mkdir(parents=True, exist_ok=True)
    seal_path = ROOT / 'experiments/m2/cross_state_reliability_analysis_001/raw_evidence_manifest.json'
    seal = read(seal_path)
    # Check all raw inputs, including arms unused for this descriptive comparison.
    for name, expected in seal['files'].items():
        p = raw_root / name
        assert p.stat().st_size == expected['bytes'] and sha(p) == expected['sha256'], name
    source_names = [
        'experiments/m2/cross_state_reliability_001/acquire.py',
        'experiments/m2/cross_state_reliability_001/protocol.json',
        'experiments/m2/cross_state_reliability_001/source_manifest.json',
        'experiments/m2/cross_state_reliability_analysis_001/audit.json',
        'experiments/m2/cross_state_reliability_analysis_001/raw_evidence_manifest.json',
        'experiments/m2/cross_state_reliability_readiness_001/readiness_manifest.json',
        'src/g1swarm/skills/basic.py', 'src/g1swarm/mission/live_session.py',
        'src/g1swarm/control/g1_locomotion.py', 'src/g1swarm/segmentation/mission.py',
        'src/g1swarm/simulation/g1_simulation.py',
        'src/g1swarm/state/robot_state.py',
        'src/g1swarm/characterization/perturbations.py',
        'configs/robot/g1_locomotion_12dof.yaml',
    ]
    sources = {}
    for name in source_names:
        blob = subprocess.check_output(['git', 'show', BASE + ':' + name], cwd=ROOT)
        # Source line endings can differ on Windows. Compare content and bind both bytes.
        data = (ROOT/name).read_bytes()
        assert data.replace(b'\r\n', b'\n') == blob.replace(b'\r\n', b'\n'), name
        sources[name] = {'git_blob_sha256': hashlib.sha256(blob).hexdigest(), 'local_sha256': sha(ROOT/name)}
    all_raw = raw_root / 'experiments/m2/cross_state_reliability_001/artifacts'
    result = {'scientific_verdict_unchanged': 'INCONCLUSIVE', 'role': 'DESCRIPTIVE_SAVED_TRACE_MECHANISM_ANALYSIS',
              'base_commit': BASE, 'source_hashes': sources, 'raw_manifest_sha256': sha(seal_path),
              'all_raw_files_verified': len(seal['files']), 'analysis_code_sha256': sha(Path(__file__)),
              'physics_calls': 0, 'policy_calls': 0, 'provider_calls': 0,
              'states': {}, 'method': {
                  'frame': 'Each parent Walk own actual entry position/yaw, exactly as frozen evaluator',
                  'identity': 'route_vy = body_forward_velocity*sin(yaw-yaw0) + body_lateral_velocity*cos(yaw-yaw0)',
                  'integration': 'Native post-step velocity right Riemann sum over actual native dt; report position closure residual',
                  'body_frame': 'Planar yaw-aligned frame, not full 3D body/foot contact frame',
                  'causality': 'Kinematic accounting, not independently manipulable causal components',
                  'snapshots': '0, 1, 1.2, 2, 4, 6, 8, 10 s and own endpoint; no time search',
                  'shared_comparison': 'Both common elapsed time and fixed progress 2/4/6m; no post-Walk samples',
              }}
    series, native, entries = {}, {}, {}
    for state in STATES:
        d = all_raw / (state + '--authorized_new_mission')
        rows = read(d / 'predecision_native_trace.json')
        robot_trace = read(d / 'predecision_trace.json')
        parent = read(d / 'parent_result.json')
        node = next(x for x in parent['nodes'] if x['skill'] == 'walk_forward')
        dispatch = next(x for x in read(d/'node_dispatches.json') if x['skill'] == 'walk_forward' and x['phase'] == 'parent')
        start, count = dispatch['simulation_steps'], node['metrics']['simulation_steps']
        if start:
            entry = rows[start-1]
        else:
            with np.load(d/'poses.npz') as poses:
                assert poses['time_s'][0] == 0
                entry = {k: poses[k][0].tolist() for k in ('qpos', 'qvel', 'ctrl')}
                entry['time_s'] = 0.0
        entries[state] = entry
        selected = rows[start:start+count]
        assert len(selected) == count
        assert all(x['phase'] == 'parent' and x['active_skill'] == 'walk_forward' for x in robot_trace[start:start+count])
        native[state] = selected
        samples = [entry] + selected
        t = np.array([r['time_s'] for r in samples]) - entry['time_s']
        q = np.array([r['qpos'] for r in samples]); v = np.array([r['qvel'] for r in samples])
        psi = yaw(q[:, 3:7]); psi0 = psi[0]; delta = wrapped(psi-psi0)
        dx = q[:, :2]-q[0, :2]; c0, s0 = np.cos(psi0), np.sin(psi0)
        progress = c0*dx[:,0]+s0*dx[:,1]; lateral = -s0*dx[:,0]+c0*dx[:,1]
        route_vx = c0*v[:,0]+s0*v[:,1]; route_vy = -s0*v[:,0]+c0*v[:,1]
        body_vx = np.cos(psi)*v[:,0]+np.sin(psi)*v[:,1]
        body_vy = -np.sin(psi)*v[:,0]+np.cos(psi)*v[:,1]
        heading_term = body_vx*np.sin(delta); lateral_term = body_vy*np.cos(delta)
        assert np.max(np.abs(route_vy-heading_term-lateral_term)) < 1e-12
        dt = np.diff(t)
        heading_integral = np.r_[0., np.cumsum(heading_term[1:]*dt)]
        lateral_integral = np.r_[0., np.cumsum(lateral_term[1:]*dt)]
        closure = lateral-heading_integral-lateral_integral
        assert abs(lateral[-1]-node['metrics']['lateral_drift_m']) < 1e-12
        assert abs(np.degrees(delta[-1])-node['metrics']['heading_error_deg']) < 1e-10
        assert np.max(np.abs(dt-0.002)) < 1e-12
        columns = {'time_from_walk_s': t, 'progress_m': progress, 'lateral_m': lateral,
                   'heading_error_deg': np.degrees(delta), 'route_vx_mps': route_vx, 'route_vy_mps': route_vy,
                   'body_forward_mps': body_vx, 'body_lateral_mps': body_vy,
                   'heading_projection_rate_mps': heading_term, 'body_lateral_projection_rate_mps': lateral_term,
                   'heading_projection_integral_m': heading_integral, 'body_lateral_integral_m': lateral_integral,
                   'position_integration_residual_m': closure}
        series[state] = columns
        with (out/(state+'.csv')).open('w', encoding='utf8', newline='') as f:
            writer = csv.writer(f); writer.writerow(columns); writer.writerows(zip(*columns.values()))
        def at(idx):
            return {k: float(a[idx]) for k,a in columns.items()}
        snapshots = {str(x): at(int(round(x/0.002))) for x in (0,1,1.2,2,4,6,8,10) if x <= t[-1]}
        snapshots['endpoint'] = at(-1)
        first_ctrl = selected[0]['controller']
        result['states'][state] = {
            'walk_start_native_index': start, 'walk_steps': count, 'walk_entry_global_time_s': entry['time_s'],
            'walk_duration_s': float(t[-1]), 'strict_evaluation': node['feedback_decision']['evaluation'],
            'correction_rms': node['metrics']['correction_rms'],
            'entry': {'position_m': q[0,:3].tolist(), 'quaternion_wxyz': q[0,3:7].tolist(), 'yaw_deg': float(np.degrees(psi0)),
                      'route_vx_mps': float(route_vx[0]), 'route_vy_mps': float(route_vy[0]),
                      'raw_angular_velocity_xyz': v[0,3:6].tolist(),
                      'joint_positions': q[0,7:].tolist(), 'joint_velocities': v[0,6:].tolist(),
                      'prior_ctrl': entry['ctrl'],
                      'prior_controller': entry.get('controller', 'NOT_RECORDED_AT_T0'),
                      'first_poststep_controller': first_ctrl,
                      'first_poststep_ctrl': selected[0]['ctrl'],
                      'zero_action_default_target_counter1_after_reset': first_ctrl['_counter']==1 and first_ctrl['_action']==[0.]*12},
            'snapshots': snapshots, 'max_abs_integration_closure_m': float(np.max(np.abs(closure))),
            'maximum_absolute_lateral_m': float(np.max(np.abs(lateral))),
            'endpoint_heading_projection_m': float(heading_integral[-1]),
            'endpoint_body_lateral_projection_m': float(lateral_integral[-1]),
            'paired_predecision_exact': all((d/name).read_bytes()==(all_raw/(state+'--authorization_refusals')/name).read_bytes() for name in ['predecision_trace.json','predecision_native_trace.json']),
            'raw_paths': [p.relative_to(raw_root).as_posix() for p in [d/'predecision_native_trace.json',d/'predecision_trace.json',d/'parent_result.json',d/'node_dispatches.json',d/'poses.npz']],
        }
    a,b = native[STATES[0]], native[STATES[2]]
    common_prefix=0
    for x,y in zip(a,b):
        if x != y: break
        common_prefix += 1
    force_indices=[i for i,r in enumerate(b) if any(x for body in r['xfrc_applied'] for x in body)]
    assert common_prefix==500 and force_indices==list(range(500,600))
    assert entries[STATES[0]] == entries[STATES[2]]
    result['push_comparability']={'initial_saved_state_exact':True,'exact_native_prefix_rows':common_prefix,
        'prefix_end_poststep_time_s':a[common_prefix-1]['time_s'], 'first_differing_poststep_time_s':b[common_prefix]['time_s'],
        'compared_fields':['time_s','qpos','qvel','ctrl','controller','xfrc_applied'],
        'force_native_intervals':100, 'nominal_window_s':[1.,1.2], 'first_last_force_poststep_times_s':[b[500]['time_s'],b[599]['time_s']],
        'unmeasured_prefix_fields':['contact solver internal state','hidden policy memory bytes','random generator state']}
    comparisons={}
    for other in STATES[1:]:
        x,y=series[STATES[0]],series[other]
        end=min(len(x['lateral_m']),len(y['lateral_m']))-1
        common={k:float(y[k][end]-x[k][end]) for k in ('lateral_m','heading_error_deg','heading_projection_integral_m','body_lateral_integral_m')}
        progress_matches={}
        for distance in (2.,4.,6.):
            # First passage, not outcome-selected time; the walks can briefly move backward initially.
            ix=int(np.flatnonzero(x['progress_m']>=distance)[0]); iy=int(np.flatnonzero(y['progress_m']>=distance)[0])
            progress_matches[str(distance)]={'seen_time_s':float(x['time_from_walk_s'][ix]),'other_time_s':float(y['time_from_walk_s'][iy]),
                'seen_progress_m':float(x['progress_m'][ix]),'other_progress_m':float(y['progress_m'][iy]),
                'lateral_difference_m':float(y['lateral_m'][iy]-x['lateral_m'][ix]),
                'heading_projection_difference_m':float(y['heading_projection_integral_m'][iy]-x['heading_projection_integral_m'][ix]),
                'body_lateral_projection_difference_m':float(y['body_lateral_integral_m'][iy]-x['body_lateral_integral_m'][ix])}
        comparisons[other]={'common_elapsed_time_s':float(x['time_from_walk_s'][end]),'common_elapsed_difference':common,'first_progress_crossings':progress_matches}
    result['comparisons_to_seen']=comparisons
    # Derive the first post-reset PD torques from recorded pre-step joint state only.
    # No controller or policy module is imported or evaluated.
    import yaml
    config=yaml.safe_load((ROOT/'configs/robot/g1_locomotion_12dof.yaml').read_text())['controller']
    for state in STATES:
        assert native[state][0]['controller']['_target'] == config['default_angles']
        e=entries[state]; pd=(np.array(config['default_angles'])-np.array(e['qpos'][7:]))*config['kp']-np.array(e['qvel'][6:])*config['kd']
        result['states'][state]['first_reset_pd_reconstruction_max_error']=float(np.max(np.abs(pd-np.array(native[state][0]['ctrl']))))
        assert result['states'][state]['first_reset_pd_reconstruction_max_error']<1e-12
    result['runtime_modules_imported']=[m for m in sys.modules if m=='mujoco' or m=='torch' or m.startswith('g1swarm')]
    assert not result['runtime_modules_imported']
    plot(series,result,out)
    halt_plot(all_raw,out)
    result['derived_files_sha256']={p.name:sha(p) for p in sorted(out.iterdir()) if p.suffix in ('.csv','.png','.svg')}
    (out/'metrics.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'status':'PASS_SAVED_TRACE_ACCOUNTING','raw_files_verified':178,'prefix_rows':common_prefix,
        'endpoint_terms':{s:{k:result['states'][s][k] for k in ('endpoint_heading_projection_m','endpoint_body_lateral_projection_m','max_abs_integration_closure_m')} for s in STATES}}))


def plot(series,result,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.grid':True,'grid.alpha':0.25})
    colors=['#2563eb','#dc2626','#059669']
    fig,axes=plt.subplots(3,1,figsize=(11,9),sharex=True)
    for s,label,color in zip(STATES,LABELS,colors):
        d=series[s]; t=d['time_from_walk_s']
        axes[0].plot(t,d['lateral_m'],label=label,color=color)
        axes[1].plot(t,d['heading_error_deg'],color=color)
        axes[2].plot(t,d['body_lateral_mps'],color=color,alpha=.7)
    lim=result['states'][STATES[0]]['strict_evaluation']['limits']['lateral_drift_max_m']
    for sign in (-1,1): axes[0].axhline(sign*lim,color='gray',ls='--')
    for ax in axes: ax.axvspan(1.,1.2,color='#059669',alpha=.12)
    axes[0].legend(); axes[0].set_ylabel('Walk-frame lateral (m)');axes[1].set_ylabel('Heading from entry (deg)');axes[2].set_ylabel('Yaw-frame lateral speed (m/s)');axes[2].set_xlabel('Time since own Walk entry (s)')
    fig.suptitle('Saved parent Walk traces only — strict limits apply at endpoint\nGreen band: fixed push window; Turn entry frame follows actual heading')
    fig.tight_layout();fig.savefig(out/'walk_dynamics.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(15,4.7),sharey=True)
    for ax,s,label in zip(axes,STATES,LABELS):
        d=series[s];t=d['time_from_walk_s'];ax.plot(t,d['lateral_m'],color='black',label='Measured lateral')
        ax.plot(t,d['heading_projection_integral_m'],label='Forward motion x heading')
        ax.plot(t,d['body_lateral_integral_m'],label='Body lateral projection')
        ax.plot(t,d['heading_projection_integral_m']+d['body_lateral_integral_m'],ls='--',color='gray',label='Sum')
        ax.set_title(label);ax.set_xlabel('Walk elapsed (s)')
    axes[0].set_ylabel('Cumulative lateral displacement (m)');axes[2].legend(fontsize=8)
    fig.suptitle('Kinematic accounting: e_dot = v_forward sin(delta yaw) + v_lateral cos(delta yaw)\nContributions are coupled observations, not independent causal effects')
    fig.tight_layout();fig.savefig(out/'lateral_decomposition.png',dpi=160);plt.close(fig)
    x,y=series[STATES[0]],series[STATES[2]]; n=min(len(x['lateral_m']),len(y['lateral_m']));t=x['time_from_walk_s'][:n]
    fig,axes=plt.subplots(2,1,figsize=(11,7),sharex=True)
    for k,label in [('lateral_m','Total lateral difference'),('heading_projection_integral_m','Heading projection difference'),('body_lateral_integral_m','Body lateral projection difference')]:
        axes[0].plot(t,y[k][:n]-x[k][:n],label=label)
    axes[1].plot(t,x['lateral_m'][:n],label='Seen');axes[1].plot(t,y['lateral_m'][:n],label='Push')
    for ax in axes: ax.axvspan(1.,1.2,color='#059669',alpha=.15);ax.axhline(0,color='gray',lw=.7);ax.legend()
    axes[0].set_ylabel('Push minus seen (m)');axes[1].set_ylabel('Own Walk lateral (m)');axes[1].set_xlabel('Common elapsed time, truncated at earlier Walk endpoint (s)')
    fig.suptitle('Push comparison: exact observed prefix through 1.000s\nNo Turn/Stop or new-mission samples enter this comparison')
    fig.tight_layout();fig.savefig(out/'push_comparison.png',dpi=160);plt.close(fig)


def halt_plot(raw,out):
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,2,figsize=(12,7))
    for col,state in enumerate(STATES[:2]):
        h=read(raw/(state+'--authorized_new_mission')/'parent_result.json')['physical_halt']
        trace=h['trace']; t=np.array([r['time_s'] for r in trace])-trace[0]['time_s']
        speeds=np.array([r['speed_mps'] for r in trace]); dt=t[1]-t[0]
        window=round(h['skill_metrics']['window_s']/dt)
        # StopSkill excludes trace[0] (the pre-step monitor snapshot).
        means=np.array([sum(speeds[i-window+1:i+1])/window for i in range(window,len(speeds))])
        threshold=h['skill_metrics']['speed_threshold_mps']
        assert np.flatnonzero(means<=threshold).tolist()==[len(means)-1]
        axes[0,col].plot(t,speeds,label='Instantaneous planar speed')
        axes[0,col].plot(t[window:],means,lw=2,label='Full 500-sample mean')
        axes[0,col].axhline(threshold,color='gray',ls='--');axes[0,col].axvline(t[-1],color='red',ls=':')
        axes[0,col].set_title(LABELS[col]+' failure Halt only');axes[0,col].set_ylabel('Speed (m/s)');axes[0,col].legend(fontsize=8)
        axes[1,col].plot(t[window:],means-threshold,marker='.',ms=2)
        axes[1,col].axhline(0,color='gray',ls='--');axes[1,col].set_xlim(t[-1]-.03,t[-1]+.002)
        end=means[-1]-threshold; previous=means[-2]-threshold
        axes[1,col].set_ylim(end-.0002,max(previous*4,.001));axes[1,col].set_ylabel('Mean minus threshold (m/s)');axes[1,col].set_xlabel('Elapsed Halt time (s)')
    fig.suptitle('StopSkill ends at first complete sliding mean <= 0.1 m/s\nNo post-qualification hold samples; new-mission samples excluded')
    fig.tight_layout();fig.savefig(out/'halt_first_crossing.png',dpi=160);plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw-root',required=True,type=Path)
    p.add_argument('--output',type=Path,default=HERE/'derived')
    args=p.parse_args();run(args.raw_root.resolve(),args.output.resolve())
