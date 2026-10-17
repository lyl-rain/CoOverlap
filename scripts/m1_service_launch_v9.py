"""Exactly one new model attempt; exports/analysis happen after root restoration."""
import hashlib,json,os,signal,subprocess,sys,time,shutil
from pathlib import Path
from m1_completion_launch_v4 import sha,put,admission
from m1_root_trace_core_v9 import pair_config,PROTOCOL
from m1_root_trace_identity_v9 import require_root_launcher as require_nvidia
from m1_execution_v9 import stage,observe,quick_verify
BASE=Path(__file__).resolve().parent
def main():
    identity=require_nvidia()
    from m1_root_trace_identity_v9 import root_prefix,monitor_prefix
    permission=dict(policy="explicit root diagnostic exception; model capabilities restricted by setpriv")
    if os.environ.get('COOVERLAP_APPROVED_BATCH')!=PROTOCOL:raise RuntimeError('wrong approval ID')
    from m1_completion_health import check_hardware,check_no_models
    root=Path(os.environ['COOVERLAP_BATCH_DIR']);quick_verify(BASE,root,os.environ['COOVERLAP_PREFLIGHT_SHA256'])
    put(root/'LAUNCH_IDENTITY.json',dict(**identity,capture_permission=permission));attempts=[];put(root/'ATTEMPTS.json',attempts)
    monitor=None;p=None
    try:
        admission(int(os.environ['COOVERLAP_SCOPE_DEADLINE_NS']),180)
        check_no_models();put(root/'hardware_before.json',check_hardware())
        if shutil.disk_usage(root).free<40*1024**3:raise RuntimeError('disk below40GiB')
        mode=subprocess.run(['nvpmodel','-q'],capture_output=True,text=True,timeout=5)
        put(root/'POWER_MODE.json',dict(exit=mode.returncode,stdout=mode.stdout,stderr=mode.stderr))
        if mode.returncode or 'MAXN' not in mode.stdout or mode.stdout.strip().splitlines()[-1].strip()!='0':raise RuntimeError('unchanged MAXN0 not confirmed')
        cfg=root/'pair.json';c=json.loads((BASE/'APPROVED_CONFIG.json').read_text());put(cfg,c)
        stage(root,'LAUNCHER_READY',identity=identity,configuration_sha256=sha(cfg))
        put(root/'FROZEN_LEDGER.json',dict(configuration=c,total=c['total_ledger'],model_attempt_limit=1))
        env=os.environ.copy();env.update(COOVERLAP_PROTOCOL=str(cfg),COOVERLAP_PROTOCOL_SHA=sha(cfg),COOVERLAP_RUN_DIR=str(root/'pair'))
        command=root_prefix()+['taskset','-c','0-10','timeout','--kill-after=5s','175s',sys.executable,'-B','-u',str(BASE/'pi05_m1_root_trace_v9.py'),'--config',str(cfg)]
        startup_keys=['LD_PRELOAD','LD_LIBRARY_PATH','CUDA_VISIBLE_DEVICES','CUDA_MODULE_LOADING','CUDA_DEVICE_MAX_CONNECTIONS','CUBLAS_WORKSPACE_CONFIG','CUDA_LAUNCH_BLOCKING','CUDA_INJECTION64_PATH','CUDA_INJECTION32_PATH','CUPTI_INJECTION64_PATH']
        put(root/'STARTUP_ENVIRONMENT.json',{k:env.get(k) for k in startup_keys})
        if any(env.get(k) for k in ['CUDA_INJECTION64_PATH','CUDA_INJECTION32_PATH','CUPTI_INJECTION64_PATH']) or 'nsys' in env.get('LD_PRELOAD','').lower():raise RuntimeError('unexpected startup injection environment; preserve without clearing')
        rec=dict(command=command,role='pair_close',status='STARTING',started=False,exit_code=None,started_ns=time.monotonic_ns(),script_sha256=sha(BASE/'pi05_m1_root_trace_v9.py'),configuration_sha256=sha(cfg))
        attempts.append(rec);put(root/'ATTEMPTS.json',attempts);stage(root,'MODEL_LAUNCH_REQUESTED',command=command,configuration_sha256=sha(cfg))
        monitor=subprocess.Popen(monitor_prefix()+[sys.executable,'-B',str(BASE/'m1_completion_monitor.py'),'--out',str(root/'hardware.jsonl'),'--parent',str(os.getpid())])
        def stopped(sig,*_):raise InterruptedError('launcher signal '+str(sig))
        for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,stopped)
        with (root/'pair.log').open('x') as log:
            p=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            rec.update(started=True,status='RUNNING',pid=p.pid);put(root/'ATTEMPTS.json',attempts)
            stage(root,'MODEL_STARTED',supervisor_pid=p.pid,model_pid='UNKNOWN_until_durable_result',basis='timeout/model process tree started; failed starts count against quota')
            seen=set()
            while p.poll() is None:
                observe(root,seen)
                try:p.wait(timeout=1)
                except subprocess.TimeoutExpired:pass
            observe(root,seen);rec['exit_code']=p.returncode
        result=json.loads((root/'pair/result.json').read_text()) if (root/'pair/result.json').exists() else {}
        if rec['exit_code'] or result.get('status')!='PASS':raise RuntimeError('single attempt stopped; no retry')
        activity=root/'pair/activity_trace/activity.jsonl'
        put(root/'BATCH_STATUS.json',dict(status='COMPLETE_REQUIRES_OFFLINE_AUDIT',attempts=1,trace='PRESENT_REQUIRES_OFFLINE_VALIDATION' if activity.exists() and activity.stat().st_size else 'UNKNOWN_MISSING_ACTIVITY'))
    except BaseException as e:
        put(root/'BATCH_STATUS.json',dict(status='STOPPED',reason=repr(e),attempts=len(attempts)));stage(root,'LAUNCHER_STOP',error=repr(e),model_started=bool(p));raise
    finally:
        if p is not None and p.poll() is None:
            os.killpg(p.pid,signal.SIGTERM)
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
        if attempts:
            rec=attempts[0];rec.update(ended_ns=time.monotonic_ns(),exit_code=p.returncode if p else None,status='EXITED' if p else 'FAILED_START')
            rec['wall_s']=(rec['ended_ns']-rec['started_ns'])/1e9;put(root/'ATTEMPTS.json',attempts)
        stage(root,'MODEL_EXIT',exit_code=p.returncode if p else 'NOT_STARTED',termination_signal=(-p.returncode if p and p.returncode is not None and p.returncode<0 else 'UNKNOWN_OR_NOT_SIGNALED'),model_attempts=len(attempts))
        if 'seen' in locals():
            for name in ['REFERENCE_GATE_RESULT','NORMAL_SAMPLES_SAVED','COLLECTOR_ENABLED','POST_ENABLE_GATE_RESULT','DIAGNOSTIC_SAMPLES_SAVED']:
                if name not in seen:stage(root,name,status='NOT_REACHED_OR_NOT_DURABLY_OBSERVED')
        if monitor:
            monitor.terminate()
            try:monitor.wait(timeout=3)
            except subprocess.TimeoutExpired:monitor.kill();monitor.wait()
if __name__=='__main__':main()
