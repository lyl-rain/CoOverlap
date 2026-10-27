"""PREPARED ONLY: one newly approved M3 four-condition controlled-interference batch.

Four conditions under the SAME two_9_9 plan and P=D=180 ms: A quiet/serial,
B quiet/b2_boundary, C fixed_cpu_mem/serial, D fixed_cpu_mem/b2_boundary;
order A,B,C,D,D,C,B,A, each 8 cycles / 4 refreshes, Expert phase +15 ms.
Every segment uses the same relative release/deadline manifest; the worker and
replay share one t0 per segment. Not authorized by, and does not reuse, any
previous M3/M2 one-shot approval. No graph, concurrency, partition, new cut
point, extra phase/intensity/budget/probe/warm-up. The frozen math bodies in
``m2_pi05_ops`` are called unchanged; cells differ only by interference and
the Expert decision policy.

Entry orchestration (gates, prefix reference, candidate loop) lives in
``m3_b3_orchestrate`` so the shipped sequence is also the CPU-tested sequence.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback
from m2_clean_core import gate_retention_layout
from m2_clean_stats import augment, write_tables
from m3_b3_orchestrate import (INTERRUPT_GATE, OLD_READER_GATE, describe_active,
                               export_failed_retention, mark_active, run_candidates,
                               run_gate, run_prefix_reference)
from m3_b3_plan import CONTROL, THREE
from m3_b6_plan import (CELLS, CYCLES, GATE_PLAN, PERIOD_NS, PLANS, PROTOCOL,
                        RESULT_STATUS, RUN, SEGMENT_IDS,
                        budget, manifests, protocol)
from m3_b6_window import SegmentWindow
from m3_m2_preparation import prepare, preparation_audit


def jsonable(v):
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--approved-m3-b6-controlled-interference-v1', action='store_true')
    ap.add_argument('--verification-mode', choices=['performance', 'correctness'],
                    default='performance')
    for k in ('config', 'out', 'reference', 'source-preflight'):
        ap.add_argument('--' + k, type=Path)
    args = ap.parse_args()
    if args.config and json.loads(args.config.read_text()) != protocol():
        raise ValueError('frozen M3 controlled-interference configuration changed')
    _, _, audit = preparation_audit()
    if args.dry_run:
        print(json.dumps(dict(protocol=protocol(), preparation_reuse=audit), indent=2))
        return
    if (not args.approved_m3_b6_controlled_interference_v1
            or os.environ.get('COOVERLAP_APPROVED_BATCH') != PROTOCOL):
        ap.error('NEW M3 controlled-interference approval required before GPU imports; '
                 'previous M3/M2 authorizations are invalid')
    if None in (args.config, args.out, args.reference, args.source_preflight):
        ap.error('all paths required')
    if os.geteuid() == 0:
        raise PermissionError('model must be ordinary nvidia')
    # Verify this B6 package and its own CPU preflight credential.
    from m3_b6_control import sha, verify_credential
    credential = verify_credential(args.config.parent, args.source_preflight.parent,
                                   sha(args.source_preflight))
    for k, v in os.environ.items():
        if v and (k.startswith(('NSYS_', 'KINETO_', 'TORCH_PROFILER_', 'CUPTI_INJECTION',
                                'CUDA_INJECTION')) or k == 'LD_PRELOAD'):
            raise RuntimeError('unexpected injection ' + k)
    args.out.mkdir(exist_ok=False)
    report = dict(status='INCOMPLETE', protocol=protocol(),
                  segments=[dict(index=i, candidate=c['cell'], cell=c['cell'],
                                 pass_=c['pass_'], interference=c['interference'],
                                 policy=c['policy'], plan=c['plan'],
                                 period_ns=c['period_ns'], segment_id=SEGMENT_IDS[i],
                                 status='NOT_STARTED', planned_Experts=CYCLES,
                                 planned_Context=CYCLES//2)
                            for i, c in enumerate(RUN)],
                  gates={name: dict(status='INCOMPLETE', segment_id=gate_id)
                         for name, gate_id in ((OLD_READER_GATE, 'gate_old_reader'),
                                               (INTERRUPT_GATE, 'gate_interrupt'))},
                  checks=[], source_config_fingerprints={k: v['sha256']
                                                         for k, v in credential['package'].items()},
                  config_sha256=sha(args.config),
                  source_preflight_sha256=sha(args.source_preflight),
                  preparation_reuse=audit, observation_mode=args.verification_mode,
                  interpretation='four-condition controlled-interference mechanism check under '
                                 'the same two_9_9/180 ms workload; no reliable-tail, k_min, '
                                 'final-route or net-benefit claim',
                  worker_process_plan=dict(model_processes=1, max_workers=4,
                                           simultaneous_workers=1, quiet_workers=0,
                                           fixed_workers=4, retries=0,
                                           helper='python shared-memory/resource-tracker if present'),
                  time_budget=budget()['time_budget'],
                  worker_budget=budget()['worker_budget'])
    start = time.monotonic()
    deadline = time.monotonic_ns() + 170_000_000_000

    def save():
        tmp = args.out/'result.tmp'
        tmp.write_text(json.dumps(jsonable(report), indent=2))
        tmp.replace(args.out/'result.json')

    def require(ok, name):
        report['checks'].append(dict(name=name, pass_=bool(ok)))
        if not ok:
            save()
            raise AssertionError(name)

    def bound():
        if time.monotonic_ns() >= deadline:
            raise TimeoutError('170s internal cutoff; zero retry')
        if int(Path('/sys/devices/virtual/thermal/thermal_zone0/temp').read_text()) >= 80000:
            raise RuntimeError('thermal >=80C')

    def term(*_):
        raise TimeoutError('signal; preserve partial work without retry')
    signal.signal(signal.SIGTERM, term)
    device = None
    # Live holder of the phase that is currently executing; never serialized.
    active = {}
    try:
        e = prepare(args, report, save, require, bound)
        torch, np, owner, ps, ledger = e['torch'], e['np'], e['owner'], e['ps'], e['ledger']
        p0, p1 = ps
        refs, midrefs, snaps = e['refs'], e['midrefs'], e['snaps']
        context, block1, block2 = e['context'], e['block1'], e['block2']
        stage, snap, read = e['stage'], e['snap'], e['read']
        address_manifest, stream, noise_sha = e['address_manifest'], e['stream'], e['noise_sha']
        from m2_pi05_ops import encoder_block, prefix_block
        original = address_manifest(owner, p0, p1, e['attn1'], e['runner1'])
        bank_bytes = budget()['bank_bytes']
        require(torch.cuda.mem_get_info()[0] > 12*1024**3+2*bank_bytes,
                'GPU_and_pinned_retention_budget')
        report['retention_memory'] = dict(bank_bytes=bank_bytes, pinned_bytes=bank_bytes,
                                          budget=budget())
        expected = dict(images=e['images'].view(torch.uint8).cpu().numpy().tobytes(),
                        noise=e['f']['noise0_bf16_bytes'].tobytes())
        for i in (0, 1):
            expected['ref'+str(i)] = b''.join(refs[i][0])
            expected['mid'+str(i)] = b''.join(midrefs[i])
            expected['raw'+str(i)] = refs[i][1]
            for data in (*refs[i][0], *midrefs[i]):
                vals = (np.frombuffer(data, dtype='<u2').astype('<u4') << 16).view('<f4')
                require(np.isfinite(vals).all(), 'finite_same_process_reference')

        # Complete two-block Control per slot: prefix reference at layer-0 entry,
        # then B2, then the FULL Context must equal the same-process reference.
        report['prefix_reference'] = []
        for slot in (0, 1):
            prefix = run_prefix_reference(ps[slot], slot, stage, snap, ledger, block1, block2,
                                          e['ENC_D'], e['VIS_D'], require, refs, midrefs)
            expected['pre'+str(slot)] = prefix
            report['prefix_reference'].append(dict(
                slot=slot, nbytes=len(prefix),
                sha256=hashlib.sha256(prefix).hexdigest(),
                mid_sha256=hashlib.sha256(b''.join(midrefs[slot])).hexdigest(),
                full_sha256=hashlib.sha256(b''.join(refs[slot][0])).hexdigest(),
                complete_context=True,
                source='validated two-block B1+B2 at layer-0 entry; same process/slot'))
        # Three-block assembly must reproduce the same prefix/mid/full/output bytes.
        stage(p0, True)
        ledger.execute('assembly/P', 0, 'P', lambda: prefix_block(p0, e['ENC_D'], e['VIS_D']),
                       expected=[('language',), ('vision27',)], work=THREE.blocks[0])
        prefix_actual = snap(p0, 'assembly_prefix', 0)[0]
        require(prefix_actual == expected['pre0'], 'assembly_prefix_byte_exact')
        ledger.execute('assembly/B1', 0, 'B1', lambda: encoder_block(p0, 0, 9),
                       expected=[('encoder', i) for i in range(9)], work=THREE.blocks[1])
        require(snap(p0, 'assembly_mid', 9) == midrefs[0], 'assembly_mid_byte_exact')
        ledger.execute('assembly/B2', 0, 'B2', lambda: block2(p0),
                       expected=[('encoder', i) for i in range(9, 18)], work=THREE.blocks[2])
        require(snap(p0, 'assembly_full', 18) == refs[0][0], 'assembly_full_context_byte_exact')
        ledger.execute('assembly/Expert', 0, 'Expert', lambda: p0.transformer_decoder(0))
        raw = read(p0.input_noise_buf.ptr.value, 3200)
        require(raw == refs[0][1], 'assembly_raw_byte_exact')
        from flash_rt.core.utils.actions import unnormalize_actions
        vals = torch.from_numpy(np.frombuffer(raw, dtype=np.uint8).copy()).view(
            torch.bfloat16).float().reshape(50, 32).numpy()
        actions = np.ascontiguousarray(unnormalize_actions(vals, owner.norm_stats)[:, :7],
                                       dtype=np.float32).tobytes()
        require(actions == refs[0][2], 'assembly_actions_byte_exact')
        report['assembly'] = dict(prefix_sha256=hashlib.sha256(prefix_actual).hexdigest(),
                                  mid_sha256=hashlib.sha256(b''.join(midrefs[0])).hexdigest(),
                                  full_sha256=hashlib.sha256(b''.join(refs[0][0])).hexdigest(),
                                  raw_sha256=hashlib.sha256(raw).hexdigest(),
                                  actions_sha256=hashlib.sha256(actions).hexdigest(),
                                  note='three declared blocks reassemble the validated full path')

        from m2_clean_cuda import CudaDevice
        from m3_b2_backend import BoundaryBackend

        def math_for(plan):
            if plan is CONTROL:
                return dict(B1=lambda p: block1(p, e['ENC_D'], e['VIS_D']), B2=block2)
            return dict(P=lambda p: prefix_block(p, e['ENC_D'], e['VIS_D']),
                        B1=lambda p: encoder_block(p, 0, 9), B2=block2)

        def bootstrap(m, snapshots, key):
            h = m.begin(0, snapshots[0])
            stage(p0, True)
            ledger.execute(device.label()+'/bootstrap', 0, 'Context', lambda: context(p0))
            ev = torch.cuda.Event(enable_timing=True)
            ev.record(stream)
            ev.synchronize()
            for b in range(len(m.plan)):
                m.submit_block(h, b, snapshots[0], m.plan.blocks[b], ev)
                require(m.poll_block(h), 'bootstrap_complete')
            require(m.get(h).valid_layers == 18, 'bootstrap_publishes_all_18_layers')
            require(snap(p0, device.label()+'_bootstrap') == refs[0][0],
                    'bootstrap_matches_same_process_S0')
            m.publish(h)

        def ready(phase, d, logical):
            require(address_manifest(owner, p0, p1, e['attn1'], e['runner1']) == original,
                    'visible_resources_stable')
            require(torch.cuda.mem_get_info()[0] > 12*1024**3, 'memory_floor')
            for i, p in enumerate(ps):
                require(snap(p, 'initial_'+d.label()+'_S'+str(i)) == refs[i][0],
                        'same_physical_initial_context')
            d.record['initial_state'] = logical
            save()
            for path in args.out.rglob('*'):
                if path.is_file():
                    with path.open('rb') as f:
                        os.fsync(f.fileno())
            stream.synchronize()
            bound()

        device = CudaDevice(torch, np, owner, ps, ledger, expected, [r[2] for r in refs],
                            owner.norm_stats,
                            (context, lambda p: block1(p, e['ENC_D'], e['VIS_D']), block2),
                            bootstrap, ready, args.out, deadline, capacity=bank_bytes,
                            plan=THREE, block_math=math_for(THREE), max_blocks=len(THREE))
        device.images = e['images']
        device.noise = e['noise']
        intervals = original['writable'] + original['shared_readonly']
        require(not any(x['ptr'] and x['nbytes'] and max(device.gptr, x['ptr']) <
                        min(device.gptr+bank_bytes, x['ptr']+x['nbytes']) for x in intervals),
                'bank_no_model_alias')
        require(device.images.is_contiguous() and device.noise.is_contiguous(),
                'contiguous_fixed_inputs')

        # Version-lifecycle gates run on the NEW three-block plan so that
        # "prefix complete with 0 new KV layers cannot publish" is exercised by
        # the real ownership state machine, with exact journal content and order.
        for name, segment_id, interleave in ((OLD_READER_GATE, 'gate_old_reader', False),
                                             (INTERRUPT_GATE, 'gate_interrupt', True)):
            device.use_plan(GATE_PLAN, math_for(GATE_PLAN))
            device.set_segment_id(segment_id)
            gate = report['gates'][name]
            gate.update(plan=GATE_PLAN.id,
                        role='manual interleaving correctness only; not an arrival-policy sample'
                             if interleave else 'old-reader gate')
            backend = BoundaryBackend(device, snaps, 'correctness',
                                      layout=gate_retention_layout(CYCLES, GATE_PLAN), plan=GATE_PLAN)
            manager = __import__('m2_executor').VersionedKV(GATE_PLAN)
            mark_active(active, 'gate', segment_id, GATE_PLAN.id, backend, manager, gate)
            result = run_gate(backend, manager, snaps, noise_sha, GATE_PLAN, interleave, require, gate)
            backend.validate_and_persist()
            gate.update(status='PASS', journal=result['journal'], expected=result['expected'],
                        entries=result['entries'], valid_layers=result['valid_layers'])
            require(result['entries'] == protocol()['gates']['interrupt' if interleave
                                                            else 'old_reader']['journal_entries'],
                    'gate_'+segment_id+'_entries')
            save()

        seg_confs = [manifests()[c['period_ns']] for c in RUN]
        report['manifests'] = {str(ns): conf for ns, conf in manifests().items()}

        def window_factory(index, candidate, seg_conf, record):
            return SegmentWindow(candidate['interference'])

        summary = run_candidates(device, snaps, RUN, PLANS,
                                 args.verification_mode, args.out, time.monotonic_ns, require,
                                 math_for, list(SEGMENT_IDS), None, report['segments'],
                                 augment, write_tables, active=active, confs=seg_confs,
                                 window_factory=window_factory)
        report['segment_summary'] = summary
        require(len({row['segment_id'] for row in summary}) == len(RUN),
                'unique_segment_ids')
        require([row['segment_id'] for row in summary] == list(SEGMENT_IDS),
                'segments_ran_in_declared_order')
        require([row['plan'] for row in summary] == [c['plan'] for c in RUN],
                'cells_ran_with_their_declared_plan')
        require([row['policy'] for row in summary] == [c['policy'] for c in RUN],
                'cells_ran_with_their_declared_policy')
        require(all(row['protocol'] == PROTOCOL for row in summary),
                'segment_protocol_matches_frozen_config')
        require([row['period_ns'] for row in summary] == [c['period_ns'] for c in RUN],
                'segments_ran_with_their_declared_budget')
        report['window_timing'] = protocol()['timing']
        report['interference_condition_check'] = dict(
            all_conditions_valid=bool(summary) and len(summary) == len(RUN)
            and all(row.get('condition_valid') for row in summary),
            fixed_workers=sum(row.get('interference') == 'fixed_cpu_mem' for row in summary),
            quiet_segments=sum(row.get('interference') == 'quiet' for row in summary),
            simultaneous_workers=1, retries=0,
            covered_segments=len(summary),
            coverage_note='positive copies prove work occurred, not continuous bandwidth; '
                          'copy_bytes is logical memmove traffic, not DRAM bandwidth',
            condition_rows=[{k: row.get(k) for k in
                             ('segment_id', 'interference', 'condition_valid', 'comparison_status',
                              'window_t0_ns', 'replay_end_ns')}
                            for row in summary])
        report['interference_summary'] = [{
            k: row.get(k) for k in ('segment_id', 'interference', 'condition_valid', 'comparison_status',
                                    'window_t0_ns', 'replay_end_ns')
        } for row in summary]
        require({row['period_ns'] for row in summary} == {PERIOD_NS},
                'all_segments_use_180ms')
        require(report['interference_condition_check']['all_conditions_valid'],
                'all_interference_conditions_valid')
        require(sum(row.get('interference') == 'fixed_cpu_mem' for row in summary) == 4,
                'four_fixed_workers_declared')
        require(sum(row.get('interference') == 'quiet' for row in summary) == 4,
                'four_quiet_segments')
        require(all((record.get('interference') or {}).get('resource_release', {}).get(
                    'resources_released') for record in report['segments']
                    if record.get('t0_ns') is not None),
                'all_window_resources_released')
        require(all(record.get('protocol') == PROTOCOL for record in report['segments']
                    if record.get('status') != 'NOT_STARTED'),
                'segment_records_carry_this_batch_protocol')
        require(sorted({row['cell'] for row in summary}) == sorted(c['cell'] for c in CELLS),
                'all_four_cells_completed')
        require(address_manifest(owner, p0, p1, e['attn1'], e['runner1']) == original,
                'resources_stable_after_segments')

        from collections import Counter
        counts = dict(Counter(x[2] for x in ledger.calls))
        report['observed_call_counts'] = counts
        observed = protocol()['work']['observed_ledger']
        require(counts == dict(encoder=observed['encoder_layers'],
                               decoder=observed['decoder_layers'],
                               language=observed['language'],
                               vision27=observed['vision27']), 'complete_observed_work')
        require(len(ledger.calls) == observed['rows'], 'observed_ledger_rows')
        require(sum(1 for row in report['segments'] if row.get('status') != 'NOT_STARTED')
                == len(RUN), 'all_segments_completed')
        require(owner._cudart.cudaGetLastError() == 0, 'cuda_last_error')
        report['call_ledger'] = ledger.calls
        report['cross_process_gate'] = dict(
            admission=False,
            within_historical_envelope=all(x['pass_'] for x in report['cross_process']))
        report['status'] = RESULT_STATUS
        report['elapsed_s'] = time.monotonic()-start
        save()
    except BaseException:
        report['status'] = 'FAIL_OR_INCOMPLETE'
        report['error'] = traceback.format_exc()
        report['failed_phase'] = describe_active(active)
        failed_backend = active.get('backend')
        if failed_backend is not None:
            try:
                failed_backend.leave_window()
            except BaseException:
                report.setdefault('cleanup_errors', []).append(traceback.format_exc())
            try:
                report['unfinished_retention'] = failed_backend.bank.metadata()
            except BaseException:
                report['unfinished_retention_error'] = traceback.format_exc()
            report['partial_retention'] = export_failed_retention(
                device, active, args.out, deadline, time.monotonic_ns)
            report['partial_retention_status'] = report['partial_retention']['status']
        else:
            report['partial_retention_status'] = 'NOT_EXPORTED_no_active_segment'
        if 'ledger' in locals():
            report['call_ledger'] = ledger.calls
        report['elapsed_s'] = time.monotonic()-start
        save()
        raise


if __name__ == '__main__':
    main()
