"""PREPARED selection probe: is the cold-autotune #1 choice the cause? Never imports torch on dry-run.

One ordinary-user, Eager, stream-0 process:
  S1C  slot1 computes its natural S1 Context (positive control against the frozen S1 reference)
  S0W  slot1's language buffer is overwritten with S0's, then S0 Context+Expert10
  S0C  slot0 computes S0 Context+Expert10 with its cold-tuned (non-historical) selection

S0C vs S0W is the same process, the same fixed inputs and the same call sequence;
the only difference between the two slots is the autotune selection measured
moments earlier (#1 cold 306 MHz versus #1 warm 1300 MHz). No threshold, no
cross-reference comparison and no numeric PASS/FAIL happens in this process.
"""
import argparse
import hashlib
import json
import os
import signal
import socket
import threading
import time
import traceback
from pathlib import Path

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
HIST_LANGUAGE = {'S0': '5d2c913f17bf4b1a367ab0f6f51710558885814001b6e44841bb127f960e4a99',
                 'S1': 'be301862a09d09e547856ba53f385dcb9eabe7373c0727c2f19398725485b770'}
GPU_CUR = Path('/sys/class/devfreq/17000000.gpu/cur_freq')
EMC_CUR = Path('/sys/class/devfreq/bwmgr/cur_freq')
TEMP = Path('/sys/devices/virtual/thermal/thermal_zone0/temp')


