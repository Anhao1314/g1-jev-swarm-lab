"""Read-only retained-record acceptance; no simulator or policy imports."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

repo = Path(r'D:\webcodex\mujoco-g1\language-g1-saved-results')
index = Path(r'D:\webcodex\mujoco-g1\evidence\language-first-real-6161176858\evidence-index.json')
pin = 'c3e9a9b9726eaffd14bce07b025ea78c80cbbc5f78ab4811240d282504d99d48'
request = '5404feae6d3b449ab1e1dfbb53cdd387'
sys.path.insert(0, str(repo))
from console.language_v01.saved_results import SavedArchive

before = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
          for name in json.loads(index.read_bytes())['files']}
result, video = SavedArchive(index, pin, request).read()
assert result['run_id'] == 'e709447a946f45e1b91b25942319e178'
assert result['physics_steps'] == 6030 and result['policy_calls'] == 603
assert result['result']['completed_nodes'] == 3
assert result['authority']['consumed'] is True
assert result['authority']['d011'] == 'BLOCKED'
assert result['authority']['original_language_proposal'] == 'DENY'
assert hashlib.sha256(video).hexdigest() == '3f23c28b338936e2beb6fb046cce908509130b7aba018e1966fc69962304316f'
# Retained observer imports NumPy through shared geometry metadata. Importing it
# performs no robot policy inference or physics; eliminating it is not this task.
assert not any(name.split('.')[0] in {'torch', 'mujoco'} for name in sys.modules)
assert before == {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in before}
print(json.dumps({'status': 'PASS', 'request_id': request, 'run_id': result['run_id'],
                  'retained_native_steps': result['physics_steps'], 'retained_policy_calls': result['policy_calls'],
                  'current_native_steps': 0, 'current_policy_calls': 0,
                  'unchanged_pinned_files': len(before), 'video_sha256': result['media']['sha256'],
                  'viewer_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
                  'viewer_source_sha256': hashlib.sha256((repo/'console/language_v01/saved_results.py').read_bytes()).hexdigest()}))
