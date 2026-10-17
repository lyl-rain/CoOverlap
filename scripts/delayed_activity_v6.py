"""Small late-loaded observation facade. No Torch/CUDA/CUPTI import at startup.

The shared activity adapter must be built against the actual installed CUPTI
headers from its official example. It is not loaded until normal samples drain.
"""
import contextlib,ctypes,hashlib,json,os,time
from pathlib import Path
class Collector:
    def __init__(self,path,expected_sha,out):
        path=Path(path)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected_sha:raise RuntimeError('collector binary SHA mismatch')
        self.out=Path(out);self.out.mkdir(exist_ok=False);self.ids={};self.next_id=1;self.active=False
        self.lib=ctypes.CDLL(str(path)) # called only in stage C
        self.lib.m1_library_path.restype=ctypes.c_char_p
        actual_library=Path(self.lib.m1_library_path().decode()).resolve()
        library_sha=hashlib.sha256(actual_library.read_bytes()).hexdigest()
        self.lib.m1_abi.restype=ctypes.c_char_p;self.lib.m1_runtime_version.restype=ctypes.c_int
        self.abi=json.loads(self.lib.m1_abi().decode());self.runtime_version=self.lib.m1_runtime_version()
        meta=dict(path=str(actual_library),sha256=library_sha,adapter_abi=self.abi,runtime_version=self.runtime_version)
        (self.out/'LIBRARY_ABI.json').write_text(json.dumps(meta,indent=2))
        if library_sha!=os.environ['COOVERLAP_CUPTI_LIBRARY_SHA256'] or self.runtime_version!=self.abi['CUPTI_API_VERSION']:raise RuntimeError('late CUPTI library/ABI differs from reviewed build')
        for name,args in [('m1_start',[]),('m1_stop',[ctypes.c_char_p]),('m1_push',[ctypes.c_uint64]),('m1_pop',[])]:
            fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=ctypes.c_int
    def start(self):
        rc=self.lib.m1_start()
        if rc:
            self.lib.m1_stop(str(self.out/'activity_start_failure.jsonl').encode())
            raise RuntimeError('collector start error '+str(rc))
        self.active=True
    @contextlib.contextmanager
    def phase(self,name):
        if name not in self.ids:self.ids[name]=self.next_id;self.next_id+=1
        rc=self.lib.m1_push(self.ids[name])
        if rc:raise RuntimeError('external correlation push error '+str(rc))
        try:yield
        finally:
            rc=self.lib.m1_pop()
            if rc:raise RuntimeError('external correlation pop error '+str(rc))
    def stop(self):
        if not self.active:return
        try:
            rc=self.lib.m1_stop(str(self.out/'activity.jsonl').encode())
            if rc:raise RuntimeError('collector flush/export error '+str(rc))
        finally:
            self.active=False
            p=self.out/'PHASE_IDS.json'
            with p.open('x') as f:json.dump(self.ids,f,indent=2);f.flush();os.fsync(f.fileno())
