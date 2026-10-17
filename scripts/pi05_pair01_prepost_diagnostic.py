"""UNEXECUTED Pair01 pre/post diagnostic proposal. Source/device audit incomplete.
No Block2 after the pair, even if every observed comparison passes.
Set COOVERLAP_SOURCE_AUDIT_COMPLETE=1 only after the documented audit gate.
"""
import ast
import ctypes
import hashlib
import inspect
import json
import os
import textwrap
import time
import traceback
from pathlib import Path

import numpy as np
import torch
import flash_rt_gemm_diag as diag
from pi05_dual_slot_adapter import build_slots, address_manifest, CHECKPOINT, PROMPT
from pi05_dual_slot_adapter import _collect
import pi05_dual_slot_adapter as adapter_module
from flash_rt.models.pi05.pipeline_rtx import Pi05Pipeline, ENC_D, VIS_D
from flash_rt.core.utils.actions import unnormalize_actions

OUT=Path(os.environ['COOVERLAP_RUN_DIR'])
OUT.mkdir(parents=True,exist_ok=False)
report={'status':'INCOMPLETE','checks':[],'memory':{},'events':[], 'ledger':{}}

def save_json(path,obj):
    with path.open('w') as f:json.dump(obj,f,indent=2);f.flush();os.fsync(f.fileno())

def save():save_json(OUT/'result.json',report)

def require(condition,name):
    report['checks'].append(dict(name=name,pass_=bool(condition)));save()
    if not condition:raise AssertionError(name)

def digest(data):return hashlib.sha256(data).hexdigest()

def memory(label):
    free,total=torch.cuda.mem_get_info()
    r=dict(cuda_free=free,cuda_total=total,torch_allocated=torch.cuda.memory_allocated(),
           torch_reserved=torch.cuda.memory_reserved(),torch_peak=torch.cuda.max_memory_allocated(),
           proc={l.split(':')[0]:l.split(':',1)[1].strip() for l in Path('/proc/self/status').read_text().splitlines() if l.startswith(('VmRSS:','VmHWM:'))})
    report['memory'][label]=r;save()
    return r

def store(name,array):
    a=np.ascontiguousarray(array)
    with (OUT/(name+'.bin')).open('xb') as f:f.write(a.tobytes());f.flush();os.fsync(f.fileno())
    meta=dict(shape=list(a.shape),storage_dtype=str(a.dtype),nbytes=a.nbytes,sha256=digest(a.tobytes()))
    save_json(OUT/(name+'.json'),meta)
    return a

def compare(name,a,b,bf16=True):
    exact=a.shape==b.shape and a.dtype==b.dtype and a.tobytes()==b.tobytes()
    if bf16:
        aa=torch.from_numpy(a.copy()).view(torch.bfloat16).float().numpy().flatten()
        bb=torch.from_numpy(b.copy()).view(torch.bfloat16).float().numpy().flatten()
    else:aa=a.astype(np.float32).flatten();bb=b.astype(np.float32).flatten()
    require(aa.shape==bb.shape,name+'_shape')
    delta=np.abs(aa-bb)
    metrics=dict(name=name,exact=exact,finite=bool(np.isfinite(aa).all() and np.isfinite(bb).all()),
                 max_abs=float(delta.max()),max_rel=float((delta/np.maximum(np.abs(bb),1e-6)).max()),
                 mismatch_elements=int(np.count_nonzero(aa!=bb)))
    report.setdefault('comparisons',[]).append(metrics);save()
    if report.get('collect_pair_comparisons'):
        report['checks'].append(dict(name=name+'_exact',pass_=bool(exact and metrics['finite'])));save()
    else:
        require(exact and metrics['finite'],name+'_exact')

