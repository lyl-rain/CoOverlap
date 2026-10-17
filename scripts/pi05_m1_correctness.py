"""M1 eager full-vs-two-block correctness; graph reference is diagnostic only.

Run only on the approved AGX after checking memory and other GPU jobs. This
does not change FlashRT source or implement a cross-period scheduler.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import torch

from flash_rt.frontends.torch.pi05_rtx import Pi05TorchFrontendRtx
from flash_rt.models.pi05.pipeline_rtx import ENC_D, ENC_L, VIS_D
from flash_rt.core.utils.actions import unnormalize_actions


CHECKPOINT = Path('/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5')
PROMPT = 'pick up the black bowl and place it on the plate'
FIXTURE = Path('/tmp/cooverlap_pi05_fixed_reference.npz')


def check_equal(name, a, b):
    af, bf = a.float().cpu().numpy(), b.float().cpu().numpy()
    delta = np.abs(af - bf)
    result = dict(name=name, shape=list(a.shape), finite=bool(np.isfinite(af).all()),
                  exact=bool(torch.equal(a, b)), max_abs=float(delta.max()),
                  max_rel=float((delta / np.maximum(np.abs(bf), 1e-6)).max()))
    print(json.dumps(result, sort_keys=True), flush=True)
    if not result['finite'] or not result['exact']:
        raise AssertionError(f'{name}: exact equality failed')


def main():
    outdir = Path(os.environ['COOVERLAP_RUN_DIR'])
    outdir.mkdir(parents=True, exist_ok=False)
    config = json.loads((CHECKPOINT / 'config.json').read_text())
    assert (config['chunk_size'], config['num_inference_steps'], config['state_cond']) == (50, 10, False)
    fixture = np.load(FIXTURE, allow_pickle=False)
    obs = {k: fixture[k] for k in ('image', 'wrist_image', 'state')}
    frontend = Pi05TorchFrontendRtx(CHECKPOINT, num_views=2, chunk_size=50, num_steps=10,
                                    hardware='rtx_sm87', state_prompt_mode='exact')
    frontend.set_prompt(PROMPT, state=obs['state'])
    frontend.calibrate(obs)
    p = frontend.pipeline
    assert p and not p.use_fp8 and not p.use_int8_encoder and ENC_L == 18
    assert frontend.current_prompt_len == int(fixture['prompt_tokens'])
    stream = frontend._graph_torch_stream
    stream_int = stream.cuda_stream
    images = frontend._stack_images(obs)
    noise = torch.from_numpy(fixture['noise0_bf16_bytes'].copy()).to('cuda').view(torch.bfloat16).reshape(50, 32)
    assert images.shape == (2, 224, 224, 3)

    def read_ptr(ptr, nbytes):
        out = torch.empty(nbytes, dtype=torch.uint8, device='cuda')
        rc = frontend._cudart.cudaMemcpyAsync(ctypes.c_void_p(out.data_ptr()),
                ctypes.c_void_p(ptr), nbytes, 3, stream_int)
        if rc != 0:
            raise RuntimeError(f'cudaMemcpyAsync failed: {rc}')
        stream.synchronize()
        return out.clone()

    def stage():
        with torch.cuda.stream(stream):
            frontend._copy_tensor_to_pipeline_buf_stream(images, p.input_images_buf, stream_int)
            frontend._copy_tensor_to_pipeline_buf_stream(noise, p.input_noise_buf, stream_int)
        stream.synchronize()
        assert torch.equal(read_ptr(p.input_noise_buf.ptr.value, noise.numel() * 2),
                           noise.view(torch.uint8).flatten())

    enc_bytes = p.encoder_seq_len * ENC_D * 2
    def snapshot(layers=18, rows=None):
        if rows is None:
            rows = p.encoder_seq_len + 50
        with torch.cuda.stream(stream):
            k = frontend.attn_backend.enc_K[:layers, :rows].contiguous().view(torch.uint8).flatten().clone()
            v = frontend.attn_backend.enc_V[:layers, :rows].contiguous().view(torch.uint8).flatten().clone()
        stream.synchronize()
        return (read_ptr(p.bufs['encoder_x'].ptr.value, enc_bytes), k, v)

    # Full original method, instrumented only to observe its layer-8 boundary.
    orig = p._encoder_layer
    full_calls = []
    mid_full = []
    def observe(i, seq, fuse_b1, stream):
        full_calls.append(i)
        orig(i, seq, fuse_b1, stream)
        if i == 8:
            mid_full.append(snapshot(layers=9, rows=p.encoder_seq_len))
    stage()
    p._encoder_layer = observe
    try:
        p.run_pipeline(stream_int)
        stream.synchronize()
    finally:
        p._encoder_layer = orig
    full_final = snapshot()
    full_action = read_ptr(p.input_noise_buf.ptr.value, noise.numel() * 2)
    assert full_calls == list(range(18)) and len(mid_full) == 1

    # Block 1 = original vision + projection + encoder layers 0..8.
    stage()
    p._copy_lang_embeds_to_encoder_x(stream=stream_int)
    p.vision_encoder(stream_int)
    B, W, fvk, gemm = p.bufs, p.weights, p.fvk, p.gemm
    vs = p.vision_seq_enc
    fvk.layer_norm(B['vision_x_pooled'].ptr.value, W['vision_final_norm_w'],
                   W['vision_final_norm_b'], B['vision_x_norm'].ptr.value,
                   vs, VIS_D, 1e-5, stream=stream_int)
    gemm.bf16_nn(B['vision_x_norm'].ptr.value, W['encoder_multi_modal_projector_w'],
                 B['encoder_x'].ptr.value, vs, ENC_D, VIS_D, stream=stream_int)
    fvk.add_bias_bf16(B['encoder_x'].ptr.value, W['encoder_multi_modal_projector_b'],
                      vs, ENC_D, stream=stream_int)
    split_calls = []
    for i in range(0, 9):
        split_calls.append(i)
        orig(i, p.encoder_seq_len, fuse_b1=False, stream=stream_int)
    stream.synchronize()
    mid_split = snapshot(layers=9, rows=p.encoder_seq_len)
    for label, a, b in zip(('mid_encoder_x', 'mid_K', 'mid_V'), mid_split, mid_full[0]):
        check_equal(label, a, b)
    # Block 2 = remaining original encoder layers 9..17, then original decoder.
    for i in range(9, 18):
        split_calls.append(i)
        orig(i, p.encoder_seq_len, fuse_b1=False, stream=stream_int)
    p.transformer_decoder(stream_int)
    stream.synchronize()
    split_final = snapshot()
    split_action = read_ptr(p.input_noise_buf.ptr.value, noise.numel() * 2)
    assert split_calls == full_calls == list(range(18))
    for label, a, b in zip(('final_encoder_x', 'final_K', 'final_V'), split_final, full_final):
        check_equal(label, a, b)
    check_equal('raw_action_bytes', split_action, full_action)
    expected_bytes = torch.from_numpy(fixture['reference_raw_bf16_bytes'].copy()).to('cuda').flatten()
    graph_reference_exact = bool(torch.equal(full_action, expected_bytes))
    print(json.dumps(dict(name='prior_graph_reference_diagnostic', exact=graph_reference_exact,
                          full_sha256=hashlib.sha256(full_action.cpu().numpy().tobytes()).hexdigest(),
                          reference_sha256=hashlib.sha256(expected_bytes.cpu().numpy().tobytes()).hexdigest())), flush=True)
    outdir.joinpath('eager_full_raw_bf16.bin').write_bytes(full_action.cpu().numpy().tobytes())
    outdir.joinpath('eager_split_raw_bf16.bin').write_bytes(split_action.cpu().numpy().tobytes())
    raw_full = full_action.view(torch.bfloat16).reshape(50, 32)
    raw_split = split_action.view(torch.bfloat16).reshape(50, 32)
    actions_full = unnormalize_actions(raw_full.float().cpu().numpy(), frontend.norm_stats)[:, :7]
    actions_split = unnormalize_actions(raw_split.float().cpu().numpy(), frontend.norm_stats)[:, :7]
    assert np.array_equal(actions_full, actions_split)
    print(json.dumps(dict(status='PASS', layers=split_calls, prompt_tokens=frontend.current_prompt_len,
                          encoder_seq_len=p.encoder_seq_len, action_shape=list(actions_split.shape),
                          max_memory_allocated=torch.cuda.max_memory_allocated())), flush=True)


if __name__ == '__main__':
    main()
