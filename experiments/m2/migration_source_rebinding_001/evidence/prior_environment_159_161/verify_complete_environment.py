import hashlib,json,runpy,sys
from pathlib import Path
root=Path(r'D:\webcodex\mujoco-g1\main-codex');out=Path(r'D:\webcodex\mujoco-g1\environment-acceptance-3082e2b-20261009')
r=runpy.run_path(str(root/'experiments/m2/unseen_halt_hold_p1_repair_001/readiness.py'))
rows=r['verify_assets']();xml=r['xml_resources']();actual=r['dependency_check']();source_count=r['verify_sources']()
expected=r['load'](root/'experiments/m2/unseen_halt_hold_p1_repair_001/dependencies.json')
fields={k:{'frozen':expected[k],'actual':actual[k]} for k in expected if expected[k]!=actual[k]}
report={'status':'ASSETS_SOURCES_DEPENDENCY_VERSIONS_MATCH_BUT_FROZEN_ORIGIN_MISMATCH','source_count':source_count,'official_asset_count':len(rows),'official_asset_bytes':sum(v['bytes'] for v in rows),'asset_rows':rows,'xml_documents':len(xml['xml_documents']),'xml_resources':len(xml['resource_links']),'dependency_versions_match':expected['packages']==actual['packages'],'dependency_count':len(actual['packages']),'interpreter_match':expected['executable']==actual['executable'],'actual_dependency_metadata':actual,'frozen_dependency_fields_different':fields,'forbidden_imports_present':[x for x in r['FORBIDDEN_IMPORTS'] if x in sys.modules],'physics_steps':0,'policy_inferences':0,'model_loads':0}
assert source_count==438 and len(rows)==91 and not report['forbidden_imports_present']
(out/'full-source-assets-dependencies.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k not in ['asset_rows','actual_dependency_metadata','frozen_dependency_fields_different']},indent=2))
print('DEPENDENCY_DIFF_FIELDS='+str(list(fields)))
