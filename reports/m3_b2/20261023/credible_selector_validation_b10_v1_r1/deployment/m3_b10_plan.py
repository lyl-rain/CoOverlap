"""M3 Expert-reserve selection validation (PREPARED only; no GPU, no hardware write).

Four pre-declared conditions over the two validated split plans, both with
``b2_boundary``:

    A  two_9_9          P=D=160 ms
    B  three_prefix_9_9 P=D=160 ms
    C  two_9_9          P=D=150 ms
    D  three_prefix_9_9 P=D=150 ms

Order A,B,C,D,D,C,B,A; each segment 8 cycles / 4 complete Context refreshes.
Within one budget the two candidates are strictly paired; the two budgets are
NOT the same wall-clock arrival trace.  This is a finite challenge, not a sweep,
tail study, WCET argument, k_min measurement or final-split decision.
"""
from m2_clean_core import gate_retention_layout, retention_layout
from m3_b3_plan import BINDING, CONTROL, PHASE_NS, THREE, manifest as _manifest

PROTOCOL = 'm3_b10_credible_selector_validation_v1'
RESULT_STATUS = 'PASS_IN_PROCESS_CREDIBLE_SELECTOR_VALIDATION'
CYCLES = 8
ORDER = ('b2_boundary',)          # this batch has one priority policy only
BUDGETS = (160_000_000, 150_000_000)
GATE_PLAN = THREE                 # gates keep the validated three-block path
PLANS = {CONTROL.id: CONTROL, THREE.id: THREE}

# Final identity constants are populated only by freeze_package.py.
PREDICTION_STATUS = 'PRE_RUN_PREDICTION_FROZEN'
PREDICTION_PATH = 'prediction/PREDICTION.json'
PREDICTION_SHA256 = 'ad4da44ad3194ddcb4ad3b0fd07f30d5755cbd2bf05b73f0e0d2cac8b80a35ce'
PREDICTION_FINGERPRINT = 'b7482a9d802f4df2066a7e65f9e1ea299833c802c3872f40047aaad10a6f8330'
SELECTION_PATH = 'prediction/SELECTION_FREEZE.json'
SELECTION_SHA256 = 'e46992433ae1352bb58bba9ad4a72466e3f98a7081b4db63fd7d91bf2f4121a7'
SELECTION_FINGERPRINT = 'cc72dac68702cab887efc5554bc4e34d96455f18095c20fbf6704c25edc8d0a2'
RESERVE_MS = 10.0
RULE_ID = 'credible_plan_selector_v2'
ANALYSIS_MODULES = {'evaluate_b10.py': '79848335eac411e7cb22f67d8102e682bce2807cf4547cacb88f321ddc5d7141', 'build_b10_prediction.py': '114f95a07fa205dc16cf3ce8e94dc1e5f88d0cba3d13a9c3944cc5afc722d08f', 'run.py': 'e84e0d12778cbd3e5246e540c9ed37dcdf374eeb02a4c022a40f281e001e232c', 'core.py': '0e8d6d58accc112ddc948227844b0f4635af40878aa6ce252e061e0f6e8e78ee', 'model.py': 'f928df142edf55c5c0a2c09095d51e201428cdee140c53bed3d185dd6a7527e5', 'integrity.py': '9659f9c9ef9b19989894d458da1e95804fe0be6d1809b9acf6b57715afd442d6', 'test_cps2_cpu.py': '9a7b31f5df4e8bec681ac920366215b3f7fe41eaefd4b7d2c7c168d79eea50c2'}
RULE_SHA256 = 'acef611a8c7142a223785b4f39944b5319615f920c6871d99788e6f8c5facb42'
COSTS_SHA256 = 'fb8ddd337f1927bcf06dd15d628767176233194aa797f6d95d7ff1bccd551e64'
SELECTION_BY_PERIOD = {'150000000': {'accepted': [], 'candidates': {'three_prefix_9_9': {'G0': {'full_work': True, 'lifecycle': True, 'missing': [], 'pass_': True}, 'G1': {'pass_': True}, 'G2': {'pass_': False}, 'G3': {'pass_': True}, 'MC': 7.195, 'ME': 35.559, 'MR': 97.496, 'MU': 7.195, 'accepted': False, 'reason': 'G2 reserve fail'}, 'two_9_9': {'G0': {'full_work': True, 'lifecycle': True, 'missing': [], 'pass_': True}, 'G1': {'pass_': True}, 'G2': {'pass_': False}, 'G3': {'pass_': True}, 'MC': 9.48, 'ME': 9.48, 'MR': 99.853, 'MU': 85.211, 'accepted': False, 'reason': 'G2 reserve fail'}}, 'note': 'not a mathematical infeasibility claim', 'rejections': {'three_prefix_9_9': 'G2 reserve fail', 'two_9_9': 'G2 reserve fail'}, 'selected': None, 'status': 'NO_ACCEPTABLE_PLAN_UNDER_RULE'}, '160000000': {'accepted': ['two_9_9', 'three_prefix_9_9'], 'candidates': {'three_prefix_9_9': {'G0': {'full_work': True, 'lifecycle': True, 'missing': [], 'pass_': True}, 'G1': {'pass_': True}, 'G2': {'pass_': True}, 'G3': {'pass_': True}, 'MC': 17.195, 'ME': 55.559, 'MR': 117.496, 'MU': 17.195, 'accepted': True, 'reason': ''}, 'two_9_9': {'G0': {'full_work': True, 'lifecycle': True, 'missing': [], 'pass_': True}, 'G1': {'pass_': True}, 'G2': {'pass_': True}, 'G3': {'pass_': True}, 'MC': 19.48, 'ME': 19.48, 'MR': 119.853, 'MU': 95.211, 'accepted': True, 'reason': ''}}, 'selected': 'two_9_9', 'status': 'SELECTED'}}

