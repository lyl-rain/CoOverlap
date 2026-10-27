"""Evidence extraction and structured condition for the empirical plan selector.

Only pass 1 of B4 is used to build costs.  Pass 2 is never read by
``extract_training`` and is used only by the retrospective validation step.
Costs are operation Event totals; no layer division and no report-mean copying.

The condition is built from the actual B4 result and the frozen deployment
sources.  Fields that the result does not record are marked ``UNKNOWN`` rather
than inferred from a prose description.
"""
from __future__ import annotations

import hashlib
import json
import re
import statistics
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[5]
B4 = PROJECT / 'reports/m3_b2/20261021/split_priority_ablation_v1_r2'
B4_RESULT = B4 / 'gpu_run_01/board/run_01/model/result.json'
B4_CONFIG = B4 / 'deployment/CONFIG.json'
B4_CORE = B4 / 'deployment/m3_b2_core.py'
B4_GPU_PLAN = B4 / 'GPU_PLAN.md'
B4_CHECKPOINT_MANIFEST = B4 / 'deployment/reference/SOURCE_CHECKPOINT_SHA256.json'
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


def canonical_sha(value):
    """Stable fingerprint of a JSON-compatible value."""
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def _condition_unknown(reason, **extra):
    out = dict(lead_ms='UNKNOWN', reason=reason)
    out.update(extra)
    return out


def _lead_condition(data):
    """Startup lead: declared by the frozen B4 run_segment source.

    The result does not record a lead field.  The frozen source sets
    ``t0 = clock() + 10_000_000``, and the result's source fingerprint ties that
    file to the executed deployment.  The per-segment ``t0 - first decision``
    gap is only an observation check, not the declared value.
    """
    prints = data.get('source_config_fingerprints') or {}
    expected = prints.get('m3_b2_core.py')
    if not B4_CORE.exists():
        return _condition_unknown('m3_b2_core.py is not available')
    actual = sha(B4_CORE)
    if not expected or actual != expected:
        return _condition_unknown('m3_b2_core.py SHA differs from the result fingerprint',
                                  source=str(B4_CORE), source_sha256=actual)
    match = re.search(r't0\s*=\s*clock\(\)\s*\+\s*([0-9_]+)', B4_CORE.read_text())
    if not match:
        return _condition_unknown('lead constant not found in m3_b2_core.py',
                                  source=str(B4_CORE), source_sha256=actual)
    lead_ns = int(match.group(1).replace('_', ''))
    return dict(lead_ms=round(lead_ns / 1e6, 6), lead_ns=lead_ns,
                source=str(B4_CORE), source_sha256=actual,
                basis='frozen B4 m3_b2_core.run_segment: t0 = clock() + constant',
                note='declared startup lead; no per-segment value is substituted')


def _pressure_condition():
    """Pressure condition: B4 declares no interference; runtime count is absent."""
    if not B4_GPU_PLAN.exists():
        return dict(mode='UNKNOWN', worker_processes='UNKNOWN', runtime_audit='UNKNOWN',
                    reason='B4 GPU_PLAN.md is not available')
    text = B4_GPU_PLAN.read_text()
    declared = ('干扰' in text and '不新增' in text)
    if not declared:
        return dict(mode='UNKNOWN', worker_processes='UNKNOWN', runtime_audit='UNKNOWN',
                    source=str(B4_GPU_PLAN), source_sha256=sha(B4_GPU_PLAN),
                    reason='no-interference declaration not found in B4 GPU_PLAN.md')
    return dict(mode='quiet',
                worker_processes='UNKNOWN',
                runtime_audit='UNKNOWN',
                source=str(B4_GPU_PLAN), source_sha256=sha(B4_GPU_PLAN),
                basis='B4 GPU_PLAN excludes interference; result.json has no pressure/worker field',
                limitation='declared batch condition, not a runtime process-count audit')


