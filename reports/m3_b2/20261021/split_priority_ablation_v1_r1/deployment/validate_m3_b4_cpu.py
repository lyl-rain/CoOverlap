"""CPU regressions for the M3 split x priority ablation (no GPU, no hardware).

Drives the real ownership state machine, the real candidate loop and the real
retention/attribution paths through the symbolic device already used for the r2
suites. The four cells must differ only by their declared block plan and Expert
decision policy; everything else is shared and asserted here.
"""
import argparse
import hashlib
import json
import os
import re
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

from m2_clean_core import retention_layout
from m2_executor import VersionedKV
from m3_b2_backend import BoundaryBackend
from m3_b2_core import run_segment
from m3_b3_orchestrate import describe_active, export_failed_retention
from m3_b3_plan import CONTROL, THREE
from m3_b4_plan import (CELLS, CYCLES, PLANS, PROTOCOL, RUN, SEGMENT_IDS, budget,
                        manifest, protocol)
from validate_m3_b3_cpu import PlanDevice, SNAPS, maths, run as b3_run
from validate_m3_b3_entry_cpu import _augment, _math_for, _require, _write_tables


def _records():
    return [dict(index=i, candidate=c['cell'], cell=c['cell'], pass_=c['pass_'],
                 policy=c['policy'], plan=c['plan'], segment_id=SEGMENT_IDS[i],
                 status='NOT_STARTED') for i, c in enumerate(RUN)]

PHASE = 15_000_000


def run_cell(cell, cycles=CYCLES, expert=74_000_000, phase=PHASE):
    plan = PLANS[cell['plan']]
    d = PlanDevice(plan=plan, expert=expert)
    conf = manifest(cycles=cycles, phase_ns=phase)
    backend = BoundaryBackend(d, SNAPS, 'performance',
                              layout=retention_layout(cycles, plan), plan=plan)
    manager = VersionedKV(plan)
    record = {}
    run_segment(manager, SNAPS, cell['policy'], backend, record, d.clock, conf=conf, expect=conf)
    return d, backend, manager, record


def interleaved_refreshes(d):
    """Refreshes where an Expert call appears before that refresh's last block."""
    out, current, done, nblocks = set(), None, 0, len(d.plan)
    for call in maths(d):
        if call.startswith('R'):
            q = int(call[1:call.index('/')])
            if q != current:
                current, done = q, 0
            done += 1
        elif call.startswith('E') and current is not None and done < nblocks:
            out.add(current)
    return out


