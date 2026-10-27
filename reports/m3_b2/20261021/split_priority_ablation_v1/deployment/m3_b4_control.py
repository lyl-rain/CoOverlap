"""PREPARED ONLY: one-shot M3 split x priority ablation controller.

preflight/readback never import CUDA. Only submit/scope plus the new explicit
approval flag can write hardware. Reuses the frozen v6 five-node transaction and
descendant cleanup unchanged; identical custody to the r2 controller.
"""
import argparse,ctypes,hashlib,json,os,pwd,signal,socket,subprocess,time
from pathlib import Path
from m3_b4_plan import PROTOCOL, protocol
from m1_clock_scope_v6 import NODES,SnapshotTransaction,apply,state,telemetry,stop_children

PYTHON='/home/nvidia/jetson-torch-env/bin/python'
DIAG='/home/nvidia/rtvla/cooverlap_diag_20261014_resource/lib'
FLASH='/home/nvidia/rtvla/FlashRT'
FIXTURES={'/tmp/cooverlap_pi05_fixed_reference.npz':'92f1a92b64352cc34010c81c1accd1cb00fcb227d0004f545b87549d5d6c544d',
'/tmp/cooverlap_pi05_state_versions.npz':'cabb191ec2b319c43fa769e5c8b9b8851724ef25ecff8850d118b8276124205e'}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()


def identity(path):
    s=Path(path).stat();return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]


def dump(path,data):
    with Path(path).open('x') as f:
        json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())


def package_files(base):
    records={}
    for line in (base/'DEPLOY_SHA256.txt').read_text().splitlines():
        digest,name=line.split(None,1);name=name.strip()
        path=(base/name).resolve()
        if not path.is_relative_to(base.resolve()) or name in records:raise ValueError('unsafe deployment manifest')
        if sha(path)!=digest:raise ValueError('deployment SHA differs: '+name)
        records[name]=dict(sha256=digest,identity=identity(path))
    if 'CONFIG.json' not in records or json.loads((base/'CONFIG.json').read_text())!=protocol():raise ValueError('protocol changed')
    return records


def competing_jobs():
    # Read-only /proc inventory; allow this CPU controller/its shell ancestry.
    bad=[]
    for p in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            argv=p.read_bytes().split(b'\0');text=b' '.join(argv).decode(errors='replace')
            if any(x in text for x in ('torchrun','nsys profile','pi05_m2_','pi05_m3_','pi05_period_obligation','pi05_green')):
                # Only executable/first script positions: a shell's literal
                # command text is not itself an executing model process.
                first=' '.join(a.decode(errors='replace') for a in argv[:3])
                if 'm3_b4_control.py' not in first and any(x in first for x in ('torchrun','nsys','pi05_')):bad.append(dict(pid=int(p.parent.name),cmd=text))
        except (OSError,ValueError):pass
    if bad:raise RuntimeError('competing model/profiler: '+repr(bad))


