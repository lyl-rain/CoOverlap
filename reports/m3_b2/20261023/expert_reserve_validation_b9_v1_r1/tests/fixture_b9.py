"""Synthetic B9-structure fixtures for the evaluation CPU tests.

A fixture is NOT a B9 result: every document carries ``fixture: true`` and a
``fixture_note``.  It only reproduces the recorded shapes the evaluator consumes
(manifest, per-job intervals, decisions, journal) so the real evaluation entry can
be exercised end to end without any hardware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
B9 = HERE.parent
DEPLOY = B9 / 'deployment'
if str(DEPLOY) not in sys.path:
    sys.path.insert(0, str(DEPLOY))

import m3_b9_plan as plan  # noqa: E402


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(config, config_path, prediction_path, selection_path, base_ns=1_000_000_000,
          segments=8, expert_ratio=0.35, refresh_ratio=1.2, damage=None):
    damage = damage or {}
    out = dict(schema='m3_b9_fixture_v1', fixture=True,
               fixture_note='synthetic structure for CPU tests; never a B9 run',
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
               segments=[], protocol_work=config['work'])
    segs = []
    for i, cell in enumerate(config['run'][:segments]):
        m = plan.manifest(cell['period_ns'])
        period = cell['period_ns']
        t0 = base_ns * (i + 1)
        dmg = damage.get(i, {})
        experts, units, published, blocks, decisions = {}, {}, {}, {}, []
        for e in m['experts']:
            rel = t0 + e['release_ns']
            comp = rel + int(expert_ratio * period)
            if dmg.get('drop_expert') == e['id']:
                continue
            lo, hi = comp - 1000, comp
            if dmg.get('straddle_expert') == e['id']:
                lo, hi = rel + int(0.9 * period), rel + int(1.1 * period)
            experts[str(e['id'])] = (lo, hi)
            decisions.append(dict(host_ns=lo, kind='Expert', id=e['id']))
        for r in m['refreshes']:
            base = t0 + r['release_ns']
            for b in range(2):
                units['(%d, %d)' % (r['id'], b)] = (base + 10_000_000, base + 20_000_000)
            if dmg.get('drop_refresh') == r['id']:
                continue
            ready = base + int(refresh_ratio * period)
            if dmg.get('straddle_refresh') == r['id']:
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
        if dmg.get('drop_block'):
            blocks.pop(dmg['drop_block'], None)
        if dmg.get('drop_unit'):
            units.pop(dmg['drop_unit'], None)
        binds = []
        for e in m['experts']:
            if e['id'] % 2 == 0:
                binds.append(['bind', 'E%d' % e['id'], e['id'] // 2, 'S0'])
                binds.append(['bind', 'E%d' % (e['id'] + 1), e['id'] // 2, 'S0'])
        layout = __import__('m2_clean_core').retention_layout(config['cycles'], plan.PLANS[cell['plan']])
        segs.append(dict(
            segment_id=cell['id'] if False else
            config['segment_ids'][i], cell=cell['cell'], plan=cell['plan'],
            policy=cell['policy'], mode=cell['policy'], period_ns=period, t0_ns=t0,
            manifest=m, experts=experts, units=units, published=published, blocks=blocks,
            decisions=sorted(decisions, key=lambda d: d['host_ns']), journal=binds,
            block_plan=dict(id=cell['plan']),
            validation=dict(payload_B=layout['nbytes'], records=layout['count'],
                            all_job_actions_exact=True),
            statistics=dict(cycles=[], refreshes=[])))
    out['segments'] = segs
    return out


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
