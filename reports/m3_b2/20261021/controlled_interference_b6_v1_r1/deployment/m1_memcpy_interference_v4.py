"""Bounded CPU11 libc memmove pressure, exact 32MiB payloads and guard bytes."""
import argparse, ctypes as C, hashlib, json, os, signal, time
from pathlib import Path
N=32*1024*1024
GUARD=64
LIB=C.CDLL(None,use_errno=True)
LIB.memmove.argtypes=[C.c_void_p,C.c_void_p,C.c_size_t]
LIB.memmove.restype=C.c_void_p

class GuardedBuffer:
    def __init__(self,n,pattern):
        if n<=0:raise ValueError('positive capacity required')
        self.owner=C.create_string_buffer(n+2*GUARD)
        C.memset(C.addressof(self.owner),0xA7,n+2*GUARD)
        self.payload=(C.c_ubyte*n).from_buffer(self.owner,GUARD)
        C.memset(C.addressof(self.payload),pattern,n)
    def check(self):
        base=C.addressof(self.owner);end=base+C.sizeof(self.owner)-GUARD
        if C.string_at(base,GUARD)!=bytes([0xA7])*GUARD or C.string_at(end,GUARD)!=bytes([0xA7])*GUARD:
            raise RuntimeError('MEMCPY_GUARD_CORRUPTION')
    def info(self):
        return dict(ptr=C.addressof(self.payload),capacity=C.sizeof(self.payload),owner_ptr=C.addressof(self.owner),owner_bytes=C.sizeof(self.owner),guard_bytes_per_side=GUARD)

def copy_once(src,dst,n):
    if C.sizeof(src)!=n or C.sizeof(dst)!=n:raise ValueError('capacity/length mismatch')
    LIB.memmove(C.addressof(dst),C.addressof(src),n)

def durable(path,obj):
    with path.open('x') as f:
        json.dump(obj,f);f.flush();os.fsync(f.fileno())

def main():
    from m1_run_identity import require_nvidia
    identity=require_nvidia()
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--parent',required=True,type=int);ap.add_argument('--cpu',type=int,default=11);ap.add_argument('--bytes',type=int,default=N);ap.add_argument('--seconds',type=int,default=90);a=ap.parse_args()
    if (a.cpu,a.bytes,a.seconds)!=(11,N,90):raise ValueError('fixed interference parameters')
    LIB.prctl.argtypes=[C.c_int,C.c_ulong,C.c_ulong,C.c_ulong,C.c_ulong];LIB.prctl.restype=C.c_int
    if LIB.prctl(1,signal.SIGTERM,0,0,0):raise OSError(C.get_errno(),'PDEATHSIG')
    if os.getppid()!=a.parent:raise RuntimeError('parent changed before readiness')
    os.sched_setaffinity(0,{11})
    if os.sched_getaffinity(0)!={11}:raise RuntimeError('affinity mismatch')
    out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
    src,dst=GuardedBuffer(N,0x5A),GuardedBuffer(N,0)
    src.check();dst.check();copy_once(src.payload,dst.payload,N);src.check();dst.check()
    if bytes(dst.payload)!=bytes(src.payload):raise RuntimeError('preflight copy differs')
    stopped=[False];signal.signal(signal.SIGTERM,lambda *_:stopped.__setitem__(0,True))
    durable(out/'ready.json',dict(identity=identity,pid=os.getpid(),cpu=11,src=src.info(),dst=dst.info(),copy_bytes=N,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),preflight_copies=1,guard_status='PASS'))
    start=time.monotonic();last=start;n=0
    with (out/'progress.jsonl').open('x') as f:
        while not stopped[0] and os.getppid()==a.parent and time.monotonic()-start<90:
            copy_once(src.payload,dst.payload,N);n+=1;now=time.monotonic()
            if now-last>=1:
                src.check();dst.check();f.write(json.dumps(dict(copies=n,bytes_copied=n*N,elapsed_s=now-start))+'\n');f.flush();last=now
        src.check();dst.check();f.flush();os.fsync(f.fileno())
    durable(out/'result.json',dict(copies=n,bytes_copied=n*N,copy_bytes=N,elapsed_s=time.monotonic()-start,src=src.info(),dst=dst.info(),guards='PASS',affinity=sorted(os.sched_getaffinity(0)),exit='parent_exit' if os.getppid()!=a.parent else 'signal_or_90s_bound'))
if __name__=='__main__':main()
