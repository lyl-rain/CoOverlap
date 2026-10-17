"""Future approved CPU-only interference; no CUDA/torch/model imports."""
import argparse,ctypes,os,time,json,signal,hashlib
from pathlib import Path

def copy_once(src,dst):
    if len(src)!=len(dst):raise ValueError('source/destination capacities differ')
    ctypes.memmove(dst,src,len(src))
def main():
    from m1_run_identity import require_nvidia
    identity=require_nvidia()
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--parent',type=int,required=True);ap.add_argument('--cpu',type=int,default=11);ap.add_argument('--bytes',type=int,default=33554432);ap.add_argument('--seconds',type=int,default=90);a=ap.parse_args();out=Path(a.out);out.mkdir(exist_ok=False,parents=True)
    if a.bytes!=33554432 or a.seconds!=90 or a.cpu!=11:raise ValueError('fixed interference parameters')
    lib=ctypes.CDLL(None,use_errno=True)
    if lib.prctl(1,signal.SIGTERM,0,0,0)!=0:raise OSError(ctypes.get_errno(),'PR_SET_PDEATHSIG') # Linux PR_SET_PDEATHSIG
    if os.getppid()!=a.parent:return
    os.sched_setaffinity(0,{a.cpu});assert os.sched_getaffinity(0)=={a.cpu}
    src=ctypes.create_string_buffer(bytes([0x5a])*a.bytes,a.bytes);dst=ctypes.create_string_buffer(a.bytes);stop=[False]
    signal.signal(signal.SIGTERM,lambda *_:stop.__setitem__(0,True));start=time.monotonic();n=0;last=start
    (out/'ready.json').write_text(json.dumps(dict(identity=identity,pid=os.getpid(),cpu=a.cpu,bytes=a.bytes,src_pattern='0x5a',kind='fixed contiguous libc memmove loop')))
    with (out/'progress.jsonl').open('x') as f:
        while not stop[0] and time.monotonic()-start<a.seconds and os.getppid()==a.parent:
            copy_once(src,dst);n+=1;now=time.monotonic()
            if now-last>=1:f.write(json.dumps(dict(elapsed_s=now-start,copies=n,bytes_copied=n*a.bytes))+'\n');f.flush();last=now
    (out/'result.json').write_text(json.dumps(dict(copies=n,bytes_copied=n*a.bytes,elapsed_s=time.monotonic()-start,dst_sha256=hashlib.sha256(dst.raw).hexdigest(),cpu_affinity=sorted(os.sched_getaffinity(0)),exit='parent_exit' if os.getppid()!=a.parent else 'stop_or_bound')))
if __name__=='__main__':main()
