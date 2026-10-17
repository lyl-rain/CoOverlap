"""Permission exception checks only. No GPU/model or real privilege changes."""
import ast,copy,unittest
from pathlib import Path
from m1_root_trace_identity_v9 import ROOT_MASK,PROTOCOL,check_diagnostic_state,root_prefix,monitor_prefix
from m1_root_trace_core_v9 import pair_config,validate_config
from m1_submit_service_v9 import command
S=Path(__file__).resolve().parent
def funcs(p):return {x.name:ast.dump(x,include_attributes=False) for x in ast.walk(ast.parse(p.read_text())) if isinstance(x,ast.FunctionDef)}
class Checks(unittest.TestCase):
    def profile(self):return dict(Uid=[0]*4,Gid=[0]*4,CapPrm=ROOT_MASK,CapEff=ROOT_MASK,CapBnd=ROOT_MASK,CapInh=0,CapAmb=0,NoNewPrivs=1)
    def test_explicit_root_profile(self):self.assertEqual(check_diagnostic_state(self.profile(),PROTOCOL),self.profile())
    def test_missing_approval_refused(self):
        for token in [None,'',PROTOCOL+'wrong']:
            with self.assertRaises(PermissionError):check_diagnostic_state(self.profile(),token)
    def test_nvidia_not_mislabelled_root(self):
        p=self.profile();p['Uid']=[1001]*4
        with self.assertRaises(PermissionError):check_diagnostic_state(p,PROTOCOL)
    def test_extra_missing_or_inheritable_caps_refused(self):
        for k,v in [('CapEff',ROOT_MASK|1),('CapPrm',0),('CapBnd',0),('CapInh',ROOT_MASK),('CapAmb',ROOT_MASK),('NoNewPrivs',0)]:
            p=self.profile();p[k]=v
            with self.assertRaises(PermissionError):check_diagnostic_state(p,PROTOCOL)
    def test_minimal_model_capability_command(self):
        c=root_prefix();self.assertIn('--reuid=0',c);self.assertIn('--no-new-privs',c)
        self.assertIn('--bounding-set=-all,+sys_admin,+dac_override,+dac_read_search',c)
        self.assertNotIn('setuid',' '.join(c).replace('--reuid',''))
    def test_monitor_remains_unprivileged(self):
        c=monitor_prefix();self.assertIn('--reuid=nvidia',c);self.assertIn('--bounding-set=-all',c);self.assertIn('--no-new-privs',c)
        s=(S/'m1_service_launch_v9.py').read_text();self.assertIn('monitor=subprocess.Popen(monitor_prefix()+',s)
    def test_unchanged_math_and_submission(self):
        a,b=funcs(S/'pi05_m1_pair_scoped_v7.py'),funcs(S/'pi05_m1_root_trace_v9.py')
        for n in ['context','block1','block2','stage','snap','action','compare','buffer_dtypes']:self.assertEqual(a[n],b[n],n)
        a,b=funcs(S/'pi05_encoder_pair_v6.py'),funcs(S/'pi05_encoder_pair_root_trace_v9.py')
        for n in ['sample','prefix','phase_push','phase_pop','deadline','__getattr__']:self.assertEqual(a[n],b[n],n)
    def test_only_missing_four_diagnostic_samples(self):
        c=pair_config();self.assertEqual(c['pair']['formal_order'],[]);self.assertEqual(c['pair']['diagnostic_order'],['serial','ordinary','fixed','return'])
        self.assertEqual(validate_config(c)['Contexts'],9);self.assertEqual(c['total_ledger']['Experts'],9)
        self.assertEqual(c['permission_smoke']['models'],0);self.assertEqual(c['permission_smoke']['explicit_kernel_launches'],0)
    def test_no_relaxed_thresholds(self):
        c=pair_config();self.assertEqual(c['numerical_policy']['cross_process_bf16_max_abs'],.015625);self.assertEqual(c['numerical_policy']['cross_process_action_f32_max_abs'],.01)
        self.assertEqual(c['numerical_policy']['in_process'],'raw bytes exact')
    def test_permission_smoke_before_clocks(self):
        s=(S/'m1_service_scope_v9.py').read_text();self.assertLess(s.index('root CUPTI permission smoke failed'),s.index('clock.apply('));self.assertIn('timeout=15',s)
        self.assertIn('--allow-root-diagnostic',s);self.assertLess(s.index('clock.stop_children(child)'),s.index('tx.recover(root)'))
    def test_explicit_flag_and_one_shot_service(self):
        c=' '.join(command(Path('/base'),Path('/run'),'unit','sha'));self.assertIn('--allow-root-diagnostic',c);self.assertIn('Restart=no',c);self.assertNotIn('nsys',c)
        self.assertIn('RuntimeMaxSec=340s',c);self.assertIn('TimeoutStopSec=60s',c)
        s=(S/'m1_submit_service_v9.py').read_text();self.assertLess(s.index('if not a.allow_root_diagnostic'),s.index('quick_verify(base'))
    def test_no_root_source_bytecode_writes(self):
        self.assertIn("PYTHONDONTWRITEBYTECODE='1'",(S/'m1_execution_v9.py').read_text())
        self.assertIn("sys.executable,'-B','-u'",(S/'m1_service_launch_v9.py').read_text())
    def test_collector_still_late(self):
        s=(S/'pi05_encoder_pair_root_trace_v9.py').read_text();self.assertLess(s.index("sample('ordinary','gate'"),s.index('collector.start()'))
        self.assertLess(s.index("collector_reference_status']='PASS"),s.index("sample(mode,'diagnostic'"))
    def test_smoke_is_not_model(self):
        s=(S/'m1_root_trace_identity_v9.py').read_text();self.assertNotIn('import torch',s);self.assertNotIn('cuLaunchKernel',s);self.assertIn('model_processes=0',s)
if __name__=='__main__':unittest.main(verbosity=2)
