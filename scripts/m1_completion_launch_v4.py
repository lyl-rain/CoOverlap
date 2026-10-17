"""One 2700s scope, at most nine named model attempts, no automatic retry."""
import hashlib,json,os,signal,subprocess,sys,time,shutil
from pathlib import Path
from m1_completion_core_v4 import trace_config,calibration_config,pair_config,formal_configs,select_budgets
from m1_run_identity import require_nvidia
BASE=Path(__file__).resolve().parent
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def put(path,value):
    tmp=Path(str(path)+'.tmp')
    with tmp.open('w') as f:json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def admission(deadline_ns,timeout_s,now_ns=None):
    # Root deadline already reserves60s restore, launcher adds10s local cleanup.
    if (time.monotonic_ns() if now_ns is None else now_ns)+(timeout_s+10)*10**9>=deadline_ns:
        raise TimeoutError('NOT_RUN: insufficient scope remainder including cleanup')

def main():
    identity=require_nvidia()
    if os.environ.get('COOVERLAP_APPROVED_BATCH')!='m1_completion_20261016_v4':raise RuntimeError('new protocol approval identifier required')
    from m1_completion_health import check_hardware,check_no_models
    root=Path(os.environ['COOVERLAP_BATCH_DIR']);root.mkdir(exist_ok=False)
    put(root/'LAUNCH_IDENTITY.json',identity)
    deadline=int(os.environ['COOVERLAP_SCOPE_DEADLINE_NS'])
    if shutil.disk_usage(root).free<40*1024**3:raise RuntimeError('disk below40GiB')
    files=list(BASE.glob('*.py'))+list(BASE.glob('*.sh'))
    files+=list(Path('/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5').rglob('*'))
    source=Path('/home/nvidia/rtvla/FlashRT');files+=list(source.rglob('*.py'))+list(source.rglob('*.so'))
    current={str(p):sha(p) for p in files if p.is_file()};put(root/'INPUT_SOURCE_SHA256.json',current)
    frozen=json.loads((BASE/'unified_reference/SOURCE_CHECKPOINT_SHA256.json').read_text())
    if any(current.get(k)!=v for k,v in frozen.items()):raise RuntimeError('source/checkpoint changed, no launch')
    attempts=[];monitor=None;plan=[dict(role=x,timeout_s=t,status='NOT_RUN') for x,t in [('trace',180),('calibration',180),('pair',180),('tight_repeat1',300),('loose_repeat1',300),('loose_repeat2',300),('tight_repeat2',300),('tight_repeat3',300),('loose_repeat3',300)]]
    put(root/'RUN_PLAN.json',plan);put(root/'ATTEMPTS.json',attempts)
    def run(c):
        if len(attempts)>=9:raise RuntimeError('attempt limit9')
        role=c['role'];admission(deadline,c['timeout_s']);check_no_models();check_hardware()
        if (root/'STOP_BATCH').exists():raise RuntimeError('external safety stop requested')
        mode=subprocess.run(['nvpmodel','-q'],capture_output=True,text=True,timeout=5)
        if mode.returncode or 'MAXN' not in mode.stdout or mode.stdout.strip().splitlines()[-1].strip()!='0':raise RuntimeError('unchanged MAXN0 mode not confirmed')
        cfg=root/(role+'.json');put(cfg,c)
        out=root/role;env=os.environ.copy();env.update(COOVERLAP_PROTOCOL=str(cfg),COOVERLAP_PROTOCOL_SHA=sha(cfg),COOVERLAP_RUN_DIR=str(out))
        command=['taskset','-c','0-10','timeout','--kill-after=5s',str(c['timeout_s']-5)+'s',sys.executable,str(BASE/'pi05_m1_completion_v4.py'),'--config',str(cfg)]
        if c['capture']:
            env['NSYS_NVTX_PROFILER_REGISTER_ONLY']='0';trace=root/'trace_report';trace.mkdir()
            command=['timeout','--kill-after=5s',str(c['timeout_s']-5)+'s','nsys','profile','--trace=cuda,nvtx,osrt','--sample=none','--cpuctxsw=none','--capture-range=nvtx','--nvtx-capture=M1_COMPLETION_TRACE','--capture-range-end=stop','--output='+str(trace/'trace')]+command
        rec=dict(role=role,command=command,status='STARTING',started=False,started_ns=time.monotonic_ns(),exit_code=None,protocol_sha256=sha(cfg),script_sha256=sha(BASE/'pi05_m1_completion_v4.py'))
        attempts.append(rec);put(root/'ATTEMPTS.json',attempts)
        p=None
        try:
            with (root/(role+'.log')).open('x') as log:
                p=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                rec.update(pid=p.pid,started=True,status='RUNNING');put(root/'ATTEMPTS.json',attempts);rec['exit_code']=p.wait()
        except BaseException as e:rec['stop_reason']=repr(e);raise
        finally:
            if p is not None and p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
            rec.update(ended_ns=time.monotonic_ns(),status='EXITED' if p is not None else 'FAILED_START')
            if p is not None:rec['exit_code']=p.returncode
            rec['wall_s']=(rec['ended_ns']-rec['started_ns'])/1e9;put(root/'ATTEMPTS.json',attempts)
        result=json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else {}
        # Only pure pairing numerical failure with protected old KV and clean cleanup
        # may leave the independent sequential branch open. No other retry/bypass.
        pr=result.get('pair',{})
        pair_only=(role=='pair' and rec['exit_code']==1 and pr.get('failure_kind')=='PAIR_NUMERICAL_ONLY' and pr.get('cuda_clean') is True and pr.get('old_v0_protected') is True and pr.get('cleanup')=='PASS_synchronized_resources_released')
        entry=next(x for x in plan if x['role']==role);entry.update(status='PAIR_FAIL_SEQUENTIAL_MAY_CONTINUE' if pair_only else result.get('status','INCOMPLETE_NO_RESULT'),result_sha256=sha(out/'result.json') if result else None)
        put(root/'RUN_PLAN.json',plan)
        if pair_only:
            check_no_models();check_hardware();return result
        if rec['exit_code']!=0 or result.get('status')!='PASS':raise RuntimeError(role+' failed/incomplete: no retry, retain remaining NOT_RUN')
        if c['capture']:
            rep=root/'trace_report/trace.nsys-rep'
            entry['trace_status']='PRESENT_REQUIRES_OFFLINE_VALIDATION' if rep.exists() and rep.stat().st_size else 'UNKNOWN_NO_REPORT'
            put(root/'RUN_PLAN.json',plan)
        return result
    def stopped(signum,*_):raise InterruptedError('launcher signal '+str(signum))
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,stopped)
    try:
        monitor=subprocess.Popen([sys.executable,str(BASE/'m1_completion_monitor.py'),'--out',str(root/'hardware.jsonl'),'--parent',str(os.getpid())])
        run(trace_config())
        rep=root/'trace_report/trace.nsys-rep'
        if rep.exists() and rep.stat().st_size:
            with (root/'TRACE_OFFLINE.log').open('x') as log:
                export=subprocess.run(['timeout','--kill-after=5s','35s','nsys','export','--type=sqlite','--output='+str(root/'trace_report/trace.sqlite'),str(rep)],stdout=log,stderr=subprocess.STDOUT)
                if export.returncode==0:
                    analyze=subprocess.run(['timeout','--kill-after=5s','25s',sys.executable,str(BASE/'analyze_m1_trace_v4.py'),str(root/'trace_report/trace.sqlite'),str(root/'trace_report/NOISE_CORRELATION.json')],stdout=log,stderr=subprocess.STDOUT)
                    put(root/'TRACE_ANALYSIS_STATUS.json',dict(export_exit=export.returncode,analysis_exit=analyze.returncode))
                else:put(root/'TRACE_ANALYSIS_STATUS.json',dict(export_exit=export.returncode,analysis='UNKNOWN; no repeat'))
        # Trace evidence does not become a root-cause gate; final scripts remain frozen.
        put(root/'FINAL_CODE_FREEZE.json',dict(files={p.name:sha(p) for p in BASE.glob('*.py')},after_trace=True,submission_error='NOT_ESTABLISHED; automatic correlation only, human offline review pending',root_cause='UNKNOWN; no second trace'))
        result=run(calibration_config());selection=None
        try:
            selection=select_budgets(result);selection['result_sha256']=sha(root/'calibration/result.json');put(root/'SELECTION.json',selection)
        except ValueError as e:put(root/'SELECTION_STOP.json',dict(reason=str(e),formal='NOT_RUN',no_candidate_expansion=True))
        fs=formal_configs(selection) if selection is not None else []
        for c in fs:put(root/(c['role']+'.frozen.json'),c)
        run(pair_config())
        for c in fs:run(c)
        put(root/'BATCH_STATUS.json',dict(status='COMPLETE_REQUIRES_OFFLINE_AUDIT' if selection is not None else 'PARTIAL_FORMAL_NOT_RUN_NO_LEGAL_CALIBRATION',attempts=len(attempts)))
    except BaseException as e:
        put(root/'BATCH_STATUS.json',dict(status='STOPPED',reason=repr(e),attempts=len(attempts)));raise
    finally:
        if monitor is not None:
            monitor.terminate()
            try:monitor.wait(timeout=3)
            except subprocess.TimeoutExpired:monitor.kill();monitor.wait()
        put(root/'RUN_PLAN.json',plan)
if __name__=='__main__':main()
