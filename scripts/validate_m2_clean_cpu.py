"""Targeted CPU fault/integration tests for clean replay; never import Torch."""
import ast,contextlib,copy,hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
from m2_clean_core import *
from m2_clean_backend import CleanBackend
from m2_executor import VersionedKV,Snapshot,Handle,BLOCKS,DECODER
from m2_clean_stats import augment

SNAPS=[Snapshot('S'+str(i),*['a'*64,'b'*64,str(i)*64,'d'*64,'e'*64]) for i in (0,1)]

class Event:
    def __init__(self,done=True):self.done=done
    def query(self):return self.done

class Device:
    """Symbolic mutable device buffers, immutable copy receipts, fixed clock.

    Payload is derived from execution, independently of the retention index.
    The fake does not allocate 1GB and does not simulate GPU performance.
    """
    capacity=retention_layout()['nbytes']
    def __init__(self,slow=False,fail_at=None):
        self.now=10**9;self.active=False;self.mode='performance';self.epoch=-1;self.leased=False
        self.trace=[];self.outputs={};self.physical={};self.nextv=1;self.slow=slow;self.fail_at=fail_at;self.operations={}
    def clock(self):self.now+=100;return self.now
    def set_window(self,on,mode):self.active=on;self.mode=mode;self.trace.append(('window',on))
    def outside(self,action):
        if self.active and self.mode=='performance':raise AssertionError('forbidden '+action)
    def prepare_segment(self,epoch,conf,record):
        self.outside('prepare');assert not self.leased;self.leased=True;self.epoch=epoch
        record['segment_id']=getattr(self,'segment_id',None) or ('segment'+str(epoch))
        self.outputs={};self.operations={};self.physical={0:dict(v=0,state='full'),1:dict(v=-1,state='full')};self.nextv=1
        self.trace.append(('prepare',epoch));self.now+=100_000_000
    def bootstrap(self,m,snapshots,key):
        self.outside('bootstrap');h=m.begin(0,snapshots[0]);e=Event()
        for b in (0,1):m.submit_block(h,b,snapshots[0],BLOCKS[b],e);assert m.poll_block(h)
        m.publish(h);self.physical[0].update(v=0,state='full');self.now+=100_000_000;self.trace.append(('bootstrap',))
    def ready(self,initial):
        self.outside('initial checks/report/drain');self.trace.append(('ready',self.clock()));self.now+=100_000_000
    def restore(self,slot,images,observer=None):
        assert self.active;self.trace.append(('restore',slot,images));self.physical[slot]['noise']='fixed'
        if observer is not None:
            if images:
                observer.restore_before('images')
                observer.restore_after('images')
            observer.restore_before('noise')
            observer.restore_after('noise')
    def capture(self,e,slot):
        assert self.active;s=self.physical[slot]
        if e['shape'] in ('images','noise'):value=(e['shape'],'fixed')
        elif e['shape']=='raw':value=('raw',s['raw_job'],s['raw_version'])
        else:value=(s['state'],s['v'])
        self.outputs[e['key']]=copy.deepcopy(value);self.trace.append(('capture',e['key'],slot))
    def mark(self,key,index,observer=None):
        if observer is not None:observer.event_before(key,index)
        if index==0:self.operations[key]=dict(submitted=True,completed=False)
        self.now+=100
        if observer is not None:observer.event_after(key,index)
        return Event()
    def run_math(self,key,slot,kind):
        self.trace.append(('math',key,slot,kind))
        if key==self.fail_at:raise TimeoutError('injected unfinished work')
        s=self.physical[slot]
        if kind=='Expert':
            assert s['state']=='full';s.update(raw_job=key,raw_version=s['v'],noise='overwritten')
            self.now+=500_000_000 if self.slow else 180_000_000
            return DECODER
        if kind=='B1':s.update(v=self.nextv,state='mid');self.nextv+=1
        else:s['state']='full'
        self.now+=70_000_000;return BLOCKS[0 if kind=='B1' else 1]
    def wait_event(self,event,observer=None):
        if observer is not None:observer.event7_wait_before()
        assert event.query()
        self.clock()
        if observer is not None:observer.event7_wait_after(1)
        return self.clock()
    def wait_release(self,release):self.trace.append(('release',release));self.now=max(self.now,release)
    def complete_op(self,key,lower,upper,keys):self.operations[key].update(completed=True,lower_ns=lower,upper_ns=upper)
    def audit_ready(self,entries):self.outside('numeric/D2H');self.trace.append(('eager_compare',len(entries)))
    def audit_and_persist(self,layout,metadata):
        self.outside('D2H/compare/write');assert len(metadata)==layout['count'];self.trace.append(('deferred',))
        checks=[]
        for e in layout['entries']:
            value=self.outputs[e['key']]
            wanted=(e['shape'],'fixed') if e['shape'] in ('noise','images') else ('raw',e['job'],e['version']) if e['shape']=='raw' else (e['shape'],e['version'])
            checks.append(value==wanted)
        return dict(pass_=all(checks),persisted=True)
    def release_bank(self):self.outside('reuse');self.leased=False