def buffer_dtypes(manifest):
    """CudaBuffer has no runtime dtype: record the original allocation source."""
    tree=ast.parse(textwrap.dedent(inspect.getsource(Pi05Pipeline._allocate_buffers)))
    mapping={'valid_encoder_len':'int32','vision_x_pooled':'bfloat16'}
    for node in ast.walk(tree):
        if not isinstance(node,ast.Assign) or not isinstance(node.value,ast.Call):continue
        if not isinstance(node.value.func,ast.Attribute) or node.value.func.attr not in ('device_empty','device_zeros'):continue
        dtype=node.value.args[-1]
        if not isinstance(dtype,ast.Name):continue
        for target in node.targets:
            if isinstance(target,ast.Subscript) and isinstance(target.slice,ast.Constant):
                mapping[target.slice.value]={'BF16':'bfloat16','FP32':'float32','INT8':'int8','FP8':'uint8'}[dtype.id]
    for entry in manifest['writable']:
        if entry['dtype']!='CudaBuffer: source-defined':continue
        name=entry['name']
        if '.bufs.' in name:entry['dtype']=mapping.get(name.split('.bufs.',1)[1],'UNKNOWN')
        elif name.endswith(('_rms_ones_enc','_rms_ones_dec','_lang_embeds_buf','_bias_zero_buf')):entry['dtype']='bfloat16'
        else:entry['dtype']='UNKNOWN'
        entry['dtype_provenance']='original CudaBuffer allocation/input source; object stores bytes only'
    return manifest

