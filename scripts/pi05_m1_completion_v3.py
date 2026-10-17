# CPU-only preparation mode exits before importing torch or creating a GPU context.
import sys as _sys, os as _os, json as _json, hashlib as _hashlib, time as _time
from pathlib import Path as _Path
from m1_completion_core_v3 import validate_config as _validate_config
_PROCESS_START=_time.monotonic()
_CONFIG_PATH=_Path(_sys.argv[_sys.argv.index('--config')+1]) if '--config' in _sys.argv else _Path(_os.environ['COOVERLAP_PROTOCOL'])
_PRE_CONFIG=_json.loads(_CONFIG_PATH.read_text());_validate_config(_PRE_CONFIG)
if '--dry-run' in _sys.argv:
    print(_json.dumps(dict(status='CPU_ONLY_CONFIG_VALID',role=_PRE_CONFIG['role'],ledger=_PRE_CONFIG['timed_ledger'])));raise SystemExit(0)
if _os.environ.get('COOVERLAP_APPROVED_BATCH')!='m1_completion_dual_gate_v3':raise RuntimeError('new batch requires explicit approval; old authorizations do not start it')
from m1_run_identity import require_nvidia as _require_nvidia
_IDENTITY=_require_nvidia()
from m1_completion_health import check_hardware as _check_hardware
_check_hardware()
"""Prepared finite single-stream M1 batch driver; requires new explicit approval."""
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
from m1_completion_core_v3 import jobs,cycle_rows,counts,classify
from m1_frequency_condition import assess,read_root_samples
from m1_dual_gate import evaluate as cross_evaluate, POLICY
import subprocess
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
report={'status':'INCOMPLETE','protocol_id':'m1_completion_dual_gate_v3','role':_PRE_CONFIG['role'],'identity':_IDENTITY,'checks':[],'memory':{},'events':[], 'ledger':{}}
_workers=[]
_fast_compare=False
_certified=set()

def save_json(path,obj):
    with path.open('w') as f:json.dump(obj,f,indent=2);f.flush();os.fsync(f.fileno())

from m1_durable_journal import DurableJournal
_durable=DurableJournal(OUT)
def save():_durable.commit(report)

