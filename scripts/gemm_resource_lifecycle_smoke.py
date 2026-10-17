"""One approved no-checkpoint resource/lifecycle/two-stream BF16 smoke."""
import ctypes
import gc
import hashlib
import json
import os
import traceback
from pathlib import Path

import numpy as np
import torch
import flash_rt_gemm_diag as diag

OUT=Path(os.environ['COOVERLAP_RUN_DIR'])
OUT.mkdir(parents=True,exist_ok=False)
result={'status':'INCOMPLETE','checks':[]}

def save():
    with (OUT/'result.json').open('w') as f:
        json.dump(result,f,indent=2);f.flush();os.fsync(f.fileno())

def require(condition,label):
    result['checks'].append({'name':label,'pass':bool(condition)})
    save()
    if not condition:raise AssertionError(label)

def raw(name,tensor):
    data=tensor.detach().contiguous().view(torch.uint8).cpu().numpy().tobytes()
    with (OUT/(name+'.bin')).open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    return dict(shape=list(tensor.shape),dtype=str(tensor.dtype),sha256=hashlib.sha256(data).hexdigest())

def memory():
    free,total=torch.cuda.mem_get_info()
    return dict(cuda_free=free,cuda_total=total,torch_allocated=torch.cuda.memory_allocated(),
        proc={l.split(':')[0]:l.split(':',1)[1].strip() for l in Path('/proc/self/status').read_text().splitlines() if l.startswith(('VmRSS:','VmHWM:'))})

class Attr(ctypes.Structure):
    _fields_=[('type',ctypes.c_int),('device',ctypes.c_int),
              ('devicePointer',ctypes.c_void_p),('hostPointer',ctypes.c_void_p),
              ('reserved',ctypes.c_long*8)]

