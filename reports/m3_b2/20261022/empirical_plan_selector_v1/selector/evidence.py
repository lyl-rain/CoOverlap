"""Evidence extraction for the empirical plan selector.

Only pass 1 of B4 is used to build costs.  Pass 2 is never read by
``extract_training`` and is used only by the freeze-first validation step.
Costs are operation Event totals; no layer division and no report-mean copying.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[5]
B4 = PROJECT / 'reports/m3_b2/20261021/split_priority_ablation_v1_r2'
B4_RESULT = B4 / 'gpu_run_01/board/run_01/model/result.json'
B4_CONFIG = B4 / 'deployment/CONFIG.json'
B5_RESULT = PROJECT / 'reports/m3_b2/20261021/boundary_budget_anchors_v1_r1/gpu_run_01/board/run_01/model/result.json'
B6_RESULT = PROJECT / 'reports/m3_b2/20261021/controlled_interference_b6_v1_r1/gpu_run_01/board/run_01/model/result.json'
B7_RESULT = PROJECT / 'reports/m3_b2/20261021/stage_startup_b7_v1/gpu_run_01/board/run_01/model/result.json'
B7_CORRECTION = PROJECT / 'reports/m3_b2/20261021/stage_startup_b7_v1/corrections/output/B7_STAGE_INTERVALS.json'
MODEL = Path(__file__).resolve().parent / 'plan_model.py'
MODEL_ENV = Path(__file__).resolve().parent / 'model_env.py'
COST_BLOCKS = {
    'two_9_9': (('B1', 'R{q}/B1'), ('B2', 'R{q}/B2')),
    'three_prefix_9_9': (('P', 'R{q}/B1'), ('B1', 'R{q}/B2'), ('B2', 'R{q}/B3')),
}
B4_CANDIDATE_CELLS = {'two_9_9': 'B_two_b2_boundary',
                      'three_prefix_9_9': 'D_three_b2_boundary'}
B4_SERIAL_CELLS = {'two_9_9': 'A_two_serial_context',
                   'three_prefix_9_9': 'C_three_serial_context'}
MODEL_CONSTANTS = dict(gap_ms=0.041, publish_cost_ms=0.012,
                       source='plan_feasibility_v1_r1/plan_model.py defaults',
                       note='existing analysis model constants; not fitted to validation')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def condition(segment):
    m = segment['manifest']
    return dict(period_ms=m['period_ns'] / 1e6, phase_ms=m['phase_ns'] / 1e6,
                cycles=m['cycles'], plan=segment['plan'], policy=segment['policy'],
                configuration='quiet; no pressure worker; B4 default t0=+10 ms; 8 cycles/4 refreshes',
                lead_ns=10_000_000, lead_source='m3_b2_core.run_segment default when window is absent',
                host_clock='Host monotonic completion confirmation upper',
                event_clock='operation GPU_total_envelope_ms (CUDA Event; not pure kernel)')


def cost_rows(segment):
    ops = {o['key']: o for o in segment['operations']}
    rows = []
    for q in range(segment['manifest']['cycles'] // 2):
        for label, template in COST_BLOCKS[segment['plan']]:
            key = template.format(q=q)
            o = ops.get(key)
            if o is None:
                raise ValueError('missing block operation %s in %s' % (key, segment['segment_id']))
            rows.append(dict(segment_id=segment['segment_id'], cell=segment['cell'],
                             pass_=segment['pass_'], plan=segment['plan'],
                             policy=segment['policy'], job_type='ContextBlock',
                             job_key='R%d/%s' % (q, label), refresh=q, block=label,
                             ms=float(o['GPU_total_envelope_ms']),
                             source='operation.GPU_total_envelope_ms'))
    for j in range(segment['manifest']['cycles']):
        key = 'E%d' % j
        o = ops.get(key)
        if o is None:
            raise ValueError('missing Expert operation %s in %s' % (key, segment['segment_id']))
        rows.append(dict(segment_id=segment['segment_id'], cell=segment['cell'],
                         pass_=segment['pass_'], plan=segment['plan'],
                         policy=segment['policy'], job_type='Expert',
                         job_key=key, expert=j, ms=float(o['GPU_total_envelope_ms']),
                         source='operation.GPU_total_envelope_ms'))
    stages = {x['stage_index']: x for x in (segment.get('stage_observation') or {}).get('stages', [])}
    for q in range(segment['manifest']['cycles'] // 2):
        key = 'R%d/stage' % q
        o = ops.get(key)
        if o is None:
            raise ValueError('missing stage operation %s in %s' % (key, segment['segment_id']))
        if q in stages:
            ts = stages[q]['timestamps']
            host_ms = (ts['stage_exit'] - ts['stage_enter']) / 1e6
            clock = 'Host stage observer entry->exit'
        else:
            dec = next((d for d in segment.get('decisions', [])
                        if d.get('kind') == 'stage' and d.get('id') == q), None)
            if dec is None:
                raise ValueError('missing stage decision %s in %s' % (key, segment['segment_id']))
            host_ms = (o['lower_ns'] - dec['host_ns']) / 1e6
            clock = 'Host decision->completion lower'
        rows.append(dict(segment_id=segment['segment_id'], cell=segment['cell'],
                         pass_=segment['pass_'], plan=segment['plan'],
                         policy=segment['policy'], job_type='Stage', job_key=key,
                         refresh=q, stage_first=(q == 0), ms=host_ms,
                         event_ms=float(o['GPU_total_envelope_ms']), host_clock=clock,
                         source='stage Host interval; Event separately'))
    return rows


def summarize(rows):
    by = {}
    for r in rows:
        by.setdefault((r['job_type'], r.get('block', r.get('stage_first'))), []).append(r['ms'])
    out = {}
    for key, values in sorted(by.items(), key=lambda kv: str(kv[0])):
        typ, label = key
        name = ('stage_first' if label is True else 'stage_later' if label is False else str(label))
        out['%s:%s' % (typ, name)] = dict(values=len(values), median=round(statistics.median(values), 6),
                                          max=round(max(values), 6), min=round(min(values), 6))
    return out


def extract_training(data=None):
    data = load(B4_RESULT) if data is None else data
    training = {}; serial = {}
    for plan in ('two_9_9', 'three_prefix_9_9'):
        seg = next(s for s in data['segments'] if s['pass_'] == 1
                   and s['cell'] == B4_CANDIDATE_CELLS[plan])
        rows = cost_rows(seg)
        training[plan] = dict(segment_id=seg['segment_id'], cell=seg['cell'], policy=seg['policy'],
                              condition=condition(seg), rows=rows, summary=summarize(rows))
        cseg = next(s for s in data['segments'] if s['pass_'] == 1
                    and s['cell'] == B4_SERIAL_CELLS[plan])
        serial[plan] = dict(segment_id=cseg['segment_id'], cell=cseg['cell'],
                            policy=cseg['policy'], rows=cost_rows(cseg), summary=summarize(cost_rows(cseg)))
    return training, serial


def scenario_from_rows(rows):
    """Scenario: median or max per corresponding cost dimension (no multiplier)."""
    out = {}
    for plan in ('two_9_9', 'three_prefix_9_9'):
        r = [x for x in rows if x['plan'] == plan]
        if not r:
            continue
        blocks = {}
        for label, _ in COST_BLOCKS[plan]:
            vals = [x['ms'] for x in r if x['job_type'] == 'ContextBlock' and x.get('block') == label]
            if not vals:
                raise ValueError('no training block costs for %s/%s' % (plan, label))
            blocks[label] = dict(n=len(vals), median=statistics.median(vals), max=max(vals))
        experts = [x['ms'] for x in r if x['job_type'] == 'Expert']
        first = [x['ms'] for x in r if x['job_type'] == 'Stage' and x.get('stage_first') is True]
        later = [x['ms'] for x in r if x['job_type'] == 'Stage' and x.get('stage_first') is False]
        if not experts or not first or not later:
            raise ValueError('incomplete training costs for %s' % plan)
        out[plan] = dict(
            blocks=blocks, expert=dict(n=len(experts), median=statistics.median(experts), max=max(experts)),
            stage=dict(first=dict(n=len(first), median=statistics.median(first), max=max(first)),
                       later=dict(n=len(later), median=statistics.median(later), max=max(later))))
    return out


def make_train_costs(training):
    all_rows = []
    for plan, block in training.items():
        all_rows.extend(block['rows'])
    scenarios = scenario_from_rows(all_rows)
    # Candidate-specific medians/maxima only: do not mix the other plan or serial cells.
    candidate = {}
    for plan, block in training.items():
        candidate[plan] = scenario_from_rows(block['rows'])[plan]
    return dict(
        schema='m3_b7_empirical_plan_selector_train_costs_v1',
        source=dict(result=str(B4_RESULT), result_sha256=sha(B4_RESULT),
                    config=str(B4_CONFIG), config_sha256=sha(B4_CONFIG),
                    model=str(MODEL), model_sha256=sha(MODEL),
                    executor=str((Path(__file__).resolve().parent / 'model_env.py')),
                    executor_sha256=sha(PROJECT / 'reports/m3_b2/20261021/split_priority_ablation_v1_r2/deployment/m2_executor.py')),
        split=dict(training='B4 pass 1', validation='B4 pass 2 (not read by this function)',
                   fixed_by='original execution order; not chosen by outcome'),
        condition=condition(next(s for s in load(B4_RESULT)['segments'] if s['pass_'] == 1
                                        and s['cell'] == B4_CANDIDATE_CELLS['two_9_9'])),
        candidate_cells=B4_CANDIDATE_CELLS,
        candidates=candidate, serial_comparison=scenario_from_rows([x for plan in training for x in training[plan]['rows'] if plan == plan]),
        raw_rows=all_rows, model_constants=MODEL_CONSTANTS,
        notes=['Block/Expert/stage are operation Event totals; layers are not divided.',
               'B4 pass 1 only is used for these costs.',
               'Stress is the per-dimension maximum of training samples; it is not a formal upper bound.',
               'Stage first and later are separate; startup is not subtracted or added twice.'])


def catalog():
    def meta(path, condition):
        return dict(path=str(path), sha256=sha(path), condition=condition)
    return dict(
        schema='m3_b2_empirical_plan_selector_evidence_catalog_v1',
        primary=dict(batch='split_priority_ablation_v1_r2', result=str(B4_RESULT), result_sha256=sha(B4_RESULT),
                     config=str(B4_CONFIG), config_sha256=sha(B4_CONFIG),
                     condition='P=240 ms, phase=+15 ms, quiet, 8 cycles/4 refreshes, B4 default 10 ms lead',
                     sample=dict(training='pass1 B/D: 8 Expert + 8 block ops (two) / 12 block ops (three) + 4 stages',
                                 validation='pass2 D/B: same counts, not used for costs')),
        supplemental=[
            dict(batch='boundary_budget_anchors_v1_r1', result=str(B5_RESULT), sha256=sha(B5_RESULT),
                 condition='P=180/240; C/D 180 two_9_9; no three plan; quiet; no worker',
                 use='applicability only; not mixed into B4 cost distribution'),
            dict(batch='controlled_interference_b6_v1_r1', result=str(B6_RESULT), sha256=sha(B6_RESULT),
                 condition='P=180; four conditions; two_9_9; quiet/fixed; 4 s leads; 8 seg',
                 use='applicability/limit: startup and fixed conditions differ'),
            dict(batch='stage_startup_b7_v1', result=str(B7_RESULT), sha256=sha(B7_RESULT),
                 condition='P=180; two_9_9; quiet; A=10 ms/B=4 s leads; 4 seg',
                 use='startup applicability only; B7 first-stage Event0 localization is B7-only'),
            dict(batch='stage_startup_b7_v1 corrections', result=str(B7_CORRECTION), sha256=sha(B7_CORRECTION),
                 condition='16 stage Host intervals; B7-only',
                 use='observable Event0 localization; not a B6 direct measurement and not a cost mix'),
        ],
        observations=[
            'B4 is the only batch with both two_9_9 and three_prefix_9_9 at the same P=240 condition.',
            'B5/B6/B7 contain two_9_9 only; they cannot supply three-plan 180 ms evidence.',
            'B4, B5, B6 and B7 differ in budget/lead/observation/pressure; costs are not pooled.',
            'B7 Event0 Host share is a diagnostic interval, not added to B4 block or stage costs.',
        ],
        model=dict(path=str(MODEL), sha256=sha(MODEL), env=str(MODEL_ENV), env_sha256=sha(MODEL_ENV),
                   executor=str(PROJECT / 'reports/m3_b2/20261021/split_priority_ablation_v1_r2/deployment/m2_executor.py'),
                   executor_sha256=sha(PROJECT / 'reports/m3_b2/20261021/split_priority_ablation_v1_r2/deployment/m2_executor.py')),
        model_constants=MODEL_CONSTANTS,
    )
