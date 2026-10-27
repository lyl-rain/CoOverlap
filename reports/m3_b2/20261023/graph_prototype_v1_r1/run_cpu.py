"""Run CPU tests only and save attributable evidence; never import Torch."""
import contextlib,io,json,os,subprocess,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent;D=HERE/'deployment'
sys.path[:0]=[str(HERE/'tests'),str(D)]
import test_graph_cpu,test_entry_control_cpu
import validate_m2_clean_cpu as old
suite=unittest.TestSuite()
for mod in [test_graph_cpu,test_entry_control_cpu]:suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(mod))
for name in ['test_native_copy_direction_and_packing','test_window_forbidden_guards','test_D1_cross_process_is_report_only']:
 suite.addTest(old.CleanTests(name))
log=io.StringIO()
with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
 result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
(HERE/'CPU_TESTS.log').write_text(log.getvalue())
obj=dict(tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),
         pass_=result.wasSuccessful(),environment='Python CPU, CUDA API/native-operation boundary fixtures',
         GPU_capture='NOT_RUN',GPU_numerical='NOT_RUN',GPU_performance='NOT_RUN',
         fixture_math='symbolic native-op effects only; not Pi0.5 numerical evidence',
         regression='three relevant existing M2 tests only; entire historical suites not rerun')
(HERE/'CPU_RESULTS.json').write_text(json.dumps(obj,indent=2)+'\n')
print(log.getvalue());sys.exit(0 if result.wasSuccessful() else 1)