CELLS = (
    dict(id='A_p160_two_b2_boundary', letter='A', period_ns=160_000_000,
         plan=CONTROL.id, policy='b2_boundary',
         role='two-block split at the 160 ms budget'),
    dict(id='B_p160_three_b2_boundary', letter='B', period_ns=160_000_000,
         plan=THREE.id, policy='b2_boundary',
         role='three-block split at the 160 ms budget'),
    dict(id='C_p150_two_b2_boundary', letter='C', period_ns=150_000_000,
         plan=CONTROL.id, policy='b2_boundary',
         role='two-block split at the 150 ms budget'),
    dict(id='D_p150_three_b2_boundary', letter='D', period_ns=150_000_000,
         plan=THREE.id, policy='b2_boundary',
         role='three-block split at the 150 ms budget'),
)
CELL_BY_LETTER = {c['letter']: c for c in CELLS}
PASS_ORDER = (('A', 'B', 'C', 'D'), ('D', 'C', 'B', 'A'))
RUN = tuple(dict(id='p%d_%s' % (p + 1, CELL_BY_LETTER[letter]['id']),
                 cell=CELL_BY_LETTER[letter]['id'], pass_=p + 1,
                 plan=CELL_BY_LETTER[letter]['plan'],
                 policy=CELL_BY_LETTER[letter]['policy'],
                 period_ns=CELL_BY_LETTER[letter]['period_ns'])
            for p, letters in enumerate(PASS_ORDER) for letter in letters)
SEGMENT_IDS = tuple(entry['id'] for entry in RUN)

INITIAL_SNAPSHOT_BYTES = 25_276_416
BOOTSTRAP_SNAPSHOT_BYTES = 12_638_208
FIXED_BINARY_BYTES = 120_076_776
JSON_CSV_LOG_BYTES = 4_000_000
DISK_SAFETY_FRACTION = 0.10
DISK_ADMISSION_BYTES = 12 * 1024**3


