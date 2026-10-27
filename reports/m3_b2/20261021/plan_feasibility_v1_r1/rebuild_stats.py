"""Independent statistics rebuild from raw mappings (not from stored statistics).

The stored `statistics.cycles/refreshes` are OUTPUTS. This module rebuilds them
from the raw ownership records of each segment (`manifest`, `t0_ns`, `experts`,
`units`, `published`) using the frozen `m2_executor.replay_stats`, then compares
job by job. It also cross-checks the raw maps against the per-operation Event
fields. It never writes to the original result file; fault injection always
works on a temporary copy.
"""
import copy
import json
import math
import tempfile
from pathlib import Path

from model_env import DEPLOYMENT  # noqa: F401
import m2_executor

RUN_RESULT = (Path(__file__).resolve().parents[1]
              / 'split_priority_ablation_v1_r2' / 'gpu_run_01'
              / 'board' / 'run_01' / 'model' / 'result.json')


def _pair(v):
    if not (isinstance(v, (list, tuple)) and len(v) == 2):
        raise ValueError('completion record must be [lower, upper]')
    return (int(v[0]), int(v[1]))


def raw_maps(segment):
    experts = {int(k): _pair(v) for k, v in segment['experts'].items()}
    units = {}
    for k, v in segment['units'].items():
        m, g = (int(x) for x in k.strip('()').split(','))
        units[(m, g)] = _pair(v)
    published = {int(k): _pair(v) for k, v in segment['published'].items()}
    return dict(manifest=copy.deepcopy(segment['manifest']), t0=int(segment['t0_ns']),
                experts=experts, units=units, published=published)


def rebuild(raw):
    return m2_executor.replay_stats(raw['manifest'], raw['experts'], raw['units'],
                                    raw['published'], raw['t0'])