def legal_hardware():
    rows=state()
    if any(r['target']!=r['max'] or r['target'] not in r['available'] for r in rows):raise RuntimeError('unreviewed hardware legal values')
    temp=int(Path('/sys/devices/virtual/thermal/thermal_zone0/temp').read_text())
    mem=next(int(l.split()[1])*1024 for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
    if temp>=80000 or mem<36*1024**3:raise RuntimeError('thermal/memory admission')
    governors={name:(Path(b)/'scaling_governor' if name.startswith('cpu') else Path(b)/'governor').read_text().strip() for name,b,*_ in NODES}
    power=subprocess.run(['/usr/sbin/nvpmodel','-q'],capture_output=True,text=True,check=True,timeout=5).stdout.strip()
    return dict(nodes=rows,temp_mC=temp,MemAvailable_B=mem,governors=governors,power_mode=power)


def preflight(base,run):
    if os.geteuid()==0 or pwd.getpwuid(os.geteuid()).pw_name!='nvidia' or socket.gethostname()!='jyh-orin':raise RuntimeError('ordinary nvidia on jyh-orin only')
    run.mkdir(exist_ok=False)
    package=package_files(base);competing_jobs();hw=legal_hardware()
    src=json.loads((base/'reference/SOURCE_CHECKPOINT_SHA256.json').read_text())
    if len(src)!=967:raise ValueError('frozen source lock must have 967 entries')
    src.update(FIXTURES)
    # The binary was already approved/installed; neither build nor install.
    diag=list(Path(DIAG).glob('flash_rt_gemm_diag*.so'))
    if len(diag)!=1:raise ValueError('existing diagnostic library ambiguity')
    src[str(diag[0])]='bee648c5b5a9821084a39bb88ed9cba9681503c1043f90a7c95ace0bb1048d78'
    rows={}
    for name,wanted in src.items():
        before=identity(name)
        if sha(name)!=wanted or identity(name)!=before:raise ValueError('source/fixture changed: '+name)
        rows[name]=dict(sha256=wanted,identity=before)
    vfs=os.statvfs(run)
    if vfs.f_bavail*vfs.f_frsize<12*1024**3:raise RuntimeError('disk admission 12GiB')
    result=dict(protocol=PROTOCOL,host=socket.gethostname(),uid=os.geteuid(),created=time.time(),
                base=str(base.resolve()),run=str(run.resolve()),package=package,sources=rows,hardware_before=hw,
                no_GPU_import=True,no_hardware_write=True)
    dump(run/'PREFLIGHT.json',result)
    print(json.dumps(dict(status='CPU_PREFLIGHT_PASS',credential_sha256=sha(run/'PREFLIGHT.json')),indent=2))


def verify_credential(base,run,credential_sha,large_files=False):
    base=base.resolve();run=run.resolve();path=run/'PREFLIGHT.json'
    if sha(path)!=credential_sha:raise ValueError('credential SHA changed')
    c=json.loads(path.read_text())
    if c['host']!=socket.gethostname() or c['base']!=str(base) or c['run']!=str(run) or c['protocol']!=PROTOCOL or not 0<=time.time()-c['created']<=600:raise ValueError('stale/wrong credential')
    if package_files(base)!=c['package']:raise ValueError('package changed after CPU preflight')
    for name,row in c['sources'].items():
        if identity(name)!=row['identity'] or (large_files and sha(name)!=row['sha256']):raise ValueError('source changed after preflight: '+name)
    return c


def check_telemetry(row):
    if any(r['min']!=r['target'] or r['max']!=r['target'] or r['cur']!=r['target'] for r in row['limits']):raise RuntimeError('fixed frequency deviation; preserve batch, no retry')
    if row.get('emc_bpmp_status')!='READ' or row.get('emc_bpmp_rate_hz')!=3199000000:raise RuntimeError('independent EMC actual frequency unknown/deviated')
    row['temp_mC']=int(Path('/sys/devices/virtual/thermal/thermal_zone0/temp').read_text())
    row['MemAvailable_B']=next(int(l.split()[1])*1024 for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
    if row['temp_mC']>=80000 or row['MemAvailable_B']<12*1024**3:raise RuntimeError('thermal/memory stop')


def scope(base,run,credential_sha):
    if os.geteuid()!=0:raise PermissionError('approved transient controller only')
    c=verify_credential(base,run,credential_sha);competing_jobs()
    hw=legal_hardware()
    if any(hw[k]!=c['hardware_before'][k] for k in ('governors','power_mode')):raise RuntimeError('hardware mode changed after preflight')
    # Original minima must match the credential; a changed host needs a new
    # review/preflight, never restore old planning values.
    if hw['nodes']!=c['hardware_before']['nodes']:
        for now,before in zip(hw['nodes'],c['hardware_before']['nodes']):
            if any(now[k]!=before[k] for k in ('path','min','max','available','target')):raise RuntimeError('hardware changed after preflight')
    claim=run/'MODEL_ATTEMPT_USED';claim.mkdir(exist_ok=False)
    tx=SnapshotTransaction(run/'clock_before.json');child=None;rows=[];error=None;restored=False
    began=time.monotonic();old={}
    def interrupted(sig,*_):raise InterruptedError('scope signal '+str(sig))
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):old[sig]=signal.signal(sig,interrupted)
    # Independent timer includes root preparation; reserve >=60s restoration.
    old_alarm=signal.signal(signal.SIGALRM,interrupted);signal.alarm(300)
    try:
        lib=ctypes.CDLL(None,use_errno=True)
        if lib.prctl(36,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),'subreaper')
        apply(tx.path,transaction=tx)
        # Bounded read-only stabilization, BEFORE warmup/autotune/model.
        until=time.monotonic()+3
        while True:
            row=telemetry();row['phase']='fixed_condition_admission';rows.append(row)
            try:check_telemetry(row);break
            except RuntimeError:
                if time.monotonic()>=until:raise
                time.sleep(.05)
        if time.monotonic()-began>60:raise TimeoutError('insufficient scope time for one model and cleanup')
        env=['COOVERLAP_APPROVED_BATCH='+PROTOCOL,'PYTHONDONTWRITEBYTECODE=1',
             'PYTHONPATH='+str(base)+':'+DIAG+':'+FLASH]
        command=['/usr/sbin/runuser','-u','nvidia','--','/usr/bin/env','-i','HOME=/home/nvidia','USER=nvidia','PATH=/usr/bin:/bin',*env,
                 '/usr/bin/timeout','--signal=TERM','--kill-after=10s','180s',PYTHON,str(base/'pi05_m3_b4_ablation.py'),
                 '--approved-m3-b4-split-priority-ablation-v1','--verification-mode','performance','--config',str(base/'CONFIG.json'),
                 '--reference',str(base/'reference'),'--source-preflight',str(run/'PREFLIGHT.json'),'--out',str(run/'model')]
        dump(run/'MODEL_COMMAND.json',command)
        with (run/'model.log').open('x') as log:
            child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            while True:
                row=telemetry();row['phase']='model';rows.append(row);check_telemetry(row)
                rc=child.poll()
                if rc is not None:
                    if rc:raise RuntimeError('single model exit '+str(rc))
                    break
                if time.monotonic()-began>=300:raise TimeoutError('controller internal300s')
                time.sleep(1)
    except BaseException as exc:error=repr(exc)
    finally:
        signal.alarm(0)
        for sig in old:signal.signal(sig,signal.SIG_IGN)
        try:
            if child is not None:stop_children(child)
            restored=tx.recover()
        except BaseException as exc:error=(error or '')+' CLEANUP_OR_RESTORE_FAILED '+repr(exc)
        # No root JSON serialization or telemetry disk writes while the model
        # executes. Child cleanup and hardware restoration have finished here.
        dump(run/'ROOT_TELEMETRY.json',rows)
        dump(run/'SCOPE_RESULT.json',dict(status='PASS' if not error and restored else 'FAIL_OR_INCOMPLETE',
                    error=error,restored=restored,elapsed_s=time.monotonic()-began,
                    snapshot=str(tx.path),samples=len(rows)))
        for sig,h in old.items():signal.signal(sig,h)
        signal.signal(signal.SIGALRM,old_alarm)
    if error or not restored:raise RuntimeError(error or 'no restoration receipt')