def manifest(period_ns, cycles=CYCLES, phase_ns=PHASE_NS):
    """One frozen trajectory per declared budget; phase moves Experts only."""
    if period_ns not in BUDGETS:
        raise ValueError('undeclared budget: %r' % (period_ns,))
    conf = _manifest(period_ns, cycles, phase_ns)
    conf['schema'] = PROTOCOL
    conf['block_plans'] = {p.id: p.summary() for p in PLANS.values()}
    return conf


_MANIFESTS = {}


def manifests():
    """One canonical manifest object per budget, reused by both conditions."""
    if not _MANIFESTS:
        for ns in BUDGETS:
            _MANIFESTS[ns] = manifest(ns)
    return _MANIFESTS


def budget(cycles=CYCLES, segments=len(RUN)):
    """Exact retention/payload/disk/time projection from the declared layout."""
    layouts = {p.id: retention_layout(cycles, p) for p in PLANS.values()}
    gate_layout = gate_retention_layout(cycles, GATE_PLAN)
    bank = max(v['nbytes'] for v in layouts.values())
    gate_bank = gate_layout['nbytes']
    per_cell = {c['id']: layouts[c['plan']]['nbytes'] for c in CELLS}
    payload = sum(per_cell[entry['cell']] for entry in RUN)
    timeline = sum(entry['period_ns'] for entry in RUN) * cycles / 1e9
    labels = segments + 2          # eight timed segments plus two gates
    initial = labels * INITIAL_SNAPSHOT_BYTES
    bootstrap = labels * BOOTSTRAP_SNAPSHOT_BYTES
    binaries = payload + 2 * gate_bank + initial + bootstrap + FIXED_BINARY_BYTES
    temp = bank + 2_000_000
    subtotal = binaries + JSON_CSV_LOG_BYTES + temp
    estimate = int(subtotal * (1 + DISK_SAFETY_FRACTION))
    return dict(
        layouts={k: dict(count=v['count'], nbytes=v['nbytes']) for k, v in layouts.items()},
        gate_layout=dict(plan=GATE_PLAN.id, count=gate_layout['count'], nbytes=gate_bank),
        per_cell_segment_bytes=per_cell,
        bank_bytes=bank, gate_bank_bytes=gate_bank,
        gpu_and_pinned_bytes=2 * bank,
        batch_payload_bytes=payload,
        gate_payload_bytes=2 * gate_bank,
        disk=dict(
            retention_payload_bytes=payload, gate_payload_bytes=2 * gate_bank,
            initial_snapshot_bytes=initial, bootstrap_snapshot_bytes=bootstrap,
            fixed_binary_bytes=FIXED_BINARY_BYTES, binary_total_bytes=binaries,
            json_csv_log_bytes=JSON_CSV_LOG_BYTES, temp_bytes=temp,
            subtotal_bytes=subtotal, safety_fraction=DISK_SAFETY_FRACTION,
            estimate_bytes=estimate, estimate_gib=round(estimate / 1024**3, 2),
            admission_bytes=DISK_ADMISSION_BYTES, admission_gib=12,
            admission_source=['m3_b10_control.preflight (12*1024**3)',
                              'pi05_m2_clean.prepare via m3_m2_preparation (disk_space_12GiB)'],
            labels=labels,
            note='itemized projection from the same plan layouts and preparation path;'
                 ' the admission threshold is the actual 12 GiB code check'),
        timeline_s=round(timeline, 3),
        segments=segments, cycles=cycles, budgets_ns=list(BUDGETS),
        note='per-segment retention depends on plan and cycle count, not period;'
             ' the timeline is the sum of the eight declared periods')


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
        approval_required='new explicit M3 Expert-reserve validation GPU and five-node scope approval',
        order=list(ORDER), cycles=CYCLES, phase_ns=PHASE_NS,
        budgets_ns=list(BUDGETS), binding=BINDING,
        cells=list(CELLS), run=list(RUN), segment_ids=list(SEGMENT_IDS),
        pass_order=[list(p) for p in PASS_ORDER],
        manifests={str(k): v for k, v in manifests().items()},
        plans={p.id: p.summary() for p in PLANS.values()},
        prediction=dict(
            status=PREDICTION_STATUS, path=PREDICTION_PATH, sha256=PREDICTION_SHA256,
            fingerprint=PREDICTION_FINGERPRINT,
            source='B9 separate 180/140 cost sources + credible_plan_selector_v2; target budgets unmeasured',
            note='pre-run prediction; the timed window neither evaluates nor changes it'),
        selection=dict(
            path=SELECTION_PATH, sha256=SELECTION_SHA256, fingerprint=SELECTION_FINGERPRINT,
            rule=RULE_ID, rule_sha256=RULE_SHA256, reserve_ms=RESERVE_MS,
            costs_sha256=COSTS_SHA256,
            by_budget_ns=SELECTION_BY_PERIOD,
            note='recorded before each segment; it does not change the executed plan'),
        analysis_modules=dict(ANALYSIS_MODULES),
        reserve=dict(
            value_ms=RESERVE_MS, RU_ms=10.0, metric='ME and MU over all source/scenario combinations',
            is_task_book_requirement=False, is_wcet=False, is_validated_safety_bound=False,
            official_deadline_unchanged=True,
            note='reserve shortfall is auxiliary, never an official deadline miss'),
        design=dict(
            lead_ms=10, pressure_workers=0, pressure_mode='quiet',
            questions=['do accepted candidates satisfy official deadlines and Expert/VLM reserves?',
                       'do rejected candidates actually violate their stated reserve criterion?',
                       'how do timing, order and versions compare with the frozen extrapolations?'],
            contrasts=dict(p160='A vs B', p150='C vs D',budget_two='A vs C',budget_three='B vs D'),
            shared_within_budget=['manifest', 'inputs/noise/checkpoint/BF16', 'phase +15 ms',
                                  'lead 10 ms', 'consumption v=floor(id/2)', 'even/odd reservation',
                                  'Context FIFO', 'obligation groups', 'complete work', 'retention path',
                                  'normal Event/Host observation'],
            differs_only_within_budget=['block plan (2 vs 3 legal cuts)'],
            cross_budget_note='160 and 150 ms move releases, deadlines and refresh arrivals; the two'
                              ' budgets are NOT the same wall-clock arrival trace and are paired only'
                              ' inside each budget',
            no_serial_control='this batch has no serial_context cell, so it makes no relative-serial'
                              ' benefit claim',
            limits=['two segments per condition in one process, not independent repeats',
                    'n=4 refreshes per segment; no violation-rate, tail, k_min or final-split claim',
                    '150 ms is a pre-declared reserve challenge point, not a measured feasibility boundary',
                    'no phase scan, interference, pressure worker, graph, partition or concurrency']),
        metrics=dict(
            expert_wait='release -> dispatch decision (Host monotonic_ns)',
            expert_response='release -> completion (GPU Event confirmed, Host upper bound)',
            cycle_response='period release -> all obligations of that cycle complete, including the'
                           ' same complete VLM obligation group',
            refresh_ready='refresh release -> full KV publish (wall clock, cross-cycle waits included)',
            refresh_response='publish_time - refresh_release; completion offset is relative to segment t0',
            obligations='violations/denominator, W assigned/completed, backlog, version waits,'
                        ' incomplete, uncertain',
            kernels='Event envelopes include submission gaps and instrumentation; never pure kernel time',
            host_vs_gpu='Host decision time, completion confirmation and publish bounds are separate',
            aligned_scope='two-block B1 = P+B1 of the three-block plan; sequential keys B1/B2/B3 are'
                          ' not mathematical names'),
        work=dict(batch=dict(work, total_C=total_c, total_E=total_e,
                             note='complete model work: %d Contextes and %d Expert10, including two'
                                  ' discarded warm-ups and the 1+1 D1 original pipeline' % (total_c, total_e)),
                  observed_ledger=dict(contexts=obs_c, experts=obs_e, encoder_layers=obs_c * 18,
                                       decoder_layers=obs_e * 180, language=obs_c, vision27=obs_c,
                                       rows=obs_c * 20 + obs_e * 180,
                                       excluded=['warmup_C=2 (outside the ledger by design)',
                                                 'D1 original run_pipeline 1C+1E (bypasses the wrappers)'],
                                       note='each observed Context is one complete 18-layer VLM obligation set'),
                  autotune_requests=36, autotune_separate=True),
        retention=b,
        gates=dict(old_reader=dict(journal_entries=22, segment_id='gate_old_reader'),
                   interrupt=dict(journal_entries=24, segment_id='gate_interrupt'),
                   plan=GATE_PLAN.id,
                   verification='exact journal content and order; not a length check'),
        compatibility=dict(
            identity='new independent protocol; legacy protocol ids are not rewritten',
            math='same frozen m2_pi05_ops block bodies; same CONTROL/THREE plan definitions',
            inputs='same fixed fixture, checkpoint, BF16 precision, images, wrist, state, language, noise',
            version='same v=floor(Expert.id/2) consumption and even/odd reservation',
            obligations='same per-plan obligation groups and complete work',
            retention='same per-plan retention layouts for 8 cycles; D2D cost retained',
            timing='same Host completion bounds and Event envelopes; fixed releases from each manifest',
            extrapolation_variable='new process / new trajectories; costs are frozen B9 180/140 source scenarios',
            cost_source='B9 own operations per cell; sources never pooled',
            selection='the frozen v2 recommendation is recorded per segment and never changes the plan',
            disclosed_differences=['two plans are exercised at both budgets', 'no serial_context cell',
                                   'normal Event/Host observation only; no B7 22-point diagnostics',
                                   'no 4 s lead, no pressure worker, no graph/partition/concurrency'],
            not_claimed='this batch does not assume the numeric configuration or observation protocol'
                        ' are unchanged; if they differ, the selector domain is INSUFFICIENT_EVIDENCE'
                        ' and the prediction comparison is CONDITION_MISMATCH'),
        fairness=dict(same_budget_pairs=[['A', 'B'], ['C', 'D']],
                      same_plan_across_budgets=[['A', 'C'], ['B', 'D']],
                      same_phase=True, same_binding=True, same_obligations=True,
                      same_complete_work=True, same_retention_rule=True,
                      cross_budget_not_matched=True, no_serial_control=True),
        limits=dict(model_processes=1, timeout_s=180, grace_s=10, internal_s=170,
                    scope_count=1, scope_max_s=420, retries=0, new_work_segments=0,
                    pressure_workers=0, profiler=False),
        scope=dict(nodes=5,
                   apply=['cpu policy0/4/8 min_freq=2201600', 'gpu min_freq=1300500000',
                          'emc min_freq=3199000000'],
                   snapshot='real per-batch clock_before.json (root 0600)',
                   restore='descendant cleanup first, reverse restore, independent uid1001 readback',
                   limits='max/governor/power/fan/thermal unchanged'),
        stop=['internal 170 s', 'external 180 s + 10 s grace', 'thermal >=80 C',
              'disk <12 GiB', 'five-node deviation or missing EMC read',
              'retention/evidence failure', 'D2H/compare/write inside a timed window',
              'CUDA error', 'address table change', 'assembly/prefix reference mismatch',
              'gate journal mismatch', 'ledger/protocol/segment id mismatch'],
        stop_note='performance violation, backlog, prediction miss or empirical-envelope exceedance'
                  ' is NOT a stop or retry reason; only correctness/resource/time safety stops the batch',
        raw=['result.json', 'per-segment RETENTION.bin + RETENTION_INDEX.json',
             'call ledger', 'decisions/arrivals/progress', 'autotune logs', 'scope telemetry'],
        recovery='frozen v6 five-node SnapshotTransaction apply/restore; no service left,'
                 ' ordinary-user independent readback',
        no_performance_or_k_min_claim=True,
        calibration_use='finite Expert-reserve validation batch; not a paper baseline, tail estimate,'
                        ' violation-rate claim, k_min measurement or final-split decision')
