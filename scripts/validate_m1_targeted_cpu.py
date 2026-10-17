"""No GPU/root/scope execution. Fake sysfs and mocked process-control tests."""
import unittest,tempfile,json,signal,ast,ctypes
from pathlib import Path
from unittest.mock import patch,Mock
import m1_clock_scope as scope
from m1_frequency_condition import assess
from m1_completion_core import select_budgets

class Targeted(unittest.TestCase):
    def test_apply_interruption_rolls_back_fake_nodes(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for name,b,mn,mx,av,cur,target in scope.NODES:
                p=root/b.lstrip('/');p.mkdir(parents=True)
                for k,v in [(mn,'1'),(mx,str(target)),(av,'1 '+str(target)),(cur,'1')]: (p/k).write_text(v)
            before=scope.state(root);original=Path.write_text;raised=[False]
            def write(p,value,*a,**kw):
                if str(p).endswith('policy4/scaling_min_freq') and value=='2201600' and not raised[0]:raised[0]=True;raise InterruptedError('mock signal during apply')
                return original(p,value,*a,**kw)
            with patch.object(Path,'write_text',write):
                with self.assertRaises(InterruptedError):scope.apply(root/'snapshot.json',root)
            self.assertEqual(before,scope.state(root))
    def test_scope_exit_paths_cleanup_before_restore(self):
        for mode in ['normal','SIGTERM','timeout']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as t:
                order=[];child=Mock();child.poll.return_value=0 if mode=='normal' else None
                if mode=='SIGTERM':child.poll.side_effect=InterruptedError('simulated SIGTERM handler')
                lib=Mock();lib.prctl.return_value=0
                def fake_apply(snapshot,transaction):
                    order.append('apply');transaction.persist([dict(path=str(Path(b)/mn),min=1,max=target) for _,b,mn,_,_,_,target in scope.NODES])
                with patch.object(scope.ctypes,'CDLL',return_value=lib),patch.object(scope,'apply',side_effect=fake_apply),patch.object(scope,'restore',side_effect=lambda *_:order.append('restore')),patch.object(scope,'stop_children',side_effect=lambda *_:order.append('stop')),patch.object(scope,'telemetry',return_value={}),patch.object(scope.subprocess,'Popen',return_value=child) as pop,patch.object(scope.signal,'signal'):
                    if mode=='normal':scope.run_scope(Path(t)/'snap.json','/reviewed/run_batch.sh',timeout_s=0)
                    else:
                        with self.assertRaises((InterruptedError,TimeoutError)):scope.run_scope(Path(t)/'snap.json','/reviewed/run_batch.sh',timeout_s=0)
                    self.assertEqual(order,['apply','stop','restore']);args=pop.call_args.args[0];self.assertEqual(args[:4],['/usr/sbin/runuser','-u','nvidia','--'])
    def test_no_restore_while_children_unconfirmed(self):
        with tempfile.TemporaryDirectory() as t:
            child=Mock();child.poll.return_value=0;lib=Mock();lib.prctl.return_value=0
            with patch.object(scope.ctypes,'CDLL',return_value=lib),patch.object(scope,'apply'),patch.object(scope,'restore') as restore,patch.object(scope,'stop_children',side_effect=RuntimeError('unreaped')),patch.object(scope,'telemetry',return_value={}),patch.object(scope.subprocess,'Popen',return_value=child),patch.object(scope.signal,'signal'):
                with self.assertRaises(RuntimeError):scope.run_scope(Path(t)/'snap.json','/reviewed/run_batch.sh')
                restore.assert_not_called()
    def test_frequency_mismatch_preserves_classification(self):
        def sample(t):return dict(monotonic_ns=t,limits=[dict(name='cpu0',min=1,max=1,target=1,cur=1)])
        d=[sample(1_000_000_000),sample(2_000_000_000)];r=[dict(monotonic_ns=s['monotonic_ns'],emc_bpmp_status='READ',emc_bpmp_rate_hz=3199000000) for s in d]
        self.assertEqual(assess(d,r,0,3_000_000_000)['status'],'SATISFIED_SAMPLED')
        d[0]['limits'][0]['cur']=0;self.assertEqual(assess(d,r,0,3_000_000_000)['status'],'NOT_MET')
        self.assertEqual(len(d),2);self.assertEqual(len(r),2) # no filtering/repair
    def test_frequency_unknown_not_pass(self):
        d=[dict(monotonic_ns=1,limits=[])]
        self.assertEqual(assess(d,[],0,10)['status'],'UNKNOWN')
        r=[dict(monotonic_ns=1,emc_bpmp_status='UNKNOWN')]
        self.assertEqual(assess(d,r,0,10)['status'],'UNKNOWN')
    def test_event_order_and_no_inner_scheduler(self):
        p=Path(__file__).with_name('pi05_m1_completion.py');tree=ast.parse(p.read_text())
        funcs={n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        s=ast.unparse(funcs['observed_B1'])
        self.assertLess(s.index('block1(p1)'),s.index('evt.record(stream)'));self.assertLess(s.index('evt.record(stream)'),s.index('retain_snap('))
        self.assertNotIn('synchronize',s);self.assertNotIn('.query(',s)
        self.assertIn('observed_B1(j), submit_B2(j)',ast.unparse(tree))
        self.assertIn('B1_begin_to_model_done_event_ms',p.read_text())
    def test_child_identity_fails_root(self):
        import m1_run_identity as ident
        with patch.object(ident.pwd,'getpwnam',return_value=Mock(pw_uid=1001,pw_gid=1001)),patch.object(ident.os,'getresuid',create=True,return_value=(0,0,0)),patch.object(ident.os,'getresgid',create=True,return_value=(0,0,0)):
            with self.assertRaises(PermissionError):ident.require_nvidia()
    def test_only_five_write_nodes(self):
        self.assertEqual(len(scope.NODES),5)
        self.assertTrue(all(n[2] in ('scaling_min_freq','min_freq') for n in scope.NODES))
        self.assertNotIn(scope.BPMP_RATE,[str(Path(n[1])/n[2]) for n in scope.NODES])

if __name__=='__main__':unittest.main(verbosity=2)
