"""Exactly one new model attempt; exports/analysis happen after root restoration."""
import hashlib,json,os,signal,subprocess,sys,time,shutil
from pathlib import Path
from m1_completion_launch_v4 import sha,put,admission
from m1_pair_close_core_v5 import pair_config,PROTOCOL
from m1_run_identity import require_nvidia
BASE=Path(__file__).resolve().parent
def main():
    identity=require_nvidia()
    if os.environ.get('COOVERLAP_APPROVED_BATCH')!=PROTOCOL:raise RuntimeError('wrong approval ID')
    from m1_completion_health import check_hardware,check_no_models
    root=Path(os.environ['COOVERLAP_BATCH_DIR']);root.mkdir(exist_ok=False)
    put(root/'LAUNCH_IDENTITY.json',identity);attempts=[];put(root/'ATTEMPTS.json',attempts)
    monitor=None;p=None
    try:
        admission(int(os.environ['COOVERLAP_SCOPE_DEADLINE_NS']),180)
        check_no_models();put(root/'hardware_before.json',check_hardware())
        if shutil.disk_usage(root).free<40*1024**3:raise RuntimeError('disk below40GiB')
        mode=subprocess.run(['nvpmodel','-q'],capture_output=True,text=True,timeout=5)
        put(root/'POWER_MODE.json',dict(exit=mode.returncode,stdout=mode.stdout,stderr=mode.stderr))
        if mode.returncode or 'MAXN' not in mode.stdout or mode.stdout.strip().splitlines()[-1].strip()!='0':raise RuntimeError('unchanged MAXN0 not confirmed')
        frozen=json.loads((BASE/'unified_reference/SOURCE_CHECKPOINT_SHA256.json').read_text())
        actual={path:sha(path) for path in frozen};put(root/'INPUT_SOURCE_SHA256.json',actual)
        if actual!=frozen:raise RuntimeError('source/checkpoint changed')
        c=pair_config();cfg=root/'pair.json';put(cfg,c)
        put(root/'FROZEN_LEDGER.json',dict(configuration=c,total=c['total_ledger'],model_attempt_limit=1))
        env=os.environ.copy();env.update(COOVERLAP_PROTOCOL=str(cfg),COOVERLAP_PROTOCOL_SHA=sha(cfg),COOVERLAP_RUN_DIR=str(root/'pair'),NSYS_NVTX_PROFILER_REGISTER_ONLY='0')
        trace=root/'trace_report';trace.mkdir()
        command=['taskset','-c','0-10','timeout','--kill-after=5s','175s','nsys','profile','--trace=cuda,nvtx,osrt','--sample=none','--cpuctxsw=none','--capture-range=nvtx','--nvtx-capture=M1_PAIR_TRACE','--capture-range-end=stop','--output='+str(trace/'pair'),sys.executable,'-u',str(BASE/'pi05_m1_pair_close_v5.py'),'--config',str(cfg)]
        rec=dict(command=command,role='pair_close',status='STARTING',started=False,exit_code=None,started_ns=time.monotonic_ns(),script_sha256=sha(BASE/'pi05_m1_pair_close_v5.py'),configuration_sha256=sha(cfg))
        attempts.append(rec);put(root/'ATTEMPTS.json',attempts)
        monitor=subprocess.Popen([sys.executable,str(BASE/'m1_completion_monitor.py'),'--out',str(root/'hardware.jsonl'),'--parent',str(os.getpid())])
        def stopped(sig,*_):raise InterruptedError('launcher signal '+str(sig))
        for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,stopped)
        with (root/'pair.log').open('x') as log:
            p=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            rec.update(started=True,status='RUNNING',pid=p.pid);put(root/'ATTEMPTS.json',attempts);rec['exit_code']=p.wait()
        result=json.loads((root/'pair/result.json').read_text()) if (root/'pair/result.json').exists() else {}
        if rec['exit_code'] or result.get('status')!='PASS':raise RuntimeError('single attempt stopped; no retry')
        rep=trace/'pair.nsys-rep'
        put(root/'BATCH_STATUS.json',dict(status='COMPLETE_REQUIRES_OFFLINE_AUDIT',attempts=1,trace='PRESENT_REQUIRES_OFFLINE_VALIDATION' if rep.exists() and rep.stat().st_size else 'UNKNOWN_MISSING_REPORT'))
    except BaseException as e:
        put(root/'BATCH_STATUS.json',dict(status='STOPPED',reason=repr(e),attempts=len(attempts)));raise
    finally:
        if p is not None and p.poll() is None:
            os.killpg(p.pid,signal.SIGTERM)
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
        if attempts:
            rec=attempts[0];rec.update(ended_ns=time.monotonic_ns(),exit_code=p.returncode if p else None,status='EXITED' if p else 'FAILED_START')
            rec['wall_s']=(rec['ended_ns']-rec['started_ns'])/1e9;put(root/'ATTEMPTS.json',attempts)
        if monitor:
            monitor.terminate()
            try:monitor.wait(timeout=3)
            except subprocess.TimeoutExpired:monitor.kill();monitor.wait()
if __name__=='__main__':main()
