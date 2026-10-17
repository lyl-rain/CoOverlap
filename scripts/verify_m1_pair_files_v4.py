"""Offline exact audit of every saved paired output, including old KV protection."""
import hashlib,json,re,sys
from pathlib import Path
def verify(root):
    root=Path(root);rows=[];integrity=[]
    for p in sorted(root.glob('*.json')):
        m=json.loads(p.read_text())
        if not isinstance(m,dict) or not {'shape','storage_dtype','nbytes','sha256'}<=m.keys():continue
        data=p.with_suffix('.bin').read_bytes();ok=len(data)==m['nbytes'] and hashlib.sha256(data).hexdigest()==m['sha256'];integrity.append(dict(name=p.stem,pass_=ok))
        if not ok:raise ValueError('paired raw integrity failed '+p.stem)
        name=p.stem
        if not re.match(r'^pair_(gate|formal)_(ordinary|serial|fixed|return)_[0-2]_',name):continue
        if '_boundary_' in name:ref='reference_S1_boundary_'+name.rsplit('_',1)[1]
        elif '_final_' in name:ref='reference_S1_'+name.rsplit('_',1)[1]
        elif '_old_' in name:ref='reference_S0_'+name.rsplit('_',1)[1]
        elif name.endswith('_Expert_raw_bf16'):ref='reference_S0_raw_bf16'
        elif name.endswith('_Expert_actions'):ref='reference_S0_actions'
        else:raise ValueError('unknown paired output '+name)
        meta=json.loads((root/(ref+'.json')).read_text())
        rows.append(dict(name=name,reference=ref,exact=data==(root/(ref+'.bin')).read_bytes() and m['shape']==meta['shape'] and m['storage_dtype']==meta['storage_dtype']))
    return dict(status='PASS' if len(rows)==143 and all(x['exact'] for x in rows) else 'FAIL',integrity_files=len(integrity),paired_comparisons=len(rows),comparisons=rows,integrity=integrity)
if __name__=='__main__':
    from m1_run_identity import require_analysis_user
    require_analysis_user();r=verify(sys.argv[1]);Path(sys.argv[2]).open('x').write(json.dumps(r,indent=2))
    if r['status']!='PASS':raise SystemExit(1)
