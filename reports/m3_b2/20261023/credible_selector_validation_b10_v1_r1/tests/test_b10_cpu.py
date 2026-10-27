"""CPU-only B10 real-entry and real-evaluator tests; writes temporary files only."""
import contextlib,copy,hashlib,io,json,os,socket,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
B=Path(__file__).resolve().parents[1]
for p in (B/'deployment',B/'analysis',B/'tests'):sys.path.insert(0,str(p))
import m3_b10_plan as plan
import m3_b10_control as control
import pi05_m3_b10_validation as entry
import evaluate_b10 as ev
import build_b10_prediction as builder
from selection_contract import load_identity,sha
import fixture_b10

class IdentityTests(unittest.TestCase):
 def test_config_protocol(self):self.assertEqual(ev.load(B/'deployment/CONFIG.json'),plan.protocol())
 def test_manifest_time(self):
  for ns in plan.BUDGETS:
   m=plan.manifest(ns)
   for e in m['experts']:self.assertEqual(e['deadline_ns']-e['release_ns'],ns);self.assertEqual(e['release_ns'],e['id']*ns+15_000_000)
 def test_order_and_resources(self):
  self.assertEqual([x['cell'][0] for x in plan.RUN],list('ABCDDCBA'));self.assertEqual(len(set(plan.SEGMENT_IDS)),8)
  self.assertEqual((plan.protocol()['work']['batch']['total_C'],plan.protocol()['work']['batch']['total_E']),(52,70));self.assertEqual(plan.budget()['bank_bytes'],597617152)
 def test_deployment_package(self):self.assertEqual(len(control.package_files(B/'deployment')),len((B/'deployment/DEPLOY_SHA256.txt').read_text().splitlines()))
 def test_freeze(self):self.assertTrue(ev.verify_freeze()['files'])
 def test_prediction_coverage(self):
  s,p=load_identity(B/'deployment');self.assertEqual(len(p['segment_mapping']),8);self.assertEqual(sum(len(x['rows']) for c in p['segments'].values() for x in c.values()),480)
  self.assertTrue(all(x['status'] in ('PASS','FAIL','INCOMPLETE') for c in p['segments'].values() for z in c.values() for x in z['rows'] if x['job_type']=='Expert'))
 def test_prediction_rebuild(self):
  p,s=builder.build();self.assertEqual(p,ev.load(B/'prediction/PREDICTION.json'));self.assertEqual(s,ev.load(B/'prediction/SELECTION_FREEZE.json'))
 def test_selection_changes_with_real_selector(self):
  with patch.object(builder.selector,'evaluate_budget',return_value=({},dict(status='NO_ACCEPTABLE_PLAN_UNDER_RULE',selected=None))):p,s=builder.build()
  self.assertIsNone(s['by_period_ns']['160000000']['selected'])
 def test_contract_tamper(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'deployment').mkdir();(root/'prediction').mkdir()
   for name in ('PREDICTION.json','SELECTION_FREEZE.json'):(root/'prediction'/name).write_bytes((B/'prediction'/name).read_bytes())
   (root/'prediction/SELECTION_FREEZE.json').write_text('{}')
   with self.assertRaises(ValueError):load_identity(root/'deployment')

class EntryTests(unittest.TestCase):
 def invoke(self,change=None):
  with tempfile.TemporaryDirectory() as d:
   run=Path(d);out=run/'model'
   cred=dict(host=socket.gethostname(),base=str((B/'deployment').resolve()),run=str(run.resolve()),protocol=plan.PROTOCOL,created=time.time(),package=control.package_files(B/'deployment'),sources={})
   if change:change(cred)
   (run/'PREFLIGHT.json').write_text(json.dumps(cred))
   args=['entry','--approved-m3-b10-credible-selector-validation-v1','--config',str(B/'deployment/CONFIG.json'),'--out',str(out),'--reference',str(B/'deployment/reference'),'--source-preflight',str(run/'PREFLIGHT.json')]
   reached=[]
   def sentinel(*a,**k):reached.append(True);raise RuntimeError('CPU_PREPARE_SENTINEL')
   with patch.object(sys,'argv',args),patch.dict(os.environ,{'COOVERLAP_APPROVED_BATCH':plan.PROTOCOL}),patch.object(entry,'preparation_audit',return_value=(None,None,{'fixture':True})),patch.object(entry,'prepare',side_effect=sentinel),patch.object(entry.os,'geteuid',return_value=1001):
    try:entry.main()
    except ValueError:return reached,out.exists(),None
    except RuntimeError as exc:
     if str(exc)!='CPU_PREPARE_SENTINEL':raise
    return reached,out.exists(),ev.load(out/'result.json')
 def test_real_entry_legal_credential_reaches_prepare_without_cuda(self):
  torch_before='torch' in sys.modules;r,exists,report=self.invoke();self.assertEqual(r,[True]);self.assertTrue(exists);self.assertEqual(report['status'],'FAIL_OR_INCOMPLETE');self.assertIn('CPU_PREPARE_SENTINEL',report['error']);self.assertEqual(torch_before,'torch' in sys.modules)
 def test_old_protocol_rejected(self):r,o,_=self.invoke(lambda c:c.update(protocol='m3_b9_expert_reserve_validation_v1'));self.assertFalse(r);self.assertFalse(o)
 def test_expired_credential_rejected(self):r,o,_=self.invoke(lambda c:c.update(created=time.time()-601));self.assertFalse(r);self.assertFalse(o)

