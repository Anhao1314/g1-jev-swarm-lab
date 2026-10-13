"""Lazy physical collector: only invoked after real entry/source/Owner gates.

Retains the exact historical skills, WindowController and zero-action callback.
The only control intervention is the frozen ScheduledCorrection.
"""
import importlib.util
import json
import math
import random
import time
import traceback
from entry import ROOT, DESIGN, read, write, canonical
from native import NativeLedger, physical_flags

class ObservedPhysicalStop(RuntimeError): pass

def execute(arm,destination,deadline):
    import numpy as np
    import torch
    import mujoco
    from g1swarm.simulation import g1_simulation as simulation
    from g1swarm.control.g1_locomotion import G1LocomotionController
    from g1swarm.tradeoff_isolation.experiment import FixedAlphaCorrectionPolicy
    from handoff import ScheduledCorrection
    spec=importlib.util.spec_from_file_location('handoff_retained',ROOT/'experiments/phase3b/decision_benchmark_acquisition_001/study.py')
    hist=importlib.util.module_from_spec(spec); spec.loader.exec_module(hist)
    case=hist.derive_case(read(ROOT/'experiments/phase3a/residual_yaw_component_001/case.json'),
                         {'case_id':'phase3b0a-stand5-16m','stand_duration_s':5.})
    case['nodes']=case['nodes'][:3]
    torch.set_num_threads(1); torch.use_deterministic_algorithms(True)
    random.seed(0); np.random.seed(0); torch.manual_seed(0)
    ledger=NativeLedger(destination/'native.jsonl',deadline)
    schedules=(destination/'schedule.jsonl').open('x',encoding='utf-8',buffering=1)
    errors=[]; archive_errors=[]; boundaries=[]; resets=[]; controller_resets=[]
    observed={'fallen':False,'nonfinite':False}; runner=None; result=None
    last_command=[0.,0.,0.]; triggered=False; stop_reason=None
    original_native=mujoco.mj_step; original_step=simulation.G1Simulation.step
    original_reset=simulation.G1Simulation.reset; original_set=simulation.G1Simulation.set_base_state
    original_compute=G1LocomotionController.compute_torques
    original_ctrl_reset=G1LocomotionController.reset
    original_action=hist.YAW.profile_action

    def check():
        if ledger.failed: raise ObservedPhysicalStop('OBSERVED_PHYSICAL_FAILURE_NO_FURTHER_STEPS')
        ledger.check()
    def snapshot(data=None):
        r=runner; d=data if data is not None else r.sim._data
        return {'node':r.index,'time_s':float(d.time),'qpos':d.qpos.tolist(),'qvel':d.qvel.tolist(),
                'ctrl':d.ctrl.tolist(),'command':list(last_command),'counter':r.base._counter,
                'action':r.base._action.tolist(),'target':r.base._target.tolist(),'resets':r.resets}
    def error(stage,exc):
        errors.append({'stage':stage,'type':type(exc).__name__,'message':str(exc),
                       'native_attempts':ledger.attempts,'completed':ledger.completed})
    def native(model,data,*args,**kwargs):
        if args or kwargs or runner is None or not hasattr(runner,'base'):
            raise RuntimeError('UNDECLARED_NATIVE_INVOCATION')
        check()
        ledger.before(snapshot(data))
        try:
            value=original_native(model,data)
        except BaseException:
            # Completion is unknown, but an already visible physical violation
            # must survive the technical exception on an independent axis.
            state=snapshot(data)
            flags=physical_flags(state['qpos'],state['qvel'],state['ctrl'])
            observed['fallen'] |= flags['fallen']; observed['nonfinite'] |= flags['nonfinite']
            with (destination/'native_exception_state.json').open('x',encoding='utf-8') as f:
                json.dump(state,f,allow_nan=True)
            raise
        flags=physical_flags(data.qpos.tolist(),data.qvel.tolist(),data.ctrl.tolist())
        observed['fallen'] |= flags['fallen']; observed['nonfinite'] |= flags['nonfinite']
        ledger.failed=any(observed.values())
        ledger.after(snapshot(data))
        return value
    def step(sim,control=None):
        check()
        try: return original_step(sim,control)
        except BaseException as exc:
            error('simulation_step',exc); raise
    def compute(ctrl,**kwargs):
        nonlocal last_command
        check(); last_command=np.asarray(kwargs['command']).tolist()
        try: return original_compute(ctrl,**kwargs)
        except BaseException as exc:
            error('controller_compute',exc); raise
    def reset(sim,**kwargs):
        if ledger.attempts or resets: raise RuntimeError('UNEXPECTED_SIMULATOR_RESET')
        resets.append('constructor_reset'); return original_reset(sim,**kwargs)
    def set_base(sim,**kwargs):
        if ledger.attempts or 'initial_base' in resets: raise RuntimeError('UNEXPECTED_BASE_STATE_INJECTION')
        resets.append('initial_base'); return original_set(sim,**kwargs)
    def ctrl_reset(ctrl):
        record={'counter_before':ctrl._counter,'step':ledger.completed,
                'node':getattr(runner,'index',-1)}
        value=original_ctrl_reset(ctrl)
        record['counter_after']=ctrl._counter
        if runner is not None and hasattr(runner,'base'):
            # The WindowController increments its reset count after this call.
            # This is the actual post-reset controller/policy state, with the
            # unchanged physical state; no reset or state injection is added.
            record['post_reset_snapshot']=snapshot()
            record['policy_tensors_sha256']=hist.tensor_digest(ctrl._policy)
        controller_resets.append(record)
        return value
    def boundary(phase):
        boundaries.append({'node':runner.index,'phase':phase,'snapshot':snapshot(),
                           'policy_tensors_sha256':hist.tensor_digest(runner.base._policy)})
    def emit(row):
        nonlocal triggered
        if row['original_progress_m']>7 and not triggered:
            trigger={'next_native_step':ledger.attempts+1,'native_prefix_sha256':ledger.hash.hexdigest(),
                     'snapshot':snapshot(),'policy_tensors_sha256':hist.tensor_digest(runner.base._policy),
                     'frame':{'origin':list(runner.frame.initial_position),'yaw':runner.frame.initial_yaw_rad},
                     'progress_m':row['original_progress_m']}
            write(destination/'preintervention.json',trigger)
            if arm=='terminal_schedule' and trigger!=read(destination.parent/'constant/preintervention.json'):
                raise RuntimeError('PREINTERVENTION_NATIVE_POLICY_STATE_MISMATCH')
            triggered=True
        schedules.write(json.dumps(row,allow_nan=False)+'\n')
        # Legacy zero-residual authority checker derives corrected vx from this
        # diagnostic variable. Preserve its assertion, supply declared scheduled
        # nominal, and separately retain original nominal in schedule/trace.
        runner.last_nominal_command=np.asarray(row['scheduled_nominal'],dtype=np.float64)

    class Runner(hist.AcquisitionRunner):
        def __init__(self):
            nonlocal runner
            runner=self
            super().__init__(case,'CONTINUE',destination,deadline,push_spec=None)
            if self.sim.timestep!=.002: raise RuntimeError('TIMESTEP_DRIFT')
            prior=self.router.execute
            def observed_execute(request,context):
                check()
                if errors: raise RuntimeError('PRIOR_TECHNICAL_EXCEPTION')
                if self.index==1:
                    fixed=FixedAlphaCorrectionPolicy(self,.25,self.correction.delegate)
                    self.correction=ScheduledCorrection(self,fixed,arm,emit)
                    self.reference_mode='fixed_alpha0.25'; self.alpha=.25
                boundary('entry')
                value=prior(request,context)
                boundary('exit')
                if errors:
                    write(destination/'router_result_on_exception.json',{'status':value.status.value,'reason':value.reason,'metrics':value.metrics})
                    raise RuntimeError('TECHNICAL_EXCEPTION_CAUGHT_BY_ROUTER')
                return value
            self.router.execute=observed_execute

    mujoco.mj_step=native; simulation.G1Simulation.step=step
    simulation.G1Simulation.reset=reset; simulation.G1Simulation.set_base_state=set_base
    G1LocomotionController.compute_torques=compute; G1LocomotionController.reset=ctrl_reset
    hist.YAW.profile_action=hist.action
    try:
        with hist.CONTROLLER.isolated_controller():
            Runner(); result=runner.run(); write(destination/'result.json',result)
    except ObservedPhysicalStop as exc:
        stop_reason=str(exc)
    except BaseException as exc:
        error('execution',exc)
        (destination/'exception.txt').write_text(traceback.format_exc(),encoding='utf-8')
    finally:
        def save(name,action):
            try: action()
            except BaseException as exc: archive_errors.append({'operation':name,'type':type(exc).__name__,'message':str(exc)})
        if runner is not None:
            save('partial_nodes',lambda:write(destination/'partial_nodes.json',getattr(runner,'nodes',[])))
            def archive():
                if not runner.sim.states or runner.sim.states[-1][0]!=runner.sim.simulation_time: runner.sim.snapshot()
                names=('time_s','qpos','qvel','ctrl','node_index','planned_origin','planned_heading','local_origin','local_heading','reference_heading')
                np.savez_compressed(destination/'poses.npz',**dict(zip(names,[np.asarray(v) for v in zip(*runner.sim.states)])))
            save('poses',archive)
            if hasattr(runner,'decision_file'): save('decision_close',runner.decision_file.close)
            save('runner_close',runner.close)
        save('boundaries',lambda:write(destination/'boundaries.json',boundaries))
        save('controller_resets',lambda:write(destination/'controller_resets.json',controller_resets))
        save('schedule_close',schedules.close); save('native_close',ledger.close)
        mujoco.mj_step=original_native; simulation.G1Simulation.step=original_step
        simulation.G1Simulation.reset=original_reset; simulation.G1Simulation.set_base_state=original_set
        G1LocomotionController.compute_torques=original_compute; G1LocomotionController.reset=original_ctrl_reset
        hist.YAW.profile_action=original_action
    status={'complete':result is not None and len(result['nodes'])==3 and not errors and not archive_errors,
            'physical_failure_observed':any(observed.values()) or any(n.get('physical_success') is False for n in getattr(runner,'nodes',[])),
            'nonfinite_state_observed':observed['nonfinite'],'technical_errors':errors,'archive_errors':archive_errors,
            'native_attempts':ledger.attempts,'native_steps_completed':ledger.completed,
            'native_completion_unknown':ledger.attempts-ledger.completed,'native_sha256':ledger.hash.hexdigest(),
            'reset_events':resets,'stop_reason':stop_reason,'optimizer_updates':0,'checkpoint_writes':0,
            'prefix_only':True,'trigger_observed':triggered}
    write(destination/'status.json',status)
    return status
