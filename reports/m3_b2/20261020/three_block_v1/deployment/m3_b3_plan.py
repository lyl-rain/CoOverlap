"""M3 three-block candidate: legal blocks, publish state, retention and obligations.

CPU-safe: no Torch/CUDA import. Model math is the frozen ``m2_pi05_ops`` bodies;
this module only declares where the legal execution cut is, which state each cut
produces, and how that state is retained/compared. The existing two-block plan is
kept as the control and compatibility path.

State semantics (must not be conflated):
  after block P (language+Vision27+norm/project/bias): effective NEW KV layers = 0
      -> x holds the projected 561x2048 inputs; enc_K/enc_V still hold the
         previous generation (or are unwritten) and are NOT valid new KV.
  after block 1 (Encoder 0-8): effective NEW KV layers = 9
  after block 2 (Encoder 9-17): effective NEW KV layers = 18  -> publishable

Publication is refused unless all plan blocks have completed with fresh
completion events AND the effective new-KV layer count is 18.
"""
from m2_executor import DEFAULT_PLAN, PREFIX, BlockPlan, replay_manifest
from m2_clean_core import gate_retention_layout, retention_layout

PROTOCOL = 'm3_b3_three_block_v1'
CYCLES = 4
PERIOD_NS = 240_000_000
# One pre-declared phase, identical for both candidates. Expert releases sit
# PHASE_NS after the period clock so that a release lands inside the first VLM
# block instead of in idle time. Deadlines keep the same relative budget
# (deadline - release = P); refresh releases are unchanged.
PHASE_NS = 15_000_000
ORDER = ('control_two_9_9', 'three_prefix_9_9')
BINDING = ('planned v=floor(Expert.id/2); at first dispatch of even Expert, bind that Expert '
           'and reserve its odd partner to the SAME published v; reservation is ownership only, '
           'never early execution; unavailable v waits; identical for both candidates')

CONTROL = DEFAULT_PLAN
THREE = BlockPlan('three_prefix_9_9',
                  (PREFIX, tuple(range(0, 9)), tuple(range(9, 18))),
                  (0, 9, 18), ('prefix', 'mid', 'full'), ('P', 'B1', 'B2'),
                  ((0, 1), (2,)))
PLANS = {p.id: p for p in (CONTROL, THREE)}
CANDIDATES = (dict(id='C0_control_two_9_9', plan=CONTROL.id, policy='b2_boundary',
                   decision_boundaries=['stage_complete', 'block1_complete', 'Context_complete'],
                   isolates='control for the split: same policy, same arrivals/budget/work'),
              dict(id='C1_three_prefix_9_9', plan=THREE.id, policy='b2_boundary',
                   decision_boundaries=['stage_complete', 'prefix_complete', 'block1_complete',
                                        'Context_complete'],
                   isolates='the split only: one extra legal decision boundary after the prefix'))


def manifest(period_ns=PERIOD_NS, cycles=CYCLES, phase_ns=PHASE_NS):
    conf = replay_manifest(period_ns, cycles)
    if phase_ns < 0 or phase_ns >= period_ns:
        raise ValueError('declared phase must stay inside one period')
    for e in conf['experts']:
        if e['deadline_ns']-e['release_ns'] != period_ns:
            raise ValueError('expert relative deadline changed')
        e['release_ns'] += phase_ns
        e['deadline_ns'] += phase_ns
    conf.update(schema=PROTOCOL, binding=BINDING, phase_ns=phase_ns,
                block_plans={p.id: p.summary() for p in (CONTROL, THREE)})
    return conf


