"""Exact entry orchestration for the three-block batch, CPU-testable.

`pi05_m3_b3_prepare.py` calls these functions unchanged; the CPU regressions call
the same functions with symbolic devices, so the shipped sequence -- not a copy of
it -- is what gets tested. No Torch/CUDA import happens here.
"""
import hashlib
import os
import traceback
from pathlib import Path

from m2_clean_core import retention_layout
from m2_executor import VersionedKV
from m3_b2_backend import BoundaryBackend
from m3_b2_core import finalize_segment_stats, run_segment
from m3_b3_plan import CYCLES

OLD_READER_GATE = 'gate_old_reader'
INTERRUPT_GATE = 'gate_interrupt'


def journal_signature(journal):
    """Hashable, comparable view of the ownership journal."""
    return [tuple(row) for row in journal]


def expected_gate_signature(plan, interleave):
    """The exact ownership journal a gate must produce, from the plan alone.

    Counts the real transitions: bootstrap (begin + one submit/done per declared
    block + publish), reader binding, the new build, the refused prefix-only
    publish (which must add no entry), publication, latest binding, the reader
    protection refusal (also no entry) and reclamation.
    """
    if len(plan) != 3:
        raise ValueError('gate signatures are fixed for the declared three-block plan')
    signature = [('begin', 0, 0, 1, 'S0')]
    for b in range(len(plan)):
        signature.append(('block_submit', 0, b, plan.valid_layers[b]))
        signature.append(('block_done', 0, b, plan.valid_layers[b],
                          'READY' if b == len(plan)-1 else 'BUILDING'))
    signature += [('publish', 0), ('bind', 'E0', 0, 'S0'), ('begin', 1, 1, 1, 'S1')]
    if interleave:
        signature.append(('bind', 'hold', 0, 'S0'))
    signature.append(('block_submit', 1, 0, plan.valid_layers[0]))
    signature.append(('block_done', 1, 0, plan.valid_layers[0], 'BUILDING'))
    signature.append(('block_submit', 1, 1, plan.valid_layers[1]))
    signature.append(('block_done', 1, 1, plan.valid_layers[1], 'BUILDING'))
    if interleave:
        # The manual interleave inserts the old-slot Expert before the last block.
        signature += [('expert_submit', 'E0', 0, 180), ('expert_done', 'E0', 0)]
    signature.append(('block_submit', 1, 2, plan.valid_layers[2]))
    signature.append(('block_done', 1, 2, plan.valid_layers[2], 'READY'))
    signature += [('publish', 1), ('bind', 'latest', 1, 'S1'),
                  ('cancel_unsubmitted', 'latest')]
    if interleave:
        signature += [('cancel_unsubmitted', 'hold'), ('reclaim', 0, 0, 1)]
    else:
        signature += [('expert_submit', 'E0', 0, 180), ('expert_done', 'E0', 0),
                      ('reclaim', 0, 0, 1)]
    return signature


def run_gate(backend, manager, snaps, noise_sha, plan, interleave, require, record=None):
    """Old-reader gate or manual-interleave gate on one declared plan.

    The shipped ownership state machine performs the work; this function asserts
    the real transition content and order, not just a journal length.
    """
    require(len(plan) == 3, 'gate_runs_on_three_block_plan')
    backend.prepare(manager, None, record if record is not None else {})
    backend.bootstrap(manager, 'bootstrap')
    backend.ready(manager)
    manager.bind('E0', noise_sha)
    old = manager.current
    new = manager.begin(1, snaps[1])
    if interleave:
        manager.bind('hold', noise_sha)
    backend.enter_window()
    try:
        backend.stage(manager, new, 'R0')
        backend.block(manager, new, 0, 'R0/B1')
        require(manager.get(new).valid_layers == 0, 'prefix_state_reports_zero_effective_kv')
        require(manager.get(new).phase == 'BUILDING', 'prefix_state_not_ready')
        try:
            manager.publish(new)
        except RuntimeError:
            require(True, 'prefix_only_cannot_publish')
        else:
            raise AssertionError('prefix-only block published')
        backend.block(manager, new, 1, 'R0/B2')
        require(manager.get(new).valid_layers == plan.valid_layers[1],
                'layers_after_encoder_0_8')
        if interleave:
            backend.expert(manager, 'E0', old)
        backend.block(manager, new, 2, 'R0/B3')
        require(manager.get(new).valid_layers == plan.valid_layers[2],
                'layers_after_encoder_9_17')
        manager.publish(new)
        require(manager.get(new).phase == 'PUBLISHED', 'full_context_published')
        require(manager.bind('latest', noise_sha) == new, 'latest_published_binding')
        manager.cancel_unsubmitted('latest')
        try:
            manager.reclaim(old)
        except RuntimeError:
            require(True, 'old_reader_prevents_reuse')
        else:
            raise AssertionError('old slot reclaimed with reader')
        if interleave:
            manager.cancel_unsubmitted('hold')
        else:
            backend.expert(manager, 'E0', old)
        manager.reclaim(old)
        backend.drain()
    finally:
        backend.leave_window()
    signature = journal_signature(manager.journal)
    expected = expected_gate_signature(plan, interleave)
    expected_entries = len(expected)
    require(len(manager.journal) == expected_entries, 'gate_journal_length_%d' % expected_entries)
    require(signature == expected, 'gate_journal_content_and_order')
    return dict(interleave=bool(interleave), journal=list(manager.journal),
                expected=expected, entries=len(manager.journal),
                valid_layers=dict(prefix=0, after_encoder_0_8=plan.valid_layers[1],
                                  after_encoder_9_17=plan.valid_layers[2]))


