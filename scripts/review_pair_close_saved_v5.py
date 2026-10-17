"""Saved evidence only. Never imports Torch or initializes CUDA."""
import hashlib,json,re,sys
from pathlib import Path
import numpy as np
from m1_frequency_condition import assess,read_root_samples

def digest(b):return hashlib.sha256(b).hexdigest()
def difference(a,b,bf16=True):
    if len(a)!=len(b):raise ValueError('stored size mismatch')
    dtype='<u2' if bf16 else '<f4';aa=np.frombuffer(a,dtype=dtype);bb=np.frombuffer(b,dtype=dtype)
    if bf16:x=(aa.astype('<u4')<<16).view('<f4');y=(bb.astype('<u4')<<16).view('<f4')
    else:x,y=aa,bb
    delta=np.abs(x-y);idx=int(np.argmax(delta));eq=aa==bb
    return dict(byte_exact=a==b,nbytes=len(a),elements=len(aa),different_elements=int(np.count_nonzero(~eq)),
        different_fraction=float(np.mean(~eq)),max_abs=float(delta[idx]),max_position_flat=idx,reference_at_max=float(y[idx]),current_at_max=float(x[idx]),
        max_relative=float(np.max(delta/np.maximum(np.abs(y),1e-6))),relative_definition='abs(current-reference)/max(abs(reference),1e-6), diagnostic only, not a gate',
        NaN_current=int(np.isnan(x).sum()),Inf_current=int(np.isinf(x).sum()),NaN_reference=int(np.isnan(y).sum()),Inf_reference=int(np.isinf(y).sum()),
        current_sha256=digest(a),reference_sha256=digest(b),dtype='BF16 little-endian u16 shifted16 -> float32' if bf16 else 'little-endian float32')

def main(base):
    base=Path(base);board=base/'board';run=next(board.glob('results_*'));out=run/'pair'
    r=json.loads((out/'result.json').read_text());manifest=json.loads((board/'unified_reference/MANIFEST.json').read_text())
    diff={}
    for name in ('x','K','V'):
        a=(out/f'reference_S0_{name}.bin').read_bytes();b=(base/f'frozen_old_{name}.bin').read_bytes()
        if digest(b)!=manifest['tensor_metadata']['reference_S0_'+name]['sha256']:raise ValueError('comparison baseline not the frozen reference')
        diff[name]=difference(a,b)
        if name!='x':
            n=len(a)//18;diff[name]['per_layer_byte_exact']=[a[i*n:(i+1)*n]==b[i*n:(i+1)*n] for i in range(18)]
    for name,bf16 in [('raw_bf16',True),('actions',False)]:
        diff[name]=difference((out/f'reference_S0_{name}.bin').read_bytes(),(board/f'unified_reference/reference_S0_{name}.bin').read_bytes(),bf16)
    exact={}
    for name in ('S0_language','S1_language'):
        exact[name]=json.loads((out/(name+'.json')).read_text())==manifest['tensor_metadata'][name]
    exact['actual_noise']=digest((out/'reference_Expert_pre_noise.bin').read_bytes())==manifest['inputs']['noise_sha256']
    exact['fixture']=r['inputs']==manifest['inputs']
    exact['images']=r['preprocessed_image_sha256']==manifest['preprocessed_image_sha256']
    for k in ('x','K','V'):
        exact['Expert_pre_'+k]=json.loads((out/f'reference_Expert_pre_Context_{k}.json').read_text())==manifest['tensor_metadata']['reference_S0_'+k]
    integrity=[]
    for p in out.glob('*.json'):
        m=json.loads(p.read_text())
        if isinstance(m,dict) and {'shape','storage_dtype','nbytes','sha256'}<=m.keys():
            b=p.with_suffix('.bin').read_bytes();integrity.append(dict(name=p.stem,pass_=len(b)==m['nbytes'] and digest(b)==m['sha256']))
    raw=json.loads((board/'BOARD_RAW_SHA256.json').read_text());backup=[]
    for path,m in raw['files'].items():
        p=board/path;backup.append(dict(path=path,match=p.exists() and digest(p.read_bytes())==m['sha256']))
    attempts=json.loads((run/'ATTEMPTS.json').read_text());a=attempts[0]
    hw=[json.loads(l) for l in (run/'hardware.jsonl').read_text().splitlines()]
    freq=assess(hw,read_root_samples(board/'clock_before_v5_scope01.telemetry.jsonl'),a['started_ns'],a['ended_ns'])
    return dict(status='FAIL_CROSS_PROCESS_CONTEXT_EXACT_GATE',root_cause='UNKNOWN',first_observed_failure='reference_S0 final encoder_x; not a first faulty operator',
        differences=diff,offline_input_exact=exact,integrity=integrity,raw_integrity_pass=all(x['pass_'] for x in integrity),
        backup=dict(files=len(backup),matches=sum(x['match'] for x in backup),files_detailed=backup,unreadable=raw['unreadable'],bytes=sum(m['nbytes'] for m in raw['files'].values())),
        frequency=freq,hardware=dict(samples=len(hw),temp_min_mC=min(x['temp_mC'] for x in hw),temp_max_mC=max(x['temp_mC'] for x in hw),available_min_kB=min(x['MemAvailable_kB'] for x in hw)),
        attempts=attempts,actual_ledger=dict(Contexts=1,Experts=1,Encoder_layers=18,Decoder_layers=180,SM_probes=0,Autotune='two original per-slot runners completed'),
        unexecuted=dict(Contexts=19,Experts=18,normal_samples=12,diagnostic_samples=4,pair_gate_samples=1,reason='mandatory Context exact gate stopped before S1 reference and sequential gate'),
        kernel_overlap='UNKNOWN_NO_PAIR_TRACE',numerical_gate='FAIL; Expert-only tolerance cannot override Context byte-exact failure')
if __name__=='__main__':
    base=Path(sys.argv[1]);r=main(base);(base/'OFFLINE_SAVED_REVIEW.json').open('x').write(json.dumps(r,indent=2))
    print(json.dumps({k:r[k] for k in ('status','differences','offline_input_exact','frequency','hardware','actual_ledger')},indent=2))