def replay(mode='serial_adjacent',observation='performance',slow=False,fail_at=None):
    d=Device(slow,fail_at);b=CleanBackend(d,SNAPS,observation);m=VersionedKV();r={}
    replay_segment(m,SNAPS,mode,b,r,d.clock)
    return d,b,m,r

class CleanTests(unittest.TestCase):
    def test_exact_layout_and_memory(self):
        l=retention_layout();self.assertEqual(l['nbytes'],974640128);self.assertEqual(l['count'],128)
        end=0
        for e in l['entries']:self.assertEqual(e['offset'],end);end+=e['nbytes']
        self.assertEqual(end,l['nbytes']);self.assertEqual(sum(e['shape']=='raw' for e in l['entries']),16)
        self.assertEqual(gate_retention_layout()['count'],12)
    def test_capacity_refuses_before_launch(self):
        with self.assertRaises(ValueError):RetentionLedger(retention_layout(),974640127)
    def test_generation_and_snapshot_binding(self):
        l=RetentionLedger(retention_layout(),Device.capacity);l.begin(0)
        for wrong in (Handle(0,2,0),Handle(1,1,0),Handle(0,1,2)):
            with self.assertRaises(ValueError):l.claim('E0/pre',wrong,SNAPS[0])
        with self.assertRaises(ValueError):l.claim('E0/pre',Handle(0,1,0),SNAPS[1])
        l.claim('E0/pre',Handle(0,1,0),SNAPS[0]);self.assertEqual(l.metadata()[0]['state_sha'],'0'*64)
        with self.assertRaises(RuntimeError):l.claim('E0/pre',Handle(0,1,0),SNAPS[0])
    def test_missing_and_unfinished_retention(self):
        d,b,m,r=replay();key='E0/raw';c=b.bank.claims.pop(key)
        with self.assertRaises(RuntimeError):b.bank.complete()
        b.bank.claims[key]=c;c['event']=Event(False)
        with self.assertRaises(RuntimeError):b.bank.complete()
        with self.assertRaises(RuntimeError):b.bank.release(True)
    def test_no_reuse_until_verified_and_persisted(self):
        d,b,m,r=replay()
        with self.assertRaises(RuntimeError):b.bank.begin(1)
        with self.assertRaises(RuntimeError):b.bank.release(True)
        b.bank.mark_verified()
        with self.assertRaises(RuntimeError):b.bank.release(False)
        b.validate_and_persist();self.assertTrue(b.bank.reusable);self.assertFalse(d.leased)
        b.prepare(VersionedKV(),None,{})
        with self.assertRaises(RuntimeError):b.bank.begin(1)
    def test_deferred_reads_survive_all_source_overwrites(self):
        for mode in set(ORDER):
            d,b,m,r=replay(mode);retained=copy.deepcopy(d.outputs)
            d.physical={0:dict(v=999,state='destroyed'),1:dict(v=999,state='destroyed')}
            self.assertTrue(b.validate_and_persist()['pass_']);self.assertEqual(retained,d.outputs)
            self.assertEqual(d.outputs['E0/raw'],('raw','E0',0));self.assertEqual(d.outputs['E15/raw'],('raw','E15',7))
    def test_all_jobs_compared_not_last_output(self):
        d,b,m,r=replay();d.outputs['E0/raw']=d.outputs['E15/raw']
        with self.assertRaises(AssertionError):b.validate_and_persist()
        self.assertFalse(b.bank.reusable)
    def test_modes_have_equal_manifest_versions_and_layer_work(self):
        runs=[replay(mode) for mode in ORDER];self.assertEqual(len(runs),4)
        for d,b,m,r in runs:
            self.assertEqual(r['manifest'],protocol()['manifest']);self.assertEqual(len(r['experts']),16)
            self.assertEqual(len(r['units']),16);self.assertEqual(len(r['published']),8)
            binds=[j for j in m.journal if j[0]=='bind']
            self.assertEqual([x[2] for x in binds],[j//2 for j in range(16)])
            self.assertEqual(sum(x[0]=='math' and x[3]=='Expert' for x in d.trace),16)
            self.assertEqual(sum(x[0]=='math' and x[3] in ('B1','B2') for x in d.trace),16)
            self.assertEqual(r['initial_state'],runs[0][3]['initial_state']);b.validate_and_persist()
    def test_correctness_performance_share_math_and_schedule(self):
        for mode in set(ORDER):
            d1,b1,m1,r1=replay(mode,'performance');d2,b2,m2,r2=replay(mode,'correctness')
            self.assertEqual([x for x in d1.trace if x[0] in ('math','capture','restore')],
                             [x for x in d2.trace if x[0] in ('math','capture','restore')])
            self.assertEqual(m1.journal,m2.journal);self.assertFalse(any(x[0]=='eager_compare' for x in d1.trace))
            self.assertTrue(any(x[0]=='eager_compare' for x in d2.trace));b1.validate_and_persist();b2.validate_and_persist()
    def test_t0_after_all_setup_no_completion_reset(self):
        d,b,m,r=replay(slow=True)
        ready=next(x[1] for x in d.trace if x[0]=='ready');self.assertGreater(r['t0_ns'],ready)
        self.assertEqual([x[1] for x in d.trace if x[0]=='release'],[r['t0_ns']+j*PERIOD_NS for j in range(16)])
        self.assertEqual(r['statistics']['cycle_counts']['denominator'],16)
        self.assertEqual(r['statistics']['cycles'][0]['cycle'],0);self.assertEqual(len(r['experts']),16)
        self.assertEqual(r['statistics']['backlog'],0);self.assertIsNone(r['statistics']['k_min'])
        b.validate_and_persist()
    def test_runtime_costs_inside_window(self):
        d,b,m,r=replay();active=False
        for row in d.trace:
            if row[0]=='window':active=row[1]
            if row[0] in ('restore','capture','math','release'):self.assertTrue(active)
            if row[0] in ('prepare','ready','bootstrap','deferred'):self.assertFalse(active)
        b.validate_and_persist()
    def test_incomplete_keeps_full_denominator_and_bank_owned(self):
        d=Device(fail_at='E3');b=CleanBackend(d,SNAPS);m=VersionedKV();r={}
        with self.assertRaises(TimeoutError):replay_segment(m,SNAPS,ORDER[0],b,r,d.clock)
        self.assertFalse(b.window);self.assertFalse(b.bank.reusable)
        self.assertEqual(r['statistics']['cycle_counts']['denominator'],16)
        self.assertGreater(r['statistics']['cycle_counts']['INCOMPLETE'],0);self.assertIsNone(r['statistics']['response_upper_p99_ns'])
        with self.assertRaises(RuntimeError):b.validate_and_persist()
    def test_statistics_json_roundtrip_and_early_B2(self):
        from pi05_m2_clean import jsonable
        d,b,m,r=replay();a=augment(r);restored=json.loads(json.dumps(jsonable(r)));self.assertEqual(a,augment(restored))
        self.assertEqual(a['completed_Experts'],16);self.assertEqual(a['completed_units'],16)
        self.assertIn('VLM_already_ready_at_release',r['statistics']['cycles'][1])
    def test_window_forbidden_guards(self):
        from m2_clean_cuda import CudaDevice
        d=CudaDevice.__new__(CudaDevice);d.window=True;d.mode='performance'
        for method in (lambda:d.download(),lambda:d.compare_entry({}),lambda:d.event_metrics(),lambda:d.prepare_segment(0,None,{}),lambda:d.release_bank()):
            with self.assertRaises(RuntimeError):method()
        d.window=False;d.guard('post-window allowed')
    def test_native_copy_direction_and_packing(self):
        from m2_clean_cuda import CudaDevice
        class Runtime:
            def __init__(self):self.rows=[]
            def cudaMemcpyAsync(self,*args):self.rows.append(('1D',args));return 0
            def cudaMemcpy2DAsync(self,*args):self.rows.append(('2D',args));return 0
        d=CudaDevice.__new__(CudaDevice);d.window=True;d.mode='performance';d.deadline=10**20;d.clock=lambda:0
        d.runtime=Runtime();d.capacity=Device.capacity;d.gptr=100;d.sources=[dict(x=200,kv=[(300,400000),(500,400000)])];d.receipts=[]
        e=dict(offset=0,nbytes=MID,shape='mid',key='test');d.capture(e,0)
        self.assertEqual([a[0] for a in d.runtime.rows],['1D','2D','2D'])
        for kind,args in d.runtime.rows:self.assertEqual(args[-2],3)
        self.assertEqual(d.runtime.rows[1][1][4:6],(KV_LAYER,9));self.assertEqual(d.runtime.rows[2][1][0].value,100+X+9*KV_LAYER)
        with self.assertRaises(RuntimeError):d.copy(0,0,1,2)
    def test_exact_frozen_work_totals(self):
        p=protocol();prep=p['prep'];contexts=p['timed']['Contexts']+sum(v.get('Contexts',0) for v in prep.values())
        experts=p['timed']['Experts']+sum(v.get('Experts',0) for v in prep.values())
        self.assertEqual((contexts,experts),(43,68));self.assertEqual(p['observed_ledger']['entries'],720+12060+40+40)
        self.assertEqual(p['retention']['batch_payload_B'],3898560512);self.assertEqual(p['scope_runtime_max_s']+p['scope_start_s']+p['scope_stop_s'],415)
    def test_D1_cross_process_is_report_only(self):
        source=(Path(__file__).parent/'pi05_m2_clean.py').read_text();tree=ast.parse(source)
        req=[ast.get_source_segment(source,n.args[0]) for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='require']
        self.assertTrue(any("digest(a)==digest(b)"==s for s in req))
        self.assertFalse(any('matches_frozen' in s or 'metrics' in s or 'within' in s for s in req))
        self.assertIn("admission=False",source);self.assertIn("PASS_IN_PROCESS_DEVIATION",source)
        self.assertEqual(source.count('p.autotune_gemms()'),1)
    def test_fixed_v3_math_modules_are_imported(self):
        src=(Path(__file__).parent/'pi05_m2_clean.py').read_text();self.assertIn('from m2_pi05_ops import context,block1,block2,CallLedger',src)
        for name in ('context','block1','block2'):
            self.assertNotIn('\ndef '+name+'(',src)
    def test_only_new_authorized_scope_model_and_no_retry(self):
        import m2_clean_control as control
        source=Path(control.__file__).read_text()
        self.assertEqual(source.count('subprocess.Popen('),1);self.assertIn("'180s',PYTHON",source)
        self.assertIn("'--property=Restart=no'",source);self.assertIn("'--approved-m2-clean-v1'",source)
        self.assertIn('SnapshotTransaction',source);self.assertIn('stop_children(child)',source)
    def test_window_callgraph_excludes_intrusive_operations(self):
        allowed={
            'm2_clean_core.py':{'replay_segment'},
            'm2_clean_backend.py':{'enter_window','leave_window','wait_release','capture','observe','stage','block','expert','drain'},
            'm2_clean_cuda.py':{'bound','set_window','restore','copy','capture','mark','run_math','wait_release','wait_event','complete_op'},
        }
        forbidden={'cpu','numpy','tobytes','compare_entry','download','elapsed_time','sha256','dumps','dump','write_text','write_bytes','fsync','empty','zeros','contiguous'}
        for name,methods in allowed.items():
            tree=ast.parse((Path(__file__).parent/name).read_text())
            for fn in ast.walk(tree):
                if isinstance(fn,(ast.FunctionDef,ast.AsyncFunctionDef)) and fn.name in methods:
                    for node in ast.walk(fn):
                        if isinstance(node,ast.Call):
                            callee=node.func.attr if isinstance(node.func,ast.Attribute) else node.func.id if isinstance(node.func,ast.Name) else ''
                            self.assertNotIn(callee,forbidden,(name,fn.name,callee))
        # The intrusive observation hook is guarded by correctness mode.
        self.assertIn("if self.mode=='correctness':",(Path(__file__).parent/'m2_clean_backend.py').read_text())
    def test_hardware_telemetry_unknown_or_deviation_stops(self):
        import m2_clean_control as c
        from unittest.mock import patch
        row=dict(limits=[dict(min=1,max=2,cur=2,target=2)],emc_bpmp_status='READ',emc_bpmp_rate_hz=3199000000)
        with self.assertRaises(RuntimeError):c.check_telemetry(row)
        row['limits'][0]['min']=2;row['emc_bpmp_status']='UNKNOWN'
        with self.assertRaises(RuntimeError):c.check_telemetry(row)
    def test_new_controller_cleanup_and_deferred_telemetry(self):
        import m2_clean_control as c
        from unittest.mock import patch
        from types import SimpleNamespace
        from contextlib import ExitStack
        for apply_fails in (False,True):
            events=[];running=[False]
            class Transaction:
                def __init__(self,path):self.path=path
                def recover(self):events.append('restore');return True
            class Child:
                def poll(self):return 0
            def launch(*a,**k):running[0]=True;events.append('launch');return Child()
            def stop(child):running[0]=False;events.append('stop')
            def write(path,data):
                if path.name in ('ROOT_TELEMETRY.json','SCOPE_RESULT.json'):self.assertFalse(running[0])
                events.append(path.name)
            def apply(*a,**k):
                events.append('apply')
                if apply_fails:raise RuntimeError('injected partial apply')
            with tempfile.TemporaryDirectory() as temp,ExitStack() as stack:
                base=Path(temp);run=base/'run_01';run.mkdir()
                values=dict(verify_credential=lambda *a,**k:dict(hardware_before=dict(nodes=[],governors={},power_mode='MAXN')),
                            legal_hardware=lambda:dict(nodes=[],governors={},power_mode='MAXN'),competing_jobs=lambda:None,
                            SnapshotTransaction=Transaction,apply=apply,telemetry=lambda:dict(limits=[],emc_bpmp_status='READ',emc_bpmp_rate_hz=3199000000),
                            check_telemetry=lambda r:None,stop_children=stop,dump=write)
                for key,value in values.items():stack.enter_context(patch.object(c,key,value))
                stack.enter_context(patch.object(c.os,'geteuid',lambda:0));stack.enter_context(patch.object(c.ctypes,'CDLL',lambda *a,**k:SimpleNamespace(prctl=lambda *a:0)))
                stack.enter_context(patch.object(c.subprocess,'Popen',launch));stack.enter_context(patch.object(c.signal,'alarm',lambda x:None))
                if apply_fails:
                    with self.assertRaises(RuntimeError):c.scope(base,run,'credential')
                    self.assertNotIn('launch',events)
                else:c.scope(base,run,'credential');self.assertLess(events.index('stop'),events.index('restore'))
                self.assertIn('restore',events);self.assertLess(events.index('restore'),events.index('ROOT_TELEMETRY.json'))
    def test_credentials_detect_package_mutation_without_GPU(self):
        import m2_clean_control as c
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);config=base/'CONFIG.json';config.write_text(json.dumps(protocol()))
            (base/'DEPLOY_SHA256.txt').write_text(c.sha(config)+'  CONFIG.json\n')
            self.assertEqual(c.package_files(base)['CONFIG.json']['sha256'],c.sha(config))
            config.write_text('{}')
            with self.assertRaises(ValueError):c.package_files(base)
    def test_saved_auditor_full_jobs_and_report_only_configuration(self):
        import audit_m2_clean_saved as auditor
        import m2_clean_core as core
        from pi05_m2_clean import jsonable
        from unittest.mock import patch
        # Tiny byte-level fixture keeps all 128 identities/obligations; this
        # tests saved-data association, not CUDA numerics or performance.
        small=copy.deepcopy(retention_layout());offset=0
        for e in small['entries']:
            e['offset']=offset;e['nbytes']=3 if e['shape'] in ('full','mid') else 1;offset+=e['nbytes']
        small['nbytes']=offset
        with tempfile.TemporaryDirectory() as temp,patch.object(core,'retention_layout',lambda:small):
            root=Path(temp);run=root/'run';base=run/'model';base.mkdir(parents=True)
            credential={'package':{'CONFIG.json':{'sha256':'a'*64}}};(run/'PREFLIGHT.json').write_text(json.dumps(credential))
            for name,data in [('SCOPE_RESULT.json',dict(status='PASS',restored=True)),('INDEPENDENT_RESTORE_READBACK.json',dict(status='PASS',independent_uid=1001)),('ROOT_TELEMETRY.json',[dict(phase='model',monotonic_ns=2000000000,limits=[dict(min=1,max=1,cur=1,target=1)],emc_bpmp_status='READ',emc_bpmp_rate_hz=3199000000)])]:
                (run/name).write_text(json.dumps(data))
            for i in (0,1):
                for key in ('context_x','context_K','context_V','mid_x','mid_K','mid_V','raw'):(base/('ref'+str(i)+'_'+key+'.bin')).write_bytes(b'a')
            segments=[]
            for n,mode in enumerate(ORDER):
                d,b,m,rec=replay(mode);rec['metrics']=augment(rec);rec['status']='PASS';rec['validation']={'records':128}
                segments.append(rec);folder=base/('segment'+str(n));folder.mkdir()
                payload=b''.join(b'a'*e['nbytes'] for e in small['entries']);(folder/'RETENTION.bin').write_bytes(payload)
                idx=dict(layout=small,claims=b.bank.metadata(),capture_receipts=[(e['key'],e['slot'],e['offset'],e['nbytes']) for e in small['entries']],comparisons=[dict(key=e['key'],exact=True,reference_sha256=hashlib.sha256(b'a'*e['nbytes']).hexdigest()) for e in small['entries']],payload_sha256=hashlib.sha256(payload).hexdigest())
                (folder/'RETENTION_INDEX.json').write_text(json.dumps(idx))
            report=dict(status='PASS_IN_PROCESS_DEVIATION',observation_mode='performance',in_process_equivalence={'byte_exact':True},protocol=core.protocol(),observed_call_counts=dict(encoder=720,decoder=12060,language=40,vision27=40),
                        source_preflight_sha256=hashlib.sha256((run/'PREFLIGHT.json').read_bytes()).hexdigest(),source_config_fingerprints={'CONFIG.json':'a'*64},segments=segments,configuration={'label':'OTHER'},cross_process=[dict(pass_=False)])
            (base/'result.json').write_text(json.dumps(jsonable(report)))
            with contextlib.redirect_stdout(io.StringIO()):auditor.audit(run,root/'good')
            self.assertEqual(json.loads((root/'good/AUDIT.json').read_text())['status'],'PASS')
            bad=base/'segment0/RETENTION.bin';data=bytearray(bad.read_bytes());data[0]=0;bad.write_bytes(data)
            with self.assertRaises(AssertionError),contextlib.redirect_stdout(io.StringIO()):auditor.audit(run,root/'bad')
            self.assertEqual(json.loads((root/'bad/AUDIT.json').read_text())['status'],'FAIL_OR_INCOMPLETE')
    def test_no_accidental_cuda_import(self):
        self.assertNotIn('torch',sys.modules);self.assertNotIn('numpy',sys.modules)

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(CleanTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    summary=dict(status='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,
                 failures=len(result.failures),errors=len(result.errors),GPU_imported='torch' in sys.modules,
                 scope_executed=False,hardware_writes=0)
    print(json.dumps(summary,indent=2));sys.exit(not result.wasSuccessful())
