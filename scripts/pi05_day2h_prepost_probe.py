"""Approved Day 2I pre/post-state probe; no production Graph changes.

One process, at most two replays. No new CUDA graphs or FlashRT source edits.
COOVERLAP_RUN_DIR must name a new, empty directory.
"""
from __future__ import annotations

import ctypes
import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch

from flash_rt.frontends.torch.pi05_rtx import Pi05TorchFrontendRtx
from flash_rt.models.pi05 import pipeline_rtx
from flash_rt.subgraphs.pi05 import context_denoise_groups
from flash_rt.subgraphs.pi05.context_denoise_groups import enable

CKPT = Path('/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5')
FIXTURE = Path('/tmp/cooverlap_pi05_fixed_reference.npz')
PROMPT = 'pick up the black bowl and place it on the plate'
REFERENCE_SHA = '92f1a92b64352cc34010c81c1accd1cb00fcb227d0004f545b87549d5d6c544d'

def sha_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as src:
        for block in iter(lambda: src.read(4*1024*1024),b''): h.update(block)
    return h.hexdigest()

def sha_array(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()

def put_bytes(path: Path, data: bytes) -> None:
    with path.open('xb') as out:
        out.write(data); out.flush(); os.fsync(out.fileno())

def put_json(path: Path, obj: dict) -> None:
    put_bytes(path,(json.dumps(obj,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())

def compare_bf16(current: np.ndarray, reference: np.ndarray) -> dict:
    assert current.shape==reference.shape==(50,64)
    assert current.dtype==reference.dtype==np.uint8
    def decode(a): return (a.view('<u2').astype('<u4') << 16).view('<f4')
    a,b=decode(current),decode(reference)
    mismatch=a.view('<u4')!=b.view('<u4')
    finite=np.isfinite(a)&np.isfinite(b)
    if finite.any():
        difference=np.abs(a[finite]-b[finite]); relative=difference/np.maximum(np.abs(b[finite]),1e-6)
        max_abs=float(np.max(difference)); max_rel=float(np.max(relative))
    else: max_abs=max_rel=None
    positions=np.argwhere(mismatch)
    first=[int(v) for v in positions[0]] if positions.size else None
    return dict(bytes_exact=bool(np.array_equal(current,reference)),
                current_shape_bf16=list(a.shape),reference_shape_bf16=list(b.shape),
                mismatched_elements=int(mismatch.sum()),mismatch_fraction=float(mismatch.mean()),
                first_mismatch=first,max_abs_finite=max_abs,max_rel_finite=max_rel,
                relative_denominator='max(abs(reference), 1e-6)',
                current_nan=int(np.isnan(a).sum()),current_inf=int(np.isinf(a).sum()),
                reference_nan=int(np.isnan(b).sum()),reference_inf=int(np.isinf(b).sum()))

def main() -> None:
    run=Path(os.environ['COOVERLAP_RUN_DIR'])
    run.mkdir(parents=False,exist_ok=False)
    script=Path(__file__).resolve()
    source_paths={
        'frontend':Path(inspect.getfile(Pi05TorchFrontendRtx)).resolve(),
        'pipeline':Path(inspect.getfile(pipeline_rtx)).resolve(),
        'context_groups':Path(inspect.getfile(context_denoise_groups)).resolve(),
    }
    immutable=dict(run_id=run.name,pid=os.getpid(),script=str(script),script_sha256=sha_file(script),
                   checkpoint=str(CKPT),checkpoint_weight_sha256=sha_file(CKPT/'model.safetensors'),
                   checkpoint_config_sha256=sha_file(CKPT/'config.json'),
                   fixture=str(FIXTURE),fixture_sha256=sha_file(FIXTURE),
                   source_sha256={k:sha_file(v) for k,v in source_paths.items()},
                   source_paths={k:str(v) for k,v in source_paths.items()},
                   python=sys.version,torch=torch.__version__,cuda=torch.version.cuda,
                   device=torch.cuda.get_device_name(),byteorder=sys.byteorder,
                   relevant_env={k:os.environ.get(k) for k in
                                 ('FVK_RTX_FA2','FVK_RTX_FA2_SITES','FLASHRT_PI05_USE_EXEC')})
    put_json(run/'provenance.json',immutable)
    assert immutable['fixture_sha256']==REFERENCE_SHA and sys.byteorder=='little'
    f=np.load(FIXTURE,allow_pickle=False)
    assert str(f['prompt'])==PROMPT and int(f['prompt_tokens'])==49
    assert str(f['checkpoint_config_sha256'])==immutable['checkpoint_config_sha256']
    obs={k:f[k] for k in ('image','wrist_image','state')}
    input_info=dict(prompt=PROMPT,prompt_sha256=hashlib.sha256(PROMPT.encode()).hexdigest(),
                    image_sha256=sha_array(obs['image']),wrist_image_sha256=sha_array(obs['wrist_image']),
                    state_sha256=sha_array(obs['state']),noise_sha256=sha_array(f['noise0_bf16_bytes']),
                    reference_raw_sha256=sha_array(f['reference_raw_bf16_bytes']),
                    image_shape=list(obs['image'].shape),wrist_shape=list(obs['wrist_image'].shape),
                    state_shape=list(obs['state'].shape),noise_shape_bf16=[50,32])
    put_json(run/'inputs.json',input_info)
    assert json.loads((CKPT/'config.json').read_text())['num_inference_steps']==10
    noise=torch.from_numpy(f['noise0_bf16_bytes'].copy()).to('cuda').view(torch.bfloat16).reshape(50,32)
    frontend=Pi05TorchFrontendRtx(CKPT,num_views=2,chunk_size=50,num_steps=10,
                                  hardware='rtx_sm87',state_prompt_mode='exact')
    enable(frontend,num_groups=2)
    frontend.set_prompt(PROMPT,state=obs['state'])
    frontend.calibrate(obs)
    p=frontend.pipeline
    assert p and p._graph and p._context_graph and len(p._denoise_group_graphs)==2
    assert p.num_steps==10 and p.chunk_size==50 and not p.use_fp8 and not p.use_fp8_decoder
    assert frontend.current_prompt_len==49 and p.encoder_seq_len==561
    assert p.vision_seq_enc==512 and p.vision_pool_factor==1
    sites=getattr(frontend.attn_backend,'_fa2_sites',None)
    assert isinstance(sites,dict) and set(sites)=={'siglip','encoder','decoder'}
    assert all(type(value) is bool for value in sites.values())
    lang_buf=p._lang_embeds_buf
    rope_buf=p.bufs['encoder_rope_weights']
    vision_buf=p.bufs['vision_x_pooled']
    assert lang_buf.nbytes==49*2048*2
    assert rope_buf.nbytes==561*256*2
    assert vision_buf.nbytes==512*1152*2
    assert vision_buf is p.bufs['vision_x']
    observed_buffers={'lang_embeds':lang_buf,'encoder_rope':rope_buf,'vision_pooled':vision_buf}
    for name,buf in observed_buffers.items():
        assert isinstance(buf.ptr.value,int) and buf.ptr.value>0 and buf.nbytes>0,name
    intervals=[(buf.ptr.value,buf.ptr.value+buf.nbytes,name) for name,buf in observed_buffers.items()]
    intervals.append((p.input_noise_buf.ptr.value,p.input_noise_buf.ptr.value+p.input_noise_buf.nbytes,'action_noise'))
    for idx,(lo,hi,name) in enumerate(intervals):
        assert all(hi<=other_lo or other_hi<=lo for other_lo,other_hi,_ in intervals[idx+1:]),name
    stream=frontend._graph_torch_stream; stream_int=stream.cuda_stream
    assert stream_int and int(p._graph_stream.value)==stream_int
    handle=ctypes.c_void_p(stream_int)
    images=frontend._stack_images(obs)
    assert images.shape==(2,224,224,3) and images.dtype==torch.bfloat16
    image_bytes=images.view(torch.uint8).cpu().numpy()
    capture=dict(enable_groups=2,enable_before_set_prompt=True,graph='producer_full_graph',
                 capture_stream=stream_int,producer_stream=int(p._graph_stream.value),
                 graph_groups=len(p._denoise_group_graphs),effective_precision='BF16',
                 num_views=2,prompt_tokens=49,encoder_seq_len=561,action_length=50,
                 denoise_steps=10,preprocessed_image_shape=list(images.shape),
                 preprocessed_image_dtype=str(images.dtype),preprocessed_image_sha256=sha_array(image_bytes),
                 encoder_x_ptr=int(p.bufs['encoder_x'].ptr.value),
                 enc_k_ptr=int(p._attn_ptrs['enc_K']),enc_v_ptr=int(p._attn_ptrs['enc_V']),
                 attention_sites=dict(sites),observed_buffer_intervals=intervals,
                 vision_pooled_aliases_vision_x=(p.bufs['vision_x_pooled'].ptr.value==p.bufs['vision_x'].ptr.value),
                 vision_pooled_ptr=int(p.bufs['vision_x_pooled'].ptr.value),
                 lang_embeds_ptr=int(p._lang_embeds_buf.ptr.value))
    put_json(run/'capture.json',capture)
    print(json.dumps(dict(phase='capture',**capture),sort_keys=True),flush=True)
    def read(ptr,nbytes):
        out=torch.empty(nbytes,dtype=torch.uint8,device='cuda')
        rc=frontend._cudart.cudaMemcpyAsync(ctypes.c_void_p(out.data_ptr()),ctypes.c_void_p(ptr),nbytes,3,stream_int)
        if rc: raise RuntimeError(f'cudaMemcpyAsync={rc}')
        stream.synchronize()
        return out.cpu().numpy().copy()
    # Read-only state AFTER production Capture and BEFORE first fixed replay.
    # This adds a sync/readback, but no node to the production Graph.
    lang=read(lang_buf.ptr.value,lang_buf.nbytes)
    rope=read(rope_buf.ptr.value,rope_buf.nbytes)
    put_bytes(run/'pre_replay_lang_embeds.bin',lang.tobytes())
    put_bytes(run/'pre_replay_encoder_rope.bin',rope.tobytes())
    put_json(run/'pre_replay_state.json',dict(lang_sha256=sha_array(lang),lang_bytes=len(lang),
                                             rope_sha256=sha_array(rope),rope_bytes=len(rope)))
    for trial in range(2):
        with torch.cuda.stream(stream):
            frontend._copy_tensor_to_pipeline_buf_stream(images,p.input_images_buf,stream_int)
            frontend._copy_tensor_to_pipeline_buf_stream(noise,p.input_noise_buf,stream_int)
        stream.synchronize()
        staged_noise=read(p.input_noise_buf.ptr.value,3200).reshape(50,64)
        staged_images=read(p.input_images_buf.ptr.value,images.numel()*2)
        assert np.array_equal(staged_noise,f['noise0_bf16_bytes'])
        assert sha_array(staged_images)==sha_array(image_bytes)
        p._graph.replay(handle)
        stream.synchronize()  # completed graph before any readback
        raw=read(p.input_noise_buf.ptr.value,3200).reshape(50,64)
        # Persist the raw output before reading another buffer or comparing.
        prefix=f'replay_{trial}'
        put_bytes(run/f'{prefix}_raw_bf16.bin',raw.tobytes())
        output_meta=dict(trial=trial,raw_file=f'{prefix}_raw_bf16.bin',
                         shape_bytes=[50,64],dtype_bytes='uint8',shape_bf16=[50,32],
                         dtype_bf16='little-endian BF16',sha256=sha_array(raw),
                         staged_noise_sha256=sha_array(staged_noise),
                         staged_images_sha256=sha_array(staged_images),
                         cuda_last_error=int(frontend._cudart.cudaGetLastError()))
        put_json(run/f'{prefix}_output.json',output_meta)
        print(json.dumps(dict(phase='raw_saved',**output_meta),sort_keys=True),flush=True)
        # The pooled Vision buffer persists in this model; report it only as
        # post-full-graph state, never as an in-graph layer boundary snapshot.
        vis=read(vision_buf.ptr.value,vision_buf.nbytes)
        put_bytes(run/f'{prefix}_vision_pooled_postgraph.bin',vis.tobytes())
        put_json(run/f'{prefix}_vision_pooled_postgraph.json',
                 dict(sha256=sha_array(vis),nbytes=len(vis),
                      caveat='post-full-graph state; confirm no later writer before interpreting'))
        # Only final post-graph state is observable; no claim about earlier stages.
        # enc_K/V layout: (18,611,1,256) BF16. Rows 0:561 are Encoder,
        # 561:611 are Decoder-written suffix after all ten denoise steps.
        k=read(p._attn_ptrs['enc_K'],18*611*256*2)
        v=read(p._attn_ptrs['enc_V'],18*611*256*2)
        x=read(p.bufs['encoder_x'].ptr.value,561*2048*2)
        for name,array in [('enc_K_postgraph',k),('enc_V_postgraph',v),('encoder_x_postgraph',x)]:
            put_bytes(run/f'{prefix}_{name}.bin',array.tobytes())
        buffers=dict(trial=trial,enc_k_sha256=sha_array(k),enc_v_sha256=sha_array(v),
                     encoder_x_sha256=sha_array(x),enc_k_bytes=len(k),enc_v_bytes=len(v),
                     encoder_x_bytes=len(x),enc_k_v_shape_bf16=[18,611,1,256],
                     enc_k_v_encoder_rows=[0,561],enc_k_v_decoder_suffix_rows=[561,611],
                     caveat='post-full-graph state only; intermediate layer/group values not observable')
        put_json(run/f'{prefix}_buffers.json',buffers)
        comparison=compare_bf16(raw,f['reference_raw_bf16_bytes'])
        put_json(run/f'{prefix}_comparison.json',comparison)
        print(json.dumps(dict(phase='comparison',trial=trial,**comparison),sort_keys=True),flush=True)
        if not comparison['bytes_exact'] or output_meta['cuda_last_error']:
            raise RuntimeError(f'Replay {trial} mismatch or CUDA error; saved data in {run}')
    print(json.dumps(dict(status='PASS',run_id=run.name,peak_allocated=torch.cuda.max_memory_allocated()),sort_keys=True),flush=True)

if __name__=='__main__': main()
