"""M3 four-condition controlled-interference batch (two_9_9, P=D=180 ms).

A=quiet/serial, B=quiet/b2_boundary, C=fixed_cpu_mem/serial,
D=fixed_cpu_mem/b2_boundary; order A,B,C,D,D,C,B,A, 8 cycles / 4 refreshes
each.  The interference worker is the accepted r1 window-gated CPU11 worker.
No new candidate, phase, intensity, budget, probe or warm-up is introduced.
"""
from m2_clean_core import gate_retention_layout, retention_layout
from m3_b3_plan import BINDING, CONTROL, PHASE_NS, THREE, manifest as _manifest

PROTOCOL = 'm3_b6_controlled_interference_v1'
RESULT_STATUS = 'PASS_IN_PROCESS_CONTROLLED_INTERFERENCE_V1'
CYCLES = 8
PERIOD_NS = 180_000_000
ORDER = ('serial_context', 'b2_boundary')
PLAN = CONTROL
GATE_PLAN = THREE
PLANS = {PLAN.id: PLAN, THREE.id: THREE}

# Pre-declared engineering timing.  These are not measured startup bounds,
# WCET or feasibility guarantees.
LEAD_NS = 4_000_000_000
NOMINAL_NS = CYCLES * PERIOD_NS          # 1.440 s
DRAIN_NS = 720_000_000                   # 0.720 s
WORKER_END_NS = NOMINAL_NS + DRAIN_NS    # 2.160 s

CELLS = (
    dict(id='A_quiet_serial', cell='A', interference='quiet', policy='serial_context',
         plan=PLAN.id, period_ns=PERIOD_NS,
         role='quiet + serial_context'),
    dict(id='B_quiet_boundary', cell='B', interference='quiet', policy='b2_boundary',
         plan=PLAN.id, period_ns=PERIOD_NS,
         role='quiet + b2_boundary'),
    dict(id='C_fixed_serial', cell='C', interference='fixed_cpu_mem', policy='serial_context',
         plan=PLAN.id, period_ns=PERIOD_NS,
         role='fixed_cpu_mem + serial_context'),
    dict(id='D_fixed_boundary', cell='D', interference='fixed_cpu_mem', policy='b2_boundary',
         plan=PLAN.id, period_ns=PERIOD_NS,
         role='fixed_cpu_mem + b2_boundary'),
)
LETTER_CELL = {c['cell']: c for c in CELLS}
PASS_ORDER = (('A', 'B', 'C', 'D'), ('D', 'C', 'B', 'A'))
RUN = tuple(dict(id='p%d_%s' % (p + 1, LETTER_CELL[letter]['id']),
                 cell=LETTER_CELL[letter]['cell'], pass_=p + 1,
                 interference=LETTER_CELL[letter]['interference'],
                 policy=LETTER_CELL[letter]['policy'], plan=LETTER_CELL[letter]['plan'],
                 period_ns=LETTER_CELL[letter]['period_ns'])
            for p, letters in enumerate(PASS_ORDER) for letter in letters)
SEGMENT_IDS = tuple(e['id'] for e in RUN)
INTERFERENCE_MODES = ('quiet', 'fixed_cpu_mem')


def manifest(period_ns=PERIOD_NS, cycles=CYCLES, phase_ns=PHASE_NS):
    """One frozen 180 ms trajectory shared by every condition."""
    conf = _manifest(period_ns, cycles, phase_ns)
    conf['schema'] = PROTOCOL
    conf['block_plans'] = {p.id: p.summary() for p in PLANS.values()}
    conf['interference_excluded'] = True
    return conf


_MANIFESTS = {}


def manifests():
    if not _MANIFESTS:
        _MANIFESTS[PERIOD_NS] = manifest()
    return _MANIFESTS


def worker_budget():
    per_worker = 2 * (32 * 1024 * 1024 + 2 * 64)
    return dict(
        max_workers=4, simultaneous_workers=1, quiet_workers=0, fixed_workers=4,
        worker_mode='fixed_cpu_mem', cpu=11,
        source_capacity_bytes=32 * 1024 * 1024,
        dest_capacity_bytes=32 * 1024 * 1024,
        copy_length_bytes=32 * 1024 * 1024,
        guard_bytes_per_side=64,
        data_buffers_bytes_per_worker=per_worker,
        shared_memory_bytes=64,
        python_runtime_overhead='not bounded by the buffer byte count',
        rss_limit=False,
        process_tree='one model; at most four sequential workers, one at a time; '
                     'python shared-memory/resource-tracker helper if present',
        no_adaptive_intensity=True,
        copy_bytes_interpretation='logical memmove bytes, NOT DRAM bandwidth',
    )


