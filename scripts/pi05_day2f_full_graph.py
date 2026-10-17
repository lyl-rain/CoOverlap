"""Day 2F fixed-input full-graph diagnostic; no new encoder graphs."""
import ctypes
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import torch

from flash_rt.frontends.torch.pi05_rtx import Pi05TorchFrontendRtx
from flash_rt.subgraphs.pi05.context_denoise_groups import enable

CKPT = Path('/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5')
FIXTURE = Path('/tmp/cooverlap_pi05_fixed_reference.npz')
PROMPT = 'pick up the black bowl and place it on the plate'

def digest(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()

def bf16_float(b):
    assert b.dtype == np.uint8 and b.shape == (50, 64)
    words = b.view('<u2')
    return (words.astype('<u4') << 16).view('<f4')

def compare(a, b):
    assert a.shape == b.shape == (50,64) and a.dtype == b.dtype == np.uint8
    x, y = bf16_float(a), bf16_float(b)
    d = np.abs(x-y)
    rel = d / np.maximum(np.abs(y), 1e-6)
    idx = np.unravel_index(np.argmax(d), d.shape)
    return dict(bytes_exact=bool(np.array_equal(a,b)), shape_bytes=list(a.shape),
                shape_bf16=list(x.shape), unequal_bf16=int(np.count_nonzero(x.view('<u4') != y.view('<u4'))),
                unequal_fraction=float(np.count_nonzero(x.view('<u4') != y.view('<u4')) / x.size),
                max_abs=float(np.nanmax(d)), max_rel=float(np.nanmax(rel)), max_position=[int(v) for v in idx],
                current_at_max=float(x[idx]), reference_at_max=float(y[idx]),
                current_nan=int(np.isnan(x).sum()), current_inf=int(np.isinf(x).sum()),
                reference_nan=int(np.isnan(y).sum()), reference_inf=int(np.isinf(y).sum()))

def main():
    f=np.load(FIXTURE, allow_pickle=False)
    assert digest(f['reference_raw_bf16_bytes']) == 'b40eeecfeefa3d25a886f2976c988914ff3b590e601bd41a8fe904f0b108691a'
    assert str(f['prompt']) == PROMPT and int(f['prompt_tokens']) == 49
    assert hashlib.sha256((CKPT/'config.json').read_bytes()).hexdigest() == str(f['checkpoint_config_sha256'])
    obs={k:f[k] for k in ('image','wrist_image','state')}
    noise=torch.from_numpy(f['noise0_bf16_bytes'].copy()).to('cuda').view(torch.bfloat16).reshape(50,32)
    print(json.dumps(dict(phase='fixture',pid=os.getpid(),fixture_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                          image_sha256=digest(obs['image']),wrist_sha256=digest(obs['wrist_image']),
                          state_sha256=digest(obs['state']),noise_sha256=digest(f['noise0_bf16_bytes'])),sort_keys=True),flush=True)
    frontend=Pi05TorchFrontendRtx(CKPT,num_views=2,chunk_size=50,num_steps=10,
                                  hardware='rtx_sm87',state_prompt_mode='exact')
    enable(frontend,num_groups=2)
    frontend.set_prompt(PROMPT,state=obs['state'])
    frontend.calibrate(obs)
    p=frontend.pipeline
    assert p and p._graph and p._decoder_only_graph and p._context_graph and len(p._denoise_group_graphs)==2
    assert p.num_steps==10 and p.chunk_size==50 and not p.use_fp8 and not p.use_fp8_decoder
    assert frontend.current_prompt_len==49 and p.encoder_seq_len==561
    s=frontend._graph_torch_stream; si=s.cuda_stream; h=ctypes.c_void_p(si)
    assert si and int(p._graph_stream.value)==si
    images=frontend._stack_images(obs)
    assert images.shape==(2,224,224,3) and images.dtype==torch.bfloat16
    print(json.dumps(dict(phase='capture',capture_stream=si,producer_stream=int(p._graph_stream.value),
                          images_sha256=digest(images.view(torch.uint8).cpu().numpy()),
                          noise_device_sha256=digest(noise.view(torch.uint8).cpu().numpy()),
                          precision='BF16',prompt_tokens=frontend.current_prompt_len,encoder_seq_len=p.encoder_seq_len,
                          torch_version=torch.__version__,cuda_version=torch.version.cuda,
                          graph_groups=len(p._denoise_group_graphs)),sort_keys=True),flush=True)
    def read(ptr,n):
        out=torch.empty(n,dtype=torch.uint8,device='cuda')
        rc=frontend._cudart.cudaMemcpyAsync(ctypes.c_void_p(out.data_ptr()),ctypes.c_void_p(ptr),n,3,si)
        if rc: raise RuntimeError(f'cudaMemcpyAsync={rc}')
        s.synchronize()
        return out.cpu().numpy().copy()
    outputs=[]
    for trial in range(2):
        with torch.cuda.stream(s):
            frontend._copy_tensor_to_pipeline_buf_stream(images,p.input_images_buf,si)
            frontend._copy_tensor_to_pipeline_buf_stream(noise,p.input_noise_buf,si)
        s.synchronize()
        staged=read(p.input_noise_buf.ptr.value,3200).reshape(50,64)
        assert np.array_equal(staged,f['noise0_bf16_bytes'])
        image_staged=read(p.input_images_buf.ptr.value,images.numel()*2)
        assert digest(image_staged)==digest(images.view(torch.uint8).cpu().numpy())
        p._graph.replay(h); s.synchronize()
        raw=read(p.input_noise_buf.ptr.value,3200).reshape(50,64)
        k=read(p._attn_ptrs['enc_K'],512)
        v=read(p._attn_ptrs['enc_V'],512)
        result=dict(phase='replay',trial=trial,raw_sha256=digest(raw),k_prefix_sha256=digest(k),
                    v_prefix_sha256=digest(v),staged_noise_sha256=digest(staged),
                    staged_image_sha256=digest(image_staged),
                    vs_day2b=compare(raw,f['reference_raw_bf16_bytes']),
                    cuda_last_error=int(frontend._cudart.cudaGetLastError()))
        if outputs: result['vs_trial0']=compare(raw,outputs[0])
        print(json.dumps(result,sort_keys=True),flush=True)
        outputs.append(raw)
    path=Path(os.environ.get('COOVERLAP_DIAG_OUTPUT','/tmp/cooverlap_day2f_full_graph.npz'))
    np.savez_compressed(path,trial0_raw_bf16_bytes=outputs[0],trial1_raw_bf16_bytes=outputs[1])
    print(json.dumps(dict(phase='saved',path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          peak_allocated=torch.cuda.max_memory_allocated()),sort_keys=True),flush=True)

if __name__=='__main__': main()
