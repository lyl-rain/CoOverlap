import contextlib,io,json,sys,unittest
from pathlib import Path
p=Path(__file__).resolve().parent
sys.path[:0]=[str(p/'gap'),str(p/'lsg2')]
import test_search_cpu
stream=io.StringIO()
suite=unittest.defaultTestLoader.loadTestsFromModule(test_search_cpu)
r=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
(p/'CPU_TESTS.log').write_text(stream.getvalue())
obj=dict(tests_run=r.testsRun,failures=len(r.failures),errors=len(r.errors),skipped=len(r.skipped),pass_=r.wasSuccessful(),scope='CPU only; shared transition core, historical input regressions and small synthetic exhaustive tree')
(p/'CPU_RESULTS.json').write_text(json.dumps(obj,indent=2)+'\n')
print(stream.getvalue());sys.exit(0 if r.wasSuccessful() else 1)
