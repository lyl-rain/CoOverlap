"""Affected permission/execution-only checks; no CUDA imports or privilege writes."""
import ast, copy, hashlib, json, unittest
from pathlib import Path
from m1_capture_permissions_v8 import ADMIN,FIELDS,parse_status,check_profile,launch_prefix
from m1_pair_capture_core_v8 import pair_config,validate_config
from m1_submit_service_v8 import command
S=Path(__file__).resolve().parent;ROOT=S.parent
def functions(path):
    return {v.name:ast.dump(v,include_attributes=False) for v in ast.walk(ast.parse(path.read_text())) if isinstance(v,ast.FunctionDef)}
class Checks(unittest.TestCase):
    def profile(self):return {**{k:ADMIN for k in FIELDS},'Uid':[1001]*4,'Gid':[1001]*4,'NoNewPrivs':1}
    def test_exact_single_capability_profile(self):self.assertEqual(check_profile(self.profile(),1001,1001),self.profile())
    def test_extra_or_missing_capability_refused(self):
        for k in FIELDS:
            for v in (0,ADMIN|1):
                p=self.profile();p[k]=v
                with self.assertRaises(PermissionError):check_profile(p,1001,1001)
    def test_root_and_mixed_ids_refused(self):
        for k in ['Uid','Gid']:
            p=self.profile();p[k][1]=0
            with self.assertRaises(PermissionError):check_profile(p,1001,1001)
    def test_no_new_privileges_required(self):
        p=self.profile();p['NoNewPrivs']=0
        with self.assertRaises(PermissionError):check_profile(p,1001,1001)
    def test_proc_parser(self):
        text='Uid:\t1001 1001 1001 1001\nGid:\t1001 1001 1001 1001\nNoNewPrivs:\t1\n'+''.join(k+':\t0000000000200000\n' for k in FIELDS)
        self.assertEqual(parse_status(text),self.profile())
    def test_no_permanent_privilege_change(self):
        c=launch_prefix();self.assertIn('--reuid=nvidia',c);self.assertIn('--bounding-set=-all,+sys_admin',c);self.assertIn('--no-new-privs',c)
        self.assertFalse(any(x in ' '.join(c) for x in ['setcap','chmod','usermod','modprobe','reset-env']))
    def test_work_only_fills_missing_trace(self):
        c=pair_config();self.assertEqual(c['pair']['formal_order'],[]);self.assertEqual(c['pair']['diagnostic_order'],['serial','ordinary','fixed','return'])
        self.assertEqual(validate_config(c)['Experts'],9);self.assertEqual(c['total_ledger']['Contexts'],9)
        c['pair']['formal_order']=['serial']
        with self.assertRaises(ValueError):validate_config(c)
    def test_model_math_reference_functions_unchanged(self):
        a,b=functions(S/'pi05_m1_pair_scoped_v7.py'),functions(S/'pi05_m1_pair_capture_v8.py')
        for n in ['context','block1','block2','stage','snap','action','compare','buffer_dtypes']:self.assertEqual(a[n],b[n],n)
    def test_pair_submission_math_unchanged(self):
        a,b=functions(S/'pi05_encoder_pair_v6.py'),functions(S/'pi05_encoder_pair_capture_v8.py')
        for n in ['sample','prefix','phase_push','phase_pop','deadline','__getattr__']:self.assertEqual(a[n],b[n],n)
    def test_permission_check_precedes_real_apply(self):
        s=(S/'m1_service_scope_v8.py').read_text();self.assertLess(s.index('PERMISSION_PRE_CLOCK_CHECK.json'),s.index('clock.apply('));self.assertIn('if check.returncode:raise',s)
        self.assertIn('clock.stop_children(child)',s);self.assertLess(s.index('clock.stop_children(child)'),s.index('tx.recover(root)'))
    def test_monitor_drops_capabilities(self):
        s=(S/'m1_service_launch_v8.py').read_text();self.assertIn("'--drop-all-exec',sys.executable,str(BASE/'m1_completion_monitor.py')",s)
        d=(S/'m1_capture_permissions_v8.py').read_text();self.assertIn('lib.capset',d);self.assertIn("('CapInh','CapPrm','CapEff','CapAmb')",d)
    def test_transient_no_retry_service(self):
        s=' '.join(command(Path('/base'),Path('/run'),'unit','sha'))
        for token in ['Restart=no','RuntimeMaxSec=340s','TimeoutStopSec=60s','m1_service_scope_v8.py']:self.assertIn(token,s)
        self.assertNotIn('nsys',s);self.assertLess(15+340+60,420)
    def test_normal_reuse_not_fake_new_samples(self):
        s=(S/'pi05_encoder_pair_capture_v8.py').read_text();self.assertIn('REUSED_V7_NORMAL12_NOT_RERUN',s)
        self.assertLess(s.index("sample('ordinary','gate'"),s.index('collector.start()'))
        self.assertLess(s.index("collector_reference_status']='PASS"),s.index("sample(mode,'diagnostic'"))
    def test_final_thresholds_unchanged(self):
        c=pair_config();self.assertEqual(c['numerical_policy']['cross_process_bf16_max_abs'],.015625);self.assertEqual(c['numerical_policy']['cross_process_action_f32_max_abs'],.01)
if __name__=='__main__':unittest.main(verbosity=2)
