"""CPU-only audit and read-only capsule import for the completed r2 batch.

Never starts models, SSH, CUDA or hardware scopes; frozen/raw files stay intact.
"""
import argparse
import ast
import base64
import collections
import hashlib
import json
import mmap
import sys
from pathlib import Path

CLOSE = Path(__file__).resolve().parent
RUN = CLOSE.parent
BOARD = RUN / 'board/run_01'
MODEL = BOARD / 'model'
FROZEN = RUN.parent / 'deployment'
sys.path.insert(0, str(FROZEN))
from m2_executor import replay_stats
from m3_b3_orchestrate import expected_gate_signature
from m3_b3_plan import THREE, protocol


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')


def append_only(path, data):
    if path.exists():
        assert path.read_bytes() == data, 'conflicting supplemental evidence: ' + str(path)
    else:
        with path.open('xb') as f:
            f.write(data)


def import_capsule(path):
    text = path.read_text().replace('\r', '')
    payload = text.split('ROOT_EVIDENCE_EXPORT_BEGIN\n', 1)[1].split('\nROOT_EVIDENCE_EXPORT_COMPLETE', 1)[0]
    packet = json.loads(payload)
    assert packet['schema'] == 'cooverlap_root_readonly_capsule_v1'
    assert packet['host'] == 'jyh-orin' and packet['uid'] == 0
    assert packet['run'] == '/home/nvidia/rtvla/cooverlap_m3_b3_20261021/run_01'
    assert packet['no_model'] and packet['no_hardware_write'] and packet['no_scope']
    snap = packet['snapshot']
    data = base64.b64decode(snap['content_b64'], validate=True)
    assert len(data) == snap['bytes'] == 2981 and digest(data) == snap['sha256']
    before = json.loads(data)
    pref = json.loads((BOARD / 'PREFLIGHT.json').read_text())
    assert before['schema'] == 'm1_clock_minima_v1' and before['host'] == 'jyh-orin'
    assert len(before['nodes']) == len(pref['hardware_before']['nodes']) == 5
    for a, b in zip(before['nodes'], pref['hardware_before']['nodes']):
        assert all(a[k] == b[k] for k in ('path', 'min', 'max', 'available', 'target'))
    names = [row['path'] for row in packet['files']]
    assert len(names) == len(set(names)) == 108
    for row in packet['files']:
        name = row['path']
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        actual = data if name == 'clock_before.json' else (BOARD / name).read_bytes()
        assert len(actual) == row['bytes'] and digest(actual) == row['sha256'], name
    target = CLOSE / 'root_evidence'
    target.mkdir(exist_ok=True)
    append_only(target / 'clock_before.json', data)
    append_only(target / 'ROOT_READONLY_CAPSULE.json', (json.dumps(packet, indent=2) + '\n').encode())
    log = packet['journal']
    if 'stdout_b64' in log:
        append_only(target / 'service_journal.txt', base64.b64decode(log['stdout_b64'], validate=True))
        append_only(target / 'service_journal_stderr.txt', base64.b64decode(log['stderr_b64'], validate=True))
    append_only(target / 'BOARD_ALL_FILES_SHA256.txt', ''.join(row['sha256'] + '  ' + row['path'] + '\n'
                                                             for row in packet['files']).encode())


