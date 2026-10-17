"""Offline CPU-only validation of saved tensors; never imports torch/CUDA."""
import json,hashlib,sys,os
from pathlib import Path
import numpy as np

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def main():
    if os.geteuid()==0:raise PermissionError('offline analysis must be ordinary user')
    root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(exist_ok=False)
    files={str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file()}
    (out/'RAW_SHA256.json').write_text(json.dumps(files,indent=2))
    numeric=[];comparisons=[];summaries=[]
    for role in ['calibration','repeat1']:
        d=root/role;r=json.loads((d/'result.json').read_text())
        for p in sorted(d.glob('*.bin')):
            m=json.loads(p.with_suffix('.json').read_text());data=p.read_bytes();dt=np.dtype(m['storage_dtype'])
            if dt==np.dtype('uint8'):
                a=np.frombuffer(data,dtype='<u2');finite=bool(np.all((a&0x7f80)!=0x7f80));logical='BF16 raw little endian'
            else:a=np.frombuffer(data,dtype=dt);finite=bool(np.isfinite(a).all());logical=str(dt)
            ok=files[str(p.relative_to(root))]==m['sha256'] and len(data)==m['nbytes']==int(np.prod(m['shape']))*dt.itemsize and finite
            numeric.append(dict(file=str(p.relative_to(root)),pass_=ok,finite=finite,logical_type=logical,sha256=files[str(p.relative_to(root))]))
        def cmp(name,p,ref):
            aa,bb=p.read_bytes(),ref.read_bytes();exact=aa==bb;row=dict(name=name,exact=exact,bytes=len(aa))
            if not exact:
                def decode(b):return (np.frombuffer(b,dtype='<u2').astype(np.uint32)<<16).view(np.float32)
                a,b=decode(aa),decode(bb);delta=np.abs(a-b);row.update(max_abs=float(delta.max()),max_rel=float((delta/np.maximum(np.abs(b),1e-6)).max()),mismatch_elements=int(np.count_nonzero(a!=b)))
            comparisons.append(row)
        for s in r.get('segments',[]):
            if s['status']!='PASS':continue
            for e in s['experts']:cmp(f'{role}/s{s["id"]}/E{e["id"]}',d/f'seg{s["id"]}_E{e["id"]}_raw.bin',d/'reference_S0_raw_bf16.bin')
            for q in s['refreshes']:
                for tag,reference in [('mid','reference_S1_boundary'),('final','reference_S1')]:
                    for k in ['x','K','V']:cmp(f'{role}/s{s["id"]}/R{q["id"]}/{tag}/{k}',d/f'seg{s["id"]}_R{q["id"]}_{tag}_{k}.bin',d/(reference+'_'+k+'.bin'))
            for k in ['x','K','V']:cmp(f'{role}/s{s["id"]}/old/{k}',d/f'seg{s["id"]}_old_v0_{k}.bin',d/('reference_S0_'+k+'.bin'))
        summaries.append(dict(role=role,status=r['status'],runtime_checks=len(r['checks']),runtime_check_failures=sum(not c['pass_'] for c in r['checks']),runtime_comparisons=len(r.get('comparisons',[])),finished_experts=sum(len(s['experts']) for s in r.get('segments',[])),finished_refreshes=sum(len(s['refreshes']) for s in r.get('segments',[]))))
    cross=[]
    for p in sorted((root/'calibration').glob('reference*.bin')):
        q=root/'repeat1'/p.name
        if q.exists():cross.append(dict(name=p.name,exact=p.read_bytes()==q.read_bytes()))
    result=dict(uid=os.geteuid(),scope='CPU saved-data only, no model run',files_hashed=len(files),tensor_files=len(numeric),tensor_metadata_and_finite_PASS=all(v['pass_'] for v in numeric),comparisons=len(comparisons),saved_comparison_PASS=all(v['exact'] for v in comparisons),cross_process_references=cross,processes=summaries,numeric=numeric,comparison_details=comparisons)
    (out/'AUDIT.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ['numeric','comparison_details']}))
if __name__=='__main__':main()
