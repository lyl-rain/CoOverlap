"""One bounded sequential legal-quota sweep on the fixed Pi0.5 real load.

No concurrent pair, no CUDA Graph, no root, no collector. One model process
sequentially creates one legal Green execution context per quota, probes the
actual SM IDs, runs Context/Expert and checks byte-exact equality against the
full-GPU reference. The full ABI and all fixed-load checks are the same as the
already-verified isolated_limit run; only the SM quota loop is new.
"""
import time
START = time.monotonic()
import os, json, ctypes as C, hashlib, signal, traceback, collections
from pathlib import Path

OUT = Path(os.environ['COOVERLAP_RUN_DIR'])
OUT.mkdir(exist_ok=False, parents=True)
r = dict(status='INCOMPLETE', samples=[], checks=[], api=[], ledger={}, phases=[], cleanup='NOT_REACHED')
def save():
    with (OUT / 'result.json').open('w') as f:
        json.dump(r, f, indent=2); f.flush(); os.fsync(f.fileno())
def phase(s):
    r['phases'].append(dict(name=s, elapsed_s=time.monotonic() - START)); save()
def stop(signum, frame):
    r['status'] = 'INCOMPLETE_TIMEOUT'; r['signal'] = signum; save(); raise SystemExit(124)
signal.signal(signal.SIGTERM, stop); save()
def sha(b): return hashlib.sha256(b).hexdigest()
def check(v, name):
    r['checks'].append(dict(name=name, pass_=bool(v))); save()
    if not v: raise AssertionError(name)

cfgpath = Path(os.environ['COOVERLAP_PROTOCOL'])
cfg = json.loads(cfgpath.read_text())
SOFT = float(cfg.get('soft_no_new_work_after_s', 160))
def budget():
    if time.monotonic() - START > SOFT:
        raise TimeoutError('reserve final live checks and cleanup; no new work after soft limit')

def store(name, b, shape):
    with (OUT / (name + '.bin')).open('xb') as f:
        f.write(b); f.flush(); os.fsync(f.fileno())
    (OUT / (name + '.json')).write_text(json.dumps(dict(sha256=sha(b), nbytes=len(b),
                                                        logical_dtype='bfloat16', shape=shape)))

phase('imports')
import numpy as np
import torch
import flash_rt_gemm_diag as diag
from flash_rt.core.cuda_buffer import _cudart, CudaBuffer
from flash_rt.frontends.torch.pi05_rtx import Pi05TorchFrontendRtx
from flash_rt.models.pi05.pipeline_rtx import VIS_D, VIS_H, ENC_D, BF16
from pi05_dual_slot_adapter import CHECKPOINT, PROMPT, _collect
from quota_runtime_resource_v10 import QuotaRuntime

