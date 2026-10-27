"""PREPARED ONLY: one newly approved M3 three-block correctness/coverage process.

Not authorized by, and does not reuse, any previous M3/M2 one-shot approval.
No graph, concurrency, partition, interference or dependency change. The frozen
math bodies in ``m2_pi05_ops`` are called unchanged; only the legal cut between
them, the published-state semantics and the retained state differ by plan.
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
from m2_executor import VersionedKV
from m2_clean_core import retention_layout, gate_retention_layout
from m2_clean_stats import augment, write_tables
from m3_b2_core import run_segment
from m3_b3_plan import (CANDIDATES, CONTROL, CYCLES, PLANS, PROTOCOL, THREE,
                        budget, manifest, protocol)
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
    ap.add_argument('--approved-m3-b3-three-block-v1', action='store_true')
    ap.add_argument('--verification-mode', choices=['performance', 'correctness'],
                    default='performance')
    for k in ('config', 'out', 'reference', 'source-preflight'):
        ap.add_argument('--' + k, type=Path)
    args = ap.parse_args()
    if args.config and json.loads(args.config.read_text()) != protocol():
        raise ValueError('frozen M3 three-block configuration changed')
    _, _, audit = preparation_audit()
    if args.dry_run:
        print(json.dumps(dict(protocol=protocol(), preparation_reuse=audit), indent=2))
        return
    if (not args.approved_m3_b3_three_block_v1
            or os.environ.get('COOVERLAP_APPROVED_BATCH') != PROTOCOL):
        ap.error('NEW M3 three-block approval required before GPU imports; '
                 'previous M3/M2 authorizations are invalid')
    if None in (args.config, args.out, args.reference, args.source_preflight):
        ap.error('all paths required')
    if os.geteuid() == 0:
        raise PermissionError('model must be ordinary nvidia')
    from m3_b3_control import sha, verify_credential
    credential = verify_credential(args.config.parent, args.source_preflight.parent,
                                   sha(args.source_preflight))
    for k, v in os.environ.items():
        if v and (k.startswith(('NSYS_', 'KINETO_', 'TORCH_PROFILER_', 'CUPTI_INJECTION',
                                'CUDA_INJECTION')) or k == 'LD_PRELOAD'):
            raise RuntimeError('unexpected injection ' + k)
    args.out.mkdir(exist_ok=False)
    report = dict(status='INCOMPLETE', protocol=protocol(),
                  segments=[dict(index=i, candidate=c['id'], plan=c['plan'],
                                 mode='b2_boundary', status='NOT_STARTED',
                                 planned_Experts=CYCLES, planned_Context=CYCLES//2)
                            for i, c in enumerate(CANDIDATES)],
                  checks=[], source_config_fingerprints={k: v['sha256']
                                                         for k, v in credential['package'].items()},
                  config_sha256=sha(args.config),
                  source_preflight_sha256=sha(args.source_preflight),
                  preparation_reuse=audit, observation_mode=args.verification_mode,
                  interpretation='three-block correctness/coverage diagnostic with symmetric '
                                 'retention and D2D; no tail, k_min, final-split or net-benefit claim')
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
    device = backend = None
    try:
        e = prepare(args, report, save, require, bound)
        torch, np, owner, ps, ledger = e['torch'], e['np'], e['owner'], e['ps'], e['ledger']
        p0, p1 = ps
        refs, midrefs, snaps = e['refs'], e['midrefs'], e['snaps']
        context, block1, block2 = e['context'], e['block1'], e['block2']
        stage, snap, read = e['stage'], e['snap'], e['read']
        address_manifest, stream, noise_sha = e['address_manifest'], e['stream'], e['noise_sha']
        from m2_pi05_ops import prefix_block, encoder_block
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

        def prefix_reference(slot):
            """Same-process prefix state taken from the validated two-block path.

            The hook only reads encoder_x at layer-0 entry, i.e. exactly after
            language+Vision+norm/project/bias; it adds no math and no cut.
            """
            p = ps[slot]
            stage(p, True)
            seen = []
            original_enc = p._encoder_layer

            def observe(i, seq, fuse_b1, stream, orig=original_enc):
                if i == 0 and not seen:
                    seen.append(snap(p, 'prefix_ref_slot'+str(slot), 0)[0])
                return orig(i, seq, fuse_b1, stream)
            p._encoder_layer = observe
            try:
                ledger.execute('prefix_ref_slot'+str(slot), slot, 'B1',
                               lambda: block1(p, e['ENC_D'], e['VIS_D']))
            finally:
                p._encoder_layer = original_enc
            require(len(seen) == 1, 'prefix_snapshot_once')
            require(snap(p, 'prefix_ref_mid_slot'+str(slot), 9) == midrefs[slot],
                    'prefix_reference_path_matches_validated_mid')
            return seen[0]

        for slot in (0, 1):
            expected['pre'+str(slot)] = prefix_reference(slot)
            report.setdefault('prefix_reference', []).append(
                dict(slot=slot, nbytes=len(expected['pre'+str(slot)]),
                     sha256=hashlib.sha256(expected['pre'+str(slot)]).hexdigest(),
                     source='validated two-block B1 at layer-0 entry; same process/slot'))
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
            ledger.execute(device.namespace+str(device.epoch)+'/bootstrap', 0, 'Context',
                           lambda: context(p0))
            ev = torch.cuda.Event(enable_timing=True)
            ev.record(stream)
            ev.synchronize()
            for b in range(len(m.plan)):
                m.submit_block(h, b, snapshots[0], m.plan.blocks[b], ev)
                require(m.poll_block(h), 'bootstrap_complete')
            require(m.get(h).valid_layers == 18, 'bootstrap_publishes_all_18_layers')
            require(snap(p0, device.namespace+str(device.epoch)+'_bootstrap') == refs[0][0],
                    'bootstrap_matches_same_process_S0')
            m.publish(h)

        def ready(phase, d, logical):
            require(address_manifest(owner, p0, p1, e['attn1'], e['runner1']) == original,
                    'visible_resources_stable')
            require(torch.cuda.mem_get_info()[0] > 12*1024**3, 'memory_floor')
            for i, p in enumerate(ps):
                require(snap(p, 'initial_'+d.namespace+str(d.epoch)+'_S'+str(i)) == refs[i][0],
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
        intervals = original['writable']+original['shared_readonly']
        require(not any(x['ptr'] and x['nbytes'] and max(device.gptr, x['ptr']) <
                        min(device.gptr+bank_bytes, x['ptr']+x['nbytes']) for x in intervals),
                'bank_no_model_alias')
        require(device.images.is_contiguous() and device.noise.is_contiguous(),
                'contiguous_fixed_inputs')

        # Version-lifecycle gates run on the NEW three-block plan so that
        # "prefix complete with 0 new KV layers cannot publish" is exercised by
        # the real ownership state machine, not only by CPU tests.
        for interleave in (False, True):
            device.use_plan(THREE, math_for(THREE))
            device.namespace = 'interrupt_gate' if interleave else 'gate'
            gate = dict(status='INCOMPLETE',
                        plan=THREE.id,
                        role='manual interleaving correctness only; not an arrival-policy sample'
                             if interleave else 'old-reader gate')
            report[device.namespace] = gate
            backend = BoundaryBackend(device, snaps, 'correctness',
                                      layout=gate_retention_layout(CYCLES, THREE), plan=THREE)
            m = VersionedKV(THREE)
            backend.prepare(m, None, gate)
            backend.bootstrap(m, 'bootstrap')
            backend.ready(m)
            m.bind('E0', noise_sha)
            old = m.current
            new = m.begin(1, snaps[1])
            if interleave:
                m.bind('hold', noise_sha)
            backend.enter_window()
            try:
                backend.stage(m, new, 'R0')
                backend.block(m, new, 0, 'R0/B1')
                require(m.get(new).valid_layers == 0, 'prefix_state_reports_zero_effective_kv')
                try:
                    m.publish(new)
                except RuntimeError:
                    require(True, 'prefix_only_cannot_publish')
                else:
                    raise AssertionError('prefix-only block published')
                backend.block(m, new, 1, 'R0/B2')
                require(m.get(new).valid_layers == 9, 'nine_layers_after_encoder_0_8')
                if interleave:
                    backend.expert(m, 'E0', old)
                backend.block(m, new, 2, 'R0/B3')
                require(m.get(new).valid_layers == 18, 'eighteen_layers_after_encoder_9_17')
                m.publish(new)
                require(m.bind('latest', noise_sha) == new, 'latest_published_binding')
                m.cancel_unsubmitted('latest')
                try:
                    m.reclaim(old)
                except RuntimeError:
                    require(True, 'old_reader_prevents_reuse')
                else:
                    raise AssertionError('old slot reclaimed with reader')
                if interleave:
                    m.cancel_unsubmitted('hold')
                else:
                    backend.expert(m, 'E0', old)
                m.reclaim(old)
                backend.drain()
            finally:
                backend.leave_window()
                gate['journal'] = m.journal
            backend.validate_and_persist()
            require(len(m.journal) == (20+3 if interleave else 18+3), 'gate_exact_journal')
            save()

        for index, cand in enumerate(CANDIDATES):
            bound()
            plan = PLANS[cand['plan']]
            device.use_plan(plan, math_for(plan))
            device.namespace = 'segment'
            backend = BoundaryBackend(device, snaps, args.verification_mode,
                                      layout=retention_layout(CYCLES, plan), plan=plan)
            record = report['segments'][index]
            m = VersionedKV(plan)
            try:
                run_segment(m, snaps, 'b2_boundary', backend, record, time.monotonic_ns,
                            conf=manifest(), expect=manifest())
            finally:
                if record.get('t0_ns') is not None:
                    record['metrics'] = augment(record)
            backend.validate_and_persist()
            require(address_manifest(owner, p0, p1, e['attn1'], e['runner1']) == original,
                    'resources_stable_after_segment')
            write_tables(record, args.out/('segment'+str(index)))
            require(len(record['units']) == CYCLES, 'two_declared_obligation_units_per_refresh')
            save()

        from collections import Counter
        counts = dict(Counter(x[2] for x in ledger.calls))
        report['observed_call_counts'] = counts
        work = protocol()['work']
        require(counts == dict(encoder=work['encoder_layers'], decoder=work['decoder_layers'],
                               language=work['language'], vision27=work['language']),
                'complete_observed_work')
        require(len(ledger.calls) == work['observed_ledger_rows'], 'observed_ledger_rows')
        require(owner._cudart.cudaGetLastError() == 0, 'cuda_last_error')
        report['call_ledger'] = ledger.calls
        report['cross_process_gate'] = dict(
            admission=False,
            within_historical_envelope=all(x['pass_'] for x in report['cross_process']))
        report['status'] = 'PASS_IN_PROCESS_THREE_BLOCK_COVERAGE'
        report['elapsed_s'] = time.monotonic()-start
        save()
    except BaseException:
        report['status'] = 'FAIL_OR_INCOMPLETE'
        report['error'] = traceback.format_exc()
        if backend is not None:
            backend.leave_window()
            report['unfinished_retention'] = backend.bank.metadata()
            report['partial_retention_status'] = 'UNAVAILABLE_UNSAFE_OR_NO_TIME'
            try:
                if device is not None and device.leased and time.monotonic_ns()+5_000_000_000 < deadline and device.stream.query():
                    device.download(0, backend.layout['nbytes'])
                    with (args.out/'PARTIAL_UNVERIFIED_RETENTION.bin').open('xb') as f:
                        f.write(device.host_view[:backend.layout['nbytes']])
                        f.flush()
                        os.fsync(f.fileno())
                    report['partial_retention_status'] = 'EXPORTED_UNVERIFIED_NOT_REUSABLE'
            except BaseException:
                report['partial_retention_error'] = traceback.format_exc()
        if 'ledger' in locals():
            report['call_ledger'] = ledger.calls
        report['elapsed_s'] = time.monotonic()-start
        save()
        raise


if __name__ == '__main__':
    main()
