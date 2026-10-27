#!/usr/bin/env python3
"""Write the B9 frozen configuration, budget, fairness/compatibility reports and
the deployment SHA manifest.  CPU only; imports the plan module, no CUDA."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
B9 = HERE.parent
B8 = B9.parents[1] / '20261022' / 'split_budget_challenge_b8_v1'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load_module(name, path, first_on_path):
    if str(first_on_path) not in sys.path:
        sys.path.insert(0, str(first_on_path))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    sys.path.insert(0, str(HERE))
    import m3_b10_plan as b9

    protocol = b9.protocol()
    budget = b9.budget()
    (HERE / 'CONFIG.json').write_text(json.dumps(protocol, indent=2, sort_keys=True) + '\n')

    batch = protocol['work']['batch']
    observed = protocol['work']['observed_ledger']
    budget_doc = dict(
        schema='m3_b9_budget_v1', protocol=b9.PROTOCOL,
        work=dict(
            batch=batch, observed_ledger=observed,
            autotune_requests=protocol['work']['autotune_requests'],
            selection_record=dict(
                added_context=0, added_expert=0, added_model_calls=0,
                note='the pre-segment selection record is one JSON copy per segment; it adds no '
                     'Context, Expert or model work'),
            totals=dict(context=batch['total_C'], expert10=batch['total_E'])),
        retention=dict(bank_bytes=budget['bank_bytes'],
                       gpu_and_pinned_bytes=budget['gpu_and_pinned_bytes'],
                       batch_payload_bytes=budget['batch_payload_bytes'],
                       gate_payload_bytes=budget['gate_payload_bytes'],
                       per_cell_segment_bytes=budget['per_cell_segment_bytes']),
        disk=budget['disk'], timeline_s=budget['timeline_s'],
        time=dict(internal_s=170, outer_timeout_s=180, exit_grace_s=10,
                  scope_max_s=420, retries=0,
                  note='internal 170 s cutoff; 180 s outer timeout plus at most 10 s grace;'
                       ' one five-node scope with a 420 s cap; no retry'),
        memory=dict(gpu_plus_pinned=budget['gpu_and_pinned_bytes'],
                    floor_check='torch.cuda.mem_get_info()[0] > 12 GiB + 2*bank'),
        source='computed from m3_b10_plan.budget()/protocol() at freeze time, not copied from a report')
    (HERE / 'BUDGET.json').write_text(json.dumps(budget_doc, indent=2, sort_keys=True) + '\n')

    # Fairness: within one budget the two cells share everything except the cut.
    same_budget = {}
    for ns, conf in sorted(b9.manifests().items()):
        pair = [c for c in b9.RUN if c['period_ns'] == ns]
        same_budget[str(ns)] = dict(
            cells=[c['cell'] for c in pair], period_ns=ns,
            plans=[c['plan'] for c in pair],
            identical_keys=sorted(conf.keys() - {'block_plans'}),
            cycles=conf['cycles'], phase_ns=conf['phase_ns'],
            releases=[e['release_ns'] for e in conf['experts']],
            deadlines=[e['deadline_ns'] for e in conf['experts']],
            refresh_releases=[r['release_ns'] for r in conf['refreshes']],
            note='same manifest object per budget; the two cells differ only in plan')
    fairness = dict(
        schema='m3_b9_fairness_v1', protocol=b9.PROTOCOL,
        same_budget_pairs=[['A', 'B'], ['C', 'D']],
        same_plan_across_budgets=[['A', 'C'], ['B', 'D']],
        by_budget=same_budget,
        cross_budget=dict(matched=False,
                          note='180 and 140 ms move releases, deadlines and refresh arrivals; the '
                               'two budgets are not the same wall-clock arrival trace'),
        shared=['inputs/noise/checkpoint/BF16', 'phase +15 ms', 'lead 10 ms',
                'consumption v=floor(id/2)', 'even/odd reservation', 'Context FIFO',
                'obligation groups', 'complete work', 'retention path', 'Event/Host observation'],
        not_matched=['wall clock across budgets'],
        no_serial_control=True)
    (HERE / 'FAIRNESS_CHECK.json').write_text(json.dumps(fairness, indent=2, sort_keys=True) + '\n')

    # Compatibility with the executed B8 batch: compare manifests after the schema field.
    b8 = load_module('m3_b8_plan', str(B8 / 'deployment' / 'm3_b8_plan.py'),
                     B8 / 'deployment')
    diffs = []
    for ns in b9.BUDGETS:
        a = json.loads(json.dumps(b9.manifests()[ns]))
        c = json.loads(json.dumps(b8.manifests()[ns]))
        a.pop('schema', None)
        c.pop('schema', None)
        if a != c:
            diffs.append(str(ns))
    compat = dict(
        schema='m3_b9_compatibility_v1', protocol=b9.PROTOCOL, previous=b8.PROTOCOL,
        protocol_identity=dict(equal=False, note='new independent protocol id; not required to match'),
        math=dict(equal=True, source='same frozen m2_pi05_ops block bodies; same CONTROL/THREE plans'),
        manifests=dict(equal_after_schema=not diffs, differing=list(diffs),
                       note='expert releases/deadlines, refresh releases, cycles, phase and plans'),
        inputs=dict(equal=True, source='fixed fixture/checkpoint/BF16/images/wrist/state/language/noise'),
        version=dict(equal=True, source='v=floor(id/2), even/odd reservation, FIFO, publish guard'),
        obligations=dict(equal=True, source='same per-plan obligation groups and complete work'),
        retention=dict(equal=True, source='same per-plan retention layouts for 8 cycles; D2D retained'),
        timing=dict(equal=True, source='same Host completion bounds and Event envelopes'),
        lead_ms=10, pressure='quiet, 0 workers', observation='normal Event/Host, no 22-point diagnostics',
        differences=['protocol id and result status', 'pre-segment selection record (JSON only)',
                     'prediction source is the frozen B8 cost table, not the B4 extrapolation',
                     'no B8 extrapolation claim; the reserve rule is the object of validation'],
        not_claimed='this batch does not assume the numeric configuration is unchanged; it is recorded '
                    'before timing and decides whether the selector domain is evaluated or declined')
    (HERE / 'COMPATIBILITY.json').write_text(json.dumps(compat, indent=2, sort_keys=True) + '\n')

    files = sorted(p for p in HERE.rglob('*')
                   if p.is_file() and p.name != 'DEPLOY_SHA256.txt'
                   and '__pycache__' not in p.parts)
    lines = ['%s  %s' % (sha(p), p.relative_to(HERE).as_posix()) for p in files]
    (HERE / 'DEPLOY_SHA256.txt').write_text('\n'.join(lines) + '\n')
    print(json.dumps(dict(files=len(files), config_sha=sha(HERE / 'CONFIG.json'),
                          manifest_equal_after_schema=not diffs,
                          totals=[batch['total_C'], batch['total_E']],
                          observed_rows=observed['rows'],
                          bank=budget['bank_bytes'], payload=budget['batch_payload_bytes'],
                          disk_gib=budget['disk']['estimate_gib']), indent=2))


if __name__ == '__main__':
    main()
