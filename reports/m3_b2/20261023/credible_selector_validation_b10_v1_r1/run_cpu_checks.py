"""Run authorized local CPU checks and retain machine-readable evidence."""
import argparse,json,os,re,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
S=HERE.parent/'credible_plan_selector_v2_r1'
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,default=HERE);a=ap.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
 rows=[]
 for name,p in [('selector',S/'cps2/test_cps2_cpu.py'),('b10_entry_evaluation',HERE/'tests/test_b10_cpu.py'),('deployment_package',HERE/'deployment/validate_m3_b10_cpu.py')]:
  r=subprocess.run([sys.executable,'-B',str(p)],capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
  log=r.stdout+r.stderr;(a.output_dir/(name+'_CPU_TESTS.log')).write_text(log)
  match=re.search(r'Ran (\d+) tests?',log)
  rows.append(dict(suite=name,command=[sys.executable,'-B',str(p)],tests=None if match is None else int(match[1]),exit_code=r.returncode,pass_=r.returncode==0 and match is not None))
 result=dict(status='PASS' if all(x['pass_'] for x in rows) else 'FAIL',total_tests=sum(x['tests'] or 0 for x in rows),suites=rows,scope='CPU fixtures and local file contracts only; no GPU/SSH/hardware validation',python=sys.version)
 (a.output_dir/'CPU_RESULTS.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));return 0 if result['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
