"""Offline tests only: retained arrays, stdlib fake workers, no backend import."""
import ast
from copy import deepcopy
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as c
import run
import rule

class GateTests(unittest.TestCase):
    def test_rule_hash(self):
        self.assertEqual(c.sha(HERE/'rule.py'),'1797e0e457483226335f99b9c51330b22822c4fe6daa7f94ecf0b17b8e55917b')
    def test_protocol_hash(self):
        self.assertEqual(c.sha(HERE/'protocol.json'),'9882e8204985465ed559949fa3b1a7e7251222036d40fa796a46ae3d931cbef2')
    def test_original_entry_selection(self):
        v=c.read(c.HISTORY/'predecision.json'); yaw=v['walking_reference']['measurement_heading_rad']
        self.assertEqual(rule.select(v['qpos'][:2],yaw,0,[8,0])['alpha'],.5)
    def test_budget_cap_before_dispatch(self):
        b=c.Budget(10,clock=lambda:0,maximum=1); b.before_step(); b.completed_step()
        with self.assertRaisesRegex(RuntimeError,'BUDGET'): b.before_step()
        self.assertEqual(b.steps,1)
    def test_deadline_before_dispatch(self):
        with self.assertRaises(RuntimeError): c.Budget(1,clock=lambda:1).before_step()
    def test_physical_failure_not_erased_by_partial(self):
        self.assertTrue(c.physical_failure([{'physical_success':False}]))
    def test_exact_reject_bool_number(self):
        self.assertFalse(c.exact(True,1))
    def test_pair_excludes_only_reference(self):
        a=c.read(c.HISTORY/'predecision.json'); b=deepcopy(a)
        b['walking_reference']['control_heading_rad']+=.1
        self.assertTrue(c.paired_entry(a,b))
        b['qvel'][0]+=1e-12
        self.assertFalse(c.paired_entry(a,b))
    def test_pair_missing_rejected(self):
        self.assertFalse(c.paired_entry({},{}))
    def test_unauthorized_entry_before_preflight(self):
        with patch.object(run,'preflight',side_effect=AssertionError('should not reach')):
            with self.assertRaises(PermissionError): run.acquire(None,None,None,False)
    def test_direct_cli_denied_without_live_import(self):
        result=subprocess.run([sys.executable,'-B',str(HERE/'run.py'),'worker'],capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('backend.py',result.stderr)
    def test_preflight_is_stdlib(self):
        # This clean process proves static entry inspection does not load runtime.
        code="import sys; sys.path.insert(0,"+repr(str(HERE))+"); import run; assert not {'torch','mujoco','numpy','backend'} & sys.modules.keys()"
        self.assertEqual(subprocess.run([sys.executable,'-B','-c',code],timeout=10).returncode,0)
    def test_owner_assertion_not_authentication(self):
        self.assertIn('not human authentication',(HERE/'run.py').read_text())
    def test_no_shared_source_edits(self):
        diff=subprocess.check_output(['git','diff','--name-only','4e2a51bf'],cwd=c.ROOT,text=True)
        self.assertTrue(all(n.startswith('experiments/mission_constrained/stand5_pair_001/') for n in diff.splitlines()))
    def test_backend_no_top_level_runtime_import(self):
        tree=ast.parse((HERE/'backend.py').read_text())
        names=[n.names[0].name for n in tree.body if isinstance(n,ast.Import)]
        self.assertFalse(set(names)&{'torch','numpy','mujoco'})

class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)
        for p in c.HISTORY.iterdir():
            if p.suffix=='.gz': (self.path/p.stem).write_bytes(gzip.decompress(p.read_bytes()))
            elif p.is_file(): shutil.copyfile(p,self.path/p.name)
    def tearDown(self): self.temp.cleanup()
    def change(self,name,update):
        v=c.read(self.path/name); update(v); (self.path/name).write_text(json.dumps(v))
    def test_complete_history_self_comparison(self):
        self.assertTrue(c.replay_checks(self.path)['passed'])
    def test_wall_and_run_identity_only(self):
        self.change('result.json',lambda v:v.update(wall_time_s=0,run_id='new'))
        self.assertTrue(c.replay_checks(self.path)['passed'])
    def test_strict_change_rejected(self):
        self.change('result.json',lambda v:v['nodes'][1].update(strict_success=False))
        self.assertFalse(c.replay_checks(self.path)['passed'])
    def test_small_float_drift_rejected(self):
        self.change('predecision.json',lambda v:v['qvel'].__setitem__(0,v['qvel'][0]+1e-14))
        self.assertFalse(c.replay_checks(self.path)['passed'])
    def test_stream_hash_change_rejected(self):
        self.change('audit.json',lambda v:v['streams']['commands'].update(sha256='0'*64))
        self.assertFalse(c.replay_checks(self.path)['passed'])
    def test_active_not_ignored(self):
        p=self.path/'trace.jsonl'; v=c.rows(p); v[0]['active']=not v[0]['active']
        p.write_text('\n'.join(json.dumps(x) for x in v))
        self.assertFalse(c.replay_checks(self.path)['passed'])
    def test_missing_trace_sample_rejected(self):
        p=self.path/'trace.jsonl'; p.write_text('\n'.join(p.read_text().splitlines()[1:]))
        self.assertFalse(c.replay_checks(self.path)['passed'])
    def test_pose_change_rejected(self):
        import numpy as np
        p=self.path/'poses.npz'
        with np.load(p,allow_pickle=False) as data: v={k:data[k].copy() for k in data.files}
        v['qpos'][0,0]+=1e-14; np.savez_compressed(p,**v)
        self.assertFalse(c.replay_checks(self.path)['passed'])
    def test_identical_outcome_no_claim(self):
        v=c.read(self.path/'result.json')
        self.assertEqual(c.compare_outcomes(v,v)['verdict'],'NO_JOINT_SUPPORT')

class ProcessTests(unittest.TestCase):
    def run_synthetic(self,code,budget=5):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t); result=run.supervise([sys.executable,'-B','-c',code],p,time.perf_counter()+budget)
            self.assertEqual(result,c.read(p/'process_receipt.json'))
            return result
    def test_synthetic_child_success(self):
        self.assertTrue(self.run_synthetic("print('synthetic_no_physics')")['passed'])
    def test_crash_retained(self):
        r=self.run_synthetic('raise RuntimeError("injected")')
        self.assertFalse(r['passed']); self.assertTrue(r['reaped'])
    def test_timeout_reaped(self):
        r=self.run_synthetic('import time; time.sleep(30)',budget=2.3)
        self.assertTrue(r['timed_out']); self.assertTrue(r['reaped']); self.assertFalse(r['passed'])
    def test_spawn_failure_retained(self):
        with tempfile.TemporaryDirectory() as t:
            with patch.object(run.subprocess,'Popen',side_effect=OSError('injected spawn failure')):
                r=run.supervise([sys.executable,'-B','-c','pass'],Path(t),time.perf_counter()+5)
            self.assertFalse(r['passed']); self.assertIn('exception',r)

if __name__=='__main__': unittest.main(verbosity=2)
