import ast, hashlib, json, os, tempfile, unittest
from pathlib import Path
from m1_durable_journal import DurableJournal
BASE=Path(__file__).resolve().parent
class ResumeTests(unittest.TestCase):
    def test_window_and_model_functions_unchanged(self):
        old=ast.parse((BASE/'pi05_m1_completion.py').read_text());new=ast.parse((BASE/'pi05_m1_completion_v2.py').read_text())
        def nodes(t):return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(t) if isinstance(n,ast.FunctionDef) and n.name in ('context','block1','block2','retain_snap','copy_raw')}
        self.assertEqual(nodes(old),nodes(new))
        a=(BASE/'pi05_m1_completion.py').read_text();b=(BASE/'pi05_m1_completion_v2.py').read_text()
        start='    # Capture only necessary results';end='try:main()'
        self.assertEqual(a[a.index(start):a.index(end)],b[b.index(start):b.index(end)])
    def test_append_recovery_and_atomic_commit(self):
        with tempfile.TemporaryDirectory() as td:
            j=DurableJournal(td);r={'checks':[]}
            for i in range(40):
                x={'name':str(i),'pass_':i!=39};r['checks'].append(x);j.append('check',x)
            j.commit(r)
            self.assertEqual(json.loads((Path(td)/'result.json').read_text()),r)
            records=[json.loads(s) for s in (Path(td)/'diagnostics.jsonl').read_text().splitlines()]
            self.assertEqual([v['seq'] for v in records],list(range(1,41)))
            self.assertFalse(records[-1]['value']['pass_']);j.file.close()
    def test_existing_journal_refused(self):
        with tempfile.TemporaryDirectory() as td:
            j=DurableJournal(td)
            with self.assertRaises(FileExistsError):DurableJournal(td)
            j.file.close()
    def test_original_reference_manifest(self):
        root=BASE.parent/'reports/m1_acceptance/batch_20261015/cross_process_references/calibration'
        self.assertEqual((root/'reference_S0_raw_bf16.bin').stat().st_size,3200)
        self.assertEqual((root/'reference_S0_actions.bin').stat().st_size,1400)
    def test_gate_before_timing(self):
        s=(BASE/'pi05_m1_completion_v2.py').read_text()
        self.assertLess(s.index("compare('cross_process_unified_"),s.index("if '--gate-only'"))
        self.assertLess(s.index("if '--gate-only'"),s.index('    banks=dict('))
        self.assertIn('finally:p0.transformer_decoder=decoder_original',s)
if __name__=='__main__':unittest.main()
