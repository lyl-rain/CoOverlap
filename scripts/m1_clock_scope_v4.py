"""Prepared ONLY: narrow five-minimum frequency scope with exact restoration."""
import argparse,json,os,socket,subprocess,signal,time,ctypes,uuid,stat
from pathlib import Path
NODES=[('cpu0','/sys/devices/system/cpu/cpufreq/policy0','scaling_min_freq','scaling_max_freq','scaling_available_frequencies','scaling_cur_freq',2201600),('cpu4','/sys/devices/system/cpu/cpufreq/policy4','scaling_min_freq','scaling_max_freq','scaling_available_frequencies','scaling_cur_freq',2201600),('cpu8','/sys/devices/system/cpu/cpufreq/policy8','scaling_min_freq','scaling_max_freq','scaling_available_frequencies','scaling_cur_freq',2201600),('gpu','/sys/class/devfreq/17000000.gpu','min_freq','max_freq','available_frequencies','cur_freq',1300500000),('emc','/sys/class/devfreq/bwmgr','min_freq','max_freq','available_frequencies','cur_freq',3199000000)]
BPMP_RATE='/sys/kernel/debug/bpmp/debug/clk/emc/rate' # read only, never written
READBACK_TIMEOUT_S=1.0
READBACK_POLL_S=0.01

def write_min_once(path,value,phase):
    """One write, then bounded READ-ONLY observation; never rewrite/retry."""
    print(json.dumps(dict(event='MIN_WRITE_BEGIN',phase=phase,node=str(path),target=value,host_ns=time.monotonic_ns())),flush=True)
    path.write_text(str(value))
    deadline=time.monotonic()+READBACK_TIMEOUT_S;samples=[]
    while True:
        observed=int(path.read_text());now=time.monotonic()
        samples.append(dict(host_ns=time.monotonic_ns(),observed=observed))
        if observed==value:
            print(json.dumps(dict(event='MIN_READBACK_PASS',phase=phase,node=str(path),target=value,samples=samples)),flush=True);return
        if now>=deadline:
            info=dict(event='MIN_READBACK_FAIL',phase=phase,node=str(path),target=value,observed=observed,timeout_s=READBACK_TIMEOUT_S,samples=samples)
            print(json.dumps(info),flush=True);raise RuntimeError(json.dumps(info))
        time.sleep(min(READBACK_POLL_S,deadline-now))

class SnapshotTransaction:
    """Recovery responsibility exists BEFORE apply; never adopts old files."""
    def __init__(self,snapshot):
        self.path=Path(snapshot)
        if os.path.lexists(self.path):raise FileExistsError('snapshot reuse refused: '+str(self.path))
        self.token=uuid.uuid4().hex;self.identity=None;self.writes_started=False
    def persist(self,nodes):
        with self.path.open('x') as f:
            st=os.fstat(f.fileno());self.identity=(st.st_dev,st.st_ino)
            os.fchmod(f.fileno(),0o600)
            json.dump(dict(schema='m1_clock_minima_v1',transaction_id=self.token,host=socket.gethostname(),nodes=nodes),f,indent=2)
            f.flush();os.fsync(f.fileno())
    def owns_valid_snapshot(self):
        try:
            st=self.path.lstat()
            if not stat.S_ISREG(st.st_mode) or self.identity!=(st.st_dev,st.st_ino):return False
            s=json.loads(self.path.read_text());validate_snapshot(s)
            return s.get('transaction_id')==self.token
        except (OSError,ValueError,KeyError,TypeError):return False
    def recover(self,root=Path('/')):
        if self.owns_valid_snapshot():restore(self.path,root);return True
        if self.writes_started:raise RuntimeError('OWNED_VALID_SNAPSHOT_LOST: manual recovery required')
        return False # failure before durable snapshot: never restore another file

