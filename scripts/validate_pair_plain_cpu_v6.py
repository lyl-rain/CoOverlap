import ast,copy,unittest
from pathlib import Path
from m1_pair_plain_core_v6 import pair_config,validate_config,MODES
class Plain(unittest.TestCase):
    def src(self,n):return Path(__file__).with_name(n).read_text()
    def test_manifest(self):
        c=pair_config();self.assertEqual(validate_config(c)['Contexts'],21);self.assertEqual(c['total_ledger']['Experts'],20)
        self.assertEqual(len(c['pair']['formal_order']),12);self.assertEqual(c['pair']['diagnostic_order'],MODES)
        for m in MODES:self.assertEqual(c['pair']['formal_order'].count(m),3)
        c['total_ledger']['Experts']=21
        with self.assertRaises(ValueError):validate_config(c)
    def test_v4_original_math_and_preparation_functions(self):
        def funcs(s):return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(s)) if isinstance(n,ast.FunctionDef)}
        old,new=funcs(self.src('pi05_m1_completion_v4.py')),funcs(self.src('pi05_m1_pair_plain_v6.py'))
        for name in ['context','block1','block2','stage','snap','compare','buffer_dtypes']:
            self.assertEqual(old[name],new[name],name)
        archive=Path(__file__).resolve().parents[1]/'reports/m1_acceptance/completion_20261016_v4/board/archive/pi05_dual_slot_adapter.py'
        self.assertEqual(self.src('pi05_dual_slot_adapter.py'),archive.read_text())
    def test_startup_and_autotune_order(self):
        old=self.src('pi05_m1_completion_v4.py');new=self.src('pi05_m1_pair_plain_v6.py')
        calls=['owner,p0,p1,attn1,runner1=build_slots','images=owner._stack_images','noise=torch.from_numpy','emb0=store','p.autotune_gemms()','p0.run_pipeline(0)']
        self.assertEqual(sorted(calls,key=old.index),sorted(calls,key=new.index))
    def test_context_gate_before_Expert(self):
        s=self.src('pi05_m1_pair_plain_v6.py');a=s.index('def decoder_with_prestate');b=s.index('return decoder_original',a)
        self.assertIn('pre_Expert_frozen_Context_',s[a:b]);self.assertIn("for key in ('x','K','V')",s[a:b])
        self.assertLess(s.index("snap(p0,'reference_Expert_pre_Context')",a),s.index('pre_Expert_frozen_Context_',a))
    def test_no_nsys_model_launch(self):
        s=self.src('m1_pair_plain_launch_v6.py');tree=ast.parse(s)
        command=next(n.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='command' for t in n.targets))
        constants=[n.value for n in ast.walk(command) if isinstance(n,ast.Constant)]
        self.assertNotIn('nsys',constants);self.assertIn('175s',constants);self.assertEqual(s.count('p=subprocess.Popen(command'),1)
        self.assertNotIn('os.environ.clear',s)
    def test_late_collector_only(self):
        s=self.src('pi05_encoder_pair_v6.py')
        self.assertLess(s.index("sample(mode,'normal'"),s.index('from delayed_activity_v6 import Collector'))
        self.assertLess(s.index('collector.start()'),s.index("job[0]='collector_reference_S0'"))
        self.assertLess(s.index("collector_reference_status']='PASS"),s.index("sample(mode,'diagnostic'"))
        self.assertNotIn('autotune_gemms',s)
    def test_adapter_concurrent_and_ownership(self):
        s=self.src('m1_activity_adapter_v6.cpp')
        self.assertIn('CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL',s);self.assertNotIn('CUPTI_ACTIVITY_KIND_KERNEL',s)
        for n in ['cuptiActivityGetNumDroppedRecords','cuptiActivityGetNextRecord','free(b)','CUpti_ActivityKernel11','outstanding_CUPTI_owned_buffers']:
            self.assertIn(n,s)
        for n in ['cudaDeviceSynchronize(', 'cuCtxSetCurrent(', 'cudaMalloc(', 'cuptiActivityEnableLatencyTimestamps(']:self.assertNotIn(n,s)
    def test_no_activity_import_at_driver_start(self):
        tree=ast.parse(self.src('pi05_m1_pair_plain_v6.py'))
        for n in tree.body:
            if isinstance(n,ast.ImportFrom):self.assertNotEqual(n.module,'delayed_activity_v6')
        facade=ast.parse(self.src('delayed_activity_v6.py'))
        self.assertFalse(any(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and 'CDLL' in ast.dump(n) for n in facade.body))
    def test_boundary_observation_retained(self):
        s=self.src('pi05_encoder_pair_v6.py')
        self.assertIn('Completion(name,1,release)',s);self.assertLess(s.index('control_begin=time.monotonic_ns()'),s.index("returned=mode=='return'"))
        self.assertLess(s.index('b1.record(A)'),s.index("retained['K'].copy_"));self.assertLess(s.index('retained_done.record(A)'),s.index('target.wait_event(retained_done)'))
    def test_scope_unchanged(self):
        self.assertEqual(self.src('m1_clock_scope_v6.py'),self.src('m1_clock_scope_v5.py'))
if __name__=='__main__':unittest.main(verbosity=2)
