"""Synthetic B9-structure fixtures for the evaluation CPU tests.

Every document carries ``fixture: true``.  Segments are shaped exactly like the
real entry creates them *before* the run: the eight records already exist with
index/cell/plan/policy/period_ns/segment_id/status=NOT_STARTED/planned_*; executed
segments get the execution keys merged in.  That is the structure the r2 fixes
must handle, so deleting segments is no longer used to simulate NOT_STARTED.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
B9 = HERE.parent
DEPLOY = B9 / 'deployment'
if str(DEPLOY) not in sys.path:
    sys.path.insert(0, str(DEPLOY))

import m3_b9_plan as plan  # noqa: E402

IDENTITY = ('index', 'candidate', 'cell', 'pass_', 'policy', 'plan', 'period_ns',
            'segment_id', 'status', 'planned_Experts', 'planned_Context', 'selection',
            'selection_fingerprint', 'reserve_ms')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def records(config, config_path, prediction_path, selection_path):
    """The eight pre-created records, exactly as the entry builds them."""
    selection = json.loads(selection_path.read_text())
    out = []
    for i, cell in enumerate(config['run']):
        out.append(dict(
            index=i, candidate=cell['cell'], cell=cell['cell'], pass_=cell['pass_'],
            policy=cell['policy'], plan=cell['plan'], period_ns=cell['period_ns'],
            segment_id=config['segment_ids'][i], status='NOT_STARTED',
            planned_Experts=config['cycles'], planned_Context=config['cycles'] // 2,
            selection=selection['by_period_ns'][str(cell['period_ns'])],
            selection_fingerprint=selection['fingerprint'],
            reserve_ms=config['reserve']['value_ms']))
    return out


def execute(record, config, index, base_ns, expert_ratio=0.35, refresh_ratio=1.2,
            damage=None):
    """Merge one executed trajectory into a pre-created record (entry behaviour)."""
    damage = damage or {}
    cell = config['run'][index]
    period = cell['period_ns']
    m = plan.manifest(period)
    t0 = base_ns * (index + 1)
    experts, units, published, blocks, decisions = {}, {}, {}, {}, []
    for e in m['experts']:
        rel = t0 + e['release_ns']
        comp = rel + int(expert_ratio * period)
        if damage.get('drop_expert') == e['id']:
            continue
        lo, hi = comp - 1000, comp
        if damage.get('straddle_expert') == e['id']:
            lo, hi = rel + int(0.9 * period), rel + int(1.1 * period)
        experts[str(e['id'])] = (lo, hi)
        decisions.append(dict(host_ns=lo, kind='Expert', id=e['id']))
    for r in m['refreshes']:
        base = t0 + r['release_ns']
        for b in range(2):
            units['(%d, %d)' % (r['id'], b)] = (base + 10_000_000, base + 20_000_000)
        if damage.get('drop_refresh') == r['id']:
            continue
        ready = base + int(refresh_ratio * period)
        if damage.get('straddle_refresh') == r['id']:
            deadline = base + 2 * period
            published[str(r['id'])] = (deadline - 500_000, deadline + 500_000)
        else:
            published[str(r['id'])] = (ready - 1000, ready)
        decisions.append(dict(host_ns=base + 1, kind='stage', id=r['id']))
    nblocks = 2 if cell['plan'] == 'two_9_9' else 3
    for q in range(4):
        for b in range(nblocks):
            start = t0 + q * 2 * period + b * 30_000_000
            blocks['(%d, %d)' % (q, b)] = (start, start + 20_000_000)
            decisions.append(dict(host_ns=start, kind='Context', id=q, block=b))
    if damage.get('drop_block'):
        blocks.pop(damage['drop_block'], None)
    if damage.get('drop_unit'):
        units.pop(damage['drop_unit'], None)
    binds = []
    for e in m['experts']:
        if e['id'] % 2 == 0:
            binds.append(['bind', 'E%d' % e['id'], e['id'] // 2, 'S0'])
            binds.append(['bind', 'E%d' % (e['id'] + 1), e['id'] // 2, 'S0'])
    layout = __import__('m2_clean_core').retention_layout(config['cycles'],
                                                          plan.PLANS[cell['plan']])
    record.update(dict(
        policy=cell['policy'], mode=cell['policy'], period_ns=period, t0_ns=t0,
        manifest=m, experts=experts, units=units, published=published, blocks=blocks,
        decisions=sorted(decisions, key=lambda d: d['host_ns']), journal=binds,
        block_plan=dict(id=cell['plan']),
        validation=dict(payload_B=layout['nbytes'], records=layout['count'],
                        all_job_actions_exact=True),
        statistics=dict(cycles=[], refreshes=[]), status='PASS'))
    return record


def build(config, config_path, prediction_path, selection_path, base_ns=1_000_000_000,
          executed=8, expert_ratio=0.35, refresh_ratio=1.2, damage=None):
    damage = damage or {}
    out = dict(schema='m3_b9_fixture_v2', fixture=True,
               fixture_note='synthetic entry-shaped structure for CPU tests; never a B9 run',
               status='PASS_IN_PROCESS_EXPERT_RESERVE_VALIDATION',
               protocol=config, config_sha256=sha(config_path),
               prediction_identity=dict(path=config['prediction']['path'],
                                        sha256=sha(prediction_path)),
               selection_freeze=dict(fingerprint=json.loads(selection_path.read_text())['fingerprint'],
                                     reserve_ms=config['reserve']['value_ms'],
                                     rule=config['selection']['rule']),
               configuration=dict(label='H_frozen', matches_frozen_context=True,
                                  S0_context_sha256=[
                                      'ea62dc726393626b26de570d3e66a8d00a8a7145d5d240398b350c0ddb3eec4f',
                                      '7ff20f0d73d9db1cb8cd1cf1ddf435314ad2cd42cf8f644f41d4a7dd7bb7974b',
                                      '4357374f84765b337d2633aa3cae5dd08003333691acad3e710223de29edfe93']),
               observation_mode='performance', initial_clock_limits=dict(cpu='2201600'),
               source_config_fingerprints={'m3_b9_plan.py': 'fixture'},
               checks=[dict(name='fixture', pass_=True)],
               in_process_equivalence=dict(byte_exact=True),
               gates=dict(gate_old_reader=dict(status='PASS'),
                          gate_interrupt=dict(status='PASS')),
               observed_call_counts=dict(encoder=882, decoder=12420, language=49, vision27=49),
               call_ledger=[[]] * 13400,
               segments=records(config, config_path, prediction_path, selection_path))
    for i in range(min(executed, len(out['segments']))):
        execute(out['segments'][i], config, i, base_ns, expert_ratio, refresh_ratio,
                damage.get(i, {}))
    return out


def set_expert_completion(result, segment_index, job_id, completion_ns):
    """Set one Expert interval (absolute ns) inside an executed segment."""
    seg = result['segments'][segment_index]
    seg['experts'][str(job_id)] = (completion_ns - 1000, completion_ns)


def predicted_stress(result, pred, segment_index, job_id):
    seg = result['segments'][segment_index]
    period = seg['period_ns'] / 1e6
    plan_id = seg['plan']
    for row in pred['jobs']:
        if (row['budget_ms'] == period and row['plan'] == plan_id
                and row['scenario'] == 'stress' and row['job_type'] == 'Expert'
                and row['job_id'] == 'E%d' % job_id):
            return row['completion_ms']
    raise KeyError('no stress prediction for %s/%s' % (plan_id, job_id))


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
