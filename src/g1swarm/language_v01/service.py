"""Small offline composition of retained compiler, validator and grounder.

No issuer, executor or live session is constructed. All decisions deny execution.
Canonical bytes bind proposals, not authority; no hash is an authorization token.
"""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import uuid

from g1swarm.language.compiler import LanguageCompiler, COMPILER_VERSION
from g1swarm.mission.ir import Mission
from g1swarm.mission.validator import MissionValidator
from g1swarm.mission.grounding import CapabilityGrounder
from g1swarm.mission.task_graph import TaskGraph

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
PROTOCOL='experiments/phase2/oracle_mission_runtime_001/protocol_frozen.json'

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')

def digest(value): return hashlib.sha256(value).hexdigest()
def load(path): return json.loads(path.read_text(encoding='utf-8'))

class ContractError(ValueError): pass

class ContractService:
    def __init__(self, evidence_dir=None):
        self._session=uuid.uuid4().hex
        self._records={}
        self._evidence=Path(evidence_dir) if evidence_dir else None
        if self._evidence: self._evidence.mkdir(parents=True,exist_ok=False)
        self._pins=load(HERE/'sources.json')
        self._pin_sha=digest((HERE/'sources.json').read_bytes())
        self._adapter_sha=digest(Path(__file__).read_bytes())
        self._verify_sources()

    def _verify_sources(self):
        if digest((HERE/'sources.json').read_bytes())!=self._pin_sha or digest(Path(__file__).read_bytes())!=self._adapter_sha:
            raise ContractError('PREVIEW_SOURCE_CHANGED_RESTART_REQUIRED')
        for name,expected in self._pins['files'].items():
            if digest((ROOT/name).read_bytes())!=expected:
                raise ContractError('RETAINED_SOURCE_DRIFT:'+name)

    def create(self,text):
        if not isinstance(text,str) or len(text)>512:
            raise ContractError('INPUT_MUST_BE_TEXT_AT_MOST_512_CHARACTERS')
        if len(self._records)>=256:
            raise ContractError('LOCAL_SESSION_CAPACITY_REACHED')
        self._verify_sources()
        request_id=uuid.uuid4().hex
        compiled=LanguageCompiler().compile(text)
        mission=compiled.mission.to_dict() if compiled.success else None
        validation=None; grounded=None; graph=[]
        if mission is not None:
            # Reparse into a private instance: Mission's frozen dataclass is shallow.
            private=Mission.from_dict(json.loads(canonical(mission)))
            validation=MissionValidator().validate(private).to_dict()
            if validation['valid']:
                protocol=load(ROOT/PROTOCOL)['grounding']
                paths=protocol['evidence']
                plan=CapabilityGrounder(
                    risk_map_path=ROOT/paths['risk_map'],
                    boundary_comparison_path=ROOT/paths['boundary_comparison'],
                    capability_map_path=ROOT/paths['capability_map'],
                    historical_limits=protocol['historical'],
                    mode_preference=protocol['mode_preference'],
                ).ground_mission(private)
                grounded=plan.to_dict()
                if plan.grounded:
                    graph=[node.to_dict() for node in TaskGraph.from_mission(private,plan).nodes]
        reasons=['LANGUAGE_RUNTIME_BLOCKED','D011_BLOCKED','OWNER_AUTHORIZATION_ABSENT','LIVE_STATE_NOT_OBSERVED']
        if not compiled.success: reasons.insert(0,'LANGUAGE_'+compiled.status.value)
        elif not validation['valid']: reasons.insert(0,'MISSION_VALIDATION_REJECTED')
        elif grounded['status']!='GROUNDED': reasons.insert(0,grounded['status'])
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        record={
            'schema':'language-to-g1-offline-contract/0.1',
            'request_id':request_id,'created_at':datetime.now(timezone.utc).isoformat(),
            'source':{'text':text,'sha256':digest(text.encode('utf-8'))},
            'compiler':{k:v for k,v in compiled.to_dict().items() if k!='mission'},
            'mission':mission,'validation':validation,'capability':grounded,'task_graph':graph,
            'request_context':{'session_id':self._session,'target':'MUJOCO_PROPOSED_NOT_CONNECTED',
                               'physical_state':'NOT_OBSERVED','principal':'NOT_AUTHENTICATED',
                               'intent':'OFFLINE_CONTRACT_REVIEW_ONLY'},
            'authorization':{'decision':'DENY','reasons':reasons,'language_runtime':'BLOCKED','d011':'BLOCKED',
                             'owner_authorization':'NOT_PRESENT','state_assessment':'NOT_OBSERVED'},
            'execution':{'status':'NOT_EXECUTED','physics_steps':0,'policy_calls':0,'result':None,'replay':None},
            'provenance':{'head_at_request':head,'retained_base':self._pins['base'],
                          'retained_source_hashes':dict(self._pins['files']),
                          'adapter_sha256':digest(Path(__file__).read_bytes()),
                          'source_manifest_sha256':digest((HERE/'sources.json').read_bytes()),
                          'compiler_version':COMPILER_VERSION,'lark_version':importlib.metadata.version('lark'),
                          'capability_scope':'Historical per-skill evidence; not a full mission or live-state qualification',
                          'authority_scope':'No execution issuer/provider; binding is not a permission or signature'}}
        record['binding']={'mission_sha256':digest(canonical(mission)) if mission else None,
                           'request_sha256':digest(canonical(record))}
        record['contract_sha256']=digest(canonical(record))
        frozen=canonical(record)
        if self._evidence:
            with (self._evidence/(request_id+'.json')).open('xb') as stream: stream.write(frozen)
        self._records[request_id]=frozen
        return json.loads(frozen)

    def get(self,request_id):
        if request_id not in self._records: raise KeyError('UNKNOWN_REQUEST')
        return json.loads(self._records[request_id])

    def check(self,request_id,claimed_hash):
        self._verify_sources()
        record=self.get(request_id)
        if not isinstance(claimed_hash,str) or claimed_hash!=record['contract_sha256']:
            raise ContractError('CONTRACT_BINDING_MISMATCH')
        # No grant creation, consumption or dispatch follows even a valid binding.
        result={'request_id':request_id,'contract_sha256':claimed_hash,'binding_valid':True,
                'decision':'DENY','reasons':record['authorization']['reasons'],
                'execution':'NOT_EXECUTED','authority_granted':False}
        if self._evidence:
            with (self._evidence/(request_id+'-check-'+uuid.uuid4().hex+'.json')).open('xb') as stream:
                stream.write(canonical(result))
        return result