def require(condition,name):
    entry=dict(name=name,pass_=bool(condition));report['checks'].append(entry)
    _durable.append('check',entry)
    if not condition:save()
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
    if _fast_compare and exact and digest(b.tobytes()) in _certified:
        report.setdefault('comparisons',[]).append(dict(name=name,exact=True,finite=True,max_abs=0.0,max_rel=0.0,mismatch_elements=0,finite_basis='same bytes as finite gate-certified reference'))
        require(True,name+'_exact');return
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
    report.setdefault('comparisons',[]).append(metrics);_durable.append('comparison',metrics)
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
    report['norm_stats_sha256']=digest(json.dumps(owner.norm_stats,sort_keys=True,default=lambda v:v.tolist()).encode());save()
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
    require(cfg==_PRE_CONFIG,'reviewed_process_config_unchanged');_validate_config(cfg)
    ncycles=cfg['cycles'];nrefresh=ncycles//2
    report['segments']=[];report['prep_ledger']=dict(initialization='build_slots and original per-slot Autotune',reference_S0='one complete Context + Expert10',reference_S1='one Context with diagnostic layer8 readback',gate='one B1 -> v0 Expert10 -> B2; also serves as necessary warmup');save()
    progress=(OUT/'progress.jsonl').open('x',buffering=1)
    def journal(event_type,**record):
        progress.write(json.dumps(dict(event=event_type,host_ns=time.monotonic_ns(),**record))+'\n');progress.flush()
    def stop_worker(proc):
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=2)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    def terminated(signum,frame):
        report['status']='INCOMPLETE_TIMEOUT_OR_SIGNAL';report['signal']=signum
        for proc in _workers:stop_worker(proc)
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
    store('actual_upload_images',images.view(torch.uint8).cpu().numpy())
    store('actual_fixture_state_S0',s0);store('actual_fixture_state_S1',s1)
    store('actual_upload_noise',noise.view(torch.uint8).cpu().numpy())
    decoder_original=p0.transformer_decoder
    def decoder_with_prestate(stream=0,rtc_prefix_len=0):
        # Only the out-of-window reference is observed. Production decode is restored.
        store('reference_Expert_pre_noise',read(p0.input_noise_buf.ptr.value,3200))
        snap(p0,'reference_Expert_pre_Context')
        for key in ('decoder_rope_weights','valid_encoder_len'):
            buf=p0.bufs.get(key)
            if buf is not None:store('reference_Expert_pre_'+key,read(buf.ptr.value,buf.nbytes))
        return decoder_original(stream,rtc_prefix_len)
    report['Expert_static_conditions']={}
    for key in ('decoder_time_emb','decoder_style_attn','decoder_style_ffn','decoder_style_final'):
        buf=p0.bufs.get(key)
        report['Expert_static_conditions'][key]=dict(ptr=buf.ptr.value,nbytes=buf.nbytes,sha256=digest(read(buf.ptr.value,buf.nbytes)),old_reference_comparison='UNKNOWN') if buf is not None else {'status':'UNKNOWN'}
    save()
    p0.transformer_decoder=decoder_with_prestate
    job[0]='reference_S0';stage(p0)
    try:p0.run_pipeline(0);stream.synchronize()
    finally:p0.transformer_decoder=decoder_original
    ref0=snap(p0,'reference_S0');raw0,act0=action(p0,'reference_S0')
    pub0=event('publish_v0');report['versions']={'v0':'published_S0_immutable','v1':'S1_build_only'};save()
    unified=Path(os.environ['COOVERLAP_UNIFIED_REFERENCE'])
    expected_meta=json.loads((unified/'MANIFEST.json').read_text())
    report['unified_reference']=expected_meta;report['numerical_policy']=POLICY;save()
    require(report['inputs']==expected_meta['inputs'],'cross_process_fixture_inputs_exact')
    require(report['preprocessed_image_sha256']==expected_meta['preprocessed_image_sha256'],'cross_process_preprocessed_images_exact')
    for key in ('x','K','V'):
        a=json.loads((OUT/('reference_S0_'+key+'.json')).read_text())
        require(a==expected_meta['tensor_metadata']['reference_S0_'+key],'cross_process_S0_'+key+'_exact')
        before=json.loads((OUT/('reference_Expert_pre_Context_'+key+'.json')).read_text())
        require(before==expected_meta['tensor_metadata']['reference_S0_'+key],'cross_process_pre_S0_'+key+'_exact')
    for label in ('S0_language','S1_language'):
        actual=json.loads((OUT/(label+'.json')).read_text())
        require(actual==expected_meta['tensor_metadata'][label],'cross_process_'+label+'_exact')
    require(digest((OUT/'reference_Expert_pre_noise.bin').read_bytes())==expected_meta['inputs']['noise_sha256'],'cross_process_actual_noise_exact')
    for filename,current,is_bf16 in [('reference_S0_raw_bf16.bin',raw0,True),('reference_S0_actions.bin',act0,False)]:
        data=(unified/filename).read_bytes()
        require(digest(data)==expected_meta['files'][filename]['sha256'],'unified_file_sha_'+filename)
        expected=np.frombuffer(data,dtype=current.dtype).reshape(current.shape).copy()
        require(current.dtype==expected.dtype and current.shape==expected.shape,'cross_process_storage_shape_'+filename)
        logical_shape=[50,32] if is_bf16 else [50,7]
        metrics=cross_evaluate(current.tobytes(),expected.tobytes(),'bf16' if is_bf16 else 'f32',logical_shape,logical_shape)
        report.setdefault('cross_process_comparisons',[]).append(dict(name=filename,**metrics));save()
        require(metrics['pass_'],'cross_process_absolute_'+filename)

    job[0]='reference_S1';stage(p1);orig=p1._encoder_layer;mid=[]
    def observe(i,seq,fuse_b1,stream):
        orig(i,seq,fuse_b1,stream)
        if i==8:mid.append(snap(p1,'reference_S1_boundary',9))
    p1._encoder_layer=observe
    try:context(p1);stream.synchronize()
    finally:p1._encoder_layer=orig
    ref1=snap(p1,'reference_S1');require(len(mid)==1,'S1_reference_boundary')
    for label in ('reference_S1','reference_S1_boundary'):
        for key in ('x','K','V'):
            actual=json.loads((OUT/(label+'_'+key+'.json')).read_text())
            require(actual==expected_meta['tensor_metadata'][label+'_'+key],'cross_process_'+label+'_'+key+'_exact')
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
    compare('reference_language_S0_finite',emb0,emb0);compare('reference_language_S1_finite',emb1,emb1)
    global _fast_compare
    _certified.update(digest(v.tobytes()) for v in tuple(ref0)+tuple(ref1)+tuple(mid[0])+(raw0,act0,emb0,emb1))
    _fast_compare=True
    report['gate']='PASS';save()
    if '--gate-only' in sys.argv:
        observer.close();memory('gate_complete');report.update(status='PASS',actual_timed_ledger={'Experts':0,'Contexts':0},gate_only=True)
        save();return


    # Capture only necessary results into PREALLOCATED device buffers. No D2H,
    # numerical comparison, or large disk write is performed inside a segment.
    def new_snap(layers):
        return dict(x=torch.empty(561*ENC_D*2,dtype=torch.uint8,device='cuda'),K=torch.empty((layers,561,1,256),dtype=torch.bfloat16,device='cuda'),V=torch.empty((layers,561,1,256),dtype=torch.bfloat16,device='cuda'))
    banks=dict(expert=[torch.empty(3200,dtype=torch.uint8,device='cuda') for _ in range(ncycles)],mid=[new_snap(9) for _ in range(nrefresh)],final=[new_snap(18) for _ in range(nrefresh)])
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
    for _ in cfg['segments']:
        es=[torch.cuda.Event(enable_timing=True) for _ in range(ncycles*10+32)]
        for e in es:e.record(stream)
        stream.synchronize();evpool.append(es)
    if cfg['capture']:torch.cuda.nvtx.range_push('M1_COMPLETION_TRACE')
    for segment_id,configuration in enumerate(cfg['segments']):
        if _time.monotonic()-_PROCESS_START>cfg['timeout_s']-cfg['tail_reserve_s']:
            report['status']='INCOMPLETE_TAIL_RESERVED';save();raise TimeoutError('no new segment; preserve60s cleanup/validation tail')
        Pms,plan=configuration['P_ms'],configuration['plan']
        hardware_before=_check_hardware()
        seg=dict(id=segment_id,P_ms=Pms,plan=plan,status='INCOMPLETE',experts=[],refreshes=[],blocks=[],retention=[],protocol='m1_completion_dual_gate_v3',cycles=ncycles,interference=configuration['interference'],unit_completions=[],B1_observation=[],cycle_miss_definition='max(Expert, assigned same-refresh B1/B2) versus r_j+P')
        report['segments'].append(seg);save()
        evs=iter(evpool[segment_id]);stage(p1);stream.synchronize()
        worker=None
        if configuration['interference']=='memcpy32MiB':
            worker_out=OUT/f'seg{segment_id}_interference'
            worker=subprocess.Popen([sys.executable,str(Path(__file__).with_name('m1_memcpy_interference.py')),'--out',str(worker_out),'--parent',str(os.getpid()),'--cpu','11','--bytes','33554432','--seconds','90'])
            _workers.append(worker)
            ready_until=time.monotonic()+5
            while not (worker_out/'ready.json').exists():
                if worker.poll() is not None or time.monotonic()>ready_until:raise RuntimeError('interference failed readiness')
                time.sleep(.01)
            seg['interference_pid']=worker.pid
        time.sleep(cfg['interference']['settle_s'])
        # All blocking one-time report writes precede the release clock.
        P=Pms*1_000_000
        experts,refreshes=jobs(0,P,ncycles)
        seg.update(hardware_before=hardware_before,expert_jobs=experts,refresh_jobs=refreshes)
        save();progress.flush();os.fsync(progress.fileno())
        t0=time.monotonic_ns()+10_000_000
        for rec in experts+refreshes:
            rec['release_ns']+=t0;rec['deadline_ns']+=t0
        seg['t0_ns']=t0
        journal('segment_start',segment=segment_id,t0_ns=t0,P_ms=Pms,plan=plan)
        health_at=[t0];seg['health_guard_cost_ns']=[]
        active_start=[None];b1_gpu_envelopes=[];seg['B2_submission']=[]
        def discover(now):
            if now-health_at[0]>=1_000_000_000:
                hb=time.monotonic_ns();seg.setdefault('hardware_in_window',[]).append(_check_hardware());he=time.monotonic_ns();seg['health_guard_cost_ns'].append(he-hb);health_at[0]=he
            if now-t0>cfg['segment_timeout_s']*1_000_000_000:raise TimeoutError('segment wall bound; keep unfinished ledger')
            if worker is not None and worker.poll() is not None:raise RuntimeError('interference ended before drain')
            for rec in experts+refreshes:
                if rec['status']=='NOT_RELEASED' and now>=rec['release_ns']:
                    rec['status']='READY';rec['discovered_ns']=now
                    if rec in refreshes:rec['prior_unfinished_at_discovery']=[v['id'] for v in refreshes if v['id']<rec['id'] and v['status']!='DONE']
        def run_op(kind,idx,fn):
            before=time.monotonic_ns();discover(before)
            start,end=next(evs),next(evs)
            journal('submit',segment=segment_id,work=kind,id=idx)
            start.record(stream);active_start[0]=start;submit_start=time.monotonic_ns()
            if cfg['capture']:torch.cuda.nvtx.range_push(f'M1_SEG_{segment_id}_{kind}_{idx}')
            try:fn()
            finally:
                if cfg['capture']:torch.cuda.nvtx.range_pop()
            submit_end=time.monotonic_ns()
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
            model_submit_return=time.monotonic_ns()
            evt=next(evs);rb=time.monotonic_ns();evt.record(stream);re=time.monotonic_ns()
            key=f'seg{segment_id}_R{refresh_id}'
            ab=time.monotonic_ns();observer.arm(key,evt,rb,re);ae=time.monotonic_ns()
            boundary=dict(id=refresh_id,key=key,model_submit_return_ns=model_submit_return,event_record_begin_ns=rb,event_record_end_ns=re,arm_cpu_ns=ae-ab,cuda_stream=0,unit_done_event='B1 model end, BEFORE diagnostic D2D',scheduler_boundary='after D2D and Block1 end-Event query only for two_blocks; no internal scheduler for whole_context')
            seg['B1_observation'].append(boundary);b1_gpu_envelopes.append((boundary,active_start[0],evt))
            ca,cb=next(evs),next(evs);cp=time.monotonic_ns();ca.record(stream);retain_snap(banks['mid'][refresh_id]);cb.record(stream);cq=time.monotonic_ns()
            boundary.update(retention_submit_begin_ns=cp,retention_submit_return_ns=cq)
            retained.append((dict(work='boundary_mid_retention',id=refresh_id,cpu_submit_ns=cq-cp),ca,cb))
        def submit_B2(refresh_id):
            before=time.monotonic_ns();block2(p1);after=time.monotonic_ns()
            seg['B2_submission'].append(dict(id=refresh_id,submit_before_ns=before,submit_return_ns=after,cuda_stream=0,plan=plan))
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
                    rec,a,b=run_op(kind,j,(lambda:(observed_B1(j),submit_B2(j))) if plan=='whole_context' else (lambda:observed_B1(j)) if phase==0 else (lambda:submit_B2(j)))
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
                    if is_final:
                        ca,cb=next(evs),next(evs);cp=time.monotonic_ns();ca.record(stream);retain_snap(banks['final'][j]);cb.record(stream);cq=time.monotonic_ns()
                        retained.append((dict(work=kind,id=j,cpu_submit_ns=cq-cp),ca,cb))
                else:
                    future=[v['release_ns'] for v in experts+refreshes if v['status']=='NOT_RELEASED']
                    if not future:raise RuntimeError('lost work ledger')
                    time.sleep(min(cfg['poll_sleep_s'],max(0,(min(future)-now)/1e9)))
        seg['drain_complete_observed_ns']=time.monotonic_ns();stream.synchronize()
        seg['timed_window_end_ns']=time.monotonic_ns()
        if worker is not None:stop_worker(worker)
        seg['hardware_after']=_check_hardware()
        seg['root_telemetry_window']=[s for s in read_root_samples(os.environ.get('COOVERLAP_ROOT_TELEMETRY')) if t0<=s['monotonic_ns']<=seg['timed_window_end_ns']]
        seg['frequency_condition']=assess(seg.get('hardware_in_window',[]),seg['root_telemetry_window'],t0,seg['timed_window_end_ns'])
        # Stop release clock measurement here. All D2H/comparisons/files below.
        for rec,a,b in timed:rec['event_elapsed_ms']=a.elapsed_time(b)
        for rec,a,b in b1_gpu_envelopes:rec['B1_begin_to_model_done_event_ms']=a.elapsed_time(b)
        seg['model_events']=[rec for rec,a,b in timed]
        for rec,a,b in retained:rec['event_elapsed_ms']=a.elapsed_time(b);seg['retention'].append(rec)
        seg['status']='DRAINED_VALIDATION_PENDING';save();os.fsync(progress.fileno())
        raw_experts=[store(f'seg{segment_id}_E{j}_raw',t.cpu().numpy()) for j,t in enumerate(banks['expert'])]
        snapshots={}
        for q in range(nrefresh):
            for tag in ['final','mid']:
                snapshots[q,tag]=[store(f'seg{segment_id}_R{q}_{tag}_{k}',banks[tag][q][k].view(torch.uint8).cpu().numpy()) for k in ['x','K','V']]
        old=snap(p0,f'seg{segment_id}_old_v0')
        after=buffer_dtypes(address_manifest(owner,p0,p1,attn1,runner1,validate=False));save_json(OUT/f'seg{segment_id}_resources.json',after)
        for j,raw in enumerate(raw_experts):
            compare(f'seg{segment_id}_E{j}',raw,raw0)
            values=torch.from_numpy(raw.copy()).view(torch.bfloat16).float().reshape(50,32).numpy()
            actions=store(f'seg{segment_id}_E{j}_actions',unnormalize_actions(values,owner.norm_stats)[:,:7])
            compare(f'seg{segment_id}_E{j}_actions',actions,act0,False)
        compare(f'seg{segment_id}_fixed_noise_source',noise.view(torch.uint8).cpu().numpy().reshape(f['noise0_bf16_bytes'].shape),f['noise0_bf16_bytes'])
        require(digest(read(p1.input_images_buf.ptr.value,p1.input_images_buf.nbytes))==report['preprocessed_image_sha256'],f'seg{segment_id}_images_protected')
        for q in range(nrefresh):
            for k,a,b in zip(['x','K','V'],snapshots[q,'final'],ref1):compare(f'seg{segment_id}_R{q}_final_{k}',a,b)
            for k,a,b in zip(['x','K','V'],snapshots[q,'mid'],mid[0]):compare(f'seg{segment_id}_R{q}_mid_{k}',a,b)
        for k,a,b in zip(['x','K','V'],old,ref0):compare(f'seg{segment_id}_old_{k}',a,b)
        require(pointer0==pointer_leaves(p0.weights)==pointer_leaves(p1.weights),'seg'+str(segment_id)+'_shared_weight_owner')
        compare(f'seg{segment_id}_S0_language',read(p0._lang_embeds_buf.ptr.value,p0._lang_embeds_buf.nbytes),emb0)
        compare(f'seg{segment_id}_S1_language',read(p1._lang_embeds_buf.ptr.value,p1._lang_embeds_buf.nbytes),emb1)
        require(not after['overlaps'],'seg'+str(segment_id)+'_resources_disjoint')
        require({x['name']:(x['ptr'],x['nbytes']) for x in after['writable']}=={x['name']:(x['ptr'],x['nbytes']) for x in manifest['writable']},'seg'+str(segment_id)+'_resource_addresses_stable')
        for j in range(ncycles):require(report['ledger'][f'seg{segment_id}_E{j}']['v0']['decoder']==expected_dec,f'seg{segment_id}_E{j}_10steps')
        for q in range(nrefresh):
            layers=report['ledger'][f'seg{segment_id}_R{q}_Context']['v1']['encoder'] if plan=='whole_context' else report['ledger'][f'seg{segment_id}_R{q}_Block1']['v1']['encoder']+report['ledger'][f'seg{segment_id}_R{q}_Block2']['v1']['encoder']
            require(layers==list(range(18)),f'seg{segment_id}_R{q}_18layers')
        mem=memory(f'seg{segment_id}_validated');require(mem['cuda_free']>12*1024**3 and baseline_memory['cuda_free']-mem['cuda_free']<2*1024**3,'segment_memory_normal')
        seg['cycle_obligations']=cycle_rows(seg)
        seg['cycle_statistics']={k:counts([v[k] for v in seg['cycle_obligations']]) for k in ['cycle_status','expert_status','VLM_status']}
        seg['refresh_statistics']=counts([classify(x['completion_lower_ns'],x['ready_observed_ns'],x['deadline_ns']) for x in seg['refreshes']])
        seg['status']='PASS';save();journal('segment_validated',segment=segment_id)
    if cfg['capture']:torch.cuda.nvtx.range_pop()
    observer.close()
    report['status']='PASS';report['scope']='bounded M1 completion batch; serial legal contrasts only; no concurrent or net partition-loss inference';save()
    print(json.dumps(dict(status='PASS',segments=len(report['segments']),out=str(OUT))),flush=True)

try:main()
except BaseException:
    if report.get('status') not in ('INCOMPLETE_TIMEOUT_OR_SIGNAL','INCOMPLETE_TAIL_RESERVED'):report['status']='INCOMPLETE_BOUND' if isinstance(sys.exc_info()[1],TimeoutError) else 'FAIL'
    for proc in _workers:
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=2)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    report['error']=traceback.format_exc()
    if report.get('segments') and report['segments'][-1]['status']!='PASS':
        report['segments'][-1]['status']='INCOMPLETE' if report['status'].startswith('INCOMPLETE') else 'FAIL'
    save();raise
