"""Condition-specific operation costs for the two evaluation entries.

Two separate cost objects, never pooled:

``b4_source``   the frozen r1 cost table (B4 r2, label ``OTHER_S0_0c63ddfb1c91``).
                This is the source of the B8 pre-run prediction.  Replaying it at
                P=140/180 only re-derives the frozen prediction; it is not new
                evidence about B8.

``b8_measured`` per-cell costs extracted from the B8 raw ``operations`` records of
                that same cell (label ``H_frozen``).  It is the B8 condition's own
                observation and is therefore *retrospective* by construction.

No entry mixes the two, and no entry changes the frozen r1 files.
"""
from __future__ import annotations

import statistics
from pathlib import Path

import env

# Cost/scenario keys: the plan's declared block kinds (evaluator.PLAN_LAYOUT).
BLOCK_ORDER = {'two_9_9': ('B1', 'B2'), 'three_prefix_9_9': ('P', 'B1', 'B2')}

# Job keys: the operation naming used by the raw records (backend key R{q}/B{b+1}).
# The tail block is therefore B2 for two_9_9 and **B3** for three_prefix_9_9;
# the plan's third *kind* is called B2 and must not be confused with the tail key.
BLOCK_KEY = {'two_9_9': ('B1', 'B2'), 'three_prefix_9_9': ('B1', 'B2', 'B3')}

# Declared kind of the same block index (P/B1/B2 for the three-block plan).
BLOCK_KIND = {'two_9_9': ('B1', 'B2'), 'three_prefix_9_9': ('P', 'B1', 'B2')}


def tail_key(plan):
    return BLOCK_KEY[plan][-1]
CELL_LETTER = {'A': 'two_9_9', 'B': 'three_prefix_9_9',
               'C': 'two_9_9', 'D': 'three_prefix_9_9'}


def _stats(values):
    values = sorted(float(v) for v in values)
    if not values:
        return dict(n=0, median=None, max=None, min=None)
    return dict(n=len(values), median=round(statistics.median(values), 6),
                max=round(values[-1], 6), min=round(values[0], 6))


def operation_ms(segment):
    """Every observed operation GPU envelope of one segment, keyed by plan label."""
    labels = BLOCK_KIND[segment['plan']]
    out = {}
    for op in segment.get('operations') or []:
        key = op['key']
        ms = op.get('GPU_total_envelope_ms')
        if ms is None:
            continue
        if key.startswith('E'):
            out[('Expert', int(key[1:]))] = float(ms)
        elif key.startswith('R') and key.endswith('/stage'):
            q = int(key[1:key.index('/')])
            out[('stage', q)] = float(ms)
        elif key.startswith('R'):
            q, b = key[1:].split('/B')
            out[('block', int(q), labels[int(b) - 1])] = float(ms)
    return out


def b8_measured_costs(result):
    """Per-cell, per-plan costs from that cell's own B8 raw operation records."""
    cells = {}
    for segment in result['segments']:
        cell = segment['cell']
        plan = segment['plan']
        ops = operation_ms(segment)
        c = cells.setdefault(cell, dict(cell=cell, letter=cell[0], plan=plan,
                                        period_ns=segment['period_ns'],
                                        segments=[], blocks={}, expert=[], stage={},
                                        rows={}))
        c['segments'].append(segment['segment_id'])
        for key, ms in ops.items():
            c['rows'].setdefault(key, []).append(ms)
    for cell, c in cells.items():
        for key, values in c['rows'].items():
            if key[0] == 'Expert':
                c['expert'].extend(values)
            elif key[0] == 'stage':
                slot = 'first' if key[1] == 0 else 'later'
                c['stage'].setdefault(slot, []).extend(values)
            else:
                c['blocks'].setdefault(key[2], []).extend(values)
        c['expert'] = _stats(c['expert'])
        c['stage'] = {k: _stats(v) for k, v in c['stage'].items()}
        c['blocks'] = {k: _stats(v) for k, v in c['blocks'].items()}
        c.pop('rows')
    return dict(schema='rbe_b8_measured_costs_v1', source='B8 raw operations.GPU_total_envelope_ms',
                condition=env.CONDITION_LABELS['b8_actual'], retrospective=True,
                note='per-cell extraction; C and D (and A and B) are never pooled; '
                     'medians are single-number model inputs, not distributions',
                cells=cells)


def b8_scenario(measured_cell, kind):
    """costs-shaped scenario for ``evaluator.evaluate`` from B8-measured costs."""
    if kind not in ('typical', 'stress'):
        raise ValueError('unreviewed scenario kind: %r' % (kind,))
    key = 'median' if kind == 'typical' else 'max'
    plan = measured_cell['plan']
    blocks = {}
    for label in BLOCK_ORDER[plan]:
        st = measured_cell['blocks'][label]
        blocks[label] = {key: st['median'] if key == 'median' else st['max'],
                         'median': st['median'], 'max': st['max'], 'min': st['min'],
                         'n': st['n']}
    expert = measured_cell['expert']
    stage = measured_cell['stage']
    return dict(kind=kind,
                blocks=blocks,
                expert={'median': expert['median'], 'max': expert['max'],
                        'min': expert['min'], 'n': expert['n']},
                stage={slot: {'median': st['median'], 'max': st['max'],
                              'min': st['min'], 'n': st['n']}
                       for slot, st in stage.items()})


def b4_source_costs():
    costs = env.load(env.TRAIN_COSTS)
    return dict(schema='rbe_b4_source_costs_v1', source=str(env.TRAIN_COSTS.relative_to(env.PROJECT)),
                condition=costs['condition']['fingerprint'],
                condition_label=env.CONDITION_LABELS['b4_source'],
                retrospective=False,
                note='unchanged frozen r1 table; the B8 pre-run prediction was generated from it',
                candidates=costs['candidates'], raw=costs)


def forecast_scenario(b4_costs, plan, kind):
    """The frozen prediction's own scenario selector (r1 selection.scenario_for)."""
    from selection import scenario_for
    return scenario_for(b4_costs['raw'], plan, kind)


def observed_expert_range(measured_cell):
    st = measured_cell['expert']
    return dict(min=st['min'], max=st['max'], median=st['median'], n=st['n'])


def condition_summary(b4, b8, cells):
    """Side-by-side cost identity; never a pooled distribution."""
    rows = []
    for letter in ('A', 'B', 'C', 'D'):
        cell = cells[letter]
        plan = cell['plan']
        b4c = b4['candidates'][plan]
        for label in BLOCK_ORDER[plan]:
            rows.append(dict(letter=letter, cell=cellid(cells, letter), plan=plan,
                             operation=label, kind='ContextBlock',
                             b4_source_median_ms=b4c['blocks'][label]['median'],
                             b4_source_max_ms=b4c['blocks'][label]['max'],
                             b8_median_ms=cell['blocks'][label]['median'],
                             b8_min_ms=cell['blocks'][label]['min'],
                             b8_max_ms=cell['blocks'][label]['max'],
                             b8_n=cell['blocks'][label]['n']))
        rows.append(dict(letter=letter, cell=cellid(cells, letter), plan=plan,
                         operation='Expert', kind='Expert',
                         b4_source_median_ms=b4c['expert']['median'],
                         b4_source_max_ms=b4c['expert']['max'],
                         b8_median_ms=cell['expert']['median'],
                         b8_min_ms=cell['expert']['min'],
                         b8_max_ms=cell['expert']['max'],
                         b8_n=cell['expert']['n']))
    return rows


def cellid(cells, letter):
    return cells[letter]['cell']
