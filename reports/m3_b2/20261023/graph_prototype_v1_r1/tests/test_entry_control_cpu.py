import copy,hashlib,json,os,shutil,signal,socket,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];D=HERE/'deployment'
sys.path[:0]=[str(D),str(HERE/'tests')]
import graph_control as c,pi05_graph_validation as entry
from graph_plan import RUN,PROTOCOL,protocol
from test_graph_cpu import run
from graph_evaluate import evaluate


class EntryControlCPU(unittest.TestCase):
    def package(self,tmp):
        base=Path(tmp)/'deployment';shutil.copytree(D,base,ignore=shutil.ignore_patterns('__pycache__'))
        run=base/'run_01';run.mkdir()
        cred=dict(host=socket.gethostname(),base=str(base.resolve()),run=str(run.resolve()),protocol=PROTOCOL,
                  created=time.time(),package=c.package_files(base),sources={})
        (run/'PREFLIGHT.json').write_text(json.dumps(cred))
        return base,run,cred

    def test_real_entry_credential_to_prepare_without_cuda(self):
        with tempfile.TemporaryDirectory() as tmp:
            base,run,cred=self.package(tmp);old=signal.getsignal(signal.SIGTERM)
            args=['--approved-m3-symmetric-graph-v1-r1','--verification-mode','performance','--config',str(base/'CONFIG.json'),
                  '--reference',str(base/'reference'),'--source-preflight',str(run/'PREFLIGHT.json'),'--out',str(run/'model')]
            try:
                with patch.dict(os.environ,COOVERLAP_APPROVED_BATCH=PROTOCOL),patch.object(entry,'prepare',side_effect=RuntimeError('CPU_PREPARE_SENTINEL')) as prep:
                    with self.assertRaisesRegex(RuntimeError,'CPU_PREPARE_SENTINEL'):entry.main(args)
                    self.assertEqual(prep.call_count,1)
                report=json.loads((run/'model/result.json').read_text())
                self.assertEqual(report['status'],'FAIL_OR_INCOMPLETE')
                self.assertEqual(len(report['segments']),8)
                self.assertNotIn('torch',sys.modules)
            finally:signal.signal(signal.SIGTERM,old)

    def test_wrong_or_expired_credential_refused_before_prepare(self):
        for kind in ('protocol','expired'):
            with tempfile.TemporaryDirectory() as tmp:
                base,run,cred=self.package(tmp)
                if kind=='protocol':cred['protocol']='m3_b10_credible_selector_validation_v1'
                else:cred['created']-=601
                (run/'PREFLIGHT.json').write_text(json.dumps(cred))
                with patch.dict(os.environ,COOVERLAP_APPROVED_BATCH=PROTOCOL),patch.object(entry,'prepare') as prep:
                    with self.assertRaisesRegex(ValueError,'stale/wrong credential'):
                        entry.main(['--approved-m3-symmetric-graph-v1-r1','--config',str(base/'CONFIG.json'),'--reference',str(base/'reference'),
                                    '--source-preflight',str(run/'PREFLIGHT.json'),'--out',str(run/'model')])
                    self.assertFalse(prep.called);self.assertFalse((run/'model').exists())

    def test_missing_approval_is_refused(self):
        with patch.object(entry,'prepare') as prep:
            with self.assertRaises(SystemExit):entry.main([])
            self.assertFalse(prep.called)

    def test_package_change_and_credential_sha_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base,run,cred=self.package(tmp);fp=run/'PREFLIGHT.json'
            with self.assertRaisesRegex(ValueError,'credential SHA changed'):c.verify_credential(base,run,'0'*64)
            with (base/'graph_backend.py').open('a') as f:f.write('\n# changed\n')
            with self.assertRaisesRegex(ValueError,'deployment SHA differs'):c.verify_credential(base,run,c.sha(fp))

    def before(self):
        return dict(nodes=[dict(path='/node/'+str(i),min=1,max=10) for i in range(5)],governors={},power_mode='MAXN')

    def test_snapshot_mismatch_rejected_before_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            before=self.before();t=c.CheckedTransaction(Path(tmp)/'root.json',before)
            changed=copy.deepcopy(before['nodes']);changed[0]['min']=10
            with self.assertRaises(RuntimeError):t.persist(changed)
            self.assertFalse(t.path.exists())

    def test_restore_true_but_readback_fail_is_failure(self):
        tx=type('TX',(),{'recover':lambda self:True})()
        with patch.object(c,'readback',return_value=dict(status='FAIL')):
            ok,receipt=c.recover_checked(tx,self.before())
        self.assertFalse(ok);self.assertEqual(receipt['status'],'FAIL')
        self.assertFalse(c.original_nodes_equal([],[]))
        self.assertFalse(c.original_nodes_equal(self.before()['nodes'][:1],self.before()['nodes']))

    def test_independent_fail_is_preserved_on_later_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'PREFLIGHT.json').write_text(json.dumps(dict(host=socket.gethostname(),hardware_before=self.before())))
            (p/'SCOPE_RESULT.json').write_text(json.dumps(dict(status='PASS',restored=True)))
            with patch.object(c.os,'geteuid',return_value=1001),patch.object(c,'readback',return_value=dict(status='FAIL')):
                with self.assertRaises(RuntimeError):c.verify_restored(p)
            first=(p/'INDEPENDENT_RESTORE_READBACK.json').read_bytes()
            with patch.object(c.os,'geteuid',return_value=1001),patch.object(c,'readback',return_value=dict(status='PASS')):
                c.verify_restored(p)
            self.assertEqual((p/'INDEPENDENT_RESTORE_READBACK.json').read_bytes(),first)
            self.assertEqual(json.loads((p/'INDEPENDENT_RESTORE_READBACK_02.json').read_text())['hardware_closeout'],'PASS')

    def test_independent_pass_does_not_erase_scope_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'PREFLIGHT.json').write_text(json.dumps(dict(host=socket.gethostname(),hardware_before=self.before())))
            (p/'SCOPE_RESULT.json').write_text(json.dumps(dict(status='FAIL_OR_INCOMPLETE',restored=False)))
            with patch.object(c.os,'geteuid',return_value=1001),patch.object(c,'readback',return_value=dict(status='PASS')):
                with self.assertRaises(RuntimeError):c.verify_restored(p)
            self.assertEqual(json.loads((p/'INDEPENDENT_RESTORE_READBACK.json').read_text())['hardware_closeout'],'FAIL')

    def test_not_started_all_denominators_retained(self):
        report=dict(segments=[dict(x,status='NOT_STARTED') for x in RUN])
        e=evaluate(report)
        self.assertEqual((e['totals']['Expert']['INCOMPLETE'],e['totals']['Cycle']['INCOMPLETE'],e['totals']['Refresh']['INCOMPLETE']),(64,64,32))

    def test_json_roundtrip_official_counts_and_partial(self):
        report=dict(segments=[dict(x,status='NOT_STARTED') for x in RUN])
        d,b,m,r=run('B');report['segments'][1].update(r)
        self.assertEqual(evaluate(report)['totals']['Cycle']['INCOMPLETE'],56)
        raw=entry.jsonable(report)
        self.assertEqual(evaluate(json.loads(json.dumps(raw)))['totals'],evaluate(report)['totals'])
        report['segments'][1]['plan']='wrong'
        with self.assertRaises(ValueError):evaluate(report)

    def test_actual_persistence_method_defines_complete_counts(self):
        from m2_clean_cuda import CudaDevice
        with tempfile.TemporaryDirectory() as tmp:
            d=CudaDevice.__new__(CudaDevice);d.window=False;d.mode='performance';d.out=Path(tmp)
            d.segment_id='tiny';d.host_view=memoryview(bytearray(4));d.receipts=[];d.audited_segments=set();d.record={}
            d.call_start=d.call_end=0;d.ledger=type('L',(),{'calls':[]})();d.bound=lambda:None
            d.download=lambda *a:None;d.compare_entry=lambda e:dict(exact=True)
            d.audit_calls=lambda layout,rows:(True,{});d.event_metrics=lambda:[]
            layout=dict(nbytes=4,entries=[dict(job='E0'),dict(job='R0')])
            result=d.audit_and_persist(layout,[])
            self.assertEqual((result['expert_outputs'],result['refreshes']),(1,1))
            self.assertEqual((Path(tmp)/'tiny/RETENTION.bin').read_bytes(),bytes(4))


if __name__=='__main__':unittest.main(verbosity=2)