def run_prefix_reference(p, slot, stage, snap, ledger, block1, block2, enc_d, vis_d,
                         require, refs, midrefs):
    """Complete two-block validated Control used as the prefix/mid/full reference.

    Reads encoder_x only at layer-0 entry (exactly after the prefix), completes
    the remaining encoder layers, and requires the full Context to match the
    same-process reference byte for byte. It is one complete Context of real
    model work in the batch ledger.
    """
    stage(p, True)
    seen = []
    original = p._encoder_layer

    def observe(i, seq, fuse_b1, stream, orig=original):
        if i == 0 and not seen:
            seen.append(snap(p, 'prefix_ref_slot'+str(slot), 0)[0])
        return orig(i, seq, fuse_b1, stream)
    p._encoder_layer = observe
    try:
        ledger.execute('prefix_ref_slot'+str(slot)+'/B1', slot, 'B1',
                       lambda: block1(p, enc_d, vis_d))
    finally:
        p._encoder_layer = original
    require(len(seen) == 1, 'prefix_snapshot_once')
    require(snap(p, 'prefix_ref_mid_slot'+str(slot), 9) == midrefs[slot],
            'prefix_reference_path_matches_validated_mid')
    ledger.execute('prefix_ref_slot'+str(slot)+'/B2', slot, 'B2', lambda: block2(p))
    require(snap(p, 'prefix_ref_full_slot'+str(slot), 18) == refs[slot][0],
            'prefix_reference_full_context_byte_exact')
    return seen[0]


def mark_active(active, kind, segment_id, plan_id, backend, manager, record):
    """Record the phase that is about to execute, so failures are attributed to it."""
    active.clear()
    active.update(kind=kind, segment_id=segment_id, plan=plan_id, backend=backend,
                  manager=manager, record=record, layout=backend.layout,
                  capacity=backend.bank.capacity)
    return active


def describe_active(active):
    """Serializable attribution of the active phase; never includes live objects."""
    if not active:
        return dict(kind=None, reason='no_active_phase')
    return {k: v for k, v in active.items() if k not in ('backend', 'manager', 'record')}



def window_resource_safety(window_result):
    """Reliable-release receipt for a b6 fixed/quiet window.

    A finite failure such as zero copies/coverage is allowed to continue to
    full validation only when the owned process is confirmed exited and all
    owned resources are released.  A finish exception is not itself unsafe when
    that receipt is still reliable; it is unsafe when the receipt is missing or
    false.
    """
    if not isinstance(window_result, dict):
        return dict(safe=False, status='UNCONFIRMED', mode=None,
                    process_exit_confirmed=None, resources_released=None,
                    finish_error=None, reasons=['window_result_missing'])
    release = window_result.get('resource_release') or {}
    raw_mode = window_result.get('worker_mode') or window_result.get('mode')
    mode = ('fixed' if raw_mode in ('fixed', 'fixed_cpu_mem')
            else 'quiet' if raw_mode == 'quiet' else raw_mode)
    process = release.get('process_exit_confirmed')
    resources = release.get('resources_released')
    finish_error = window_result.get('finish_error')
    reasons = []
    if mode not in ('quiet', 'fixed'):
        reasons.append('worker_mode_unknown')
    if resources is not True:
        reasons.append('resources_released_false')
    if mode == 'fixed' and process is not True:
        reasons.append('process_exit_not_confirmed')
    if mode == 'quiet' and process is not None:
        reasons.append('quiet_process_unexpected')
    reliable = bool(
        mode in ('quiet', 'fixed') and resources is True
        and (mode == 'quiet' or process is True))
    if finish_error is not None:
        reasons.append('finish_exception')
    return dict(safe=reliable,
                status='RELEASED' if reliable else 'UNCONFIRMED',
                mode=mode, process_exit_confirmed=process,
                resources_released=resources, finish_error=finish_error,
                reasons=reasons, reliable_release=reliable)



