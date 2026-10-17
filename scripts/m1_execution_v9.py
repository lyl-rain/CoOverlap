"""Run-specific execution credentials and durable stage journal; CPU/IO only."""
import argparse,fcntl,hashlib,json,os,socket,time,shutil,subprocess
from pathlib import Path
from m1_root_trace_core_v9 import PROTOCOL,pair_config

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def put(p,obj):
    p=Path(p);tmp=p.with_name(p.name+'.tmp')
    with tmp.open('w') as f:json.dump(obj,f,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(tmp,p)
def stage(out,event,**data):
    with (Path(out)/'STAGES.jsonl').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        f.write(json.dumps(dict(event=event,host_ns=time.monotonic_ns(),wall_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),pid=os.getpid(),uid=os.geteuid(),**data))+'\n');f.flush();os.fsync(f.fileno())
def signature(p):
    s=Path(p).stat();return dict(dev=s.st_dev,ino=s.st_ino,size=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns)
def environment(base):
    env=os.environ.copy()
    keys=['LD_PRELOAD','LD_LIBRARY_PATH','CUDA_VISIBLE_DEVICES','CUDA_MODULE_LOADING','CUDA_DEVICE_MAX_CONNECTIONS','CUBLAS_WORKSPACE_CONFIG','PYTORCH_CUDA_ALLOC_CONF','CUDA_LAUNCH_BLOCKING','CUDA_INJECTION64_PATH','CUDA_INJECTION32_PATH','CUPTI_INJECTION64_PATH']
    keys += [k for k in env if k.startswith(('NSYS_','KINETO_','TORCH_PROFILER_'))]
    if any(env.get(k) for k in ['CUDA_INJECTION64_PATH','CUDA_INJECTION32_PATH','CUPTI_INJECTION64_PATH']) or 'nsys' in env.get('LD_PRELOAD','').lower():raise RuntimeError('startup injection refused; not cleared')
    # Explicit reproduction of the frozen run_batch.sh exports. Other CUDA
    # environment values are preserved exactly as captured, not invented.
    selected={k:env[k] for k in set(keys+['PATH','HOME','LANG','LC_ALL','LC_CTYPE']) if k in env}
    selected.update(COOVERLAP_APPROVED_BATCH=PROTOCOL,COOVERLAP_DIAG_ROOT='/home/nvidia/rtvla/cooverlap_diag_20261014_resource',COOVERLAP_DIAG_SHA256='bee648c5b5a9821084a39bb88ed9cba9681503c1043f90a7c95ace0bb1048d78',COOVERLAP_PROBE_CUBIN='/home/nvidia/rtvla/cooverlap_isolated_limit_20261015/cooverlap_green_context_sm_probe.1.sm_87.cubin',COOVERLAP_ACTIVITY_ADAPTER=str(base/'m1_activity_adapter_v6.so'),COOVERLAP_ACTIVITY_SHA256='f479bb25a23540068b4b9ddbd93c0449b37e2c39f07f3aedd0c6feb4a50e1721',COOVERLAP_CUPTI_LIBRARY_SHA256='af7d1630292f78dc2dd412e9c74c9c318068ee8aca267f932453b45c38975787',COOVERLAP_UNIFIED_REFERENCE=str(base/'unified_reference'))
    selected.update(USER='nvidia',LOGNAME='nvidia',PYTHONDONTWRITEBYTECODE='1')
    selected['PYTHONPATH']=str(base)+':'+selected['COOVERLAP_DIAG_ROOT']+'/lib:'+selected['COOVERLAP_DIAG_ROOT']+':/home/nvidia/rtvla/FlashRT'
    return selected

