"""Read-only CPU reconstruction of B4 report claims; no model/device imports."""
import ast
import collections
import hashlib
import json
from pathlib import Path
import statistics
import sys

RUN = Path(__file__).resolve().parents[1]
ROOT = RUN.parent
RAW = RUN / 'board/run_01'

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()

def reconstruct():
    r = json.loads((RAW / 'model/result.json').read_text())
    assert len(r['checks']) == 255 and all(c['pass_'] for c in r['checks'])
    assert len(r['call_ledger']) == 13400
    assert r['protocol'] == json.loads((ROOT / 'deployment/CONFIG.json').read_text())
    tree = ast.parse((ROOT / 'deployment/m3_b3_plan.py').read_text())
    plan = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'THREE' for t in n.targets))
    assert ast.literal_eval(plan.args[-1]) == ((0, 1), (2,))
    cells = collections.defaultdict(lambda: dict(even=[], refresh=[], boundary=[]))
    publication_rows, boundary_rows = [], []
    cycles = refreshes = 0
    for s in r['segments']:
        assert s['status'] == 'PASS' and s['protocol'] == r['protocol']['id']
        c = s['cell'][0]
        assert s['block_plan']['groups'] == ([[0], [1]] if c in 'AB' else [[0, 1], [2]])
        assert [x[1] for x in s['journal'] if x[0] == 'publish'] == [0, 1, 2, 3, 4]
        assert all(o['completed'] and o['gpu_event_confirmed'] for o in s['operations'])
        ops = {o['key']: o for o in s['operations']}
        for j, row in enumerate(s['statistics']['cycles']):
            assert row['cycle'] == j and row['status'] == 'PASS'
            assert row['response_upper_ns'] == max(row['expert_response_upper_ns'], row['VLM_response_upper_ns'])
            cycles += 1
            if j % 2 == 0:
                cells[c]['even'].append({k: row[f'{k}_response_upper_ns'] / 1e6 for k in ('expert', 'VLM')}
                                        | {'cycle': row['response_upper_ns'] / 1e6})
        for qstr, pub in s['published'].items():
            q = int(qstr)
            arrival = s['t0_ns'] + s['manifest']['refreshes'][q]['release_ns']
            last = ops[f'R{q}/B{len(s["block_plan"]["blocks"])}']
            confirmed = last['gpu_completion_upper_host_ns']
            row = dict(segment_id=s['segment_id'], cell=c, refresh_id=q,
                       version=s['manifest']['refreshes'][q]['version'], release_host_ns=arrival,
                       tail_event_confirmed_host_ns=confirmed, publish_upper_host_ns=pub[1],
                       tail_confirmed_response_ms=(confirmed-arrival)/1e6,
                       publish_ready_response_ms=(pub[1]-arrival)/1e6,
                       confirmed_to_publish_host_interval_ms=(pub[1]-confirmed)/1e6)
            assert pub[1] >= confirmed
            cells[c]['refresh'].append(row); publication_rows.append(row); refreshes += 1
        for d in s['decisions']:
            if d['kind'] != 'Expert' or d['id'] % 2:
                continue
            q = d['id'] // 2
            ready = [o for o in s['operations'] if o['key'].startswith(f'R{q}/')
                     and o['gpu_completion_upper_host_ns'] <= d['host_ns']]
            last = max(ready, key=lambda o: o['gpu_completion_upper_host_ns'])
            expected = f'R{q}/B{len(s["block_plan"]["blocks"])}' if c in 'AC' else f'R{q}/B1'
            assert last['key'] == expected
            row = dict(segment_id=s['segment_id'], cell=c, expert_id=d['id'], block_key=last['key'],
                       dispatch_host_ns=d['host_ns'], completed_observed_host_ns=last['gpu_completion_upper_host_ns'],
                       boundary_host_interval_ms=(d['host_ns']-last['gpu_completion_upper_host_ns'])/1e6)
            cells[c]['boundary'].append(row); boundary_rows.append(row)
    assert (cycles, refreshes, len(boundary_rows)) == (64, 32, 32)
    summaries = {}
    old_cells = json.loads((RUN / 'offline/CELLS.json').read_text())
    for c, data in sorted(cells.items()):
        avg = {k+'_response_even_mean_ms': statistics.mean(x[k] for x in data['even']) for k in ('expert','VLM','cycle')}
        for k, old in [('expert', 'expert_resp_even'),('VLM','vlm_resp_even'),('cycle','cycle_resp_even')]:
            assert abs(avg[k+'_response_even_mean_ms'] - next(v for key,v in old_cells.items() if key.startswith(c+'_'))[old]) < .001
        avg.update({k+'_mean_ms': statistics.mean(x[k+'_ms'] for x in data['refresh']) for k in
                    ('tail_confirmed_response','publish_ready_response','confirmed_to_publish_host_interval')})
        vals = [x['boundary_host_interval_ms'] for x in data['boundary']]
        avg.update(boundary_host_interval_min_ms=min(vals), boundary_host_interval_mean_ms=statistics.mean(vals),
                   boundary_host_interval_max_ms=max(vals), even_samples=8, refresh_samples=8)
        summaries[c] = avg
    raw_files = {str(p.relative_to(RAW)): dict(bytes=p.stat().st_size, sha256=sha(p))
                 for p in sorted(RAW.rglob('*')) if p.is_file()}
    assert len(raw_files) == 191 and sum(x['bytes'] for x in raw_files.values()) == 5090444806
    assert 'clock_before.json' not in raw_files
    frozen = {}
    for line in (ROOT / 'deployment/DEPLOY_SHA256.txt').read_text().splitlines():
        expected, name = line.split(None, 1); name = name.strip()
        assert sha(ROOT / 'deployment' / name) == expected
        frozen[name] = expected
    assert len(frozen) == 36
    return dict(status='PASS_LOCAL_REPORT_RECONSTRUCTION', scope='CPU/offline only; no new GPU correctness or performance run',
                raw_result_sha256=sha(RAW/'model/result.json'), checks_unchanged=255, cycles=cycles, refreshes=refreshes,
                local_archive_files=191, local_archive_bytes=5090444806,
                archive_scope='191 ordinary-user-readable files; root snapshot content and privileged journal not archived',
                timing_definition='Host monotonic timestamps; tail Event covers the whole block operation including symmetric retention. Differences are observed Host intervals, not pure GPU computation or isolated overhead.',
                groups_three=[[0,1],[2]], cells=summaries, publication_rows=publication_rows, boundary_rows=boundary_rows,
                raw_files=raw_files, frozen_deployment_files=frozen,
                remote_manifest_scope='This reconstruction independently hashes local files only; it does not re-fetch or replace a board-side source manifest.')

if __name__ == '__main__':
    value = reconstruct()
    output = Path(__file__).with_name('REPORT_CORRECTIONS.json')
    if sys.argv[1:] == ['--verify']:
        assert value == json.loads(output.read_text()), 'saved reconstruction changed'
    elif sys.argv[1:]:
        raise SystemExit('usage: audit_report_corrections.py [--verify]')
    else:
        output.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({k:value[k] for k in ('status','checks_unchanged','cycles','refreshes','local_archive_files','local_archive_bytes')},ensure_ascii=False))
