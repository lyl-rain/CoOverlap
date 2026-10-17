"""One-Hz read-only status log, no CUDA imports, no hardware writes."""
import argparse,json,os,time,signal
from pathlib import Path
from m1_completion_health import check_hardware
def main():
    from m1_run_identity import require_nvidia
    require_nvidia()
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--parent',type=int,required=True);a=p.parse_args();stop=[False]
    signal.signal(signal.SIGTERM,lambda *_:stop.__setitem__(0,True))
    with Path(a.out).open('x') as f:
        while not stop[0] and os.getppid()==a.parent:
            try:r=check_hardware()
            except Exception as e:r=dict(monotonic_ns=time.monotonic_ns(),health_error=repr(e))
            f.write(json.dumps(r)+'\n');f.flush();time.sleep(1)
if __name__=='__main__':main()
