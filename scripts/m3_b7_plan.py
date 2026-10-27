"""B7 finite stage-startup diagnostic: only t0 lead differs.

A/B are the same quiet/b2_boundary/two_9_9/180 ms trajectory; A establishes t0
10 ms after preparation, B after 4 s.  Order A,B,B,A; four segments; no pressure
worker, no extra GPU work/warm-up, no other variable.
"""
from m2_clean_core import gate_retention_layout, retention_layout
from m3_b3_plan import BINDING, CONTROL, PHASE_NS, THREE, manifest as _manifest

PROTOCOL = 'm3_b7_stage_startup_v1'
RESULT_STATUS = 'PASS_IN_PROCESS_STAGE_STARTUP_DIAGNOSTIC_V1'
CYCLES = 8
PERIOD_NS = 180_000_000
PLAN = CONTROL
GATE_PLAN = THREE
PLANS = {PLAN.id: PLAN, THREE.id: THREE}
LEAD_SHORT_NS = 10_000_000
LEAD_LONG_NS = 4_000_000_000
NOMINAL_NS = CYCLES * PERIOD_NS
DRAIN_NS = 720_000_000
WORKER_END_NS = NOMINAL_NS + DRAIN_NS
STAGE_SLOTS = 22

CELLS = (
    dict(id='A_lead10ms', cell='A', lead_ns=LEAD_SHORT_NS,
         policy='b2_boundary', plan=PLAN.id, period_ns=PERIOD_NS,
         role='preparation-complete + 10 ms t0'),
    dict(id='B_lead4s', cell='B', lead_ns=LEAD_LONG_NS,
         policy='b2_boundary', plan=PLAN.id, period_ns=PERIOD_NS,
         role='preparation-complete + 4 s t0'),
)
LETTER_CELL = {c['cell']: c for c in CELLS}
ORDER = ('A', 'B', 'B', 'A')
RUN = tuple(dict(id='p%d_%s' % (p + 1, LETTER_CELL[letter]['id']),
                 cell=LETTER_CELL[letter]['cell'], pass_=p + 1,
                 lead_ns=LETTER_CELL[letter]['lead_ns'], interference='quiet',
                 policy=LETTER_CELL[letter]['policy'], plan=LETTER_CELL[letter]['plan'],
                 period_ns=LETTER_CELL[letter]['period_ns'])
            for p, letter in enumerate(ORDER))
SEGMENT_IDS = tuple(e['id'] for e in RUN)
STAGE_TIMESTAMP_NAMES = (
    'stage_enter',
    'event0_before', 'event0_after', 'event1_before', 'event1_after',
    'restore_images_before', 'restore_images_after',
    'restore_noise_before', 'restore_noise_after',
    'capture_images_before', 'capture_images_after',
    'capture_noise_before', 'capture_noise_after',
    'event2_before', 'event2_after', 'event7_before', 'event7_after',
    'event7_wait_before', 'event7_wait_after',
    'confirmation_before', 'confirmation_after',
    'stage_exit',
)


def manifest(period_ns=PERIOD_NS, cycles=CYCLES, phase_ns=PHASE_NS):
    conf = _manifest(period_ns, cycles, phase_ns)
    conf['schema'] = PROTOCOL
    conf['block_plans'] = {p.id: p.summary() for p in PLANS.values()}
    return conf


_MANIFESTS = {}


def manifests():
    if not _MANIFESTS:
        _MANIFESTS[PERIOD_NS] = manifest()
    return _MANIFESTS


