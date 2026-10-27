import ast,inspect,json,os,socket,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()))
import pi05_m3_b5_anchors as entry
import m3_b5_control as ctrl
from m3_b5_plan import PROTOCOL,RESULT_STATUS,GATE_PLAN,budget,protocol
import validate_m3_b5_cpu as tests

class PrepareSentinel(Exception): pass
base=Path.cwd().resolve()
package=ctrl.package_files(base)
with tempfile.TemporaryDirectory(prefix='cooverlap-b5-r1-cpu-') as tmp:
 run=Path(tmp).resolve();pre=run/'PREFLIGHT.json';out=run/'model'
 pre.write_text(json.dumps(dict(host=socket.gethostname(),base=str(base),run=str(run),protocol=PROTOCOL,created=time.time(),package=package,sources={})))
 argv=['pi05_m3_b5_anchors.py','--approved-m3-b5-boundary-budget-anchors-v1','--config',str(base/'CONFIG.json'),'--out',str(out),'--reference',str(base/'reference'),'--source-preflight',str(pre)]
 reached=[]
 def stop(*a,**kw): reached.append(True);raise PrepareSentinel('CPU sentinel before any model preparation')
 with patch('sys.argv',argv),patch.dict(os.environ,{'COOVERLAP_APPROVED_BATCH':PROTOCOL}),patch.object(entry,'prepare',stop):
  try:entry.main()
  except PrepareSentinel:pass
 result=json.loads((out/'result.json').read_text())
 assert reached and 'torch' not in sys.modules
 assert result['status']=='FAIL_OR_INCOMPLETE' and result['protocol']['id']==PROTOCOL
 assert result['interpretation'].startswith('two-anchor boundary-priority mechanism check')
 assert len(result['segments'])==8 and sorted({s['period_ns'] for s in result['segments']})==[180000000,240000000]
# Success identity is inspected without running the model branch.
tree=ast.parse(inspect.getsource(entry.main));status_values=[]
for n in ast.walk(tree):
 if isinstance(n,ast.Assign) and any(isinstance(t,ast.Subscript) and isinstance(t.value,ast.Name) and t.value.id=='report' and isinstance(t.slice,ast.Constant) and t.slice.value=='status' for t in n.targets):
  if isinstance(n.value,ast.Name): status_values.append(n.value.id)
assert status_values==['RESULT_STATUS'] and entry.RESULT_STATUS==RESULT_STATUS=='PASS_IN_PROCESS_BOUNDARY_BUDGET_ANCHORS'
# A regression to the old two-block gate budget must fail the new contract test.
from m2_clean_core import gate_retention_layout
from m3_b3_plan import CONTROL
caught=False
with patch('m3_b5_plan.gate_retention_layout',side_effect=lambda cycles,plan:gate_retention_layout(cycles,CONTROL)):
 try: tests.ProtocolTests('test_gate_budget_matches_the_entry_plan').test_gate_budget_matches_the_entry_plan()
 except AssertionError: caught=True
assert caught
print(json.dumps(dict(status='PASS_CPU_ENTRY_AND_GATE_BUDGET_AUDIT',valid_B5_credential_reached_prepare_sentinel=True,no_torch_import=True,success_identity=RESULT_STATUS,interpretation=result['interpretation'],old_two_block_gate_budget_regression_caught=True,config_equals_protocol=json.loads((base/'CONFIG.json').read_text())==protocol(),deployment_manifest_entries=len(package),model_starts=0,ssh=0,hardware_writes=0,scopes=0),indent=2))
