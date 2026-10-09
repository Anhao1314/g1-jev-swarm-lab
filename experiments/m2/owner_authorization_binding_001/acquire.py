"""Owner-binding entry: real acquisition disabled; explicit test flow only.

No live backend, policy, simulator or controller is loaded by the positive path.
Original P1 external supervisor/watchdog is reused with stdin delegation added
to its Popen factory. This is not a fake scientific acquisition or raw scoring.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[2]

def module(name,path):
    spec = importlib.util.spec_from_file_location(name,path)
    result = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(),str(path),'exec'),result.__dict__)
    return result

def gate_module():
    return module('owner_entry_gate',HERE/'readiness.py')

def authority_module():
    return module('owner_entry_authority',HERE/'authority.py')

def binding(gate,args):
    receipt = gate.check_target(expected_sha=args.readiness_sha256,execution_head=args.execution_head)
    for path in (args.output,args.ledger):
        gate.require(path is not None,'Unique output and ledger paths required')
        target = gate.helpers()['no_links'](Path(path).absolute())
        gate.require(not target.is_relative_to(ROOT),'Authorization state/output must be outside the source worktree')
    return gate.canonical_binding(receipt,args.output,args.ledger)

def load_frozen_supervisor(gate):
    path = ROOT/gate.ORIGINAL/'acquire.py'
    expected = gate.load(HERE/'source_manifest.json')['files'][path.relative_to(ROOT).as_posix()]
    gate.require(gate.digest(path) == expected,'Frozen P1 supervisor bytes drift')
    return module('owner_frozen_p1_supervisor',path)

def offline_supervisor(gate,auth,args,expected):
    auth.need(args.test_record is not None,'EXPLICIT_TEST_AUTHORIZATION_RECORD_REQUIRED')
    lease = auth.TestLedger(args.ledger).consume(auth.read(args.test_record),expected)
    # Claim is irreversible, including an adapter load or process-launch failure.
    results=[]
    started=time.perf_counter()
    try:
        auth.need(not args.output.exists(),'OUTPUT_ALREADY_EXISTS_NO_RETRY')
        p1 = load_frozen_supervisor(gate)
        args.output.mkdir()
        for index,cell_id in enumerate(expected['cell_order']):
            p1.campaign_wall_guard(started,{'budget':expected['budget']})
            cell_started=time.perf_counter()
            current = binding(gate,args)
            auth.need(auth.canonical(current) == auth.canonical(expected),'SUPERVISOR_SOURCE_OR_BINDING_DRIFT')
            run_dir=args.output/cell_id
            run_dir.mkdir()
            def popen(command,**keywords):
                child=subprocess.Popen(command,stdin=subprocess.PIPE,**keywords)
                try:
                    packet=lease.delegate(index,child.pid)
                    child.stdin.write(auth.canonical(packet)+b'\n')
                    child.stdin.close()
                    return child
                except BaseException:
                    child.kill()
                    child.wait(timeout=10)
                    raise
            p1.subprocess=SimpleNamespace(Popen=popen,TimeoutExpired=subprocess.TimeoutExpired)
            command=[sys.executable,str(HERE/'acquire.py'),'offline-worker','--execution-head',args.execution_head,
                     '--readiness-sha256',args.readiness_sha256,'--output',str(args.output),
                     '--ledger',str(args.ledger),'--cell-index',str(index)]
            # Preserve the original external watchdog and retained failure receipt.
            p1.supervise(command,run_dir,expected['budget']['max_wall_s_per_cell'])
            p1.campaign_wall_guard(started,{'budget':expected['budget']})
            result=auth.read(run_dir/'substitute_result.json')
            auth.need(result['kind']==auth.TEST and result['binding_sha256']==auth.digest(expected)
                      and result['cell_id']==cell_id,'SUBSTITUTE_RESULT_BINDING_MISMATCH')
            lease.complete(index)
            p1.cell_wall_guard(cell_started,{'max_wall_s':expected['budget']['max_wall_s_per_cell']})
            results.append(result)
            print(json.dumps({'event':'offline_worker_completed','index':index,'cell_id':cell_id,'physics_steps':0}),flush=True)
        lease.close('NONPHYSICAL_SIX_CELL_AUTHORIZATION_FLOW_COMPLETE')
        receipt={'status':'PASS_TEST_ONLY_SUPERVISOR_WORKER_BACKEND_FLOW','kind':auth.TEST,'results':results,
                 'binding':expected,'physical_outcomes':'NOT_MEASURED','physics_steps':0,'policy_inferences':0,'model_loads':0}
        auth.write_once(args.output/'authorization_flow.json',receipt)
        return receipt
    except BaseException as exc:
        lease.close(type(exc).__name__+': '+str(exc))
        if args.output.exists():
            auth.write_once(args.output/'authorization_flow_failed.json',{'kind':auth.TEST,'reason':type(exc).__name__+': '+str(exc),
                'classification':'AUTHORIZATION_DENIED_NONPHYSICAL' if isinstance(exc,auth.AuthorizationError) else 'TECHNICAL_INTERRUPTION_NONPHYSICAL',
                'completed_workers':len(results),'no_retry':True})
        raise

def offline_worker(gate,auth,args,expected):
    auth.need(args.cell_index is not None,'DIRECT_WORKER_WITHOUT_DELEGATION')
    auth.need(not sys.stdin.isatty(),'DIRECT_WORKER_WITHOUT_SUPERVISOR_PIPE')
    raw=sys.stdin.read(65537)
    auth.need(0 < len(raw) <= 65536,'WORKER_DELEGATION_MISSING_OR_OVERSIZE')
    packet=json.loads(raw)
    auth.need(packet['index']==args.cell_index,'WORKER_CLI_CELL_MISMATCH')
    lease=auth.TestLedger(args.ledger).claim_worker(packet,expected)
    cell_id=expected['cell_order'][args.cell_index]
    run_dir=args.output/cell_id
    auth.need(run_dir.is_dir() and sorted(p.name for p in run_dir.iterdir())==['worker.log'],'WORKER_DIRECTORY_NOT_PRISTINE')
    current=binding(gate,args)  # Repeat identity immediately before substitute seam.
    result=lease.enter_substitute(current)
    auth.write_once(run_dir/'substitute_result.json',result)
    return result

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('preflight','acquire','worker','offline-supervisor','offline-worker'))
    parser.add_argument('--execution-head',required=True)
    parser.add_argument('--readiness-sha256',required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--ledger',type=Path)
    parser.add_argument('--owner-record',type=Path)
    parser.add_argument('--test-record',type=Path)
    parser.add_argument('--authorize-physics',action='store_true')
    parser.add_argument('--cell-index',type=int)
    args=parser.parse_args(argv)
    gate=gate_module()
    receipt=gate.check_target(expected_sha=args.readiness_sha256,execution_head=args.execution_head)
    if args.command=='preflight':
        print(json.dumps(receipt,sort_keys=True,indent=2))
        return receipt
    expected=binding(gate,args)
    auth=authority_module()
    if args.command in ('acquire','worker'):
        auth.need(args.owner_record is not None,'REAL_OWNER_AUTHORIZATION_MISSING_CLI_FLAG_INSUFFICIENT')
        auth.verify_owner_record(auth.read(args.owner_record),expected,gate.load(HERE/'owner_trust.json'))
        raise auth.AuthorizationError('REAL_PHYSICAL_DISPATCH_NOT_ENABLED_IN_THIS_ENGINEERING_FREEZE')
    auth.need(not args.authorize_physics and args.owner_record is None,'TEST_SUBSTITUTE_CANNOT_REQUEST_OWNER_PHYSICS')
    if args.command=='offline-supervisor':
        result=offline_supervisor(gate,auth,args,expected)
    else:
        auth.need(args.test_record is None,'DIRECT_WORKER_CANNOT_SELF_AUTHORIZE')
        result=offline_worker(gate,auth,args,expected)
    print(json.dumps(result,sort_keys=True))
    return result

if __name__=='__main__':
    main()