def export_failed_retention(device, active, out_dir, deadline_ns, now_ns):
    """Export the ACTIVE segment's bank only when safe; never marks it PASS.

    The caller always gets a machine-readable status naming the segment, plan,
    layout size and byte range that belong to the phase that actually failed.
    """
    backend = (active or {}).get('backend')
    if backend is None:
        return dict(status='NOT_EXPORTED_no_active_segment', segment_id=None, plan=None,
                    layout_nbytes=None, claims=None)
    layout = backend.layout
    try:
        bank = backend.bank.status()
    except BaseException:
        bank = dict(status='UNAVAILABLE', error=traceback.format_exc())
    base = dict(segment_id=(active or {}).get('segment_id'), plan=(active or {}).get('plan'),
                kind=(active or {}).get('kind'), layout_nbytes=layout['nbytes'],
                capacity=getattr(backend.bank, 'capacity', None), bank=bank)
    active = active or {}
    if active.get('window_expected'):
        base.update(window_condition_valid=active.get('window_condition_valid'),
                    resource_safety=active.get('resource_safety'),
                    resource_status=active.get('resource_status'),
                    validation_attempted=active.get('validation_attempted'),
                    validation_persisted=active.get('validation_persisted'),
                    export_allowed=active.get('export_allowed'))
        if active.get('validation_persisted'):
            return dict(base, status='NOT_EXPORTED_already_validated_and_persisted',
                        reason='segment retention was already verified and persisted')
        if active.get('unsafe_resources') or active.get('export_allowed') is not True:
            detail = active.get('resource_safety') or {}
            return dict(base, status='NOT_EXPORTED_no_reliable_worker_release',
                        reason='; '.join(detail.get('reasons') or
                                        ['worker resources were not confirmed released']))
    reasons = []
    if device is None or not getattr(device, 'leased', False):
        reasons.append('no_active_bank')
    if now_ns() + 5_000_000_000 >= deadline_ns:
        reasons.append('outside_deadline')
    if device is not None:
        try:
            if not device.stream.query():
                reasons.append('cuda_not_idle')
        except BaseException:
            reasons.append('cuda_query_failed')
    if reasons:
        return dict(base, status='NOT_EXPORTED_'+'+'.join(reasons))
    try:
        device.download(0, layout['nbytes'])
        with (Path(out_dir)/'PARTIAL_UNVERIFIED_RETENTION.bin').open('xb') as f:
            f.write(device.host_view[:layout['nbytes']])
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        return dict(base, status='EXPORT_FAILED', error=traceback.format_exc())
    return dict(base, status='EXPORTED_UNVERIFIED_NOT_REUSABLE', offset=0,
                nbytes=layout['nbytes'],
                sha256=hashlib.sha256(device.host_view[:layout['nbytes']]).hexdigest())


