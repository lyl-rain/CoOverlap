"""Read-only Pair01 token/head/channel statistics and launch-correlated trace map.
Writes only a new output directory. No CUDA imports or execution.
"""
import argparse, collections, csv, hashlib, json, pathlib, sqlite3
import numpy as np
ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--out',required=True);args=ap.parse_args()
src=pathlib.Path(args.source);out=pathlib.Path(args.out);out.mkdir(parents=True,exist_ok=False)
run=src/'runs/cooverlap_first_pair_20261014_01'
expected=json.loads((src/'REMOTE_RUN_SHA256.json').read_text())
assert all(hashlib.sha256((run/k).read_bytes()).hexdigest()==v for k,v in expected.items())
summary={'raw_hash_verified':len(expected),'segments':[], 'similarity':[], 'shifts':[], 'anomalies':[]}
segments=[('view1',0,256),('view2',256,512),('language_state',512,561)]
def load(name,shape):
    raw=(run/(name+'.bin')).read_bytes();meta=json.loads((run/(name+'.json')).read_text())
    assert hashlib.sha256(raw).hexdigest()==meta['sha256'] and len(raw)==int(np.prod(shape))*2
    u=np.frombuffer(raw,dtype='<u2').reshape(shape)
    return u,(u.astype('<u4')<<16).view('<f4')
def stat(u,x,v,y):
    mask=u!=v;d=np.abs(x.astype(np.float64)-y.astype(np.float64));pos=np.unravel_index(int(np.argmax(d)),d.shape)
    return dict(elements=u.size,different=int(mask.sum()),ratio=float(mask.mean()),max_abs=float(d.max()),mean_abs=float(d.mean()),rms=float(np.sqrt(np.mean(d*d))),max_rel=float(np.max(d/np.maximum(np.abs(y),1e-6))),max_index=list(map(int,pos)),nonfinite=int((~np.isfinite(x)).sum()),reference_nonfinite=int((~np.isfinite(y)).sum()),current_zero=int((x==0).sum()),reference_zero=int((y==0).sum()))
tokens=[];channels=[]
for kind,shape in [('x',(1,561,2048)),('K',(9,561,256)),('V',(9,561,256))]:
    u,x=load('Pair01_boundary_'+kind,shape);v,y=load('reference_S1_boundary_'+kind,shape)
    su,sy=load('Serial_boundary_'+kind,shape);assert np.array_equal(su,v)
    for layer in range(shape[0]):
        for seg,lo,hi in segments:
            rec=dict(kind=kind,layer=8 if kind=='x' else layer,segment=seg,head='hidden_channels_not_attention_heads' if kind=='x' else 'KV_head_0',**stat(u[layer,lo:hi],x[layer,lo:hi],v[layer,lo:hi],y[layer,lo:hi]));summary['segments'].append(rec)
            mm=u[layer,lo:hi]!=v[layer,lo:hi];dd=np.abs(x[layer,lo:hi].astype(float)-y[layer,lo:hi])
            for ch in range(shape[2]):channels.append(dict(kind=kind,layer=rec['layer'],segment=seg,channel=ch,different=int(mm[:,ch].sum()),ratio=float(mm[:,ch].mean()),max_abs=float(dd[:,ch].max())))
        for t in range(561):tokens.append(dict(kind=kind,layer=8 if kind=='x' else layer,token=t,segment=next(s for s,lo,hi in segments if lo<=t<hi),**stat(u[layer,t],x[layer,t],v[layer,t],y[layer,t])))
        summary['anomalies'].append(dict(kind=kind,layer=8 if kind=='x' else layer,all_zero_rows=np.where(np.all(x[layer]==0,axis=1))[0].tolist(),reference_all_zero_rows=np.where(np.all(y[layer]==0,axis=1))[0].tolist(),all_zero_channels=np.where(np.all(x[layer]==0,axis=0))[0].tolist(),reference_all_zero_channels=np.where(np.all(y[layer]==0,axis=0))[0].tolist(),unchanged_rows=np.where(np.all(u[layer]==v[layer],axis=1))[0].tolist(),fully_different_rows=np.where(np.all(u[layer]!=v[layer],axis=1))[0].tolist()))
    # Finite candidate comparisons: old S0 matching layer, S1 later-layer residue.
    candidates=[('old_S0','published_v0_'+kind,(1,561,2048) if kind=='x' else (18,561,256)),('S1_after_Block2','Serial_new_context_'+kind,(1,561,2048) if kind=='x' else (18,561,256))]
    for label,name,cs in candidates:
        cu,cy=load(name,cs)
        pairs=[(0,0)] if kind=='x' else ([(i,i) for i in range(9)] if label=='old_S0' else [(i,i+9) for i in range(9)])
        for i,j in pairs:summary['similarity'].append(dict(kind=kind,current_layer=i,candidate_layer=j,candidate=label,**stat(u[i],x[i],cu[j],cy[j])))
    for shift in (0,-256,-2,-1,1,2,256):
        lo=max(0,-shift);hi=min(561,561-shift)
        summary['shifts'].append(dict(kind=kind,token_shift=shift,**stat(u[:,lo:hi],x[:,lo:hi],v[:,lo+shift:hi+shift],y[:,lo+shift:hi+shift])))
