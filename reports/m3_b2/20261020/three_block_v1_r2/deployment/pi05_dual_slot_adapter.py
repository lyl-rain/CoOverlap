"""Fail-closed Pi0.5 two-slot constructor and device-range inventory.

This is not a concurrency runner. The approved isolated diagnostic runner
provides resource_info(); the installed production runner remains unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

import torch

from flash_rt import flash_rt_kernels as fvk
from flash_rt.core.cuda_buffer import CudaBuffer
from flash_rt.frontends.torch.pi05_rtx import (
    Pi05TorchFrontendRtx, PI05_STATE_PROMPT_MAX_LEN, _embed_prompt,
)
from flash_rt.hardware.rtx.attn_backend import RtxFlashAttnBackend
from flash_rt.models.pi05.pipeline_rtx import ENC_L, VIS_D, VIS_H, BF16, Pi05Pipeline

CHECKPOINT = Path('/home/nvidia/rtvla/checkpoints/vlash_pi05_libero_async5')
PROMPT = 'pick up the black bowl and place it on the plate'


def require_resource_introspection(runner_class=fvk.GemmRunner) -> None:
    if not hasattr(runner_class, 'resource_info'):
        raise RuntimeError(
            'BLOCKED: installed GemmRunner has private cuBLASLt handle and '
            '256 MiB workspace with no read-only pointer/size binding; '
            'see reports/m1_recovery/GEMM_RESOURCE_INFO.patch')


def build_slots(state_s0, state_s1, observation_s0, runner_class=fvk.GemmRunner, on_stage=None):
    """Construct private pipelines/backends/runners around one weight owner.

    Only call after resource introspection is approved and available. The
    caller must still audit all intervals and run sequential correctness.
    """
    require_resource_introspection(runner_class)  # before checkpoint load or GPU model work
    owner = Pi05TorchFrontendRtx(CHECKPOINT, num_views=2, chunk_size=50,
                                 num_steps=10, hardware='rtx_sm87',
                                 state_prompt_mode='exact')
    if on_stage:on_stage('after_weight_owner')
    # Isolated diagnostic runner can be injected without changing production
    # fvk.GemmRunner or its installed extension. No pipeline exists yet.
    owner.gemm = runner_class()
    owner.set_prompt(PROMPT, state=state_s0)
    # This functional harness is entirely eager: no graph calibration/capture.
    # Each slot's original BF16 autotune is performed explicitly by the caller.
    old = owner.pipeline
    if on_stage:on_stage('after_v0_slot')
    assert old and old.encoder_seq_len == 561 and old.num_steps == 10
    assert old.max_prompt_len == 49 and not old.use_fp8 and not old.use_int8_encoder

    new_backend = RtxFlashAttnBackend(num_views=2,
                                      encoder_seq_max=owner.attn_backend._encoder_seq_max,
                                      chunk_size=50, num_encoder_layers=ENC_L)
    new_runner = runner_class()
    new_weights = owner._build_pipeline_weights()  # pointers, no checkpoint reload
    new = Pi05Pipeline(
        gemm=new_runner, fvk=owner.fvk, attn_backend=new_backend,
        weights=new_weights, num_views=2, max_prompt_len=49, chunk_size=50,
        num_steps=10, vision_pool_factor=owner._vision_pool_factor,
        vision_num_layers=owner._vision_num_layers,
        **owner._pipeline_precision_kwargs())
    embeds, prompt_len = _embed_prompt(PROMPT, owner.embedding_weight,
                                      max_len=PI05_STATE_PROMPT_MAX_LEN,
                                      state=state_s1)
    assert prompt_len == 49
    new.set_language_embeds(embeds.contiguous().view(torch.uint16).cpu().numpy())
    # Original _bias_add_bf16 allocates this same persistent zero buffer lazily.
    # Allocate it before the pointer audit so no known BF16 scratch is omitted.
    for pipeline in (old,new):
        pipeline._bias_zero_buf=CudaBuffer.device_zeros(
            max(pipeline.vision_seq*3*VIS_D,pipeline.vision_seq*VIS_H),BF16)
    if on_stage:on_stage('after_v1_slot')
    assert old.attn is owner.attn_backend and new.attn is new_backend
    assert old.gemm is owner.gemm and new.gemm is new_runner
    assert old.weights['encoder_multi_modal_projector_w'] == new.weights['encoder_multi_modal_projector_w']
    return owner, old, new, new_backend, new_runner


def _collect(obj, prefix, seen=None):
    """Find owned Torch tensors/CudaBuffers; preserve aliases in the manifest."""
    if seen is None: seen=set()
    if isinstance(obj, torch.Tensor):
        if obj.device.type == 'cuda':
            storage=obj.untyped_storage()
            lower=upper=obj.storage_offset()
            for size,stride in zip(obj.shape,obj.stride()):
                lower+=min(0,(size-1)*stride)
                upper+=max(0,(size-1)*stride)
            begin=storage.data_ptr()+lower*obj.element_size()
            end=storage.data_ptr()+(upper+1)*obj.element_size() if obj.numel() else begin
            assert storage.data_ptr()<=begin<=end<=storage.data_ptr()+storage.nbytes()
            yield dict(name=prefix,ptr=begin,nbytes=end-begin,
                       first_element_ptr=obj.data_ptr(),logical_nbytes=obj.numel()*obj.element_size(),
                       storage_ptr=storage.data_ptr(),storage_nbytes=storage.nbytes(),
                       storage_offset=obj.storage_offset(),shape=list(obj.shape),stride=list(obj.stride()),
                       dtype=str(obj.dtype),owner=prefix.split('.')[0],writable=True,
                       interval_policy='conservative strided bounding interval')
        return
    if isinstance(obj, CudaBuffer):
        yield dict(name=prefix, ptr=obj.ptr.value, nbytes=obj.nbytes,
                   dtype='CudaBuffer: source-defined', owner=prefix.split('.')[0], writable=True)
        return
    if isinstance(obj, dict):
        for key,value in obj.items():
            yield from _collect(value,f'{prefix}.{key}',seen)
        return
    if isinstance(obj,(tuple,list)):
        for i,value in enumerate(obj):yield from _collect(value,f'{prefix}[{i}]',seen)
        return
    # Inspect only direct attributes of known owner objects, not arbitrary
    # object graphs that may hold shared weights and CUDA runtime objects.
    if prefix in ('v0.pipeline','v1.pipeline','v0.attn','v1.attn'):
        for key,value in vars(obj).items():
            if isinstance(value,(torch.Tensor,CudaBuffer,dict,list,tuple)):
                yield from _collect(value,f'{prefix}.{key}',seen)


def address_manifest(owner, old, new, new_backend, new_runner, validate=True):
    for runner in (owner.gemm,new_runner):
        if not hasattr(runner,'resource_info'):raise RuntimeError('missing resource_info')
    entries=[]
    host_resources=[]
    for label,obj in [('v0.pipeline',old),('v1.pipeline',new),
                      ('v0.attn',owner.attn_backend),('v1.attn',new_backend)]:
        entries.extend(_collect(obj,label))
    for label,runner in [('v0.gemm',owner.gemm),('v1.gemm',new_runner)]:
        info=dict(runner.resource_info())
        if not info.get('workspace_ptr') or not info.get('workspace_bytes') or not info.get('handle_ptr'):
            raise RuntimeError(f'{label}: incomplete GEMM resource metadata')
        entries.append(dict(name=label+'.workspace',ptr=info['workspace_ptr'],
                            nbytes=info['workspace_bytes'],dtype='uint8 workspace',
                            owner=label,writable=True))
        for key in ('scale_a_ptr','scale_b_ptr'):
            entries.append(dict(name=label+'.'+key,ptr=info[key],nbytes=4,
                                dtype='float32',owner=label,writable=True))
        host_resources.append(dict(name=label+'.handle',ptr=info['handle_ptr'],
                            nbytes=None,dtype='host opaque handle',owner=label,
                            writable=True))
    weight_entries=[]
    for key,value in owner._ckpt_bf16.items():
        if isinstance(value,torch.Tensor) and value.device.type=='cuda':
            entry=next(_collect(value,'shared.weights.'+key))
            entry.update(owner='shared.weights',writable=False)
            weight_entries.append(entry)
    # No writable interval may overlap a writable interval from another slot.
    intervals=[x for x in entries if x['nbytes'] and x['ptr']]
    overlaps=[]
    for i,a in enumerate(intervals):
        for b in intervals[i+1:]:
            if a['owner'].split('.')[0] == b['owner'].split('.')[0]:continue
            if max(a['ptr'],b['ptr']) < min(a['ptr']+a['nbytes'],b['ptr']+b['nbytes']):
                overlaps.append(dict(kind='cross_slot_write_write',a=a['name'],b=b['name']))
    for a in intervals:
        for b in weight_entries:
            if max(a['ptr'],b['ptr']) < min(a['ptr']+a['nbytes'],b['ptr']+b['nbytes']):
                overlaps.append(dict(kind='write_readonly',a=a['name'],b=b['name']))
    if validate and overlaps:raise RuntimeError(str(overlaps))
    return dict(writable=entries,host_resources=host_resources,shared_readonly=weight_entries,
                gemm_v0=dict(owner.gemm.resource_info()),
                gemm_v1=dict(new_runner.resource_info()),
                overlaps=overlaps,
                unknown_resources=['cuBLASLt internal context resources and shared-handle semantics',
                                   'extension-internal transient allocations not exposed by owning tensors'],
                public_ranges_disjoint=not overlaps,
                safe_for_concurrent_model=False)


if __name__ == '__main__':
    # Deliberately fail before loading model in the current unpatched build.
    require_resource_introspection()
    print(json.dumps(dict(status='READY_FOR_APPROVED_SEQUENTIAL_HARNESS')))
