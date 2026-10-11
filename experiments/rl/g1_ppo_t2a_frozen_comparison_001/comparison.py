"""T2a pure scoring helpers; no simulator/Torch/policy imports."""
import math
from types import SimpleNamespace

def classify(outcomes):
    names=('B0','C0','C256')
    if any(n not in outcomes for n in names): return 'INCONCLUSIVE'
    if any(outcomes[n].get('technical_invalid',False) for n in names): return 'INCONCLUSIVE'
    keys=('physical_success','task_success','strict_success')
    vectors={n:tuple(bool(outcomes[n][k]) for k in keys) for n in names}
    trained=vectors['C256']
    if any(any(ref[i] and not trained[i] for i in range(3)) for ref in (vectors['B0'],vectors['C0'])):
        return 'REGRESSION'
    if all(all(trained[i]>=ref[i] for i in range(3)) and trained!=ref for ref in (vectors['B0'],vectors['C0'])):
        return 'IMPROVED_SEEN_CASE'
    if len(set(vectors.values()))==1: return 'NO_MEANINGFUL_GAIN'
    return 'INCONCLUSIVE'


def curves(rows, frame):
    values=[]
    for row in rows:
        t=float(row['sim_time']); q=row['qpos']; f,l=frame.project(q[:3])
        heading=frame.heading_error_deg(SimpleNamespace(base_orientation=tuple(q[3:7])))
        det=float(row['deterministic_command'][2]); applied=float(row['applied_command'][2])
        v={'t':t,'forward_m':f,'lateral_m':l,'heading_deg':heading,
           'deterministic_yaw':det,'applied_yaw':applied,'residual_yaw':applied-det}
        if not all(math.isfinite(x) for x in v.values()): raise ValueError('nonfinite_curve')
        values.append(v)
    if not values: raise ValueError('missing_raw_trajectory')
    return {'values':values,'lateral_rms_m':math.sqrt(sum(v['lateral_m']**2 for v in values)/len(values)),
            'heading_rms_deg':math.sqrt(sum(v['heading_deg']**2 for v in values)/len(values)),
            'max_abs_lateral_m':max(abs(v['lateral_m']) for v in values),
            'max_abs_heading_deg':max(abs(v['heading_deg']) for v in values)}


def matched_delta(a,b):
    # Native steps start from the same reset. Compare common clock only; never extrapolate a shorter run.
    common=min(len(a),len(b)); pairs=list(zip(a[:common],b[:common]))
    if not pairs or any(x['t']!=y['t'] for x,y in pairs): raise ValueError('unmatched_native_clock')
    return {'common_native_samples':common,'common_end_s':pairs[-1][0]['t'],
            'lateral_delta_rms_m':math.sqrt(sum((y['lateral_m']-x['lateral_m'])**2 for x,y in pairs)/common),
            'heading_delta_rms_deg':math.sqrt(sum((y['heading_deg']-x['heading_deg'])**2 for x,y in pairs)/common),
            'residual_delta_rms_radps':math.sqrt(sum((y['residual_yaw']-x['residual_yaw'])**2 for x,y in pairs)/common)}


def lock_actor(actor):
    def forbidden(*a,**kw):raise RuntimeError('optimizer_or_training_forbidden_in_T2a')
    actor.policy.optimizer.step=forbidden;actor.learn=forbidden;actor.train=forbidden


def frozen_action(actor,observation):
    action,_=actor.predict(observation,deterministic=True)
    if len(action)!=1 or not math.isfinite(float(action[0])) or abs(float(action[0]))>1:
        raise ValueError('invalid_frozen_actor_action')
    return action
