"""M3 split x priority minimal ablation (PREPARED only; no GPU, no hardware write).

Four matched cells over the same frozen manifest, inputs, consumption contract,
releases, deadlines, obligation groups and complete work:

    A  two_9_9            + serial_context
    B  two_9_9            + b2_boundary
    C  three_prefix_9_9   + serial_context
    D  three_prefix_9_9   + b2_boundary

A/B isolate the priority order at the two-block split, C/D at the three-block
split; A/C and B/D isolate the extra legal cut at fixed priority. One process,
one autotune, same numerical configuration. No new cut point, graph, concurrency,
partition, interference or budget sweep is introduced.
"""
from m2_clean_core import gate_retention_layout, retention_layout
from m3_b3_plan import (BINDING, CONTROL, PERIOD_NS, PHASE_NS, THREE,
                        manifest as three_block_manifest)

PROTOCOL = 'm3_b4_split_priority_ablation_v1'
CYCLES = 8
ORDER = ('serial_context', 'b2_boundary')
PLANS = {p.id: p for p in (CONTROL, THREE)}
ARTIFACT_BYTES = 400 * 1024 * 1024      # references, assembly, indexes, logs
DISK_REQUIRED_BYTES = 8 * 1024**3      # conservative floor above the exact payload

CELLS = (
    dict(id='A_two_serial_context', plan=CONTROL.id, policy='serial_context',
         role='two-block split; Expert decisions suppressed while a Context executes',
         isolates='priority order at the two-block split',
         pair=dict(twin='B_two_b2_boundary', dimension='priority')),
    dict(id='B_two_b2_boundary', plan=CONTROL.id, policy='b2_boundary',
         role='two-block split; released Experts served at legal block boundaries',
         isolates='the r2 control cell (same split, boundary priority)',
         pair=dict(twin='A_two_serial_context', dimension='priority')),
    dict(id='C_three_serial_context', plan=THREE.id, policy='serial_context',
         role='three-block split; Expert decisions suppressed while a Context executes',
         isolates='priority order at the three-block split',
         pair=dict(twin='D_three_b2_boundary', dimension='priority')),
    dict(id='D_three_b2_boundary', plan=THREE.id, policy='b2_boundary',
         role='three-block split; released Experts served at legal block boundaries',
         isolates='the r2 three-block cell (same split, boundary priority)',
         pair=dict(twin='C_three_serial_context', dimension='priority')),
)
CELL_BY_ID = {c['id']: c for c in CELLS}

# Two declared passes in opposite order give a within-process position control.
PASS_ORDER = (('A', 'B', 'C', 'D'), ('D', 'C', 'B', 'A'))
LETTER_CELL = {c['id'][0]: c for c in CELLS}
RUN = tuple(dict(id='p%d_%s' % (p + 1, LETTER_CELL[letter]['id']),
                 cell=LETTER_CELL[letter]['id'], pass_=p + 1,
                 plan=LETTER_CELL[letter]['plan'], policy=LETTER_CELL[letter]['policy'])
            for p, letters in enumerate(PASS_ORDER) for letter in letters)
SEGMENT_IDS = tuple(entry['id'] for entry in RUN)


def manifest(period_ns=PERIOD_NS, cycles=CYCLES, phase_ns=PHASE_NS):
    """The single frozen trajectory shared by all four cells."""
    conf = three_block_manifest(period_ns, cycles, phase_ns)
    conf['schema'] = PROTOCOL
    conf['block_plans'] = {p.id: p.summary() for p in (CONTROL, THREE)}
    return conf


def budget(cycles=CYCLES, segments=len(RUN)):
    """Every capacity, payload and time figure recomputed for this trajectory."""
    layouts = {p.id: retention_layout(cycles, p) for p in (CONTROL, THREE)}
    gates = {p.id: gate_retention_layout(cycles, p) for p in (CONTROL, THREE)}
    bank = max(v['nbytes'] for v in layouts.values())
    gate_bank = max(v['nbytes'] for v in gates.values())
    per_cell = {c['id']: layouts[c['plan']]['nbytes'] for c in CELLS}
    payload = sum(per_cell[entry['cell']] for entry in RUN)
    gate_payload = 2 * gate_bank
    timeline_s = segments * cycles * PERIOD_NS / 1e9
    return dict(
        layouts={k: dict(count=v['count'], nbytes=v['nbytes']) for k, v in layouts.items()},
        gate_layouts={k: dict(count=v['count'], nbytes=v['nbytes']) for k, v in gates.items()},
        per_cell_segment_bytes=per_cell,
        bank_bytes=bank, gate_bank_bytes=gate_bank,
        gpu_and_pinned_bytes=2 * bank,
        batch_payload_bytes=payload,
        gate_payload_bytes=gate_payload,
        artifact_bytes=ARTIFACT_BYTES,
        disk_bytes=payload + gate_payload + ARTIFACT_BYTES,
        disk_required_bytes=DISK_REQUIRED_BYTES,
        timeline_s=timeline_s,
        segments=segments, cycles=cycles, period_ns=PERIOD_NS,
        note='exact intake of the declared trajectory; not the previous batch numbers')