def _configuration_condition(data, segment):
    """Numeric configuration read from the actual result, plus its fingerprints."""
    manifest = segment['manifest']
    prints = data.get('source_config_fingerprints') or {}
    keys = ('m2_executor.py', 'm3_b2_core.py', 'reference/SOURCE_CHECKPOINT_SHA256.json')
    body = dict(
        numeric=dict(
            period_ns=manifest['period_ns'],
            phase_ns=manifest['phase_ns'],
            cycles=manifest['cycles'],
            work=manifest['work'],
            expert_steps=sorted({int(e['steps']) for e in manifest['experts']}),
            expert_layers=sorted({int(e['layers']) for e in manifest['experts']}),
            retention_capacity_B=segment.get('retention_capacity_B', 'UNKNOWN'),
        ),
        config_sha256=data.get('config_sha256', 'UNKNOWN'),
        source_fingerprints={key: prints.get(key, 'UNKNOWN') for key in keys},
        source='result.manifest + result.config_sha256 + result.source_config_fingerprints',
    )
    body['fingerprint'] = canonical_sha(body)
    return body


def _checkpoint_condition(data):
    prints = data.get('source_config_fingerprints') or {}
    manifest_sha = prints.get('reference/SOURCE_CHECKPOINT_SHA256.json', 'UNKNOWN')
    model_sha = 'UNKNOWN'
    if (manifest_sha != 'UNKNOWN' and B4_CHECKPOINT_MANIFEST.exists()
            and sha(B4_CHECKPOINT_MANIFEST) == manifest_sha):
        try:
            checkpoint = json.loads(B4_CHECKPOINT_MANIFEST.read_text())
            keys = sorted(k for k in checkpoint if k.endswith('/model.safetensors'))
            if len(keys) == 1:
                model_sha = checkpoint[keys[0]]
        except (OSError, ValueError):
            pass
    return dict(checksum_manifest_sha256=manifest_sha,
                model_safetensors_sha256=model_sha,
                source='result.source_config_fingerprints + deployment/reference/SOURCE_CHECKPOINT_SHA256.json')


def _input_condition(data, segment):
    manifest = segment['manifest']
    snapshots = data.get('snapshots') or 'UNKNOWN'
    body = dict(
        snapshots=snapshots,
        precision=manifest.get('work', {}).get('precision', 'UNKNOWN'),
        checkpoint=_checkpoint_condition(data),
        source='result.snapshots + result.manifest.work.precision + checkpoint checksum manifest',
    )
    body['fingerprint'] = canonical_sha(body)
    return body


def _version_condition(segment):
    manifest = segment['manifest']
    journal = segment.get('journal') or []
    binds = {row[1]: row[2] for row in journal
             if len(row) >= 3 and row[0] == 'bind'}
    # Journal 'begin' rows are (kind, version, slot, generation, snapshot).
    # The first begin is the pre-window bootstrap; the following rows are the
    # declared refreshes in order.  Do not read row[1] as a refresh id.
    begin_versions = [row[1] for row in journal if len(row) >= 3 and row[0] == 'begin']
    planned_experts = {'E%d' % e['id']: e['version'] for e in manifest['experts']}
    planned_refreshes = {str(r['id']): r['version'] for r in manifest['refreshes']}
    observed_refreshes = {str(i): v for i, v in enumerate(begin_versions[1:])}
    body = dict(
        binding=manifest.get('binding', 'UNKNOWN'),
        bootstrap_version=(begin_versions[0] if begin_versions else 'UNKNOWN'),
        planned_expert_versions=planned_experts,
        planned_refresh_versions=planned_refreshes,
        observed_expert_versions=binds,
        observed_refresh_versions=observed_refreshes,
        consistent=(binds == planned_experts and observed_refreshes == planned_refreshes),
        source='manifest binding/versions + segment.journal',
    )
    body['fingerprint'] = canonical_sha(body)
    return body


