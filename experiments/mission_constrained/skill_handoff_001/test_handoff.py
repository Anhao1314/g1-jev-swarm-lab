"""Nonphysical tests; source-extracted call-path tests use a recording fake base.
No torch, mujoco, policy asset or physical backend imports.
"""
import ast
from copy import deepcopy
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE))
import handoff as h

def row(**updates):
    value=dict(complete=True,physical=True,strict=True,technical=False,
               exit_speed=.49,mean_speed=.49,walk_world_norm=.35,
               turn_world_norm=.6,turn_x=.44,turn_y=-.41,turn_heading=-.05,duration=26.)
    value.update(updates)
    return value

class Frame:
    def __init__(self,xy=(0.,0.),yaw=0.): self.xy,self.yaw=xy,yaw
    def project(self,position):
        x,y=position[0]-self.xy[0],position[1]-self.xy[1]
        return math.cos(self.yaw)*x+math.sin(self.yaw)*y,-math.sin(self.yaw)*x+math.cos(self.yaw)*y

class FakeCorrection:
    alpha=.25
    def compute(self,state,frame,command,**kwargs):
        self.received=command
        out=np.array(command,copy=True); out[2]=.07
        return out,'sample'

def wrapper(arm='terminal_schedule',frame=None,emit=None):
    r=NS(index=1,skill='walk_forward',frame=frame or Frame(),parameters={'target_distance_m':8.,'speed_mps':.5})
    d=FakeCorrection(); log=[]
    w=h.ScheduledCorrection(r,d,arm,emit or log.append)
    return r,d,w,log