def protocol():
    b = budget()
    work_c = dict(warmup_C=2, reference_C=2, reference_E=2, D1_C=1, D1_E=1,
                  prefix_reference_C=2, assembly_C=1, assembly_E=1,
                  old_reader_gate_C=2, old_reader_gate_E=1,
                  interrupt_gate_C=2, interrupt_gate_E=1,
                  segment_bootstrap_C=len(RUN),
                  timed_C=len(RUN) * CYCLES // 2, timed_E=len(RUN) * CYCLES)
    total_c = sum(v for k, v in work_c.items() if k.endswith('_C'))
    total_e = sum(v for k, v in work_c.items() if k.endswith('_E'))
    observed_c = total_c - work_c['warmup_C'] - work_c['D1_C']
    observed_e = total_e - work_c['D1_E']
    return dict(
        id=PROTOCOL, status='PREPARED',
        approval_required='new explicit M3 split x priority ablation GPU and five-node scope approval',
        order=list(ORDER), cycles=CYCLES, period_ns=PERIOD_NS, phase_ns=PHASE_NS,
        binding=BINDING, manifest=manifest(),
        cells=list(CELLS), run=list(RUN), segment_ids=list(SEGMENT_IDS),
        pass_order=[list(p) for p in PASS_ORDER],
        plans={p.id: p.summary() for p in (CONTROL, THREE)},
        design=dict(
            question='does the priority order interact with the extra legal split?',
            contrasts=dict(priority_two='A vs B', priority_three='C vs D',
                           split_serial='A vs C', split_boundary='B vs D',
                           interaction='(A-B) vs (C-D) and (A-C) vs (B-D)'),
            shared=['manifest', 'inputs', 'noise', 'checkpoint', 'precision', 'consumption v=floor(id/2)',
                    'even dispatch reserves odd partner on the same published v',
                    'Context FIFO', 'obligation groups', 'complete work', 'retention path'],
            differs_only=['block plan (2 vs 3 legal cuts)', 'Expert decision policy during Context execution'],
            serial_rule='A/C keep the identical blocks, fences and retention; they only suppress Expert'
                        ' decisions while a Context is executing, and still release the already-released'
                        ' Expert that the publication guard needs once every block has completed',
            not_a_new_implementation='serial_context uses the same block math, fences, D2D retention and'
                                     ' publication path as boundary; no fused reimplementation and no'
                                     ' omitted intermediate observation cost',
            order_control='two passes in opposite declared order (A,B,C,D then D,C,B,A); each segment'
                          ' restores the same physical initial state and starts from the same manifest',
            limits=['n=4 refreshes per cell per pass; not a tail/k_min/net-benefit sample',
                    'two passes are not independent repeats (same process/autotune/inputs)',
                    'no cross-process independent repetition',
                    'fixed +15 ms phase only; no phase sweep']),
        metrics=dict(
            expert_wait='release -> dispatch decision (Host monotonic_ns)',
            expert_response='release -> completion (GPU Event confirmed, Host upper bound)',
            cycle_response='period release -> all obligations of that cycle complete, including the same'
                           ' complete VLM obligation group',
            refresh_ready='refresh release -> full KV publish (wall clock, includes cross-cycle waits)',
            obligations='violations/denominator, W assigned/completed, backlog, incomplete, uncertain',
            kernels='Event envelopes include submission gaps and instrumentation; never reported as pure kernel time',
            host_vs_gpu='Host decision time, completion confirmation time and GPU Event time reported separately',
            aligned_scope='the same mathematical scope is compared across cells (two-block B1 = P+B1 of the'
                          ' three-block plan; sequential keys B1/B2/B3 are not mathematical names)'),
        work=dict(
            batch=dict(work_c, total_C=total_c, total_E=total_e,
                       note='complete model work: %d Contextes and %d Expert10, including 2 discarded'
                            ' warm-ups and the 1+1 D1 original pipeline' % (total_c, total_e)),
            observed_ledger=dict(contexts=observed_c, experts=observed_e,
                                 encoder_layers=observed_c * 18, decoder_layers=observed_e * 180,
                                 language=observed_c, vision27=observed_c,
                                 rows=observed_c * 20 + observed_e * 180,
                                 excluded=['warmup_C=2 (outside the ledger by design)',
                                           'D1 original run_pipeline 1C+1E (bypasses the wrappers)'],
                                 note='each observed Context is one complete 18-layer VLM obligation set;'
                                      ' the per-segment counts must be identical for all four cells'),
            autotune_requests=36, autotune_separate=True),
        retention=b,
        gates=dict(
            old_reader=dict(journal_entries=22, segment_id='gate_old_reader'),
            interrupt=dict(journal_entries=24, segment_id='gate_interrupt'),
            plan=THREE.id,
            verification='exact journal content and order from expected_gate_signature; not a length check'),
        protocol_recording=dict(
            segment_protocol='taken from the session manifest schema, cross-checked against CONFIG.json',
            legacy='r2 raw segments[].protocol=m3_b2_boundary_profile_v1 is preserved unchanged; this batch'
                   ' records its own identity and never rewrites the r2 artifacts'),
        limits=dict(model_processes=1, timeout_s=180, grace_s=10, internal_s=170,
                    scope_count=1, scope_max_s=420, retries=0, new_work_segments=0),
        fairness=dict(same_manifest=True, same_binding=True, same_phase=True,
                      same_releases_and_deadlines=True, same_inputs=True,
                      same_obligation_groups=True, same_complete_work=True,
                      same_retention_rule=True, different=['plan', 'policy'],
                      order_control='opposite declared passes inside one process'),
        scope=dict(nodes=5, path='frozen v6 SnapshotTransaction apply/restore with independent uid1001 readback',
                   apply=['cpu policy0/4/8 min_freq=2201600', 'gpu min_freq=1300500000',
                          'emc min_freq=3199000000'],
                   snapshot='real per-batch clock_before.json (root 0600)',
                   restore='descendant cleanup first, then reverse restore, then independent readback'),
        no_performance_or_k_min_claim=True,
        calibration_use='finite four-cell mechanism contrast; not a paper baseline, not a tail estimate')
