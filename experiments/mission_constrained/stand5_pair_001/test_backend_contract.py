"""Execute exact production nested adapters with synthetic objects, no runtime imports."""
import ast
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
import math

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import contract as c
from rule import select

def production_node(name):
    tree=ast.parse((HERE/'backend.py').read_text())
    execute=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='execute')
    return deepcopy(next(n for n in execute.body if getattr(n,'name',None)==name))

def extract_function(name,scope):
    node=production_node(name)
    node.body=[n for n in node.body if not isinstance(n,ast.Nonlocal)]
    # Only lexical binding changes; execute the frozen production statements.
    if name=='native': node.body.insert(0,ast.Global(names=['native_attempts']))
    module=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
    exec(compile(module,str(HERE/'backend.py'),'exec'),scope)
    return scope[name]

class BackendTests(unittest.TestCase):
    def test_native_return_count_before_postcheck(self):
        b=c.Budget(10,clock=lambda:0)
        scope={'budget':b,'native_attempts':0,'original_native':lambda *a:None}
        native=extract_function('native',scope); native(None,None)
        self.assertEqual((scope['native_attempts'],b.steps),(1,1))
    def test_native_error_leaves_unknown(self):
        b=c.Budget(10,clock=lambda:0)
        def fail(*args): raise RuntimeError('injected native error')
        scope={'budget':b,'native_attempts':0,'original_native':fail}
        with self.assertRaises(RuntimeError): extract_function('native',scope)(None,None)
        self.assertEqual((scope['native_attempts'],b.steps),(1,0))
    def test_native_multistep_refused(self):
        scope={'budget':c.Budget(10,clock=lambda:0),'native_attempts':0,'original_native':lambda *a:None}
        with self.assertRaises(RuntimeError): extract_function('native',scope)(None,None,2)
        self.assertEqual(scope['native_attempts'],0)
    def test_control_error_retained_then_raised(self):
        evidence=[]
        def fail(*a,**k): raise ValueError('invalid command')
        scope={'budget':c.Budget(10,clock=lambda:0),'original_compute':fail,
               'record_error':lambda stage,exc:evidence.append([stage,type(exc).__name__])}
        with self.assertRaises(ValueError): extract_function('compute',scope)(None)
        self.assertEqual(evidence,[['controller_compute','ValueError']])
    def test_nonfinite_after_native_retained(self):
        import numpy as np
        observed={'nonfinite':False,'fallen':False}; evidence=[]
        def fail(*args): raise RuntimeError('non-finite state')
        scope={'np':np,'budget':c.Budget(10,clock=lambda:0),'original_step':fail,'observed':observed,
               'record_error':lambda stage,exc:evidence.append(stage)}
        sim=NS(_data=NS(qpos=np.array([float('nan')]),qvel=np.zeros(1)))
        with self.assertRaises(RuntimeError): extract_function('step',scope)(sim)
        self.assertTrue(observed['nonfinite']); self.assertEqual(evidence,['simulation_step'])
    def runner(self,destination,arm,entry=None):
        import numpy as np
        v=c.read(c.HISTORY/'predecision.json') if entry is None else entry
        calls=[]
        class Base:
            def __init__(self,*args,**kwargs):
                self.index=1; self.skill='walk_forward'; self.alpha=.5
                self.node_start=NS(base_position=v['robot_state']['base_position'],to_dict=lambda:v['robot_state'])
                self.frame=NS(initial_yaw_rad=v['walking_reference']['measurement_heading_rad'])
                self.planned_heading=v['planned_heading_rad']; self.planned_origin=np.array(v['planned_origin'])
                self.sim=NS(_data=NS(time=v['simulation_time_s'],qpos=np.array(v['qpos']),qvel=np.array(v['qvel']),ctrl=np.array(v['ctrl']),xfrc_applied=np.zeros(6)))
                self.base=NS(_policy='synthetic'); self.correction=NS(delegate='frozen-controller')
                self.router=NS(execute=lambda request,context:calls.append(self.index) or NS(status=NS(value='SUCCESS'),reason='',metrics={}))
        node=production_node('Runner')
        scope={'hist':NS(AcquisitionRunner=Base,tensor_digest=lambda p:v['policy_tensors_sha256']),
               'case':{},'destination':destination,'deadline':10,'arm':arm,'errors':[],
               'math':math,'np':np,'select':select,'read':c.read,'write':c.write,'paired_entry':c.paired_entry,
               'FixedAlphaCorrectionPolicy':lambda r,a,d:NS(alpha=a,delegate=d)}
        # Preserve enclosing nonlocal semantics with a tiny synthetic factory.
        wrapper=ast.FunctionDef(name='factory',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),
            body=[ast.Assign(targets=[ast.Name(id='runner',ctx=ast.Store())],value=ast.Constant(None)),node,
                  ast.Return(value=ast.Call(func=ast.Name(id='Runner',ctx=ast.Load()),args=[],keywords=[]))],decorator_list=[])
        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper],type_ignores=[])),str(HERE/'backend.py'),'exec'),scope)
        return scope['factory'](),calls
    def test_selected_preserves_object_and_persists(self):
        with tempfile.TemporaryDirectory() as t:
            runner,calls=self.runner(Path(t),'selected'); original=runner.correction
            runner.router.execute(None,None); runner.index=3; runner.router.execute(None,None)
            self.assertIs(runner.correction,original); self.assertEqual(calls,[1,3]); self.assertEqual(runner.selection['applied_alpha'],.5)
    def test_fixed_pair_gate_before_walk(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t); (p/'selected').mkdir(); (p/'fixed').mkdir()
            old=c.read(c.HISTORY/'predecision.json'); c.write(p/'selected/predecision.json',old)
            bad=deepcopy(old); bad['qvel'][0]+=.001
            runner,calls=self.runner(p/'fixed','fixed',bad)
            with self.assertRaisesRegex(RuntimeError,'PAIRED_ENTRY'): runner.router.execute(None,None)
            self.assertEqual(calls,[])
    def test_fixed_matched_pair_uses_existing_formula_object(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t); (p/'selected').mkdir(); (p/'fixed').mkdir()
            c.write(p/'selected/predecision.json',c.read(c.HISTORY/'predecision.json'))
            runner,calls=self.runner(p/'fixed','fixed'); runner.router.execute(None,None)
            self.assertEqual(runner.correction.alpha,.25); self.assertEqual(calls,[1])

if __name__=='__main__': unittest.main(verbosity=2)