def _obligation_condition(segment):
    manifest = segment['manifest']
    plan = segment['plan']
    block_plan = manifest['block_plans'][plan]
    groups = block_plan['groups']
    declared_units = len(groups) * (manifest['cycles'] // 2)
    stats = segment.get('statistics') or {}
    observed_units = sorted(segment.get('units') or {})
    body = dict(
        groups=groups,
        kinds=block_plan['kinds'],
        valid_layers=block_plan['valid_layers'],
        declared_units=declared_units,
        statistics_units_are_declared_groups=stats.get('units_are_declared_groups', 'UNKNOWN'),
        observed_unit_count=len(observed_units),
        consistent=(stats.get('units_are_declared_groups') == groups
                    and len(observed_units) == declared_units),
        source='manifest.block_plans[plan] + segment.statistics.units_are_declared_groups + segment.units',
    )
    body['fingerprint'] = canonical_sha(body)
    return body


def _retention_condition(data, segment):
    validation = segment.get('validation') or {}
    retention_memory = data.get('retention_memory') or {}
    body = dict(
        capacity_B=segment.get('retention_capacity_B', 'UNKNOWN'),
        bank_bytes=retention_memory.get('bank_bytes', 'UNKNOWN'),
        all_job_actions_exact=validation.get('all_job_actions_exact', 'UNKNOWN'),
        source='segment.retention_capacity_B + result.retention_memory.bank_bytes + segment.validation',
    )
    body['fingerprint'] = canonical_sha(body)
    return body


def _candidate_retention(segment):
    validation = segment.get('validation') or {}
    body = dict(
        records=validation.get('records', 'UNKNOWN'),
        payload_B=validation.get('payload_B', 'UNKNOWN'),
        expert_outputs=validation.get('expert_outputs', 'UNKNOWN'),
        refreshes=validation.get('refreshes', 'UNKNOWN'),
        index_recorded=bool(validation.get('index')),
        source='segment.validation',
    )
    body['fingerprint'] = canonical_sha(body)
    return body


def _observation_condition(data, segment):
    stats = segment.get('statistics') or {}
    body = dict(
        mode=segment.get('observation_mode', 'UNKNOWN'),
        top_level_mode=data.get('observation_mode', 'UNKNOWN'),
        stage_observation=bool(segment.get('stage_observation')),
        quantile_method=stats.get('quantile_method', 'UNKNOWN'),
        source='segment.observation_mode + result.observation_mode + segment.statistics.quantile_method',
    )
    body['fingerprint'] = canonical_sha(body)
    return body


def _hardware_condition(data):
    limits = data.get('initial_clock_limits') or []
    clocks = {x['name']: x.get('target') for x in limits
              if isinstance(x, dict) and x.get('name')}
    body = dict(
        clock_limits=clocks,
        device='UNKNOWN',
        temperature='UNKNOWN',
        source='result.initial_clock_limits',
        limitation='device model and temperature are not recorded in result.json',
    )
    body['fingerprint'] = canonical_sha(body)
    return body


def condition_from_segment(data, segment):
    """Shared condition for one B4 candidate segment.

    Plan-specific retention counts and obligation groups are in
    ``candidate_condition``; everything here must agree across the two
    pass-1 candidate cells for the costs to be evidence for one condition.
    """
    manifest = segment['manifest']
    body = dict(
        period_ms=round(manifest['period_ns'] / 1e6, 6),
        phase_ms=round(manifest['phase_ns'] / 1e6, 6),
        cycles=manifest['cycles'],
        policy=segment['policy'],
        protocol=segment.get('protocol', 'UNKNOWN'),
        lead=_lead_condition(data),
        pressure=_pressure_condition(),
        configuration=_configuration_condition(data, segment),
        input=_input_condition(data, segment),
        version_consumption=_version_condition(segment),
        retention=_retention_condition(data, segment),
        observation=_observation_condition(data, segment),
        hardware=_hardware_condition(data),
    )
    body['fingerprint'] = canonical_sha(body)
    return body


def candidate_condition(data, segment):
    manifest = segment['manifest']
    plan = segment['plan']
    block_plan = manifest['block_plans'][plan]
    layout = dict(blocks=block_plan['blocks'], groups=block_plan['groups'],
                  valid_layers=block_plan['valid_layers'],
                  kinds=block_plan['kinds'], shapes=block_plan.get('shapes'))
    body = dict(
        plan=plan,
        policy=segment['policy'],
        segment_id=segment['segment_id'],
        cell=segment['cell'],
        pass_=segment['pass_'],
        layout=layout,
        layout_fingerprint=canonical_sha(layout),
        obligation_groups=_obligation_condition(segment),
        retention_observed=_candidate_retention(segment),
    )
    body['fingerprint'] = canonical_sha(body)
    return body


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
                              condition=condition_from_segment(data, seg),
                              candidate_condition=candidate_condition(data, seg),
                              rows=rows, summary=summarize(rows))
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
    shared = training['two_9_9']['condition']
    for plan, block in training.items():
        if block['condition'] != shared:
            diff = sorted(k for k in set(shared) | set(block['condition'])
                          if shared.get(k) != block['condition'].get(k))
            raise ValueError('shared condition differs for %s: %s' % (plan, diff))
    # Candidate-specific medians/maxima only: do not mix the other plan or serial cells.
    candidate = {}
    for plan, block in training.items():
        candidate[plan] = scenario_from_rows(block['rows'])[plan]
        candidate[plan]['condition'] = block['candidate_condition']
    return dict(
        schema='m3_b2_empirical_plan_selector_train_costs_v1_r1',
        source=dict(result=str(B4_RESULT), result_sha256=sha(B4_RESULT),
                    config=str(B4_CONFIG), config_sha256=sha(B4_CONFIG),
                    model=str(MODEL), model_sha256=sha(MODEL),
                    executor=str(PROJECT / 'reports/m3_b2/20261021/split_priority_ablation_v1_r2/deployment/m2_executor.py')),
        split=dict(training='B4 pass 1', validation='B4 pass 2 (not read by this function)',
                   fixed_by='original execution order; not chosen by outcome'),
        condition=shared,
        candidate_cells=B4_CANDIDATE_CELLS,
        candidates=candidate,
        serial_comparison=scenario_from_rows(all_rows),
        raw_rows=all_rows, model_constants=MODEL_CONSTANTS,
        notes=['Block/Expert/stage are operation Event totals; layers are not divided.',
               'B4 pass 1 only is used for these costs.',
               'Stress is the per-dimension maximum of training samples; it is not a formal upper bound.',
               'Stage first and later are separate; startup is not subtracted or added twice.',
               'Condition pressure.mode is the declared quiet condition; runtime worker count is UNKNOWN.',
               'Condition hardware.device and hardware.temperature are UNKNOWN; clock limits are recorded.'])


def catalog():
    return dict(
        schema='m3_b2_empirical_plan_selector_evidence_catalog_v1_r1',
        primary=dict(batch='split_priority_ablation_v1_r2', result=str(B4_RESULT), result_sha256=sha(B4_RESULT),
                     config=str(B4_CONFIG), config_sha256=sha(B4_CONFIG),
                     condition='P=240 ms, phase=+15 ms, quiet declared (no interference); 8 cycles/4 refreshes; B4 default 10 ms lead from frozen source',
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
            'B4 result.json does not record a pressure worker count, device model or temperature; those fields are UNKNOWN.',
        ],
        model=dict(path=str(MODEL), sha256=sha(MODEL), env=str(MODEL_ENV), env_sha256=sha(MODEL_ENV),
                   executor=str(PROJECT / 'reports/m3_b2/20261021/split_priority_ablation_v1_r2/deployment/m2_executor.py'),
                   executor_sha256=sha(PROJECT / 'reports/m3_b2/20261021/split_priority_ablation_v1_r2/deployment/m2_executor.py')),
        model_constants=MODEL_CONSTANTS,
    )
