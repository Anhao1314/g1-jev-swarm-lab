"""Current production CLI fails closed before any model/simulator import.

There is deliberately no Owner-approved flag or synthetic mode in this entry.
The component qualification in tests cannot activate this process.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from g1swarm.language_v01.action import require_physical_release

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--preparation',type=Path,required=True)
    parser.add_argument('--readiness',type=Path,required=True)
    parser.add_argument('--readiness-sha256',required=True)
    args=parser.parse_args()
    try:
        document=json.loads(args.preparation.read_bytes())
        require_physical_release(document,args.readiness,args.readiness_sha256)
    except (ValueError,PermissionError,OSError) as exc:
        print(json.dumps({'status':'REFUSED_BEFORE_MODEL_OR_SIMULATOR_CONSTRUCTION','reason':str(exc),
                          'physics_steps':0,'policy_calls':0,'optimizer_updates':0}))
        sys.exit(2)