def time_budget():
    b5_observed_s = 76.468
    added_lead_s = 8 * (LEAD_NS - 10_000_000) / 1e9   # B5 used +10 ms
    added_drain_s = 8 * DRAIN_NS / 1e9
    projection_s = b5_observed_s + added_lead_s + added_drain_s
    cleanup_allowance_s = 4 * 3.0
    high_s = projection_s + cleanup_allowance_s
    scope_projection_s = 78.841 + added_lead_s + added_drain_s
    return dict(
        lead_ns=LEAD_NS, nominal_ns=NOMINAL_NS, drain_ns=DRAIN_NS,
        worker_end_ns=WORKER_END_NS,
        b5_observed_model_s=b5_observed_s,
        added_lead_s=added_lead_s, added_drain_s=added_drain_s,
        projection_s=projection_s,
        projection_with_cleanup_allowance_s=high_s,
        internal_deadline_s=170, outer_timeout_s=180, exit_grace_s=10,
        internal_headroom_projection_s=170 - projection_s,
        internal_headroom_high_s=170 - high_s,
        outer_headroom_projection_s=180 - projection_s,
        outer_headroom_high_s=180 - high_s,
        scope_projection_s=scope_projection_s,
        scope_max_s=420,
        measured=False,
        caveat='projection from B5 observed time plus fixed lead/drain; NOT a startup bound, '
               'WCET or feasibility guarantee; worker readiness/cleanup and real D2H/write '
               'costs must be measured on the board',
    )