def safety_before_clocks(base):
    from m1_completion_health import check_no_models
    import m1_clock_scope_v6 as clock
    no_models=check_no_models();limits=clock.state()
    if any(r['max']!=r['target'] or r['target'] not in r['available'] for r in limits):raise RuntimeError('max/support differs from authorization')
    temp=int(Path('/sys/devices/virtual/thermal/thermal_zone0/temp').read_text())
    mem=next(int(l.split()[1]) for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
    if temp>=80000 or mem<12*1024**2 or shutil.disk_usage(base).free<40*1024**3:raise RuntimeError('pre-clock thermal/memory/disk safety threshold')
    power=subprocess.run(['nvpmodel','-q'],capture_output=True,text=True,timeout=5)
    if power.returncode or 'MAXN' not in power.stdout or power.stdout.strip().splitlines()[-1].strip()!='0':raise RuntimeError('MAXN0 not confirmed')
    return dict(limits=limits,temp_mC=temp,MemAvailable_kB=mem,known_models=no_models,power=power.stdout)

def preflight(base,out):
    from m1_run_identity import require_nvidia
    identity=require_nvidia();base=Path(base).resolve();out=Path(out).resolve()
    out.mkdir(exist_ok=False);put(out/'ATTEMPTS.json',[])
    try:
        put(out/'PREFLIGHT_HARDWARE.json',safety_before_clocks(base))
        env=environment(base);expected=json.loads((base/'unified_reference/SOURCE_CHECKPOINT_SHA256.json').read_text())
        source_count=len(expected)
        if source_count!=967:raise RuntimeError('unexpected frozen source/checkpoint count')
        # Deployment manifest, config, input fixtures, external observer and
        # extension binaries are included before clocks, not inside scope.
        for line in (base/'DEPLOY_SHA256.txt').read_text().splitlines():
            h,n=line.split(None,1);expected[str(base/n.lstrip('*'))]=h
        extra={'/tmp/cooverlap_pi05_fixed_reference.npz':'92f1a92b64352cc34010c81c1accd1cb00fcb227d0004f545b87549d5d6c544d','/tmp/cooverlap_pi05_state_versions.npz':'cabb191ec2b319c43fa769e5c8b9b8851724ef25ecff8850d118b8276124205e',env['COOVERLAP_PROBE_CUBIN']:'68374788021779b09326587e04099d1a71a1a585145aba02379bc0c8c410faad'}
        diag=list((Path(env['COOVERLAP_DIAG_ROOT'])/'lib').glob('flash_rt_gemm_diag*.so'))
        if len(diag)!=1:raise RuntimeError('isolated extension path ambiguous')
        extra[str(diag[0])]=env['COOVERLAP_DIAG_SHA256']
        extra['/home/nvidia/jetson-torch-env/lib/python3.12/site-packages/nvidia/cu13/lib/libcupti.so.13']=env['COOVERLAP_CUPTI_LIBRARY_SHA256']
        expected.update(extra);rows=[]
        for p,h in expected.items():
            before=signature(p);actual=sha(p);after=signature(p)
            if before!=after or actual!=h:raise RuntimeError('preflight mismatch: '+p)
            rows.append(dict(path=p,sha256=actual,stat=after))
        cfg=base/'APPROVED_CONFIG.json'
        if json.loads(cfg.read_text())!=pair_config():raise RuntimeError('config differs from frozen v9')
        if sha(base/'normal_v7/NORMAL_SAMPLES.csv')!=pair_config()['capture_permission']['normal_source_sha256']:raise RuntimeError('frozen v7 normal samples changed')
        c=dict(schema='m1_v9_execution_credential_v1',run_id=out.name,host=socket.gethostname(),created_wall_ns=time.time_ns(),created_host_ns=time.monotonic_ns(),protocol=PROTOCOL,base=str(base),out=str(out),source_checkpoint_count=source_count,identity=identity,environment=env,config_sha256=sha(cfg),deployment_manifest_sha256=sha(base/'DEPLOY_SHA256.txt'),files=rows)
        put(out/'PREFLIGHT.json',c);stage(out,'PREFLIGHT_OK',files=len(rows),source_checkpoint_files=source_count,credential_sha256=sha(out/'PREFLIGHT.json'))
        return c
    except BaseException as e:
        stage(out,'PREFLIGHT_FAILED',error=repr(e));raise

def quick_verify(base,out,credential_sha):
    p=Path(out)/'PREFLIGHT.json'
    if sha(p)!=credential_sha:raise RuntimeError('credential changed')
    c=json.loads(p.read_text())
    if c['schema']!='m1_v9_execution_credential_v1' or c['host']!=socket.gethostname() or c['base']!=str(Path(base).resolve()) or c['out']!=str(Path(out).resolve()) or c['protocol']!=PROTOCOL:raise RuntimeError('credential identity mismatch')
    if sha(Path(base)/'DEPLOY_SHA256.txt')!=c['deployment_manifest_sha256']:raise RuntimeError('deployment manifest changed')
    age=time.time_ns()-c['created_wall_ns']
    if not 0<=age<=3600*10**9:raise RuntimeError('credential expired; no clocks applied')
    for r in c['files']:
        if signature(r['path'])!=r['stat']:raise RuntimeError('preflight invalidated: '+r['path'])
    # Rehash only small execution/deployment/config files; no large checkpoint
    # scan inside hardware scope. All verified large-file identities must match.
    for r in c['files']:
        if str(Path(base)) in r['path'] and r['stat']['size']<8*1024*1024 and sha(r['path'])!=r['sha256']:raise RuntimeError('execution file changed: '+r['path'])
    return c

def observe(out,seen):
    path=Path(out)/'pair/result.json'
    try:r=json.loads(path.read_text())
    except (OSError,ValueError):return
    p=r.get('pair',{})
    findings={}
    if r.get('identity',{}).get('pid') and 'MODEL_PID_CONFIRMED' not in seen:
        stage(out,'MODEL_PID_CONFIRMED',model_pid=r['identity']['pid']);seen.add('MODEL_PID_CONFIRMED')
    if r.get('gate')=='PASS':findings['REFERENCE_GATE_RESULT']=dict(status='PASS',basis='same-process and frozen cross-process gate in durable model result')
    if r.get('status')=='FAIL' and 'REFERENCE_GATE_RESULT' not in seen and not p:findings['REFERENCE_GATE_RESULT']=dict(status='FAIL',checks=[v for v in r.get('checks',[]) if not v.get('pass_',True)])
    if p.get('normal_stage_status')=='REUSED_V7_NORMAL12_NOT_RERUN':findings['NORMAL_SAMPLES_REUSED']=dict(status='REUSED_V7',new_count=0)
    if 'collector_enable_return_ns' in p:findings['COLLECTOR_ENABLED']=dict(status='RETURNED',model_host_ns=p['collector_enable_return_ns'])
    if p.get('collector_reference_status','').startswith(('PASS','FAIL')):findings['POST_ENABLE_GATE_RESULT']=dict(status=p['collector_reference_status'])
    count=sum(s.get('role')=='diagnostic' and s.get('status')=='PASS' for s in p.get('samples',[]))
    if count==4:findings['DIAGNOSTIC_SAMPLES_SAVED']=dict(status='PASS',count=4)
    for name,data in findings.items():
        if name not in seen:stage(out,name,observation='controller read of existing durable result; timestamp is observation, not GPU completion',**data);seen.add(name)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--base',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();preflight(a.base,a.out)
