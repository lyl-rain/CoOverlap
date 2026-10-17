"""CPU only. Real child/signal fault injection restricted to temporary fake sysfs."""
import argparse,ast,json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import m1_execution_v6 as ex
import m1_service_scope_v6 as sc
import m1_submit_service_v6 as submit

def fake_nodes(root):
    for i,(_,b,mn,mx,av,cur,target) in enumerate(sc.clock.NODES):
        p=root/b.lstrip('/');p.mkdir(parents=True)
        for n,v in [(mn,10+i),(mx,target),(av,str(target)+' '+str(10+i)),(cur,10+i)]: (p/n).write_text(str(v))
def case(directory,kind):
    d=Path(directory);root=d/'fake_sysfs';root.mkdir();fake_nodes(root);out=d/'out';out.mkdir();ex.put(out/'PREFLIGHT.json',dict(environment={}))
    before=sc.clock.state(root);ex.put(d/'original.json',before)
    original_restore=sc.clock.restore
    def checked_restore(path,actual_root):
        assert Path(actual_root).resolve()==root.resolve() and actual_root!=Path('/')
        live=sc.clock.descendants() if sys.platform=='linux' else set()
        assert not live,('restore before cleanup',live)
        ex.put(d/'cleanup_before_restore.json',{'descendants':list(live),'fake_root':str(actual_root)})
        return original_restore(path,actual_root)
    def launch(*args,**kw):
        script="from pathlib import Path;import time,sys;Path(sys.argv[1]).write_text('READY');time.sleep(float(sys.argv[2]));sys.exit(int(sys.argv[3]))"
        return subprocess.Popen([sys.executable,'-c',script,str(d/'child_ready'),'.1' if kind in ('normal','child_fail') else '30','7' if kind=='child_fail' else '0'])
    # macOS lacks Linux prctl and /proc; process/signal cases are run on the
    # actual board as nvidia, but all hardware paths point at fake_sysfs.
    patches=[patch.object(sc,'quick_verify',return_value={}),patch.object(sc.clock,'restore',side_effect=checked_restore)]
    if sys.platform!='linux':raise RuntimeError('signal/child tests require Linux /proc; no hardware access')
    original_apply=sc.clock.apply
    def injected_apply(*a,**kw):
        if kind=='before_snapshot':raise OSError('injected before snapshot')
        original_apply(*a,**kw)
        if kind=='apply_return_gap':raise InterruptedError('after apply before later statement')
    with patches[0],patches[1],patch.object(sc.clock,'apply',side_effect=injected_apply):
        try:sc.run(d,out,'fake',root,launch,deadline_s=.05 if kind=='timeout' else 5)
        except (InterruptedError,RuntimeError,TimeoutError,OSError):
            if kind=='normal':raise
    after=sc.clock.state(root);assert [r['min'] for r in after]==[r['min'] for r in before]
    result=json.loads((out/'CONTROLLER_RESULT.json').read_text())
    if kind=='before_snapshot':assert not result['automatic_restored'] and not (out/'clock_before.json').exists()
    else:
        assert result['automatic_restored'] and result['cleanup']==('NOT_REQUIRED' if kind=='apply_return_gap' else 'PASS');assert (d/'cleanup_before_restore.json').exists()
    ex.put(d/'TEST_RESULT.json',dict(status='PASS',kind=kind,result=result,all_five_original=[r['min'] for r in before],after=[r['min'] for r in after]))

class CPU(unittest.TestCase):
    def test_transient_service_bounds(self):
        c=submit.command(Path('/b'),Path('/o'),'unit','sha');s=' '.join(c)
        for term in ['Restart=no','RuntimeMaxSec=340s','TimeoutStopSec=60s','KillMode=mixed','--service-type=exec']:self.assertIn(term,s)
        self.assertNotIn('--scope',c);self.assertNotIn('--pty',c);self.assertLess(15+340+60,420)
    def test_model_and_collector_untouched(self):
        root=Path(__file__).resolve().parents[1]
        archived=root/'reports/m1_acceptance/pair_plain_20261016_v6/deployment'
        if not archived.exists():self.skipTest('deployment uses pinned SHA manifest instead of local archive')
        for n in ['pi05_m1_pair_plain_v6.py','pi05_encoder_pair_v6.py','delayed_activity_v6.py','m1_activity_adapter_v6.cpp','m1_pair_plain_core_v6.py']:
            self.assertEqual(ex.sha(root/'scripts'/n),ex.sha(archived/n),n)
    def test_preflight_invalidation(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'f';p.write_text('a');a=ex.signature(p);p.write_text('b');self.assertNotEqual(a,ex.signature(p))
    def test_observation_not_gpu_completion(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'pair').mkdir();ex.put(p/'pair/result.json',{'gate':'PASS','pair':{'normal_stage_status':'PASS','collector_enable_return_ns':8}})
            seen=set();ex.observe(p,seen);ex.observe(p,seen)
            rows=[json.loads(l) for l in (p/'STAGES.jsonl').read_text().splitlines()];self.assertEqual(len(rows),3)
            self.assertTrue(all('observation' in r for r in rows));self.assertEqual(rows[-1]['model_host_ns'],8)
    def test_existing_submission_status_only(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'SERVICE_SUBMISSION.json').write_text('{}')
            with patch.object(sys,'argv',['submit','--base',t,'--out',t,'--credential-sha','x']),patch.object(submit.os,'geteuid',return_value=0),patch.object(submit.subprocess,'run') as call,patch.object(submit,'quick_verify') as check:
                submit.main();check.assert_not_called();self.assertEqual(call.call_count,1);self.assertEqual(call.call_args.args[0][1],'show')
    def test_no_expensive_scan_inside_launcher(self):
        s=Path(__file__).with_name('m1_service_launch_v6.py').read_text();self.assertNotIn('for path in frozen',s);self.assertNotIn('SOURCE_CHECKPOINT_SHA256',s)
        self.assertIn('quick_verify',s);self.assertIn("'175s'",s);self.assertIn('MODEL_EXIT',s)
    def test_no_expensive_scan_inside_scope(self):
        s=Path(sc.__file__).read_text();self.assertNotIn('preflight(',s);self.assertLess(s.index('SnapshotTransaction'),s.index('clock.apply'))
        self.assertLess(s.index('clock.stop_children'),s.index('tx.recover'))
    def test_credential_change_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'PREFLIGHT.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'credential changed'):ex.quick_verify(p,p,'wrong')

if __name__=='__main__':
    if '--case' in sys.argv:
        i=sys.argv.index('--case');case(sys.argv[i+2],sys.argv[i+1])
    elif '--signals' in sys.argv:
        parent=Path(sys.argv[sys.argv.index('--signals')+1]);parent.mkdir(exist_ok=False)
        for kind in ['normal','child_fail','timeout','SIGINT','SIGTERM','SIGHUP','apply_return_gap','before_snapshot']:
            d=parent/kind;d.mkdir();p=subprocess.Popen([sys.executable,__file__,'--case',kind,str(d)],stdout=(d/'stdout.log').open('w'),stderr=subprocess.STDOUT)
            if kind.startswith('SIG'):
                end=time.monotonic()+5
                while not (d/'child_ready').exists() and p.poll() is None and time.monotonic()<end:time.sleep(.01)
                assert (d/'child_ready').exists(),'fake child did not start';os.kill(p.pid,getattr(signal,kind))
            rc=p.wait(timeout=12);assert rc==0,(kind,rc,(d/'stdout.log').read_text());print(kind+' PASS',flush=True)
    else:unittest.main(verbosity=2)