def derived_responses(raw, stats):
    """Per-cycle Expert/VLM responses, recomputed from the raw completion maps."""
    out = []
    for row in stats['cycles']:
        j = row['cycle']
        rel = row['release_ns']
        e = raw['experts'].get(j)
        u = raw['units'].get((j // 2, j % 2))
        out.append(dict(
            cycle=j,
            expert_response_ms=round((e[1] - rel) / 1e6, 6) if e else None,
            vlm_response_ms=round(max(0, u[1] - rel) / 1e6, 6) if u else None,
            response_ms=round((row['response_upper_ns']) / 1e6, 6) if row['response_upper_ns'] is not None else None,
            status=row['status'], deadline_ns=row['deadline_ns'], release_ns=rel))
    return out


def compare_with_stored(segment, stats, derived):
    """Job-by-job comparison; returns a list of mismatch strings."""
    bad = []
    stored_cycles = segment['statistics']['cycles']
    stored_refreshes = segment['statistics']['refreshes']
    if len(stored_cycles) != len(stats['cycles']):
        bad.append('cycle count %d != %d' % (len(stored_cycles), len(stats['cycles'])))
    for s, r, d in zip(stored_cycles, stats['cycles'], derived):
        if s['cycle'] != r['cycle']:
            bad.append('cycle id order')
        for key in ('release_ns', 'deadline_ns', 'status', 'response_lower_ns',
                    'response_upper_ns', 'expert_status', 'unit_status'):
            if s.get(key) != r.get(key):
                bad.append('cycle %d %s: stored %r rebuilt %r' % (s['cycle'], key, s.get(key), r.get(key)))
        if s.get('expert_response_upper_ns') != (int(round(d['expert_response_ms'] * 1e6)) if d['expert_response_ms'] is not None else None):
            got = s.get('expert_response_upper_ns')
            want = int(round(d['expert_response_ms'] * 1e6)) if d['expert_response_ms'] is not None else None
            if got != want and (abs(got - want) > 1 if (got is not None and want is not None) else True):
                bad.append('cycle %d expert_response: %r vs %r' % (s['cycle'], got, want))
        got_v = s.get('VLM_response_upper_ns')
        want_v = int(round(d['vlm_response_ms'] * 1e6)) if d['vlm_response_ms'] is not None else None
        if got_v != want_v and (abs(got_v - want_v) > 1 if (got_v is not None and want_v is not None) else True):
            bad.append('cycle %d VLM_response: %r vs %r' % (s['cycle'], got_v, want_v))
    if len(stored_refreshes) != len(stats['refreshes']):
        bad.append('refresh count mismatch')
    for s, r in zip(stored_refreshes, stats['refreshes']):
        for key in ('id', 'status', 'ready_lower_ns', 'ready_upper_ns', 'k_lower', 'k_upper'):
            if s.get(key) != r.get(key):
                bad.append('refresh %d %s: stored %r rebuilt %r' % (r['id'], key, s.get(key), r.get(key)))
    return bad


def cross_check_operations(segment):
    """Raw maps must agree with the per-operation Event completion fields."""
    bad = []
    ops = {o['key']: o for o in segment['operations']}
    for j, (lo, hi) in ((int(k), v) for k, v in segment['experts'].items()):
        op = ops.get('E%d' % j)
        if op is None:
            bad.append('missing operation E%d' % j)
            continue
        if (op.get('lower_ns'), op.get('upper_ns')) != (lo, hi):
            bad.append('E%d interval %r != raw %r' % (j, (op.get('lower_ns'), op.get('upper_ns')), (lo, hi)))
        if op.get('gpu_completion_upper_host_ns', hi) > hi:
            bad.append('E%d GPU completion %r beyond the returned upper %r'
                       % (j, op.get('gpu_completion_upper_host_ns'), hi))
    plan = segment['block_plan']
    nblocks = len(plan['blocks'])
    for q in range(segment['manifest']['cycles'] // 2):
        for gi, group in enumerate(plan['groups']):
            ups = []
            for b in group:
                op = ops.get('R%d/B%d' % (q, b + 1))
                if op is None:
                    bad.append('missing operation R%d/B%d' % (q, b + 1))
                    break
                ups.append((op['lower_ns'], op['upper_ns']))
            if len(ups) == len(group):
                key = '(%d, %d)' % (q, gi)
                stored = segment['units'].get(key)
                tail_group = [g for g, grp in enumerate(plan['groups']) if nblocks - 1 in grp][0]
                want = (max(x[0] for x in ups), max(x[1] for x in ups))
                if gi == tail_group:
                    # the executor bumps the tail group's upper to the publish instant
                    want = (want[0], segment['published'][str(q)][1])
                if stored is None:
                    bad.append('missing unit %s' % key)
                elif tuple(stored) != want:
                    bad.append('unit %s %r != %r' % (key, tuple(stored), want))
    return bad


def load_result(path=RUN_RESULT):
    return json.loads(Path(path).read_text())


def inject(mutation, path=RUN_RESULT):
    """Apply a mutation to a TEMPORARY copy, then rebuild and compare.

    Returns (detected, detail). The original file is never modified.
    """
    doc = load_result(path)
    seg = doc['segments'][0]
    mutation(doc)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / 'result.json'
        tmp_path.write_text(json.dumps(doc))
        doc2 = json.loads(tmp_path.read_text())
    seg2 = doc2['segments'][0]
    raw = raw_maps(seg2)
    stats = rebuild(raw)
    derived = derived_responses(raw, stats)
    mismatches = compare_with_stored(seg2, stats, derived)
    # A mutation is detected when the rebuilt statistics disagree with the
    # (unchanged) stored statistics of the mutated copy.
    return bool(mismatches), mismatches[:4]


MUTATIONS = dict(
    expert_upper=lambda d: d['segments'][0]['experts']['0'].__setitem__(1, d['segments'][0]['experts']['0'][1] + 1_000_000_000),
    unit_upper=lambda d: d['segments'][0]['units']['(0, 0)'].__setitem__(1, d['segments'][0]['units']['(0, 0)'][1] + 1_000_000_000),
    publish_upper=lambda d: d['segments'][0]['published']['0'].__setitem__(1, d['segments'][0]['published']['0'][1] + 1_000_000_000),
    missing_expert=lambda d: d['segments'][0]['experts'].pop('3'),
)
