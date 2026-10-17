"""Prepared bounded batch launcher. NO authorization is implied by this file."""
import os,sys,json,subprocess,time,hashlib,signal,shutil
from pathlib import Path
from m1_completion_core import calibration_config,select_budgets,formal_configs,trace_config
from m1_run_identity import require_nvidia

BASE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def stream_sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def put(p,v):
    with p.open('w') as f:json.dump(v,f,indent=2);f.flush();os.fsync(f.fileno())

def main():
    identity=require_nvidia()
    if os.environ.get('COOVERLAP_APPROVED_BATCH')!='m1_completion_batch_v1':raise RuntimeError('explicit approval required')
    from m1_completion_health import check_hardware,check_no_models
    root=Path(os.environ['COOVERLAP_BATCH_DIR']);root.mkdir(exist_ok=False)
    put(root/'LAUNCH_IDENTITY.json',identity)
    if shutil.disk_usage(root).free<40*1024**3:raise RuntimeError('need40GiB free, no model started')
    files=list(BASE.glob('*.py'))+list(BASE.glob('*.sh'))
    files+=list(Path('/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5').rglob('*'))
    source=Path('/home/nvidia/rtvla/FlashRT')
    files+=list(source.rglob('*.py'))+list(source.rglob('*.so'))
    put(root/'INPUT_SOURCE_SHA256.json',{str(p):stream_sha(p) for p in files if p.is_file()})
    attempts=[];monitor=None
    def run(c):
        check_no_models()
        check_hardware()
        mode=subprocess.run(['nvpmodel','-q'],capture_output=True,text=True,timeout=5)
        if mode.returncode or 'MAXN' not in mode.stdout or mode.stdout.strip().splitlines()[-1].strip()!='0':raise RuntimeError('reviewed MAXN0 mode differs; no model start')
        role=c['role'];cfg=root/(role+'.json');put(cfg,c)
        out=root/role;env=os.environ.copy();env.update(COOVERLAP_PROTOCOL=str(cfg),COOVERLAP_PROTOCOL_SHA=sha(cfg),COOVERLAP_RUN_DIR=str(out))
        command=['taskset','-c','0-10','timeout','--kill-after=5s',str(c['timeout_s']-5)+'s',sys.executable,str(BASE/'pi05_m1_completion.py'),'--config',str(cfg)]
        if c['capture']:
            env['NSYS_NVTX_PROFILER_REGISTER_ONLY']='0'
            trace=root/'trace_report';trace.mkdir()
            # Bound the profiler as well as the target, one target process only.
            command=['timeout','--kill-after=5s',str(c['timeout_s']-5)+'s','nsys','profile','--trace=cuda,nvtx,osrt','--sample=none','--cpuctxsw=none','--capture-range=nvtx','--nvtx-capture=M1_COMPLETION_TRACE','--capture-range-end=stop','--output='+str(trace/'trace')]+command
        rec=dict(role=role,command=command,started=False,started_ns=time.monotonic_ns(),status='STARTING',exit_code=None,protocol_sha256=sha(cfg),script_sha256=sha(BASE/'pi05_m1_completion.py'))
        attempts.append(rec);put(root/'ATTEMPTS.json',attempts) # includes failed starts
        try:
            with (root/(role+'.log')).open('x') as log:
                p=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                rec.update(pid=p.pid,started=True,status='RUNNING');put(root/'ATTEMPTS.json',attempts)
                try:rec['exit_code']=p.wait()
                finally:
                    # timeout/nsys may have their own descendants/process groups;
                    # root subreaper is the final scoped cleanup backstop.
                    if p.poll() is None:
                        os.killpg(p.pid,signal.SIGTERM)
                        try:p.wait(timeout=5)
                        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
        except BaseException as e:
            rec['stop_reason']=repr(e)
            if 'p' in locals():rec['exit_code']=p.poll()
            raise
        finally:rec['ended_ns']=time.monotonic_ns();rec['status']='INTERRUPTED_OR_FAILED_START' if 'stop_reason' in rec else 'EXITED';put(root/'ATTEMPTS.json',attempts)
        if rec['exit_code']!=0:raise RuntimeError(role+' stopped, no retry; partial data retained')
        result=json.loads((out/'result.json').read_text())
        if result['status']!='PASS':raise RuntimeError(role+' incomplete or failed, no subsequent launch')
        if c['capture']:
            rep=root/'trace_report/trace.nsys-rep'
            if not rep.exists() or rep.stat().st_size==0:raise RuntimeError('trace absent, no retry')
        return result
    def stopped(signum,*_):
        for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,signal.SIG_IGN)
        raise InterruptedError('launcher signal '+str(signum))
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,stopped)
    try:
        monitor=subprocess.Popen([sys.executable,str(BASE/'m1_completion_monitor.py'),'--out',str(root/'hardware.jsonl'),'--parent',str(os.getpid())])
        result=run(calibration_config());selection=select_budgets(result)
        selection['calibration_result_sha256']=sha(root/'calibration/result.json');put(root/'SELECTION.json',selection)
        for c in formal_configs(selection):run(c)
        run(trace_config(selection))
        put(root/'BATCH_STATUS.json',dict(status='COMPLETE_REQUIRES_OFFLINE_TRACE_AND_RAW_AUDIT',attempts=len(attempts)))
    except BaseException as e:
        put(root/'BATCH_STATUS.json',dict(status='STOPPED',reason=repr(e),attempts=len(attempts)));raise
    finally:
        if monitor is not None:
            monitor.terminate()
            try:monitor.wait(timeout=3)
            except subprocess.TimeoutExpired:monitor.kill();monitor.wait()
if __name__=='__main__':main()
