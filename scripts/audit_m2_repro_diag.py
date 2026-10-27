"""CPU-only offline audit of repro_diag_01. No GPU, no model, no threshold change.

Recomputes every in-process claim from the archived bytes (does not trust
result.json), then performs the cross-process comparisons that the GPU process
deliberately did not do. The frozen 0.015625/0.01 thresholds are applied
unchanged and reported as observations.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT/'reports/m2_common/20261020'
RUN2 = REPORTS/'gpu_run_02/board'
RUN1 = REPORTS/'gpu_run_01/board'
OUT = REPORTS/'gpu_run_02/OFFLINE_AUDIT.json'
HIST_S0 = {
    'x': 'ea62dc726393626b26de570d3e66a8d00a8a7145d5d240398b350c0ddb3eec4f',
    'K': '7ff20f0d73d9db1cb8cd1cf1ddf435314ad2cd42cf8f644f41d4a7dd7bb7974b',
    'V': '4357374f84765b337d2633aa3cae5dd08003333691acad3e710223de29edfe93',
}
TENSORS = ['context_x', 'context_K', 'context_V', 'layer8_x', 'layer8_K', 'layer8_V']


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for d in iter(lambda: f.read(8*1024*1024), b''):
            h.update(d)
    return h.hexdigest()


def words(path):
    data = Path(path).read_bytes()
    return [int.from_bytes(data[i:i+2], 'little') for i in range(0, len(data), 2)]


def bf16_compare(a_path, b_path):
    import struct
    a, b = words(a_path), words(b_path)
    if len(a) != len(b):
        return dict(error='length mismatch', n_a=len(a), n_b=len(b))
    to_f = lambda w: struct.unpack('<f', struct.pack('<I', (w << 16) & 0xFFFFFFFF))[0]
    d = [abs(to_f(x)-to_f(y)) for x, y in zip(a, b)]
    worst = max(range(len(d)), key=d.__getitem__)
    return dict(elements=len(d), mismatch=sum(1 for x, y in zip(a, b) if x != y),
                byte_exact=a == b, max_abs=d[worst],
                mean_abs=sum(d)/len(d), max_abs_flat_index=worst)


def f32_compare(a_path, b_path):
    import struct
    a = Path(a_path).read_bytes()
    b = Path(b_path).read_bytes()
    if len(a) != len(b):
        return dict(error='length mismatch')
    n = len(a)//4
    va = struct.unpack('<'+str(n)+'f', a)
    vb = struct.unpack('<'+str(n)+'f', b)
    d = [abs(x-y) for x, y in zip(va, vb)]
    return dict(elements=n, mismatch=sum(1 for x, y in zip(va, vb) if x != y),
                byte_exact=a == b, max_abs=max(d), mean_abs=sum(d)/len(d))


def main():
    result = json.loads((RUN2/'run/result.json').read_text())
    audit = dict(scope='CPU offline audit of repro_diag_01; archived bytes only',
                 run_status=result['status'], elapsed_s=result.get('elapsed_s'),
                 checks=[c for c in result['checks'] if not c['pass_']],
                 checks_total=len(result['checks']))

    # 1. In-process claims recomputed from files.
    recomputed = {}
    for label, (one, two) in {'A_vs_B': ('A', 'B'), 'B_vs_C': ('B', 'C')}.items():
        rows = []
        for name in TENSORS + ['raw', 'actions']:
            pa, pb = RUN2/('run/%s_%s.bin' % (one, name)), RUN2/('run/%s_%s.bin' % (two, name))
            if not pa.exists() or not pb.exists():
                rows.append(dict(tensor=name, present=False))
                continue
            rows.append(dict(tensor=name, present=True, byte_exact=sha(pa) == sha(pb)))
        recomputed[label] = dict(byte_exact=all(r.get('byte_exact') for r in rows), rows=rows)
    audit['in_process_recomputed'] = recomputed
    audit['in_process_declared'] = {r['comparison']: r['byte_exact']
                                    for r in result['in_process_compare']}
    audit['in_process_consistent'] = all(
        recomputed[k]['byte_exact'] == result['in_process_compare'][i]['byte_exact']
        for i, k in enumerate(['A_vs_B', 'B_vs_C']))

    # 2. Historical context match, recomputed (SHA only; the tensors are not kept).
    hist = {}
    for tag in ('A', 'B', 'C'):
        hist[tag] = {k: sha(RUN2/('run/%s_context_%s.bin' % (tag, k))) for k in ('x', 'K', 'V')}
    audit['historical_context_match'] = {
        tag: {k: hist[tag][k] == HIST_S0[k] for k in ('x', 'K', 'V')} for tag in ('A', 'B', 'C')}
    audit['context_sha'] = hist

    # 3. Cross-process: this batch versus the failed batch run01.
    pairs = dict(context_x='ref0_context_x', context_K='ref0_context_K', context_V='ref0_context_V',
                 layer8_x='ref0_mid_x', layer8_K='ref0_mid_K', layer8_V='ref0_mid_V')
    audit['versus_run01'] = {}
    for name, other in pairs.items():
        a = RUN2/('run/A_%s.bin' % name)
        b = RUN1/('run/%s.bin' % other)
        audit['versus_run01'][name] = bf16_compare(a, b)
    audit['versus_run01']['raw'] = bf16_compare(RUN2/'run/A_raw.bin', RUN1/'run/ref0_raw.bin')
    audit['versus_run01']['actions'] = f32_compare(RUN2/'run/A_actions.bin',
                                                   RUN1/'run/ref0_actions.bin')

    # 4. Versus the frozen historical reference, unchanged policy (report only).
    from m1_dual_gate import evaluate, POLICY
    audit['numeric_policy'] = POLICY
    audit['versus_frozen_reference'] = {}
    ref_raw = (RUN1/'reference/reference_S0_raw_bf16.bin').read_bytes()
    ref_act = (RUN1/'reference/reference_S0_actions.bin').read_bytes()
    assert sha(RUN1/'reference/reference_S0_raw_bf16.bin') == \
        '2d04bbbe5a7caef1a194f7c15d2fda98571179a1dfc87e9b6f7ed76c73b054c6'
    for tag in ('A', 'B', 'C'):
        row = dict(
            raw=evaluate((RUN2/('run/%s_raw.bin' % tag)).read_bytes(), ref_raw, 'bf16',
                         [50, 32], [50, 32]),
            actions=evaluate((RUN2/('run/%s_actions.bin' % tag)).read_bytes(), ref_act, 'f32',
                             [50, 7], [50, 7]))
        audit['versus_frozen_reference'][tag] = row

    # 5. Frozen historical S0 layer-8 boundary is not kept locally; only SHAs exist.
    audit['layer8_historical_reference'] = dict(
        status='NOT_AVAILABLE', note='frozen MANIFEST has no S0 boundary tensors; '
                                     'run01/A layer8 comparison is cross-process only')

    # 6. Autotune decisions per runner and phase, from the archived log.
    log = (RUN2/'ATTEMPT_USED/model.log').read_text(errors='replace')
    import re
    marks = [(m.group(1), m.start()) for m in re.finditer(r'DIAG\|([a-zA-Z0-9_]+)\|', log)]
    def segment(start, end):
        body = log[start:end]
        return [(int(b), float(t)) for b, t in
                re.findall(r'best=(\d+) \(([\d.]+) us\)', body)]
    starts = [pos for _, pos in marks]
    labels = [lab for lab, _ in marks]
    segs = {}
    for i, lab in enumerate(labels):
        end = starts[i+1] if i+1 < len(starts) else len(log)
        segs[lab] = len(segment(starts[i], end))
    audit['autotune'] = dict(
        total_lines=len(re.findall(r'best=\d+ \(', log)),
        per_marker_window=segs,
        slot0=segment(log.index('DIAG|A_autotune_slot0|'),
                      log.index('DIAG|A_autotune_slot1|')),
        slot1=segment(log.index('DIAG|A_autotune_slot1|'),
                      log.index('DIAG|A_autotune_end|')),
        phase_B_lines=len(re.findall(r'best=\d+ \(',
                                     log[log.index('DIAG|B_autotune_begin|'):])),
        note='phase B re-tune is a cache-hit no-op: no new measurements')

    # 7. Clock evidence around the first autotune call.
    samples = result.get('clock_samples', [])
    audit['clock'] = dict(
        markers=result.get('markers'),
        distinct_gpu_freq=result.get('clock_samples_summary', {}).get('distinct_gpu_freq'),
        first_samples=samples[:8], last_samples=samples[-4:],
        note='read-only sysfs; the first autotune call starts at the minimum GPU frequency')

    failed = [k for k, v in audit['in_process_declared'].items() if not v]
    audit['verdict'] = dict(
        harness_changes_math=False if not failed else None,
        within_process_deterministic=audit['in_process_recomputed']['A_vs_B']['byte_exact'],
        reproduces_historical_context=any(all(hist[t].values()) for t in ('A', 'B', 'C')),
        cross_process_reproducible=(audit['versus_run01']['context_x'].get('byte_exact', False)),
        statement='Q1/Q3 answered; Q2 mechanism observed but not yet isolated by a warm-first run')
    OUT.write_text(json.dumps(audit, indent=2))

    print(json.dumps(dict(
        run_status=audit['run_status'], checks_total=audit['checks_total'],
        failed_checks=audit['checks'],
        in_process_consistent=audit['in_process_consistent'],
        A_vs_B=audit['in_process_recomputed']['A_vs_B']['byte_exact'],
        B_vs_C=audit['in_process_recomputed']['B_vs_C']['byte_exact'],
        historical_context_match=audit['historical_context_match'],
        versus_run01_context_x=audit['versus_run01']['context_x'],
        versus_frozen_raw={t: dict(max_abs=audit['versus_frozen_reference'][t]['raw']['max_abs'],
                                   mismatch=audit['versus_frozen_reference'][t]['raw']['mismatch_elements'],
                                   pass_=audit['versus_frozen_reference'][t]['raw']['pass_'])
                           for t in ('A', 'B', 'C')},
        autotune_item1=dict(slot0=audit['autotune']['slot0'][:1], slot1=audit['autotune']['slot1'][:1],
                            phase_B_lines=audit['autotune']['phase_B_lines']),
        gpu_freqs=audit['clock']['distinct_gpu_freq'],
        verdict=audit['verdict']), indent=1))


if __name__ == '__main__':
    main()