def main():
    if os.environ.get('COOVERLAP_SOURCE_AUDIT_COMPLETE')!='1':
        raise RuntimeError('BLOCKED: complete source and device audit before model load')
    loaded=Path(diag.__file__).resolve()
    report.update(extension=str(loaded),extension_sha256=digest(loaded.read_bytes()),
        script_sha256=digest(Path(__file__).read_bytes()),adapter_sha256=digest(Path(adapter_module.__file__).read_bytes()),
        checkpoint=str(CHECKPOINT),pair_limit=1,scope='one traced functional pair; no partitions')
    save()
    require(loaded.parent==Path(os.environ['COOVERLAP_DIAG_ROOT']).resolve()/'lib','isolated_extension_path')
    require(report['extension_sha256']==os.environ['COOVERLAP_DIAG_SHA256'],'isolated_extension_sha')
    fp=Path('/tmp/cooverlap_pi05_fixed_reference.npz');sp=Path('/tmp/cooverlap_pi05_state_versions.npz')
    f=np.load(fp,allow_pickle=False);ss=np.load(sp,allow_pickle=False)
    s0,s1=ss['s0'].copy(),ss['s1'].copy()
    report['inputs']=dict(S0=s0.tolist(),S1=s1.tolist(),S0_sha256=digest(s0.tobytes()),S1_sha256=digest(s1.tobytes()),
        fixture_sha256=digest(fp.read_bytes()),state_fixture_sha256=digest(sp.read_bytes()),
        image_sha256=digest(f['image'].tobytes()),wrist_sha256=digest(f['wrist_image'].tobytes()),
        noise_sha256=digest(f['noise0_bf16_bytes'].tobytes()),prompt=PROMPT)
    save()
    require(np.array_equal(s0,f['state']) and not np.array_equal(s0,s1),'distinct_S0_S1')
    require(report['inputs']['fixture_sha256']=='92f1a92b64352cc34010c81c1accd1cb00fcb227d0004f545b87549d5d6c544d','fixed_fixture_sha')
    require(report['inputs']['state_fixture_sha256']=='cabb191ec2b319c43fa769e5c8b9b8851724ef25ecff8850d118b8276124205e','fixed_state_sha')
    require(digest((CHECKPOINT/'config.json').read_bytes())=='0458a362b574c2cb088ebf3767c9eacb1f040b9cb680a89b594379a4fe36e5f7','fixed_config_sha')
    torch.cuda.set_device(0)
    memory('before_model')
    obs={k:f[k].copy() for k in ('image','wrist_image','state')}
    owner,p0,p1,attn1,runner1=build_slots(s0,s1,obs,diag.GemmRunner,on_stage=memory)
    require(report['memory']['after_v1_slot']['cuda_free']>12*1024**3,'memory_safety_floor')
    for slot,p in [('v0',p0),('v1',p1)]:
        flags={k:getattr(p,k) for k in ('use_fp8','use_fp8_decoder','use_int8_encoder','use_int8_decoder','use_int8_vision')}
        report.setdefault('slots',{})[slot]=dict(flags=flags,seq=p.encoder_seq_len,prompt=p._current_prompt_len,steps=p.num_steps,
            chunk=p.chunk_size,vision_layers=p.vision_num_layers,routes=dict(p.attn._fa2_sites))
        save()
        require(not any(flags.values()) and p.encoder_seq_len==561 and p._current_prompt_len==49 and p.num_steps==10
                and p.chunk_size==50 and p.vision_num_layers==27 and not p._state_active,slot+'_fixed_workload')
        require(all(p.attn._fa2_sites.values()) and not p.attn._fixed_shape,slot+'_vendor_exact_attention')
        require(p._graph is None and p._decoder_only_graph is None,slot+'_no_graph')
    before=buffer_dtypes(address_manifest(owner,p0,p1,attn1,runner1,validate=False))
    save_json(OUT/'address_manifest_before.json',before)
    require(not before['overlaps'] and all(x['dtype']!='UNKNOWN' for x in before['writable']),'visible_ranges_and_dtypes_safe')
    def leaves(x,prefix=''):
        if isinstance(x,dict):return {k:v for name,child in x.items() for k,v in leaves(child,prefix+'.'+name).items()}
        if isinstance(x,(list,tuple)):return {k:v for i,child in enumerate(x) for k,v in leaves(child,prefix+f'[{i}]').items()}
        return {prefix:x} if isinstance(x,int) and x>4096 else {}
    weights0,weights1=leaves(p0.weights),leaves(p1.weights)
    save_json(OUT/'weight_pointers.json',dict(v0=weights0,v1=weights1,owner='single_frontend._ckpt_bf16'))
    require(weights0==weights1,'shared_weight_pointers')
    require(all(any(w['ptr']<=v<w['ptr']+w['nbytes'] for w in before['shared_readonly']) for v in weights0.values()),'weight_owner_ranges')

    # Complete original per-slot initialization/Autotune before any nondefault
    # stream work; no prompt switching or resource allocation in the pair.
    for slot,p in [('v0',p0),('v1',p1)]:
        p.autotune_gemms();torch.cuda.default_stream().synchronize()
        require(p._gemms_autotuned,slot+'_autotune_complete')
    images=owner._stack_images(obs)
    noise=torch.from_numpy(f['noise0_bf16_bytes'].copy()).cuda().view(torch.bfloat16).reshape(50,32)
    require(tuple(images.shape)==(2,224,224,3) and images.dtype==torch.bfloat16,'image_shape_dtype')
    uploads=[]
    for name,t in [('images',images),('noise',noise)]:
        x=next(_collect(t,'shared.inputs.'+name));x.update(writable=False,owner='shared.inputs');uploads.append(x)
    save_json(OUT/'upload_sources.json',uploads)
    require(not any(max(a['ptr'],b['ptr'])<min(a['ptr']+a['nbytes'],b['ptr']+b['nbytes']) for a in before['writable'] for b in uploads),'upload_sources_disjoint')
    A,B=torch.cuda.Stream(),torch.cuda.Stream()
    report['streams']=dict(A_v1=A.cuda_stream,B_v0=B.cuda_stream);save()
    require(A.cuda_stream!=B.cuda_stream and A.cuda_stream and B.cuda_stream,'two_nondefault_streams')
    ready=torch.cuda.Event();ready.record(torch.cuda.default_stream())
    A.wait_event(ready);B.wait_event(ready)
    streams={id(p0):B,id(p1):A};job=['initialization']
    def check_stream(explicit):
        if torch.cuda.current_stream().cuda_stream!=explicit:raise RuntimeError('Torch/FlashRT stream mismatch')
    for slot,p in [('v0',p0),('v1',p1)]:
        expected=streams[id(p)].cuda_stream
        enc0,dec0,vis0=p._encoder_layer,p._decoder_layer,p.vision_encoder
        def enc(i,seq,fuse_b1,stream,orig=enc0,slot=slot,expected=expected):
            check_stream(stream)
            if stream!=expected:raise RuntimeError('wrong slot stream')
            report['ledger'].setdefault(job[0],{}).setdefault(slot,{}).setdefault('encoder',[]).append(i)
            orig(i,seq,fuse_b1,stream)
        def dec(i,step,enc_seq,ds,skip_c1,stream,orig=dec0,slot=slot,expected=expected):
            check_stream(stream)
            if stream!=expected:raise RuntimeError('wrong slot stream')
            report['ledger'].setdefault(job[0],{}).setdefault(slot,{}).setdefault('decoder',[]).append([step,i])
            orig(i,step,enc_seq,ds,skip_c1,stream)
        def vis(stream=0,orig=vis0,slot=slot,expected=expected):
            check_stream(stream)
            if stream!=expected:raise RuntimeError('wrong vision stream')
            report['ledger'].setdefault(job[0],{}).setdefault(slot,{}).setdefault('vision',[]).append(27)
            orig(stream)
        p._encoder_layer=enc;p._decoder_layer=dec;p.vision_encoder=vis
        va,ea,da=p.attn.vision_attn,p.attn.encoder_attn,p.attn.decoder_attn
        def vision_attention(stream=0,orig=va):check_stream(stream);return orig(stream=stream)
        def encoder_attention(layer_idx,seq,stream=0,orig=ea):check_stream(stream);return orig(layer_idx,seq,stream=stream)
        def decoder_attention(layer_idx,enc_seq,dec_seq,stream=0,orig=da):check_stream(stream);return orig(layer_idx,enc_seq,dec_seq,stream=stream)
        p.attn.vision_attn=vision_attention;p.attn.encoder_attn=encoder_attention;p.attn.decoder_attn=decoder_attention
    def read(p,ptr,n):
        s=streams[id(p)]
        with torch.cuda.stream(s):
            out=torch.empty(n,dtype=torch.uint8,device='cuda')
            rc=owner._cudart.cudaMemcpyAsync(ctypes.c_void_p(out.data_ptr()),ctypes.c_void_p(ptr),n,3,s.cuda_stream)
            if rc:raise RuntimeError(f'cudaMemcpyAsync {rc}')
            s.synchronize();return out.cpu().numpy().copy()
    def stage(p,images_too=True):
        s=streams[id(p)]
        with torch.cuda.stream(s):
            if images_too:owner._copy_tensor_to_pipeline_buf_stream(images,p.input_images_buf,s.cuda_stream)
            owner._copy_tensor_to_pipeline_buf_stream(noise,p.input_noise_buf,s.cuda_stream)
        s.synchronize()
        require(read(p,p.input_noise_buf.ptr.value,3200).tobytes()==f['noise0_bf16_bytes'].tobytes(),'fixed_noise_'+job[0])
    def snap(p,name,layers=18):
        s=streams[id(p)];s.synchronize()
        with torch.cuda.stream(s):
            x=store(name+'_x',read(p,p.bufs['encoder_x'].ptr.value,561*ENC_D*2))
            k=store(name+'_K',p.attn.enc_K[:layers,:561].contiguous().view(torch.uint8).cpu().numpy())
            v=store(name+'_V',p.attn.enc_V[:layers,:561].contiguous().view(torch.uint8).cpu().numpy())
        return x,k,v
    def action(p,name):
        raw=store(name+'_raw_bf16',read(p,p.input_noise_buf.ptr.value,3200))
        vals=torch.from_numpy(raw.copy()).view(torch.bfloat16).float().reshape(50,32).numpy()
        acts=store(name+'_actions',unnormalize_actions(vals,owner.norm_stats)[:,:7])
        report.setdefault('output_finite',{})[name]=bool(np.isfinite(vals).all() and np.isfinite(acts).all());save()
        return raw,acts
    def observe_inputs(p,label):
        # Only before submission / after both done. No pair-internal reads.
        specs={'images':p.input_images_buf,'language':p._lang_embeds_buf,
               'rope':p.bufs['encoder_rope_weights']}
        data={};info={}
        for name,buf in specs.items():
            ptr,n=buf.ptr.value,buf.nbytes
            # Check against the actual owning manifest, never Python object id.
            valid=any(e['ptr']<=ptr and ptr+n<=e['ptr']+e['nbytes']
                      for e in before['writable'])
            info[name]=dict(ptr=ptr,nbytes=n,within_manifest=valid,
                            lifecycle='persistent slot input; observed outside pair')
            save_json(OUT/(label+'_addresses.json'),info)
            if not valid:raise RuntimeError('unverified input read range '+name)
            data[name]=store(label+'_'+name,read(p,ptr,n))
        return data
    def observe_post(label):
        # Call only after A/B completion. Save resource evidence before assertions.
        A.synchronize();B.synchronize()
        m=buffer_dtypes(address_manifest(owner,p0,p1,attn1,runner1,validate=False))
        save_json(OUT/(label+'_resources.json'),m)
        wp=dict(v0=leaves(p0.weights),v1=leaves(p1.weights))
        save_json(OUT/(label+'_weights.json'),wp)
        memory(label+'_observed')
        inputs0=observe_inputs(p0,label+'_v0_inputs')
        inputs1=observe_inputs(p1,label+'_v1_inputs')
        vision={}
        for name in ('vision_x','vision_x_pooled'):
            buf=p1.bufs[name];ptr,n=buf.ptr.value,buf.nbytes
            if not any(e['ptr']<=ptr and ptr+n<=e['ptr']+e['nbytes'] for e in m['writable']):
                raise RuntimeError('unverified Vision read range '+name)
            vision[name]=store(label+'_'+name,read(p1,ptr,n))
        save_json(OUT/(label+'_evidence_status.json'),dict(
            visible_no_overlap=not m['overlaps'],
            visible_addresses_stable={x['name']:(x['ptr'],x['nbytes']) for x in before['writable']}==
                                     {x['name']:(x['ptr'],x['nbytes']) for x in m['writable']},
            weight_pointer_maps_stable=wp['v0']==wp['v1']==weights0,
            vision_lifecycle='POSTSTATE only; not any intermediate Vision-layer snapshot',
            unknown_resources=m['unknown_resources']))
        return inputs0,inputs1,vision
    def context(p):
        st=streams[id(p)].cuda_stream
        p._copy_lang_embeds_to_encoder_x(stream=st);p.vision_encoder(st);p.transformer_encoder(st)
    def block1(p):
        st=streams[id(p)].cuda_stream
        p._copy_lang_embeds_to_encoder_x(stream=st);p.vision_encoder(st)
        bu,w,fvk,gemm=p.bufs,p.weights,p.fvk,p.gemm;vs=p.vision_seq_enc
        fvk.layer_norm(bu['vision_x_pooled'].ptr.value,w['vision_final_norm_w'],w['vision_final_norm_b'],bu['vision_x_norm'].ptr.value,vs,VIS_D,1e-5,stream=st)
        gemm.bf16_nn(bu['vision_x_norm'].ptr.value,w['encoder_multi_modal_projector_w'],bu['encoder_x'].ptr.value,vs,ENC_D,VIS_D,stream=st)
        fvk.add_bias_bf16(bu['encoder_x'].ptr.value,w['encoder_multi_modal_projector_b'],vs,ENC_D,stream=st)
        for i in range(9):p._encoder_layer(i,561,False,st)
    def block2(p):
        st=streams[id(p)].cuda_stream
        for i in range(9,18):p._encoder_layer(i,561,False,st)
    def finish_event(name,s):
        e=torch.cuda.Event();e.record(s);e.synchronize()
        report['events'].append(dict(name=name,stream=s.cuda_stream,complete=e.query(),host_ns=time.monotonic_ns()));save()
        require(e.query(),name+'_complete');return e
    language0=store('S0_language',read(p0,p0._lang_embeds_buf.ptr.value,p0._lang_embeds_buf.nbytes))
    language1=store('S1_language',read(p1,p1._lang_embeds_buf.ptr.value,p1._lang_embeds_buf.nbytes))
    require(language0.tobytes()!=language1.tobytes(),'distinct_language_state')
    job[0]='v0_context_S0';stage(p0)
    with torch.cuda.stream(B):context(p0);pub0=finish_event('publish_v0',B)
    report['versions']={'v0':dict(snapshot_id='S0',state='published',retained=True),'v1':dict(snapshot_id='S1',state='reference')};save()
    prefix0=snap(p0,'published_v0')
    job[0]='reference_Expert_S0';stage(p0,False)
    e0,e1=torch.cuda.Event(enable_timing=True),torch.cuda.Event(enable_timing=True)
    with torch.cuda.stream(B):
        B.wait_event(pub0);e0.record(B);submit0=time.monotonic_ns();p0.transformer_decoder(B.cuda_stream);submit1=time.monotonic_ns();e1.record(B)
    e1.synchronize()
    report['independent_expert']=dict(gpu_ms=e0.elapsed_time(e1),cpu_submit_ns=submit1-submit0,stream=B.cuda_stream);save()
    raw0,act0=action(p0,'reference_Expert_S0')
    require(report['output_finite']['reference_Expert_S0'],'independent_expert_reference_finite')
    job[0]='reference_Context_S1';stage(p1)
    reference_inputs1=observe_inputs(p1,'reference_S1_pre')
    original=p1._encoder_layer;mid=[]
    def observe(i,seq,fuse_b1,stream):
        original(i,seq,fuse_b1,stream)
        if i==8:mid.append(snap(p1,'reference_S1_boundary',9))
    p1._encoder_layer=observe
    try:
        with torch.cuda.stream(A):context(p1)
        A.synchronize()
    finally:p1._encoder_layer=original
    reference_post=observe_post('reference_S1_post')
    final1=snap(p1,'reference_S1_context');require(len(mid)==1,'S1_reference_boundary')
    memory('after_references')
    prepair=buffer_dtypes(address_manifest(owner,p0,p1,attn1,runner1,validate=False))
    save_json(OUT/'address_manifest_pre_pair.json',prepair)
    require(not prepair['overlaps'],'prepair_no_visible_overlap')

    def window(label,paired):
        # Uploads, snapshots, and all initialization precede both submissions.
        job[0]=label;stage(p1);stage(p0,False)
        report['versions']['v1']['state']='building_'+label
        report['expert_binding']=dict(version_id='v0',snapshot_id='S0',steps=10);save()
        if paired:
            observed_pre=observe_inputs(p1,'Pair01_pre_v1')
            observe_inputs(p0,'Pair01_pre_v0')
            old_pre=snap(p0,'Pair01_pre_published_v0')
            pre_m=buffer_dtypes(address_manifest(owner,p0,p1,attn1,runner1,validate=False))
            save_json(OUT/'Pair01_pre_resources.json',pre_m)
            save_json(OUT/'Pair01_pre_weights.json',dict(v0=leaves(p0.weights),v1=leaves(p1.weights)))
            require(not pre_m['overlaps'],'Pair01_pre_no_visible_overlap')
            require(pub0.query(),'Pair01_pre_published_ready')
            for key,got,expected in zip(('K','V'),old_pre[1:],prefix0[1:]):compare('Pair01_pre_old_'+key,got,expected)
            save_json(OUT/'Pair01_pre_version_event.json',dict(versions=report['versions'],publish_v0_complete=pub0.query()))
            for key in reference_inputs1:
                require(observed_pre[key].tobytes()==reference_inputs1[key].tobytes(),'Pair01_pre_'+key+'_exact')
        anchor=torch.cuda.Event(enable_timing=True);anchor.record(torch.cuda.default_stream());anchor.synchronize()
        a0,a1,b0,b1=[torch.cuda.Event(enable_timing=True) for _ in range(4)]
        A.wait_event(anchor);B.wait_event(anchor)
        if paired:torch.cuda.nvtx.range_push('M1_PAIR')
        release=time.monotonic_ns()
        torch.cuda.nvtx.range_push(label+'_Block1')
        with torch.cuda.stream(A):
            a0.record(A);astart=time.monotonic_ns();block1(p1);aend=time.monotonic_ns();a1.record(A)
        torch.cuda.nvtx.range_pop()
        a_finished_before_b=a1.query()  # nonblocking; no inter-submit sync
        if paired and a_finished_before_b:
            torch.cuda.nvtx.range_pop()
            report.setdefault('windows',[]).append(dict(name=label,block1_already_complete=True));save()
            raise RuntimeError('Block1 completed before Expert submission; no intended pair opportunity')
        torch.cuda.nvtx.range_push(label+'_Expert')
        with torch.cuda.stream(B):
            B.wait_event(pub0)
            if not paired:B.wait_event(a1)  # serial control only
            b0.record(B);bstart=time.monotonic_ns();p0.transformer_decoder(B.cuda_stream);bend=time.monotonic_ns();b1.record(B)
        torch.cuda.nvtx.range_pop()
        wait0=time.monotonic_ns();a1.synchronize();wait1=time.monotonic_ns();b1.synchronize();wait2=time.monotonic_ns()
        rc=owner._cudart.cudaGetLastError()
        if paired:torch.cuda.nvtx.range_pop()
        rec=dict(name=label,paired=paired,release_ns=release,A_submit_start_ns=astart,A_submit_end_ns=aend,
            B_submit_start_ns=bstart,B_submit_end_ns=bend,A_cpu_submit_ns=aend-astart,B_cpu_submit_ns=bend-bstart,
            A_cpu_wait_ns=wait1-wait0,B_cpu_wait_ns=wait2-wait1,cpu_wall_ns=wait2-release,
            A_gpu_ms=a0.elapsed_time(a1),B_gpu_ms=b0.elapsed_time(b1),
            A_start_offset_ms=anchor.elapsed_time(a0),A_end_offset_ms=anchor.elapsed_time(a1),
            B_start_offset_ms=anchor.elapsed_time(b0),B_end_offset_ms=anchor.elapsed_time(b1),
            all_gpu_span_ms=max(anchor.elapsed_time(a1),anchor.elapsed_time(b1))-min(anchor.elapsed_time(a0),anchor.elapsed_time(b0)),
            A_complete=a1.query(),B_complete=b1.query(),A_finished_before_B_submit=a_finished_before_b,cuda_last_error=rc,
            A_stream=A.cuda_stream,B_stream=B.cuda_stream,expert_bound_version='v0',expert_snapshot='S0',new_snapshot='S1')
        report.setdefault('windows',[]).append(rec);save()
        # Both jobs are complete; save all primary evidence before comparison.
        got_raw,got_act=action(p0,label+'_Expert')
        got_boundary=snap(p1,label+'_boundary',9)
        got_prefix=snap(p0,label+'_old_prefix')
        post=observe_post(label+'_post')
        require(rc==0,label+'_cuda_status')
        evidence=json.loads((OUT/(label+'_post_evidence_status.json')).read_text())
        require(evidence['visible_no_overlap'] and evidence['visible_addresses_stable'] and evidence['weight_pointer_maps_stable'],label+'_post_resource_gate')
        report['collect_pair_comparisons']=paired;save()
        compare(label+'_old_language',post[0]['language'],language0)
        compare(label+'_expert_raw',got_raw,raw0);compare(label+'_expert_actions',got_act,act0,False)
        for key,a,b in zip(('x','K','V'),got_boundary,mid[0]):compare(label+'_boundary_'+key,a,b)
        for key,a,b in zip(('x','K','V'),got_prefix,prefix0):compare(label+'_old_unchanged_'+key,a,b)
        for key in reference_inputs1:
            compare(label+'_input_'+key,post[1][key],reference_inputs1[key])
        for key in reference_post[2]:
            compare(label+'_vision_post_'+key,post[2][key],reference_post[2][key])
        if paired:
            report['collect_pair_comparisons']=False
            report['versions']['v1']['state']='UNPUBLISHED_DIAGNOSTIC_STOP'
            report['pair_Post_Block2_executed']=False;save()
            if any(not x['pass_'] for x in report['checks']):
                raise AssertionError('Pair numerical/resource gate failed; all safely read post evidence retained')
            return a1,b1,None  # unconditional stop: never publish this diagnostic v1
        # Serial control still completes all remaining mandatory VLM work.

        job[0]=label+'_Block2'
        with torch.cuda.stream(A):
            A.wait_event(a1);A.wait_event(b1);block2(p1)
            published=finish_event(label+'_publish_v1',A)
        report['versions']['v1']=dict(snapshot_id='S1',state='published',generation=label);save()
        completed=snap(p1,label+'_new_context')
        for key,a,b in zip(('x','K','V'),completed,final1):compare(label+'_final_Context_'+key,a,b)
        afterprefix=snap(p0,label+'_old_after_publish')
        for key,a,b in zip(('K','V'),afterprefix[1:],prefix0[1:]):compare(label+'_old_after_publish_'+key,a,b)
        mem=memory(label+'_complete')
        require(mem['cuda_free']>12*1024**3 and report['memory']['after_references']['cuda_free']-mem['cuda_free']<2*1024**3,label+'_memory_not_abnormal')
        return a1,b1,published

    window('Serial',False)
    # Exactly one real pair. The outer NVTX range brackets only its submission
    # and completion; Nsight capture ends before readbacks or Block 2.
    window('Pair01',True)
    compare('v0_language_preserved',read(p0,p0._lang_embeds_buf.ptr.value,p0._lang_embeds_buf.nbytes),language0)
    compare('v1_language_preserved',read(p1,p1._lang_embeds_buf.ptr.value,p1._lang_embeds_buf.nbytes),language1)
    expected_dec=[[step,layer] for step in range(10) for layer in range(18)]
    for label in ('reference_Expert_S0','Serial','Pair01'):
        require(report['ledger'][label]['v0']['decoder']==expected_dec,label+'_complete_10_steps')
    require(report['ledger']['Pair01']['v1']['vision']==[27], 'Pair01_full_vision')
    require(report['ledger']['Pair01']['v1']['encoder']==list(range(9)), 'Pair01_original_Block1')
    require('Pair01_Block2' not in report['ledger'], 'diagnostic_no_Block2')
    after=buffer_dtypes(address_manifest(owner,p0,p1,attn1,runner1,validate=False));save_json(OUT/'address_manifest_after.json',after)
    require(not after['overlaps'],'postpair_no_visible_overlap')
    require({x['name']:(x['ptr'],x['nbytes']) for x in before['writable']}=={x['name']:(x['ptr'],x['nbytes']) for x in after['writable']},'slot_addresses_stable')
    require(weights0==leaves(p0.weights)==leaves(p1.weights),'weight_pointer_ownership_preserved')
    report['cuda_last_error']=owner._cudart.cudaGetLastError();require(report['cuda_last_error']==0,'final_cuda_status')
    memory('final')
    report['status']='OBSERVED_PASS_NOT_STABILITY_PROOF';save()
    print(json.dumps(dict(status=report['status'],windows=report['windows'],out=str(OUT)),sort_keys=True),flush=True)

if __name__=='__main__':
    try:main()
    except BaseException:
        report['status']='FAIL';report['error']=traceback.format_exc()
        try:memory('on_failure')
        except BaseException:pass
        save();raise
