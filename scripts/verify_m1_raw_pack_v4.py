"""Full streaming integrity and exact reference audit after all model processes."""
import hashlib,json,sys,time
from pathlib import Path
def verify(root):
    root=Path(root);index=root/'RAW_INDEX.jsonl';pack=root/'RAW_TENSORS.bin'
    refs={};rows=[];offset=0;names=set();beg=time.monotonic()
    with pack.open('rb') as f:
        for line in index.open():
            m=json.loads(line);name=m['name']
            if name in names or m['offset']!=offset:raise ValueError('duplicate name or noncontiguous raw pack index')
            names.add(name);data=f.read(m['nbytes']);offset+=len(data)
            if len(data)!=m['nbytes'] or hashlib.sha256(data).hexdigest()!=m['sha256']:raise ValueError('raw tensor integrity failed '+name)
            if '_E' in name and name.endswith('_raw'):ref='reference_S0_raw_bf16'
            elif '_E' in name and name.endswith('_actions'):ref='reference_S0_actions'
            elif '_R' in name and '_mid_' in name:ref='reference_S1_boundary_'+name.rsplit('_',1)[1]
            elif '_R' in name and '_final_' in name:ref='reference_S1_'+name.rsplit('_',1)[1]
            elif '_old_v0_' in name:ref='reference_S0_'+name.rsplit('_',1)[1]
            else:raise ValueError('unknown timed raw tensor name '+name)
            if ref not in refs:refs[ref]=((root/(ref+'.bin')).read_bytes(),json.loads((root/(ref+'.json')).read_text()))
            rb,rm=refs[ref];exact=data==rb and m['shape']==rm['shape'] and m['storage_dtype']==rm['storage_dtype']
            rows.append(dict(name=name,nbytes=m['nbytes'],sha256=m['sha256'],reference=ref,byte_shape_dtype_exact=exact))
        trailing=f.read(1)
    return dict(status='PASS' if all(x['byte_shape_dtype_exact'] for x in rows) and not trailing else 'FAIL',all_saved_tensors=len(rows),raw_bytes=offset,trailing_unindexed_bytes=bool(trailing),wall_s=time.monotonic()-beg,rows=rows,scope='every saved packed timed tensor; missing/unfinished jobs are NOT_RUN/INCOMPLETE, not inferred PASS')
if __name__=='__main__':
    from m1_run_identity import require_analysis_user
    require_analysis_user();r=verify(sys.argv[1]);Path(sys.argv[2]).open('x').write(json.dumps(r,separators=(',',':')))
    if r['status']!='PASS':raise SystemExit(1)