def budget(cycles=CYCLES, segments=len(RUN)):
    layout = retention_layout(cycles, PLAN)
    gate_layout = gate_retention_layout(cycles, GATE_PLAN)
    bank = layout['nbytes']
    gate_bank = gate_layout['nbytes']
    payload = segments * bank
    labels = segments + 2
    initial = labels * 25_276_416
    bootstrap = labels * 12_638_208
    fixed = 120_076_776
    binaries = payload + 2 * gate_bank + initial + bootstrap + fixed
    temp = bank + 2_000_000
    subtotal = binaries + 4_000_000 + temp
    estimate = int(subtotal * 1.10)
    # B6 actual (83.853 s, eight segments, 32 s lead) is the only measured
    # reference.  Remove four 4 s leads and four observed segment replays; this
    # is a projection, not a guarantee.
    added_lead_s = (LEAD_SHORT_NS + LEAD_LONG_NS + LEAD_LONG_NS + LEAD_SHORT_NS) / 1e9
    b6_actual_s = 83.85306390898768
    b6_leads_s = 8 * 4.0
    b6_replay_s = 4 * 1.354
    projection_s = b6_actual_s + added_lead_s - b6_leads_s - b6_replay_s
    high_s = projection_s + 10.0
    b6_scope_s = 86.60172838403378
    scope_projection_s = b6_scope_s + added_lead_s - b6_leads_s - b6_replay_s
    scope_high_s = scope_projection_s + 10.0
    return dict(
        layout=dict(count=layout['count'], nbytes=bank),
        gate_layout=dict(plan=GATE_PLAN.id, count=gate_layout['count'], nbytes=gate_bank),
        bank_bytes=bank, gate_bank_bytes=gate_bank, gpu_and_pinned_bytes=2 * bank,
        batch_payload_bytes=payload, gate_payload_bytes=2 * gate_bank,
        initial_snapshot_bytes=initial, bootstrap_snapshot_bytes=bootstrap,
        fixed_binary_bytes=fixed, binary_total_bytes=binaries,
        json_csv_log_bytes=4_000_000, temp_bytes=temp, subtotal_bytes=subtotal,
        safety_fraction=0.10, estimate_bytes=estimate, estimate_gib=round(estimate / 1024**3, 2),
        admission_bytes=12 * 1024**3, admission_gib=12,
        admission_source=['m3_b7_control.preflight (12*1024**3)',
                          'pi05_m2_clean.prepare via m3_m2_preparation (disk_space_12GiB)'],
        labels=labels, segments=segments, cycles=cycles,
        timeline_s=segments * cycles * PERIOD_NS / 1e9,
        worker_budget=dict(max_workers=0, simultaneous_workers=0, quiet_segments=4,
                           fixed_workers=0, no_pressure_worker=True, cpu=None,
                           note='B7 deliberately creates no pressure worker'),
        stage_observation=dict(slots=STAGE_SLOTS, stages_per_segment=4,
                               total_slots=STAGE_SLOTS*4, names=list(STAGE_TIMESTAMP_NAMES),
                               preallocated=True, polls='aggregate_count_only',
                               host_only=True, no_gpu_operation=True,
                               no_extra_sync=True, d2h_after_window=True),
        time_budget=dict(added_lead_s=added_lead_s, b6_actual_s=b6_actual_s,
                         b6_leads_s=b6_leads_s, b6_replay_allowance_s=b6_replay_s,
                         projection_s=projection_s,
                         projection_with_allowance_s=high_s,
                         scope_projection_s=scope_projection_s,
                         scope_projection_with_allowance_s=scope_high_s,
                         internal_deadline_s=170, outer_timeout_s=180,
                         exit_grace_s=10, scope_max_s=420,
                         internal_headroom_projection_s=170 - projection_s,
                         internal_headroom_high_s=170 - high_s,
                         outer_headroom_projection_s=180 - projection_s,
                         outer_headroom_high_s=180 - high_s,
                         measured=False,
                         caveat='B6-derived projection; not a startup bound, WCET or '
                                'feasibility guarantee; B7 differs in segment count and lead'),
        note='four segments only; disk paths/labels recomputed for 4 segments + 2 gates',
    )


