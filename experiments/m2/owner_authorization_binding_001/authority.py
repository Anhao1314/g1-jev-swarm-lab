"""Trusted-serial authorization records and one-use NONPHYSICAL delegation.

The local ledger is trusted, not a hostile-process security boundary. Actual
Owner decisions require independently verified pinned records, not a CLI claim.
There is no Owner record issuance API, production authentication or live backend.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import time

TEST = 'TEST_ONLY_NONPHYSICAL'
OWNER = 'OWNER_REVIEWED_FROZEN_CAMPAIGN'

class AuthorizationError(PermissionError):
    pass

def need(value, reason):
    if not value:
        raise AuthorizationError(reason)

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def write_once(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        with path.open('x',encoding='utf8',newline='\n') as stream:
            json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False)
            stream.write('\n')
    except FileExistsError as exc:
        raise AuthorizationError('AUTHORIZATION_REPLAY_OR_EXISTING_STATE') from exc

def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))

def verify_record(record, binding, *, kind, now=None):
    now = time.time() if now is None else now
    need(set(record) == {'schema_version','kind','decision','record_id','issuer','evidence_ref','issued_at','expires_at','binding'}, 'RECORD_SCHEMA_INVALID')
    need(record['schema_version'] == 1 and record['kind'] == kind and record['decision'] == 'ALLOW_ONCE', 'AUTHORITY_KIND_OR_PERMISSION_MISMATCH')
    need(isinstance(record['record_id'],str) and len(record['record_id']) == 32
         and all(c in '0123456789abcdef' for c in record['record_id']), 'RECORD_ID_INVALID')
    need(canonical(record['binding']) == canonical(binding), 'AUTHORIZATION_BINDING_MISMATCH')
    need(all(type(record[k]) in (int,float) and math.isfinite(record[k]) for k in ('issued_at','expires_at')), 'RECORD_TIME_INVALID')
    need(record['issued_at'] <= now < record['expires_at'] and 0 < record['expires_at']-record['issued_at'] <= 3600, 'AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID')

def verify_owner_record(record, binding, trust):
    verify_record(record,binding,kind=OWNER)
    anchor = trust['owner_records'].get(digest(record))
    need(anchor is not None, 'OWNER_RECORD_NOT_IN_INDEPENDENTLY_REVIEWED_ALLOWLIST')
    need(anchor == {'issuer':record['issuer'],'evidence_ref':record['evidence_ref']} and
         isinstance(record['evidence_ref'],str) and record['evidence_ref'].startswith('https://github.com/Anhao1314/g1-jev-swarm-lab/'), 'OWNER_RECORD_ANCHOR_MISMATCH')
    return {'status':'OWNER_REVIEWED_RECORD_BYTES_VERIFIED','record_sha256':digest(record),
            'production_identity_authenticated':False,'physical_dispatch_enabled':False}

def issue_test_record(binding, *, record_id=None, now=None, ttl_s=300):
    """Explicit fixture issuance only; cannot issue Owner-kind records."""
    now = time.time() if now is None else now
    return {'schema_version':1,'kind':TEST,'decision':'ALLOW_ONCE','record_id':record_id or secrets.token_hex(16),
            'issuer':'NONPHYSICAL_TEST_ISSUER','evidence_ref':'EXPLICIT_TEST_SUBSTITUTE_NOT_OWNER_APPROVAL',
            'issued_at':now,'expires_at':now+ttl_s,'binding':deepcopy(binding)}

class TestLedger:
    """Persistent serial one-shot state; no rollback/refund after interruption."""
    __test__ = False
    def __init__(self, root):
        self.root = Path(root).absolute()

    def issue_test(self,binding,**kwargs):
        need(str(self.root)==binding['ledger'],'LEDGER_BINDING_MISMATCH')
        record=issue_test_record(binding,**kwargs)
        write_once(self.root/'issued'/ (record['record_id']+'.json'),
                   {'kind':TEST,'record_sha256':digest(record),'record':record})
        return deepcopy(record)

    def consume(self, record, binding):
        verify_record(record,binding,kind=TEST)
        need(record['issuer'] == 'NONPHYSICAL_TEST_ISSUER' and record['evidence_ref'] == 'EXPLICIT_TEST_SUBSTITUTE_NOT_OWNER_APPROVAL', 'TEST_ISSUER_MISMATCH')
        need(str(self.root) == binding['ledger'], 'LEDGER_BINDING_MISMATCH')
        issued=self.root/'issued'/(record['record_id']+'.json')
        need(issued.is_file(),'TEST_RECORD_NOT_ISSUED')
        need(read(issued)=={'kind':TEST,'record_sha256':digest(record),'record':record},'TEST_RECORD_TAMPERED')
        claim = self.root / 'claims' / (record['record_id'] + '.json')
        state = {'kind':TEST,'record_sha256':digest(record),'record':deepcopy(record),
                 'supervisor_pid':os.getpid(),'status':'CONSUMED_BEFORE_ADAPTER_LOAD','completed_cells':[]}
        write_once(claim,state)
        return SupervisorLease(self,claim,state)

    def claim_worker(self, packet, binding):
        need(set(packet) == {'claim','index','nonce','supervisor_pid','worker_pid','binding_sha256'}, 'WORKER_PACKET_SCHEMA_INVALID')
        claim = Path(packet['claim']).absolute()
        need(claim.parent == self.root / 'claims' and claim.suffix == '.json' and claim.stem.isalnum(), 'WORKER_CLAIM_PATH_INVALID')
        state = read(claim)
        verify_record(state['record'],binding,kind=TEST)
        need(state['kind'] == TEST and state['record_sha256'] == digest(state['record']) and
             state['supervisor_pid'] == packet['supervisor_pid'] == os.getppid(), 'SUPERVISOR_IDENTITY_MISMATCH')
        need(packet['worker_pid'] == os.getpid() and packet['binding_sha256'] == digest(binding), 'WORKER_IDENTITY_OR_BINDING_MISMATCH')
        index = packet['index']
        need(type(index) is int and 0 <= index < len(binding['cell_order']), 'CELL_INDEX_INVALID')
        campaign = claim.parent / (claim.stem + '-workers')
        need(read(campaign / f'{index}-issued.json') == packet, 'UNISSUED_OR_TAMPERED_WORKER_PERMIT')
        for previous in range(index):
            need((campaign / f'{previous}-completed.json').is_file(), 'PREVIOUS_WORKER_NOT_COMPLETE')
        need(not (campaign / 'closed.json').exists(), 'CAMPAIGN_CLOSED')
        write_once(campaign / f'{index}-used.json', {'kind':TEST,'binding_sha256':digest(binding),'worker_pid':os.getpid()})
        return WorkerLease(campaign,index,deepcopy(binding),deepcopy(packet))

class SupervisorLease:
    def __init__(self, ledger, claim, state):
        self.ledger,self.claim,self.state = ledger,claim,state
        self.campaign = claim.parent / (claim.stem + '-workers')
        self.next_index = 0

    def delegate(self,index,worker_pid):
        need(os.getpid() == self.state['supervisor_pid'] and index == self.next_index, 'SUPERVISOR_OR_CELL_ORDER_MISMATCH')
        need(index < len(self.state['record']['binding']['cell_order']), 'CELL_INDEX_INVALID')
        need(not (self.campaign/'closed.json').exists(), 'CAMPAIGN_CLOSED')
        packet = {'claim':str(self.claim),'index':index,'nonce':secrets.token_hex(32),
                  'supervisor_pid':os.getpid(),'worker_pid':worker_pid,'binding_sha256':digest(self.state['record']['binding'])}
        write_once(self.campaign / f'{index}-issued.json',packet)
        return packet

    def complete(self,index):
        need(index == self.next_index and (self.campaign/f'{index}-backend.json').is_file(), 'BACKEND_OR_ORDER_NOT_COMPLETE')
        write_once(self.campaign/f'{index}-completed.json',{'index':index,'kind':TEST})
        self.next_index += 1

    def close(self,reason):
        write_once(self.campaign/'closed.json',{'kind':TEST,'reason':reason,'completed_cells':self.next_index,'no_retry':True})

class WorkerLease:
    def __init__(self,campaign,index,binding,packet):
        self.campaign,self.index,self.binding,self.packet = campaign,index,binding,packet

    def enter_substitute(self,binding):
        claim=read(self.packet['claim'])
        verify_record(claim['record'],binding,kind=TEST)
        need(claim['record_sha256']==digest(claim['record']),'BACKEND_RECORD_DRIFT')
        need(canonical(binding) == canonical(self.binding) and os.getpid() == self.packet['worker_pid']
             and os.getppid() == self.packet['supervisor_pid'], 'BACKEND_BINDING_OR_PROCESS_MISMATCH')
        need(not (self.campaign/'closed.json').exists(), 'CAMPAIGN_CLOSED')
        need((self.campaign/f'{self.index}-issued.json').is_file() and (self.campaign/f'{self.index}-used.json').is_file(),
             'BACKEND_WITHOUT_VALID_CONSUMED_WORKER_PERMIT')
        need(read(self.campaign/f'{self.index}-issued.json') == self.packet and
             read(self.campaign/f'{self.index}-used.json') == {'kind':TEST,'binding_sha256':digest(binding),'worker_pid':os.getpid()},
             'BACKEND_WITHOUT_VALID_CONSUMED_WORKER_PERMIT')
        # Claim persists even if the double or subsequent reporting fails.
        write_once(self.campaign/f'{self.index}-backend.json',{'kind':TEST,'binding_sha256':digest(binding),'index':self.index})
        return {'status':'NONPHYSICAL_BACKEND_SUBSTITUTE_ONLY','kind':TEST,
                'cell_id':binding['cell_order'][self.index],'binding_sha256':digest(binding),
                'physics_steps':0,'policy_inferences':0,'model_loads':0,'physical_outcome':'NOT_MEASURED'}
