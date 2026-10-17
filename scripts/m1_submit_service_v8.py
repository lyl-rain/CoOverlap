"""Idempotent one-shot transient SERVICE submission, never --scope/--pty."""
import argparse,json,os,subprocess
from pathlib import Path
from m1_execution_v8 import quick_verify,put,sha

def command(base,out,unit,credential_sha):
    return ['/usr/bin/systemd-run','--unit='+unit,'--service-type=exec','--remain-after-exit','--working-directory='+str(base),
        '--property=Restart=no','--property=RuntimeMaxSec=340s','--property=TimeoutStartSec=15s','--property=TimeoutStopSec=60s',
        '--property=KillMode=mixed','--property=KillSignal=SIGTERM','--property=SendSIGKILL=yes',
        '--property=StandardOutput=append:'+str(out/'controller.log'),'--property=StandardError=append:'+str(out/'controller.log'),
        '--setenv=PATH=/usr/sbin:/usr/bin:/sbin:/bin','--setenv=PYTHONUNBUFFERED=1',
        '/usr/bin/python3','-u',str(base/'m1_service_scope_v8.py'),'--base',str(base),'--out',str(out),'--credential-sha',credential_sha]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',required=True);ap.add_argument('--out',required=True);ap.add_argument('--credential-sha',required=True);a=ap.parse_args();base=Path(a.base).resolve();out=Path(a.out).resolve();unit='cooverlap-'+out.name+'.service'
    if os.geteuid()!=0:raise PermissionError('use already approved interactive sudo')
    # Atomic durable submission receipt means a repeated user command can only
    # query status. Even a failed submit is retained, not silently retried.
    receipt=out/'SERVICE_SUBMISSION.json'
    if receipt.exists() or (out/'SCOPE_CLAIM.json').exists():
        print('EXISTING_RUN_STATUS_ONLY',flush=True)
        subprocess.run(['/usr/bin/systemctl','show',unit,'-p','ActiveState','-p','SubState','-p','Result','-p','ExecMainPID','-p','ExecMainCode','-p','ExecMainStatus']);return
    quick_verify(base,out,a.credential_sha)
    cmd=command(base,out,unit,a.credential_sha)
    with receipt.open('x') as f:json.dump(dict(unit=unit,command=cmd,status='SUBMISSION_REQUESTED'),f,indent=2);f.flush();os.fsync(f.fileno())
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
    put(out/'SERVICE_SUBMISSION_RESULT.json',dict(exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
    print(r.stdout+r.stderr,flush=True)
    if r.returncode:raise SystemExit(r.returncode)
    print('SERVICE_SUBMITTED_NOT_MODEL_COMPLETE '+unit,flush=True)
if __name__=='__main__':main()
