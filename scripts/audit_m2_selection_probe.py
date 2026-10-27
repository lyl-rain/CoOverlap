"""CPU-only offline audit of selection_probe_01. No GPU, no model, no threshold change.

Recomputes every SHA claim from the archived bytes, then answers:
  did the warm-selected slot1 reproduce the frozen S1 and S0 references,
  and does it differ from the cold-selected slot0 in the same process?
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT/'reports/m2_common/20261020'
PROBE = REPORTS/'selection_probe_01/board'
DIAG = REPORTS/'gpu_run_02/board'
RUN1 = REPORTS/'gpu_run_01/board'
OUT = REPORTS/'selection_probe_01/OFFLINE_AUDIT.json'
HIST = {
    'S0': {'x': 'ea62dc726393626b26de570d3e66a8d00a8a7145d5d240398b350c0ddb3eec4f',
           'K': '7ff20f0d73d9db1cb8cd1cf1ddf435314ad2cd42cf8f644f41d4a7dd7bb7974b',
           'V': '4357374f84765b337d2633aa3cae5dd08003333691acad3e710223de29edfe93'},
    'S1': {'x': '9ceb59114f142cba07fc78af87fb77e7260a1cc5055ab8429d1ce1f7d97dbff6',
           'K': 'be952fa6b5e1f17516777efaeb88572871a88a17b7117a113818b7e83bb29163',
           'V': 'aff53412d2f300127c976a7a7b412007ff54c61e2d7e6aaa541e026baa41170b'},
}
HIST_BOUNDARY_S1 = {'x': '907062d6fa1b380c9b4f94ddd4d47a2446c8524db09eb5cbef62af3e9b90517a',
                    'K': '7a2b14c2995af396e65db0a9e5563cda499a6c0e1017aac898791be6f15f2537',
                    'V': '7f93bb73619752572c062772428fdd56b906316fe054da50c2aa2eb9ef271368'}


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
        return dict(error='length mismatch')
    to_f = lambda w: struct.unpack('<f', struct.pack('<I', (w << 16) & 0xFFFFFFFF))[0]
    d = [abs(to_f(x)-to_f(y)) for x, y in zip(a, b)]
    return dict(elements=len(d), mismatch=sum(1 for x, y in zip(a, b) if x != y),
                byte_exact=a == b, max_abs=max(d), mean_abs=sum(d)/len(d))


def main():
    result = json.loads((PROBE/'run/result.json').read_text())
    audit = dict(scope='CPU offline audit of selection_probe_01; archived bytes only',
                 run_status=result['status'], elapsed_s=result.get('elapsed_s'),
                 checks_total=len(result['checks']),
                 failed_checks=[c for c in result['checks'] if not c['pass_']],
                 language=dict(before=result.get('language_before'),
                               after=result.get('language_after')),
                 address_delta=result.get('address_delta'))

    shas = {}
    for tag in ('S1C', 'S0W', 'S0C'):
        parts = {}
        for name, p in (('context_x', 'context_x'), ('context_K', 'context_K'),
                        ('context_V', 'context_V'), ('layer8_x', 'layer8_x'),
                        ('layer8_K', 'layer8_K'), ('layer8_V', 'layer8_V'),
                        ('raw', 'raw'), ('actions', 'actions'),
                        ('vision_x_norm', 'vision_x_norm')):
            path = PROBE/('run/%s_%s.bin' % (tag, p))
            if path.exists():
                parts[name] = dict(sha256=sha(path), nbytes=path.stat().st_size)
        shas[tag] = parts
    audit['sha'] = shas

    audit['historical'] = dict(
        S1C_context={k: shas['S1C']['context_'+k]['sha256'] == HIST['S1'][k] for k in 'xKV'},
        S1C_boundary={k: shas['S1C']['layer8_'+k]['sha256'] == HIST_BOUNDARY_S1[k] for k in 'xKV'},
        S0W_context={k: shas['S0W']['context_'+k]['sha256'] == HIST['S0'][k] for k in 'xKV'},
        S0C_context={k: shas['S0C']['context_'+k]['sha256'] == HIST['S0'][k] for k in 'xKV'})

    same = [name for name in shas['S0W']
            if shas['S0W'][name]['sha256'] == shas['S0C'].get(name, {}).get('sha256')]
    audit['S0W_vs_S0C'] = dict(identical_tensors=same,
                               all_identical=len(same) == len(shas['S0W']),
                               tensors=len(shas['S0W']))
    audit['S0W_vs_S0C_numbers'] = {
        name: bf16_compare(PROBE/('run/S0W_%s.bin' % name), PROBE/('run/S0C_%s.bin' % name))
        for name in ('context_x', 'context_K', 'context_V', 'layer8_x', 'layer8_K',
                     'layer8_V', 'vision_x_norm', 'raw')}

    from m1_dual_gate import evaluate, POLICY
    audit['numeric_policy'] = POLICY
    ref_raw = (RUN1/'reference/reference_S0_raw_bf16.bin').read_bytes()
    ref_act = (RUN1/'reference/reference_S0_actions.bin').read_bytes()
    audit['versus_frozen_S0'] = {}
    for tag in ('S0W', 'S0C'):
        audit['versus_frozen_S0'][tag] = dict(
            raw=evaluate((PROBE/('run/%s_raw.bin' % tag)).read_bytes(), ref_raw, 'bf16',
                         [50, 32], [50, 32]),
            actions=evaluate((PROBE/('run/%s_actions.bin' % tag)).read_bytes(), ref_act, 'f32',
                             [50, 7], [50, 7]))

    audit['versus_run02_A'] = {
        name: bf16_compare(PROBE/('run/S0C_%s.bin' % name), DIAG/('run/A_%s.bin' % name))
        for name in ('context_x', 'layer8_x', 'raw')}

    log = (PROBE/'ATTEMPT_USED/model.log').read_text(errors='replace')
    items = [(int(b), float(t)) for b, t in re.findall(r'best=(\d+) \(([\d.]+) us\)', log)]
    starts = [m.start() for m in re.finditer(r'DIAG\|([a-zA-Z0-9_]+)\|', log)]
    labels = [m.group(1) for m in re.finditer(r'DIAG\|([a-zA-Z0-9_]+)\|', log)]
    seg = {}
    for i, lab in enumerate(labels):
        end = starts[i+1] if i+1 < len(starts) else len(log)
        seg[lab] = [(int(b), float(t)) for b, t in
                    re.findall(r'best=(\d+) \(([\d.]+) us\)', log[starts[i]:end])]
    audit['autotune'] = dict(total=len(items),
                             slot0=seg.get('autotune_slot0'),
                             slot1=seg.get('autotune_slot1'),
                             markers=result.get('markers'))
    audit['clock'] = dict(distinct_gpu_freq=result.get('clock_samples_summary', {}).get(
        'distinct_gpu_freq'), n=result.get('clock_samples_summary', {}).get('n'))

    warm_reproduces_s0 = all(audit['historical']['S0W_context'].values())
    cold_reproduces_s0 = all(audit['historical']['S0C_context'].values())
    slots_differ = not audit['S0W_vs_S0C']['all_identical']
    audit['verdict'] = dict(
        harness_equivalent=True,  # established in gpu_run_02 (B=C)
        warm_slot_reproduces_historical_S0=warm_reproduces_s0,
        cold_slot_reproduces_historical_S0=cold_reproduces_s0,
        selection_changes_bytes=slots_differ,
        s1_positive_control=all(audit['historical']['S1C_context'].values())
        and all(audit['historical']['S1C_boundary'].values()),
        root_cause='cold-autotune selection of #1' if (warm_reproduces_s0 and slots_differ)
        else 'selection matters but is not sufficient' if slots_differ
        else 'selection numerically equivalent; cause elsewhere')
    OUT.write_text(json.dumps(audit, indent=2))
    print(json.dumps(dict(run_status=audit['run_status'], checks_total=audit['checks_total'],
                          failed_checks=audit['failed_checks'],
                          historical=audit['historical'],
                          S0W_vs_S0C=audit['S0W_vs_S0C'],
                          S0W_vs_S0C_context_x=audit['S0W_vs_S0C_numbers']['context_x'],
                          versus_frozen_S0={t: dict(max_abs=audit['versus_frozen_S0'][t]['raw']['max_abs'],
                                                    pass_=audit['versus_frozen_S0'][t]['raw']['pass_'])
                                            for t in ('S0W', 'S0C')},
                          autotune_item1=dict(slot0=(audit['autotune']['slot0'] or [None])[0],
                                              slot1=(audit['autotune']['slot1'] or [None])[0]),
                          gpu_freqs=audit['clock']['distinct_gpu_freq'],
                          verdict=audit['verdict']), indent=1))


if __name__ == '__main__':
    main()
