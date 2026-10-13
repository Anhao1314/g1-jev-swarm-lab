"""Nonphysical production-source probes; no simulator or policy imports."""
import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from entry import ROOT,DESIGN,canonical
from native import NativeLedger,physical_flags
from handoff import ScheduledCorrection

def extract(path,name,scope):
    tree=ast.parse(path.read_text())
    node=deepcopy(next(n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==name))
    # Nested functions are executed with their actual statements and supplied
    # enclosing lexical state. No production import/controller is replaced.
    node.body=[ast.copy_location(ast.Global(names=n.names),n) if isinstance(n,ast.Nonlocal) else n for n in node.body]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(path),'exec'),scope)
    return scope[name]

class BackendTests(unittest.TestCase):
    def test_native_observer_is_read_only_and_unknown_completion_retained(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'native.jsonl'; l=NativeLedger(p,time.perf_counter()+10)
            state={'time_s':0.,'qpos':[0,0,.8,1,0,0,0],'qvel':[0.]*6,'ctrl':[0.]*12}
            original=deepcopy(state); l.before(state); l.after(state)
            self.assertEqual(state,original)
            l.before(state) # simulated dispatch exception: no completion record
            l.close(); self.assertEqual((l.attempts,l.completed),(2,1))
            rows=[json.loads(s) for s in p.read_text().splitlines()]
            self.assertEqual(l.hash.hexdigest(),hashlib.sha256(b''.join(canonical(r) for r in rows)).hexdigest())
    def test_native_budget_and_timeout_before_dispatch(self):
        with tempfile.TemporaryDirectory() as td:
            l=NativeLedger(Path(td)/'native',time.perf_counter()+10)
            l.attempts=32000
            with self.assertRaisesRegex(RuntimeError,'ATTEMPT_BUDGET'): l.before({})
            self.assertEqual(l.attempts,32000)
            l.attempts=0; l.deadline=0
            with self.assertRaises(TimeoutError): l.before({})
            self.assertEqual(l.attempts,0); l.close()
    def test_frozen_step_bound_not_speed_assumption(self):
        p=json.loads((DESIGN/'protocol.json').read_text())
        case=json.loads((ROOT/'experiments/phase3a/residual_yaw_component_001/case.json').read_text())
        self.assertEqual(case['nodes'][1]['parameters']['max_duration_s'],48.)
        self.assertEqual(case['nodes'][2]['parameters']['max_duration_s'],10.)
        self.assertEqual(sum(round(t/.002) for t in [5,48,10,.5]),31750)
        self.assertLess(31750,p['budget_candidate']['max_native_attempts_per_arm'])
    def test_physical_flags_preserve_nonfinite_and_fall(self):
        for z,fall in [(.45,False),(.449,True)]:
            self.assertEqual(physical_flags([0,0,z,1,0,0,0],[0]*6,[0]*12)['fallen'],fall)
        self.assertTrue(physical_flags([0,0,.8,1,0,0,0],[float('nan')],[0])['nonfinite'])
    def test_unexpected_resets_rejected_without_dispatch(self):
        calls=[]; scope={'ledger':NS(attempts=0),'resets':[],
                         'original_reset':lambda *a,**k:calls.append('reset'),
                         'original_set':lambda *a,**k:calls.append('set')}
        reset=extract(HERE/'backend.py','reset',scope); set_base=extract(HERE/'backend.py','set_base',scope)
        reset(None); set_base(None)
        with self.assertRaises(RuntimeError): reset(None)
        with self.assertRaises(RuntimeError): set_base(None)
        self.assertEqual(calls,['reset','set'])
    def test_actual_window_controller_and_authority_assertion(self):
        controller_source=ROOT/'experiments/phase3a/residual_yaw_component_001/controller.py'
        observed_source=ROOT/'experiments/phase3a/residual_yaw_component_001/study.py'
        scope={'np':np,'math':math,'time':time,'ORIGINAL_CONTROLLER':object,'Cancelled':RuntimeError,
               'PAIRS':{('stand','walk_forward')},'WINDOW':2.,'QUANTUM_STEPS':50,
               'BOUNDS':np.array([.1,.06,.12]),'tilt':lambda s:0.}
        Controller=extract(controller_source,'WindowController',scope)
        for arm in ['constant','terminal_schedule']:
            calls=[]; traces=[]
            state=NS(base_position=(7.5,0,.8),simulation_time=20.)
            frame=NS(project=lambda p:(p[0],p[1]))
            r=NS(index=1,skill='walk_forward',previous='stand',frame=frame,
                 parameters={'target_distance_m':8.,'speed_mps':.5},resets=0,
                 abort=NS(is_set=lambda:False),treatment='learned',node_steps=0,
                 node_start=NS(simulation_time=0),authority_window_s=2.,
                 sim=NS(get_robot_state=lambda:state,simulation_time=20.),action=np.zeros(3),
                 observation=lambda *a:np.zeros(2),control=lambda *a:np.zeros(3),
                 dense_reward=lambda:0.,trace=traces.append,mask_window=lambda:2.,
                 full_step_authority_checks=0,audit_array=lambda *a:None)
            delegate=NS(alpha=.25,last_sample={'yaw_clipped':.07})
            def correct(s,f,command,**kw):
                result=command.copy(); result[2]=.07; return result,{}
            delegate.compute=correct
            emit_scope={'runner':r,'triggered':True,'np':np,'schedules':NS(write=lambda s:None),'json':json}
            emit=extract(HERE/'backend.py','emit',emit_scope)
            r.correction=ScheduledCorrection(r,delegate,arm,emit)
            original=lambda **kw:calls.append(kw['command'].copy()) or np.zeros(12)
            r.base=NS(_action=np.zeros(12),reset=lambda:None)
            obs_scope=dict(scope,self=r,deadline=time.perf_counter()+10,probe_id='CONTINUE',
                           original_torques=original,profile_action=lambda *a:np.zeros(3))
            r.base.compute_torques=extract(observed_source,'observed_torques',obs_scope)
            c=Controller(r); c.reset(); c.compute_torques(command=np.array([.5,0.,0.]))
            expected=.5 if arm=='constant' else .375
            self.assertEqual(tuple(calls[0]),(expected,0.,.07))
            self.assertEqual(traces[0]['nominal_command'],[.5,0.,0.])
            self.assertEqual(traces[0]['applied_command'],[expected,0.,.07])
            with self.assertRaisesRegex(RuntimeError,'Original applied authority'):
                r.base.compute_torques(command=np.array([expected+.01,0.,.07]))
    def test_native_exception_keeps_observed_physical_failure(self):
        with tempfile.TemporaryDirectory() as td:
            l=NativeLedger(Path(td)/'native',time.perf_counter()+10)
            s={'qpos':[0,0,.8,1,0,0,0],'qvel':[0.]*6,'ctrl':[0.]*12}
            def fail(*a): s['qpos'][2]=.1; raise ValueError('injected native exception')
            scope={'runner':NS(base=True),'ledger':l,'check':l.check,'snapshot':lambda data:deepcopy(s),
                   'original_native':fail,'physical_flags':physical_flags,'observed':{'fallen':False,'nonfinite':False},
                   'destination':Path(td),'json':json}
            call=extract(HERE/'backend.py','native',scope)
            with self.assertRaises(ValueError): call(None,None)
            self.assertTrue(scope['observed']['fallen']); self.assertEqual((l.attempts,l.completed),(1,0))
            self.assertEqual(json.loads((Path(td)/'native_exception_state.json').read_text())['qpos'][2],.1)
            l.close()
    def test_no_heavy_modules_loaded(self):
        for m in ['torch','mujoco','gymnasium']: self.assertNotIn(m,sys.modules)

    def test_poststep_recording_failure_does_not_hide_fall(self):
        with tempfile.TemporaryDirectory() as td:
            l=NativeLedger(Path(td)/'native',time.perf_counter()+10)
            data=NS(qpos=np.array([0,0,.8,1,0,0,0]),qvel=np.zeros(6),ctrl=np.zeros(12))
            def actual(*a): data.qpos[2]=.1
            after=l.after
            def disk_failure(s):
                l.completed+=1
                raise OSError('injected after-write failure')
            l.after=disk_failure
            scope={'runner':NS(base=True),'ledger':l,'check':l.check,'snapshot':lambda data:{},
                   'original_native':actual,'physical_flags':physical_flags,'observed':{'fallen':False,'nonfinite':False},
                   'destination':Path(td),'json':json}
            call=extract(HERE/'backend.py','native',scope)
            with self.assertRaises(OSError): call(None,data)
            self.assertTrue(scope['observed']['fallen']); self.assertTrue(l.failed)
            self.assertEqual((l.attempts,l.completed),(1,1)); l.close()

if __name__=='__main__': unittest.main(verbosity=2)