def main():
    cuda=ctypes.CDLL('libcudart.so')
    cuda.cudaPointerGetAttributes.argtypes=[ctypes.POINTER(Attr),ctypes.c_void_p]
    cuda.cudaPointerGetAttributes.restype=ctypes.c_int
    loaded=Path(diag.__file__).resolve()
    result.update(extension=str(loaded),extension_sha256=hashlib.sha256(loaded.read_bytes()).hexdigest(),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    save()
    require(loaded.parent==Path(os.environ['COOVERLAP_DIAG_ROOT']).resolve()/'lib','isolated_extension_path')
    require(result['extension_sha256']==os.environ['COOVERLAP_DIAG_SHA256'],'isolated_extension_sha256')
    torch.cuda.init()
    result['before']=memory();save()
    runner0=diag.GemmRunner();runner1=diag.GemmRunner()
    resources=[dict(runner0.resource_info()),dict(runner1.resource_info())]
    result.update(resources=resources,after_create=memory(),
                  handle_relation='HANDLE_VALUE_EQUAL' if resources[0]['handle_ptr']==resources[1]['handle_ptr'] else 'HANDLE_VALUE_DIFFERENT')
    save()  # all resource and memory facts are durable before any validation
    intervals=[]
    for i,info in enumerate(resources):
        require(info['workspace_bytes']==268435456,f'runner{i}_workspace_capacity')
        require(bool(info['handle_ptr']),f'runner{i}_host_opaque_handle_nonzero')
        for key,n in [('workspace_ptr',info['workspace_bytes']),('scale_a_ptr',4),('scale_b_ptr',4)]:
            attr=Attr();rc=cuda.cudaPointerGetAttributes(ctypes.byref(attr),ctypes.c_void_p(info[key]))
            entry=dict(owner=f'runner{i}',name=key,ptr=info[key],nbytes=n,
                       cuda_status=rc,memory_type=attr.type,device=attr.device,
                       device_pointer=attr.devicePointer)
            intervals.append(entry);result['device_intervals']=intervals;save()
            require(rc==0 and attr.type==2 and attr.devicePointer==info[key],f'runner{i}_{key}_valid_device_pointer')
    for i,a in enumerate(intervals):
        for b in intervals[i+1:]:
            require(max(a['ptr'],b['ptr'])>=min(a['ptr']+a['nbytes'],b['ptr']+b['nbytes']),a['owner']+'.'+a['name']+'/'+b['owner']+'.'+b['name']+'_disjoint')
    require(result['before']['cuda_free']-result['after_create']['cuda_free']<1536*1024**2,'smoke_memory_growth_bounded')
    require(resources==[dict(runner0.resource_info()),dict(runner1.resource_info())],'addresses_stable_before_gemm')

    s0,s1=torch.cuda.Stream(),torch.cuda.Stream()
    result['streams']=[s0.cuda_stream,s1.cuda_stream];save()
    require(s0.cuda_stream!=s1.cuda_stream and all(result['streams']),'independent_nondefault_streams')
    m=n=k=64
    ah=(np.arange(m*k).reshape(m,k)%7-3).astype(np.float32)
    bh=(np.arange(k*n).reshape(k,n)%5-2).astype(np.float32)
    expected=torch.from_numpy(ah@bh).to(torch.bfloat16)
    with torch.cuda.stream(s0):
        a0=torch.from_numpy(ah).cuda().to(torch.bfloat16);b0=torch.from_numpy(bh).cuda().to(torch.bfloat16);d0=torch.empty((m,n),device='cuda',dtype=torch.bfloat16)
    with torch.cuda.stream(s1):
        a1=torch.from_numpy(ah).cuda().to(torch.bfloat16);b1=torch.from_numpy(bh).cuda().to(torch.bfloat16);d1=torch.empty((m,n),device='cuda',dtype=torch.bfloat16)
    s0.synchronize();s1.synchronize()
    def run(r,a,b,d,s):r.bf16_nn(a.data_ptr(),b.data_ptr(),d.data_ptr(),m,n,k,stream=s.cuda_stream)
    run(runner0,a0,b0,d0,s0);s0.synchronize()
    baseline=d0.cpu().clone();result['baseline']=raw('baseline_bf16',baseline);save()
    require(torch.equal(baseline,expected),'runner0_numeric_reference')
    run(runner1,a1,b1,d1,s1);s1.synchronize()
    result['runner1_sequential']=raw('runner1_sequential_bf16',d1);save()
    require(torch.equal(d1.cpu(),baseline),'runner1_sequential_exact')
    result['iterations']=[]
    for i in range(20):
        run(runner0,a0,b0,d0,s0);run(runner1,a1,b1,d1,s1)
        s0.synchronize();s1.synchronize()
        result['iterations'].append(dict(index=i,runner0=raw(f'iter{i:02d}_runner0',d0),runner1=raw(f'iter{i:02d}_runner1',d1),cuda_last_error=cuda.cudaGetLastError()))
        save()
        require(result['iterations'][-1]['cuda_last_error']==0 and torch.equal(d0.cpu(),baseline) and torch.equal(d1.cpu(),baseline),f'two_stream_iteration_{i}_exact')
    require(resources==[dict(runner0.resource_info()),dict(runner1.resource_info())],'addresses_stable_after_gemm')
    del runner1;gc.collect();torch.cuda.synchronize()
    result['after_runner1_destroy']=memory();save()
    run(runner0,a0,b0,d0,s0);s0.synchronize()
    result['after_destroy_output']=raw('runner0_after_runner1_destroy',d0);save()
    require(torch.equal(d0.cpu(),baseline) and cuda.cudaGetLastError()==0,'runner0_works_after_runner1_destroy')
    del runner0;gc.collect();torch.cuda.synchronize()
    result['after_both_destroy']=memory();result['status']='PASS';save()
    print(json.dumps(result,sort_keys=True),flush=True)

try:
    main()
except BaseException:
    result['status']='FAIL';result['error']=traceback.format_exc();save();raise
