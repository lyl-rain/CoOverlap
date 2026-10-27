"""PREPARED ONLY: one newly approved M3 Expert-reserve selection validation.

Four conditions over the two validated split plans, both with b2_boundary:
A two/180, B three/180, C two/140, D three/140.  Order A,B,C,D,D,C,B,A; each
segment 8 cycles / 4 refreshes, Expert phase +15 ms, lead 10 ms, quiet, no
pressure worker.  The fixed matrix executes BOTH candidates at BOTH budgets, so
the Expert-reserve recommendation never changes what runs; the frozen per-budget
selection is copied into each segment record before its window and checked after
it.  The two budgets are NOT the same wall-clock arrival trace.  Not authorized
by, and does not reuse, any previous M3/M2 one-shot approval.
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
from m3_b10_plan import (BUDGETS, CELLS, CYCLES, GATE_PLAN, PLANS, PROTOCOL,
                        PREDICTION_PATH, PREDICTION_SHA256, RESULT_STATUS, RESERVE_MS,
                        SELECTION_PATH, SELECTION_SHA256, SELECTION_FINGERPRINT,
                        RUN, SEGMENT_IDS,
                        budget, manifest, manifests, protocol)
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
    ap.add_argument('--approved-m3-b10-credible-selector-validation-v1', action='store_true')
    ap.add_argument('--verification-mode', choices=['performance', 'correctness'],
                    default='performance')
    for k in ('config', 'out', 'reference', 'source-preflight'):
        ap.add_argument('--' + k, type=Path)
    args = ap.parse_args()
    if args.config and json.loads(args.config.read_text()) != protocol():
        raise ValueError('frozen M3 Expert-reserve validation configuration changed')
    _, _, audit = preparation_audit()
    if args.dry_run:
        print(json.dumps(dict(protocol=protocol(), preparation_reuse=audit), indent=2))
        return
    if (not args.approved_m3_b10_credible_selector_validation_v1
            or os.environ.get('COOVERLAP_APPROVED_BATCH') != PROTOCOL):
        ap.error('NEW M3 Expert-reserve validation approval required before GPU imports; '
                 'previous M3/M2 authorizations are invalid')
    if None in (args.config, args.out, args.reference, args.source_preflight):
        ap.error('all paths required')
    if os.geteuid() == 0:
        raise PermissionError('model must be ordinary nvidia')
    # Verify this B9 package and its own CPU preflight credential.
    from m3_b10_control import sha, verify_credential
    credential = verify_credential(args.config.parent, args.source_preflight.parent,
                                   sha(args.source_preflight))
    for k, v in os.environ.items():
        if v and (k.startswith(('NSYS_', 'KINETO_', 'TORCH_PROFILER_', 'CUPTI_INJECTION',
                                'CUDA_INJECTION')) or k == 'LD_PRELOAD'):
            raise RuntimeError('unexpected injection ' + k)
    args.out.mkdir(exist_ok=False)
    # The pre-run selection record is frozen outside the deployment package.  It
    # is read-only here: the window neither evaluates it nor lets the outcome
    # change it, the costs, or the reserve value.
    selection_path = args.config.parent.parent / SELECTION_PATH
    if sha(selection_path) != SELECTION_SHA256:
        raise ValueError('frozen selection file changed')
    frozen = json.loads(selection_path.read_text())
    if frozen.get('fingerprint') != SELECTION_FINGERPRINT:
        raise ValueError('frozen selection fingerprint changed')
    if frozen.get('reserve_ms') != RESERVE_MS or frozen.get('protocol') != PROTOCOL:
        raise ValueError('frozen selection does not belong to this batch/rule')
    by_period = frozen['by_period_ns']
    report = dict(status='INCOMPLETE', protocol=protocol(),
                  selection_freeze=dict(path=SELECTION_PATH, sha256=SELECTION_SHA256,
                                        fingerprint=SELECTION_FINGERPRINT,
                                        rule=frozen['rule_id'], reserve_ms=RESERVE_MS,
                                        by_period_ns=by_period,
                                        policy='recorded before each segment; the executed '
                                               'plan comes from the fixed matrix'),
                  prediction_identity=dict(path=PREDICTION_PATH, sha256=PREDICTION_SHA256),
                  segments=[dict(index=i, candidate=c['cell'], cell=c['cell'],
                                 pass_=c['pass_'], policy=c['policy'], plan=c['plan'],
                                 period_ns=c['period_ns'], segment_id=SEGMENT_IDS[i],
                                 status='NOT_STARTED', planned_Experts=CYCLES,
                                 planned_Context=CYCLES//2,
                                 selection=by_period[str(c['period_ns'])],
                                 selection_fingerprint=SELECTION_FINGERPRINT,
                                 reserve_ms=RESERVE_MS)
                            for i, c in enumerate(RUN)],
                  gates={name: dict(status='INCOMPLETE', segment_id=gate_id)
                         for name, gate_id in ((OLD_READER_GATE, 'gate_old_reader'),
                                               (INTERRUPT_GATE, 'gate_interrupt'))},
                  checks=[], source_config_fingerprints={k: v['sha256']
                                                         for k, v in credential['package'].items()},
                  config_sha256=sha(args.config),
                  source_preflight_sha256=sha(args.source_preflight),
                  preparation_reuse=audit, observation_mode=args.verification_mode,
                  interpretation='Expert-reserve selection validation on a fixed split x budget '
                                 'matrix; the frozen recommendation is recorded but never changes the '
                                 'plan. No reliable-tail, k_min, violation-rate, final-route or '
                                 'net-benefit claim')
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
        # Canonical expectations are fresh objects from the batch plan: run_segment
        # refuses a segment manifest that differs from its declared trajectory.
        canonical_confs = [manifest(c['period_ns']) for c in RUN]
        report['budget_manifests'] = {str(ns): conf for ns, conf in manifests().items()}
        report['prediction'] = protocol()['prediction']
        summary = run_candidates(device, snaps, RUN, PLANS,
                                 args.verification_mode, args.out, time.monotonic_ns, require,
                                 math_for, list(SEGMENT_IDS), None, report['segments'],
                                 augment, write_tables, active=active, confs=seg_confs,
                                 expects=canonical_confs)
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
        require(sorted({row['period_ns'] for row in summary}) == sorted(BUDGETS),
                'both_declared_budgets_executed')
        require(sorted({row['plan'] for row in summary}) == sorted(PLANS),
                'both_declared_plans_executed')
        require(all(record['protocol'] == PROTOCOL for record in report['segments']),
                'segment_records_carry_this_batch_protocol')
        require(sorted({row['cell'] for row in summary}) == sorted(c['id'] for c in CELLS),
                'all_four_cells_completed')
        require([row['cell'][0] for row in summary] == ['A','B','C','D','D','C','B','A'],
                'split_budget_declared_order')
        # The pre-segment selection survives each segment unchanged and is
        # identical for the two segments of one budget.
        for record, cell_ in zip(report['segments'], RUN):
            require(record.get('selection') == by_period[str(cell_['period_ns'])],
                    'pre_segment_selection_recorded_'+cell_['cell'][0])
            require(record.get('selection_fingerprint') == SELECTION_FINGERPRINT,
                    'pre_segment_selection_identity_'+cell_['cell'][0])
        require(all(record.get('selection') == by_period[str(record['period_ns'])]
                    for record in report['segments']),
                'selection_bound_to_declared_budget')
        require([row['period_ns'] for row in summary] == [c['period_ns'] for c in RUN],
                'segment_budget_drives_manifest')
        require([row['plan'] for row in summary] == [c['plan'] for c in RUN],
                'segment_plan_drives_block_plan')
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
        report['periods_ns'] = [c['period_ns'] for c in RUN]
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
