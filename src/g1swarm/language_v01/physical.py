"""Single authorized experiment backend; imports models only inside execute().

The launcher supplies the independently checked Owner record. This module is
not an authorization API and contains no CLI or alternate execution entry.
"""
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
import time

from .action import validate_preparation
from .service import canonical, digest, ROOT, PROTOCOL
from .demo_identity import read, sha, write


class PhysicalStop(RuntimeError):
    """Observed physical failure stops execution; it is not a technical error."""


def plain(value):
    if hasattr(value, 'detach'): value = value.detach().cpu().numpy()
    if hasattr(value, 'tolist'): value = value.tolist()
    if isinstance(value, dict): return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value): return {'nonfinite': str(value)}
    return value


def snapshot(session):
    simulation, controller = session.simulation, session.controller
    memory = {name: plain(tensor) for name, tensor in controller._policy.state_dict().items()}
    # Some TorchScript exporters keep recurrent state outside state_dict.
    for module_name, module in controller._policy.named_modules():
        for name in ('hidden_states', 'hidden_state', 'cell_state', 'hidden_a', 'cell_a'):
            if hasattr(module, name): memory[module_name + ':' + name] = plain(getattr(module, name))
    data = simulation._data
    return {'qpos': plain(data.qpos), 'qvel': plain(data.qvel), 'ctrl': plain(data.ctrl),
            'time_s': float(data.time), 'state': simulation.get_robot_state().to_dict(),
            'controller_counter': controller._counter, 'controller_action': plain(controller._action),
            'controller_target': plain(controller._target), 'controller_memory': memory,
            'session_steps': session.total_steps}


def finite_snapshot(value):
    if isinstance(value, dict): return 'nonfinite' not in value and all(finite_snapshot(v) for v in value.values())
    if isinstance(value, list): return all(finite_snapshot(v) for v in value)
    return not isinstance(value, float) or math.isfinite(value)


class Witness:
    """Count native attempts/completions independently of Router result labels."""
    def __init__(self, limit, deadline, journal):
        self.limit, self.deadline, self.journal = limit, deadline, journal
        self.attempts = self.completed = self.resets = 0
        self.policy_attempts = self.policy_completed = 0
        self.post_checkpoint_resets = 0
        self.errors = []
        self.physical = {'fallen': False, 'nonfinite': False}
        self.physical_observation = {'fallen':'NOT_OBSERVED', 'nonfinite':'NOT_OBSERVED'}
        self.state_reader = None
        self.rows = 0

    def check(self):
        if self.errors: raise RuntimeError('PRIOR_TECHNICAL_FAILURE')
        if any(self.physical.values()): raise PhysicalStop('OBSERVED_PHYSICAL_FAILURE')
        if time.perf_counter() >= self.deadline:
            exc = TimeoutError('PHYSICAL_DEADLINE_EXCEEDED')
            self.error('deadline_guard', exc); raise exc

    def record(self, row):
        self.journal.write(json.dumps(plain(row), allow_nan=False, separators=(',', ':')) + '\n')
        self.journal.flush(); self.rows += 1

    def error(self, stage, exc):
        row = {'stage': stage, 'type': type(exc).__name__, 'message': str(exc),
               'native_attempts': self.attempts, 'native_completed': self.completed}
        if isinstance(exc, PhysicalStop): self.record({'physical_stop': row})
        else: self.errors.append(row); self.record({'exception': row})

    def observe(self, data):
        raw = {'time_s':float(data.time), 'qpos':plain(data.qpos), 'qvel':plain(data.qvel), 'ctrl':plain(data.ctrl)}
        finite = finite_snapshot(raw['qpos']) and finite_snapshot(raw['qvel'])
        self.physical['nonfinite'] |= not finite
        self.physical_observation['nonfinite'] = 'OBSERVED_FAILURE' if self.physical['nonfinite'] else 'OBSERVED_FINITE'
        observation = {'raw':raw, 'physical_failure':dict(self.physical)}
        try:
            if self.state_reader is None: raise ValueError('STATE_READER_NOT_AVAILABLE')
            state = self.state_reader()
            self.physical['fallen'] |= bool(state.fallen)
            self.physical['nonfinite'] |= not state.is_finite()
            self.physical_observation['fallen'] = 'OBSERVED_FAILURE' if self.physical['fallen'] else 'OBSERVED_NO_FALL'
            observation['state'] = state.to_dict()
        except BaseException as exc:
            self.physical_observation['fallen'] = 'OBSERVED_FAILURE' if self.physical['fallen'] else 'UNKNOWN'
            observation['state_observation_error'] = {'type':type(exc).__name__, 'message':str(exc)}
        observation['physical_failure'] = dict(self.physical)
        observation['physical_observation'] = dict(self.physical_observation)
        return observation

    def native(self, original, model, data, *args, **kwargs):
        self.check()
        if args or kwargs or self.attempts >= self.limit:
            exc = RuntimeError('BATCHED_NATIVE_STEP_REJECTED' if args or kwargs else 'NATIVE_STEP_BUDGET_EXCEEDED')
            self.error('native_guard', exc); raise exc
        self.attempts += 1
        self.record({'native_attempt': self.attempts, 'pre': {
            'time_s': float(data.time), 'qpos': plain(data.qpos), 'qvel': plain(data.qvel), 'ctrl': plain(data.ctrl)}})
        try: result = original(model, data)
        except BaseException as exc:
            self.record({'native_post_unknown':self.attempts, **self.observe(data)})
            self.error('native_step', exc); raise
        self.completed += 1
        self.record({'native_completed': self.completed, 'post': {
            'time_s': float(data.time), 'qpos': plain(data.qpos), 'qvel': plain(data.qvel), 'ctrl': plain(data.ctrl)}})
        self.record({'native_observation':self.completed, **self.observe(data)})
        return result


