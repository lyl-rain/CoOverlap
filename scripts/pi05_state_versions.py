"""Short S0/S1 Pi0.5 state/KV semantics probe; no FlashRT source changes."""
from __future__ import annotations

import ctypes
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from flash_rt.frontends.torch.pi05_rtx import Pi05TorchFrontendRtx
from flash_rt.core.utils.actions import unnormalize_actions

CKPT = Path('/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5')
FIXTURE = Path('/tmp/cooverlap_pi05_fixed_reference.npz')
OUTPUT = Path('/tmp/cooverlap_pi05_state_versions.npz')
PROMPT = 'pick up the black bowl and place it on the plate'


def digest(x):
    return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()


def compare(name, a, b):
    aa = a.view(torch.bfloat16).float().cpu().numpy()
    bb = b.view(torch.bfloat16).float().cpu().numpy()
    d = np.abs(aa-bb)
    result = dict(name=name, exact=bool(torch.equal(a,b)),
                  max_abs=float(d.max()), max_rel=float((d/np.maximum(np.abs(bb),1e-6)).max()),
                  finite=bool(np.isfinite(aa).all() and np.isfinite(bb).all()))
    print(json.dumps(result,sort_keys=True),flush=True)
    return result


def main():
    cfg=json.loads((CKPT/'config.json').read_text())
    assert (cfg['chunk_size'],cfg['num_inference_steps'],cfg['state_cond']) == (50,10,False)
    f=np.load(FIXTURE,allow_pickle=False)
    s0=f['state'].copy()
    s1=s0.copy(); s1[0]=np.float32(s0[0]+0.5)
    assert not np.array_equal(s0,s1)
    image=f['image'].copy(); wrist=f['wrist_image'].copy()
    obs0=dict(image=image,wrist_image=wrist,state=s0)
    obs1=dict(image=image,wrist_image=wrist,state=s1)
    noise=torch.from_numpy(f['noise0_bf16_bytes'].copy()).to('cuda').view(torch.bfloat16).reshape(50,32)
    frontend=Pi05TorchFrontendRtx(CKPT,num_views=2,chunk_size=50,num_steps=10,
                                  hardware='rtx_sm87',state_prompt_mode='exact')
    stream=None
    stream_int=0
    stream_handle=None

    def read_ptr(ptr,nbytes):
        out=torch.empty(nbytes,dtype=torch.uint8,device='cuda')
        rc=frontend._cudart.cudaMemcpyAsync(ctypes.c_void_p(out.data_ptr()),
                ctypes.c_void_p(ptr),nbytes,3,stream_int)
        if rc!=0: raise RuntimeError(f'cudaMemcpyAsync D2D failed {rc}')
        stream.synchronize()
        return out.clone()

    def prompt_snapshot():
        p=frontend.pipeline
        emb=read_ptr(p._lang_embeds_buf.ptr.value,p._lang_embeds_buf.nbytes)
        return dict(tokens=int(frontend.current_prompt_len),
                    embeddings_sha256=digest(emb.cpu().numpy()),encoder_seq=int(p.encoder_seq_len))

    def stage(p):
        images=frontend._stack_images(obs0)
        with torch.cuda.stream(stream):
            frontend._copy_tensor_to_pipeline_buf_stream(images,p.input_images_buf,stream_int)
            frontend._copy_tensor_to_pipeline_buf_stream(noise,p.input_noise_buf,stream_int)
        stream.synchronize()
        assert torch.equal(read_ptr(p.input_noise_buf.ptr.value,noise.numel()*2),noise.view(torch.uint8).flatten())

    def prefix_digest(p):
        with torch.cuda.stream(stream):
            k=frontend.attn_backend.enc_K[:,:p.encoder_seq_len].contiguous().view(torch.uint8).cpu().numpy().copy()
            v=frontend.attn_backend.enc_V[:,:p.encoder_seq_len].contiguous().view(torch.uint8).cpu().numpy().copy()
        stream.synchronize()
        return digest(k),digest(v)

    def execute(label,p,kind):
        stage(p)
        if kind=='full': p._graph.replay(stream_handle)
        elif kind=='decoder': p._decoder_only_graph.replay(stream_handle)
        else: raise ValueError(kind)
        stream.synchronize()
        raw=read_ptr(p.input_noise_buf.ptr.value,noise.numel()*2)
        assert torch.isfinite(raw.view(torch.bfloat16).float()).all()
        actions=unnormalize_actions(raw.view(torch.bfloat16).float().reshape(50,32).cpu().numpy(),frontend.norm_stats)[:,:7]
        assert actions.shape==(50,7) and np.isfinite(actions).all()
        print(json.dumps(dict(case=label,graph=kind,raw_sha256=digest(raw.cpu().numpy()),
                              actions_sha256=digest(actions),k_v_sha256=prefix_digest(p)),sort_keys=True),flush=True)
        return raw,actions

    print(json.dumps(dict(state_s0_sha256=digest(s0),state_s1_sha256=digest(s1),
                          state_s0=s0.tolist(),state_s1=s1.tolist(),
                          image_sha256=digest(image),wrist_image_sha256=digest(wrist),
                          noise_sha256=digest(noise.view(torch.uint8).cpu().numpy()),
                          checkpoint=str(CKPT),precision='BF16',denoise_steps=10,chunk=50),sort_keys=True),flush=True)

    frontend.set_prompt(PROMPT,state=s0)
    frontend.calibrate(obs0)
    stream=frontend._graph_torch_stream
    stream_int=stream.cuda_stream
    stream_handle=ctypes.c_void_p(stream_int)
    p0=frontend.pipeline
    assert p0._graph is not None and p0._decoder_only_graph is not None
    m0=prompt_snapshot()
    print('S0_prompt',json.dumps(m0,sort_keys=True),flush=True)
    a_full,a_actions=execute('A_S0_full_reference',p0,'full')
    k0_before=prefix_digest(p0)
    a_decode,_=execute('A_S0_decoder_only',p0,'decoder')
    assert compare('A_decode_vs_S0_full',a_decode,a_full)['exact']
    assert prefix_digest(p0)==k0_before

    # S1 exists as an arrival, but no set_prompt/Context replay occurs. This
    # job is explicitly bound to published S0. Decoder graph alone is replayed.
    b_old,b_actions=execute('B_S1_arrived_bound_to_S0',p0,'decoder')
    assert prefix_digest(p0)==k0_before, 'B unexpectedly modified encoder prefix K/V'
    assert compare('B_old_version_vs_S0_full',b_old,a_full)['exact']

    # C binds S1, changes prompt embeddings and explicitly runs the full graph.
    frontend.set_prompt(PROMPT,state=s1)
    frontend.calibrate(obs1)
    stream=frontend._graph_torch_stream
    stream_int=stream.cuda_stream
    stream_handle=ctypes.c_void_p(stream_int)
    p1=frontend.pipeline
    assert p1._graph is not None and p1._decoder_only_graph is not None
    m1=prompt_snapshot()
    print('S1_prompt',json.dumps(m1,sort_keys=True),flush=True)
    assert m0['embeddings_sha256']!=m1['embeddings_sha256'], 'S1 did not change prompt embeddings'
    c_full,c_actions=execute('C_S1_full_reference',p1,'full')
    k1_after=prefix_digest(p1)
    c_decode,_=execute('C_S1_decoder_only',p1,'decoder')
    assert prefix_digest(p1)==k1_after
    assert compare('C_decode_vs_S1_full',c_decode,c_full)['exact']
    bc=compare('B_old_vs_C_new',b_old,c_full)
    np.savez_compressed(OUTPUT,s0=s0,s1=s1,image=image,wrist_image=wrist,
                        noise_bf16_bytes=noise.view(torch.uint8).cpu().numpy(),
                        a_full_bf16_bytes=a_full.cpu().numpy(),a_decode_bf16_bytes=a_decode.cpu().numpy(),
                        b_old_bf16_bytes=b_old.cpu().numpy(),c_full_bf16_bytes=c_full.cpu().numpy(),
                        c_decode_bf16_bytes=c_decode.cpu().numpy(),
                        a_actions=a_actions,b_actions=b_actions,c_actions=c_actions,
                        s0_tokens=np.array(m0['tokens']),s1_tokens=np.array(m1['tokens']))
    print(json.dumps(dict(status='PASS',A_reference='S0 full',B_bound_version='S0',
                          C_bound_version='S1',B_equals_C=bc['exact'],
                          prompt_token_length_changed=m0['tokens']!=m1['tokens'],
                          output=str(OUTPUT),max_memory_allocated=torch.cuda.max_memory_allocated()),
                     sort_keys=True),flush=True)


if __name__=='__main__': main()
