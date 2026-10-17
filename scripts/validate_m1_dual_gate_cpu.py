import ast,struct,unittest
from pathlib import Path
from m1_dual_gate import evaluate
from m1_completion_core_v3 import calibration_config,formal_configs,trace_config,validate_config
ROOT=Path(__file__).resolve().parent
class Gates(unittest.TestCase):
    def test_byte_exact_distinguishes_signed_zero(self):
        a=struct.pack('<H',0);b=struct.pack('<H',0x8000)
        m=evaluate(a,b,'bf16',[1],[1]);self.assertFalse(m['byte_exact']);self.assertTrue(m['pass_'])
        s=(ROOT/'pi05_m1_completion_v3.py').read_text();self.assertIn('a.tobytes()==b.tobytes()',s)
    def test_bf16_threshold(self):
        b=struct.pack('<H',0x4000)
        self.assertTrue(evaluate(struct.pack('<H',0x4001),b,'bf16',[1],[1])['pass_'])
        self.assertFalse(evaluate(struct.pack('<H',0x4002),b,'bf16',[1],[1])['pass_'])
    def test_f32_threshold(self):
        zero=struct.pack('<f',0)
        self.assertTrue(evaluate(struct.pack('<f',0.009999),zero,'f32',[1],[1])['pass_'])
        self.assertFalse(evaluate(struct.pack('<f',0.010001),zero,'f32',[1],[1])['pass_'])
    def test_nonfinite_rejected(self):
        for v in (float('nan'),float('inf'),-float('inf')):
            self.assertFalse(evaluate(struct.pack('<f',v),struct.pack('<f',0),'f32',[1],[1])['pass_'])
    def test_shape_and_size(self):
        with self.assertRaises(ValueError):evaluate(b'\0\0',b'\0\0','bf16',[1],[2])
        with self.assertRaises(ValueError):evaluate(b'\0',b'\0\0','bf16',[1],[1])
    def test_protocol_branches(self):
        configs=[calibration_config()]+formal_configs({'tight_ms':180,'loose_ms':240})+[trace_config({'tight_ms':180})]
        for c in configs:
            validate_config(c);self.assertEqual(c['protocol'],'m1_completion_dual_gate_v3');self.assertIsNone(c['numerical_policy']['relative_tolerance'])
    def test_model_functions_unchanged(self):
        def methods(name):
            t=ast.parse((ROOT/name).read_text());return {v.name:ast.dump(v,include_attributes=False) for v in ast.walk(t) if isinstance(v,ast.FunctionDef) and v.name in ('context','block1','block2','retain_snap','copy_raw')}
        self.assertEqual(methods('pi05_m1_completion_v2.py'),methods('pi05_m1_completion_v3.py'))
    def test_save_before_t0(self):
        s=(ROOT/'pi05_m1_completion_v3.py').read_text();a=s.index('        experts,refreshes=jobs(0,P,ncycles)');t=s.index('        t0=time.monotonic_ns()+10_000_000',a);end=s.index("        seg['timed_window_end_ns']",t)
        self.assertIn('save();progress.flush();os.fsync',s[a:t]);self.assertNotIn('save()',s[t:end]);self.assertNotIn('os.fsync',s[t:end])
    def test_cross_gate_not_intraprocess(self):
        s=(ROOT/'pi05_m1_completion_v3.py').read_text();self.assertEqual(s.count('metrics=cross_evaluate('),1)
        self.assertIn("compare('gate_Expert_raw',gate_raw,raw0)",s);self.assertIn("compare(f'seg{segment_id}_E{j}'",s)
if __name__=='__main__':unittest.main()