class EvaluationTests(unittest.TestCase):
 def setUp(self):self.r=fixture_b10.result()
 def test_official_complete_and_domains(self):
  d=ev.evaluate(self.r);self.assertEqual(d['verdict'],'EVALUATED');self.assertTrue(d['fixture']);self.assertEqual(d['B_official']['declared'],dict(Expert=64,Cycle=64,Refresh=32));self.assertEqual(d['B_official']['totals']['Refresh']['PASS'],32)
  self.assertTrue(all(x['nominal_verdict']=='SUPPORTED_ON_THIS_SEGMENT' for x in d['D_selection'] if x['model_accepted']))
 def test_b9_historical_interval_regression(self):
  r=fixture_b10.core.load(fixture_b10.core.B9_RESULT);cfg=r['protocol']
  with patch.object(ev,'plan_manifest',side_effect=lambda ns:cfg['manifests'][str(ns)]):d=ev.official_summary(r,cfg)
  self.assertEqual((d['totals']['Expert']['PASS'],d['totals']['Expert']['UNCERTAIN']),(63,1))
  self.assertEqual((d['totals']['Cycle']['PASS'],d['totals']['Cycle']['FAIL'],d['totals']['Cycle']['UNCERTAIN']),(56,7,1));self.assertEqual(d['totals']['Refresh']['PASS'],32)
 def test_partial_and_not_started_denominators(self):
  for i in range(5,8):fixture_b10.not_started(self.r,i)
  d=ev.evaluate(self.r);self.assertEqual(d['B_official']['totals']['Expert']['INCOMPLETE'],24);self.assertEqual(d['B_official']['totals']['Cycle']['INCOMPLETE'],24);self.assertEqual(d['B_official']['totals']['Refresh']['INCOMPLETE'],12);self.assertEqual(d['prediction_status'],'NOT_EVALUABLE')
 def test_all_not_started(self):
  for i in range(8):fixture_b10.not_started(self.r,i)
  d=ev.evaluate(self.r);self.assertEqual(d['A_correctness']['status'],'INCOMPLETE_OR_FAILED_EVIDENCE');self.assertEqual(d['B_official']['totals']['Expert']['INCOMPLETE'],64);self.assertEqual(d['B_official']['totals']['Refresh']['INCOMPLETE'],32)
 def test_uncertain_official(self):
  s=self.r['segments'][0];e=s['manifest']['experts'][0];s['experts']['0']=[s['t0_ns']+e['deadline_ns']-1000,s['t0_ns']+e['deadline_ns']+1000]
  d=ev.evaluate(self.r);self.assertEqual(d['B_official']['totals']['Expert']['UNCERTAIN'],1)
 def test_dual_reserve_boundary(self):
  self.assertEqual(ev.reserve_state(90,90,100),'SATISFIED');self.assertEqual(ev.reserve_state(90.01,90.02,100),'SHORT');self.assertEqual(ev.reserve_state(89.9,90.1,100),'UNCERTAIN');self.assertEqual(ev.reserve_state(None,None,100),'UNKNOWN')
 def test_vlm_reserve_counterexample_separate_from_expert(self):
  s=self.r['segments'][0];dl=s['manifest']['experts'][0]['deadline_ns'];s['units']['(0, 0)']=[s['t0_ns']+dl-9_000_000]*2
  d=ev.evaluate(self.r);self.assertEqual(d['D_selection'][0]['nominal_verdict'],'RESERVE_COUNTEREXAMPLE')
 def test_official_counterexample(self):
  s=self.r['segments'][0];dl=s['manifest']['experts'][0]['deadline_ns'];s['units']['(0, 0)']=[s['t0_ns']+dl+1_000_000]*2
  self.assertEqual(ev.evaluate(self.r)['D_selection'][0]['nominal_verdict'],'OFFICIAL_COUNTEREXAMPLE')
 def test_condition_mismatch_not_domain_pass(self):
  self.r['configuration']['label']='OTHER';d=ev.evaluate(self.r);self.assertEqual(d['verdict'],'CONDITION_MISMATCH');self.assertTrue(all(c['domain_verdict']=='CONDITION_MISMATCH' for c in d['D_selection']))
 def test_invalid_identity(self):
  self.r['segments'][0]['plan']='three_prefix_9_9'
  with self.assertRaises(ValueError):ev.evaluate(self.r)
 def test_manifest_changed_refused(self):
  self.r['segments'][0]['manifest']['experts'][0]['release_ns']+=1
  with self.assertRaises(ValueError):ev.evaluate(self.r)
 def test_duplicate_segment_refused(self):
  self.r['segments'].append(copy.deepcopy(self.r['segments'][0]))
  with self.assertRaises(ValueError):ev.evaluate(self.r)
 def test_stress_error_sign(self):
  base=ev.evaluate(self.r)['E_prediction'][0]['comparisons'][1]['jobs'];s=self.r['segments'][0];s['experts']['0']=[v+10_000_000 for v in s['experts']['0']]
  new=ev.evaluate(self.r)['E_prediction'][0]['comparisons'][1]['jobs']
  old=next(x for x in base if x['job_type']=='Expert' and x['job_id']=='E0');now=next(x for x in new if x['job_type']=='Expert' and x['job_id']=='E0')
  self.assertAlmostEqual(now['completion_exceedance_ms']-old['completion_exceedance_ms'],10);self.assertAlmostEqual(now['completion_error_ms']-old['completion_error_ms'],-10)
 def test_order_version_changes_reported(self):
  self.r['segments'][0]['decisions']=list(reversed(self.r['segments'][0]['decisions']));self.r['segments'][0]['journal'][0][2]=999
  d=ev.evaluate(self.r)['E_prediction'][0]['comparisons'][0];self.assertFalse(d['order_match']);self.assertFalse(d['version_match'])
 def test_missing_completion_not_zero(self):
  del self.r['segments'][0]['experts']['0'];d=ev.evaluate(self.r);e=d['B_official']['segments'][0]['experts'][0];self.assertIsNone(e['margin_ms']);self.assertEqual(e['deadline_status'],'INCOMPLETE')
 def test_missing_block_is_incomplete(self):
  s=self.r['segments'][0];del s['blocks']['(0, 0)'];del s['units']['(0, 0)']
  d=ev.evaluate(self.r);self.assertEqual(d['B_official']['segments'][0]['cycles'][0]['status'],'INCOMPLETE')
 def test_reserve_unknown_for_unstarted(self):
  fixture_b10.not_started(self.r,0);d=ev.evaluate(self.r);self.assertTrue(all(x['state']=='UNKNOWN' for x in d['C_reserves'][0]['rows']))
 def test_invalid_interval_rejected(self):
  self.r['segments'][0]['experts']['0']=[100,90]
  with self.assertRaises((ValueError,TypeError)):ev.evaluate(self.r)
 def test_refused_nominal_all_good_is_over_rejection(self):
  # Raise only the auxiliary reserve observations while keeping official deadlines and work.
  s=self.r['segments'][2];m=s['manifest']
  for e in m['experts']:
   j=e['id'];limit=s['t0_ns']+e['deadline_ns']-11_000_000
   s['experts'][str(j)]=[limit,limit];s['units'][str((j//2,j%2))]=[limit,limit]
  d=ev.evaluate(self.r);self.assertEqual(d['D_selection'][2]['nominal_verdict'],'OVER_REJECTION_ON_NOMINAL_SAMPLE_PERTURBATIONS_UNTESTED')
 def test_cli_and_invalid_freeze(self):
  with tempfile.TemporaryDirectory() as t:
   t=Path(t);raw=t/'result.json';raw.write_text(json.dumps(self.r));out=t/'out'
   with contextlib.redirect_stdout(io.StringIO()):code=ev.main(['--result',str(raw),'--out',str(out)])
   self.assertEqual(code,0);self.assertEqual(ev.load(out/'EVALUATION.json')['verdict'],'EVALUATED')
   bad=t/'bad.json';bad.write_text(json.dumps(dict(files={'x':dict(path='missing',sha256='0'*64)})))
   with contextlib.redirect_stdout(io.StringIO()):code=ev.main(['--result',str(raw),'--out',str(out),'--freeze',str(bad)])
   self.assertEqual(code,2);self.assertEqual(ev.load(out/'EVALUATION.json')['verdict'],'INVALID_EVIDENCE')

if __name__=='__main__':unittest.main(verbosity=2)
