"""Executable TEST_ONLY confirmation example; no model, no Runtime."""
import json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src')); os.environ['G1SWARM_ROOT']=str(ROOT)
from g1swarm.authority_release_001 import begin_release_request
from g1swarm.human_principal_001 import TestPrincipalAuthority
from g1swarm.language.errors import CompilerStatus
from g1swarm.language.result import CompilerResult
from g1swarm.mission.ir import Mission
from g1swarm.source_authority import apply_gate
class NeverConsulted:
    def authorize(self,*a,**kw): raise AssertionError('No model/source verifier')
source='向前走一些，然后停下来'
mission=Mission.from_dict({'schema_version':'2.0.0','mission_id':'TEST_ONLY_explicit_human_plan','steps':[{'id':'s1','skill':'walk_forward','parameters':{'distance_m':8.0}},{'id':'s2','skill':'stop','parameters':{},'depends_on':['s1']}]})
baseline=CompilerResult(CompilerStatus.SUCCESS,mission,source)
service=TestPrincipalAuthority(); session=service.create_test_session('TEST_ONLY_alice')
context=begin_release_request(source)
offer=service.present(source,mission,context,session)
# A real authenticated human and trustworthy display are NOT present in this demo.
confirmation=service.respond(session,offer,displayed_sha256=offer.display_sha256,action='CONFIRM')
result=apply_gate(source,baseline,NeverConsulted(),request_context=context,principal_authority=service,principal_confirmation=confirmation,allow_test_principal=True)
assert result.success and result.mission is mission
assert result.diagnostics['source_authorization']['status']=='UNKNOWN'
print(json.dumps({'presentation':offer.to_dict(),'confirmation':confirmation.to_dict(),'result':result.to_dict(),'audit':service.audit_events()},ensure_ascii=False,indent=2))
