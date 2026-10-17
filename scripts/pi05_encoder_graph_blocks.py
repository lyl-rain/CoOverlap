"""Day 2E single-version Pi0.5 Encoder graph split correctness probe.

No FlashRT source changes. No concurrency, timing claim, or scheduler.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch

from flash_rt.frontends.torch.pi05_rtx import Pi05TorchFrontendRtx
from flash_rt.models.pi05.pipeline_rtx import ENC_D, ENC_L, VIS_D
from flash_rt.subgraphs.capture import capture_graph
from flash_rt.subgraphs.pi05.context_denoise_groups import enable
from flash_rt.core.utils.actions import unnormalize_actions

CKPT = Path('/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5')
FIXTURE = Path('/tmp/cooverlap_pi05_fixed_reference.npz')
PROMPT = 'pick up the black bowl and place it on the plate'
OUTPUT = Path('/tmp/cooverlap_pi05_encoder_graph_blocks.npz')


def compare(name, a, b):
    assert a.shape == b.shape
    af, bf = a.float().cpu().numpy(), b.float().cpu().numpy()
    d = np.abs(af-bf)
    result = dict(name=name, shape=list(a.shape), exact=bool(torch.equal(a,b)),
                  finite=bool(np.isfinite(af).all() and np.isfinite(bf).all()),
                  max_abs=float(d.max()),
                  max_rel=float((d/np.maximum(np.abs(bf),1e-6)).max()))
    print(json.dumps(result,sort_keys=True),flush=True)
    if not result['exact'] or not result['finite']:
        raise AssertionError(f'{name} is not bitwise equal and finite')


def main():
    cfg=json.loads((CKPT/'config.json').read_text())
    assert (cfg['chunk_size'],cfg['num_inference_steps'],cfg['state_cond'])==(50,10,False)
    f=np.load(FIXTURE,allow_pickle=False)
    obs={k:f[k] for k in ('image','wrist_image','state')}
    noise=torch.from_numpy(f['noise0_bf16_bytes'].copy()).to('cuda').view(torch.bfloat16).reshape(50,32)
    frontend=Pi05TorchFrontendRtx(CKPT,num_views=2,chunk_size=50,num_steps=10,
                                  hardware='rtx_sm87',state_prompt_mode='exact')
    enable(frontend,num_groups=2)  # Day 2B reference used this capture setup.
    frontend.set_prompt(PROMPT,state=obs['state'])
    frontend.calibrate(obs)
    p=frontend.pipeline
    assert p and p._graph and p._decoder_only_graph and ENC_L==18
    assert not p.use_fp8 and not p.use_int8_encoder and p.num_steps==10
    assert frontend.current_prompt_len==int(f['prompt_tokens'])
    stream=frontend._graph_torch_stream
    stream_int=stream.cuda_stream
    handle=ctypes.c_void_p(stream_int)
    assert stream_int!=0 and int(p._graph_stream.value)==stream_int
    print(json.dumps(dict(capture_stream=stream_int,producer_stream=int(p._graph_stream.value),
                          device=torch.cuda.get_device_name(),precision='BF16',
                          prompt_tokens=frontend.current_prompt_len,
                          encoder_seq_len=p.encoder_seq_len),sort_keys=True),flush=True)
    fixed_ptrs=(p.bufs['encoder_x'].ptr.value,p._attn_ptrs['enc_K'],p._attn_ptrs['enc_V'])
    def check_cuda(label):
        rc=frontend._cudart.cudaGetLastError()
        print(json.dumps(dict(cuda_check=label,code=int(rc)),sort_keys=True),flush=True)
        if rc!=0: raise RuntimeError(f'{label}: cudaGetLastError={rc}')
    images=frontend._stack_images(obs)
    assert images.shape==(2,224,224,3) and images.dtype==torch.bfloat16

    def read_ptr(ptr,nbytes):
        out=torch.empty(nbytes,dtype=torch.uint8,device='cuda')
        rc=frontend._cudart.cudaMemcpyAsync(ctypes.c_void_p(out.data_ptr()),
                ctypes.c_void_p(ptr),nbytes,3,stream_int)
        if rc!=0: raise RuntimeError(f'cudaMemcpyAsync failed: {rc}')
        stream.synchronize()
        return out.clone()

    def stage():
        with torch.cuda.stream(stream):
            frontend._copy_tensor_to_pipeline_buf_stream(images,p.input_images_buf,stream_int)
            frontend._copy_tensor_to_pipeline_buf_stream(noise,p.input_noise_buf,stream_int)
        stream.synchronize()
        assert torch.equal(read_ptr(p.input_noise_buf.ptr.value,noise.numel()*2),
                           noise.view(torch.uint8).flatten())

    def snapshot(layers=18,rows=None):
        if rows is None: rows=p.encoder_seq_len+50
        with torch.cuda.stream(stream):
            k=frontend.attn_backend.enc_K[:layers,:rows].contiguous().view(torch.uint8).flatten().clone()
            v=frontend.attn_backend.enc_V[:layers,:rows].contiguous().view(torch.uint8).flatten().clone()
        stream.synchronize()
        x=read_ptr(p.bufs['encoder_x'].ptr.value,p.encoder_seq_len*ENC_D*2)
        return x,k,v

    def action():
        return read_ptr(p.input_noise_buf.ptr.value,noise.numel()*2)

    # A. Producer's original full graph.
    stage(); p._graph.replay(handle); stream.synchronize()
    full_final=snapshot(); full_action=action()
    expected=torch.from_numpy(f['reference_raw_bf16_bytes'].copy()).to('cuda').flatten()
    compare('A_full_vs_Day2B_reference_bytes',full_action,expected)

    # B. The Day 2C Python sequential two-block path, with layer audit.
    orig=p._encoder_layer
    calls=[]
    def counted(i,seq,fuse_b1,stream):
        calls.append(i); orig(i,seq,fuse_b1,stream)
    def block1():
        assert torch.cuda.current_stream().cuda_stream==stream_int
        p._copy_lang_embeds_to_encoder_x(stream=stream_int)
        p.vision_encoder(stream_int)
        B,W,fvk,gemm=p.bufs,p.weights,p.fvk,p.gemm
        vs=p.vision_seq_enc
        fvk.layer_norm(B['vision_x_pooled'].ptr.value,W['vision_final_norm_w'],
                       W['vision_final_norm_b'],B['vision_x_norm'].ptr.value,
                       vs,VIS_D,1e-5,stream=stream_int)
        gemm.bf16_nn(B['vision_x_norm'].ptr.value,W['encoder_multi_modal_projector_w'],
                     B['encoder_x'].ptr.value,vs,ENC_D,VIS_D,stream=stream_int)
        fvk.add_bias_bf16(B['encoder_x'].ptr.value,W['encoder_multi_modal_projector_b'],
                          vs,ENC_D,stream=stream_int)
        for i in range(9): counted(i,p.encoder_seq_len,False,stream_int)
    def block2():
        assert torch.cuda.current_stream().cuda_stream==stream_int
        for i in range(9,18): counted(i,p.encoder_seq_len,False,stream_int)

    stage()
    with torch.cuda.stream(stream): block1()
    stream.synchronize(); python_mid=snapshot(layers=9,rows=p.encoder_seq_len)
    with torch.cuda.stream(stream): block2()
    stream.synchronize(); python_context=snapshot(layers=18,rows=p.encoder_seq_len)
    p._decoder_only_graph.replay(handle); stream.synchronize()
    python_final=snapshot(); python_action=action()
    assert calls==list(range(18)),calls
    for name,a,b in zip(('B_final_x','B_final_K','B_final_V'),python_final,full_final):
        compare(name,a,b)
    compare('B_python_action',python_action,full_action)
    print(json.dumps(dict(python_layer_indices=calls,python_mid_x_bytes=python_mid[0].numel(),
                          python_mid_valid_K_bytes=python_mid[1].numel()),sort_keys=True),flush=True)

    # C. Two independent CUDA graph instances, captured on the same explicit
    # Torch stream. Existing helper uses a shared allocator pool for subgraphs.
    calls.clear()
    with torch.cuda.stream(stream):
        graph1=capture_graph(p,handle,block1,warmups=3)
    check_cuda('capture_block1')
    assert calls==list(range(9))*4,('block1 capture/warmup layer audit',calls)
    print(json.dumps(dict(graph='block1',captured=graph1.captured,
                          capture_memory_delta_bytes=graph1.capture_memory_delta_bytes,
                          capture_body_layers=list(range(9))),sort_keys=True),flush=True)
    calls.clear()
    # Restore a valid layer-8 boundary before block2 capture. Block2 warmups
    # are managed here because repeating it alone would consume stale x.
    with torch.cuda.stream(stream):
        for _ in range(3):
            block1(); block2()
        block1()
        graph2=capture_graph(p,handle,block2,warmups=0)
    stream.synchronize()
    check_cuda('capture_block2')
    assert calls==list(range(18))*3+list(range(9))+list(range(9,18)),calls
    print(json.dumps(dict(graph='block2',captured=graph2.captured,
                          capture_memory_delta_bytes=graph2.capture_memory_delta_bytes,
                          capture_body_layers=list(range(9,18))),sort_keys=True),flush=True)
    calls.clear()

    mid_first=None
    outputs=[]
    for trial in range(2):
        stage()
        graph1.replay(handle)
        done1=torch.cuda.Event(enable_timing=False)
        done1.record(stream)
        stream.synchronize()
        check_cuda(f'block1_replay_{trial}')
        assert done1.query(), 'Block1 completion event not complete'
        mid=snapshot(layers=9,rows=p.encoder_seq_len)
        for name,a,b in zip(('C_mid_x','C_mid_K','C_mid_V'),mid,python_mid):
            compare(f'{name}_trial{trial}',a,b)
        if trial==0: mid_first=mid
        if trial==1:
            for name,a,b in zip(('C_repeat_mid_x','C_repeat_mid_K','C_repeat_mid_V'),mid,mid_first):
                compare(name,a,b)
        # Controlled pause represents persistence, not a periodic deadline test.
        time.sleep(0.05)
        stream.wait_event(done1)
        graph2.replay(handle)
        done2=torch.cuda.Event(enable_timing=False)
        done2.record(stream)
        stream.synchronize()
        check_cuda(f'block2_replay_{trial}')
        assert done2.query(), 'Block2 completion event not complete'
        final_context=snapshot(layers=18,rows=p.encoder_seq_len)
        for name,a,b in zip(('C_encoder_x','C_encoder_K','C_encoder_V'),
                            final_context,python_context):
            compare(f'{name}_trial{trial}',a,b)
        p._decoder_only_graph.replay(handle); stream.synchronize()
        check_cuda(f'decoder_replay_{trial}')
        out=action(); outputs.append(out)
        final=snapshot()
        for name,a,b in zip(('C_final_x','C_final_K','C_final_V'),final,full_final):
            compare(f'{name}_trial{trial}',a,b)
        compare(f'C_action_trial{trial}',out,full_action)
        print(json.dumps(dict(trial=trial,block1_event_complete=done1.query(),
                              block2_event_complete=done2.query(),
                              graph_replay_python_layer_calls=calls),sort_keys=True),flush=True)
    compare('C_repeat_action',outputs[1],outputs[0])
    assert fixed_ptrs==(p.bufs['encoder_x'].ptr.value,p._attn_ptrs['enc_K'],p._attn_ptrs['enc_V'])
    action_np=unnormalize_actions(outputs[0].view(torch.bfloat16).float().reshape(50,32).cpu().numpy(),
                                  frontend.norm_stats)[:,:7]
    expected_actions=f['reference_actions']
    assert np.array_equal(action_np,expected_actions)
    np.savez_compressed(OUTPUT,raw_action_bf16_bytes=outputs[0].cpu().numpy(),
                        actions=action_np,mid_encoder_x=mid_first[0].cpu().numpy(),
                        mid_K=mid_first[1].cpu().numpy(),mid_V=mid_first[2].cpu().numpy())
    print(json.dumps(dict(status='PASS',graph1=True,graph2=True,decoder_graph=True,
                          sequential_layers=list(range(18)),raw_shape=[50,32],action_shape=[50,7],
                          event_checks=True,replay_count=2,
                          max_memory_allocated=torch.cuda.max_memory_allocated(),
                          output=str(OUTPUT)),sort_keys=True),flush=True)


if __name__=='__main__': main()