def validate_snapshot(s):
    allowed={str(Path(b)/mn) for _,b,mn,_,_,_,_ in NODES}
    if s.get('schema')!='m1_clock_minima_v1' or len(s['nodes'])!=5 or {v['path'] for v in s['nodes']}!=allowed or s['host']!=socket.gethostname():raise ValueError('restore whitelist/host/schema mismatch')
    if any(type(r['min']) is not int or r['min']<0 or r['min']>r['max'] for r in s['nodes']):raise ValueError('invalid original minima')
def state(root=Path('/')):
    rows=[]
    for name,base,mn,mx,av,cur,target in NODES:
        p=root/base.lstrip('/');rows.append(dict(name=name,path=str(Path(base)/mn),min=int((p/mn).read_text()),max=int((p/mx).read_text()),cur=int((p/cur).read_text()),available=list(map(int,(p/av).read_text().split())),target=target))
    return rows

def restore(snapshot,root=Path('/')):
    s=json.loads(Path(snapshot).read_text());validate_snapshot(s)
    errors=[]
    for row in reversed(s['nodes']):
        try:
            p=root/row['path'].lstrip('/');write_min_once(p,int(row['min']),'restore')
        except Exception as e:errors.append(dict(path=row['path'],error=repr(e)))
    if errors:raise RuntimeError('RESTORE_ERRORS '+json.dumps(errors))

def apply(snapshot,root=Path('/'),transaction=None):
    tx=transaction if transaction is not None else SnapshotTransaction(snapshot)
    if tx.path!=Path(snapshot):raise ValueError('transaction snapshot mismatch')
    before=state(root)
    for r in before:
        if r['max']!=r['target'] or r['target'] not in r['available']:raise ValueError('frequency/mode differs from reviewed state')
    try:
        tx.persist(before)
        if not tx.owns_valid_snapshot():raise RuntimeError('snapshot not durable/owned/valid')
        tx.writes_started=True
        for row in before:
            p=root/row['path'].lstrip('/');write_min_once(p,row['target'],'apply')
        after=state(root)
        if any(r['min']!=r['target'] or r['max']!=r['target'] for r in after):raise RuntimeError('FINAL_REQUEST_LIMIT_MISMATCH '+json.dumps(after))
        return after
    except BaseException:
        if transaction is not None:raise # scope owns recovery, including return gap
        handlers={s:signal.signal(s,signal.SIG_IGN) for s in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP)}
        try:tx.recover(root)
        finally:
            for s,h in handlers.items():signal.signal(s,h)
        raise

def telemetry(root=Path('/')):
    r=dict(monotonic_ns=time.monotonic_ns(),reader_uid=os.geteuid(),limits=state(root))
    try:r['bwmgr_requested_target_hz']=int((root/'sys/class/devfreq/bwmgr/target_freq').read_text())
    except (OSError,ValueError):r['bwmgr_requested_target_hz']=None
    r['emc_bpmp_read_begin_ns']=time.monotonic_ns()
    try:r['emc_bpmp_rate_hz']=int((root/BPMP_RATE.lstrip('/')).read_text());r['emc_bpmp_status']='READ'
    except (OSError,ValueError) as e:r.update(emc_bpmp_rate_hz=None,emc_bpmp_status='UNKNOWN',emc_bpmp_error=repr(e))
    r['emc_bpmp_read_end_ns']=time.monotonic_ns()
    return r

def descendants():
    parents={}
    for p in Path('/proc').glob('[0-9]*/status'):
        try:parents[int(p.parent.name)]=next(int(l.split()[1]) for l in p.read_text().splitlines() if l.startswith('PPid:'))
        except (OSError,ValueError,StopIteration):pass
    owned={os.getpid()};changed=True
    while changed:
        added={pid for pid,ppid in parents.items() if ppid in owned}-owned;changed=bool(added);owned|=added
    return owned-{os.getpid()}

