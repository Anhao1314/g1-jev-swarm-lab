"""Offline-qualified component, NOT an acquisition entry or authority grant.

No model or simulation imports. Attach only through a separately frozen collector.
The delegate remains the existing fixed-alpha correction; original skill bodies,
termination, reset and evaluator are unchanged.
"""
import json
import math
from pathlib import Path

PROTOCOL = json.loads(Path(__file__).with_name('protocol.json').read_text())

def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('finite numeric value required')
    return float(value)

def speed(progress, arm):
    progress = finite(progress)
    if arm not in PROTOCOL['arms_in_order']:
        raise ValueError('unknown frozen arm')
    cfg = PROTOCOL['schedule']
    if arm == 'constant':
        return cfg['baseline_mps']
    fraction = max(0., min(1., (cfg['end_progress_m']-progress)/
                           (cfg['end_progress_m']-cfg['begin_progress_m'])))
    return cfg['terminal_mps'] + (cfg['baseline_mps']-cfg['terminal_mps'])*fraction

class ScheduledCorrection:
    """Wrapper at the existing correction callback, not a low-level controller.

    emit is required and synchronous. An observer failure propagates before the
    original controller is called; a collector must preserve it as technical.
    Uses the original local frame, deliberately not delegate.selected_frame().
    """
    def __init__(self, runner, delegate, arm, emit):
        if arm not in PROTOCOL['arms_in_order'] or not callable(emit):
            raise ValueError('invalid arm or observer')
        if getattr(delegate, 'alpha', None) != PROTOCOL['case']['alpha']:
            raise ValueError('requires existing fixed alpha0.25 delegate')
        self.runner, self.delegate, self.arm, self.emit = runner, delegate, arm, emit

    def compute(self, state, frame, nominal_command, *, sim_time_s):
        r = self.runner
        if r.index != 1 or r.skill != 'walk_forward' or frame is not r.frame:
            raise ValueError('not original first-Walk frame')
        if (r.parameters.get('target_distance_m') != 8. or
                r.parameters.get('speed_mps') != .5 or
                r.parameters.get('stop_at_distance_m',8.) != 8.):
            raise ValueError('changed Walk semantics')
        if len(nominal_command) != 3 or tuple(finite(x) for x in nominal_command) != (.5,0.,0.):
            raise ValueError('unexpected nominal command')
        progress = finite(frame.project(state.base_position)[0])
        planned = speed(progress,self.arm)
        command = nominal_command if self.arm == 'constant' else nominal_command.copy()
        if self.arm != 'constant':
            command[0] = planned
        self.emit({'node_index': r.index, 'time_s': finite(sim_time_s),
                   'original_progress_m': progress, 'original_nominal': list(nominal_command),
                   'scheduled_nominal': list(command), 'arm': self.arm})
        return self.delegate.compute(state,frame,command,sim_time_s=sim_time_s)

    def __getattr__(self,name):
        return getattr(self.delegate,name)

def window_mean_speed(samples, end_time):
    """Exact time-weighted integral of piecewise-linear planar SPEED samples.

    samples: ordered (time, vx, vy), bracket entire final window; no samples
    after Walk end accepted. Does not interpolate vector direction before norm.
    This is an estimator, not a physical guarantee between native samples.
    """
    end = finite(end_time)
    start = end-PROTOCOL['measurement']['speed_window_s']
    rows = [(finite(t),math.hypot(finite(x),finite(y))) for t,x,y in samples]
    if (len(rows)<2 or rows[0][0]>start or rows[-1][0]!=end or
            any(b[0]<=a[0] for a,b in zip(rows,rows[1:]))):
        raise ValueError('window coverage/order or exact endpoint missing')
    area=0.
    for (ta,va),(tb,vb) in zip(rows,rows[1:]):
        left,right=max(start,ta),min(end,tb)
        if right<=left:
            continue
        if tb-ta > (PROTOCOL['measurement']['max_native_gap_s']+
                    PROTOCOL['measurement']['timestamp_tolerance_s']):
            raise ValueError('missing native samples in speed window')
        vl=va+(vb-va)*(left-ta)/(tb-ta)
        vr=va+(vb-va)*(right-ta)/(tb-ta)
        area+=(vl+vr)*.5*(right-left)
    return area/(end-start)

def compare(control, treatment):
    """Consume independently audited metrics, never replace raw evidence audit.

    Required gate values must be actual booleans. Technical/missing evidence
    never hides an already observed physical or strict failure.
    """
    cfg=PROTOCOL['comparison']; eps=cfg['arithmetic_tolerance']
    failure={'physical_failure_observed':False,'strict_failure_observed':False,
             'technical_or_missing':False}
    keys=('exit_speed','mean_speed','walk_world_norm','turn_world_norm',
          'turn_x','turn_y','turn_heading','duration')
    validated=[]
    for row in (control,treatment):
        failure['physical_failure_observed'] |= row.get('physical') is False
        failure['strict_failure_observed'] |= row.get('strict') is False
        if any(type(row.get(k)) is not bool for k in ('complete','physical','strict','technical')):
            failure['technical_or_missing']=True
        if row.get('complete') is not True or row.get('technical') is not False:
            failure['technical_or_missing']=True
        try:
            values={k:finite(row[k]) for k in keys}
            if any(values[k]<0 for k in ('exit_speed','mean_speed','walk_world_norm','turn_world_norm','duration')):
                raise ValueError('negative magnitude')
            validated.append(values)
        except (KeyError,TypeError,ValueError):
            failure['technical_or_missing']=True
    if failure['technical_or_missing']:
        return {'verdict':'INCONCLUSIVE',**failure}
    b,t=validated
    if failure['physical_failure_observed'] or failure['strict_failure_observed']:
        verdict='TRADEOFF_NO_JOINT_SUPPORT'
    elif b['mean_speed']-t['mean_speed']+eps<cfg['minimum_mean_speed_reduction_mps']:
        verdict='MANIPULATION_NOT_ESTABLISHED'
    elif b['turn_world_norm']-t['turn_world_norm']+eps<cfg['minimum_turn_world_error_improvement_m']:
        verdict='SPEED_CHANGED_NO_POSITION_GAIN'
    elif (t['exit_speed']>b['exit_speed']+eps or t['walk_world_norm']>b['walk_world_norm']+eps or
          t['duration']-b['duration']>cfg['maximum_added_prefix_sim_time_s']+eps or
          any(abs(t[k])>abs(b[k])+eps for k in ('turn_x','turn_y','turn_heading'))):
        verdict='TRADEOFF_NO_JOINT_SUPPORT'
    else:
        verdict='BOUNDED_HANDOFF_MECHANISM_SUPPORT'
    return {'verdict':verdict,**failure}
