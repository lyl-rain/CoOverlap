"""Offline saved failure audit only; no Torch/CUDA/model import."""
import csv,hashlib,json,re,sys
from pathlib import Path
import numpy as np
from review_pair_close_saved_v5 import difference
from m1_frequency_condition import assess,read_root_samples
sha=lambda b:hashlib.sha256(b).hexdigest()
base=Path(sys.argv[1]);run=base/'board/v6r_20261016T111847Z_f83a865c';out=run/'pair';r=json.loads((out/'result.json').read_text());m=json.loads((base/'deployment/unified_reference/MANIFEST.json').read_text())
old=base;diff={}
for k in ('x','K','V'):
    a=(out/f'reference_Expert_pre_Context_{k}.bin').read_bytes();b=(old/f'frozen_old_{k}.bin').read_bytes()
    assert sha(b)==m['tensor_metadata']['reference_S0_'+k]['sha256']
    diff[k]=difference(a,b);shape=(561,2048) if k=='x' else (18,561,1,256);diff[k]['logical_shape']=shape;diff[k]['max_position']=list(np.unravel_index(diff[k]['max_position_flat'],shape))
    if k!='x':
        n=len(a)//18;diff[k]['per_layer_byte_exact']=[a[i*n:(i+1)*n]==b[i*n:(i+1)*n] for i in range(18)]
exact={'input_fixture_metadata':r['inputs']==m['inputs'],'actual_uploaded_images':sha((out/'actual_upload_images.bin').read_bytes())==m['preprocessed_image_sha256'],'actual_noise_readback':sha((out/'reference_Expert_pre_noise.bin').read_bytes())==m['inputs']['noise_sha256']}
for k in ('S0_language','S1_language'):exact[k]=json.loads((out/(k+'.json')).read_text())==m['tensor_metadata'][k]
for k in ('S0','S1'):exact['actual_state_'+k]=sha((out/('actual_fixture_state_'+k+'.bin')).read_bytes())==m['inputs'][k+'_sha256']
integrity=[]
for p in out.glob('*.json'):
    v=json.loads(p.read_text())
    if isinstance(v,dict) and {'shape','storage_dtype','nbytes','sha256'}<=v.keys():
        b=p.with_suffix('.bin').read_bytes();integrity.append(dict(name=p.stem,pass_=len(b)==v['nbytes'] and sha(b)==v['sha256']))
manifest=json.loads((run/'BOARD_RAW_SHA256.json').read_text());back=[]
for p,v in manifest['files'].items():
    f=run/p;back.append(dict(path=p,match=f.exists() and sha(f.read_bytes())==v['sha256']))
assert all(v['match'] for v in back)
rows=read_root_samples(run/'hardware.jsonl');root_rows=read_root_samples(run/'clock.telemetry.jsonl');a=json.loads((run/'ATTEMPTS.json').read_text())[0]
frequency=assess(rows,root_rows,a['started_ns'],a['ended_ns'])
ledger=r['ledger'];print(json.dumps(ledger,indent=2))
autos=re.findall(r'autotune: tested (\d+) algos, best=(\d+) \(([^)]+) us\)',(run/'pair.log').read_text())
with (base/'AUTOTUNE_CURRENT.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['order','runner_by_call_order','candidate_count','best_index','measured_us','causality'])
 for i,(n,b,t) in enumerate(autos):w.writerow([i,i//18,n,b,t,'UNKNOWN; timing-selected indices do not prove cause'])
result=dict(status='FAIL_CROSS_PROCESS_CONTEXT_BEFORE_EXPERT',root_cause='UNKNOWN',first_observed_gate='final S0 encoder_x before Expert; not first faulty operator',differences=diff,input_exact=exact,raw_integrity=integrity,all_raw_integrity_pass=all(v['pass_'] for v in integrity),backup=dict(files=len(back),bytes=manifest['bytes'],all_sha_match=all(v['match'] for v in back),unreadable=manifest['unreadable']),frequency=frequency,hardware=dict(samples=len(rows),temp_min_mC=min(v['temp_mC'] for v in rows),temp_max_mC=max(v['temp_mC'] for v in rows),memory_available_min_kB=min(v['MemAvailable_kB'] for v in rows)),model_attempts=[a],actual_work=dict(Contexts=1,Experts=0,Vision_layers=27,Encoder_layers=18,Decoder_layers=0,SM_probes=0,Autotunes_completed=2),not_run=dict(Contexts=20,Experts=20,pair_gate=1,normal_pairs=12,collector_reference=1,diagnostic_pairs=4),autotune_records=len(autos),pre_Expert_gate=r['Context_pre_Expert_gate'],cuda_error='no CUDA exception reported; no extra live cudaGetLastError collected after process exit',overlap='UNKNOWN_NO_TRACE; not zero overlap')
# Normalize NumPy scalars from unravel_index; values remain diagnostic only.
(base/'OFFLINE_SAVED_REVIEW.json').write_text(json.dumps(result,indent=2,default=int))
print(json.dumps({k:result[k] for k in ('status','differences','input_exact','frequency','hardware','actual_work','autotune_records')},indent=2,default=int))