for name,rows in [('token_diff.csv',tokens),('channel_diff.csv',channels)]:
    with (out/name).open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
# Timeline: attribute by Runtime launch correlation, never clip to CPU NVTX.
c=sqlite3.connect(f'file:{src}/cooverlap_pair_trace_20261014_01/trace.sqlite?mode=ro',uri=True)
strings=dict(c.execute('select id,value from StringIds'))
rr=list(c.execute('select start,end,correlationId,nameId from CUPTI_ACTIVITY_KIND_RUNTIME'))
ranges={t or strings.get(tid):(a,b) for t,tid,a,b in c.execute('select text,textId,start,end from NVTX_EVENTS where end is not null')}
kk=list(c.execute('select start,end,streamId,shortName,demangledName,correlationId from CUPTI_ACTIVITY_KIND_KERNEL'))
def group(name):
    a,b=ranges[name];ids={cid for t,_,cid,_ in rr if a<=t<b}
    return sorted([k for k in kk if k[-1] in ids])
a,b=group('Pair01_Block1'),group('Pair01_Expert');assert len(a)==465 and len(b)==2410
origin=a[0][0]
vision_ops=['norm1','QKV_GEMM','QKV_bias','QKV_split','FA2','attn_out_GEMM','bias_residual1','norm2','FFN_up','FFN_bias','GELU','FFN_down','bias_residual2']
enc_ops=['RMSNorm1','QKV_GEMM','QKV_split_RoPE_KV_write','FA2','attn_out_GEMM','residual1','RMSNorm2','FFN_gate','FFN_up','SiLU_mul','FFN_down','residual2']
def mapping(i):
    if i<3:return 'Vision_init',-1,['patch_im2col','patch_embedding_GEMM','patch_bias_position'][i]
    if i<354:return 'Vision',(i-3)//13,vision_ops[(i-3)%13]
    if i<357:return 'Projection',-1,['vision_final_norm','projector_GEMM','projector_bias'][i-354]
    return 'Encoder',(i-357)//12,enc_ops[(i-357)%12]
rows=[];overlaps=[];stages=collections.defaultdict(list)
for i,(t,e,st,n,d,cid) in enumerate(a):
    stage,layer,op=mapping(i);name=strings[n]
    if stage=='Vision':
        required={'norm1':'layer_norm','norm2':'layer_norm','QKV_split':'qkv_split_kernel','FA2':'flash_fwd_kernel','GELU':'gelu_kernel'}
        if op in required:assert required[op] in name,(i,name,op)
    if stage=='Encoder':
        required={'RMSNorm1':'rms_norm','RMSNorm2':'rms_norm','QKV_split_RoPE_KV_write':'qkv_split_rope','FA2':'flash_fwd','residual1':'res_add','residual2':'res_add','SiLU_mul':'gate_silu_mul'}
        if op in required:assert required[op] in name,(i,name,op)
    hits=[]
    for j,(bt,be,bs,bn,bd,bcid) in enumerate(b):
        lo,hi=max(t,bt),min(e,be)
        if hi>lo:
            hits.append((lo,hi));overlaps.append(dict(A_index=i,A_stage=stage,A_layer=layer,A_op=op,A_kernel=name,A_start_ns=t,A_end_ns=e,B_index=j,B_kernel=strings[bn],B_start_ns=bt,B_end_ns=be,overlap_start_ms=(lo-origin)/1e6,overlap_end_ms=(hi-origin)/1e6,overlap_ms=(hi-lo)/1e6))
    rows.append(dict(index=i,stage=stage,layer=layer,op=op,name=name,demangled=strings[d],stream=st,correlation_id=cid,start_ns=t,end_ns=e,start_ms=(t-origin)/1e6,end_ms=(e-origin)/1e6,expert_overlap_ms=sum(y-x for x,y in hits)/1e6))
    stages[(stage,layer)].append(rows[-1])
for name,values in [('kernel_stage_map.csv',rows),('kernel_intersections.csv',overlaps)]:
    with (out/name).open('w') as f:w=csv.DictWriter(f,fieldnames=list(values[0]));w.writeheader();w.writerows(values)
summary['timeline']=dict(origin_ns=origin,expert_first_ns=b[0][0],expert_first_ms=(b[0][0]-origin)/1e6,expert_first_kernel=strings[b[0][3]],A_streams=sorted({k[2] for k in a}),B_streams=sorted({k[2] for k in b}),overlap_ms=sum(r['overlap_ms'] for r in overlaps),stages=[dict(stage=s,layer=l,start_ms=v[0]['start_ms'],end_ms=v[-1]['end_ms'],overlap_ms=sum(x['expert_overlap_ms'] for x in v)) for (s,l),v in stages.items()],language_memcpy=[dict(start_ns=t,end_ns=e,name=strings[n],relative_cpu_start_ms=(t-origin)/1e6) for t,e,cid,n in rr if ranges['Pair01_Block1'][0]<=t<ranges['Pair01_Block1'][1] and 'Memcpy' in strings[n]])
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(dict(verified=len(expected),segments=len(summary['segments']),kernel_map=len(rows),intersections=len(overlaps),overlap_ms=summary['timeline']['overlap_ms']),indent=2))
