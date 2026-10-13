"""Lazy physical backend. Never import this module as a preflight shortcut."""
import functools
import hashlib
import importlib.util
import json
import math
import random
import sys
import time
import traceback

from contract import ROOT, HERE, Budget, physical_failure, paired_entry, read, write
from rule import select

def execute(arm, destination, deadline):
    # Called only after the launcher's source + Owner-operation gate.
    import numpy as np
    import torch
    import mujoco
    from g1swarm.simulation import g1_simulation as simulation
    from g1swarm.control.g1_locomotion import G1LocomotionController
    from g1swarm.tradeoff_isolation.experiment import FixedAlphaCorrectionPolicy
    spec = importlib.util.spec_from_file_location('stand5_retained', ROOT/'experiments/phase3b/decision_benchmark_acquisition_001/study.py')
    hist = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hist)
    case = hist.derive_case(json.loads((ROOT/'experiments/phase3a/residual_yaw_component_001/case.json').read_text()),
                           {'case_id': 'phase3b0a-stand5-16m', 'stand_duration_s': 5.0})
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    random.seed(0); np.random.seed(0); torch.manual_seed(0)
    budget = Budget(deadline)
    errors, archival_errors, observed = [], [], {'fallen': False, 'nonfinite': False}
    native_attempts = 0
    runner = None
    result = None
    journal = (destination/'native_journal.jsonl').open('x', encoding='utf-8', buffering=1)
    original_step = simulation.G1Simulation.step
    original_native = mujoco.mj_step
    original_compute = G1LocomotionController.compute_torques
    original_reset = simulation.G1Simulation.reset
    original_set = simulation.G1Simulation.set_base_state
    resets = []
    def record_error(stage, exc):
        row = {'stage': stage, 'type': type(exc).__name__, 'message': str(exc), 'steps': budget.steps}
        errors.append(row)
        journal.write(json.dumps({'exception': row})+'\n')
    def step(sim, control=None):
        budget.before_step()
        try:
            value = original_step(sim, control)
        except BaseException as exc:
            observed['nonfinite'] |= not bool(np.isfinite(sim._data.qpos).all() and np.isfinite(sim._data.qvel).all())
            record_error('simulation_step', exc)
            raise
        observed['fallen'] |= bool(value.fallen)
        journal.write(json.dumps({'step': budget.steps, 'time_s': value.simulation_time,
                                  'fallen': bool(value.fallen)})+'\n')
        return value
    def native(model, data, *args, **kwargs):
        nonlocal native_attempts
        budget.before_step()
        if args or kwargs or native_attempts >= 40000:
            raise RuntimeError('NON_SINGLE_NATIVE_STEP_OR_ATTEMPT_BUDGET')
        native_attempts += 1
        value = original_native(model, data)
        # Count here, before G1Simulation's post-step finite-state check.
        budget.completed_step()
        return value
    def compute(ctrl, **kwargs):
        budget.before_step()
        try:
            return original_compute(ctrl, **kwargs)
        except BaseException as exc:
            record_error('controller_compute', exc)
            raise
    def reset(sim, **kwargs):
        if budget.steps or resets:
            raise RuntimeError('UNEXPECTED_SIMULATOR_RESET')
        resets.append('constructor_reset')
        return original_reset(sim, **kwargs)
    def set_base(sim, **kwargs):
        if budget.steps or 'initial_base' in resets:
            raise RuntimeError('UNEXPECTED_BASE_STATE_INJECTION')
        resets.append('initial_base')
        return original_set(sim, **kwargs)

    class Runner(hist.AcquisitionRunner):
        def __init__(self):
            # Register partial instance before constructors can raise.
            nonlocal runner
            runner = self
            super().__init__(case, 'CONTINUE', destination, deadline, push_spec=None)
            self.selection = None
            prior = self.router.execute
            def selected(request, context):
                if errors:
                    raise RuntimeError('PRIOR_TECHNICAL_FAILURE')
                if self.index == 1:
                    if self.selection is not None:
                        raise RuntimeError('REPEATED_SELECTION')
                    xy = list(self.node_start.base_position[:2])
                    actual = self.frame.initial_yaw_rad
                    heading = float(self.planned_heading)
                    waypoint = [float(self.planned_origin[0])+8*math.cos(heading),
                                float(self.planned_origin[1])+8*math.sin(heading)]
                    proposal = select(xy, actual, heading, waypoint)
                    alpha = proposal['alpha'] if arm == 'selected' else .25
                    if alpha is None:
                        raise RuntimeError('UNRESOLVED_REFERENCE')
                    if arm == 'selected' and alpha != .5:
                        raise RuntimeError('REPLAY_ANCHOR_REFERENCE_MISMATCH')
                    if arm == 'fixed':
                        data = self.sim._data
                        entry = {'simulation_time_s':float(data.time), 'qpos':data.qpos.tolist(),
                                 'qvel':data.qvel.tolist(), 'ctrl':data.ctrl.tolist(),
                                 'robot_state':self.node_start.to_dict(), 'planned_origin':self.planned_origin.tolist(),
                                 'planned_heading_rad':heading, 'policy_tensors_sha256':hist.tensor_digest(self.base._policy),
                                 'push_active':False, 'applied_force_clear':bool(np.array_equal(data.xfrc_applied,np.zeros_like(data.xfrc_applied)))}
                        if not paired_entry(read(destination.parent/'selected/predecision.json'),entry):
                            write(destination/'mismatched_entry.json',entry)
                            raise RuntimeError('PAIRED_ENTRY_MISMATCH_BEFORE_FIRST_WALK')
                    self.selection = {'arm': arm, 'proposal': proposal, 'applied_alpha': alpha,
                                      'input': {'xy': xy, 'actual_yaw': actual, 'mission_yaw': heading, 'waypoint': waypoint}}
                    write(destination/'selection.json', self.selection)
                    # Preserve historical .5 objects exactly. Use existing .25 implementation.
                    if alpha != .5:
                        self.correction = FixedAlphaCorrectionPolicy(self, alpha, self.correction.delegate)
                        self.reference_mode = 'fixed_alpha0.25'
                        self.alpha = alpha
                value = prior(request, context)
                # Router can translate technical control errors to UNSAFE. Retain the
                # returned node evidence as well, but do not dispatch another node.
                if errors:
                    write(destination/'router_result_on_exception.json',
                          {'status': value.status.value, 'reason': value.reason, 'metrics': value.metrics})
                    raise RuntimeError('TECHNICAL_EXCEPTION_CAUGHT_BY_ROUTER')
                return value
            self.router.execute = selected

    original_action = hist.YAW.profile_action
    simulation.G1Simulation.step = step
    mujoco.mj_step = native
    simulation.G1Simulation.reset = reset
    simulation.G1Simulation.set_base_state = set_base
    G1LocomotionController.compute_torques = compute
    hist.YAW.profile_action = hist.action
    before_tensor = None
    try:
        with hist.CONTROLLER.isolated_controller():
            Runner()
            before_tensor = hist.tensor_digest(runner.base._policy)
            result = runner.run()
            write(destination/'result.json', result)
    except BaseException as exc:
        record_error('execution', exc)
        (destination/'exception.txt').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        def save(label, action):
            try:
                action()
            except BaseException as exc:
                archival_errors.append({'operation': label, 'type': type(exc).__name__, 'message': str(exc)})
        if runner is not None:
            save('partial_nodes', lambda: write(destination/'partial_nodes.json', getattr(runner, 'nodes', [])))
            def archive():
                if not runner.sim.states or runner.sim.states[-1][0] != runner.sim.simulation_time:
                    runner.sim.snapshot()
                fields = list(zip(*runner.sim.states))
                names = ('time_s','qpos','qvel','ctrl','node_index','planned_origin','planned_heading','local_origin','local_heading','reference_heading')
                np.savez_compressed(destination/'poses.npz', **dict(zip(names, [np.asarray(v) for v in fields])))
                receipt = {'physics_state_sha256': runner.sim.hash.hexdigest(), 'physics_steps': runner.sim.steps,
                    'streams': {k:{'sha256':v.hexdigest(),'count':runner.counts[k]} for k,v in runner.hashes.items()},
                    'initial_tensors_sha256': before_tensor, 'final_tensors_sha256': hist.tensor_digest(runner.base._policy),
                    'rng_after_sha256': hashlib.sha256(repr((random.getstate(), np.random.get_state(), torch.get_rng_state().tolist())).encode()).hexdigest(),
                    'reward_calls': runner.counts['rewards'], 'optimizer_updates':0, 'checkpoint_writes':0,
                    'full_step_authority_checks':runner.full_step_authority_checks, 'full_step_authority_violations':0,
                    'collector':'Frozen offline state observer; acquisition samples; no renderer/UI',
                    'actor_kind':'DETERMINISTIC_BOUNDED_PROBE_NOT_TRAINED'}
                write(destination/'audit.json', receipt)
            save('poses_and_audit', archive)
            if hasattr(runner, 'decision_file'):
                save('decision_close', runner.decision_file.close)
            save('runner_close', runner.close)
        simulation.G1Simulation.step = original_step
        mujoco.mj_step = original_native
        simulation.G1Simulation.reset = original_reset
        simulation.G1Simulation.set_base_state = original_set
        G1LocomotionController.compute_torques = original_compute
        hist.YAW.profile_action = original_action
        journal.close()
    failure = observed['fallen'] or observed['nonfinite'] or physical_failure(getattr(runner, 'nodes', []))
    status = {'complete': result is not None and len(result['nodes']) == 7 and not errors and not archival_errors,
              'physical_failure_observed': failure, 'technical_errors': errors, 'archive_errors': archival_errors,
              'nonfinite_state_observed':observed['nonfinite'],
              'native_steps_completed': budget.steps, 'native_attempts':native_attempts,
              'native_completion_unknown': native_attempts-budget.steps, 'reset_events': resets,
              'physical_authority': 'EXPLICIT_OWNER_OPERATION_ONLY_NOT_PRODUCTION_AUTHORIZATION'}
    write(destination/'status.json', status)
    return status
