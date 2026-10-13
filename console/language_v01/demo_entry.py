"""Sole operator entry. UI has no execute/approve route or test bypass."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from g1swarm.language_v01 import host

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['launch','supervisor','worker','render'])
    parser.add_argument('--preparation',type=Path)
    parser.add_argument('--readiness',type=Path)
    parser.add_argument('--readiness-sha256')
    parser.add_argument('--review',type=Path)
    parser.add_argument('--owner-comment-id',type=int)
    parser.add_argument('--run-directory',type=Path)
    args=parser.parse_args()
    try:
        if args.command=='worker': sys.exit(host.worker(args.run_directory))
        if args.command=='supervisor':
            result=host.supervisor(args.run_directory)
            sys.exit(0 if result['process']['passed'] else 2)
        if args.command=='render': sys.exit(host.render_worker(args.run_directory))
        result=host.launch(args.preparation,args.readiness,args.readiness_sha256,args.review,args.owner_comment_id)
        print(json.dumps(result),flush=True)
        sys.exit(0 if result.get('outer_process',{}).get('passed') and result['status']=='CAPTURE_FINISHED' else 2)
    except (ValueError,PermissionError,OSError,TypeError,KeyError) as exc:
        print(json.dumps({'status':'REFUSED_BEFORE_MODEL_OR_SIMULATOR_CONSTRUCTION','reason':str(exc),
                          'physics_steps':0,'policy_calls':0,'optimizer_updates':0}))
        sys.exit(2)
