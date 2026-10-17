"""CPU-only tests of accounting/guards/attribution; no model import or execution."""
import unittest,tempfile,json,sqlite3,ctypes,ast
from pathlib import Path
from m1_completion_core import *
from m1_completion_trace_map import union_ns,map_ranges
from m1_clock_scope import NODES,apply,restore,state
from m1_memcpy_interference import copy_once

class Protocol(unittest.TestCase):
    def test_ledger(self):
        e,r=jobs(10,180,64)
        self.assertEqual((len(e),len(r)),(64,32));self.assertEqual(r[-1]['release_ns'],10+62*180)
        self.assertEqual(r[0]['deadline_ns'],370)
        with self.assertRaises(ValueError):jobs(0,1,63)
    def test_completion_bounds(self):
        self.assertEqual([classify(a,b,10) for a,b in [(1,10),(11,12),(9,11),(None,None)]],['PASS','FAIL','UNCERTAIN','INCOMPLETE'])
        self.assertEqual(counts(['FAIL','FAIL','UNCERTAIN','FAIL'])['longest_consecutive_definite_miss'],2)
    def test_same_unit_early_B2(self):
        es,rs=jobs(0,1_000_000,4)
        for e in es:e.update(completion_lower_ns=e['release_ns']+1,completion_observed_ns=e['release_ns']+2)
        s=dict(P_ms=1,t0_ns=0,cycles=4,experts=es,unit_completions=[dict(id=0,unit=u,completion_lower_ns=4,completion_observed_ns=5) for u in ['B1','B2']])
        rows=cycle_rows(s);self.assertEqual(rows[1]['cycle_status'],'PASS');self.assertEqual(rows[2]['cycle_status'],'INCOMPLETE')
        self.assertEqual(rows[2]['required_unit_id'],'R1/B1')
    def test_all_config_branches(self):
        total=calibration_config()['timed_ledger'].copy()
        for T,L in [(180,240),(180,320),(240,320)]:
            cs=formal_configs(dict(tight_ms=T,loose_ms=L));self.assertEqual(cs[1]['segments'],list(reversed(cs[0]['segments'])))
            for c in cs+[trace_config(dict(tight_ms=T,loose_ms=L))]:validate_config(c)
            self.assertEqual(cs[0]['timed_ledger'],dict(Experts=512,Contexts=256))
        for c in formal_configs(dict(tight_ms=180,loose_ms=320))+[trace_config(dict(tight_ms=180,loose_ms=320))]:
            for k,v in c['timed_ledger'].items():total[k]+=v
        self.assertEqual(total,dict(Experts=1696,Contexts=848))
    def test_no_runtime_budget_mutation(self):
        c=calibration_config();c['segments'][0]['P_ms']=181
        with self.assertRaises(ValueError):validate_config(c)
    def test_calibration_stop_and_selection(self):
        def result(misses):
            return dict(status='PASS',protocol_id='m1_completion_batch_v1',role='calibration',segments=[dict(P_ms=p,status='PASS',frequency_condition={'status':'SATISFIED_SAMPLED'},cycles=32,cycle_statistics={'cycle_status':counts(['FAIL']*m+['PASS']*(32-m))},refresh_statistics=counts(['PASS']*16)) for p,m in zip([180,240,320],misses)])
        self.assertEqual(select_budgets(result([28,4,0]))['tight_ms'],240)
        self.assertEqual(select_budgets(result([28,0,0]))['loose_ms'],240)
        for m in [[0,0,0],[32,32,32]]:
            with self.assertRaises(ValueError):select_budgets(result(m))
        r=result([20,0,0]);r['segments'][0]['cycle_statistics']['cycle_status']['UNCERTAIN']=1
        with self.assertRaises(ValueError):select_budgets(r)
    def test_priority_fifo_drain(self):
        # Abstract deterministic service simulation, not GPU performance data.
        for split in [False,True]:
            E,R=jobs(0,180,64);now=0;order=[];doneE=set();doneR=set();phases={r['id']:0 for r in R}
            while len(doneE)<64 or len(doneR)<32:
                ready=[e for e in E if e['release_ns']<=now and e['id'] not in doneE]
                if ready:
                    e=ready[0];now+=99;doneE.add(e['id']);order.append(e['id']);continue
                pending=[r for r in R if r['release_ns']<=now and r['id'] not in doneR]
                if pending:
                    r=pending[0];self.assertFalse(ready)
                    if split:now+=79 if phases[r['id']]==0 else 44;phases[r['id']]+=1
                    else:now+=123;phases[r['id']]=2
                    if phases[r['id']]==2:doneR.add(r['id'])
                else:now=min(v['release_ns'] for v in E+R if v['id'] not in (doneE if v['unit_id'].startswith('E') else doneR))
            self.assertEqual(order,list(range(64)));self.assertEqual(len(doneR),32)
    def test_fake_hardware_restore(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for name,b,mn,mx,av,cur,target in NODES:
                p=root/b.lstrip('/');p.mkdir(parents=True)
                for n,v in [(mn,'1'),(mx,str(target)),(av,'1 '+str(target)),(cur,'1')]: (p/n).write_text(v)
            before=state(root);snapshot=root/'snapshot.json';apply(snapshot,root)
            self.assertTrue(all(v['min']==v['target'] for v in state(root)));restore(snapshot,root)
            self.assertEqual(before,state(root))
            with self.assertRaises(FileExistsError):apply(snapshot,root)
    def test_cpu_memcpy(self):
        a=ctypes.create_string_buffer(b'abcd');b=ctypes.create_string_buffer(5);copy_once(a,b);self.assertEqual(a.raw,b.raw)
    def test_trace_correlation_not_cpu_crop(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'trace.sqlite';c=sqlite3.connect(p)
            c.executescript('CREATE TABLE NVTX_EVENTS(start,end,globalTid,text); CREATE TABLE CUPTI_ACTIVITY_KIND_RUNTIME(start,end,globalTid,correlationId); CREATE TABLE CUPTI_ACTIVITY_KIND_KERNEL(start,end,globalPid,correlationId,streamId);')
            c.execute('insert into NVTX_EVENTS values(10,20,?,?)',((7<<24)+3,'M1_SEG_0_Expert_0'))
            c.execute('insert into CUPTI_ACTIVITY_KIND_RUNTIME values(15,18,?,5)',((7<<24)+3,))
            c.execute('insert into CUPTI_ACTIVITY_KIND_KERNEL values(30,50,?,5,7)',(7<<24,));c.commit();c.close()
            r=map_ranges(p)[0];self.assertEqual(r['kernels'],1);self.assertEqual(r['kernel_union_ns'],20)
            self.assertEqual(union_ns([(0,10),(5,20),(30,40)]),30)
    def test_driver_static_boundaries(self):
        p=Path(__file__).with_name('pi05_m1_completion.py');tree=ast.parse(p.read_text())
        funcs={n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        mid=ast.unparse(funcs['observed_B1']);self.assertEqual(mid.count('retain_snap('),1)
        self.assertNotIn('synchronize',mid);self.assertNotIn('cpu()',mid)
        self.assertIn('range(9)',ast.unparse(funcs['block1']));self.assertIn('range(9, 18)',ast.unparse(funcs['block2']))
        self.assertLess(p.read_text().index("if '--dry-run'"),p.read_text().index('import torch'))

if __name__=='__main__':unittest.main(verbosity=2)
