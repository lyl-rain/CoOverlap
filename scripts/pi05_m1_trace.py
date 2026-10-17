"""One short Nsight Systems capture of M1 eager Context, Expert, and serial paths."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import torch

from flash_rt.frontends.torch.pi05_rtx import Pi05TorchFrontendRtx
from flash_rt.models.pi05.pipeline_rtx import ENC_D, ENC_L, VIS_D

CHECKPOINT = Path('/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5')
FIXTURE = Path('/tmp/cooverlap_pi05_fixed_reference.npz')
PROMPT = 'pick up the black bowl and place it on the plate'


def main():
    out = Path(os.environ['COOVERLAP_RUN_DIR'])
    out.mkdir(parents=True, exist_ok=False)
    config = json.loads((CHECKPOINT / 'config.json').read_text())
    assert (config['chunk_size'], config['num_inference_steps'], config['state_cond']) == (50, 10, False)
    fixture = np.load(FIXTURE, allow_pickle=False)
    obs = {k: fixture[k] for k in ('image', 'wrist_image', 'state')}
    f = Pi05TorchFrontendRtx(CHECKPOINT, num_views=2, chunk_size=50, num_steps=10,
                             hardware='rtx_sm87', state_prompt_mode='exact')
    t0 = time.monotonic_ns()
    f.set_prompt(PROMPT, state=obs['state'])
    f.calibrate(obs)  # May execute/capture graphs; excluded from all samples.
    cold_ns = time.monotonic_ns() - t0
    p = f.pipeline
    assert p and ENC_L == 18 and p.encoder_seq_len == 561
    assert not p.use_fp8 and not p.use_int8_encoder
    assert f.current_prompt_len == int(fixture['prompt_tokens']) == 49
    stream = f._graph_torch_stream
    stream_ptr = stream.cuda_stream
    assert stream_ptr != 0
    decoder_calls=[]
    original_decoder_steps=p.transformer_decoder_steps
    def observed_decoder_steps(step_lo,step_hi,*args,**kwargs):
        decoder_calls.append((step_lo,step_hi))
        return original_decoder_steps(step_lo,step_hi,*args,**kwargs)
    p.transformer_decoder_steps=observed_decoder_steps
    images = f._stack_images(obs)
    noise = torch.from_numpy(fixture['noise0_bf16_bytes'].copy()).to('cuda').view(torch.bfloat16).reshape(50, 32)
    assert images.shape == (2, 224, 224, 3)
    meta = dict(script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                fixture_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                config_sha256=hashlib.sha256((CHECKPOINT/'config.json').read_bytes()).hexdigest(),
                checkpoint=str(CHECKPOINT), torch_version=torch.__version__,
                cuda_runtime=torch.version.cuda, device=torch.cuda.get_device_name(0),
                stream_ptr=stream_ptr, graph_stream_ptr=int(p._graph_stream.value),
                cold_init_ns=cold_ns, warmup_per_mode=1, samples_per_mode=1,
                precision='BF16', views=2, prompt_tokens=49, encoder_seq_len=561,
                encoder_layers=18, action_length=50, denoise_steps=10)
    assert meta['stream_ptr'] == meta['graph_stream_ptr']
    (out/'config.json').write_text(json.dumps(meta, indent=2))

    def stage():
        t = time.monotonic_ns()
        with torch.cuda.stream(stream):
            f._copy_tensor_to_pipeline_buf_stream(images, p.input_images_buf, stream_ptr)
            f._copy_tensor_to_pipeline_buf_stream(noise, p.input_noise_buf, stream_ptr)
        stream.synchronize()
        return time.monotonic_ns()-t

    def b1():
        p._copy_lang_embeds_to_encoder_x(stream=stream_ptr)
        p.vision_encoder(stream_ptr)
        b,w,fvk,gemm = p.bufs,p.weights,p.fvk,p.gemm
        vs=p.vision_seq_enc
        fvk.layer_norm(b['vision_x_pooled'].ptr.value,w['vision_final_norm_w'],
                       w['vision_final_norm_b'],b['vision_x_norm'].ptr.value,
                       vs,VIS_D,1e-5,stream=stream_ptr)
        gemm.bf16_nn(b['vision_x_norm'].ptr.value,w['encoder_multi_modal_projector_w'],
                     b['encoder_x'].ptr.value,vs,ENC_D,VIS_D,stream=stream_ptr)
        fvk.add_bias_bf16(b['encoder_x'].ptr.value,w['encoder_multi_modal_projector_b'],
                          vs,ENC_D,stream=stream_ptr)
        for i in range(9): p._encoder_layer(i,p.encoder_seq_len,False,stream_ptr)

    def b2():
        for i in range(9,18): p._encoder_layer(i,p.encoder_seq_len,False,stream_ptr)

    def expert(): p.transformer_decoder(stream_ptr)

    def measure(label, fn, prepare, idx, warmup, log):
        prep_start=time.monotonic_ns()
        input_copy_ns=prepare()
        prep_ns=time.monotonic_ns()-prep_start
        start=torch.cuda.Event(enable_timing=True)
        end=torch.cuda.Event(enable_timing=True)
        wall_start=time.monotonic_ns()
        torch.cuda.nvtx.range_push(label)
        with torch.cuda.stream(stream):
            start.record(stream)
            submit_start=time.monotonic_ns()
            fn()
            submit_end=time.monotonic_ns()
            end.record(stream)
        wait_start=time.monotonic_ns()
        end.synchronize()
        wall_end=time.monotonic_ns()
        torch.cuda.nvtx.range_pop()
        rc=f._cudart.cudaGetLastError()
        rec=dict(mode=label,index=idx,warmup=warmup,gpu_ms=start.elapsed_time(end),
                 cpu_submit_ns=submit_end-submit_start,cpu_event_wait_ns=wall_end-wait_start,
                 cpu_wall_ns=wall_end-wall_start,prepare_ns=prep_ns,input_copy_ns=input_copy_ns,
                 start_ns=wall_start,finish_ns=wall_end,cuda_last_error=int(rc),
                 decoder_calls=list(decoder_calls))
        decoder_calls.clear()
        log.write(json.dumps(rec,sort_keys=True)+'\n'); log.flush(); os.fsync(log.fileno())
        print(json.dumps(rec,sort_keys=True),flush=True)
        if rc != 0: raise RuntimeError(f'CUDA last error {rc}')

    def prep_b1(): return stage()
    def prep_b2():
        copy=stage()
        with torch.cuda.stream(stream): b1()
        stream.synchronize()
        return copy
    def prep_expert():
        copy=stage()
        with torch.cuda.stream(stream): b1(); b2()
        stream.synchronize()
        return copy

    def context():
        torch.cuda.nvtx.range_push('Block1')
        b1()
        torch.cuda.nvtx.range_pop()
        torch.cuda.nvtx.range_push('Block2')
        b2()
        torch.cuda.nvtx.range_pop()

    def marked_expert():
        torch.cuda.nvtx.range_push('Expert_10_steps')
        expert()
        torch.cuda.nvtx.range_pop()

    def serial(): context(); marked_expert()

    modes=[('context',context,prep_b1),('expert',marked_expert,prep_expert),
           ('serial',serial,prep_b1)]
    # One untraced warmup per mode, then one bounded capture range around the
    # three measured executions. No model math or capture order is changed.
    for label,fn,prepare in modes:
        prepare()
        with torch.cuda.stream(stream): fn()
        stream.synchronize()
    with (out/'samples.jsonl').open('x') as log:
        torch.cuda.nvtx.range_push('M1_TRACE')
        for label,fn,prepare in modes:
            measure(label,fn,prepare,0,False,log)
        torch.cuda.nvtx.range_pop()
    print(json.dumps(dict(status='PASS',max_memory_allocated=torch.cuda.max_memory_allocated())),flush=True)

if __name__ == '__main__': main()
