"""Test delayed limit reporting without GPU, real sysfs or write retry."""
import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import m1_clock_scope as scope

class Readback(unittest.TestCase):
    def run_case(self,reports):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'fake_min';p.write_text('1');writes=[];elapsed=[0.0];seq=iter(reports)
            original_write=Path.write_text
            def write(path,value):
                self.assertEqual(path,p);writes.append(value);return original_write(path,value)
            def sleep(dt):elapsed[0]+=dt
            with patch.object(Path,'write_text',write),patch.object(Path,'read_text',side_effect=lambda:next(seq)),patch.object(scope.time,'monotonic',side_effect=lambda:elapsed[0]),patch.object(scope.time,'sleep',side_effect=sleep):
                try:scope.write_min_once(p,10,'CPU_TEST')
                except RuntimeError as e:return writes,elapsed[0],str(e)
            return writes,elapsed[0],None
    def test_immediate_match_one_write(self):
        w,t,e=self.run_case(['10']);self.assertEqual(w,['10']);self.assertEqual(t,0);self.assertIsNone(e)
    def test_delayed_match_one_write(self):
        w,t,e=self.run_case(['1','1','10']);self.assertEqual(w,['10']);self.assertGreater(t,0);self.assertIsNone(e)
    def test_persistent_mismatch_fails_no_rewrite(self):
        w,t,e=self.run_case(['1']*200);self.assertEqual(w,['10']);self.assertGreaterEqual(t,1);self.assertLess(t,1.02);self.assertIn('MIN_READBACK_FAIL',e);self.assertIn('"observed": 1',e)
    def test_target_and_write_whitelist_unchanged(self):
        self.assertEqual([n[-1] for n in scope.NODES],[2201600,2201600,2201600,1300500000,3199000000]);self.assertEqual(len(scope.NODES),5)

if __name__=='__main__':unittest.main(verbosity=2)