def run_candidates(device, snaps, candidates, plans, mode, out, clock, require,
                   math_for_plan, segment_ids, conf, records, augment, write_tables,
                   expected_units=None, active=None, confs=None, window_factory=None):
    """Run every candidate consecutively on one physical bank and persist each.

    The bank is only reused after `validate_and_persist` succeeded; the unique
    segment id threads through the device ledger keys, the retention index and
    the per-segment output directory.
    """
    if len(candidates) != len(segment_ids) or len(set(segment_ids)) != len(segment_ids):
        raise ValueError('one unique segment id per candidate is required')
    if confs is not None and len(confs) != len(candidates):
        raise ValueError('one manifest per candidate is required when confs is given')
    if expected_units is not None and confs is not None:
        raise ValueError('per-segment manifests fix their own obligation count')
    summary = []
    for index, candidate in enumerate(candidates):
        seg_conf = conf if confs is None else confs[index]
        cycles = seg_conf.get('cycles')
        if not isinstance(cycles, int) or cycles < 2 or cycles % 2:
            raise ValueError('manifest cycles must be a positive even count')
        seg_units = cycles if expected_units is None else expected_units
        plan = plans[candidate['plan']]
        policy = candidate['policy']
        if policy not in ('serial_context', 'b2_boundary'):
            raise ValueError('unreviewed candidate policy: %r' % (policy,))
        device.use_plan(plan, math_for_plan(plan))
        device.set_segment_id(segment_ids[index])
        backend = BoundaryBackend(device, snaps, mode,
                                  layout=retention_layout(cycles, plan), plan=plan)
        manager = VersionedKV(plan)
        record = records[index]
        if active is not None:
            mark_active(active, 'segment', segment_ids[index], plan.id, backend, manager, record)
            active.update(index=index, candidate=candidate['id'], policy=policy,
                          period_ns=seg_conf['period_ns'])
        window = None
        replay_error = None
        if window_factory is not None:
            try:
                window = window_factory(index, candidate, seg_conf, record)
            except BaseException as exc:
                replay_error = exc
        if window is not None and active is not None:
            active.update(window_expected=True, export_allowed=False,
                          unsafe_resources=True, resource_safety=None,
                          resource_status='UNCONFIRMED',
                          validation_attempted=False, validation_persisted=False)

        def row_for(result):
            row = dict(segment_id=segment_ids[index], candidate=candidate['id'],
                       cell=candidate.get('cell', candidate['id']),
                       pass_=candidate.get('pass_'), policy=policy, plan=plan.id,
                       blocks=len(plan), cycles=cycles, period_ns=seg_conf['period_ns'],
                       protocol=record.get('protocol'),
                       retained=None if result is None else result.get('records'),
                       experts=len(record.get('experts', {})),
                       published=len(record.get('published', {})),
                       units=len(record.get('units', {})))
            if window is not None:
                row.update(condition_valid=bool(record.get('condition_valid')),
                           interference=(record.get('interference') or {}).get('mode'),
                           window_t0_ns=record.get('window_t0_ns'),
                           replay_end_ns=record.get('replay_end_ns'),
                           comparison_status=record.get('comparison_status'),
                           validation_status=record.get('validation_status'),
                           numeric_pass=record.get('numeric_pass'),
                           resource_status=record.get('resource_status'),
                           overall_status=record.get('overall_status'))
            return row

        try:
            if replay_error is None:
                run_segment(manager, snaps, policy, backend, record, clock,
                            conf=seg_conf, expect=seg_conf, window=window)
        except BaseException as exc:
            replay_error = exc
        finally:
            window_result = None
            if window is not None:
                try:
                    window_result = window.finish(
                        replay_end_ns=(record.get('replay_end_ns')
                                       or record.get('window_end_ns') or clock()),
                        replay_status=record.get('status'),
                        replay_error=(None if replay_error is None
                                      else repr(replay_error)))
                except BaseException as exc:
                    window_result = dict(
                        condition_valid=False, finish_error=repr(exc),
                        worker_evidence=None, errors=[repr(exc)])
                    try:
                        window.abort('window_finish_error')
                    except BaseException:
                        window_result['abort_error'] = True
                pending = record.pop('_stats_pending', None)
                if pending is not None:
                    finalize_segment_stats(record, pending['conf'], pending['t0'],
                                            pending['plan'], clock)
                annotate = getattr(window, 'annotate_record', None)
                if callable(annotate):
                    try:
                        annotate(record)
                    except BaseException as exc:
                        window_result.setdefault('errors', []).append(
                            'coverage_annotation: ' + repr(exc))
                        window_result['condition_valid'] = False
                safety = window_resource_safety(window_result)
                record['interference'] = window_result
                record['condition_valid'] = bool(window_result.get('condition_valid'))
                record['interference_status'] = ('PASS' if record['condition_valid']
                                                 else 'FAILED')
                record['resource_safety'] = safety
                record['resource_status'] = safety['status']
                record['comparison_valid'] = record['condition_valid']
                if record['condition_valid']:
                    record['comparison_status'] = 'VALID_INTERFERENCE'
                elif not safety['safe']:
                    record['comparison_status'] = 'INVALID_RESOURCE_UNCONFIRMED'
                else:
                    record['comparison_status'] = 'INVALID_INTERFERENCE_CONDITION'
                record['interference_errors'] = list(window_result.get('errors') or [])
                record['validation_status'] = 'NOT_RUN'
                record['overall_status'] = 'INCOMPLETE'
                if active is not None:
                    active.update(window_expected=True, resource_safety=safety,
                                  resource_status=record['resource_status'],
                                  window_condition_valid=record['condition_valid'],
                                  window_finish_error=window_result.get('finish_error'),
                                  unsafe_resources=not safety['safe'],
                                  export_allowed=bool(safety['safe']),
                                  validation_attempted=False,
                                  validation_persisted=False)
            if record.get('t0_ns') is not None and 'statistics' in record:
                record['metrics'] = augment(record)

        safety = record.get('resource_safety') or {}
        if window is not None and not safety.get('safe'):
            record['validation'] = dict(
                pass_=None, persisted=False, status='NOT_RUN',
                reason='unsafe worker resources; normal validation/D2H/write/bank reuse blocked')
            record['validation_status'] = 'NOT_RUN_UNSAFE_RESOURCES'
            record['condition_valid'] = False
            record['comparison_valid'] = False
            record['interference_status'] = 'FAILED'
            record['comparison_status'] = 'INVALID_RESOURCE_UNCONFIRMED'
            record['status'] = 'FAILED_UNSAFE_WORKER_RESOURCES'
            record['overall_status'] = 'FAILED_UNSAFE_WORKER_RESOURCES'
            record['retention_status'] = 'UNVERIFIED_NOT_REUSABLE'
            if active is not None:
                try:
                    bank_state = backend.bank.status()
                except BaseException:
                    bank_state = dict(status='UNAVAILABLE')
                active.update(validation_attempted=False, validation_persisted=False,
                              validation_pass=None, export_allowed=False,
                              overall_status=record['overall_status'],
                              bank_state=bank_state)
            if replay_error is not None:
                raise replay_error
            row = row_for(None)
            summary.append(row)
            row['stop_after'] = 'unsafe_worker_resources'
            break

        if replay_error is not None:
            if window is not None:
                record['status'] = 'FAILED_REPLAY'
                record['overall_status'] = 'FAILED_REPLAY'
                if active is not None:
                    active.update(validation_attempted=False, validation_persisted=False,
                                  export_allowed=bool(safety.get('safe')),
                                  overall_status=record['overall_status'])
            raise replay_error

        if window is None:
            result = backend.validate_and_persist()
        else:
            try:
                result = backend.validate_and_persist()
            except BaseException as exc:
                record['validation'] = dict(pass_=False, persisted=False,
                                             status='FAILED', error=repr(exc))
                record['validation_status'] = 'FAILED_VALIDATION'
                record['validation_error'] = repr(exc)
                record['status'] = 'FAILED_VALIDATION'
                record['overall_status'] = 'FAILED_VALIDATION'
                record['retention_status'] = 'UNVERIFIED_NOT_REUSABLE'
                if active is not None:
                    try:
                        bank_state = backend.bank.status()
                    except BaseException:
                        bank_state = dict(status='UNAVAILABLE')
                    active.update(validation_attempted=True,
                                  validation_persisted=False, validation_pass=False,
                                  export_allowed=bool(safety.get('safe')),
                                  overall_status=record['overall_status'],
                                  bank_state=bank_state)
                raise
            else:
                record['validation_status'] = 'PASS' if result.get('pass_') else 'FAILED'
                record['numeric_pass'] = bool(result.get('pass_'))
                record['retention_status'] = ('VERIFIED_PERSISTED_RELEASED'
                                               if result.get('persisted')
                                               else 'UNVERIFIED_NOT_REUSABLE')
                if active is not None:
                    try:
                        bank_state = backend.bank.status()
                    except BaseException:
                        bank_state = dict(status='UNAVAILABLE')
                    active.update(validation_attempted=True,
                                  validation_persisted=bool(result.get('persisted')),
                                  validation_pass=bool(result.get('pass_')),
                                  export_allowed=False,
                                  bank_state=bank_state,
                                  bank_reusable=bool(getattr(backend.bank, 'reusable', False)))
            if record['condition_valid']:
                record['status'] = 'PASS'
                record['overall_status'] = 'PASS'
            else:
                record['status'] = 'FAILED_INTERFERENCE_CONDITION'
                record['overall_status'] = 'FAILED_INTERFERENCE_CONDITION'
            if active is not None:
                active.update(overall_status=record['overall_status'])

        require(result['pass_'], 'segment_retention_and_calls_exact')
        require(len(record['units']) == seg_units,
                'two_declared_obligation_units_per_refresh')
        require(record.get('segment_id', segment_ids[index]) == segment_ids[index],
                'segment_id_threaded_through_record')
        require(record['protocol'] == seg_conf['schema'], 'segment_protocol_from_manifest')
        require(record['mode'] == policy, 'candidate_config_drives_policy')
        require(record['block_plan']['id'] == plan.id, 'candidate_config_drives_plan')
        if write_tables is not None:
            write_tables(record, out/segment_ids[index])
        row = row_for(result)
        if window is not None:
            row.update(overall_status=record['overall_status'],
                       validation_status=record['validation_status'],
                       numeric_pass=record.get('numeric_pass'),
                       resource_status=record['resource_status'])
        summary.append(row)
        if window is not None and not row['condition_valid']:
            row['stop_after'] = 'invalid_interference_condition'
            break
    return summary
