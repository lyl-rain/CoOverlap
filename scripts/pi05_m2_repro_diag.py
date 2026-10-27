"""PREPARED M2 reproducibility diagnostic; never imports torch on dry-run.

Answers three separable questions in ONE ordinary-user, Eager, stream-0 process:
  A  cold autotune + S0 Context/Expert10: reproduces the failed batch conditions.
  B  warm re-autotune, same slot and buffers: do selection/buffer state move bytes?
  C  original run_pipeline(0): is the new harness path byte-identical to the original?

Deliberately NOT in this process: thresholds, tolerances, numeric PASS/FAIL,
cross-process comparison, hardware write, root, scope, graph, quota, concurrency.
Frozen-reference comparison stays in a later CPU audit of the archived bytes.
One process only; the wrapper enforces the bound and forbids retries.
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

HISTORICAL_S0 = {
    'x': 'ea62dc726393626b26de570d3e66a8d00a8a7145d5d240398b350c0ddb3eec4f',
    'K': '7ff20f0d73d9db1cb8cd1cf1ddf435314ad2cd42cf8f644f41d4a7dd7bb7974b',
    'V': '4357374f84765b337d2633aa3cae5dd08003333691acad3e710223de29edfe93',
}
HISTORY_LANGUAGE = {
    'S0': '5d2c913f17bf4b1a367ab0f6f51710558885814001b6e44841bb127f960e4a99',
    'S1': 'be301862a09d09e547856ba53f385dcb9eabe7373c0727c2f19398725485b770',
}
GPU_CUR = Path('/sys/class/devfreq/17000000.gpu/cur_freq')
EMC_CUR = Path('/sys/class/devfreq/bwmgr/cur_freq')
TEMP = Path('/sys/devices/virtual/thermal/thermal_zone0/temp')


def protocol():
    return dict(
        id='m2_repro_diag_01', status='PREPARED',
        questions=dict(
            Q1='does the M2 harness change the model mathematics? C vs B, byte exact',
            Q2='is the failed S0 a cold-autotune selection condition? A vs B plus autotune logs',
            Q3='is one process deterministic for identical buffers? A vs B tensors'),
        phases=dict(A='cold autotune, then S0 Context+Expert10 on slot0',
                    B='one throwaway Context on slot1, re-autotune both runners, S0 again on slot0',
                    C='original run_pipeline(0) on slot0 after phase B'),
        work=dict(Contexts=4, Experts=3, full_pipelines=1, encoder_layers=72, decoder_layers=540,
                  autotune_passes=4, warmup_contexts=1,
                  note='one slot1 Context is bounded warm-up only, never a reference'),
        model_process_limit=1, model_timeout_s=280, kill_grace_s=10, retry_limit=0,
        numeric_gate='none in-process; cross-process comparison is a separate CPU audit',
        unchanged=['checkpoint', 'BF16', '10 steps', '50 action chunk', '2 views', '49 tokens',
                   '561 encoder seq', '18 layers', 'stream 0', 'Eager'],
        forbidden=['threshold change', 'root', 'scope', 'clock/power write', 'graph', 'quota',
                   'concurrency', 'new fixture', 'retry'],
        approximate_snapshot_bytes=dict(A=21300000, B=21300000, C=13000000))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda: f.read(8*1024*1024), b''):
            h.update(data)
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
    ap.add_argument('--approved-m2-repro-diag-01', action='store_true')
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
        # CPU/IO only: the same 967-file lock as the frozen M2 package.
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
    if not args.approved_m2_repro_diag_01:
        ap.error('new explicit reproduction-diagnostic authorization required before GPU imports')
    if args.out is None or args.credential is None:
        ap.error('--out and --credential required')
    credential = json.loads(args.credential.read_text())
    if (credential['host'] != socket.gethostname() or credential['uid'] != os.geteuid()
            or not 0 <= time.time_ns()-credential['created_ns'] <= 3600*10**9):
        raise RuntimeError('preflight host/user/age changed')
    if len(credential['files']) != 967:
        raise RuntimeError('source/checkpoint preflight incomplete')
    for row in credential['files']:
        current = Path(row['path']).stat()
        if any(getattr(current, k) != v for k, v in row['stat'].items()):
            raise RuntimeError('preflight invalidated: '+row['path'])
    if os.geteuid() == 0:
        raise RuntimeError('ordinary user only')
    for key, value in os.environ.items():
        if value and (key.startswith(('NSYS_', 'KINETO_', 'TORCH_PROFILER_', 'CUPTI_INJECTION',
                                       'CUDA_INJECTION')) or key == 'LD_PRELOAD'):
            raise RuntimeError('unexpected instrumentation: '+key)
    args.out.mkdir(parents=True, exist_ok=False)
    report = dict(status='INCOMPLETE', protocol=protocol(), checks=[], phases={},
                  in_process_compare=[], markers=[], clock_samples=[], reference_integrity={})
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
        while sampler['active'] and len(sampler['rows']) < 6000:
            sampler['rows'].append(dict(monotonic_ns=time.monotonic_ns(),
                                        gpu_cur_freq=node(GPU_CUR),
                                        emc_cur_freq=node(EMC_CUR), temp_mc=node(TEMP)))
            time.sleep(0.05)

    def bound():
        if time.monotonic()-start > 265:
            raise TimeoutError('265s internal stop; no new work')
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
            path = args.reference/name
            actual = sha(path)
            require(actual == row['sha256'] and path.stat().st_size == row['nbytes'],
                    'reference_integrity_'+name)
            report['reference_integrity'][name] = dict(sha256=actual, nbytes=row['nbytes'])
        mem = [line for line in Path('/proc/meminfo').read_text().splitlines()
               if line.startswith('MemAvailable:')][0]
        require(int(mem.split()[1]) >= 32*1024**2, 'available_system_memory_32GiB')
        disk = os.statvfs(args.out)
        require(disk.f_bavail*disk.f_frsize >= 2*1024**3, 'disk_space_2GiB')
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

        def tbytes(t):
            return t.contiguous().view(torch.uint8).cpu().numpy().tobytes()

        def store(name, data):
            (args.out/(name+'.bin')).write_bytes(data)
            return dict(sha256=digest(data), nbytes=len(data))

        def stage(p, tag, fatal=False):
            owner._copy_tensor_to_pipeline_buf_stream(images, p.input_images_buf, 0)
            owner._copy_tensor_to_pipeline_buf_stream(noise, p.input_noise_buf, 0)
            stream.synchronize()
            # New observation: the device image buffer was never read back before.
            same_images = read(p.input_images_buf.ptr.value, images.numel()*2) == host_images
            same_noise = read(p.input_noise_buf.ptr.value, 3200) == host_noise
            row = dict(tag=tag, slot=ps.index(p), device_images_equal=same_images,
                       device_noise_equal=same_noise,
                       note='phase A is fatal by precondition; later restages are recorded only')
            report.setdefault('input_readback', []).append(row)
            if fatal:
                require(same_images, 'device_images_readback')
                require(same_noise, 'device_noise_readback')
            else:
                report['checks'].append(dict(name='restage_readback_'+tag,
                                             pass_=bool(same_images and same_noise)))
            save()

        def snap(p, layers=18):
            stream.synchronize()
            return dict(x=read(p.bufs['encoder_x'].ptr.value, 561*ENC_D*2),
                        K=tbytes(p.attn.enc_K[:layers, :561]),
                        V=tbytes(p.attn.enc_V[:layers, :561]))

        class Boundary:
            """Snapshot encoder_x and the written K/V prefix after layers 0 and 8."""
            def __init__(self, p):
                self.p, self.saved = p, {}
            def __enter__(self):
                self.orig = self.p._encoder_layer
                def observe(i, seq, fuse_b1, stream, orig=self.orig, me=self):
                    orig(i, seq, fuse_b1, stream)
                    if i in (0, 8):
                        me.saved[i] = snap(me.p, i+1)
                self.p._encoder_layer = observe
                return self
            def __exit__(self, *exc):
                self.p._encoder_layer = self.orig
                return False

        ledger = CallLedger(ps)

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

        def capture_ab(tag, p):
            bound()
            parts = {}
            with Boundary(p) as b:
                ledger.execute(tag+'_context', 0, 'Context', lambda: context(p))
                parts['layer0_x'] = b.saved[0]['x']
                parts['layer8_x'], parts['layer8_K'], parts['layer8_V'] = (
                    b.saved[8]['x'], b.saved[8]['K'], b.saved[8]['V'])
                ctx = snap(p, 18)
                # Read the projector input right after the Context: nothing later
                # in this phase writes it, while the Decoder scratch is unproven.
                parts['vision_x_norm'] = read(p.bufs['vision_x_norm'].ptr.value,
                                             p.bufs['vision_x_norm'].nbytes)
                ledger.execute(tag+'_expert', 0, 'Expert', lambda: p.transformer_decoder(0))
            parts['context_x'], parts['context_K'], parts['context_V'] = ctx['x'], ctx['K'], ctx['V']
            parts['raw'], parts['actions'] = outputs(p)
            record(tag, parts)

        def counted(p):
            """Count real model calls for the single original run_pipeline call."""
            saved = (p._encoder_layer, p._decoder_layer, p.vision_encoder,
                     p._copy_lang_embeds_to_encoder_x)
            calls = []
            def e(i, seq, fuse_b1, stream, orig=saved[0]):
                calls.append(('encoder', i)); return orig(i, seq, fuse_b1, stream)
            def d(i, step, enc_seq, ds, skip_c1, stream, orig=saved[1]):
                calls.append(('decoder', step, i))
                return orig(i, step, enc_seq, ds, skip_c1, stream)
            def v(stream=0, orig=saved[2]):
                calls.append(('vision27',)); return orig(stream)
            def l(stream=0, orig=saved[3]):
                calls.append(('language',)); return orig(stream=stream)
            p._encoder_layer, p._decoder_layer = e, d
            p.vision_encoder, p._copy_lang_embeds_to_encoder_x = v, l
            return calls, saved

        sampler['active'] = True
        threading.Thread(target=sample_loop, daemon=True).start()

        # ---- Phase A: run01 conditions, autotune immediately after build ----
        mark('A_autotune_begin')
        for slot in (0, 1):
            mark('A_autotune_slot%d' % slot)
            ps[slot].autotune_gemms()
            stream.synchronize()
            bound()
        mark('A_autotune_end')
        # Same order as the failed batch: image/noise staging comes after autotune,
        # so phase A runs its first measurement in the cold condition.
        images = owner._stack_images({k: f[k] for k in ('image', 'wrist_image', 'state')})
        require(tuple(images.shape) == (2, 224, 224, 3) and images.dtype == torch.bfloat16,
                'fixed_images_shape_dtype')
        require(digest(images.view(torch.uint8).cpu().numpy().tobytes()) ==
                meta['preprocessed_image_sha256'], 'fixed_preprocessed_images')
        noise = torch.from_numpy(f['noise0_bf16_bytes'].copy()).cuda().view(
            torch.bfloat16).reshape(50, 32)
        host_images = images.view(torch.uint8).cpu().numpy().tobytes()
        host_noise = f['noise0_bf16_bytes'].tobytes()
        # Report-only language identity, same position as the failed batch.
        report['language_sha'] = []
        for slot, p in enumerate(ps):
            got = digest(read(p._lang_embeds_buf.ptr.value, p._lang_embeds_buf.nbytes))
            report['language_sha'].append(dict(
                slot=slot, sha256=got,
                historical=HISTORY_LANGUAGE['S%d' % slot],
                matches_historical=got == HISTORY_LANGUAGE['S%d' % slot]))
        save()
        stage(p0, 'A', fatal=True)
        bound()
        capture_ab('A', p0)

        # ---- Bounded warm-up: one complete Context on the other slot ----
        mark('warmup_begin')
        stage(p1, 'warmup')
        ledger.execute('warmup_context', 1, 'Context', lambda: context(p1))
        stream.synchronize()
        mark('warmup_end')

        # ---- Phase B: warm re-autotune, identical slot and buffers ----
        mark('B_autotune_begin')
        for slot in (0, 1):
            mark('B_autotune_slot%d' % slot)
            before_flag = bool(getattr(ps[slot], '_gemms_autotuned', False))
            try:
                ps[slot].autotune_gemms()
                stream.synchronize()
                outcome = 'CALLED'
            except Exception as exc:  # a refused re-tune is a finding, not a stop
                outcome = 'RAISED'
                report.setdefault('autotune_calls', []).append(
                    dict(phase='B', slot=slot, status=outcome, error=repr(exc)[:300]))
            else:
                report.setdefault('autotune_calls', []).append(
                    dict(phase='B', slot=slot, status=outcome, flag_before=before_flag,
                         flag_after=bool(getattr(ps[slot], '_gemms_autotuned', False))))
            bound()
        mark('B_autotune_end')
        bound()
        stage(p0, 'B')
        capture_ab('B', p0)

        # ---- Phase C: the original single-call full pipeline ----
        mark('C_pipeline_begin')
        bound()
        stage(p0, 'C')
        calls, saved = counted(p0)
        parts = {}
        try:
            with Boundary(p0) as b:
                p0.run_pipeline(0)
                stream.synchronize()
                parts['layer8_x'], parts['layer8_K'], parts['layer8_V'] = (
                    b.saved[8]['x'], b.saved[8]['K'], b.saved[8]['V'])
        finally:
            p0._encoder_layer, p0._decoder_layer = saved[0], saved[1]
            p0.vision_encoder, p0._copy_lang_embeds_to_encoder_x = saved[2], saved[3]
        expected = ([('language',), ('vision27',)] + [('encoder', i) for i in range(18)]
                    + [('decoder', s, i) for s in range(10) for i in range(18)])
        require(tuple(calls) == tuple(expected), 'C_complete_original_work')
        ctx = snap(p0, 18)
        parts['context_x'], parts['context_K'], parts['context_V'] = ctx['x'], ctx['K'], ctx['V']
        parts['raw'], parts['actions'] = outputs(p0)
        record('C', parts)
        mark('C_pipeline_end')
        sampler['active'] = False

        shared = ['context_x', 'context_K', 'context_V', 'layer8_x', 'layer8_K', 'layer8_V',
                  'raw', 'actions']
        ab_names = shared + ['layer0_x', 'vision_x_norm']

        def compare(one, two, label, keys):
            rows = []
            for name in keys:
                a = report['phases'][one]['sha'].get(name)
                b = report['phases'][two]['sha'].get(name)
                rows.append(dict(tensor=name, equal=a == b,
                                 sha_a=a['sha256'] if a else None,
                                 sha_b=b['sha256'] if b else None))
            ok = all(r['equal'] for r in rows)
            report['in_process_compare'].append(dict(comparison=label, byte_exact=ok, rows=rows))
            save()
            return ok

        ab = compare('A', 'B', 'A_vs_B', ab_names)
        bc = compare('B', 'C', 'B_vs_C', shared)
        shas = lambda tag, key: report['phases'][tag]['sha'][key]['sha256']
        report['answers'] = dict(
            Q1_harness_byte_exact=bc, Q3_same_process_byte_exact=ab,
            Q2_needs_autotune_log_review=True,
            historical_context_match=dict(
                A=[shas('A', k) == HISTORICAL_S0[t] for k, t in
                   (('context_x', 'x'), ('context_K', 'K'), ('context_V', 'V'))],
                B=[shas('B', k) == HISTORICAL_S0[t] for k, t in
                   (('context_x', 'x'), ('context_K', 'K'), ('context_V', 'V'))],
                C=[shas('C', k) == HISTORICAL_S0[t] for k, t in
                   (('context_x', 'x'), ('context_K', 'K'), ('context_V', 'V'))]),
            note='historical matching is reported only; no tolerance is applied in-process')
        final = address_manifest(owner, p0, p1, attn1, runner1)
        (args.out/'address_after.json').write_text(json.dumps(final, indent=2))
        before_names = {e['name'] for e in manifest_before['writable']+manifest_before['shared_readonly']}
        after_names = {e['name'] for e in final['writable']+final['shared_readonly']}
        report['address_delta'] = dict(
            identical=final == manifest_before,
            added=sorted(after_names-before_names), removed=sorted(before_names-after_names),
            note='report only: a lazily allocated visible buffer is evidence, not a stop')
        require(owner._cudart.cudaGetLastError() == 0, 'cuda_last_error')
        report['elapsed_s'] = round(time.monotonic()-start, 3)
        report['status'] = 'DIAGNOSTIC_COMPLETE'
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
            distinct_emc_freq=sorted({r['emc_cur_freq'] for r in sampler['rows']}),
            note='read-only sysfs sampling; not a locked-frequency claim')
        save()


if __name__ == '__main__':
    main()
