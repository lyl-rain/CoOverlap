"""Offline byte-exact validation; does not promote a timed-out model process."""
from pathlib import Path
import hashlib,json,sys
p=Path(sys.argv[1]);raw=p/'raw/cooverlap_period_obligations_20261015_01';result=json.loads((raw/'result.json').read_text());checks=[]
def check(a,b):
 aa=(raw/(a+'.bin')).read_bytes();bb=(raw/(b+'.bin')).read_bytes();meta=json.loads((raw/(a+'.json')).read_text())
 assert len(aa)==meta['nbytes'] and hashlib.sha256(aa).hexdigest()==meta['sha256'] and aa==bb
 checks.append(dict(actual=a,reference=b,byte_exact=True,nbytes=len(aa)))
for s in result['segments']:
 i=s['id']
 for j in range(8):check(f'seg{i}_E{j}_raw','reference_S0_raw_bf16')
 for q in range(4):
  for k in ['x','K','V']:
   check(f'seg{i}_R{q}_final_{k}','reference_S1_'+k)
   if s['plan']=='two_blocks':check(f'seg{i}_R{q}_mid_{k}','reference_S1_boundary_'+k)
 for k in ['x','K','V']:check(f'seg{i}_old_v0_{k}','reference_S0_'+k)
initial=json.loads((raw/'address_manifest_before.json').read_text());after=json.loads((raw/'seg3_resources.json').read_text())
assert not after['overlaps']
assert {v['name']:(v['ptr'],v['nbytes']) for v in initial['writable']}=={v['name']:(v['ptr'],v['nbytes']) for v in after['writable']}
report=dict(status='PASS_FOR_SAVED_TENSORS_ONLY',count=len(checks),raw_tensor_comparisons=checks,last_segment_visible_address_stable=True,not_recovered=['seg3 final live S0/S1 language readback','seg3 validated memory checkpoint','clean observer close and normal exit'],process_and_segment3_stay_INCOMPLETE=True)
print(json.dumps(report,indent=2))
