"""Transient service controller; five existing minima, no model changes."""
import argparse,ctypes,fcntl,json,os,signal,subprocess,time
from pathlib import Path
import m1_clock_scope_v6 as clock
from m1_execution_v9 import quick_verify,stage,put,safety_before_clocks

def run(base,out,credential_sha,root=Path('/'),launch=None,deadline_s=300):
    out=Path(out);snapshot=out/'clock_before.json';child=None;tx=None;signals=[];start=time.monotonic();status='FAILED';rc=None;error=None
    def stopped(sig,*_):
        signals.append(sig);raise InterruptedError('controller signal '+str(sig))
    handlers={s:signal.signal(s,stopped) for s in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP)}
    try:
        quick_verify(base,out,credential_sha)
        if root==Path('/'):safety_before_clocks(base)
        from m1_root_trace_identity_v9 import root_prefix,PROTOCOL
        credential=json.loads((out/'PREFLIGHT.json').read_text());trace_env=dict(credential['environment'])
        trace_env.update(COOVERLAP_ROOT_DIAGNOSTIC=PROTOCOL)
        check=subprocess.run(root_prefix()+['/usr/bin/python3','-B',str(Path(base)/'m1_root_trace_identity_v9.py'),'--permission-smoke',str(out/'permission_smoke')],env=trace_env,cwd=base,capture_output=True,text=True,timeout=15)
        put(out/'PERMISSION_PRE_CLOCK_CHECK.json',dict(exit_code=check.returncode,stdout=check.stdout,stderr=check.stderr))
        if check.returncode:raise RuntimeError('root CUPTI permission smoke failed before clocks; model NOT_RUN')
        tx=clock.SnapshotTransaction(snapshot) # refuses existing snapshot, responsibility before apply
        lib=ctypes.CDLL(None,use_errno=True)
        if lib.prctl(36,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),'subreaper')
        clock.apply(snapshot,root,transaction=tx)
        stage(out,'CLOCKS_APPLIED')
        telemetry=out/'clock.telemetry.jsonl'
        with telemetry.open('x') as log:
            os.chmod(telemetry,0o644)
            c=json.loads((out/'PREFLIGHT.json').read_text());env=c['environment']
            env.update(COOVERLAP_ROOT_DIAGNOSTIC=PROTOCOL,COOVERLAP_ROOT_TELEMETRY=str(telemetry),COOVERLAP_SCOPE_DEADLINE_NS=str(int((start+deadline_s)*1e9)),COOVERLAP_BATCH_DIR=str(out),COOVERLAP_PREFLIGHT_SHA256=credential_sha)
            args=['/usr/bin/env']+[k+'='+v for k,v in sorted(env.items())]+['/home/nvidia/jetson-torch-env/bin/python','-u',str(Path(base)/'m1_service_launch_v9.py')]
            child=(launch or subprocess.Popen)(args,cwd=base,start_new_session=True)
            while True:
                log.write(json.dumps(clock.telemetry(root))+'\n');log.flush()
                if root==Path('/'):
                    from m1_completion_health import check_hardware
                    check_hardware()
                rc=child.poll()
                if rc is not None:
                    if rc:raise RuntimeError('launcher exit '+str(rc))
                    status='COMPLETE';break
                if time.monotonic()-start>=deadline_s:raise TimeoutError('internal 300s deadline; recovery before systemd hard bound')
                time.sleep(1)
    except BaseException as e:
        error=repr(e);stage(out,'CONTROLLER_STOP',error=error,signals=signals,launcher_exit_code=rc if rc is not None else 'UNKNOWN');raise
    finally:
        for s in handlers:signal.signal(s,signal.SIG_IGN)
        restored=False;cleanup='NOT_REQUIRED';recovery_error=None
        try:
            if child is not None:clock.stop_children(child);cleanup='PASS'
            stage(out,'RESTORE_STARTED',cleanup=cleanup)
            if tx is not None:restored=tx.recover(root)
            if restored:print('RESTORED_FIVE_MINIMA',flush=True)
            stage(out,'RESTORE_RESULT',status='PASS' if restored else 'NO_OWNED_SNAPSHOT_NO_WRITES',cleanup=cleanup,elapsed_s=time.monotonic()-start)
        except BaseException as e:
            recovery_error=repr(e);stage(out,'RESTORE_RESULT',status='FAIL',error=recovery_error,cleanup=cleanup);raise
        finally:
            put(out/'CONTROLLER_RESULT.json',dict(status=status if not error and not recovery_error else 'STOPPED',controller_pid=os.getpid(),signals=signals,launcher_exit_code=rc if rc is not None else 'UNKNOWN',error=error,restore_error=recovery_error,automatic_restored=restored,cleanup=cleanup,wall_s=time.monotonic()-start))
            for s,h in handlers.items():signal.signal(s,h)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',required=True);ap.add_argument('--out',required=True);ap.add_argument('--credential-sha',required=True);ap.add_argument('--allow-root-diagnostic',action='store_true');a=ap.parse_args()
    if not a.allow_root_diagnostic:raise PermissionError('explicit --allow-root-diagnostic required')
    if os.geteuid()!=0:raise PermissionError('explicit interactive root service required')
    # One active controller, plus a durable per-run claim preventing re-entry
    # even after a transient service has stopped or been unloaded.
    with open('/run/lock/cooverlap-m1-v6.lock','a') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        claim=Path(a.out)/'SCOPE_CLAIM.json'
        with claim.open('x') as c:json.dump(dict(pid=os.getpid(),host_ns=time.monotonic_ns()),c);c.flush();os.fsync(c.fileno())
        run(a.base,a.out,a.credential_sha)
if __name__=='__main__':main()