def protocol():
    return dict(
        id='m2_selection_probe_01', status='PREPARED',
        question='does the cold-autotune #1 (Vision patch embedding) selection change the S0 Context bytes?',
        phases=dict(S1C='slot1 natural S1 Context (positive control)',
                    S0W='slot1 after S0 language overwrite: S0 Context+Expert10',
                    S0C='slot0 cold-tuned: S0 Context+Expert10'),
        work=dict(Contexts=3, Experts=2, encoder_layers=54, decoder_layers=360,
                  autotune_passes=2),
        model_process_limit=1, model_timeout_s=220, kill_grace_s=10, retry_limit=0,
        numeric_gate='none in-process; comparisons are a separate CPU audit',
        unchanged=['checkpoint', 'BF16', '10 steps', '50 action chunk', '2 views', '49 tokens',
                   '561 encoder seq', '18 layers', 'stream 0', 'Eager'],
        forbidden=['threshold change', 'root', 'scope', 'clock/power write', 'graph', 'quota',
                   'concurrency', 'new fixture', 'retry'])


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for d in iter(lambda: f.read(8*1024*1024), b''):
            h.update(d)
    return h.hexdigest()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def node(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return 'UNKNOWN'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--preflight', action='store_true')
    ap.add_argument('--approved-m2-selection-probe-01', action='store_true')
    ap.add_argument('--out', type=Path)
    ap.add_argument('--reference', type=Path)
    ap.add_argument('--preflight-out', type=Path)
    ap.add_argument('--credential', type=Path)
    args = ap.parse_args()
    if args.dry_run:
        print(json.dumps(protocol(), indent=2))
        return
    if args.reference is None:
        ap.error('--reference required')
    if args.preflight:
        source = json.loads((args.reference/'SOURCE_CHECKPOINT_SHA256.json').read_text())
        if len(source) != 967:
            raise RuntimeError('frozen source/checkpoint lock changed')
        if args.preflight_out is None:
            ap.error('--preflight-out required')
        records = []
        for path, wanted in source.items():
            before = Path(path).stat()
            if sha(path) != wanted:
                raise RuntimeError('source/checkpoint changed: '+path)
            after = Path(path).stat()
            keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
            if any(getattr(before, k) != getattr(after, k) for k in keys):
                raise RuntimeError('file changed while hashing')
            records.append(dict(path=path, sha256=wanted,
                                stat={k: getattr(after, k) for k in keys}))
        credential = dict(status='CPU_PREFLIGHT_PASS', files=records, host=socket.gethostname(),
                          uid=os.geteuid(), created_ns=time.time_ns())
        with args.preflight_out.open('x') as out:
            json.dump(credential, out, indent=2)
        print(json.dumps(dict(status='CPU_PREFLIGHT_PASS', files=len(source), gpu_processes=0)))
        return
    if not args.approved_m2_selection_probe_01:
        ap.error('new explicit selection-probe authorization required before GPU imports')
    if args.out is None or args.credential is None:
        ap.error('--out and --credential required')
    credential = json.loads(args.credential.read_text())
    if (credential['host'] != socket.gethostname() or credential['uid'] != os.geteuid()
            or not 0 <= time.time_ns()-credential['created_ns'] <= 3600*10**9):
        raise RuntimeError('preflight host/user/age changed')
    if len(credential['files']) != 967:
        raise RuntimeError('source/checkpoint preflight incomplete')
    for row in credential['files']:
        if any(getattr(Path(row['path']).stat(), k) != v for k, v in row['stat'].items()):
            raise RuntimeError('preflight invalidated: '+row['path'])
    if os.geteuid() == 0:
        raise RuntimeError('ordinary user only')
    for key, value in os.environ.items():
        if value and (key.startswith(('NSYS_', 'KINETO_', 'TORCH_PROFILER_', 'CUPTI_INJECTION',
                                       'CUDA_INJECTION')) or key == 'LD_PRELOAD'):
            raise RuntimeError('unexpected instrumentation: '+key)
    args.out.mkdir(parents=True, exist_ok=False)
    report = dict(status='INCOMPLETE', protocol=protocol(), checks=[], phases={},
                  markers=[], clock_samples=[], reference_integrity={})
    start = time.monotonic()
    sampler = dict(active=False, rows=[])

    def save():
        tmp = args.out/'result.tmp'
        tmp.write_text(json.dumps(report, indent=2))
        tmp.replace(args.out/'result.json')

    def require(ok, name):
        report['checks'].append(dict(name=name, pass_=bool(ok)))
        if not ok:
            save()
            raise AssertionError(name)

    def mark(label):
        row = dict(label=label, monotonic_ns=time.monotonic_ns(),
                   rel_s=round(time.monotonic()-start, 4), gpu_cur_freq=node(GPU_CUR),
                   emc_cur_freq=node(EMC_CUR), temp_mc=node(TEMP))
        report['markers'].append(row)
        print('DIAG|'+label+'|'+json.dumps(row, sort_keys=True), flush=True)

    def sample_loop():
        while sampler['active'] and len(sampler['rows']) < 4000:
            sampler['rows'].append(dict(monotonic_ns=time.monotonic_ns(),
                                        gpu_cur_freq=node(GPU_CUR),
                                        emc_cur_freq=node(EMC_CUR), temp_mc=node(TEMP)))
            time.sleep(0.05)

    def bound():
        if time.monotonic()-start > 200:
            raise TimeoutError('200s internal stop; no new work')
        try:
            if int(node(TEMP)) >= 80000:
                raise RuntimeError('thermal stop >=80C')
        except ValueError:
            pass

    def term(signum, frame):
        raise TimeoutError('termination requested; no new work')
    signal.signal(signal.SIGTERM, term)
    try:
        import ctypes
        import numpy as np
        import torch
        import flash_rt_gemm_diag as diag
        from pi05_dual_slot_adapter import build_slots, address_manifest, CHECKPOINT
        from flash_rt.models.pi05.pipeline_rtx import ENC_D
        from flash_rt.core.utils.actions import unnormalize_actions
        from m2_pi05_ops import context, CallLedger
        require(sha(diag.__file__) ==
                'bee648c5b5a9821084a39bb88ed9cba9681503c1043f90a7c95ace0bb1048d78',
                'existing_diag_binary')
        fp = Path('/tmp/cooverlap_pi05_fixed_reference.npz')
        sp = Path('/tmp/cooverlap_pi05_state_versions.npz')
        require(sha(fp) == '92f1a92b64352cc34010c81c1accd1cb00fcb227d0004f545b87549d5d6c544d',
                'fixed_fixture')
        require(sha(sp) == 'cabb191ec2b319c43fa769e5c8b9b8851724ef25ecff8850d118b8276124205e',
                'fixed_states')
        require(sha(CHECKPOINT/'config.json') ==
                '0458a362b574c2cb088ebf3767c9eacb1f040b9cb680a89b594379a4fe36e5f7',
                'fixed_model_config')
        require(json.loads((CHECKPOINT/'config.json').read_text())['state_cond'] is False,
                'state_cond_false')
        meta = json.loads((args.reference/'MANIFEST.json').read_text())
        for name, row in meta['files'].items():
            actual = sha(args.reference/name)
            require(actual == row['sha256'], 'reference_integrity_'+name)
            report['reference_integrity'][name] = dict(sha256=actual, nbytes=row['nbytes'])
        mem = [line for line in Path('/proc/meminfo').read_text().splitlines()
               if line.startswith('MemAvailable:')][0]
        require(int(mem.split()[1]) >= 32*1024**2, 'available_system_memory_32GiB')
        require(os.statvfs(args.out).f_bavail*os.statvfs(args.out).f_frsize >= 1024**3,
                'disk_space_1GiB')
        require(torch.cuda.mem_get_info()[0] > 12*1024**3, 'pre_model_free_memory')
        require(int(node(TEMP)) < 80000, 'temperature_below_80C')
        f = np.load(fp, allow_pickle=False)
        ss = np.load(sp, allow_pickle=False)
        owner, p0, p1, attn1, runner1 = build_slots(
            ss['s0'].copy(), ss['s1'].copy(),
            {k: f[k].copy() for k in ('image', 'wrist_image', 'state')}, diag.GemmRunner)
        ps = [p0, p1]
        stream = torch.cuda.default_stream()
        require(stream.cuda_stream == 0, 'stream0')
        for p in ps:
            require(not any(getattr(p, k) for k in ('use_fp8', 'use_fp8_decoder', 'use_int8_encoder',
                                                   'use_int8_decoder', 'use_int8_vision')), 'BF16_only')
            require((p.encoder_seq_len, p._current_prompt_len, p.vision_num_layers,
                     p.num_steps, p.chunk_size) == (561, 49, 27, 10, 50), 'full_fixed_work')
            require(p._graph is None and p._decoder_only_graph is None and not p._state_active,
                    'Eager_only')
        require(p0._lang_embeds_buf.nbytes == p1._lang_embeds_buf.nbytes, 'language_buffer_sizes')
        require(p0._lang_embeds_buf.nbytes == 200704, 'language_buffer_200704')
        manifest_before = address_manifest(owner, p0, p1, attn1, runner1)
        (args.out/'address_before.json').write_text(json.dumps(manifest_before, indent=2))
        save()

        def read(ptr, n):
            out = torch.empty(n, dtype=torch.uint8, device='cuda')
            rc = owner._cudart.cudaMemcpyAsync(ctypes.c_void_p(out.data_ptr()),
                                               ctypes.c_void_p(ptr), n, 3, 0)
            if rc:
                raise RuntimeError('D2D copy status '+str(rc))
            stream.synchronize()
            return out.cpu().numpy().tobytes()

        def copy_d2d(dst_ptr, src_ptr, n):
            rc = owner._cudart.cudaMemcpyAsync(ctypes.c_void_p(dst_ptr), ctypes.c_void_p(src_ptr),
                                               n, 3, 0)
            if rc:
                raise RuntimeError('D2D async status '+str(rc))
            stream.synchronize()

        def tbytes(t):
            return t.contiguous().view(torch.uint8).cpu().numpy().tobytes()

        def store(name, data):
            (args.out/(name+'.bin')).write_bytes(data)
            return dict(sha256=digest(data), nbytes=len(data))

        def snap(p, layers=18):
            stream.synchronize()
            return dict(x=read(p.bufs['encoder_x'].ptr.value, 561*ENC_D*2),
                        K=tbytes(p.attn.enc_K[:layers, :561]),
                        V=tbytes(p.attn.enc_V[:layers, :561]))

        class Boundary:
            def __init__(self, p, layers=(8,)):
                self.p, self.saved, self.layers = p, {}, layers
            def __enter__(self):
                self.orig = self.p._encoder_layer
                def observe(i, seq, fuse_b1, stream, orig=self.orig, me=self):
                    orig(i, seq, fuse_b1, stream)
                    if i in me.layers:
                        me.saved[i] = snap(me.p, i+1)
                self.p._encoder_layer = observe
                return self
            def __exit__(self, *exc):
                self.p._encoder_layer = self.orig
                return False

        ledger = CallLedger(ps)
        images = owner._stack_images({k: f[k] for k in ('image', 'wrist_image', 'state')})
        require(tuple(images.shape) == (2, 224, 224, 3) and images.dtype == torch.bfloat16,
                'fixed_images_shape_dtype')
        require(digest(images.view(torch.uint8).cpu().numpy().tobytes()) ==
                meta['preprocessed_image_sha256'], 'fixed_preprocessed_images')
        noise = torch.from_numpy(f['noise0_bf16_bytes'].copy()).cuda().view(
            torch.bfloat16).reshape(50, 32)
        host_images = images.view(torch.uint8).cpu().numpy().tobytes()
        host_noise = f['noise0_bf16_bytes'].tobytes()

        def stage(p, tag, fatal=False):
            owner._copy_tensor_to_pipeline_buf_stream(images, p.input_images_buf, 0)
            owner._copy_tensor_to_pipeline_buf_stream(noise, p.input_noise_buf, 0)
            stream.synchronize()
            ok_i = read(p.input_images_buf.ptr.value, images.numel()*2) == host_images
            ok_n = read(p.input_noise_buf.ptr.value, 3200) == host_noise
            report.setdefault('input_readback', []).append(
                dict(tag=tag, slot=ps.index(p), device_images_equal=ok_i, device_noise_equal=ok_n))
            if fatal:
                require(ok_i and ok_n, 'device_input_readback')
            else:
                report['checks'].append(dict(name='restage_readback_'+tag, pass_=bool(ok_i and ok_n)))
            save()

        def outputs(p):
            raw = read(p.input_noise_buf.ptr.value, 3200)
            vals = torch.from_numpy(np.frombuffer(raw, dtype=np.uint8).copy()).view(
                torch.bfloat16).float().reshape(50, 32).numpy()
            require(bool(np.isfinite(vals).all()), 'phase_output_finite')
            actions = np.ascontiguousarray(
                unnormalize_actions(vals, owner.norm_stats)[:, :7], dtype=np.float32).tobytes()
            return raw, actions

        def record(tag, parts):
            row = dict(label=tag, sha={})
            for name, data in parts.items():
                row['sha'][name] = store(tag+'_'+name, data)
            report['phases'][tag] = row
            save()

        sampler['active'] = True
        threading.Thread(target=sample_loop, daemon=True).start()

        # ---- cold autotune, exactly the observed run01/run02 order ----
        mark('autotune_begin')
        for slot in (0, 1):
            mark('autotune_slot%d' % slot)
            ps[slot].autotune_gemms()
            stream.synchronize()
            bound()
        mark('autotune_end')
        report['language_before'] = [
            dict(slot=s, sha=digest(read(p._lang_embeds_buf.ptr.value, p._lang_embeds_buf.nbytes)))
            for s, p in enumerate(ps)]
        save()

        # ---- S1C: slot1 natural S1 Context (positive control) ----
        mark('S1C_begin')
        stage(p1, 'S1C', fatal=True)
        parts = {}
        with Boundary(p1) as b:
            ledger.execute('S1C_context', 1, 'Context', lambda: context(p1))
            parts['layer8_x'], parts['layer8_K'], parts['layer8_V'] = (
                b.saved[8]['x'], b.saved[8]['K'], b.saved[8]['V'])
        ctx = snap(p1, 18)
        parts['context_x'], parts['context_K'], parts['context_V'] = ctx['x'], ctx['K'], ctx['V']
        parts['vision_x_norm'] = read(p1.bufs['vision_x_norm'].ptr.value,
                                     p1.bufs['vision_x_norm'].nbytes)
        record('S1C', parts)
        mark('S1C_end')

        # ---- overwrite slot1's persistent language embeddings with S0's ----
        mark('language_swap_begin')
        copy_d2d(p1._lang_embeds_buf.ptr.value, p0._lang_embeds_buf.ptr.value,
                 p0._lang_embeds_buf.nbytes)
        swapped = digest(read(p1._lang_embeds_buf.ptr.value, p1._lang_embeds_buf.nbytes))
        report['language_after'] = dict(slot=1, sha=swapped,
                                        expected=HIST_LANGUAGE['S0'],
                                        matches=swapped == HIST_LANGUAGE['S0'])
        require(report['language_after']['matches'], 'S0_language_restored_on_slot1')
        mark('language_swap_end')

        # ---- S0W: S0 Context+Expert on the warm-selected slot1 ----
        mark('S0W_begin')
        stage(p1, 'S0W')
        parts = {}
        with Boundary(p1) as b:
            ledger.execute('S0W_context', 1, 'Context', lambda: context(p1))
            parts['layer8_x'], parts['layer8_K'], parts['layer8_V'] = (
                b.saved[8]['x'], b.saved[8]['K'], b.saved[8]['V'])
            ctx = snap(p1, 18)
            parts['vision_x_norm'] = read(p1.bufs['vision_x_norm'].ptr.value,
                                         p1.bufs['vision_x_norm'].nbytes)
            ledger.execute('S0W_expert', 1, 'Expert', lambda: p1.transformer_decoder(0))
        parts['context_x'], parts['context_K'], parts['context_V'] = ctx['x'], ctx['K'], ctx['V']
        parts['raw'], parts['actions'] = outputs(p1)
        record('S0W', parts)
        mark('S0W_end')

        # ---- S0C: S0 Context+Expert on the cold-selected slot0 ----
        mark('S0C_begin')
        stage(p0, 'S0C')
        parts = {}
        with Boundary(p0) as b:
            ledger.execute('S0C_context', 0, 'Context', lambda: context(p0))
            parts['layer8_x'], parts['layer8_K'], parts['layer8_V'] = (
                b.saved[8]['x'], b.saved[8]['K'], b.saved[8]['V'])
            ctx = snap(p0, 18)
            parts['vision_x_norm'] = read(p0.bufs['vision_x_norm'].ptr.value,
                                         p0.bufs['vision_x_norm'].nbytes)
            ledger.execute('S0C_expert', 0, 'Expert', lambda: p0.transformer_decoder(0))
        parts['context_x'], parts['context_K'], parts['context_V'] = ctx['x'], ctx['K'], ctx['V']
        parts['raw'], parts['actions'] = outputs(p0)
        record('S0C', parts)
        mark('S0C_end')
        sampler['active'] = False

        shas = lambda tag, key: report['phases'][tag]['sha'][key]['sha256']
        report['historical'] = dict(
            S1C_context=[shas('S1C', k) == HIST['S1'][t] for k, t in
                         (('context_x', 'x'), ('context_K', 'K'), ('context_V', 'V'))],
            S1C_boundary=[shas('S1C', k) == HIST_BOUNDARY_S1[t] for k, t in
                          (('layer8_x', 'x'), ('layer8_K', 'K'), ('layer8_V', 'V'))],
            S0W_context=[shas('S0W', k) == HIST['S0'][t] for k, t in
                         (('context_x', 'x'), ('context_K', 'K'), ('context_V', 'V'))],
            S0C_context=[shas('S0C', k) == HIST['S0'][t] for k, t in
                         (('context_x', 'x'), ('context_K', 'K'), ('context_V', 'V'))],
            note='reported only; no tolerance and no PASS/FAIL in this process')
        same = [k for k in ('context_x', 'context_K', 'context_V', 'layer8_x', 'layer8_K',
                            'layer8_V', 'raw', 'actions', 'vision_x_norm')
                if report['phases']['S0W']['sha'].get(k) and
                report['phases']['S0W']['sha'][k] == report['phases']['S0C']['sha'][k]]
        report['S0W_vs_S0C_identical_tensors'] = same
        report['S0W_vs_S0C_all_identical'] = len(same) == 9
        final = address_manifest(owner, p0, p1, attn1, runner1)
        (args.out/'address_after.json').write_text(json.dumps(final, indent=2))
        before = {e['name'] for e in manifest_before['writable']+manifest_before['shared_readonly']}
        after = {e['name'] for e in final['writable']+final['shared_readonly']}
        report['address_delta'] = dict(identical=final == manifest_before,
                                       added=sorted(after-before), removed=sorted(before-after))
        require(owner._cudart.cudaGetLastError() == 0, 'cuda_last_error')
        report['elapsed_s'] = round(time.monotonic()-start, 3)
        report['status'] = 'PROBE_COMPLETE'
        save()
    except BaseException:
        report['status'] = 'FAIL_OR_INCOMPLETE'
        report['error'] = traceback.format_exc()
        save()
        raise
    finally:
        sampler['active'] = False
        report['clock_samples'] = sampler['rows']
        report['clock_samples_summary'] = dict(
            n=len(sampler['rows']),
            distinct_gpu_freq=sorted({r['gpu_cur_freq'] for r in sampler['rows']}),
            note='read-only sysfs sampling; not a locked-frequency claim')
        save()


if __name__ == '__main__':
    main()
