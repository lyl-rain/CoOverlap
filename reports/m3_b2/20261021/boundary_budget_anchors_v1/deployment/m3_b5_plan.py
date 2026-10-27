"""M3 boundary-priority mechanism check at two pre-declared period anchors.

Four conditions over the SAME validated two_9_9 control split (an isolation
choice, not a final-split decision):

    A  P=D=240 ms  serial_context
    B  P=D=240 ms  b2_boundary
    C  P=D=180 ms  serial_context
    D  P=D=180 ms  b2_boundary

8 segments in the order A,B,C,D,D,C,B,A, each 8 cycles / 4 refreshes, Expert
phase fixed at +15 ms, refreshes released from the raw period clock. Not a
budget sweep: exactly two anchors, no phase scan, no interference, no runtime
budget change.
"""
from m2_clean_core import gate_retention_layout, retention_layout
from m3_b3_plan import BINDING, CONTROL, PHASE_NS, THREE, manifest as _manifest

PROTOCOL = 'm3_b5_boundary_budget_anchors_v1'
CYCLES = 8
ORDER = ('serial_context', 'b2_boundary')
PLAN = CONTROL                      # two_9_9, the validated control split
PLANS = {PLAN.id: PLAN, THREE.id: THREE}
ANCHORS = (240_000_000, 180_000_000)

CELLS = (
    dict(id='A_p240_serial', period_ns=240_000_000, policy='serial_context', plan=PLAN.id,
         role='240 ms anchor, serial_context'),
    dict(id='B_p240_boundary', period_ns=240_000_000, policy='b2_boundary', plan=PLAN.id,
         role='240 ms anchor, b2_boundary (the executed r2 cell)'),
    dict(id='C_p180_serial', period_ns=180_000_000, policy='serial_context', plan=PLAN.id,
         role='180 ms anchor, serial_context'),
    dict(id='D_p180_boundary', period_ns=180_000_000, policy='b2_boundary', plan=PLAN.id,
         role='180 ms anchor, b2_boundary'),
)
LETTER_CELL = {c['id'][0]: c for c in CELLS}
PASS_ORDER = (('A', 'B', 'C', 'D'), ('D', 'C', 'B', 'A'))
RUN = tuple(dict(id='p%d_%s' % (p + 1, LETTER_CELL[letter]['id']), cell=LETTER_CELL[letter]['id'],
                 pass_=p + 1, plan=LETTER_CELL[letter]['plan'], policy=LETTER_CELL[letter]['policy'],
                 period_ns=LETTER_CELL[letter]['period_ns'])
            for p, letters in enumerate(PASS_ORDER) for letter in letters)
SEGMENT_IDS = tuple(e['id'] for e in RUN)


def manifest(period_ns, cycles=CYCLES, phase_ns=PHASE_NS):
    """One frozen trajectory per declared budget; the phase moves Experts only."""
    conf = _manifest(period_ns, cycles, phase_ns)
    conf['schema'] = PROTOCOL
    conf['block_plans'] = {p.id: p.summary() for p in PLANS.values()}
    return conf


_MANIFESTS = {}


def manifests():
    """One frozen manifest object per budget, reused by every segment at that budget."""
    if not _MANIFESTS:
        for ns in ANCHORS:
            _MANIFESTS[ns] = manifest(ns)
    return _MANIFESTS


