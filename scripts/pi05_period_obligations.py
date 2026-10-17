"""One approved single-stream model process: gate then exactly six short replays."""
import ast
import ctypes
import hashlib
import inspect
import json
import os
import textwrap
import time
import traceback
import signal
import sys
from period_obligation_stats import jobs,cycle_rows,counts
from b1_event_observer import B1Observer
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
    loaded=Path(diag.__file__).resolve()
    report.update(extension=str(loaded),extension_sha256=digest(loaded.read_bytes()),
                  script_sha256=digest(Path(__file__).read_bytes()),checkpoint=str(CHECKPOINT),
                  adapter_sha256=digest(Path(adapter_module.__file__).read_bytes()))
    save()
    require(loaded.parent==Path(os.environ['COOVERLAP_DIAG_ROOT']).resolve()/'lib','isolated_extension_path')
    require(report['extension_sha256']==os.environ['COOVERLAP_DIAG_SHA256'],'isolated_extension_sha')
    fixture_path=Path('/tmp/cooverlap_pi05_fixed_reference.npz')
    states_path=Path('/tmp/cooverlap_pi05_state_versions.npz')
    f=np.load(fixture_path,allow_pickle=False);ss=np.load(states_path,allow_pickle=False)
    s0,s1=ss['s0'].copy(),ss['s1'].copy()
    require(np.array_equal(s0,f['state']) and not np.array_equal(s0,s1),'distinct_day2d_S0_S1')
    report['inputs']=dict(fixture_sha256=digest(fixture_path.read_bytes()),state_fixture_sha256=digest(states_path.read_bytes()),
        S0=s0.tolist(),S1=s1.tolist(),S0_sha256=digest(s0.tobytes()),S1_sha256=digest(s1.tobytes()),
        image_sha256=digest(f['image'].tobytes()),wrist_sha256=digest(f['wrist_image'].tobytes()),
        noise_sha256=digest(f['noise0_bf16_bytes'].tobytes()),prompt=PROMPT)
    report['config']=json.loads((CHECKPOINT/'config.json').read_text())
    save()
    require(report['inputs']['fixture_sha256']=='92f1a92b64352cc34010c81c1accd1cb00fcb227d0004f545b87549d5d6c544d','fixed_reference_fixture_sha')
    require(report['inputs']['state_fixture_sha256']=='cabb191ec2b319c43fa769e5c8b9b8851724ef25ecff8850d118b8276124205e','day2d_state_fixture_sha')
    require(digest((CHECKPOINT/'config.json').read_bytes())=='0458a362b574c2cb088ebf3767c9eacb1f040b9cb680a89b594379a4fe36e5f7','fixed_checkpoint_config_sha')
    require((report['config']['chunk_size'],report['config']['num_inference_steps'],report['config']['state_cond'])==(50,10,False),'checkpoint_config')
    stream=torch.cuda.default_stream()
    stream_int=stream.cuda_stream
    require(stream_int==0 and torch.cuda.current_stream().cuda_stream==0,'single_controlled_default_stream')
    memory('before_model')
    obs0={k:f[k].copy() for k in ('image','wrist_image','state')}
    owner,p0,p1,attn1,runner1=build_slots(s0,s1,obs0,diag.GemmRunner,on_stage=memory)
    memory('after_both_slots')
    require(report['memory']['after_both_slots']['cuda_free']>12*1024**3,'remaining_cuda_memory_above_safety_floor')
    for label,p in [('v0',p0),('v1',p1)]:
        flags={k:getattr(p,k) for k in ('use_fp8','use_fp8_decoder','use_int8_encoder','use_int8_decoder','use_int8_vision')}
        report.setdefault('slots',{})[label]=dict(flags=flags,seq=p.encoder_seq_len,prompt=p._current_prompt_len,
            vision_layers=p.vision_num_layers,steps=p.num_steps,chunk=p.chunk_size,
            backend_routes=dict(p.attn._fa2_sites),snapshot_id='S0' if label=='v0' else 'S1')
        save()
        require(not any(flags.values()) and p.encoder_seq_len==561 and p._current_prompt_len==49
                and p.vision_num_layers==27 and p.num_steps==10 and p.chunk_size==50 and not p._state_active,label+'_fixed_bf16_workload')
        require(all(p.attn._fa2_sites.values()),label+'_persistent_vendor_attention')
        require(p._graph is None and p._decoder_only_graph is None,label+'_no_graph_capture_or_replay')
    manifest=buffer_dtypes(address_manifest(owner,p0,p1,attn1,runner1,validate=False))
    def pointer_leaves(value,prefix=''):
        if isinstance(value,dict):
            return {k:v for name,child in value.items() for k,v in pointer_leaves(child,prefix+'.'+name).items()}
        if isinstance(value,(tuple,list)):
            return {k:v for i,child in enumerate(value) for k,v in pointer_leaves(child,prefix+f'[{i}]').items()}
        return {prefix:value} if isinstance(value,int) and value>4096 else {}
    pointer0,pointer1=pointer_leaves(p0.weights),pointer_leaves(p1.weights)
    save_json(OUT/'weight_pointers.json',dict(v0=pointer0,v1=pointer1,owner='single_frontend._ckpt_bf16'))
    require(pointer0==pointer1,'all_weight_pointer_leaves_shared')
    manifest['kv_effective_ranges']=[]
    for label,p in [('v0',p0),('v1',p1)]:
        for kind,t in [('K',p.attn.enc_K),('V',p.attn.enc_V)]:
            for layer in range(18):
                base=t.data_ptr()+layer*t.stride(0)*t.element_size()
                for part,start,rows,access in [('encoder_prefix',0,561,'Context write; Expert read'),('decoder_suffix',561,50,'Expert write/read')]:
                    manifest['kv_effective_ranges'].append(dict(slot=label,kind=kind,layer=layer,part=part,
                        ptr=base+start*t.stride(1)*t.element_size(),nbytes=rows*256*2,dtype='bfloat16',access=access))
    manifest['execution_stream']=dict(cuda_stream=0,policy='all initialization/autotune/reference/test sequential on default stream; no graph')
    save_json(OUT/'address_manifest_before.json',manifest)
    require(not manifest['overlaps'],'no_cross_slot_write_write_or_write_readonly_overlap')
    require(not any(e['dtype']=='UNKNOWN' for e in manifest['writable']),'all_visible_buffer_dtypes_classified')
    class Attr(ctypes.Structure):
        _fields_=[('type',ctypes.c_int),('device',ctypes.c_int),
                  ('devicePointer',ctypes.c_void_p),('hostPointer',ctypes.c_void_p),
                  ('reserved',ctypes.c_long*8)]
    owner._cudart.cudaPointerGetAttributes.argtypes=[ctypes.POINTER(Attr),ctypes.c_void_p]
    owner._cudart.cudaPointerGetAttributes.restype=ctypes.c_int
    attrs=[]
    for entry in manifest['writable']+manifest['shared_readonly']:
        attr=Attr();rc=owner._cudart.cudaPointerGetAttributes(ctypes.byref(attr),ctypes.c_void_p(entry['ptr']))
        attrs.append(dict(name=entry['name'],ptr=entry['ptr'],cuda_status=rc,
                          memory_type=attr.type,device=attr.device,device_pointer=attr.devicePointer))
    save_json(OUT/'pointer_attributes.json',attrs)
    require(all(a['cuda_status']==0 and a['memory_type'] in (2,3) and a['device_pointer'] for a in attrs),'all_visible_device_pointers_valid')
    # Capture complete layer and denoise-layer call ledgers without replacing math.
    job=['initialization']
    for label,p in [('v0',p0),('v1',p1)]:
        orig_enc,orig_dec=p._encoder_layer,p._decoder_layer
        def enc(i,seq,fuse_b1,stream,orig=orig_enc,slot=label):
            if stream!=0:raise RuntimeError('encoder escaped controlled stream')
            report['ledger'].setdefault(job[0],{}).setdefault(slot,{}).setdefault('encoder',[]).append(i)
            orig(i,seq,fuse_b1,stream)
        def dec(i,step,enc_seq,ds,skip_c1,stream,orig=orig_dec,slot=label):
            if stream!=0:raise RuntimeError('decoder escaped controlled stream')
            report['ledger'].setdefault(job[0],{}).setdefault(slot,{}).setdefault('decoder',[]).append([step,i])
            orig(i,step,enc_seq,ds,skip_c1,stream)
        p._encoder_layer=enc;p._decoder_layer=dec
    images=owner._stack_images(obs0)
    noise=torch.from_numpy(f['noise0_bf16_bytes'].copy()).cuda().view(torch.bfloat16).reshape(50,32)
    upload_sources=[]
    for label,t in [('images',images),('initial_noise',noise)]:
        entry=next(_collect(t,'shared.inputs.'+label));entry.update(owner='shared.inputs',writable=False)
        upload_sources.append(entry)
    save_json(OUT/'shared_upload_sources.json',upload_sources)
    conflicts=[]
    for a in manifest['writable']:
        for b in upload_sources:
            if max(a['ptr'],b['ptr'])<min(a['ptr']+a['nbytes'],b['ptr']+b['nbytes']):conflicts.append([a['name'],b['name']])
    report['upload_source_conflicts']=conflicts;save()
    require(not conflicts,'upload_sources_do_not_alias_writable_slot_buffers')
    require(tuple(images.shape)==(2,224,224,3) and images.dtype==torch.bfloat16,'preprocessed_images')
    report['preprocessed_image_sha256']=digest(images.view(torch.uint8).cpu().numpy().tobytes());save()
    def read(ptr,n):
        t=torch.empty(n,dtype=torch.uint8,device='cuda')
        rc=owner._cudart.cudaMemcpyAsync(ctypes.c_void_p(t.data_ptr()),ctypes.c_void_p(ptr),n,3,stream_int)
        if rc:raise RuntimeError(f'cudaMemcpyAsync status {rc}')
        stream.synchronize()
        return t.cpu().numpy().copy()
    def stage(p):
        owner._copy_tensor_to_pipeline_buf_stream(images,p.input_images_buf,0)
        owner._copy_tensor_to_pipeline_buf_stream(noise,p.input_noise_buf,0)
        stream.synchronize()
        require(read(p.input_noise_buf.ptr.value,3200).tobytes()==f['noise0_bf16_bytes'].tobytes(),'noise_readback_'+job[0])
    def snap(p,name,layers=18):
        stream.synchronize()
        x=store(name+'_x',read(p.bufs['encoder_x'].ptr.value,561*ENC_D*2))
        k=store(name+'_K',p.attn.enc_K[:layers,:561].contiguous().view(torch.uint8).cpu().numpy())
        v=store(name+'_V',p.attn.enc_V[:layers,:561].contiguous().view(torch.uint8).cpu().numpy())
        return x,k,v
    def action(p,name):
        a=store(name+'_raw_bf16',read(p.input_noise_buf.ptr.value,3200))
        values=torch.from_numpy(a.copy()).view(torch.bfloat16).float().reshape(50,32).numpy()
        require(np.isfinite(values).all(),name+'_finite')
        actions=store(name+'_actions',unnormalize_actions(values,owner.norm_stats)[:,:7])
        return a,actions
    def event(name):
        e=torch.cuda.Event();e.record(stream);e.synchronize()
        report['events'].append(dict(name=name,cuda_stream=0,complete=e.query(),host_ns=time.monotonic_ns()));save()
        require(e.query(),name+'_complete')
        return e
    emb0=store('S0_language',read(p0._lang_embeds_buf.ptr.value,p0._lang_embeds_buf.nbytes))
    emb1=store('S1_language',read(p1._lang_embeds_buf.ptr.value,p1._lang_embeds_buf.nbytes))
    require(emb0.tobytes()!=emb1.tobytes(),'distinct_language_embeddings')

    # Same original per-slot autotune, completed sequentially before references.
    for label,p in [('v0',p0),('v1',p1)]:
        job[0]='autotune_'+label;p.autotune_gemms();stream.synchronize()
        require(p._gemms_autotuned,label+'_autotune_complete')
    memory('after_autotune')
    cfgpath=Path(os.environ['COOVERLAP_PROTOCOL'])
    cfg=json.loads(cfgpath.read_text());save_json(OUT/'protocol.json',cfg)
    require(digest(cfgpath.read_bytes())==os.environ['COOVERLAP_PROTOCOL_SHA'],'protocol_sha')
    require(cfg['protocol']=='m1_period_obligations_v1' and cfg['combinations']==[[180,'whole_context'],[180,'two_blocks'],[240,'two_blocks'],[240,'whole_context']] and cfg['cycles']==8 and cfg['refresh_release_cycles']==[0,2,4,6],'approved_four_obligation_segments')
    report['segments']=[];report['prep_ledger']=dict(initialization='build_slots and original per-slot Autotune',reference_S0='one complete Context + Expert10',reference_S1='one Context with diagnostic layer8 readback',gate='one B1 -> v0 Expert10 -> B2; also serves as necessary warmup');save()
    progress=(OUT/'progress.jsonl').open('x',buffering=1)
    def journal(event_type,**record):
        progress.write(json.dumps(dict(event=event_type,host_ns=time.monotonic_ns(),**record))+'\n');progress.flush()
    def terminated(signum,frame):
        report['status']='INCOMPLETE_TIMEOUT_OR_SIGNAL';report['signal']=signum
        progress.flush();os.fsync(progress.fileno());save();raise SystemExit(124)
    signal.signal(signal.SIGTERM,terminated)
    def context(p):p._copy_lang_embeds_to_encoder_x(stream=0);p.vision_encoder(0);p.transformer_encoder(0)
    def block1(p):
        p._copy_lang_embeds_to_encoder_x(stream=0);p.vision_encoder(0)
        B,W,fvk,gemm=p.bufs,p.weights,p.fvk,p.gemm;vs=p.vision_seq_enc
        fvk.layer_norm(B['vision_x_pooled'].ptr.value,W['vision_final_norm_w'],W['vision_final_norm_b'],B['vision_x_norm'].ptr.value,vs,VIS_D,1e-5,stream=0)
        gemm.bf16_nn(B['vision_x_norm'].ptr.value,W['encoder_multi_modal_projector_w'],B['encoder_x'].ptr.value,vs,ENC_D,VIS_D,stream=0)
        fvk.add_bias_bf16(B['encoder_x'].ptr.value,W['encoder_multi_modal_projector_b'],vs,ENC_D,stream=0)
        for i in range(9):p._encoder_layer(i,561,False,0)
    def block2(p):
        for i in range(9,18):p._encoder_layer(i,561,False,0)
    job[0]='reference_S0';stage(p0);p0.run_pipeline(0);stream.synchronize()
    ref0=snap(p0,'reference_S0');raw0,act0=action(p0,'reference_S0')
    pub0=event('publish_v0');report['versions']={'v0':'published_S0_immutable','v1':'S1_build_only'};save()
    job[0]='reference_S1';stage(p1);orig=p1._encoder_layer;mid=[]
    def observe(i,seq,fuse_b1,stream):
        orig(i,seq,fuse_b1,stream)
        if i==8:mid.append(snap(p1,'reference_S1_boundary',9))
    p1._encoder_layer=observe
    try:context(p1);stream.synchronize()
    finally:p1._encoder_layer=orig
    ref1=snap(p1,'reference_S1');require(len(mid)==1,'S1_reference_boundary')
    observer=B1Observer(cfg['poll_sleep_s'])
    job[0]='gate_B1';stage(p1);block1(p1)
    gate_b1=torch.cuda.Event(enable_timing=True);gb=time.monotonic_ns();gate_b1.record(stream);ge=time.monotonic_ns();observer.arm('gate',gate_b1,gb,ge)
    event('gate_B1_done');report['gate_B1_observation']=observer.result('gate')
    gate_mid=snap(p1,'gate_boundary',9)
    job[0]='gate_Expert';stream.wait_event(pub0);owner._copy_tensor_to_pipeline_buf_stream(noise,p0.input_noise_buf,0)
    require(read(p0.input_noise_buf.ptr.value,3200).tobytes()==f['noise0_bf16_bytes'].tobytes(),'gate_fixed_noise')
    p0.transformer_decoder(0);event('gate_Expert_done');gate_raw,gate_act=action(p0,'gate_Expert')
    job[0]='gate_B2';block2(p1);event('gate_context_ready')
    gate_final=snap(p1,'gate_final');gate_old=snap(p0,'gate_old')
    for key,a,b in zip(('x','K','V'),gate_mid,mid[0]):compare('gate_boundary_'+key,a,b)
    for key,a,b in zip(('x','K','V'),gate_final,ref1):compare('gate_final_'+key,a,b)
    for key,a,b in zip(('x','K','V'),gate_old,ref0):compare('gate_old_'+key,a,b)
    compare('gate_Expert_raw',gate_raw,raw0);compare('gate_Expert_actions',gate_act,act0,False)
    require(report['ledger']['gate_B1']['v1']['encoder']+report['ledger']['gate_B2']['v1']['encoder']==list(range(18)),'gate_all_encoder_layers')
    expected_dec=[[s,i] for s in range(10) for i in range(18)]
    require(report['ledger']['gate_Expert']['v0']['decoder']==expected_dec,'gate_complete_denoise')
    report['gate']='PASS';save()

    # Capture only necessary results into PREALLOCATED device buffers. No D2H,
    # numerical comparison, or large disk write is performed inside a segment.
    def new_snap(layers):
        return dict(x=torch.empty(561*ENC_D*2,dtype=torch.uint8,device='cuda'),K=torch.empty((layers,561,1,256),dtype=torch.bfloat16,device='cuda'),V=torch.empty((layers,561,1,256),dtype=torch.bfloat16,device='cuda'))
    banks=dict(expert=[torch.empty(3200,dtype=torch.uint8,device='cuda') for _ in range(8)],mid=[new_snap(9) for _ in range(4)],final=[new_snap(18) for _ in range(4)])
    bank_entries=list(_collect(banks,'snapshot_banks'))
    save_json(OUT/'snapshot_banks.json',bank_entries)
    require(not any(max(a['ptr'],b['ptr'])<min(a['ptr']+a['nbytes'],b['ptr']+b['nbytes']) for a in bank_entries for b in manifest['writable']+manifest['shared_readonly']),'snapshot_banks_no_model_alias')
    require(not any(max(a['ptr'],b['ptr'])<min(a['ptr']+a['nbytes'],b['ptr']+b['nbytes']) for i,a in enumerate(bank_entries) for b in bank_entries[i+1:]),'snapshot_banks_pairwise_disjoint')
    def copy_raw(dst,src,n):
        rc=owner._cudart.cudaMemcpyAsync(ctypes.c_void_p(dst.data_ptr()),ctypes.c_void_p(src),n,3,0)
        if rc:raise RuntimeError('copy_raw CUDA '+str(rc))
    def retain_snap(bank):
        copy_raw(bank['x'],p1.bufs['encoder_x'].ptr.value,bank['x'].numel())
        n=bank['K'].shape[0];bank['K'].copy_(p1.attn.enc_K[:n,:561]);bank['V'].copy_(p1.attn.enc_V[:n,:561])
    baseline_memory=memory('before_segments')
    # Events are created and materialized before any timed release.
    evpool=[]
    for _ in range(4):
        es=[torch.cuda.Event(enable_timing=True) for _ in range(180)]
        for e in es:e.record(stream)
        stream.synchronize();evpool.append(es)
    for segment_id,(Pms,plan) in enumerate(cfg['combinations']):
        seg=dict(id=segment_id,P_ms=Pms,plan=plan,status='INCOMPLETE',experts=[],refreshes=[],blocks=[],retention=[],protocol='m1_period_obligations_v1',unit_completions=[],B1_observation=[],cycle_miss_definition='max(Expert, assigned same-refresh B1/B2) versus r_j+P')
        report['segments'].append(seg);save()
        evs=iter(evpool[segment_id]);stage(p1);stream.synchronize()
        t0=time.monotonic_ns()+10_000_000;P=Pms*1_000_000
        experts,refreshes=jobs(t0,P)
        seg.update(t0_ns=t0,expert_jobs=experts,refresh_jobs=refreshes);save()
        journal('segment_start',segment=segment_id,t0_ns=t0,P_ms=Pms,plan=plan)
        def discover(now):
            for rec in experts+refreshes:
                if rec['status']=='NOT_RELEASED' and now>=rec['release_ns']:
                    rec['status']='READY';rec['discovered_ns']=now
                    if rec in refreshes:rec['prior_unfinished_at_discovery']=[v['id'] for v in refreshes if v['id']<rec['id'] and v['status']!='DONE']
        def run_op(kind,idx,fn):
            before=time.monotonic_ns();discover(before)
            start,end=next(evs),next(evs)
            journal('submit',segment=segment_id,work=kind,id=idx)
            start.record(stream);submit_start=time.monotonic_ns();fn();submit_end=time.monotonic_ns()
            record_begin=time.monotonic_ns();end.record(stream);record_end=time.monotonic_ns()
            lower=record_begin;polls=0;wait_begin=time.monotonic_ns()
            while True:
                qa=time.monotonic_ns();done=end.query();qb=time.monotonic_ns();polls+=1;discover(qb)
                if done:break
                lower=qa;time.sleep(cfg['poll_sleep_s'])
            rec=dict(kind=kind,id=idx,decision_ns=now,host_begin_ns=before,submit_start_ns=submit_start,submit_end_ns=submit_end,event_record_begin_ns=record_begin,event_record_end_ns=record_end,completion_lower_ns=lower,completion_observed_ns=qb,completion_uncertainty_ns=qb-lower,cpu_submit_ns=submit_end-submit_start,cpu_poll_wait_ns=qb-wait_begin,polls=polls)
            rc=owner._cudart.cudaGetLastError();rec['cuda_last_error']=rc
            seg.setdefault('model_events_partial',[]).append(rec.copy())
            journal('completed_event',segment=segment_id,**rec)
            if rc:raise RuntimeError('CUDA error '+str(rc))
            return rec,start,end
        def observed_B1(refresh_id):
            block1(p1)
            evt=next(evs);rb=time.monotonic_ns();evt.record(stream);re=time.monotonic_ns()
            key=f'seg{segment_id}_R{refresh_id}'
            ab=time.monotonic_ns();observer.arm(key,evt,rb,re);ae=time.monotonic_ns()
            seg['B1_observation'].append(dict(id=refresh_id,key=key,event_record_begin_ns=rb,event_record_end_ns=re,arm_cpu_ns=ae-ab,cuda_stream=0))
        timed=[];retained=[]
        while any(v['status']!='DONE' for v in experts+refreshes):
            now=time.monotonic_ns();discover(now)
            ready=[v for v in experts if v['status']=='READY']
            if ready:
                item=ready[0];j=item['id'];item['status']='RUNNING';job[0]=f'seg{segment_id}_E{j}'
                input_begin=time.monotonic_ns();owner._copy_tensor_to_pipeline_buf_stream(noise,p0.input_noise_buf,0);input_end=time.monotonic_ns()
                stream.wait_event(pub0)
                rec,a,b=run_op('Expert',j,lambda:p0.transformer_decoder(0))
                item.update(rec,status='DONE',input_submit_ns=input_end-input_begin)
                seg['experts'].append(item.copy());timed.append((rec,a,b))
                ca,cb=next(evs),next(evs);cp=time.monotonic_ns();ca.record(stream);copy_raw(banks['expert'][j],p0.input_noise_buf.ptr.value,3200);cb.record(stream);cq=time.monotonic_ns()
                retained.append((dict(work='Expert',id=j,cpu_submit_ns=cq-cp),ca,cb))
            else:
                pending=[v for v in refreshes if v['status']=='READY']
                if pending:
                    item=pending[0];j=item['id'];phase=item['phase'];item['status']='RUNNING';kind='Context' if plan=='whole_context' else ('Block1' if phase==0 else 'Block2');job[0]=f'seg{segment_id}_R{j}_{kind}'
                    rec,a,b=run_op(kind,j,(lambda:(observed_B1(j),block2(p1))) if plan=='whole_context' else (lambda:observed_B1(j)) if phase==0 else (lambda:block2(p1)))
                    seg['blocks'].append(rec);timed.append((rec,a,b))
                    if plan=='whole_context' or phase==0:
                        observed=observer.result(f'seg{segment_id}_R{j}')
                        seg['unit_completions'].append(dict(id=j,unit='B1',unit_id=f'R{j}/B1',snapshot='S1',**observed))
                    if plan=='whole_context' or phase==1:
                        seg['unit_completions'].append(dict(id=j,unit='B2',unit_id=f'R{j}/B2',snapshot='S1',completion_lower_ns=rec['completion_lower_ns'],completion_observed_ns=rec['completion_observed_ns']))
                    is_final=plan=='whole_context' or phase==1
                    if is_final:
                        item.update(status='DONE',ready_observed_ns=rec['completion_observed_ns'],completion_lower_ns=rec['completion_lower_ns']);seg['refreshes'].append(item.copy())
                    else:item.update(status='READY',phase=1)
                    ca,cb=next(evs),next(evs);cp=time.monotonic_ns();ca.record(stream);retain_snap(banks['final' if is_final else 'mid'][j]);cb.record(stream);cq=time.monotonic_ns()
                    retained.append((dict(work=kind,id=j,cpu_submit_ns=cq-cp),ca,cb))
                else:
                    future=[v['release_ns'] for v in experts+refreshes if v['status']=='NOT_RELEASED']
                    if not future:raise RuntimeError('lost work ledger')
                    time.sleep(min(cfg['poll_sleep_s'],max(0,(min(future)-now)/1e9)))
        seg['drain_complete_observed_ns']=time.monotonic_ns();stream.synchronize()
        seg['timed_window_end_ns']=time.monotonic_ns()
        # Stop release clock measurement here. All D2H/comparisons/files below.
        for rec,a,b in timed:rec['event_elapsed_ms']=a.elapsed_time(b)
        seg['model_events']=[rec for rec,a,b in timed]
        for rec,a,b in retained:rec['event_elapsed_ms']=a.elapsed_time(b);seg['retention'].append(rec)
        seg['status']='DRAINED_VALIDATION_PENDING';save();os.fsync(progress.fileno())
        raw_experts=[store(f'seg{segment_id}_E{j}_raw',t.cpu().numpy()) for j,t in enumerate(banks['expert'])]
        snapshots={}
        for q in range(4):
            for tag in ['final']+(['mid'] if plan=='two_blocks' else []):
                snapshots[q,tag]=[store(f'seg{segment_id}_R{q}_{tag}_{k}',banks[tag][q][k].view(torch.uint8).cpu().numpy()) for k in ['x','K','V']]
        old=snap(p0,f'seg{segment_id}_old_v0')
        after=buffer_dtypes(address_manifest(owner,p0,p1,attn1,runner1,validate=False));save_json(OUT/f'seg{segment_id}_resources.json',after)
        for j,raw in enumerate(raw_experts):compare(f'seg{segment_id}_E{j}',raw,raw0)
        for q in range(4):
            for k,a,b in zip(['x','K','V'],snapshots[q,'final'],ref1):compare(f'seg{segment_id}_R{q}_final_{k}',a,b)
            if plan=='two_blocks':
                for k,a,b in zip(['x','K','V'],snapshots[q,'mid'],mid[0]):compare(f'seg{segment_id}_R{q}_mid_{k}',a,b)
        for k,a,b in zip(['x','K','V'],old,ref0):compare(f'seg{segment_id}_old_{k}',a,b)
        require(pointer0==pointer_leaves(p0.weights)==pointer_leaves(p1.weights),'seg'+str(segment_id)+'_shared_weight_owner')
        compare(f'seg{segment_id}_S0_language',read(p0._lang_embeds_buf.ptr.value,p0._lang_embeds_buf.nbytes),emb0)
        compare(f'seg{segment_id}_S1_language',read(p1._lang_embeds_buf.ptr.value,p1._lang_embeds_buf.nbytes),emb1)
        require(not after['overlaps'],'seg'+str(segment_id)+'_resources_disjoint')
        require({x['name']:(x['ptr'],x['nbytes']) for x in after['writable']}=={x['name']:(x['ptr'],x['nbytes']) for x in manifest['writable']},'seg'+str(segment_id)+'_resource_addresses_stable')
        for j in range(8):require(report['ledger'][f'seg{segment_id}_E{j}']['v0']['decoder']==expected_dec,f'seg{segment_id}_E{j}_10steps')
        for q in range(4):
            layers=report['ledger'][f'seg{segment_id}_R{q}_Context']['v1']['encoder'] if plan=='whole_context' else report['ledger'][f'seg{segment_id}_R{q}_Block1']['v1']['encoder']+report['ledger'][f'seg{segment_id}_R{q}_Block2']['v1']['encoder']
            require(layers==list(range(18)),f'seg{segment_id}_R{q}_18layers')
        mem=memory(f'seg{segment_id}_validated');require(mem['cuda_free']>12*1024**3 and baseline_memory['cuda_free']-mem['cuda_free']<2*1024**3,'segment_memory_normal')
        seg['cycle_obligations']=cycle_rows(seg)
        seg['cycle_statistics']={k:counts([v[k] for v in seg['cycle_obligations']]) for k in ['cycle_status','expert_status','VLM_status']}
        seg['status']='PASS';save();journal('segment_validated',segment=segment_id)
    observer.close()
    report['status']='PASS';report['scope']='four finite fixed-period obligation validation segments, no route/stable-performance claims';save()
    print(json.dumps(dict(status='PASS',segments=len(report['segments']),out=str(OUT))),flush=True)

try:main()
except BaseException:
    if report.get('status')!='INCOMPLETE_TIMEOUT_OR_SIGNAL':report['status']='FAIL'
    report['error']=traceback.format_exc()
    if report.get('segments') and report['segments'][-1]['status']!='PASS':
        report['segments'][-1]['status']='INCOMPLETE' if report['status']=='INCOMPLETE_TIMEOUT_OR_SIGNAL' else 'FAIL'
    save();raise
