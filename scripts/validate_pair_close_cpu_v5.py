import ast,copy,json,sys,unittest
from pathlib import Path
from pair_observation_v5 import Completion
from m1_pair_close_core_v5 import pair_config,validate_config,MODES
class Event:
    def __init__(self,answers):self.answers=iter(answers)
    def query(self):
        a=next(self.answers)
        if isinstance(a,Exception):raise a
        return a
class Checks(unittest.TestCase):
    def obs(self,stamps):
        t=iter(stamps);return Completion('job1',1,100,lambda:next(t))
    def test_first_completed(self):
        o=self.obs([210,220]);self.assertTrue(o.query(Event([True]),'job1',1));self.assertEqual((o.lower,o.upper),(100,220))
    def test_false_then_true(self):
        o=self.obs([110,120,160,170]);e=Event([False,True]);self.assertFalse(o.query(e,'job1',1));self.assertTrue(o.query(e,'job1',1));self.assertEqual((o.lower,o.upper),(110,170))
    def test_uncompleted(self):
        o=self.obs([110,120]);self.assertFalse(o.query(Event([False]),'job1',1));self.assertEqual(o.state()['status'],'INCOMPLETE');self.assertIsNone(o.upper)
    def test_error(self):
        o=self.obs([110,120])
        with self.assertRaises(RuntimeError):o.query(Event([RuntimeError('CUDA query error')]),'job1',1)
        self.assertIn('error',o.queries[0]);self.assertIsNone(o.upper)
    def test_generation(self):
        o=self.obs([])
        for job,g in [('oldjob',1),('job1',0),('job1',2)]:
            with self.assertRaises(ValueError):o.query(Event([True]),job,g)
    def test_frozen_manifest(self):
        c=pair_config();self.assertEqual(validate_config(c)['Experts'],19);self.assertEqual(c['total_ledger']['Contexts'],20)
        self.assertEqual(len(c['pair']['formal_order']),12);self.assertEqual(c['pair']['diagnostic_order'],MODES)
        for m in MODES:self.assertEqual(c['pair']['formal_order'].count(m),3)
        c['scope_timeout_s']=421
        with self.assertRaises(ValueError):validate_config(c)
    def test_math_prefix_unchanged(self):
        p=Path(__file__).parent
        def fn(file,name):return next(ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse((p/file).read_text())) if isinstance(n,ast.FunctionDef) and n.name==name)
        self.assertEqual(fn('pi05_encoder_pair_v4.py','prefix'),fn('pi05_encoder_pair_v5.py','prefix'))
    def test_control_and_endpoint_order(self):
        s=Path(__file__).with_name('pi05_encoder_pair_v5.py').read_text()
        self.assertLess(s.index('control_begin=time.monotonic_ns()'),s.index("returned=mode=='return'"))
        self.assertLess(s.index('b1.record(A)'),s.index("retained['K'].copy_"))
        self.assertLess(s.index('retained_done.record(A)'),s.index('target.wait_event(retained_done)'))
        self.assertIn("range(9,18)",s);self.assertIn('range(9)',s)
        self.assertIn('B1_math_done',s);self.assertIn('schedulable_boundary',s)
    def test_scope_and_attempt_cap(self):
        p=Path(__file__).parent;s=(p/'m1_clock_scope_v5.py').read_text()
        self.assertIn('timeout_s=420',s);self.assertIn('timeout_s-60',s)
        launch=(p/'m1_pair_close_launch_v5.py').read_text();self.assertEqual(launch.count('p=subprocess.Popen(command'),1)
        self.assertIn("'175s'",launch);self.assertIn('--nvtx-capture=M1_PAIR_TRACE',launch)
    def test_normal_before_capture(self):
        s=Path(__file__).with_name('pi05_encoder_pair_v5.py').read_text()
        self.assertLess(s.index("sample(mode,'normal'"),s.index("range_push('M1_PAIR_TRACE')"))
        self.assertLess(s.index("range_push('M1_PAIR_TRACE')"),s.index("sample(mode,'diagnostic'"))
if __name__=='__main__':unittest.main(verbosity=2)