def protocol():
    b = budget()
    work = dict(warmup_C=2, reference_C=2, reference_E=2, D1_C=1, D1_E=1,
                prefix_reference_C=2, assembly_C=1, assembly_E=1,
                old_reader_gate_C=2, old_reader_gate_E=1,
                interrupt_gate_C=2, interrupt_gate_E=1,
                segment_bootstrap_C=len(RUN),
                timed_C=len(RUN) * CYCLES // 2, timed_E=len(RUN) * CYCLES)
    total_c = sum(v for k, v in work.items() if k.endswith('_C'))
    total_e = sum(v for k, v in work.items() if k.endswith('_E'))
    obs_c = total_c - work['warmup_C'] - work['D1_C']
    obs_e = total_e - work['D1_E']
    return dict(
        id=PROTOCOL, status='PREPARED',
        approval_required='new explicit B7 stage-startup GPU and five-node scope approval',
        period_ns=PERIOD_NS, deadline_ns=PERIOD_NS, cycles=CYCLES, phase_ns=PHASE_NS,
        plan=PLAN.id, binding=BINDING, order=list(ORDER),
        cells=list(CELLS), run=list(RUN), segment_ids=list(SEGMENT_IDS),
        manifests={str(k): v for k, v in manifests().items()},
        plans={p.id: p.summary() for p in PLANS.values()},
        design=dict(
            question='does the t0 lead after preparation change the first R0/stage '
                     'Host interval and the subsequent cycle/refresh outcome?',
            only_variable='lead_ns: 10 ms (A) vs 4 s (B)',
            shared=['quiet', 'b2_boundary', 'two_9_9', 'P=D=180 ms', 'Expert +15 ms',
                    '8 cycles/4 refreshes', 'same complete work/retention',
                    'same window coordinator', 'same stage observation'],
            order='A,B,B,A',
            no_extra='no serial, no pressure worker, no other lead, no warm-up, no probe',
            interpretation='if long lead shows first-stage latency and short does not, report the '
                           'correspondence and Host intervals; do not declare GPU wake/page/driver/'
                           'frequency root cause',
        ),
        timing=dict(
            lead_A_ns=LEAD_SHORT_NS, lead_B_ns=LEAD_LONG_NS,
            t0='single t0 after bootstrap/initial restore/report init/GPU drain + configured lead',
            nominal_end='t0 + 8*180 ms = t0 + 1.440 s', drain_ns=DRAIN_NS,
            worker_end='t0 + 2.160 s', no_t0_move=True, no_retry=True,
            late='actual start lateness does not move releases; original release/deadline kept',
            prep_boundary='bootstrap, initial restore, report initialization and GPU drain complete before t0',
            both_rules='same SegmentWindow and finite-resource rules for A and B',
        ),
        stage_observation=dict(
            slots=STAGE_SLOTS, stages_per_segment=4, total_slots=STAGE_SLOTS*4,
            timestamps=list(STAGE_TIMESTAMP_NAMES),
            scope='stage path only; symmetric for A/B',
            content=['stage entry/exit', 'Event0/1/2/7 record before/after',
                     'images/noise restore before/after', 'images/noise capture before/after',
                     'Event7 wait start/end', 'completion confirmation before/after'],
            polling='aggregate poll count only; no per-poll log',
            storage='preallocated in memory; window writes no JSON/file',
            d2h='D2H/comparison/serialization/write after window only',
            claims='Host interval is not pure driver time; Event envelope is not pure kernel time; '
                   'do not subtract Host-Event to claim CPU cost',
        ),
        work=dict(batch=dict(work, total_C=total_c, total_E=total_e,
                             note='complete preparation including warm-ups and D1'),
                  observed_ledger=dict(contexts=obs_c, experts=obs_e,
                                       language=obs_c, vision27=obs_c, encoder_layers=obs_c*18,
                                       decoder_layers=obs_e*180, rows=obs_c*20+obs_e*180,
                                       note='29*20 + 37*180 = 7,240 rows'),
                  autotune_requests=36, autotune_separate=True),
        retention=b,
        gates=dict(old_reader=dict(journal_entries=22, segment_id='gate_old_reader'),
                   interrupt=dict(journal_entries=24, segment_id='gate_interrupt'),
                   plan=GATE_PLAN.id),
        fairness=dict(same_plan=True, same_binding=True, same_obligations=True,
                      same_complete_work=True, same_phase=True, same_manifest=True,
                      only_lead_differs=True, cells_two=True),
        limits=dict(model_processes=1, timeout_s=180, grace_s=10, internal_s=170,
                    scope_count=1, scope_max_s=420, retries=0,
                    pressure_workers=0, new_work_segments=0, new_candidates=0),
        stage_slots=STAGE_SLOTS,
        no_pressure_worker=True,
        no_new_performance_baseline=True,
        no_correction='cycle 0 retained; first-stage latency not subtracted; no corrected performance',
        no_performance_or_k_min_claim=True,
        scope=dict(nodes=5, apply=['cpu policy0/4/8 min_freq=2201600',
                                   'gpu min_freq=1300500000', 'emc min_freq=3199000000']),
    )
