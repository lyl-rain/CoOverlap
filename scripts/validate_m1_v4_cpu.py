"""CPU checks only: guarded copy, raw pack, fixed ledger and unchanged math."""
import ast, ctypes as C, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import m1_memcpy_interference_v4 as worker
from m1_evidence_io_v4 import EvidenceIO
from m1_completion_core_v4 import calibration_config, trace_config, pair_config, formal_configs, validate_config, select_budgets
ROOT=Path(__file__).resolve().parent

class FakeArray:
    shape=(2,);dtype='uint8';nbytes=2
    def tobytes(self):return b'\x00\xff'

class Protocol(unittest.TestCase):
    def test_exact_32MiB_and_guards(self):
        a,b=worker.GuardedBuffer(worker.N,0x5A),worker.GuardedBuffer(worker.N,0)
        self.assertEqual(C.sizeof(a.payload),33554432);self.assertEqual(C.sizeof(b.payload),33554432)
        worker.copy_once(a.payload,b.payload,worker.N);a.check();b.check();self.assertEqual(bytes(a.payload),bytes(b.payload))
    def test_bad_lengths_rejected_before_copy(self):
        a,b=worker.GuardedBuffer(8,1),worker.GuardedBuffer(9,0)
        with patch.object(worker.LIB,'memmove') as moved:
            for n in (8,9,10):
                with self.assertRaises(ValueError):worker.copy_once(a.payload,b.payload,n)
            moved.assert_not_called()
    def test_guards_detect_source_and_destination(self):
        for side in (0,1):
            a=worker.GuardedBuffer(8,1);a.owner[0 if side==0 else C.sizeof(a.owner)-1]=b'\x00'
            with self.assertRaises(RuntimeError):a.check()
    def test_ctypes_signature(self):
        self.assertEqual(worker.LIB.memmove.argtypes,[C.c_void_p,C.c_void_p,C.c_size_t]);self.assertIs(worker.LIB.memmove.restype,C.c_void_p)
    def test_pack_all_bytes_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            e=EvidenceIO(d);e.tensor('seg0_E0_raw',FakeArray());e.tensor('seg0_E1_raw',FakeArray());e.append('check',dict(pass_=True));r={};e.commit(r)
            rows=[json.loads(x) for x in (Path(d)/'RAW_INDEX.jsonl').read_text().splitlines()]
            self.assertEqual([x['offset'] for x in rows],[0,2]);self.assertEqual((Path(d)/'RAW_TENSORS.bin').read_bytes(),b'\x00\xff'*2)
            self.assertEqual(len(rows),2);self.assertIn('off_window_costs',json.loads((Path(d)/'result.json').read_text()))
            for f in (e.diag,e.index,e.pack):f.close()
    def test_reference_sidecars_readable_before_commit(self):
        with tempfile.TemporaryDirectory() as d:
            e=EvidenceIO(d);e.tensor('reference_S0_raw',FakeArray())
            self.assertEqual(json.loads((Path(d)/'reference_S0_raw.json').read_text())['nbytes'],2)
            e.commit({})
            for f in (e.diag,e.index,e.pack):f.close()
    def test_all_frozen_configurations(self):
        for T,L in ((180,240),(180,320),(240,320)):
            configs=[trace_config(),calibration_config()]+formal_configs(dict(tight_ms=T,loose_ms=L))
            for c in configs:validate_config(c)
            fs=configs[2:];self.assertEqual(len(fs),6);self.assertTrue(all(len(c['segments'])==4 for c in fs))
            self.assertEqual(sum(c['timed_ledger']['Experts'] for c in configs),1696)
            self.assertEqual(sum(c['timed_ledger']['Contexts'] for c in configs),848)
            self.assertEqual([c['role'] for c in fs],['tight_repeat1','loose_repeat1','loose_repeat2','tight_repeat2','tight_repeat3','loose_repeat3'])
    def test_config_change_rejected(self):
        c=trace_config();c['cycles']=15
        with self.assertRaises(ValueError):validate_config(c)
    def test_model_functions_unchanged(self):
        names=('context','block1','block2','retain_snap','copy_raw')
        def methods(name):
            return {v.name:ast.dump(v,include_attributes=False) for v in ast.walk(ast.parse((ROOT/name).read_text())) if isinstance(v,ast.FunctionDef) and v.name in names}
        self.assertEqual(methods('pi05_m1_completion_v3.py'),methods('pi05_m1_completion_v4.py'))
    def test_t0_has_no_preparation_write(self):
        s=(ROOT/'pi05_m1_completion_v4.py').read_text();a=s.index('experts,refreshes=jobs(0,P,ncycles)');t=s.index('t0=time.monotonic_ns()+10_000_000',a);end=s.index("seg['timed_window_end_ns']",t)
        self.assertIn('save();progress.flush();os.fsync',s[a:t]);self.assertNotIn('save()',s[t:end]);self.assertNotIn('os.fsync',s[t:end])
    def test_worker_actual_entry_and_all_checks(self):
        s=(ROOT/'pi05_m1_completion_v4.py').read_text();self.assertIn("with_name('m1_memcpy_interference_v4.py')",s);self.assertNotIn("with_name('m1_memcpy_interference.py')",s)
        self.assertIn("worker_result['guards']=='PASS'",s);self.assertIn("a.tobytes()==b.tobytes()",s)
        self.assertIn("compare(f'seg{segment_id}_E{j}'",s);self.assertIn("compare(f'seg{segment_id}_R{q}_final_{k}'",s)
    def test_scope_budget_and_write_whitelist(self):
        import m1_clock_scope_v4 as scope
        self.assertEqual(scope.run_scope.__defaults__,(2700,));self.assertEqual(len(scope.NODES),5)
        s=(ROOT/'m1_clock_scope_v4.py').read_text();self.assertIn('timeout_s-60',s);self.assertIn('COOVERLAP_SCOPE_DEADLINE_NS',s)
    def test_pair_fixed_group_and_work(self):
        c=pair_config();validate_config(c);self.assertEqual(c['pair']['groups'],[list(range(9)),list(range(9,18))]);self.assertEqual(c['timed_ledger'],dict(Experts=12,Contexts=12))
        self.assertEqual(len(c['pair']['formal_order']),12);self.assertEqual(c['pair_gate_ledger'],dict(Experts=1,Contexts=1))
    def test_scope_admission_reserves_cleanup(self):
        from m1_completion_launch_v4 import admission
        with self.assertRaises(TimeoutError):admission(310*10**9,300,0)
        admission(311*10**9,300,0)
    def test_pair_no_expert_wait_to_manufacture_return(self):
        s=(ROOT/'pi05_encoder_pair_v4.py').read_text()
        self.assertIn("if mode=='serial':B=A",s)
        self.assertNotIn('ee.synchronize()',s)
        self.assertIn("returned=mode=='return' and ee.query()",s)
        self.assertIn("target.wait_event(retained_done)",s)
    def test_cleanup_before_restore_v4(self):
        s=(ROOT/'m1_clock_scope_v4.py').read_text();self.assertLess(s.index('if child is not None:stop_children(child)'),s.index('if transaction.recover()'))

if __name__=='__main__':unittest.main(verbosity=2)