class AblationTests(unittest.TestCase):
    def test_four_cells_and_two_declared_passes(self):
        p = protocol()
        self.assertEqual(p['id'], PROTOCOL)
        self.assertEqual(len(p['cells']), 4)
        by = {c['id'][0]: c for c in p['cells']}
        self.assertEqual((by['A']['plan'], by['A']['policy']), (CONTROL.id, 'serial_context'))
        self.assertEqual((by['B']['plan'], by['B']['policy']), (CONTROL.id, 'b2_boundary'))
        self.assertEqual((by['C']['plan'], by['C']['policy']), (THREE.id, 'serial_context'))
        self.assertEqual((by['D']['plan'], by['D']['policy']), (THREE.id, 'b2_boundary'))
        self.assertEqual(by['A']['plan'], by['B']['plan'])
        self.assertEqual(by['C']['plan'], by['D']['plan'])
        self.assertEqual(by['A']['policy'], by['C']['policy'])
        self.assertEqual(by['B']['policy'], by['D']['policy'])
        self.assertEqual(len(RUN), 8)
        self.assertEqual(len(set(SEGMENT_IDS)), 8)
        self.assertEqual([r['pass_'] for r in RUN], [1] * 4 + [2] * 4)
        self.assertEqual([r['cell'][0] for r in RUN], ['A', 'B', 'C', 'D', 'D', 'C', 'B', 'A'])
        self.assertEqual(p['pass_order'], [['A', 'B', 'C', 'D'], ['D', 'C', 'B', 'A']])
        for entry in RUN:
            self.assertIn(entry['plan'], PLANS)
            self.assertIn(entry['policy'], ('serial_context', 'b2_boundary'))

    def test_candidate_config_drives_policy_and_plan(self):
        device = PlanDevice()
        records = _records()
        with tempfile.TemporaryDirectory() as tmp:
            from m3_b3_orchestrate import run_candidates
            summary = run_candidates(device, SNAPS, RUN, PLANS, 'performance', Path(tmp),
                                     device.clock, _require, _math_for, list(SEGMENT_IDS),
                                     manifest(), records, _augment, None)
        self.assertEqual([row['segment_id'] for row in summary], list(SEGMENT_IDS))
        for row, entry, record in zip(summary, RUN, records):
            self.assertEqual(row['policy'], entry['policy'])
            self.assertEqual(row['plan'], entry['plan'])
            self.assertEqual(record['mode'], entry['policy'])
            self.assertEqual(record['block_plan']['id'], entry['plan'])
            self.assertEqual(record['protocol'], PROTOCOL)
        bad = [dict(RUN[0], policy='unreviewed')]
        with self.assertRaises(ValueError):
            from m3_b3_orchestrate import run_candidates
            run_candidates(PlanDevice(), SNAPS, bad, PLANS, 'performance', Path('/tmp'),
                           lambda: 0, _require, _math_for, [bad[0]['id']], manifest(), [{}],
                           _augment, None)

    def test_serial_context_suppresses_experts_during_a_running_context(self):
        for cell in (CELLS[0], CELLS[2]):
            d, backend, manager, r = run_cell(cell)
            self.assertEqual(r['status'], 'DRAINED_PENDING_VALIDATION')
            experts = [x for x in r['decisions'] if x['kind'] == 'Expert']
            # serial_context: a refresh's legal blocks are contiguous in call order.
            self.assertFalse([x for x in interleaved_refreshes(d) if isinstance(x, int)],
                             'serial_context interleaved an Expert inside a refresh')
            self.assertTrue(r.get('publication_deferred'))
            self.assertTrue(r.get('publication_unblocking_experts'))
            for j in r['publication_unblocking_experts']:
                first = next(x for x in experts if x['id'] == j)
                self.assertGreaterEqual(first['host_ns'], first['release_ns'])
            backend.validate_and_persist()

    def test_boundary_services_released_experts_only_at_legal_boundaries(self):
        for cell in (CELLS[1], CELLS[3]):
            d, backend, manager, r = run_cell(cell)
            self.assertEqual(r['status'], 'DRAINED_PENDING_VALIDATION')
            # b2_boundary serves an already released Expert at a legal block
            # boundary, so some refresh must show an Expert between its blocks.
            self.assertTrue([x for x in interleaved_refreshes(d) if isinstance(x, int)],
                            'boundary policy never served an Expert at a block boundary')
            self.assertFalse(r.get('publication_deferred'))
            backend.validate_and_persist()

    def test_context_runs_uninterrupted_when_no_expert_is_ready(self):
        conf = manifest()
        for e in conf['experts']:
            e['release_ns'] += 150_000_000
            e['deadline_ns'] += 150_000_000
        for cell in CELLS:
            plan = PLANS[cell['plan']]
            d = PlanDevice(plan=plan)
            backend = BoundaryBackend(d, SNAPS, 'performance',
                                      layout=retention_layout(CYCLES, plan), plan=plan)
            manager = VersionedKV(plan)
            record = {}
            run_segment(manager, SNAPS, cell['policy'], backend, record, d.clock,
                        conf=conf, expect=conf)
            nblocks = len(plan)
            first = [x for x in record['decisions'] if x['kind'] in ('Context', 'Expert')][:nblocks]
            self.assertTrue(all(x['kind'] == 'Context' for x in first),
                            'a Context was interleaved with an unreleased Expert')
            self.assertEqual([x['block'] for x in first], list(range(nblocks)))
            backend.validate_and_persist()

    def test_queued_experts_and_version_waits_still_drain(self):
        for cell in CELLS:
            d, backend, manager, r = run_cell(cell, expert=350_000_000)
            self.assertEqual(r['status'], 'DRAINED_PENDING_VALIDATION')
            self.assertEqual(r['statistics']['cycle_counts']['denominator'], CYCLES)
            self.assertEqual(r['statistics']['refresh_counts']['denominator'], CYCLES // 2)
            self.assertTrue(any(p.get('version_wait_experts') for p in r['progress']),
                            'queueing scenario did not exercise a version dependency wait')
            misses = sum(r['statistics']['cycle_counts'][k] for k in ('FAIL', 'UNCERTAIN', 'INCOMPLETE'))
            self.assertGreater(misses, 0, 'deadline misses must stay in the denominator')
            self.assertEqual(r['statistics']['cycle_counts']['denominator'], CYCLES)
            backend.validate_and_persist()

    def test_context_fifo_and_publication_order(self):
        for cell in CELLS:
            d, backend, manager, r = run_cell(cell)
            self.assertEqual([int(v) for v in r['published']], list(range(CYCLES // 2)))
            begins = [x[1] for x in manager.journal if x[0] == 'begin']
            self.assertEqual(begins, sorted(begins), 'Context versions must be FIFO')
            context_rows = [x for x in r['decisions'] if x['kind'] == 'Context']
            self.assertEqual(sorted({x['id'] for x in context_rows}), list(range(CYCLES // 2)))
            for q in range(CYCLES // 2):
                blocks = [x['block'] for x in context_rows if x['id'] == q]
                self.assertEqual(blocks, list(range(len(PLANS[cell['plan']]))))
            backend.validate_and_persist()

    def test_all_cells_share_inputs_binding_releases_and_call_totals(self):
        conf = manifest()
        p = protocol()
        self.assertEqual(p['manifest'], conf)
        self.assertEqual(conf['phase_ns'], PHASE)
        self.assertEqual(len(conf['experts']), CYCLES)
        self.assertEqual(len(conf['refreshes']), CYCLES // 2)
        for e in conf['experts']:
            self.assertEqual(e['deadline_ns'] - e['release_ns'], conf['period_ns'])
            self.assertEqual(e['version'], e['id'] // 2)
        totals = {}
        for cell in CELLS:
            d, backend, manager, r = run_cell(cell)
            result = backend.validate_and_persist()
            self.assertTrue(result['pass_'])
            totals[cell['id']] = (len(r['units']), len(r['experts']), len(r['published']))
            self.assertEqual(len(r['units']), CYCLES)
        self.assertEqual(len(set(totals.values())), 1, 'cells must complete identical work')

    def test_protocol_recorded_from_manifest_not_a_hardcoded_constant(self):
        d, backend, manager, r = run_cell(CELLS[1])
        self.assertEqual(r['protocol'], PROTOCOL)
        self.assertEqual(r['manifest']['schema'], PROTOCOL)
        # r2's defect was an inherited constant; the field must follow the manifest.
        conf = dict(manifest(), schema='m3_b3_three_block_v1')
        plan = CONTROL
        other = PlanDevice(plan=plan)
        backend = BoundaryBackend(other, SNAPS, 'performance',
                                  layout=retention_layout(CYCLES, plan), plan=plan)
        record = {}
        run_segment(VersionedKV(plan), SNAPS, 'b2_boundary', backend, record, other.clock,
                    conf=conf, expect=conf)
        self.assertEqual(record['protocol'], 'm3_b3_three_block_v1')
        self.assertNotEqual(record['protocol'], PROTOCOL)

    def test_multi_segment_run_has_unique_ids_and_safe_bank_reuse(self):
        from m3_b3_orchestrate import run_candidates
        device = PlanDevice()
        records = _records()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = run_candidates(device, SNAPS, RUN, PLANS, 'performance', out,
                                     device.clock, _require, _math_for, list(SEGMENT_IDS),
                                     manifest(), records, _augment, _write_tables)
            self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(SEGMENT_IDS))
        self.assertEqual(device.audited_segments, set(SEGMENT_IDS))
        self.assertFalse(device.leased)
        self.assertEqual(sum(1 for x in device.trace if x[0] == 'deferred'), len(RUN))
        for record, segment_id in zip(records, SEGMENT_IDS):
            self.assertEqual(record['segment_id'], segment_id)
            self.assertEqual(record['protocol'], PROTOCOL)
        self.assertEqual(len({row['segment_id'] for row in summary}), len(RUN))

    def test_failure_in_a_middle_segment_is_attributed_to_it(self):
        from m3_b3_orchestrate import run_candidates

        class Failing(PlanDevice):
            def run_math(self, key, slot, kind):
                if self.label() == SEGMENT_IDS[4] and key == 'E3':
                    raise TimeoutError('injected middle-segment failure')
                return super().run_math(key, slot, kind)

        device = Failing()
        active = {}
        records = _records()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self.assertRaises(TimeoutError):
                run_candidates(device, SNAPS, RUN, PLANS, 'performance', out, device.clock,
                               _require, _math_for, list(SEGMENT_IDS), manifest(), records,
                               _augment, None, active=active)
            info = describe_active(active)
            self.assertEqual(info['segment_id'], SEGMENT_IDS[4])
            self.assertEqual(info['plan'], 'three_prefix_9_9')
            self.assertEqual(info['layout']['nbytes'], budget()['layouts']['three_prefix_9_9']['nbytes'])
            self.assertEqual(info['policy'], 'b2_boundary')
            status = export_failed_retention(device, active, out, device.clock() + 10**12,
                                             device.clock)
            self.assertEqual(status['segment_id'], SEGMENT_IDS[4])
            self.assertEqual(status['layout_nbytes'], 597_617_152)
            self.assertEqual(device.downloads, [(0, 597_617_152)])
            self.assertNotIn('PASS', status['status'])
            self.assertNotEqual(records[4]['status'], 'PASS')

    def test_window_has_no_intrusive_observation(self):
        for cell in CELLS:
            d, backend, manager, r = run_cell(cell)
            active = False
            for row in d.trace:
                if row[0] == 'window':
                    active = row[1]
                if row[0] in ('prepare', 'bootstrap', 'ready', 'deferred', 'eager_compare'):
                    self.assertFalse(active, '%s: %s inside the window' % (cell['id'], row[0]))
                if row[0] in ('restore', 'capture', 'math'):
                    self.assertTrue(active, '%s: %s outside the window' % (cell['id'], row[0]))
            self.assertFalse(any(x[0] == 'eager_compare' for x in d.trace))
            backend.validate_and_persist()

    def test_b4_files_are_spec_only_variants_of_the_r2_ones(self):
        base = Path(__file__).parent

        def strip_doc(text):
            return re.sub(r'^""".*?"""', '', text, count=1, flags=re.S)

        b3 = strip_doc((base / 'm3_b3_control.py').read_text())
        b4 = strip_doc((base / 'm3_b4_control.py').read_text())
        spec = [
                ('from m3_b3_plan import PROTOCOL, protocol', 'from m3_b4_plan import PROTOCOL, protocol'),
                ("'m3_b3_control.py' not in first", "'m3_b4_control.py' not in first"),
                ("str(base/'pi05_m3_b3_prepare.py')", "str(base/'pi05_m3_b4_ablation.py')"),
                ('--approved-m3-b3-three-block-v1', '--approved-m3-b4-split-priority-ablation-v1'),
                ('cooverlap-m3-b3-three-block-20261021-run01', 'cooverlap-m3-b4-ablation-20261021-run01'),
                ("str(base/'m3_b3_control.py')", "str(base/'m3_b4_control.py')")]
        normalised = b4
        for old, new in spec:
            normalised = normalised.replace(new, old)
        self.assertEqual(normalised, b3, 'controller differs beyond the declared spec')
        entry3 = (base / 'pi05_m3_b3_prepare.py').read_text()
        entry4 = (base / 'pi05_m3_b4_ablation.py').read_text()
        start, end = '    def ready(phase, d, logical):', '        device = CudaDevice('
        self.assertEqual(entry3[entry3.index(start):entry3.index(end)],
                         entry4[entry4.index(start):entry4.index(end)],
                         'the fixed physical initial state / readiness block changed')


class CredentialTests(unittest.TestCase):
    """Drive the REAL entry through its credential branch (no CUDA, no model)."""

    def _base(self, tmp):
        base = Path(tmp)/'base'
        base.mkdir()
        (base/'CONFIG.json').write_text(json.dumps(protocol(), indent=2)+'\n')
        digest = hashlib.sha256((base/'CONFIG.json').read_bytes()).hexdigest()
        (base/'DEPLOY_SHA256.txt').write_text(digest+'  CONFIG.json\n')
        run = Path(tmp)/'run_01'
        run.mkdir()
        return base, run

    def _credential(self, base, run, protocol_id=PROTOCOL, created=None, package=None):
        import m3_b4_control
        doc = dict(protocol=protocol_id, host=socket.gethostname(), uid=os.geteuid(),
                   created=time.time() if created is None else created,
                   base=str(base.resolve()), run=str(run.resolve()),
                   package=package if package is not None else m3_b4_control.package_files(base),
                   sources={})
        path = run/'PREFLIGHT.json'
        path.write_text(json.dumps(doc))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _run_main(self, base, run, out):
        import pi05_m3_b4_ablation as entry
        reached = []

        class Reached(BaseException):
            pass

        def sentinel(*a, **k):
            reached.append(dict(args=a, kwargs=k))
            raise Reached('prepare was reached')

        entry.prepare = sentinel
        argv = ['pi05_m3_b4_ablation.py', '--approved-m3-b4-split-priority-ablation-v1',
                '--config', str(base/'CONFIG.json'), '--out', str(out),
                '--reference', str(base), '--source-preflight', str(run/'PREFLIGHT.json')]
        saved_argv = sys.argv
        saved_env = {k: os.environ.pop(k) for k in list(os.environ)
                     if k == 'LD_PRELOAD' or k.startswith(('NSYS_', 'KINETO_', 'TORCH_PROFILER_',
                                                           'CUPTI_INJECTION', 'CUDA_INJECTION'))}
        os.environ['COOVERLAP_APPROVED_BATCH'] = PROTOCOL
        sys.argv = argv
        try:
            entry.main()
        except BaseException as exc:
            return exc, reached, entry
        finally:
            sys.argv = saved_argv
            os.environ.pop('COOVERLAP_APPROVED_BATCH', None)
            os.environ.update(saved_env)
        raise AssertionError('main() returned without reaching prepare')

    def test_valid_b4_credential_reaches_prepare_without_cuda(self):
        import m3_b4_control
        with tempfile.TemporaryDirectory() as tmp:
            base, run = self._base(tmp)
            self._credential(base, run)
            out = run/'model'
            exc, reached, entry = self._run_main(base, run, out)
            report = json.loads((out/'result.json').read_text())
            self.assertEqual(type(exc).__name__, 'Reached',
                             'valid B4 credential did not reach prepare')
            self.assertEqual(len(reached), 1)
            self.assertEqual(report['status'], 'FAIL_OR_INCOMPLETE')
            self.assertEqual(report['failed_phase'], dict(kind=None, reason='no_active_phase'))
            self.assertEqual(report['protocol']['id'], PROTOCOL)
        # behavioural proof + runtime/static supplements
        self.assertIn('m3_b4_control', sys.modules)
        self.assertNotIn('m3_b3_control', sys.modules,
                         'the r2 controller (and its r2 PROTOCOL) must not be used')
        self.assertIn('from m3_b4_control import sha, verify_credential',
                      Path(entry.__file__).read_text())
        self.assertNotIn('torch', sys.modules, 'the credential branch must not import CUDA')

    def test_old_b3_protocol_credential_is_rejected_before_prepare(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, run = self._base(tmp)
            self._credential(base, run, protocol_id='m3_b3_three_block_v1')
            out = run/'model'
            exc, reached, _ = self._run_main(base, run, out)
            self.assertIsInstance(exc, ValueError)
            self.assertIn('stale/wrong credential', str(exc))
            self.assertEqual(reached, [], 'prepare ran despite a rejected credential')
            self.assertFalse(out.exists(), 'an out dir was created before the credential passed')

    def test_expired_credential_is_rejected_before_prepare(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, run = self._base(tmp)
            self._credential(base, run, created=time.time()-601)
            out = run/'model'
            exc, reached, _ = self._run_main(base, run, out)
            self.assertIsInstance(exc, ValueError)
            self.assertIn('stale/wrong credential', str(exc))
            self.assertEqual(reached, [])
            self.assertFalse(out.exists())

    def test_changed_package_is_rejected_before_prepare(self):
        import m3_b4_control
        with tempfile.TemporaryDirectory() as tmp:
            base, run = self._base(tmp)
            package = dict(m3_b4_control.package_files(base))
            package['CONFIG.json'] = dict(package['CONFIG.json'], sha256='0'*64)
            self._credential(base, run, package=package)
            out = run/'model'
            exc, reached, _ = self._run_main(base, run, out)
            self.assertIsInstance(exc, ValueError)
            self.assertIn('package changed after CPU preflight', str(exc))
            self.assertEqual(reached, [])
            self.assertFalse(out.exists())

    def test_wrong_credential_sha_is_rejected_at_the_controller(self):
        import m3_b4_control
        with tempfile.TemporaryDirectory() as tmp:
            base, run = self._base(tmp)
            self._credential(base, run)
            with self.assertRaises(ValueError) as ctx:
                m3_b4_control.verify_credential(base, run, '0'*64)
            self.assertIn('credential SHA changed', str(ctx.exception))
            good = self._credential(base, run)
            doc = m3_b4_control.verify_credential(base, run, good)
            self.assertEqual(doc['protocol'], PROTOCOL)


class DiskBudgetTests(unittest.TestCase):
    def test_disk_budget_items_reconcile_with_the_r2_measurements(self):
        d = budget()['disk']
        self.assertEqual(d['retention_payload_bytes'],
                         4*597_617_152 + 4*487_320_064)
        self.assertEqual(d['gate_payload_bytes'], 2*124_121_472)
        self.assertEqual(d['initial_snapshot_bytes'], 10*25_276_416)
        self.assertEqual(d['bootstrap_snapshot_bytes'], 10*12_638_208)
        self.assertEqual(d['fixed_binary_bytes'], 120_076_776)
        self.assertEqual(d['labels'], 10)
        self.assertEqual(d['binary_total_bytes'], 5_087_214_824)
        self.assertGreaterEqual(d['estimate_bytes'],
                                d['binary_total_bytes']+d['json_csv_log_bytes'])
        self.assertLess(d['estimate_bytes'], d['admission_bytes'])
        self.assertEqual(protocol()['retention']['disk'], d)
        self.assertNotIn('artifact_bytes', budget())
        self.assertNotIn('disk_bytes', budget())

    def test_disk_admission_is_the_actual_12_gib_check_everywhere(self):
        base = Path(__file__).parent
        control = (base/'m3_b4_control.py').read_text()
        prep = (base/'pi05_m2_clean.py').read_text()
        plan = (base/'m3_b4_plan.py').read_text()
        self.assertIn('12*1024**3', control)
        self.assertNotIn('8*1024**3', control)
        self.assertIn('disk_space_12GiB', prep)
        self.assertIn('12*1024**3', prep)
        self.assertNotIn('8 * 1024**3', plan)
        d = budget()['disk']
        self.assertEqual(d['admission_bytes'], 12*1024**3)
        self.assertEqual(d['admission_gib'], 12)
        self.assertEqual(len(d['admission_source']), 2)
        self.assertNotIn('disk_required_bytes', protocol()['retention'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    suite = unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromTestCase(cls)
        for cls in (AblationTests, CredentialTests, DiskBudgetTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    data = dict(status='PASS' if result.wasSuccessful() else 'FAIL', tests=result.testsRun,
                failures=len(result.failures), errors=len(result.errors),
                scope='CPU: four plan/policy cells, policy plumbing, serial vs boundary, queue/version waits,'
                      ' multi-segment reuse, failure attribution, real-entry credential branch (B4 accepted;'
                      ' B3/expired/package-change/wrong-SHA rejected, sentinel at prepare, no CUDA import),'
                      ' itemized disk budget and the uniform 12 GiB admission;'
                      ' no GPU correctness or performance claim',
                model_starts=0, hardware_writes=0, scopes=0)
    if args.json:
        args.json.write_text(json.dumps(data, indent=2) + '\n')
    sys.exit(0 if result.wasSuccessful() else 1)
