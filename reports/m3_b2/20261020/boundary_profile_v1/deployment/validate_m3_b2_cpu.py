"""Targeted CPU logic tests only. No CUDA/Torch import or hardware access."""
import argparse
import copy
import json
import ast
import hashlib
import subprocess
from pathlib import Path
import sys
import unittest
import validate_m2_clean_cpu as old
from m2_executor import VersionedKV, BLOCKS
from m2_clean_core import retention_layout, RetentionLedger
from m3_b2_core import manifest, protocol, run_segment, ORDER, PROTOCOL
from m3_b2_backend import BoundaryBackend, confirm_completion


class Device(old.Device):
    def __init__(self, expert=10_000_000, b1=60_000_000, b2=30_000_000, **kw):
        super().__init__(**kw)
        self.durations = dict(Expert=expert, B1=b1, B2=b2)
        self.events = {}

    def mark(self, key, index):
        e = super().mark(key, index)
        self.events.setdefault(key, [None]*8)[index] = e
        return e

    def run_math(self, key, slot, kind):
        before = self.now
        calls = super().run_math(key, slot, kind)
        self.now = before + self.durations[kind]
        return calls

    def wait_event(self, event):
        if not event.query(): raise TimeoutError('injected finite Event wait')
        return self.clock()


def run(policy=ORDER[1], period=100_000_000, cycles=4, mode='performance', **kw):
    d = Device(**kw)
    b = BoundaryBackend(d, old.SNAPS, mode, layout=retention_layout(cycles))
    m, r = VersionedKV(), {}
    run_segment(m, old.SNAPS, policy, b, r, d.clock, manifest(period,cycles))
    return d,b,m,r


def maths(d):
    return [x[1] for x in d.trace if x[0]=='math']