def _runtime():
    # The real launcher must validate authorization before calling this function.
    import random
    import numpy as np
    import torch
    import mujoco
    from g1swarm.config import load_yaml
    from g1swarm.mission import live_session
    from g1swarm.mission.runtime import MissionExecutor
    from g1swarm.mission.ir import Mission
    from g1swarm.mission.validator import MissionValidator
    from g1swarm.mission.grounding import CapabilityGrounder
    from g1swarm.simulation.g1_simulation import G1Simulation
    from g1swarm.control.g1_locomotion import G1LocomotionController
    import importlib.util
    # Exact retained collector, without invoking acquire()/freeze().
    import sys
    sys.path.insert(0, str(ROOT))
    try:
        spec = importlib.util.spec_from_file_location('language_g1_pose_collector',
            ROOT/'experiments/m2/closed_loop_mission_001/acquire.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    finally: sys.path.remove(str(ROOT))
    PoseCollector = module.PoseCollector
    return locals()


def execute(preparation: dict, source: dict, directory: Path, deadline: float) -> dict:
    """One continuous real mission; owner checking belongs to the sole launcher."""
    private = json.loads(canonical(preparation))
    mission_bytes = validate_preparation(private)
    if (private['C_exec'] != source['C_exec'] or Path(source['root']).resolve() != ROOT.resolve()
            or private['budget']['native_steps'] != 15000 or not Path(directory).is_dir()):
        raise PermissionError('BACKEND_EXECUTION_IDENTITY_OR_BUDGET_MISMATCH')
    if time.perf_counter() >= deadline: raise TimeoutError('BACKEND_DEADLINE_EXCEEDED_BEFORE_IMPORT')
    directory = Path(directory)
    journal = (directory/'native.jsonl').open('x', encoding='utf-8', buffering=1)
    witness = Witness(15000, deadline, journal)
    session = None; poses = None; result = None; saved = {}; archival = []
    checkpoint = None; constructing = True; created_simulation = None
    try:
        runtime = _runtime()
        np, torch, mujoco = (runtime[key] for key in ('np', 'torch', 'mujoco'))
        torch.set_num_threads(1); torch.use_deterministic_algorithms(True)
        runtime['random'].seed(0); np.random.seed(0); torch.manual_seed(0)
        protocol = read(ROOT/PROTOCOL)
        robot = runtime['load_yaml'](ROOT/protocol['robot_config'])
        for section, key in (('model', 'xml_path'), ('controller', 'policy_path')):
            relative = robot[section][key]
            target = (Path(source['asset_root'])/relative).resolve()
            if not target.is_relative_to(Path(source['asset_root']).resolve()) or sha(target) != source['assets'][relative]:
                raise ValueError('BACKEND_ASSET_BINDING_MISMATCH:'+relative)
            robot[section][key] = str(target)
        if sha(robot['controller']['policy_path']) != protocol['provenance']['policy_sha256']:
            raise ValueError('RETAINED_POLICY_MISMATCH')
        poses = runtime['PoseCollector']()
        simulation_class, controller_class = runtime['G1Simulation'], runtime['G1LocomotionController']
        def patch(stack, obj, key, value):
            prior = getattr(obj, key); setattr(obj, key, value)
            stack.callback(setattr, obj, key, prior); return prior
        with ExitStack() as stack:
            original_native = mujoco.mj_step
            patch(stack, mujoco, 'mj_step', lambda m, d, *a, **k: witness.native(original_native, m, d, *a, **k))
            original_reset = simulation_class.reset
            def reset(sim, **kwargs):
                nonlocal created_simulation
                created_simulation = sim
                witness.check()
                # Preserve both retained constructor initializations. Neither
                # steps physics; all additional/post-checkpoint resets refuse.
                if not constructing or witness.attempts or witness.resets >= 2:
                    witness.post_checkpoint_resets += int(not constructing)
                    exc = RuntimeError('UNEXPECTED_SIMULATOR_RESET')
                    witness.error('reset_guard', exc); raise exc
                witness.resets += 1
                return original_reset(sim, **kwargs)
            patch(stack, simulation_class, 'reset', reset)
            original_step, original_compute = simulation_class.step, controller_class.compute_torques
            def step(sim, control=None):
                witness.check()
                try: state = original_step(sim, control)
                except BaseException as exc:
                    witness.physical['nonfinite'] |= not bool(np.isfinite(sim._data.qpos).all() and np.isfinite(sim._data.qvel).all())
                    # The retained adapter's finite-state check is a physical
                    # stop. A previously recorded native/control error remains
                    # technical, even when physical failure also occurred.
                    if any(witness.physical.values()) and not witness.errors:
                        stop = PhysicalStop(str(exc)); witness.error('simulation_step', stop); raise stop from exc
                    witness.error('simulation_step', exc); raise
                witness.physical['fallen'] |= bool(state.fallen)
                witness.physical['nonfinite'] |= not state.is_finite()
                witness.record({'state': state.to_dict(), 'native_completed': witness.completed})
                if witness.physical['fallen'] or witness.physical['nonfinite']:
                    raise PhysicalStop('OBSERVED_PHYSICAL_FAILURE')
                return state
            def compute(ctrl, **kwargs):
                witness.check()
                witness.record({'control_command': plain(kwargs['command']), 'native_completed':witness.completed})
                try: return original_compute(ctrl, **kwargs)
                except BaseException as exc:
                    witness.error('controller_compute', exc); raise
            patch(stack, simulation_class, 'step', step)
            patch(stack, controller_class, 'compute_torques', compute)
            session = runtime['live_session'].LiveMissionSession(robot_config=robot, protocol=protocol,
                         seed=0, simulation_wrapper=poses.wrap)
            constructing = False
            policy = session.controller._policy
            class CountedPolicy:
                def __getattr__(self, name): return getattr(policy, name)
                def __call__(self, *args, **kwargs):
                    witness.check(); witness.policy_attempts += 1
                    witness.record({'policy_attempt':witness.policy_attempts,'native_completed':witness.completed})
                    try: response = policy(*args, **kwargs)
                    except BaseException as exc:
                        witness.error('policy_inference', exc); raise
                    witness.policy_completed += 1
                    witness.record({'policy_completed':witness.policy_completed,'native_completed':witness.completed})
                    return response
            session.controller._policy = CountedPolicy()
            witness.state_reader = session.simulation.get_robot_state
            poses.capture(session.simulation)
            checkpoint = snapshot(session)
            state = session.state()
            if (not state.is_finite() or not finite_snapshot(checkpoint) or state.standing is not True or state.fallen is not False
                    or state.active_skill is not None or state.simulation_time != 0.0 or witness.resets != 2):
                raise PermissionError('INITIAL_LIVE_STATE_NOT_ELIGIBLE')
            write(directory/'initial-state.json', checkpoint)
            paths = protocol['grounding']['evidence']
            grounder = runtime['CapabilityGrounder'](risk_map_path=ROOT/paths['risk_map'],
                boundary_comparison_path=ROOT/paths['boundary_comparison'],capability_map_path=ROOT/paths['capability_map'],
                historical_limits=protocol['grounding']['historical'],mode_preference=protocol['grounding']['mode_preference'])
            executor = runtime['MissionExecutor'](validator=runtime['MissionValidator'](),grounder=grounder,
                session_factory=lambda seed: (_ for _ in ()).throw(RuntimeError('SECOND_SESSION_REJECTED')),
                protocol=protocol,seed=0,recorder_root=str(directory/'ledger'),walk_strict_gate=True,
                provenance={'C_exec':private['C_exec'],'request_id':private['request_id'],
                            'preparation_sha256':private['preparation_sha256'],'mission_sha256':digest(mission_bytes)})
            mission = runtime['Mission'].from_dict(json.loads(mission_bytes))
            witness.check()
            if canonical(snapshot(session)) != canonical(checkpoint): raise PermissionError('LIVE_STATE_DRIFT_BEFORE_DISPATCH')
            result = executor.run(mission, existing_session=session, phase='language-g1-real-new-mission').to_dict()
            write(directory/'result.json', result)
            if witness.errors: raise RuntimeError('ROUTER_OR_RUNTIME_MASKED_TECHNICAL_FAILURE')
            if result['failure_type'] in ('INTERNAL_ERROR', 'INVALID_STATE') and not any(witness.physical.values()):
                raise RuntimeError('RUNTIME_TECHNICAL_FAILURE:'+str(result['failure_reason']))
    except BaseException as exc:
        witness.error('backend', exc)
    finally:
        if session is not None:
            try: write(directory/'final-state.json', snapshot(session))
            except BaseException as exc: archival.append({'stage':'final_state','type':type(exc).__name__,'message':str(exc)})
            try: poses.save(directory/'poses.npz', session.simulation)
            except BaseException as exc:
                # Preserve even zero/one-frame partial capture; rendering refuses it.
                archival.append({'stage':'poses','type':type(exc).__name__,'message':str(exc)})
                write(directory/'partial-poses.json', {'time_s':poses.times,'qpos':plain(poses.qpos),
                                                      'qvel':plain(poses.qvel),'ctrl':plain(poses.ctrl)})
            try: session.close()
            except BaseException as exc: archival.append({'stage':'close','type':type(exc).__name__,'message':str(exc)})
        elif created_simulation is not None:
            try:
                write(directory/'partial-state.json',plain({'qpos':created_simulation._data.qpos,
                    'qvel':created_simulation._data.qvel,'ctrl':created_simulation._data.ctrl,
                    'time_s':float(created_simulation._data.time)}))
                created_simulation.close()
            except BaseException as exc: archival.append({'stage':'partial_constructor_close','type':type(exc).__name__,'message':str(exc)})
        journal.close()
        # The launcher/Job receipts and worker stdout may still be open when
        # this backend returns. Freeze only closed backend-owned evidence.
        owned = [directory/name for name in ('native.jsonl','initial-state.json','final-state.json',
                    'partial-state.json','poses.npz','partial-poses.json','result.json')]
        owned += list((directory/'ledger').rglob('*'))
        saved = {path.relative_to(directory).as_posix():sha(path) for path in owned if path.is_file()}
        receipt = {'kind':'NEW_MUJOCO_CAPTURE','request_id':private['request_id'],
            'preparation_sha256':private['preparation_sha256'],'C_exec':private['C_exec'],
            'executed_mission_sha256':digest(mission_bytes),'native_attempts':witness.attempts,'native_completed':witness.completed,
            'startup_reset_requests':witness.resets,'post_checkpoint_reset_requests':witness.post_checkpoint_resets,
            'policy_inference_attempts':witness.policy_attempts,'policy_inference_completed':witness.policy_completed,
            'runtime_result':result,'physical_failure':dict(witness.physical),'technical_errors':witness.errors,
            'physical_observation':dict(witness.physical_observation),
            'archival_errors':archival,'files':saved,'media':None,
            'status':'COMPLETED' if result and result['mission_success'] and not witness.errors and not archival else 'FAILED_OR_PARTIAL',
            'failure_action':'STOP_SIMULATION_NO_ADDITIONAL_PHYSICAL_HALT_NO_RECOVERY'}
        write(directory/'physical.json', receipt)
    return receipt