def budget(cycles=CYCLES):
    """Exact per-candidate retention and the shared bank capacity."""
    layouts = {p.id: retention_layout(cycles, p) for p in (CONTROL, THREE)}
    gates = {p.id: gate_retention_layout(cycles, p) for p in (CONTROL, THREE)}
    bank = max(v['nbytes'] for v in layouts.values())
    gate_bank = max(v['nbytes'] for v in gates.values())
    return dict(layouts={k: dict(count=v['count'], nbytes=v['nbytes']) for k, v in layouts.items()},
                gate_layouts={k: dict(count=v['count'], nbytes=v['nbytes']) for k, v in gates.items()},
                bank_bytes=bank, gate_bank_bytes=gate_bank,
                timed_payload_bytes=sum(v['nbytes'] for v in layouts.values()),
                gate_payload_bytes=2*gate_bank,
                gpu_and_pinned_bytes=2*bank)


def protocol():
    b = budget()
    return dict(
        id=PROTOCOL, status='PREPARED',
        approval_required='new explicit M3 three-block GPU and five-node scope approval',
        order=list(ORDER), manifest=manifest(), binding=BINDING,
        candidates=list(CANDIDATES),
        plans={p.id: p.summary() for p in (CONTROL, THREE)},
        phase=dict(ns=PHASE_NS, applies_to='Expert releases only; identical for both candidates',
                   rationale='place one release inside the first VLM block so boundary priority is '
                             'driven by the real clock, not by manual call order',
                   refresh_releases='unchanged relative to t0',
                   deadline='release + P for every Expert; refresh deadline = release + 2P'),
        policy='single stream, queue depth 1, real completion fence, FIFO Context, '
               'boundary Expert priority, never preempt a running block, never reset arrivals',
        splits=dict(isolates_split='C1 - C0 (same policy/arrivals/budget/work, one extra legal cut)',
                    isolates_priority='reused from boundary_profile_v1 (C0 serial_context vs C1 9+9); '
                                      'not re-measured in this batch'),
        work=dict(warmup_C=2, reference_C=2, reference_E=2, D1_C=1, D1_E=1,
                  prefix_reference_C=2, assembly_C=1, assembly_E=1,
                  old_reader_gate_C=2, old_reader_gate_E=1,
                  interrupt_gate_C=2, interrupt_gate_E=1,
                  segment_bootstrap_C=2, timed_C=4, timed_E=8,
                  total_C=18, total_E=14, observed_C=15, observed_E=13,
                  encoder_layers=15*18, decoder_layers=13*180, vision_layers=15*27,
                  language=15, observed_ledger_rows=15*20+13*180,
                  autotune_requests=36, autotune_separate=True),
        retention=b,
        limits=dict(model_processes=1, timeout_s=180, grace_s=10, internal_s=170,
                    scope_count=1, scope_max_s=420, retries=0, new_work_segments=0),
        clock=dict(release_and_deadline='Host monotonic_ns at the fixed period clock',
                   gpu_math='CUDA Event envelopes inside an operation only',
                   completion='Host lower/upper bounds from fresh tail-Event queries',
                   forbidden='Host timestamps are never used as GPU durations'),
        stop=['internal 170s', 'external 180s + 10s grace', 'thermal >=80C',
              'tail Event not ready (TimeoutError, keep INCOMPLETE)',
              'retention capacity/evidence failure', 'any uninstrumented D2H in a timed window'],
        raw=['result.json', 'per-gate/segment RETENTION.bin + RETENTION_INDEX.json',
             'call ledger', 'decisions/arrivals/progress', 'autotune logs',
             'scope telemetry + hardware samples'],
        recovery='reuse frozen v6 five-node SnapshotTransaction apply/restore with independent '
                 'uid1001 readback; no service left, no permanent change',
        scope='one five-node scope (CPU policies 0/4/8, GPU min, EMC min) at the already '
              'validated maxima, <=420s',
        numerical='D1 same-process byte exact admission; frozen cross-process thresholds '
                  '0.015625/0.01 report only; prefix boundary gets its own same-process reference',
        no_performance_or_k_min_claim=True,
        calibration_use='4 cycles / 2 refreshes per candidate is a coverage diagnostic, '
                        'not a tail, k_min or net-benefit sample')
