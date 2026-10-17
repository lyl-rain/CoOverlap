"""Offline only: raw-file integrity, exact intra-process and absolute cross gates."""
import hashlib,json,sys,os,re,math
from pathlib import Path
import numpy as np
from m1_dual_gate import evaluate

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(8*1024*1024),b''):h.update(c)
    return h.hexdigest()
def main():
    if os.geteuid()==0:raise PermissionError('ordinary-user analysis only')
    batch=Path(sys.argv[1]);frozen=Path(sys.argv[2]);out=Path(sys.argv[3]);out.mkdir(exist_ok=False)
    hashes={str(p.relative_to(batch)):digest(p) for p in batch.rglob('*') if p.is_file()}
    (out/'RAW_SHA256.json').write_text(json.dumps(hashes,indent=2));runs=[]
    for role in ('calibration','repeat1','repeat2','repeat3','trace'):
        d=batch/role
        if not (d/'result.json').exists():runs.append(dict(role=role,status='NOT_RUN_OR_NO_RESULT'));continue
        r=json.loads((d/'result.json').read_text());files=[];checks=[]
        for p in d.glob('*.bin'):
            meta=json.loads(p.with_suffix('.json').read_text());data=p.read_bytes();dt=np.dtype(meta['storage_dtype'])
            if dt==np.dtype('uint8'):
                if 'valid_encoder_len' in p.name:arr=np.frombuffer(data,dtype='<i4');finite=True;kind='int32 bytes'
                else:arr=np.frombuffer(data,dtype='<u2');finite=bool(np.all((arr&0x7f80)!=0x7f80));kind='BF16 raw bytes'
            else:arr=np.frombuffer(data,dtype=dt);finite=bool(np.isfinite(arr).all());kind=str(dt)
            ok=hashes[str(p.relative_to(batch))]==meta['sha256'] and len(data)==meta['nbytes']==math.prod(meta['shape'])*dt.itemsize and finite
            files.append(dict(file=p.name,pass_=ok,finite=finite,decoded_kind=kind))
        def exact(name,expected):
            p=d/(name+'.json');ref=d/(expected+'.json')
            if not p.exists():checks.append(dict(name=name,pass_=False,reason='missing required saved tensor'));return
            a,b=json.loads(p.read_text()),json.loads(ref.read_text());checks.append(dict(name=name,pass_=a['sha256']==b['sha256'] and a['shape']==b['shape'] and a['storage_dtype']==b['storage_dtype']))
        for seg in r.get('segments',[]):
            if seg['status']!='PASS':continue
            for j in range(seg['cycles']):
                exact(f'seg{seg["id"]}_E{j}_raw','reference_S0_raw_bf16');exact(f'seg{seg["id"]}_E{j}_actions','reference_S0_actions')
            for q in range(seg['cycles']//2):
                for tag,ref in [('mid','reference_S1_boundary'),('final','reference_S1')]:
                    for key in ('x','K','V'):exact(f'seg{seg["id"]}_R{q}_{tag}_{key}',ref+'_'+key)
            for key in ('x','K','V'):exact(f'seg{seg["id"]}_old_v0_{key}','reference_S0_'+key)
        cross=[]
        for stem,kind,shape in [('reference_S0_raw_bf16','bf16',[50,32]),('reference_S0_actions','f32',[50,7])]:
            p=d/(stem+'.bin')
            if p.exists():cross.append(dict(name=stem,**evaluate(p.read_bytes(),(frozen/(stem+'.bin')).read_bytes(),kind,shape,shape)))
        runs.append(dict(role=role,status=r['status'],tensor_count=len(files),integrity_finite_PASS=all(v['pass_'] for v in files),in_process_saved_exact_PASS=all(v['pass_'] for v in checks) if checks else None,in_process_saved_comparisons=len(checks),runtime_failed_checks=[v for v in r['checks'] if not v['pass_']],cross_process_absolute=cross,numerical_policy=r.get('numerical_policy'),norm_stats_sha256=r.get('norm_stats_sha256'),static_conditions=r.get('Expert_static_conditions'),tensor_details=files,exact_details=checks))
    result=dict(scope='CPU offline only; no new model or CUDA context',files_hashed=len(hashes),runs=runs)
    (out/'AUDIT.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(files_hashed=len(hashes),runs=[{k:v for k,v in s.items() if k not in ('tensor_details','exact_details','static_conditions')} for s in runs]),indent=2))
if __name__=='__main__':main()
