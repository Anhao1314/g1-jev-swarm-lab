"""Reuse the byte-pinned PR25 exclusive metadata freeze, never grant authority."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[2]
BASE = '8adef9f6f6a89f93c9c225b92b3b7fc90430693a'
if __name__ == '__main__':
    path = ROOT / 'experiments/m2/acquisition_entry_binding_001/freeze_sources.py'
    raw = path.read_bytes()
    assert raw == subprocess.check_output(['git','show',BASE+':'+path.relative_to(ROOT).as_posix()],cwd=ROOT)
    spec = importlib.util.spec_from_file_location('owner_freeze_immutable_pr25',path)
    old = importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),old.__dict__)
    old.HERE = HERE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code-head',required=True)
    print(json.dumps(old.freeze(parser.parse_args().code_head),indent=2))
