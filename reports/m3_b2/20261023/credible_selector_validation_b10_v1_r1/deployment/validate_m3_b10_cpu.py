"""Self-contained deployed-package CPU checks; never starts CUDA or hardware."""
import json,unittest
from pathlib import Path
import m3_b10_plan as p
from selection_contract import load_identity
from m3_b10_control import package_files
HERE=Path(__file__).resolve().parent
class PackageCPU(unittest.TestCase):
 def test_config(self):self.assertEqual(json.loads((HERE/'CONFIG.json').read_text()),p.protocol())
 def test_package(self):self.assertTrue(package_files(HERE))
 def test_identity(self):self.assertEqual(load_identity(HERE)[0]['rule_id'],p.RULE_ID)
 def test_manifest(self):
  for ns in p.BUDGETS:
   for e in p.manifest(ns)['experts']:self.assertEqual(e['release_ns']+ns,e['deadline_ns'])
 def test_budget(self):self.assertEqual((p.protocol()['work']['batch']['total_C'],p.protocol()['work']['batch']['total_E'],p.budget()['bank_bytes']),(52,70,597617152))
if __name__=='__main__':unittest.main(verbosity=2)
