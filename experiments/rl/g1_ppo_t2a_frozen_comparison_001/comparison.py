"""T2a pure scoring helpers; no simulator/Torch/policy imports."""
import math
from collections.abc import Mapping
from types import SimpleNamespace

GROUPS=('B0','C0','C256')
GATES=('physical_success','task_success','strict_success')

def _outcome_vector(outcome):
    # Fail closed: only a mapping carrying three genuine booleans plus an absent-or-boolean
    # technical_invalid flag is trusted gate evidence; strings/numbers/None/NaN/objects are not.
    if not isinstance(outcome,Mapping): return None
    flag=outcome.get('technical_invalid',False)
    if type(flag) is not bool: return None
    if any(type(outcome.get(k)) is not bool for k in GATES): return None
    return tuple(outcome[k] for k in GATES),flag

def _usable_vectors(outcomes):
    if not isinstance(outcomes,Mapping): return {}
    vectors={}
    for n in GROUPS:
        parsed=_outcome_vector(outcomes.get(n))
        if parsed is not None and not parsed[1]: vectors[n]=parsed[0]
    return vectors

def _partial_physical(outcome):
    # A technically interrupted run may keep a genuine boolean physical outcome while its
    # nominal/strict gates are absent; that requires an explicitly recorded boolean True
    # technical flag, and malformed flags or non-boolean physical values are never witness.
    if not isinstance(outcome,Mapping): return None
    if outcome.get('technical_invalid',False) is not True: return None
    value=outcome.get('physical_success')
    return value if type(value) is bool else None

def classify(outcomes):
    vectors=_usable_vectors(outcomes)
    if len(vectors)==3:
        trained=vectors['C256']
        if any(any(ref[i] and not trained[i] for i in range(3)) for ref in (vectors['B0'],vectors['C0'])):
            return 'REGRESSION'
        if all(all(trained[i]>=ref[i] for i in range(3)) and trained!=ref for ref in (vectors['B0'],vectors['C0'])):
            return 'IMPROVED_SEEN_CASE'
        if len(set(vectors.values()))==1: return 'NO_MEANINGFUL_GAIN'
        return 'INCONCLUSIVE'
    # An established physical failure of the trained group is retained after a technical
    # interruption dropped its nominal/strict gates: the interruption must not erase an
    # observed fall. Both references must still record a genuine boolean physical pass, and
    # partial evidence can only ever yield REGRESSION, never an improvement verdict.
    def physical(name):
        parsed=_outcome_vector(outcomes.get(name)) if isinstance(outcomes,Mapping) else None
        if parsed is not None: return parsed[0][0]
        return _partial_physical(outcomes.get(name) if isinstance(outcomes,Mapping) else None)
    trained=physical('C256'); refs=(physical('B0'),physical('C0'))
    if trained is False and all(r is True for r in refs): return 'REGRESSION'
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
