"""Offline analysis of the approved M1 Nsight Systems SQLite export."""
import collections
import json
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
strings = dict(conn.execute('select id,value from StringIds'))
ranges = list(conn.execute('select text,start,end from NVTX_EVENTS where end is not null order by start'))
kernels = list(conn.execute('select start,end,streamId,shortName from CUPTI_ACTIVITY_KIND_KERNEL'))
copies = list(conn.execute('select start,end,streamId,bytes from CUPTI_ACTIVITY_KIND_MEMCPY'))
runtime = list(conn.execute('select start,end,nameId,returnValue from CUPTI_ACTIVITY_KIND_RUNTIME'))
runtime_launch = list(conn.execute('select start,correlationId from CUPTI_ACTIVITY_KIND_RUNTIME where correlationId is not null'))
kernel_corr = list(conn.execute('select start,end,streamId,shortName,correlationId from CUPTI_ACTIVITY_KIND_KERNEL'))


def union_ns(intervals):
    intervals = sorted(intervals)
    if not intervals:
        return 0
    lo,hi=intervals[0]
    total=0
    for a,b in intervals[1:]:
        if a>hi:
            total+=hi-lo
            lo,hi=a,b
        else:
            hi=max(hi,b)
    return total+hi-lo


for name,start,end in ranges:
    if name not in ('context','expert','serial','Block1','Block2','Expert_10_steps'):
        continue
    kk=[(max(start,a),min(end,b),st,n) for a,b,st,n in kernels if a<end and b>start]
    rr=[(max(start,a),min(end,b),strings.get(n,str(n)),rv) for a,b,n,rv in runtime if a<end and b>start]
    cc=[(max(start,a),min(end,b),st,by) for a,b,st,by in copies if a<end and b>start]
    ki=[(a,b) for a,b,_,_ in kk]
    busy=union_ns(ki)
    if ki:
        active_span=max(b for a,b in ki)-min(a for a,b in ki)
        inside_idle=active_span-busy
    else:
        active_span=inside_idle=0
    by_api=collections.defaultdict(lambda:[0,0])
    for a,b,n,rv in rr:
        by_api[n][0]+=1
        by_api[n][1]+=b-a
    api_top=sorted(by_api.items(),key=lambda kv:kv[1][1],reverse=True)[:8]
    rec=dict(name=name,nvtx_ms=(end-start)/1e6,kernel_count=len(kk),
             kernel_sum_ms=sum(b-a for a,b,_,_ in kk)/1e6,
             kernel_union_ms=busy/1e6,kernel_activity_span_ms=active_span/1e6,
             internal_no_kernel_ms=inside_idle/1e6,
             kernel_streams=dict(collections.Counter(st for _,_,st,_ in kk)),
             memcpy_count=len(cc),memcpy_bytes=sum(by for _,_,_,by in cc),
             runtime_count=len(rr),runtime_nonzero=sum(rv!=0 for *_,rv in rr),
             api_top=[dict(name=n,count=v[0],total_ms=v[1]/1e6) for n,v in api_top],
             longest_api=[dict(name=n,ms=(b-a)/1e6) for a,b,n,rv in sorted(rr,key=lambda r:r[1]-r[0],reverse=True)[:5]])
    print(json.dumps(rec,sort_keys=True))

# CPU NVTX ranges end when calls return, often long before corresponding GPU
# kernels finish. Attribute kernels by launch correlation ID, not by GPU start
# timestamp falling inside a CPU NVTX interval.
for name,start,end in ranges:
    if name not in ('context','expert','serial','Block1','Block2','Expert_10_steps'):
        continue
    ids={cid for t,cid in runtime_launch if start<=t<end}
    kk=sorted((a,b,st,n) for a,b,st,n,cid in kernel_corr if cid in ids)
    if not kk: continue
    rec=dict(name=name,range_start_ns=start,launch_attributed_kernels=len(kk),
             launch_attributed_kernel_sum_ms=sum(b-a for a,b,_,_ in kk)/1e6,
             gpu_start_ns=kk[0][0],gpu_end_ns=max(b for a,b,_,_ in kk),
             gpu_activity_span_ms=(max(b for a,b,_,_ in kk)-kk[0][0])/1e6,
             streams=dict(collections.Counter(st for a,b,st,n in kk)))
    if name in ('expert','Expert_10_steps') and len(kk)==2410:
        names=[n for a,b,st,n in kk]
        rec['ten_repeated_241_kernel_sequences']=all(names[i*241:(i+1)*241]==names[:241] for i in range(10))
        rec['step_kernel_sum_ms']=[sum(b-a for a,b,_,_ in kk[i*241:(i+1)*241])/1e6 for i in range(10)]
    print(json.dumps(dict(launch_attribution=rec),sort_keys=True))