class Tests(unittest.TestCase):
    def test_profile_hooks_preallocate_and_preserve_call_order(self):
        from m3_b2_profile import ProfileHooks
        class E:
            created=0
            def __init__(self,**kw):type(self).created+=1;self.done=True
            def record(self,s):pass
            def query(self):return self.done
            def elapsed_time(self,other):return 1.0
        class Stream:
            def synchronize(self):pass
        class CUDA:
            Event=E
            def default_stream(self):return Stream()
        class Torch:cuda=CUDA()
        class Ledger:active='fixture'
        calls=[]
        class Pipeline:
            def _copy_lang_embeds_to_encoder_x(self,stream=0):calls.append('lang')
            def vision_encoder(self,stream=0):calls.append('vision')
            def _encoder_layer(self,i,*a):calls.append(i)
            def transformer_encoder(self,stream=0):
                for i in range(18):self._encoder_layer(i,561,False,0)
        p=Pipeline();h=ProfileHooks(Torch(),[p],Ledger(),lambda:1,capacity=1)
        self.assertEqual(E.created,41)
        p._copy_lang_embeds_to_encoder_x();p.vision_encoder();p.transformer_encoder()
        self.assertEqual(calls,['lang','vision']+list(range(18)))
        self.assertEqual(E.created,41);self.assertTrue(h.export()[0]['complete'])
        h.pool[0]['tail_end'].done=False
        with self.assertRaises(RuntimeError):h.export()
        self.assertFalse(h.export(False)[0]['complete'])
        with self.assertRaises(RuntimeError):p._copy_lang_embeds_to_encoder_x()

    def test_original_D1_preparation_is_exact_pinned_AST(self):
        from m3_m2_preparation import preparation_audit,SOURCE_SHA
        source,prefix,audit=preparation_audit()
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),SOURCE_SHA)
        tree=ast.Module(body=prefix,type_ignores=[])
        text=ast.unparse(tree)
        self.assertIn('p0.run_pipeline(0)',text)
        self.assertIn("require(digest(a) == digest(b)",text)
        self.assertNotIn('require(metrics',text)
        self.assertIn("report.setdefault('cross_process', []).append",text)
        # Compile exactly the body used by the bridge, without invoking it.
        fn=ast.parse('def f(args,report,save,require,bound):\n return locals()').body[0]
        fn.body=prefix+fn.body
        compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(source),'exec')

    def test_both_gates_have_exact_expected_lifecycle(self):
        from m2_clean_core import gate_retention_layout
        for interleave in (False,True):
            d=Device();b=BoundaryBackend(d,old.SNAPS,'correctness',layout=gate_retention_layout());m=VersionedKV()
            b.prepare(m,None,{});b.bootstrap(m,'bootstrap');b.ready(m)
            m.bind('E0',old.SNAPS[0].noise_sha);oldh=m.current;h=m.begin(1,old.SNAPS[1])
            if interleave:m.bind('hold',old.SNAPS[0].noise_sha)
            b.enter_window();b.stage(m,h,'R0');b.block(m,h,0,'R0/B1')
            if interleave:b.expert(m,'E0',oldh)
            b.block(m,h,1,'R0/B2');m.publish(h)
            m.bind('latest',old.SNAPS[0].noise_sha);m.cancel_unsubmitted('latest')
            with self.assertRaises(RuntimeError):m.reclaim(oldh)
            if interleave:m.cancel_unsubmitted('hold')
            else:b.expert(m,'E0',oldh)
            m.reclaim(oldh);b.drain();b.leave_window();b.validate_and_persist()
            self.assertEqual(len(m.journal),20 if interleave else 18)

    def test_future_stage_query_is_independent_of_submit_return(self):
        from m3_b2_profile import ProfileDevice
        d=object.__new__(ProfileDevice);d.operations={'stage':{}}
        d.events={'stage':[None]*7+[old.Event(False)]};d.clock=lambda:1
        with self.assertRaises(RuntimeError):d.complete_op('stage',0,None,[])
        self.assertFalse(d.operations['stage']['completed'])
        d.events['stage'][7].done=True;d.complete_op('stage',0,None,[])
        self.assertTrue(d.operations['stage']['gpu_event_confirmed'])

    def test_controller_keeps_single_submit_and_new_authorization(self):
        text=Path(__file__).with_name('m3_b2_control.py').read_text()
        self.assertIn('cooverlap-m3-b2-profile-20261020-run01',text)
        self.assertIn("'--approved-m3-b2-profile-v1'",text)
        self.assertNotIn('--approved-m2-clean-v1',text)
        self.assertIn("'--kill-after=10s','180s'",text)
        self.assertIn("'SCOPE_ATTEMPT_USED'",text);self.assertIn("'MODEL_ATTEMPT_USED'",text)
        self.assertIn('SnapshotTransaction',text)
        self.assertIn("'--property=Restart=no'",text)

    def test_no_new_math_or_unvalidated_cut_was_added(self):
        import m3_b2_core
        text=Path(m3_b2_core.__file__).read_text()
        self.assertNotIn('_encoder_layer',text);self.assertNotIn('gemm',text)
        self.assertEqual(protocol()['candidates'][1]['decision_boundaries'],['stage_complete','encoder_8_complete','Context_complete'])
        self.assertEqual(protocol()['manifest']['experts'][3]['version'],1)

    def test_dry_run_and_unapproved_entry_never_import_model(self):
        script=Path(__file__).with_name('pi05_m3_b2_profile.py')
        dry=subprocess.run([sys.executable,str(script),'--dry-run'],capture_output=True,text=True)
        self.assertEqual(dry.returncode,0,dry.stderr)
        self.assertEqual(json.loads(dry.stdout)['protocol'],protocol())
        denied=subprocess.run([sys.executable,str(script)],capture_output=True,text=True)
        self.assertEqual(denied.returncode,2)
        self.assertIn('NEW M3 approval',denied.stderr)

    def test_pending_event_cannot_set_completed(self):
        row={'completed': True}
        with self.assertRaises(RuntimeError):
            confirm_completion(old.Event(False),row,0,iter(range(10)).__next__)
        self.assertFalse(row['completed']);self.assertNotIn('gpu_done_observed_host_ns',row)

    def test_event_failure_propagates(self):
        class Broken:
            def query(self): raise RuntimeError('device failed')
        row={}
        with self.assertRaisesRegex(RuntimeError,'device failed'):
            confirm_completion(Broken(),row,0,lambda:1)
        self.assertFalse(row['completed'])

    def test_actual_event_and_host_completion_are_distinct(self):
        d,b,m,r=run()
        self.assertEqual(len(d.operations),10)
        for key,row in d.operations.items():
            self.assertTrue(d.events[key][7].query());self.assertTrue(row['completed'])
            self.assertTrue(row['gpu_event_confirmed'])
            self.assertLessEqual(row['gpu_completion_lower_host_ns'],row['gpu_completion_upper_host_ns'])
            self.assertEqual(row['gpu_completion_upper_host_ns'],row['gpu_done_observed_host_ns'])
            self.assertLess(row['host_finalization_lower_ns'],row['host_finalization_upper_ns'])
        self.assertTrue(d.operations['R0/stage']['completed'])

    def test_no_expert_context_advances_without_period_wait(self):
        d,b,m,r=run(b2=10_000_000)
        seq=maths(d);self.assertEqual(seq[seq.index('R0/B1')+1],'R0/B2')
        b1=next(x for x in r['decisions'] if x['kind']=='Context' and x['block']==0)
        b2=next(x for x in r['decisions'] if x['kind']=='Context' and x['block']==1)
        self.assertLess(b2['host_ns']-r['t0_ns'],100_000_000)
        self.assertFalse(any(x['kind']=='idle_until_arrival' and b1['host_ns']<x['host_ns']<b2['host_ns'] for x in r['decisions']))

    def test_expert_arriving_inside_block_precedes_next_block(self):
        d,b,m,r=run(b1=110_000_000)
        seq=maths(d);self.assertEqual(seq[seq.index('R0/B1')+1],'E1')
        self.assertLess(seq.index('E1'),seq.index('R0/B2'))

    def test_arrival_just_before_boundary(self):
        d,b,m,r=run(b1=90_100_000)
        seq=maths(d);self.assertEqual(seq[seq.index('R0/B1')+1],'E1')

    def test_arrival_just_after_boundary_does_not_preempt_running_block(self):
        d,b,m,r=run(b1=89_900_000)
        seq=maths(d);self.assertEqual(seq[seq.index('R0/B1')+1],'R0/B2')

    def test_serial_control_masks_only_mid_context_policy_decision(self):
        d,b,m,r=run(ORDER[0],b1=110_000_000)
        seq=maths(d);self.assertEqual(seq[seq.index('R0/B1')+1],'R0/B2')
        self.assertGreater(seq.index('E1'),seq.index('R0/B2'))

    def test_multiple_experts_and_version_dependency_progress(self):
        d,b,m,r=run(expert=350_000_000)
        seq=maths(d);self.assertEqual(seq[:2],['E0','E1'])
        self.assertLess(seq.index('R0/B2'),seq.index('E2'))
        self.assertTrue(any(len(x['version_wait_experts'])>=2 for x in r['progress']))
        self.assertEqual(len(r['experts']),4);b.validate_and_persist()

    def test_fifo_backlog_keeps_original_release_times(self):
        d,b,m,r=run(expert=350_000_000,cycles=8)
        contexts=[x for x in r['arrivals'] if x['kind']=='Context']
        self.assertEqual([x['release_ns']-r['t0_ns'] for x in contexts],[0,200_000_000,400_000_000,600_000_000])
        self.assertTrue(any(x['observed_host_ns']>x['release_ns'] for x in contexts))
        self.assertGreater(max(x['context_backlog'] for x in r['progress']),1)
        self.assertEqual([x[1] for x in m.journal if x[0]=='publish'],list(range(5)))
        self.assertEqual(r['statistics']['backlog'],0)

    def test_no_job_executes_before_its_logical_release(self):
        for policy in ORDER:
            d,b,m,r=run(policy)
            for x in r['decisions']:
                if x['kind']!='idle_until_arrival':self.assertGreaterEqual(x['host_ns'],x['release_ns'])

    def test_same_versions_ledger_complete_work_both_policies(self):
        runs=[run(p,b1=110_000_000) for p in ORDER]
        for d,b,m,r in runs:
            self.assertEqual(r['manifest'],runs[0][3]['manifest'])
            self.assertEqual([x[2] for x in m.journal if x[0]=='bind'],[0,0,1,1])
            self.assertEqual(sorted(maths(d)),sorted(maths(runs[0][0])))
            self.assertEqual(len(r['units']),4);self.assertEqual(len(r['published']),2)
            b.validate_and_persist()

    def test_reader_pins_prevent_reclaim_and_stale_generation(self):
        d,b,m,r=run(cycles=8,b1=110_000_000)
        self.assertEqual(m.generations,[3,2])
        journal=m.journal
        for idx,x in enumerate(journal):
            if x[0]=='reclaim':
                v=x[1]
                done=[i for i,y in enumerate(journal) if y[0]=='expert_done' and y[2]==v]
                self.assertTrue(done);self.assertLess(max(done),idx)
        with self.assertRaises(ValueError):m.get(old.Handle(0,1,0))

    def test_early_publish_and_inflight_reader_still_blocked(self):
        d=Device();b=BoundaryBackend(d,old.SNAPS,layout=retention_layout(4));m=VersionedKV()
        b.prepare(m,None,{});b.bootstrap(m,'bootstrap');h=m.begin(1,old.SNAPS[1])
        with self.assertRaises(RuntimeError):m.publish(h)
        m.bind('held',old.SNAPS[0].noise_sha)
        for i in (0,1):
            m.submit_block(h,i,old.SNAPS[1],BLOCKS[i],old.Event());self.assertTrue(m.poll_block(h))
        oldh=m.current;m.publish(h)
        with self.assertRaises(RuntimeError):m.reclaim(oldh)

    def test_pending_event_timeout_preserves_all_denominators_and_bank(self):
        class Pending(Device):
            def mark(self,key,index):
                e=super().mark(key,index)
                if key=='R0/B1' and index==7:e.done=False
                return e
        d=Pending();b=BoundaryBackend(d,old.SNAPS,layout=retention_layout(4));m=VersionedKV();r={}
        with self.assertRaises(TimeoutError):run_segment(m,old.SNAPS,ORDER[1],b,r,d.clock)
        self.assertFalse(b.window);self.assertFalse(b.bank.reusable)
        self.assertEqual(r['statistics']['cycle_counts']['denominator'],4)
        self.assertEqual(r['statistics']['refresh_counts']['denominator'],2)
        self.assertTrue(r['remaining_Context_ids']);self.assertIsNone(r['statistics']['response_upper_p99_ns'])
        self.assertFalse(d.operations['R0/B1']['completed'])
        with self.assertRaises(RuntimeError):m.publish(m.slots[1].handle)

    def test_failure_exit_is_incomplete_not_silent_drop(self):
        d=Device(fail_at='E1');b=BoundaryBackend(d,old.SNAPS,layout=retention_layout(4));m=VersionedKV();r={}
        with self.assertRaises(TimeoutError):run_segment(m,old.SNAPS,ORDER[1],b,r,d.clock)
        self.assertEqual(r['statistics']['cycle_counts']['denominator'],4)
        self.assertIn(1,r['remaining_Expert_ids']);self.assertFalse(b.bank.reusable)

    def test_no_d2h_comparison_write_in_performance_window(self):
        d,b,m,r=run();b.validate_and_persist()
        active=False
        for x in d.trace:
            if x[0]=='window':active=x[1]
            if x[0] in ('prepare','bootstrap','ready','deferred','eager_compare'):self.assertFalse(active)
            if x[0] in ('restore','capture','math'):self.assertTrue(active)

    def test_t0_after_ready_and_late_work_drained_without_reset(self):
        d,b,m,r=run(expert=350_000_000)
        self.assertGreater(r['t0_ns'],next(x[1] for x in d.trace if x[0]=='ready'))
        self.assertEqual(r['statistics']['cycle_counts']['denominator'],4)
        self.assertEqual(r['statistics']['cycle_counts']['FAIL'],4)
        self.assertEqual(r['statistics']['backlog'],0);self.assertIsNone(r['statistics']['k_min'])

    def test_full_retention_survives_source_reuse(self):
        d,b,m,r=run(cycles=8)
        first=copy.deepcopy(d.outputs['E0/raw'])
        d.physical.clear();self.assertTrue(b.validate_and_persist()['pass_'])
        self.assertEqual(first,('raw','E0',0))

    def test_capacity_generation_and_missing_evidence_rejected(self):
        l=retention_layout(4)
        with self.assertRaises(ValueError):RetentionLedger(l,l['nbytes']-1)
        bank=RetentionLedger(l,l['nbytes']);bank.begin(0)
        with self.assertRaises(ValueError):bank.claim('E0/raw',old.Handle(0,2,0),old.SNAPS[0])
        with self.assertRaises(RuntimeError):bank.complete()

    def test_observation_modes_share_same_math_and_schedule(self):
        ds=[run(mode=mode,b1=110_000_000) for mode in ('performance','correctness')]
        self.assertEqual(maths(ds[0][0]),maths(ds[1][0]))
        self.assertEqual(ds[0][2].journal,ds[1][2].journal)

    def test_protocol_work_budget_and_no_m2_mutation(self):
        p=protocol();self.assertNotEqual(PROTOCOL,'m2_clean_serial_v1')
        self.assertEqual(p['explicit_work']['total_C'],15);self.assertEqual(p['explicit_work']['total_E'],13)
        self.assertEqual(p['retention']['nbytes'],243660032)
        self.assertEqual(len(p['candidates']),2)
        self.assertNotIn('torch',sys.modules);self.assertNotIn('numpy',sys.modules)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--json',type=Path);a=ap.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    data=dict(status='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,
              failures=len(result.failures),errors=len(result.errors),scope='CPU symbolic scheduling/ownership only; no GPU correctness/performance claim',
              model_starts=0,hardware_writes=0,scopes=0)
    if a.json:a.json.write_text(json.dumps(data,indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