def stop_children(child):
    # The scope is a Linux subreaper; orphaned timeout/model descendants remain
    # its own children. Never target unrelated nvidia processes.
    def send(sig):
        for pid in descendants():
            try:os.kill(pid,sig)
            except ProcessLookupError:pass
    send(signal.SIGTERM);end=time.monotonic()+10
    while time.monotonic()<end:
        child.poll()
        try:
            while os.waitpid(-1,os.WNOHANG)[0]:pass
        except ChildProcessError:pass
        if not descendants():return
        time.sleep(.05)
    send(signal.SIGKILL);end=time.monotonic()+3
    while time.monotonic()<end:
        try:
            while os.waitpid(-1,os.WNOHANG)[0]:pass
        except ChildProcessError:pass
        if not descendants():return
        time.sleep(.05)
    raise RuntimeError('scoped descendants not reaped; require manual safety check before restoration')

def run_scope(snapshot,batch_script,timeout_s=2700):
    scope_started=time.monotonic();child=None;transaction=SnapshotTransaction(snapshot)
    def stopped(signum,*_):raise InterruptedError('scope signal '+str(signum))
    old={s:signal.signal(s,stopped) for s in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP)}
    try:
        # Before any hardware write, enable scoped descendant adoption. This
        # process-only flag does not change a persistent system configuration.
        lib=ctypes.CDLL(None,use_errno=True)
        if lib.prctl(36,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),'PR_SET_CHILD_SUBREAPER')
        apply(snapshot,transaction=transaction)
        telemetry_path=str(Path(snapshot).with_suffix('.telemetry.jsonl'))
        with open(telemetry_path,'x') as log:
            os.chmod(telemetry_path,0o644)
            child=subprocess.Popen(['/usr/sbin/runuser','-u','nvidia','--','/usr/bin/env','COOVERLAP_ROOT_TELEMETRY='+telemetry_path,'COOVERLAP_SCOPE_DEADLINE_NS='+str(int((scope_started+timeout_s-60)*1e9)),'/bin/bash',batch_script],start_new_session=True)
            deadline=scope_started+max(0,timeout_s-60) # include setup; reserve60s cleanup/restoration
            while True:
                log.write(json.dumps(telemetry())+'\n');log.flush()
                rc=child.poll()
                if rc is not None:
                    if rc:raise RuntimeError('batch exit '+str(rc))
                    break
                if time.monotonic()>=deadline:raise TimeoutError('root scope2700s bound')
                time.sleep(1)
    finally:
        # Repeated TERM/INT/HUP cannot interrupt restoration halfway. SIGKILL,
        # kernel failure or power loss remain outside automatic guarantees.
        for s in old:signal.signal(s,signal.SIG_IGN)
        try:
            if child is not None:stop_children(child)
            if transaction.recover():print('RESTORED_FIVE_MINIMA',flush=True)
        except BaseException:
            print('CLEANUP_OR_RESTORE_FAILED: preserve snapshot; check scoped processes then manual restore',flush=True);raise
        finally:
            for s,h in old.items():signal.signal(s,h)

def main():
    ap=argparse.ArgumentParser();g=ap.add_mutually_exclusive_group(required=True);g.add_argument('--inspect',action='store_true');g.add_argument('--apply',action='store_true');g.add_argument('--restore',action='store_true');g.add_argument('--scope',action='store_true');ap.add_argument('--snapshot');ap.add_argument('--batch-script');a=ap.parse_args()
    if a.inspect:print(json.dumps(state(),indent=2));return
    if os.geteuid()!=0:raise PermissionError('explicit approved sudo/root operation required')
    if not a.snapshot:raise ValueError('unique snapshot path required')
    if a.restore:restore(a.snapshot);return
    if a.scope and Path(a.batch_script).resolve()!=Path(__file__).resolve().with_name('run_batch.sh'):raise ValueError('reviewed batch script only')
    if a.apply:print(json.dumps(apply(a.snapshot),indent=2),flush=True);return
    run_scope(a.snapshot,a.batch_script)
if __name__=='__main__':main()