def budget(cycles=CYCLES, segments=len(RUN)):
    layouts = {PLAN.id: retention_layout(cycles, PLAN)}
    gate_layout = gate_retention_layout(cycles, GATE_PLAN)
    bank = layouts[PLAN.id]['nbytes']
    gate_bank = gate_layout['nbytes']
    payload = segments * bank
    timeline = segments * cycles * PERIOD_NS / 1e9
    initial = (segments + 2) * 25_276_416
    bootstrap = (segments + 2) * 12_638_208
    fixed = 120_076_776
    binaries = payload + 2 * gate_bank + initial + bootstrap + fixed
    temp = bank + 2_000_000
    subtotal = binaries + 4_000_000 + temp
    estimate = int(subtotal * 1.10)
    return dict(
        layout=dict(count=layouts[PLAN.id]['count'], nbytes=bank),
        gate_layout=dict(plan=GATE_PLAN.id, count=gate_layout['count'], nbytes=gate_bank),
        bank_bytes=bank, gate_bank_bytes=gate_bank, gpu_and_pinned_bytes=2 * bank,
        batch_payload_bytes=payload, gate_payload_bytes=2 * gate_bank,
        initial_snapshot_bytes=initial, bootstrap_snapshot_bytes=bootstrap,
        fixed_binary_bytes=fixed, binary_total_bytes=binaries,
        json_csv_log_bytes=4_000_000, temp_bytes=temp, subtotal_bytes=subtotal,
        safety_fraction=0.10, estimate_bytes=estimate,
        estimate_gib=round(estimate / 1024**3, 2),
        admission_bytes=12 * 1024**3,
        admission_gib=12,
        admission_source=['m3_b6_control.preflight (12*1024**3)',
                          'pi05_m2_clean.prepare via m3_m2_preparation (disk_space_12GiB)'],
        timeline_s=timeline, segments=segments, cycles=cycles,
        worker_budget=worker_budget(),
        time_budget=time_budget(),
        note='per-segment retention is cycle-count fixed; worker buffers are listed separately '
             'and are not part of the retention estimate',
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
    obs_c, obs_e = total_c - work['warmup_C'] - work['D1_C'], total_e - work['D1_E']
    return dict(
        id=PROTOCOL, status='PREPARED',
        approval_required='new explicit M3 controlled-interference GPU and five-node scope approval',
        period_ns=PERIOD_NS, deadline_ns=PERIOD_NS, cycles=CYCLES, phase_ns=PHASE_NS,
        order=list(ORDER), plan=PLAN.id, binding=BINDING,
        cells=list(CELLS), run=list(RUN), segment_ids=list(SEGMENT_IDS),
        pass_order=[list(p) for p in PASS_ORDER],
        manifests={str(k): v for k, v in manifests().items()},
        plans={p.id: p.summary() for p in PLANS.values()},
        design=dict(
            question='under P=D=180 ms and fixed t0 windows, how do serial_context and '
                     'b2_boundary respond to quiet versus fixed CPU11 memmove interference?',
            mapping=dict(A='quiet + serial_context', B='quiet + b2_boundary',
                         C='fixed_cpu_mem + serial_context',
                         D='fixed_cpu_mem + b2_boundary'),
            comparisons=['A->B: quiet priority-policy difference',
                         'C->D: fixed-interference priority-policy difference',
                         'A->C: serial response to interference',
                         'B->D: boundary response to interference'],
            shared=['plan two_9_9', 'P=D=180 ms', 'Expert phase +15 ms',
                    'inputs/noise/precision/consumption versions',
                    'refresh release and complete obligations',
                    'non-Graph single stream and two-slot version lifecycle',
                    'D1 same-process byte-exact admission'],
            passes='A,B,C,D then D,C,B,A; two sequential passes, NOT independent repeats',
            no_extension='no extra candidate, phase, intensity, budget, probe or warm-up',
        ),
        timing=dict(
            lead_ns=LEAD_NS, t0='one monotonic t0 = preparation_complete + lead_ns',
            nominal_end='t0 + 8*180 ms = t0 + 1.440 s',
            drain_ns=DRAIN_NS, worker_end='t0 + 2.160 s',
            shared_t0='worker plan.start_ns and replay t0 are the same value',
            quiet='same t0 and worker_end; no pressure worker exists',
            readiness_timeout_ns=3_000_000_000, ready_margin_ns=10_000_000,
            readiness_deadline='one absolute deadline; spawn/receive/parse/validate consume it',
            no_retry=True, no_t0_move=True, no_window_extension=True,
            early_replay='worker stays until fixed worker_end',
            late_replay='worker not extended; mark coverage and stop subsequent segments',
            pre_window='bootstrap/initial restore/allocation/report init/GPU drain complete before t0',
        ),
        interference=dict(
            worker_protocol='m3_ci_worker_v1_r1',
            lifecycle_protocol='m3_interference_lifecycle_v1_r1',
            modes=list(INTERFERENCE_MODES), fixed='fixed_cpu_mem', quiet='quiet',
            one_worker_at_a_time=True, max_total_workers=4, retries=0,
            worker_budget=worker_budget(),
            evidence='Host copy_loop_enter/exit, first_copy_call, last_copy_return, copies, '
                     'bytes, start lateness, end overrun; copies=0 is invalid',
            coverage='condition valid only if replay_end <= worker_end and worker work valid; '
                     'positive copies prove work occurred, not continuous bandwidth',
            file_policy='worker writes no JSON/log file; normal timed path has no file/JSON write',
            outside_window='bootstrap/autotune/reference/D1/gates/all model warm-up outside pressure',
        ),
        metrics=dict(cycle='release -> max(Expert completion, its complete VLM obligation)',
                     expert='release -> completion (GPU Event confirmed, Host upper bound)',
                     refresh='refresh release -> full KV publish (wall clock)',
                     fields='Event envelope / Host completion confirmation / Host publish upper bound '
                            'reported separately',
                     denominators='violations/denominator, W, backlog, version waits, incomplete, uncertain',
                     worker='worker execution/coverage reported separately; copy_bytes logical only'),
        work=dict(batch=dict(work, total_C=total_c, total_E=total_e,
                             note='complete model work including warm-ups and D1'),
                  observed_ledger=dict(contexts=obs_c, experts=obs_e, encoder_layers=obs_c * 18,
                                       decoder_layers=obs_e * 180, language=obs_c, vision27=obs_c,
                                       rows=obs_c * 20 + obs_e * 180,
                                       note='each observed Context is one complete 18-layer set'),
                  autotune_requests=36, autotune_separate=True),
        retention=b,
        gates=dict(old_reader=dict(journal_entries=22, segment_id='gate_old_reader'),
                   interrupt=dict(journal_entries=24, segment_id='gate_interrupt'),
                   plan=GATE_PLAN.id),
        protocol_recording=dict(segment_protocol='from the session manifest schema, cross-checked '
                                                 'against CONFIG.json'),
        fairness=dict(same_plan=True, same_binding=True, same_obligations=True,
                      same_complete_work=True, same_phase=True, same_manifest=True,
                      same_relative_releases=True,
                      wallclock_paired=False,
                      pairs=['A/B quiet policy', 'C/D fixed policy', 'A/C serial response',
                             'B/D boundary response']),
        time_budget=time_budget(),
        limits=dict(model_processes=1, timeout_s=180, grace_s=10, internal_s=170,
                    scope_count=1, scope_max_s=420, retries=0,
                    worker_processes_max=4, simultaneous_workers=1,
                    new_work_segments=0, new_candidates=0, phase_scans=0,
                    intensity_settings=1, budget_settings=1),
        scope=dict(nodes=5, apply=['cpu policy0/4/8 min_freq=2201600',
                                   'gpu min_freq=1300500000', 'emc min_freq=3199000000']),
        no_performance_or_k_min_claim=True,
        calibration_use='finite four-condition mechanism check; no violation-rate, tail, k_min '
                        'or final-route claim; performance violations are normal results',
    )
