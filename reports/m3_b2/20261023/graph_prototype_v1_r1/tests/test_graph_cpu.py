import ast,copy,hashlib,importlib,json,os,signal,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];D=HERE/'deployment'
sys.path[:0]=[str(D),str(HERE/'tests')]
import fixtures
from graph_backend import GraphBoundaryBackend,GraphError,GraphDevice
from graph_plan import RUN,manifest,protocol,budget
from m2_executor import VersionedKV,Handle,DEFAULT_PLAN
from m2_clean_core import retention_layout
from m3_b2_core import run_segment
from validate_m2_clean_cpu import SNAPS,Event


def run(cell='B',device=None):
    d=device or fixtures.Device();c=next(x for x in RUN if x['cell']==cell)
    d.select_engine(c['engine']);d.set_segment_id(c['id'])
    b=GraphBoundaryBackend(d,SNAPS,layout=retention_layout(8),plan=DEFAULT_PLAN)
    m=VersionedKV(DEFAULT_PLAN);r={};conf=manifest()
    run_segment(m,SNAPS,c['policy'],b,r,d.clock,conf=conf,expect=manifest())
    return d,b,m,r


class GraphCPU(unittest.TestCase):
    def test_capture_is_real_api_path_and_observed_work(self):
        d=fixtures.Device()
        self.assertEqual(d.api.capture_calls,6);self.assertEqual(d.api.replays,0)
        self.assertEqual(len(d.registry.units[(0,'Expert')].observed_capture_calls),180)
        self.assertEqual(len(d.registry.units[(0,'B1')].observed_capture_calls),11)
        self.assertFalse(d.physical) # native ops recorded, no numerical forward

    def test_full_eight_cycles_both_engines_both_policies(self):
        results={}
        for cell in 'ABCD':
            d,b,m,r=run(cell);results[cell]=r
            self.assertEqual((len(r['experts']),len(r['published']),len(r['units'])),(8,4,8))
            self.assertEqual([x[2] for x in m.journal if x[0]=='bind'],[j//2 for j in range(8)])
            result=b.validate_and_persist();self.assertTrue(result['pass_']);self.assertFalse(d.leased)
            if cell in 'CD':
                self.assertEqual(d.api.replays,16)
                self.assertEqual(len(d.ledger.calls[d.call_start:d.call_end]),0)
            else:self.assertEqual(d.api.replays,0)
        seq=lambda r:[(x['kind'],x.get('id'),x.get('block')) for x in r['decisions']]
        self.assertEqual(seq(results['A']),seq(results['C']))
        self.assertEqual(seq(results['B']),seq(results['D']))
        self.assertNotEqual(seq(results['A']),seq(results['B']))
        self.assertEqual(results['A']['manifest'],results['D']['manifest'])

    def test_bound_handle_slot_is_used_for_odd_partner(self):
        d,b,m,r=run('D')
        self.assertEqual(d.registry.rows['E0']['slot'],d.registry.rows['E1']['slot'])
        self.assertEqual(d.registry.rows['E1']['slot'],0)
        self.assertEqual(d.registry.rows['E6']['version'],3)
        b.validate_and_persist()

    def test_unpublished_and_stale_generation_rejected_at_adapter(self):
        d,b,m,r=run('D');h=m.versions[3]
        d.math_context=(m,Handle(h.slot,h.generation,999),'E999','Expert')
        with self.assertRaises((ValueError,RuntimeError,KeyError)):d.run_math('E999',h.slot,'Expert')
        d.math_context=(m,Handle(h.slot,h.generation+1,h.version),'E999','Expert')
        with self.assertRaises((ValueError,RuntimeError,KeyError)):d.run_math('E999',h.slot,'Expert')
        d.math_context=None

    def test_mutated_addresses_rejected_before_replay(self):
        d=fixtures.Device();d.addresses[1]+=1
        with self.assertRaises(GraphError):run('D',d)

    def test_actual_registry_positive_and_negative_coverage(self):
        d,b,m,r=run('D');layout=retention_layout(8)
        self.assertEqual(d.registry.audit(layout)['decoder'],1440)
        saved=copy.deepcopy(d.registry.rows)
        for mutate in [lambda rows:rows.pop('E1'),lambda rows:rows.update(extra=rows['E0']),
                       lambda rows:rows['E1'].update(slot=1),lambda rows:rows['E1'].update(generation=99),
                       lambda rows:rows['E1'].update(version=99),lambda rows:rows['E1'].update(segment_id='old'),
                       lambda rows:rows['E1'].update(status='SUBMITTED')]:
            d.registry.rows=copy.deepcopy(saved);mutate(d.registry.rows)
            with self.assertRaises(GraphError):d.registry.audit(layout)
        d.registry.rows=saved
        with self.assertRaises(GraphError):d.registry.confirm('E0',Event())

    def test_not_ready_event_cannot_complete(self):
        d=fixtures.Device();d.registry.begin_segment('probe','graph')
        event=Event(False);d.registry.rows['E0']=dict(status='SUBMITTED',expected_event=id(event))
        with self.assertRaises(GraphError):d.registry.confirm('E0',event)
        self.assertEqual(d.registry.rows['E0']['status'],'SUBMITTED')

    def test_graph_never_calls_python_math_at_replay(self):
        d,b,m,r=run('D');self.assertEqual(len(d.ledger.calls[d.call_start:d.call_end]),0)
        self.assertEqual(d.api.replays,16);b.validate_and_persist()

    def test_generation_reuse_and_retention_safe_reuse(self):
        d,b,m,r=run('D');self.assertEqual(m.generations,[3,2])
        with self.assertRaises(RuntimeError):d.select_engine('eager')
        b.validate_and_persist();d.select_engine('eager')
        self.assertFalse(d.leased)

    def test_failure_keeps_denominator_and_unverified_bank(self):
        d=fixtures.Device();original=d.registry.execute
        def fail(manager,h,key,kind,eager,completion_event):
            if key=='E3':raise TimeoutError('injected GPU boundary')
            return original(manager,h,key,kind,eager,completion_event)
        d.registry.execute=fail
        d.select_engine('graph');d.set_segment_id('failure')
        b=GraphBoundaryBackend(d,SNAPS,layout=retention_layout(8),plan=DEFAULT_PLAN);r={}
        with self.assertRaises(TimeoutError):run_segment(VersionedKV(),SNAPS,'b2_boundary',b,r,d.clock,conf=manifest(),expect=manifest())
        self.assertEqual(r['statistics']['cycle_counts']['denominator'],8)
        self.assertGreater(r['statistics']['cycle_counts']['INCOMPLETE'],0)
        self.assertTrue(d.leased);self.assertFalse(b.bank.reusable)
        with self.assertRaises(RuntimeError):b.validate_and_persist()

    def test_window_guards_use_real_device_methods(self):
        d,b,m,r=run('D');d.window=True;d.mode='performance'
        for fn in [lambda:d.download(),lambda:d.compare_entry({}),lambda:d.event_metrics(),lambda:GraphDevice.release_bank(d),lambda:d.select_engine('eager')]:
            with self.assertRaises(RuntimeError):fn()
        d.window=False;b.validate_and_persist()
        active=False
        for row in d.trace:
            if row[0]=='window':active=row[1]
            if row[0] in ('restore','capture'):self.assertTrue(active)
            if row[0] in ('prepare','ready','bootstrap','deferred'):self.assertFalse(active)

    def test_t0_is_after_ready_and_releases_never_reset(self):
        d,b,m,r=run('D');ready=next(x[1] for x in d.trace if x[0]=='ready')
        self.assertGreater(r['t0_ns'],ready)
        releases=[a['release_ns']-r['t0_ns'] for a in r['arrivals'] if a['kind']=='Expert']
        self.assertEqual(releases,[j*180_000_000+15_000_000 for j in range(8)])

    def test_stream_math_ast_only_stream_routing_changed(self):
        old=Path('/Users/moblumen/Desktop/CoOverlap/reports/m3_b2/20261023/credible_selector_validation_b10_v1_r1/deployment/m2_pi05_ops.py')
        aa=ast.parse(old.read_text());bb=ast.parse((D/'m2_pi05_ops.py').read_text())
        class Normalize(ast.NodeTransformer):
            def visit_Name(self,n):return ast.copy_location(ast.Constant(value=0),n) if n.id=='stream' and isinstance(n.ctx,ast.Load) else n
        for name in ['context','block1','block2','prefix_block','encoder_block']:
            a=next(n for n in aa.body if isinstance(n,ast.FunctionDef) and n.name==name)
            b=next(n for n in bb.body if isinstance(n,ast.FunctionDef) and n.name==name)
            b.args.args.pop();b.args.defaults.pop();b.body=[Normalize().visit(n) for n in b.body]
            self.assertEqual(ast.dump(a,include_attributes=False),ast.dump(b,include_attributes=False),name)

    def test_budget_disjoint_sum_and_full_work(self):
        b=budget();self.assertEqual((b['total_C'],b['total_E']),(53,73))
        self.assertEqual(sum(b['disk']['components'].values()),b['disk']['subtotal'])
        self.assertEqual(b['disk']['estimate_bytes'],b['disk']['subtotal']+b['disk']['headroom_10_percent'])
        self.assertLess(b['disk']['estimate_bytes'],b['disk']['admission_bytes'])
        self.assertEqual(b['capture']['instances'],6);self.assertEqual(b['capture']['GPU_forward_equivalents'],0)

    def test_new_orchestration_calls_actual_shared_scheduler(self):
        import graph_orchestrate as o
        d=fixtures.Device();records=[dict(c,status='NOT_STARTED') for c in RUN];calls=[]
        real=o.run_segment
        def observe(*args,**kwargs):calls.append(args[2]);return real(*args,**kwargs)
        with tempfile.TemporaryDirectory() as tmp,patch.object(o,'run_segment',observe):
            out=o.run_segments(d,SNAPS,records,Path(tmp),d.clock,lambda ok,n:self.assertTrue(ok,n),{})
        self.assertEqual(calls,[c['policy'] for c in RUN]);self.assertEqual(len(out),8)
        self.assertEqual([r['engine'] for r in records],[c['engine'] for c in RUN])

    def test_real_two_block_version_gates(self):
        from graph_orchestrate import version_gate
        for interleave in (False,True):
            d=fixtures.Device();r={};version_gate(d,SNAPS,interleave,r,lambda ok,n:self.assertTrue(ok,n),{})
            self.assertEqual(len(r['journal']),20 if interleave else 18)
            self.assertEqual(r['status'],'PASS')


if __name__=='__main__':unittest.main(verbosity=2)