def submit(base,run,credential_sha):
    if os.geteuid()!=0:raise PermissionError('user executes approved sudo interactively')
    verify_credential(base,run,credential_sha);legal_hardware();competing_jobs()
    (run/'SCOPE_ATTEMPT_USED').mkdir(exist_ok=False)
    command=['/usr/bin/systemd-run','--unit=cooverlap-m3-b4-ablation-20261021-run01','--wait','--collect',
             '--property=Type=exec','--property=Restart=no','--property=RuntimeMaxSec=340s',
             '--property=TimeoutStartSec=15s','--property=TimeoutStopSec=60s','--property=KillMode=mixed',
             '/usr/bin/python3',str(base/'m3_b4_control.py'),'scope','--base',str(base),'--run',str(run),
             '--credential-sha',credential_sha,'--approved-m3-b4-split-priority-ablation-v1']
    dump(run/'SCOPE_COMMAND.json',command)
    # 340+15+60=415 <420. Timeout bounds the submitting client as well.
    try:subprocess.run(command,check=True,timeout=420)
    except subprocess.TimeoutExpired:
        subprocess.run(['/usr/bin/systemctl','stop','cooverlap-m3-b4-ablation-20261021-run01.service'],timeout=65,check=False)
        raise


def verify_restored(run):
    c=json.loads((run/'PREFLIGHT.json').read_text())
    if c['host']!=socket.gethostname() or os.geteuid()==0:raise RuntimeError('independent ordinary-user same-host readback required')
    now=state();old=c['hardware_before']['nodes']
    ok=all(a['path']==b['path'] and a['min']==b['min'] and a['max']==b['max'] for a,b in zip(now,old))
    governors={name:(Path(b)/'scaling_governor' if name.startswith('cpu') else Path(b)/'governor').read_text().strip() for name,b,*_ in NODES}
    power=subprocess.run(['/usr/sbin/nvpmodel','-q'],capture_output=True,text=True,check=True,timeout=5).stdout.strip()
    ok=ok and governors==c['hardware_before']['governors'] and power==c['hardware_before']['power_mode']
    result=dict(status='PASS' if ok else 'FAIL',independent_uid=os.geteuid(),host=socket.gethostname(),nodes=now,governors=governors,power_mode=power,
                compared_to='this batch ordinary-user preflight originals; not a historical planning snapshot')
    dump(run/'INDEPENDENT_RESTORE_READBACK.json',result);print(json.dumps(result,indent=2))
    if not ok:raise RuntimeError('restore readback mismatch')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('operation',choices=['preflight','submit','scope','verify-restored'])
    ap.add_argument('--base',type=Path,required=True);ap.add_argument('--run',type=Path,required=True)
    ap.add_argument('--credential-sha');ap.add_argument('--approved-m3-b3-three-block-v1',action='store_true');a=ap.parse_args()
    base=a.base.resolve();run=a.run.resolve()
    if a.operation=='preflight':preflight(base,run)
    elif a.operation=='verify-restored':verify_restored(run)
    else:
        if not a.approved_m3_b3_three_block_v1 or not a.credential_sha:ap.error('new explicit approval and exact credential SHA required')
        if base!=Path(__file__).resolve().parent or run!=base/'run_01':raise ValueError('reviewed fresh base/run_01 only')
        (submit if a.operation=='submit' else scope)(base,run,a.credential_sha)


if __name__=='__main__':main()