rt = None
try:
    r['protocol'] = cfg
    r['script_sha256'] = sha(Path(__file__).read_bytes())
    r['protocol_sha256'] = sha(cfgpath.read_bytes()); save()
    check(r['protocol_sha256'] == os.environ['COOVERLAP_PROTOCOL_SHA'], 'protocol_sha')
    check(sha(Path(diag.__file__).read_bytes()) ==
          'bee648c5b5a9821084a39bb88ed9cba9681503c1043f90a7c95ace0bb1048d78',
          'existing_isolated_extension_sha')
    r['extension'] = diag.__file__
    r['runtime_maps'] = [l for l in Path('/proc/self/maps').read_text().splitlines()
                         if 'libcudart' in l]
    torch.cuda.init(); torch.cuda.synchronize()
    rt = QuotaRuntime(_cudart, r['api'])
    r['device'] = rt.init_device()
    r['device']['quota_points'] = cfg['quota_points']
    normal = torch.cuda.ExternalStream(rt.ordinary.value, device=0)
    rt.load_probe(Path(os.environ['COOVERLAP_PROBE_CUBIN']))
    ids = torch.empty(4096, dtype=torch.int32, device='cuda')
    vals = torch.empty_like(ids)

    def probe(label, stream, expected_sm):
        budget()
        check(rt.resource(stream) == expected_sm, label + '_stream_resource')
        rt.probe(stream, ids.data_ptr(), vals.data_ptr())
        torch.cuda.synchronize()
        ii = ids.cpu().numpy(); vv = vals.cpu().numpy()
        observed = sorted(set(map(int, ii)))
        r.setdefault('probe', {})[label] = dict(
            stream=stream, SM_ids=observed, observed_sm_count=len(observed),
            expected_sm=expected_sm, values_sha256=sha(vv.tobytes()), n=4096)
        check(np.array_equal(vv, np.arange(4096, dtype=np.int32) + 7), label + '_probe_values')
        check(ii.min() >= 0 and ii.max() < 16, label + '_probe_id_range')
        # The resource query is the hard quota check; the short probe is diagnostic.
        # A trivial kernel may not schedule on every SM of a large quota, so only
        # require that the observed set is non-empty and within the quota.
        check(len(observed) <= expected_sm, label + '_probe_ids_within_quota')
        check(len(observed) >= 1, label + '_probe_ids_nonempty')
        r['probe'][label]['exact_sm_coverage'] = (len(observed) == expected_sm)
        save()

    probe('full', normal.cuda_stream, 16)
    phase('probe_done')

    fpath = Path('/tmp/cooverlap_pi05_fixed_reference.npz')
    f = np.load(fpath, allow_pickle=False)
    r['inputs'] = {k: sha(f[k].tobytes()) for k in
                   ['image', 'wrist_image', 'state', 'noise0_bf16_bytes']}
    r['fixture_sha256'] = sha(fpath.read_bytes()); save()
    check(r['fixture_sha256'] == '92f1a92b64352cc34010c81c1accd1cb00fcb227d0004f545b87549d5d6c544d',
          'fixed_fixture')
    check(sha((CHECKPOINT / 'config.json').read_bytes()) ==
          '0458a362b574c2cb088ebf3767c9eacb1f040b9cb680a89b594379a4fe36e5f7',
          'checkpoint_config')
    budget(); phase('load_checkpoint')
    owner = Pi05TorchFrontendRtx(CHECKPOINT, num_views=2, chunk_size=50, num_steps=10,
                                 hardware='rtx_sm87', state_prompt_mode='exact')
    owner.gemm = diag.GemmRunner()
    owner.set_prompt(PROMPT, state=f['state'])
    p = owner.pipeline
    p._bias_zero_buf = CudaBuffer.device_zeros(max(p.vision_seq * 3 * VIS_D,
                                                   p.vision_seq * VIS_H), BF16)
    check(p.encoder_seq_len == 561 and p._current_prompt_len == 49 and p.num_steps == 10
          and p.chunk_size == 50 and p.vision_num_layers == 27 and not p._state_active,
          'fixed_dimensions')
    check(not any(getattr(p, k) for k in ['use_fp8', 'use_fp8_decoder', 'use_int8_encoder',
                                          'use_int8_decoder', 'use_int8_vision']), 'fixed_BF16')
    check(p._graph is None and p._decoder_only_graph is None
          and all(p.attn._fa2_sites.values()) and not p.attn._fixed_shape,
          'existing_eager_vendor_FA2_route')
    r['backend'] = dict(routes=p.attn._fa2_sites, num_sms_heuristic=p.attn._num_sms); save()
    phase('autotune')
    p.autotune_gemms(); torch.cuda.synchronize(); check(p._gemms_autotuned, 'original_autotune_once')
    phase('autotune_done')
    images = owner._stack_images({k: f[k] for k in ['image', 'wrist_image', 'state']})
    noise = torch.from_numpy(f['noise0_bf16_bytes'].copy()).cuda().view(
        torch.bfloat16).reshape(50, 32)
    check(images.shape == (2, 224, 224, 3) and images.dtype == torch.bfloat16, 'fixed_preprocess')
    r['preprocessed_sha256'] = sha(images.view(torch.uint8).cpu().numpy().tobytes())

    def mem():
        free, total = torch.cuda.mem_get_info()
        return dict(cuda_free=free, cuda_total=total,
                    torch_allocated=torch.cuda.memory_allocated(),
                    torch_reserved=torch.cuda.memory_reserved(),
                    torch_peak=torch.cuda.max_memory_allocated(),
                    proc={l.split(':')[0]: l.split(':', 1)[1].strip()
                          for l in Path('/proc/self/status').read_text().splitlines()
                          if l.startswith(('VmRSS:', 'VmHWM:'))})
    r['memory_before'] = mem(); check(r['memory_before']['cuda_free'] > 12 * 1024 ** 3,
                                      'memory_floor_before')
    r['owner'] = 'single frontend._ckpt_bf16; one pipeline/backend/runner, sequentially reused'
    r['gemm_resources_before'] = dict(owner.gemm.resource_info())
    r['buffers_before'] = list(_collect(p, 'v0.pipeline')) + list(_collect(p.attn, 'v0.attn')); save()

    def read(ptr, n):
        buf = C.create_string_buffer(n)
        rc = _cudart.cudaMemcpy(buf, C.c_void_p(ptr), n, 2)
        if rc: raise RuntimeError('D2H CUDA ' + str(rc))
        return buf.raw

    def prefix():
        return tuple(b''.join(read(t.data_ptr() + i * t.stride(0) * t.element_size(), 561 * 256 * 2)
                             for i in range(18)) for t in [p.attn.enc_K, p.attn.enc_V])

    def context_state():
        return (read(p.bufs['encoder_x'].ptr.value, 561 * ENC_D * 2),) + prefix()

    r['initial_language_sha256'] = sha(read(p._lang_embeds_buf.ptr.value, p._lang_embeds_buf.nbytes)); save()
    expected = [0]
    job = ['none']
    routing = collections.Counter()

    class Proxy:
        def __init__(self, obj, label): self.obj = obj; self.label = label; self.cache = {}
        def __getattr__(self, name):
            fn = getattr(self.obj, name)
            if not callable(fn): return fn
            if name not in self.cache:
                def call(*a, **kw):
                    supplied = kw.get('stream')
                    if self.label == 'FVK' and name in ('patch_im2col', 'avg_pool_vision_tokens') and 'stream' not in kw:
                        supplied = a[-1]
                    if supplied != expected[0]:
                        raise RuntimeError('explicit stream missing/mismatch ' + self.label + '.' + name)
                    routing[self.label + '.' + name] += 1
                    return fn(*a, **kw)
                self.cache[name] = call
            return self.cache[name]

    p.gemm = Proxy(owner.gemm, 'GEMM'); p.fvk = Proxy(owner.fvk, 'FVK')
    oldfa = p.attn._fa2_fwd
    def fa(*a, **kw):
        if kw.get('stream') != expected[0]:
            raise RuntimeError('FA2 stream mismatch')
        routing['FA2.fwd'] += 1
        return oldfa(*a, **kw)
    p.attn._fa2_fwd = fa
    orig_enc, orig_dec = p._encoder_layer, p._decoder_layer
    boundary = [None]
    def enc(i, seq, fuse_b1, stream):
        if stream != expected[0]: raise RuntimeError('Encoder stream mismatch')
        r['ledger'].setdefault(job[0], {}).setdefault('encoder', []).append(i)
        orig_enc(i, seq, fuse_b1, stream)
        if i == 8 and boundary[0] is not None: boundary[0].record(torch.cuda.current_stream())
    def dec(i, step, enc_seq, ds, skip_c1, stream):
        if stream != expected[0]: raise RuntimeError('Expert stream mismatch')
        r['ledger'].setdefault(job[0], {}).setdefault('decoder', []).append([step, i])
        orig_dec(i, step, enc_seq, ds, skip_c1, stream)
    p._encoder_layer = enc; p._decoder_layer = dec

    # Pre-materialize all Event objects outside timed work. No Graph or polling thread.
    n_measure = 2 + len(cfg['quota_points']) * 10 + 8
    events = []
    for _ in range(n_measure):
        es = [torch.cuda.Event(enable_timing=True) for _ in range(3)]
        for e in es: e.record(normal)
        events.append(es)
    normal.synchronize()
    event_iter = iter(events)
    reference_ctx = None
    reference_raw = None

    def measure(label, kind, role, index, s, expected_sm, quota):
        global reference_ctx, reference_raw
        budget()
        name = f'{label}_{kind}_{role}_{index}'
        job[0] = name; expected[0] = s.cuda_stream
        torch.cuda.synchronize()  # config/job preparation only, outside Event/Host response
        input_start = time.monotonic_ns()
        with torch.cuda.stream(s):
            owner._copy_tensor_to_pipeline_buf_stream(images, p.input_images_buf, s.cuda_stream)
            owner._copy_tensor_to_pipeline_buf_stream(noise, p.input_noise_buf, s.cuda_stream)
        s.synchronize(); input_end = time.monotonic_ns()
        check(read(p.input_noise_buf.ptr.value, 3200) == f['noise0_bf16_bytes'].tobytes(),
              name + '_noise_readback')
        before_route = dict(routing)
        a, m, b = next(event_iter)
        boundary[0] = m if kind == 'Context' else None
        with torch.cuda.stream(s):
            check(torch.cuda.current_stream().cuda_stream == s.cuda_stream, name + '_Torch_stream')
            h0 = time.monotonic_ns(); a.record(s); submit0 = time.monotonic_ns()
            if kind == 'Context':
                p._copy_lang_embeds_to_encoder_x(s.cuda_stream)
                p.vision_encoder(s.cuda_stream)
                p.transformer_encoder(s.cuda_stream)
            else:
                p.transformer_decoder(s.cuda_stream)
            submit1 = time.monotonic_ns(); b.record(s)
            wait0 = time.monotonic_ns(); b.synchronize(); h1 = time.monotonic_ns()
        rc = _cudart.cudaGetLastError()
        rec = dict(name=name, config=label, kind=kind, role=role, index=index,
                   quota=quota, expected_sm=expected_sm, cuda_stream=s.cuda_stream,
                   host_response_ms=(h1 - h0) / 1e6, cpu_submit_ms=(submit1 - submit0) / 1e6,
                   cpu_wait_ms=(h1 - wait0) / 1e6, input_prepare_ms=(input_end - input_start) / 1e6,
                   event_ms=a.elapsed_time(b), cuda_last_error=rc,
                   routing={k: v - before_route.get(k, 0) for k, v in routing.items()
                            if v != before_route.get(k, 0)})
        if kind == 'Context':
            rec.update(B1_event_ms=a.elapsed_time(m), B2_event_ms=m.elapsed_time(b))
        r['samples'].append(rec); save()
        if rc: raise RuntimeError('CUDA error ' + str(rc))
        if kind == 'Context':
            state = context_state()
            for k, data, shape in zip(['x', 'K', 'V'], state,
                                      [[561, 2048], [18, 561, 1, 256], [18, 561, 1, 256]]):
                store(name + '_' + k, data, shape)
            if reference_ctx is None:
                reference_ctx = state
                for data in state:
                    bits = np.frombuffer(data, dtype='<u2').astype(np.uint32) << 16
                    check(np.isfinite(bits.view(np.float32)).all(), 'reference_Context_finite')
            check(all(x == y for x, y in zip(state, reference_ctx)), name + '_full_context_byte_exact')
            check(r['ledger'][name]['encoder'] == list(range(18)), name + '_18_layers')
        else:
            raw = read(p.input_noise_buf.ptr.value, 3200); store(name + '_raw', raw, [50, 32])
            old = prefix(); rec['old_KV_hashes'] = [sha(v) for v in old]; save()
            if reference_raw is None:
                reference_raw = raw
                ff = np.frombuffer(raw, dtype='<u2').astype(np.uint32) << 16
                check(np.isfinite(ff.view(np.float32)).all(), 'reference_Expert_finite')
            check(raw == reference_raw, name + '_raw_byte_exact')
            check(old == reference_ctx[1:], name + '_old_KV_unchanged')
            check(r['ledger'][name]['decoder'] == [[st, i] for st in range(10) for i in range(18)],
                  name + '_10_steps')
        check(rt.resource(s.cuda_stream) == expected_sm, name + '_resource_still_bound'); save()

    phase('reference')
    measure('full', 'Context', 'reference', 0, normal, 16, None)
    measure('full', 'Expert', 'reference', 0, normal, 16, None)

    for q in cfg['quota_points']:
        budget(); torch.cuda.synchronize(); phase(f'quota_{q}_configuration')
        try:
            info = rt.create_green(q)
        except Exception as e:
            # A driver-level legality failure is a finding, not a model FAIL.
            r.setdefault('quota_status', {})[str(q)] = dict(status='NOT_LEGAL', error=repr(e)); save()
            try:
                rt.destroy_green()
            except Exception:
                pass
            continue
        r.setdefault('green_resources', {})[str(q)] = info; save()
        green = torch.cuda.ExternalStream(info['green_stream'], device=0)
        probe(f'green{q}', green.cuda_stream, q)
        measure(f'green{q}', 'Context', 'gate', 0, green, q, q)
        measure(f'green{q}', 'Expert', 'gate', 0, green, q, q)
        for kind in ['Context', 'Expert']:
            measure(f'green{q}', kind, 'warmup', 0, green, q, q)
            for j in range(3):
                measure(f'green{q}', kind, 'formal', j, green, q, q)
        torch.cuda.synchronize()
        rt.destroy_green()
        phase(f'quota_{q}_done')
        r.setdefault('cleanup_per_quota', {})[str(q)] = 'PASS_context_stream_released'; save()

    phase('live_final_checks'); torch.cuda.synchronize()
    r['buffers_after'] = list(_collect(p, 'v0.pipeline')) + list(_collect(p.attn, 'v0.attn'))
    r['gemm_resources_after'] = dict(owner.gemm.resource_info())
    r['memory_after'] = mem()
    check({x['name']: (x['ptr'], x['nbytes']) for x in r['buffers_before']} ==
          {x['name']: (x['ptr'], x['nbytes']) for x in r['buffers_after']}, 'visible_addresses_stable')
    check(r['gemm_resources_before'] == r['gemm_resources_after'], 'GEMM_resources_stable')
    check(r['memory_after']['cuda_free'] > 12 * 1024 ** 3, 'memory_floor_after')
    r['final_language_sha256'] = sha(read(p._lang_embeds_buf.ptr.value, p._lang_embeds_buf.nbytes))
    check(r['final_language_sha256'] == r['initial_language_sha256'], 'language_immutable'); save()
    rt.close()
    r['cleanup'] = 'PASS_streams_library_contexts_released'; r['status'] = 'PASS'; save()
    print(json.dumps({'status': 'PASS', 'out': str(OUT)}), flush=True)
except BaseException:
    if r['status'] != 'INCOMPLETE_TIMEOUT':
        r['status'] = 'INCOMPLETE_RESERVED_TAIL' if isinstance(__import__('sys').exc_info()[1], TimeoutError) else 'FAIL'
    r['error'] = traceback.format_exc(); save()
    if r['status'] == 'INCOMPLETE_RESERVED_TAIL':
        try:
            torch.cuda.synchronize()
            if 'mem' in globals(): r['memory_reserved_tail'] = mem()
            if rt is not None: rt.close()
            r['cleanup'] = 'PASS_reserved_tail_cleanup'; save()
        except BaseException:
            r['cleanup_error'] = traceback.format_exc(); save()
    raise
