"""Offline BF16 and launch-correlated Nsight analysis; never runs CUDA."""
import collections, hashlib, json, pathlib, sqlite3, struct, sys
root=pathlib.Path(sys.argv[1]);run=root/'runs/cooverlap_first_pair_20261014_01'
def diff(a,b):
    x=(run/(a+'.bin')).read_bytes();y=(run/(b+'.bin')).read_bytes()
    assert len(x)==len(y) and len(x)%2==0
    aa=struct.unpack('<'+'H'*(len(x)//2),x);bb=struct.unpack('<'+'H'*(len(y)//2),y)
    n=0;mx=0.;idx=None;rel=0.;nonfinite=0
    import math
    for i,(u,v) in enumerate(zip(aa,bb)):
        p=struct.unpack('<f',struct.pack('<I',u<<16))[0];q=struct.unpack('<f',struct.pack('<I',v<<16))[0]
        nonfinite+=int(not math.isfinite(p))+int(not math.isfinite(q))
        if u!=v:
            n+=1;d=abs(p-q)
            if d>mx:mx=d;idx=i
            rel=max(rel,d/max(abs(q),1e-6))
    return dict(current=a,reference=b,bytes_equal=x==y,elements=len(aa),different=n,ratio=n/len(aa),max_abs=mx,max_rel=rel,max_index=idx,nonfinite=nonfinite)
res={'bf16':[]}
for a,b in [('Pair01_boundary_'+k,'reference_S1_boundary_'+k) for k in ('x','K','V')]+[('Pair01_old_prefix_'+k,'published_v0_'+k) for k in ('x','K','V')]+[('Pair01_Expert_raw_bf16','reference_Expert_S0_raw_bf16')]:res['bf16'].append(diff(a,b))
# Per-layer effective prefix; metadata carries [layers,seq,head,dim,bytes].
res['kv_layers']={}
for k in ('K','V'):
    a=(run/('Pair01_boundary_'+k+'.bin')).read_bytes();b=(run/('reference_S1_boundary_'+k+'.bin')).read_bytes();size=len(a)//9
    res['kv_layers'][k]=[dict(layer=i,equal=a[i*size:(i+1)*size]==b[i*size:(i+1)*size],different_bf16=sum(u!=v for u,v in zip(struct.unpack('<'+'H'*(size//2),a[i*size:(i+1)*size]),struct.unpack('<'+'H'*(size//2),b[i*size:(i+1)*size])))) for i in range(9)]
c=sqlite3.connect(root/'cooverlap_pair_trace_20261014_01/trace.sqlite')
strings=dict(c.execute('select id,value from StringIds'))
ranges=[(t or strings.get(tid),a,b) for t,tid,a,b in c.execute('select text,textId,start,end from NVTX_EVENTS where end is not null')]
kernels=list(c.execute('select start,end,streamId,correlationId from CUPTI_ACTIVITY_KIND_KERNEL'))
runtime=list(c.execute('select start,end,correlationId,nameId,returnValue from CUPTI_ACTIVITY_KIND_RUNTIME'))
def union(xs):
    out=[]
    for a,b in sorted(xs):
        if out and a<=out[-1][1]:out[-1][1]=max(b,out[-1][1])
        else:out.append([a,b])
    return out
def total(xs):return sum(b-a for a,b in xs)
groups={};res['timeline']={}
for name in ('Pair01_Block1','Pair01_Expert'):
    _,lo,hi=next(r for r in ranges if r[0]==name)
    rr=[r for r in runtime if lo<=r[0]<hi];ids={r[2] for r in rr};kk=[r for r in kernels if r[3] in ids];uu=union([(a,b) for a,b,*_ in kk]);groups[name]=uu
    apis=collections.defaultdict(lambda:[0,0])
    for a,b,_,nid,rv in rr:apis[strings.get(nid,str(nid))][0]+=1;apis[strings.get(nid,str(nid))][1]+=b-a
    res['timeline'][name]=dict(kernel_count=len(kk),streams=dict(collections.Counter(r[2] for r in kk)),kernel_sum_ms=sum(b-a for a,b,*_ in kk)/1e6,kernel_union_ms=total(uu)/1e6,span_ms=(uu[-1][1]-uu[0][0])/1e6,no_tracked_kernel_ms=(uu[-1][1]-uu[0][0]-total(uu))/1e6,cpu_nvtx_ms=(hi-lo)/1e6,api_nonzero=sum(r[4]!=0 for r in rr),api_top=[dict(name=k,count=v[0],total_ms=v[1]/1e6) for k,v in sorted(apis.items(),key=lambda x:x[1][1],reverse=True)[:10]])
a,b=groups.values();both=sum(max(0,min(y,v)-max(x,u)) for x,y in a for u,v in b)
res['physical_overlap_ms']=both/1e6;res['all_kernel_union_ms']=total(union(a+b))/1e6
res['all_kernel_streams']=dict(collections.Counter(r[2] for r in kernels))
res['total_kernels']=len(kernels)
(root/'offline_analysis.json').write_text(json.dumps(res,indent=2)+'\n')
print(json.dumps(res,indent=2))
