"""No CUDA import/model. Contract, provenance, unchanged math and service limits."""
import ast,copy,hashlib,json,math,struct,unittest
from pathlib import Path
from m1_scoped_gate_v7 import intermediate,final_gate,byte_equal
from m1_pair_scoped_core_v7 import pair_config,validate_config
from m1_submit_service_v7 import command
ROOT=Path(__file__).resolve().parents[1]
def bf(v):return struct.pack('<H',struct.unpack('<I',struct.pack('<f',v))[0]>>16)
class Checks(unittest.TestCase):
    def test_old_intermediate_mismatch_is_diagnostic(self):
        v=bf(1808);ref={'sha256':hashlib.sha256(bf(2144)).hexdigest(),'nbytes':2,'storage_dtype':'uint8'}
        r=intermediate(v,ref,[1]);self.assertTrue(r['finite']);self.assertFalse(r['old_reference_byte_exact']);self.assertNotIn('pass_',r)
    def test_intermediate_nonfinite_rejected(self):
        for v in (math.nan,math.inf,-math.inf):
            b=bf(v);r=intermediate(b,{'sha256':'x','nbytes':2,'storage_dtype':'uint8'},[1]);self.assertFalse(r['finite'])
    def test_intermediate_shape_dtype(self):
        for m in [{'sha256':'x','nbytes':4,'storage_dtype':'uint8'},{'sha256':'x','nbytes':2,'storage_dtype':'float32'}]:
            with self.assertRaises(ValueError):intermediate(bf(1),m,[1])
    def test_final_thresholds_unchanged(self):
        self.assertTrue(final_gate(bf(1.015625),bf(1),'bf16',[1])['pass_'])
        self.assertFalse(final_gate(bf(1.0234375),bf(1),'bf16',[1])['pass_'])
        self.assertTrue(final_gate(struct.pack('<f',.009),struct.pack('<f',0),'f32',[1])['pass_'])
        self.assertFalse(final_gate(struct.pack('<f',.011),struct.pack('<f',0),'f32',[1])['pass_'])
    def test_final_nonfinite(self):
        for kind,encode in [('bf16',bf),('f32',lambda v:struct.pack('<f',v))]:
            for v in (math.nan,math.inf):self.assertFalse(final_gate(encode(v),encode(1),kind,[1])['pass_'])
    def test_exact_means_bytes_not_numeric_zero(self):
        self.assertFalse(byte_equal(struct.pack('<f',0.),struct.pack('<f',-0.)))
    def test_frozen_work(self):
        c=pair_config();self.assertEqual(validate_config(c)['Contexts'],21);self.assertEqual(c['total_ledger']['Experts'],21)
        self.assertEqual(len(c['pair']['formal_order']),12);self.assertEqual(len(c['pair']['diagnostic_order']),4)
        c['total_ledger']['Experts']=20
        with self.assertRaises(ValueError):validate_config(c)
    def test_model_mathematics_unchanged(self):
        def funcs(n):return {v.name:ast.dump(v,include_attributes=False) for v in ast.walk(ast.parse((ROOT/'scripts'/n).read_text())) if isinstance(v,ast.FunctionDef)}
        a,b=funcs('pi05_m1_pair_plain_v6.py'),funcs('pi05_m1_pair_scoped_v7.py')
        for n in ['context','block1','block2','stage','snap','action','compare','buffer_dtypes']:self.assertEqual(a[n],b[n],n)
    def test_final_independent_reference_before_pair(self):
        s=(ROOT/'scripts/pi05_m1_pair_scoped_v7.py').read_text()
        self.assertLess(s.index("'cross_process_absolute_'+filename"),s.index("job[0]='reference_S1'"))
        self.assertLess(s.index("require(metrics['pass_'],'cross_process_absolute_'+filename)",s.index("S1_OUTPUT_MANIFEST.json")),s.index("job[0]='gate_B1'"))
        self.assertIn("compare('S0_pre_post_Expert_'",s);self.assertIn("compare('S1_pre_post_Expert_'",s)
        self.assertIn('from pi05_encoder_pair_v6 import run_pair',s)
    def test_original_late_collection_unchanged(self):
        s=(ROOT/'scripts/pi05_encoder_pair_v6.py').read_text();self.assertLess(s.index("sample(mode,'normal'"),s.index('from delayed_activity_v6 import Collector'));self.assertLess(s.index('collector.start()'),s.index("job[0]='collector_reference_S0'"))
    def test_service_no_retry_and_bound(self):
        s=' '.join(command(Path('/b'),Path('/o'),'unit','sha'));self.assertIn('Restart=no',s);self.assertIn('RuntimeMaxSec=340s',s);self.assertIn('TimeoutStopSec=60s',s);self.assertNotIn('nsys',s);self.assertLess(15+340+60,420)
    def test_recovery_chain_unchanged(self):
        a=(ROOT/'scripts/m1_service_scope_v6.py').read_text()
        b=(ROOT/'scripts/m1_service_scope_v7.py').read_text().replace('m1_execution_v7','m1_execution_v6').replace('m1_service_launch_v7','m1_service_launch_v6')
        self.assertEqual(a,b)
    def test_frozen_S1_has_independent_provenance(self):
        d=ROOT/'reports/m1_acceptance/scoped_equivalence_20261016_v7/independent_reference'
        if not d.exists():self.skipTest('board preflight validates frozen reference files')
        m=json.loads((d/'S1_OUTPUT_MANIFEST.json').read_text());self.assertIn('Day2D',m['source'])
        for p,v in m['files'].items():self.assertEqual(hashlib.sha256((d/p).read_bytes()).hexdigest(),v['sha256'])
if __name__=='__main__':unittest.main(verbosity=2)