class HandoffTests(unittest.TestCase):
    def test_rule_boundaries_and_no_early_change(self):
        for p,v in [(-1,.5),(0,.5),(6.999,.5),(7,.5),(7.5,.375),(8,.25),(9,.25)]:
            with self.subTest(p=p): self.assertAlmostEqual(h.speed(p,'terminal_schedule'),v)
    def test_control_constant(self):
        for p in [-1,7,7.5,8,9]: self.assertEqual(h.speed(p,'constant'),.5)
    def test_invalid_progress_or_arm(self):
        for p in [True,None,'7',float('nan'),float('inf')]:
            with self.subTest(p=p),self.assertRaises(ValueError): h.speed(p,'terminal_schedule')
        with self.assertRaises(ValueError): h.speed(7,'new_profile')
    def test_monotone_bounded_schedule(self):
        values=[h.speed(i/100,'terminal_schedule') for i in range(901)]
        self.assertTrue(all(.25<=v<=.5 for v in values))
        self.assertTrue(all(b<=a for a,b in zip(values,values[1:])))
    def test_original_frame_rigid_transform(self):
        r,d,w,log=wrapper(frame=Frame((10.,20.),math.pi/2))
        nominal=np.array([.5,0,0]); original=nominal.copy()
        output,sample=w.compute(NS(base_position=(10.,27.5,0)),r.frame,nominal,sim_time_s=10.)
        self.assertEqual(tuple(output),(.375,0.,.07)); self.assertEqual(sample,'sample')
        np.testing.assert_array_equal(nominal,original)
        self.assertEqual(log[0]['original_progress_m'],7.5)
    def test_baseline_forwards_identical_command_object(self):
        r,d,w,log=wrapper('constant'); nominal=np.array([.5,0,0])
        w.compute(NS(base_position=(7.5,0,0)),r.frame,nominal,sim_time_s=1.)
        self.assertIs(d.received,nominal)
    def test_wrong_node_frame_or_semantics_reject(self):
        for field,value in [('index',2),('skill','turn'),('parameters',{'target_distance_m':4.,'speed_mps':.5})]:
            r,d,w,_=wrapper(); setattr(r,field,value)
            with self.subTest(field=field),self.assertRaises(ValueError):
                w.compute(NS(base_position=(7,0,0)),r.frame,np.array([.5,0,0]),sim_time_s=1.)
        r,d,w,_=wrapper()
        with self.assertRaises(ValueError): w.compute(NS(base_position=(7,0,0)),Frame(),np.array([.5,0,0]),sim_time_s=1.)
    def test_wrong_delegate_or_nominal_reject(self):
        r,d,_,_=wrapper(); d.alpha=.5
        with self.assertRaises(ValueError): h.ScheduledCorrection(r,d,'constant',list().append)
        r,d,w,_=wrapper()
        with self.assertRaises(ValueError): w.compute(NS(base_position=(7,0,0)),r.frame,[.4,0,0],sim_time_s=1.)
    def test_observer_failure_prevents_delegate(self):
        def fail(row): raise OSError('injected disk failure')
        r,d,w,_=wrapper(emit=fail)
        with self.assertRaises(OSError): w.compute(NS(base_position=(7.5,0,0)),r.frame,[.5,0.,0.],sim_time_s=1.)
        self.assertFalse(hasattr(d,'received'))
    def test_window_weighted_not_sample_mean(self):
        samples=[(i*.002,.5-max(0,i*.002-.2),0) for i in range(251)]
        self.assertAlmostEqual(h.window_mean_speed(samples,.5),.41)
        samples=[(i*.002,.5,0) for i in range(501)]
        self.assertAlmostEqual(h.window_mean_speed(samples,1.),.5)
    def test_native_gap_sparse_or_single_missing_reject(self):
        dense=[(i*.002,.5,0) for i in range(251)]
        for rows in [[dense[0],dense[-1]],dense[:125]+dense[126:]]:
            with self.subTest(count=len(rows)),self.assertRaises(ValueError):
                h.window_mean_speed(rows,.5)
    def test_window_missing_duplicate_future_or_nonfinite_reject(self):
        for samples in [[(.1,.5,0),(.5,.2,0)],[(0,.5,0),(.4,.2,0)],
                        [(0,.5,0),(.5,.2,0),(.6,.2,0)],[(0,.5,0),(0,.2,0),(.5,.2,0)],
                        [(0,float('nan'),0),(.5,.2,0)]]:
            with self.subTest(samples=samples),self.assertRaises(ValueError): h.window_mean_speed(samples,.5)
    def test_bounded_support(self):
        out=h.compare(row(),row(exit_speed=.3,mean_speed=.3,turn_world_norm=.5,turn_x=.4,turn_y=-.3,duration=27.))
        self.assertEqual(out['verdict'],'BOUNDED_HANDOFF_MECHANISM_SUPPORT')
    def test_manipulation_not_command_claim(self):
        self.assertEqual(h.compare(row(),row())['verdict'],'MANIPULATION_NOT_ESTABLISHED')
    def test_speed_changed_no_position_gain(self):
        self.assertEqual(h.compare(row(),row(mean_speed=.3))['verdict'],'SPEED_CHANGED_NO_POSITION_GAIN')
    def test_error_transfer_time_heading_and_speed_cost_reject(self):
        good=row(mean_speed=.3,exit_speed=.3,turn_world_norm=.5)
        for change in [dict(walk_world_norm=.4),dict(duration=29),dict(turn_x=.5),
                       dict(turn_y=-.5),dict(turn_heading=-.1),dict(exit_speed=.6),dict(physical=False),dict(strict=False)]:
            with self.subTest(change=change):
                self.assertEqual(h.compare(row(),dict(good,**change))['verdict'],'TRADEOFF_NO_JOINT_SUPPORT')
    def test_physical_failure_survives_technical_and_missing(self):
        bad=row(physical=False,strict=False,technical=True,complete=False); del bad['mean_speed']
        out=h.compare(row(),bad)
        self.assertEqual(out['verdict'],'INCONCLUSIVE')
        self.assertTrue(out['physical_failure_observed']); self.assertTrue(out['strict_failure_observed'])
    def test_malformed_fields_not_support(self):
        for field in ['complete','strict','physical','technical','turn_world_norm','mean_speed']:
            for value in [None,'PASS',float('nan')]:
                with self.subTest(field=field,value=value):
                    self.assertEqual(h.compare(row(),row(**{field:value}))['verdict'],'INCONCLUSIVE')
    def test_real_controller_source_call_path_without_model(self):
        # Execute unmodified production _Controller statements, with recording
        # fake base only. Not a full collector or physical equivalence test.
        source=ROOT/'src/g1swarm/transition_learning/env.py'
        tree=ast.parse(source.read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='_Controller')
        scope={'np':np,'Cancelled':RuntimeError,'PAIRS':{('stand','walk_forward')},
               'WINDOW':2.,'QUANTUM_STEPS':50,'BOUNDS':np.array([.1,.06,.12]),'math':math,'tilt':lambda s:0.}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[deepcopy(cls)],type_ignores=[])),str(source),'exec'),scope)
        for arm in ['constant','terminal_schedule']:
            r,d,w,_=wrapper(arm); calls=[]; resets=[]
            r.correction=w; r.abort=NS(is_set=lambda:False)
            r.treatment='deterministic_correction'; r.previous='stand'; r.node_steps=1
            r.node_start=NS(simulation_time=0.); r.resets=0
            r.sim=NS(get_robot_state=lambda:NS(base_position=(7.5,0,0),simulation_time=10.))
            r.base=NS(compute_torques=lambda **kw:calls.append(kw['command'].copy()) or 'fake-torques',reset=lambda:resets.append(1))
            controller=scope['_Controller'](r); controller.reset()
            self.assertEqual(controller.compute_torques(command=np.array([.5,0,0])),'fake-torques')
            self.assertEqual(tuple(calls[-1]),(.5 if arm=='constant' else .375,0.,.07))
            self.assertEqual(r.resets,1); self.assertEqual(resets,[1])
            r.skill='turn'; r.index=2
            controller.compute_torques(command=np.array([0.,0.,-.5]))
            self.assertEqual(tuple(calls[-1]),(0.,0.,-.5))
    def test_no_model_or_simulator_imported(self):
        for name in ['torch','mujoco','gymnasium','g1swarm.simulation.g1_simulation']:
            self.assertNotIn(name,sys.modules)

if __name__=='__main__': unittest.main(verbosity=2)