def audit():
    r = json.loads((MODEL / 'result.json').read_text())
    assert r['protocol'] == protocol()
    assert len(r['checks']) == 151 and all(row['pass_'] for row in r['checks'])
    assert len(r['call_ledger']) == 2640
    assert dict(collections.Counter(row[2] for row in r['call_ledger'])) == r['observed_call_counts']
    frozen_rows = []
    for line in (FROZEN / 'DEPLOY_SHA256.txt').read_text().splitlines():
        wanted, name = line.split(None, 1)
        assert file_digest(FROZEN / name.strip()) == wanted
        frozen_rows.append(name.strip())
    assert len(frozen_rows) == 31
    for name in ('context_x', 'context_K', 'context_V', 'raw', 'actions'):
        assert (MODEL / ('equivalence_pipeline_' + name + '.bin')).read_bytes() == (MODEL / ('ref0_' + name + '.bin')).read_bytes()
    refs = {}
    for i in (0, 1):
        for key, part in (('ref', 'context'), ('mid', 'mid')):
            refs[key + str(i)] = b''.join((MODEL / ('ref%d_%s_%s.bin' % (i, part, axis))).read_bytes()
                                         for axis in ('x', 'K', 'V'))
        refs['pre' + str(i)] = (MODEL / ('prefix_ref_slot%d_x.bin' % i)).read_bytes()
        refs['raw' + str(i)] = (MODEL / ('ref%d_raw.bin' % i)).read_bytes()
    for name, gate in r['gates'].items():
        assert [tuple(row) for row in gate['journal']] == expected_gate_signature(THREE, name == 'gate_interrupt')
    retention = []
    reference_compares = 0
    input_hashes = collections.defaultdict(set)
    for path in sorted(MODEL.glob('*/RETENTION_INDEX.json')):
        ix = json.loads(path.read_text())
        binary = path.with_name('RETENTION.bin')
        assert binary.stat().st_size == ix['layout']['nbytes'] and file_digest(binary) == ix['payload_sha256']
        assert ix['segment_id'] == path.parent.name and ix['call_sequence_pass']
        comparisons = {c['key']: c for c in ix['comparisons']}
        claims = {c['key']: c for c in ix['claims']}
        with binary.open('rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as content:
            for e in ix['layout']['entries']:
                actual = content[e['offset']:e['offset'] + e['nbytes']]
                check = comparisons[e['key']]
                assert len(actual) == e['nbytes'] and check['exact']
                assert digest(actual) == check['sha256'] == check['reference_sha256']
                if e['expected'] in refs:
                    assert actual == refs[e['expected']]
                    reference_compares += 1
                else:
                    input_hashes[e['expected']].add(digest(actual))
                assert all(claims[e['key']][k] == e[k] for k in ('slot', 'generation', 'version', 'snapshot'))
        retention.append(dict(segment_id=ix['segment_id'], entries=ix['layout']['count'], bytes=binary.stat().st_size))
    assert all(len(values) == 1 for values in input_hashes.values())
    segments = []
    for s in r['segments']:
        fresh = replay_stats(s['manifest'], {int(k): v for k, v in s['experts'].items()},
                             {ast.literal_eval(k): v for k, v in s['units'].items()},
                             {int(k): v for k, v in s['published'].items()}, s['t0_ns'])
        for key in ('cycle_counts', 'refresh_counts', 'refreshes', 'response_upper_p99_ns', 'response_upper_p999_ns', 'backlog', 'k_min'):
            assert fresh[key] == s['statistics'][key], key
        for a, b in zip(fresh['cycles'], s['statistics']['cycles']):
            assert all(b[k] == v for k, v in a.items())
        assert all(op['completed'] and op['gpu_event_confirmed'] for op in s['operations'])
        decisions = [d for d in s['decisions'] if d['kind'] == 'Expert']
        for d in decisions:
            assert d['handle']['version'] == d['id'] // 2
            assert d['host_ns'] >= s['t0_ns'] + s['manifest']['experts'][d['id']]['release_ns']
        segments.append(dict(segment_id=s['segment_id'], effective_protocol=r['protocol']['id'],
                             raw_protocol=s['protocol'], manifest_schema=s['manifest']['schema'],
                             expert_response_upper_ms=[x['expert_response_upper_ns'] / 1e6 for x in s['statistics']['cycles']],
                             cycle_response_upper_ms=[x['response_upper_ns'] / 1e6 for x in s['statistics']['cycles']]))
    pref = json.loads((BOARD / 'PREFLIGHT.json').read_text())
    post = json.loads((BOARD / 'INDEPENDENT_RESTORE_READBACK.json').read_text())
    assert post['status'] == 'PASS' and post['independent_uid'] == 1001
    for a, b in zip(pref['hardware_before']['nodes'], post['nodes']):
        assert all(a[k] == b[k] for k in ('path', 'min', 'max'))
    assert all(pref['hardware_before'][k] == post[k] for k in ('governors', 'power_mode'))
    telemetry = json.loads((BOARD / 'ROOT_TELEMETRY.json').read_text())
    assert len(telemetry) == 23 and all(all(n['min'] == n['max'] == n['cur'] == n['target'] for n in row['limits']) for row in telemetry)
    remote = json.loads((CLOSE / 'BOARD_READABLE_INVENTORY.json').read_text())
    local = []
    for p in sorted(BOARD.rglob('*')):
        if p.is_file():
            local.append(dict(path=p.relative_to(BOARD).as_posix(), bytes=p.stat().st_size, sha256=file_digest(p)))
    assert local == remote['files'] and len(local) == 107
    save(CLOSE / 'LOCAL_RUN_MANIFEST.json', dict(files=local, count=len(local), bytes=sum(x['bytes'] for x in local)))
    (CLOSE / 'LOCAL_RUN_SHA256.txt').write_text(''.join(x['sha256'] + '  ' + x['path'] + '\n' for x in local))
    root_packet = CLOSE / 'root_evidence/ROOT_READONLY_CAPSULE.json'
    archive_complete = root_packet.exists()
    journal_evidence = dict(status='NOT_IMPORTED')
    if archive_complete:
        packet = json.loads(root_packet.read_text())
        supplement = CLOSE / 'root_evidence/clock_before.json'
        wanted = [x for x in packet['files'] if x['path'] == 'clock_before.json'][0]
        assert file_digest(supplement) == wanted['sha256'] and supplement.stat().st_size == wanted['bytes']
        assert [x for x in packet['files'] if x['path'] != 'clock_before.json'] == local
        log_path = CLOSE / 'root_evidence/service_journal.txt'
        if log_path.exists():
            events = []
            for line in log_path.read_text().splitlines():
                start = line.find('{')
                if start >= 0:
                    try:
                        events.append(json.loads(line[start:]))
                    except ValueError:
                        pass
            original = json.loads(supplement.read_text())
            for phase in ('apply', 'restore'):
                expected = {row['path']: row['target' if phase == 'apply' else 'min'] for row in original['nodes']}
                begins = [row for row in events if row.get('event') == 'MIN_WRITE_BEGIN' and row.get('phase') == phase]
                passes = [row for row in events if row.get('event') == 'MIN_READBACK_PASS' and row.get('phase') == phase]
                assert len(begins) == len(passes) == 5
                assert {row['node']: row['target'] for row in begins} == expected
                assert {row['node']: row['target'] for row in passes} == expected
                assert all(row['samples'][-1]['observed'] == row['target'] for row in passes)
                expected_order = [row['path'] for row in original['nodes']]
                if phase == 'restore':
                    expected_order.reverse()
                assert [row['node'] for row in begins] == expected_order
                assert [row['node'] for row in passes] == expected_order
            journal_evidence = dict(status='RECOVERED_AND_VERIFIED', apply_writes=5, restore_writes=5,
                                    successful_readbacks=10, reverse_restore_order=True,
                                    file_sha256=file_digest(log_path))
    result = dict(status='PASS_LOCAL_AUDIT', numerical_and_boundary_coverage='FINITE_PASS',
                  archive_status='COMPLETE_108_SOURCE_FILES' if archive_complete else 'PENDING_ROOT_SNAPSHOT_ONLY',
                  model_starts=0, hardware_writes=0, scopes=0, frozen_files=31,
                  original_internal_checks=151, original_internal_failures=0,
                  D1_saved_outputs_exact=5, ledger_rows=2640, retention=retention,
                  retention_entries=sum(x['entries'] for x in retention),
                  retained_entries_compared_to_independent_saved_references=reference_compares,
                  input_entries_note='remaining image/noise entries match recorded reference SHA and agree across all jobs; fixture NPZ not reloaded',
                  segments=segments, telemetry_samples=23, restore_matches_preflight=True,
                  board_local_verified_readable_files=107, board_local_verified_readable_bytes=sum(x['bytes'] for x in local),
                  raw_result_sha256=file_digest(MODEL / 'result.json'),
                  service_journal=journal_evidence)
    save(CLOSE / 'CLOSEOUT_AUDIT.json', result)
    print(json.dumps({k: result[k] for k in ('status', 'archive_status', 'retention_entries', 'ledger_rows')}, indent=2))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root-capsule', type=Path)
    a = ap.parse_args()
    if a.root_capsule:
        import_capsule(a.root_capsule)
    audit()