def budget(cycles=CYCLES, segments=len(RUN)):
    layouts = {PLAN.id: retention_layout(cycles, PLAN)}
    gates = {PLAN.id: gate_retention_layout(cycles, PLAN)}
    bank = layouts[PLAN.id]['nbytes']
    gate_bank = gates[PLAN.id]['nbytes']
    payload = segments * bank
    timeline = sum(e['period_ns'] for e in RUN) * cycles / 1e9
    initial = (segments + 2) * 25_276_416
    bootstrap = (segments + 2) * 12_638_208
    fixed = 120_076_776
    binaries = payload + 2 * gate_bank + initial + bootstrap + fixed
    temp = bank + 2_000_000
    subtotal = binaries + 4_000_000 + temp
    estimate = int(subtotal * 1.10)
    return dict(layout=dict(count=layouts[PLAN.id]['count'], nbytes=bank),
                gate_layout=dict(count=gates[PLAN.id]['count'], nbytes=gate_bank),
                bank_bytes=bank, gate_bank_bytes=gate_bank, gpu_and_pinned_bytes=2 * bank,
                batch_payload_bytes=payload, gate_payload_bytes=2 * gate_bank,
                initial_snapshot_bytes=initial, bootstrap_snapshot_bytes=bootstrap,
                fixed_binary_bytes=fixed, binary_total_bytes=binaries,
                json_csv_log_bytes=4_000_000, temp_bytes=temp, subtotal_bytes=subtotal,
                safety_fraction=0.10, estimate_bytes=estimate,
                estimate_gib=round(estimate / 1024**3, 2),
                admission_bytes=12 * 1024**3, admission_gib=12,
                admission_source=['m3_b5_control.preflight (12*1024**3)',
                                  'pi05_m2_clean.prepare via m3_m2_preparation (disk_space_12GiB)'],
                timeline_s=round(timeline, 3), segments=segments, cycles=cycles,
                note='per-segment retention is budget independent (cycle count fixes it);'
                     ' the timeline is the sum of the two declared anchors')


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
        approval_required='new explicit M3 boundary x budget anchor GPU and five-node scope approval',
        anchors_ns=list(ANCHORS), cycles=CYCLES, phase_ns=PHASE_NS, order=list(ORDER),
        plan=PLAN.id, binding=BINDING,
        cells=list(CELLS), run=list(RUN), segment_ids=list(SEGMENT_IDS),
        pass_order=[list(p) for p in PASS_ORDER],
        manifests={str(k): v for k, v in manifests().items()},
        plans={p.id: p.summary() for p in PLANS.values()},
        design=dict(
            question='under a pre-declared 180 ms or 240 ms budget, what violations, Expert waits,'
                     ' refresh publication and backlog do serial_context and b2_boundary show?',
            shared=['plan two_9_9', 'inputs/noise/checkpoint/BF16', 'complete work', 'obligation groups',
                    'consumption v=floor(j/2)', 'even binding + odd reservation', 'Context FIFO',
                    'initial slot/generation/reader state', 'observation rules'],
            differs_only=['period (240 vs 180 ms)', 'Expert decision policy'],
            cross_budget_note='a budget change moves releases, deadlines and refresh arrivals; the two'
                              ' budgets are NOT the same wall-clock arrival trace and are only strictly'
                              ' paired inside each budget',
            not_a_sweep='two anchors only; no phase scan, no interference, no runtime budget change',
            not_calibrated='180 ms is a new protocol anchor; M1 having used 180 ms does not calibrate'
                           ' this executor or imply it passed here'),
        metrics=dict(cycle='release -> max(Expert completion, its complete VLM obligation)',
                     expert='release -> completion (GPU Event confirmed, Host upper bound)',
                     refresh='refresh release -> full KV publish (wall clock, cross-cycle waits included)',
                     fields='Event envelope / Host completion confirmation / Host publish upper bound are'
                            ' reported separately; envelopes are not pure kernel time',
                     denominators='violations/denominator, W, backlog, version waits, incomplete, uncertain'),
        work=dict(batch=dict(work, total_C=total_c, total_E=total_e,
                             note='complete model work including warm-ups and the D1 pipeline'),
                  observed_ledger=dict(contexts=obs_c, experts=obs_e, encoder_layers=obs_c*18,
                                       decoder_layers=obs_e*180, language=obs_c, vision27=obs_c,
                                       rows=obs_c*20+obs_e*180,
                                       note='each observed Context is one complete 18-layer obligation set'),
                  autotune_requests=36, autotune_separate=True),
        retention=b,
        gates=dict(old_reader=dict(journal_entries=22, segment_id='gate_old_reader'),
                   interrupt=dict(journal_entries=24, segment_id='gate_interrupt'),
                   plan=THREE.id),
        protocol_recording=dict(segment_protocol='from the session manifest schema, cross-checked'
                                                 ' against CONFIG.json'),
        fairness=dict(same_plan=True, same_binding=True, same_obligations=True, same_complete_work=True,
                      same_phase=True, per_budget_paired=True, cross_budget_not_matched=True),
        limits=dict(model_processes=1, timeout_s=180, grace_s=10, internal_s=170,
                    scope_count=1, scope_max_s=420, retries=0, new_work_segments=0),
        scope=dict(nodes=5, apply=['cpu policy0/4/8 min_freq=2201600', 'gpu min_freq=1300500000',
                                   'emc min_freq=3199000000']),
        no_performance_or_k_min_claim=True,
        calibration_use='finite two-anchor mechanism check; no violation-rate, tail, k_min or final-route claim')
