"""One no-checkpoint resource-query smoke for isolated GemmRunner build."""
import ctypes
import atexit
import gc
import hashlib
import json
import os
from pathlib import Path

import flash_rt_gemm_diag as diag

root=Path(os.environ['COOVERLAP_DIAG_ROOT']).resolve()
loaded=Path(diag.__file__).resolve()
assert loaded.parent == root/'lib', loaded
out=Path(os.environ['COOVERLAP_RUN_DIR'])
out.mkdir(parents=True,exist_ok=False)
cuda=ctypes.CDLL('libcudart.so')
cuda.cudaMemGetInfo.argtypes=[ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)]
cuda.cudaMemGetInfo.restype=ctypes.c_int

class Attr(ctypes.Structure):
    _fields_=[('type',ctypes.c_int),('device',ctypes.c_int),
              ('devicePointer',ctypes.c_void_p),('hostPointer',ctypes.c_void_p),
              ('reserved',ctypes.c_long*8)]

cuda.cudaPointerGetAttributes.argtypes=[ctypes.POINTER(Attr),ctypes.c_void_p]
cuda.cudaPointerGetAttributes.restype=ctypes.c_int

def check(rc):
    if rc: raise RuntimeError(f'CUDA status {rc}')

def memory():
    free,total=ctypes.c_size_t(),ctypes.c_size_t()
    check(cuda.cudaMemGetInfo(ctypes.byref(free),ctypes.byref(total)))
    return dict(cuda_free=free.value,cuda_total=total.value,
        proc_status={l.split(':')[0]:l.split(':',1)[1].strip() for l in Path('/proc/self/status').read_text().splitlines() if l.startswith(('VmRSS:','VmHWM:'))})

result=dict(extension=str(loaded),extension_sha256=hashlib.sha256(loaded.read_bytes()).hexdigest(),before=memory(),status='INCOMPLETE')
def save_evidence():
    (out/'resources.json').write_text(json.dumps(result,indent=2))
atexit.register(save_evidence)
runners=[diag.GemmRunner(),diag.GemmRunner()]
resources=[dict(r.resource_info()) for r in runners]
result['resources']=resources
result['after_create']=memory()
save_evidence()
print(json.dumps(dict(resources=resources,after_create=result['after_create']),sort_keys=True),flush=True)
intervals=[]
for i,info in enumerate(resources):
    assert info['workspace_bytes']==256*1024*1024
    assert info['handle_ptr'] and info['workspace_ptr']
    for key,nbytes in [('workspace_ptr',info['workspace_bytes']),('scale_a_ptr',4),('scale_b_ptr',4)]:
        a=Attr();check(cuda.cudaPointerGetAttributes(ctypes.byref(a),ctypes.c_void_p(info[key])))
        assert a.type==2 and a.devicePointer==info[key]
        intervals.append((info[key],info[key]+nbytes,f'runner{i}.{key}'))
        result['device_intervals']=intervals
        save_evidence()
result['device_intervals']=intervals
for i,(a,b,name) in enumerate(intervals):
    for c,d,name2 in intervals[i+1:]: assert max(a,c)>=min(b,d),(name,name2)
assert resources[0]['handle_ptr'] != resources[1]['handle_ptr']
assert resources==[dict(r.resource_info()) for r in runners]
check(cuda.cudaDeviceSynchronize());check(cuda.cudaGetLastError())
del runners
gc.collect()
check(cuda.cudaDeviceSynchronize())
result['after_release']=memory()
result['status']='PASS'
save_evidence()
print(json.dumps(result,sort_keys=True),flush=True)
