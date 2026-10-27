"""Prepared M2 clean serial baseline; math/preparation inherited from passed v3.

No model or hardware operation on import/dry-run. New explicit authorization
and a CPU credential are required. Both modes share CleanBackend/replay_segment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback
from m2_executor import VersionedKV,Snapshot,BLOCKS
from m2_clean_core import PROTOCOL,protocol,replay_segment,gate_retention_layout
from pi05_m2_correctness_v3 import sha


def jsonable(value):
    if isinstance(value,dict):return {str(k):jsonable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [jsonable(v) for v in value]
    return value


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--approved-m2-clean-v1',action='store_true')
    ap.add_argument('--verification-mode',choices=['performance','correctness'],default='performance')
    ap.add_argument('--config',type=Path)
    ap.add_argument('--out',type=Path)
    ap.add_argument('--reference',type=Path)
    ap.add_argument('--source-preflight',type=Path)
    args=ap.parse_args()
    if args.config is not None and json.loads(args.config.read_text())!=protocol():
        raise ValueError('configuration differs from frozen A/B/B/A contract')
    if args.dry_run:
        print(json.dumps(protocol(),indent=2));return
    if not args.approved_m2_clean_v1 or os.environ.get('COOVERLAP_APPROVED_BATCH')!=PROTOCOL:
        ap.error('new explicit M2 clean GPU/hardware approval required before GPU imports')
    if None in (args.out,args.reference,args.source_preflight,args.config):ap.error('out/reference/preflight/config required')
    from m2_clean_control import verify_credential
    credential=verify_credential(args.config.parent,args.source_preflight.parent,sha(args.source_preflight),large_files=False)
    if os.geteuid()==0:raise RuntimeError('ordinary nvidia model only')
    for key,value in os.environ.items():
        if value and (key.startswith(('NSYS_','KINETO_','TORCH_PROFILER_','CUPTI_INJECTION','CUDA_INJECTION')) or key=='LD_PRELOAD'):
            raise RuntimeError('unexpected injection: '+key)
    args.out.mkdir(exist_ok=False)
    report=dict(status='INCOMPLETE',protocol=protocol(),observation_mode=args.verification_mode,
                source_preflight_sha256=sha(args.source_preflight),checks=[],segments=[],
                source_config_fingerprints={k:v['sha256'] for k,v in credential['package'].items()},
                config_sha256=sha(args.config))
    def save():
        tmp=args.out/'result.tmp';tmp.write_text(json.dumps(jsonable(report),indent=2));tmp.replace(args.out/'result.json')
    def require(ok,name):
        report['checks'].append(dict(name=name,pass_=bool(ok)))
        if not ok:save();raise AssertionError(name)
    start=time.monotonic();deadline=time.monotonic_ns()+170_000_000_000
    def bound():
        if time.monotonic_ns()>=deadline:raise TimeoutError('170s internal stop; no new work')
        if int(Path('/sys/devices/virtual/thermal/thermal_zone0/temp').read_text())>=80000:raise RuntimeError('thermal stop >=80C')
    def term(signum,frame):raise TimeoutError('signal; no automatic retry')
    signal.signal(signal.SIGTERM,term)
    device=None;backend=None
    try:
        from m1_clock_scope_v6 import state
        limits=state()
        require(all(row['min']==row['max']==row['target']==row['cur'] for row in limits),'fixed_conditions_before_model_warmup_autotune')
        report['initial_clock_limits']=limits
        import ctypes
        import numpy as np
        import torch
        import flash_rt_gemm_diag as diag
        from pi05_dual_slot_adapter import build_slots,address_manifest,CHECKPOINT
        from flash_rt.models.pi05.pipeline_rtx import ENC_D,VIS_D
        from flash_rt.core.utils.actions import unnormalize_actions
        from m1_dual_gate import evaluate
        from m2_pi05_ops import context,block1,block2,CallLedger
        require(sha(diag.__file__)=='bee648c5b5a9821084a39bb88ed9cba9681503c1043f90a7c95ace0bb1048d78','existing_diag_binary')
        fp=Path('/tmp/cooverlap_pi05_fixed_reference.npz');sp=Path('/tmp/cooverlap_pi05_state_versions.npz')
        require(sha(fp)=='92f1a92b64352cc34010c81c1accd1cb00fcb227d0004f545b87549d5d6c544d','fixed_fixture')
        require(sha(sp)=='cabb191ec2b319c43fa769e5c8b9b8851724ef25ecff8850d118b8276124205e','fixed_states')
        require(sha(CHECKPOINT/'config.json')=='0458a362b574c2cb088ebf3767c9eacb1f040b9cb680a89b594379a4fe36e5f7','fixed_model_config')
        require(json.loads((CHECKPOINT/'config.json').read_text())['state_cond'] is False,'state_cond_false')
        require(next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))>=36*1024**2,'available_system_memory_36GiB')
        disk=os.statvfs(args.out);require(disk.f_bavail*disk.f_frsize>=12*1024**3,'disk_space_12GiB')
        require(torch.cuda.mem_get_info()[0]>12*1024**3,'pre_model_free_memory')
        require(int(Path('/sys/devices/virtual/thermal/thermal_zone0/temp').read_text())<80000,'temperature_below_80C')
        f=np.load(fp,allow_pickle=False);ss=np.load(sp,allow_pickle=False)
        owner,p0,p1,attn1,runner1=build_slots(ss['s0'].copy(),ss['s1'].copy(),{k:f[k].copy() for k in ('image','wrist_image','state')},diag.GemmRunner)
        ps=[p0,p1];stream=torch.cuda.default_stream();require(stream.cuda_stream==0,'stream0')
        require(torch.cuda.mem_get_info()[0]>12*1024**3,'post_model_free_memory')
        manifest=address_manifest(owner,p0,p1,attn1,runner1)
        (args.out/'address_before.json').write_text(json.dumps(manifest,indent=2))
        for p in ps:
            require(not any(getattr(p,k) for k in ('use_fp8','use_fp8_decoder','use_int8_encoder','use_int8_decoder','use_int8_vision')),'BF16_only')
            require((p.encoder_seq_len,p._current_prompt_len,p.vision_num_layers,p.num_steps,p.chunk_size)==(561,49,27,10,50),'full_fixed_work')
            require(p._graph is None and p._decoder_only_graph is None and not p._state_active,'Eager_only')
        images=owner._stack_images({k:f[k] for k in ('image','wrist_image','state')})
        require(tuple(images.shape)==(2,224,224,3) and images.dtype==torch.bfloat16,'fixed_images_shape_dtype')
        expected_meta=json.loads((args.reference/'MANIFEST.json').read_text())
        require(hashlib.sha256(images.view(torch.uint8).cpu().numpy().tobytes()).hexdigest()==expected_meta['preprocessed_image_sha256'],'fixed_preprocessed_images')
        noise=torch.from_numpy(f['noise0_bf16_bytes'].copy()).cuda().view(torch.bfloat16).reshape(50,32)
        def digest(data):return hashlib.sha256(data).hexdigest()
        def read(ptr,n):
            out=torch.empty(n,dtype=torch.uint8,device='cuda')
            rc=owner._cudart.cudaMemcpyAsync(ctypes.c_void_p(out.data_ptr()),ctypes.c_void_p(ptr),n,3,0)
            if rc:raise RuntimeError('D2D copy status '+str(rc))
            stream.synchronize();return out.cpu().numpy().tobytes()
        def tensor_bytes(t):return t.contiguous().view(torch.uint8).cpu().numpy().tobytes()
        def store(name,data):
            (args.out/(name+'.bin')).write_bytes(data);return dict(nbytes=len(data),sha256=digest(data))
        def snap(p,name,layers=18,persist=True):
            stream.synchronize()
            out=(read(p.bufs['encoder_x'].ptr.value,561*ENC_D*2),tensor_bytes(p.attn.enc_K[:layers,:561]),tensor_bytes(p.attn.enc_V[:layers,:561]))
            if persist:
                for key,data in zip(('x','K','V'),out):store(name+'_'+key,data)
            return out
        def equal_snap(name,got,wanted):
            report.setdefault('snapshot_checks',[]).append(dict(name=name,actual=[digest(x) for x in got],expected=[digest(x) for x in wanted],exact=got==wanted))
            if got!=wanted:
                for key,a,b in zip(('x','K','V'),got,wanted):store(name+'_actual_'+key,a);store(name+'_expected_'+key,b)
            require(got==wanted,name+'_exact')
        def stage(p,with_images=False):
            if with_images:owner._copy_tensor_to_pipeline_buf_stream(images,p.input_images_buf,0)
            owner._copy_tensor_to_pipeline_buf_stream(noise,p.input_noise_buf,0);stream.synchronize()
            require(read(p.input_noise_buf.ptr.value,3200)==f['noise0_bf16_bytes'].tobytes(),'fixed_actual_noise')
        def outputs(p,name):
            raw=read(p.input_noise_buf.ptr.value,3200)
            vals=torch.from_numpy(np.frombuffer(raw,dtype=np.uint8).copy()).view(torch.bfloat16).float().reshape(50,32).numpy()
            require(np.isfinite(vals).all(),name+'_finite')
            actions=np.ascontiguousarray(unnormalize_actions(vals,owner.norm_stats)[:,:7],dtype=np.float32).tobytes()
            store(name+'_raw',raw);store(name+'_actions',actions);return raw,actions
        noise_sha=digest(f['noise0_bf16_bytes'].tobytes())
        snaps=[Snapshot('S'+str(i),digest(f['image'].tobytes()),digest(f['wrist_image'].tobytes()),digest(ss['s'+str(i)].tobytes()),digest(read(p._lang_embeds_buf.ptr.value,p._lang_embeds_buf.nbytes)),noise_sha) for i,p in enumerate(ps)]
        report['snapshots']=[vars(s) for s in snaps]
        # S1: ramp DVFS with real, discarded model work before any autotune measurement.
        gpu_max=int(Path('/sys/class/devfreq/17000000.gpu/max_freq').read_text())
        warm=[]
        for _ in range(2):
            bound();stage(ps[1],True);context(ps[1]);stream.synchronize()
            warm.append(int(Path('/sys/class/devfreq/17000000.gpu/cur_freq').read_text()))
        report['autotune_warmup']=dict(iterations=len(warm),gpu_cur_freq=warm,gpu_max_freq=gpu_max,
            note='exactly two complete Contexts on slot1; discarded; outside all replay windows')
        require(warm[-1]>=gpu_max*9//10,'gpu_frequency_at_max_before_autotune')
        for slot_id,p in enumerate(ps):
            print('M2_CLEAN_AUTOTUNE_BEGIN slot='+str(slot_id),flush=True)
            require(getattr(p,'_gemms_autotuned',False) is False,'autotune_not_already_done')
            p.autotune_gemms();stream.synchronize();bound()
            print('M2_CLEAN_AUTOTUNE_END slot='+str(slot_id),flush=True)
        report['autotune_started_at_gpu_freq']=int(Path('/sys/class/devfreq/17000000.gpu/cur_freq').read_text())
        require(report['autotune_started_at_gpu_freq']>=gpu_max*9//10,'autotune_ran_at_max_frequency')
        ledger=CallLedger(ps);refs=[];midrefs=[]
        # Two complete, original Context + Expert10 references; observer only.
        for i,p in enumerate(ps):
            bound();stage(p,True);old=p._encoder_layer;mid=[]
            def observe(n,seq,fuse_b1,stream,orig=old):
                orig(n,seq,fuse_b1,stream)
                if n==8:mid.append(snap(p,'ref'+str(i)+'_mid',9))
            p._encoder_layer=observe
            try:ledger.execute('reference_context'+str(i),i,'Context',lambda:context(p))
            finally:p._encoder_layer=old
            stream.synchronize();ctx=snap(p,'ref'+str(i)+'_context')
            meta=json.loads((args.reference/('MANIFEST.json' if i==0 else 'S1_OUTPUT_MANIFEST.json')).read_text())
            # D1: the frozen cross-process SHA tags the numerical configuration.
            # It is recorded, not an admission criterion.
            frozen=json.loads((args.reference/'MANIFEST.json').read_text())['tensor_metadata']
            for key,data in zip(('x','K','V'),ctx):
                want=frozen['reference_S'+str(i)+'_'+key]['sha256']
                report.setdefault('context_configuration',[]).append(
                    dict(snapshot='S'+str(i),tensor=key,sha256=digest(data),frozen=want,
                         matches_frozen=digest(data)==want))
            ledger.execute('reference_expert'+str(i),i,'Expert',lambda:p.transformer_decoder(0));stream.synchronize()
            raw,act=outputs(p,'ref'+str(i));refs.append((ctx,raw,act));midrefs.append(mid[0])
            for suffix,data,kind,shape in [('raw_bf16',raw,'bf16',[50,32]),('actions',act,'f32',[50,7])]:
                fn='reference_S'+str(i)+'_'+suffix+'.bin';olddata=(args.reference/fn).read_bytes()
                require(digest(olddata)==meta['files'][fn]['sha256'],'historical_reference_sha')
                metrics=evaluate(data,olddata,kind,shape,shape);report.setdefault('cross_process',[]).append(dict(name=fn,**metrics))
        # D1 admission: original single-call pipeline vs the split path, same process,
        # same buffers, byte exact. Ledger wrappers are bypassed for this one call so
        # the observed ledger stays exact; this extra 1C/1E is declared separately.
        report['configuration']=dict(
            S0_context_sha256=[digest(x) for x in refs[0][0]],
            S1_context_sha256=[digest(x) for x in refs[1][0]],
            matches_frozen_context=all(digest(a)==frozen['reference_S0_'+k]['sha256']
                                       for a,k in zip(refs[0][0],('x','K','V'))),
            label_scope='S0 Context tag (v3 definition); S1 complete SHA recorded separately',
            slot_context_tags={str(i):('H_frozen_S'+str(i) if all(digest(a)==frozen['reference_S'+str(i)+'_'+k]['sha256'] for a,k in zip(refs[i][0],('x','K','V'))) else 'OTHER_S'+str(i)+'_'+digest(refs[i][0][0])[:12]) for i in (0,1)},
            label='H_frozen' if all(digest(a)==frozen['reference_S0_'+k]['sha256']
                                    for a,k in zip(refs[0][0],('x','K','V'))) else 'OTHER_S0_'+digest(refs[0][0][0])[:12])
        saved=tuple(getattr(p0,n) for n in ('_encoder_layer','_decoder_layer','vision_encoder',
                                            '_copy_lang_embeds_to_encoder_x'))
        p0._encoder_layer,p0._decoder_layer,p0.vision_encoder,p0._copy_lang_embeds_to_encoder_x=ledger.original[0][1:5]
        try:
            stage(p0,True);p0.run_pipeline(0);stream.synchronize()
        finally:
            p0._encoder_layer,p0._decoder_layer,p0.vision_encoder,p0._copy_lang_embeds_to_encoder_x=saved
        eq_ctx=snap(p0,'equivalence_pipeline_context');eq_raw,eq_act=outputs(p0,'equivalence_pipeline')
        pairs=[('context_x',refs[0][0][0],eq_ctx[0]),('context_K',refs[0][0][1],eq_ctx[1]),
               ('context_V',refs[0][0][2],eq_ctx[2]),('raw',refs[0][1],eq_raw),('actions',refs[0][2],eq_act)]
        for name,a,b in pairs:
            report['checks'].append(dict(name='in_process_'+name+'_byte_exact',pass_=digest(a)==digest(b)))
            require(digest(a)==digest(b),'in_process_'+name+'_byte_exact')
        report['in_process_equivalence']=dict(
            original='run_pipeline(0)', split='context()+transformer_decoder(0)',
            tensors=[n for n,_,_ in pairs], byte_exact=True,
            scope='same process, same slot, same staged inputs; no frozen reference involved')

        from m2_clean_cuda import CudaDevice
        from m2_clean_backend import CleanBackend
        from m2_clean_stats import augment,write_tables
        from m2_clean_core import ORDER,retention_layout
        # Certify complete reference payloads once, before all replay windows.
        expected=dict(images=images.view(torch.uint8).cpu().numpy().tobytes(),
                      noise=f['noise0_bf16_bytes'].tobytes())
        for slot_id in (0,1):
            expected['ref'+str(slot_id)]=b''.join(refs[slot_id][0])
            expected['mid'+str(slot_id)]=b''.join(midrefs[slot_id])
            expected['raw'+str(slot_id)]=refs[slot_id][1]
            for data in (*refs[slot_id][0],*midrefs[slot_id]):
                vals=(np.frombuffer(data,dtype='<u2').astype('<u4')<<16).view('<f4')
                require(np.isfinite(vals).all(),'finite_same_process_context_reference')
        original_manifest=address_manifest(owner,p0,p1,attn1,runner1)
        bank_bytes=retention_layout()['nbytes']
        require(torch.cuda.mem_get_info()[0]>12*1024**3+2*bank_bytes,'memory_budget_before_GPU_and_pinned_retention')
        initial_states=[]
        def bootstrap(m,snapshots,key):
            h=m.begin(0,snapshots[0]);stage(p0,True)
            ledger.execute(device.namespace+str(device.epoch)+'/bootstrap',0,'Context',lambda:context(p0))
            ev=torch.cuda.Event();ev.record(stream);ev.synchronize()
            for b in (0,1):m.submit_block(h,b,snapshots[0],BLOCKS[b],ev);require(m.poll_block(h),'bootstrap_complete')
            require(snap(p0,device.namespace+str(device.epoch)+'_bootstrap')==refs[0][0],'bootstrap_matches_same_process_S0')
            m.publish(h)
        def before_window(phase,d,initial):
            d.guard('report preparation')
            require(address_manifest(owner,p0,p1,attn1,runner1)==original_manifest,'visible_resources_stable_before_window')
            require(torch.cuda.mem_get_info()[0]>12*1024**3,'memory_safety_floor_after_retention')
            for i,p in enumerate(ps):
                require(snap(p,'initial_'+d.namespace+str(d.epoch)+'_slot'+str(i))==refs[i][0],'equal_physical_initial_Context')
                require(read(p._lang_embeds_buf.ptr.value,p._lang_embeds_buf.nbytes)==(embeddings[i]),'language_not_modified')
            if d.namespace=='segment':
                if initial_states:require(initial==initial_states[0],'identical_logical_initial_state')
                initial_states.append(initial)
            d.record['initial_state']=initial
            d.record['source_fingerprint']=report['configuration']
            save()
            # Settle this batch's preparation/output I/O before formal t0.
            # No global sync and no disk operation occurs in the window.
            for prepared in args.out.rglob('*'):
                if prepared.is_file():
                    with prepared.open('rb') as f:os.fsync(f.fileno())
            for directory in [args.out,*[p for p in args.out.rglob('*') if p.is_dir()]]:
                fd=os.open(directory,os.O_RDONLY)
                try:os.fsync(fd)
                finally:os.close(fd)
            sys.stdout.flush();sys.stderr.flush();os.fsync(1);os.fsync(2)
        embeddings=[read(p._lang_embeds_buf.ptr.value,p._lang_embeds_buf.nbytes) for p in ps]
        device=CudaDevice(torch,np,owner,ps,ledger,expected,[r[2] for r in refs],owner.norm_stats,
                          (context,lambda p:block1(p,ENC_D,VIS_D),block2),bootstrap,before_window,args.out,deadline)
        device.images=images;device.noise=noise
        # Explicitly rule out bank aliasing with all model/weight buffers.
        intervals=original_manifest['writable']+original_manifest['shared_readonly']
        require(not any(e['ptr'] and e['nbytes'] and max(device.gptr,e['ptr'])<min(device.gptr+bank_bytes,e['ptr']+e['nbytes']) for e in intervals),'retention_bank_no_model_alias')
        require(images.is_contiguous() and noise.is_contiguous(),'preallocated_contiguous_inputs')
        report['retention_memory']=dict(GPU_B=bank_bytes,Host_pinned_B=bank_bytes,
                                        free_after_allocation_B=torch.cuda.mem_get_info()[0])
        # The same backend is used for v3's cross-publication gate, in the
        # intrusive correctness observation mode, entirely before formal t0.
        device.namespace='gate';gate=dict(status='INCOMPLETE');report['gate']=gate
        backend=CleanBackend(device,snaps,'correctness',layout=gate_retention_layout())
        m=VersionedKV();backend.prepare(m,None,gate);backend.bootstrap(m,'bootstrap');backend.ready(m)
        m.bind('E0',noise_sha);old=m.current;new=m.begin(1,snaps[1])
        backend.enter_window()
        try:
            backend.stage(m,new,'R0');backend.block(m,new,0,'R0/B1');backend.block(m,new,1,'R0/B2');m.publish(new)
            require(m.bind('latest',noise_sha)==new,'latest_published_binding');m.cancel_unsubmitted('latest')
            try:m.reclaim(old)
            except RuntimeError:report['checks'].append(dict(name='old_bound_reader_blocks_reuse',pass_=True))
            else:raise AssertionError('premature old-slot recycle')
            backend.expert(m,'E0',old);m.reclaim(old);backend.drain()
        finally:backend.leave_window();gate['journal']=m.journal
        backend.validate_and_persist();require(len(m.journal)==18,'version_gate_same_18_journal_contract')
        report['gate_journal']=m.journal;save()
        device.namespace='segment'
        backend=CleanBackend(device,snaps,args.verification_mode)
        for index,mode in enumerate(ORDER):
            bound();record=dict(index=index,status='NOT_STARTED');report['segments'].append(record)
            m=VersionedKV()
            try:
                replay_segment(m,snaps,mode,backend,record,time.monotonic_ns)
            finally:
                record['metrics']=augment(record)
            backend.validate_and_persist()
            require(address_manifest(owner,p0,p1,attn1,runner1)==original_manifest,'visible_resources_stable_after_window')
            write_tables(record,args.out/('segment'+str(index)))
            report['completed_segments']=index+1;save()
        # Full observed call ledger excludes the separately declared 2 warmup
        # Contexts and one original-pipeline D1 call, exactly as in frozen v3.
        from collections import Counter
        counts=dict(Counter(x[2] for x in ledger.calls));report['observed_call_counts']=counts
        require(counts==dict(encoder=720,decoder=12060,language=40,vision27=40),'complete_observed_work_12860_rows')
        require(len(ledger.calls)==12860,'complete_observed_ledger_size')
        require(owner._cudart.cudaGetLastError()==0,'cuda_last_error')
        report['call_ledger']=ledger.calls
        within=all(row['pass_'] for row in report['cross_process'])
        report['cross_process_gate']=dict(within_historical_envelope=within,admission=False,
                                         policy='D1 report item; no configuration filtering/retry')
        report['status']='PASS' if within else 'PASS_IN_PROCESS_DEVIATION'
        report['performance_data_eligible_for_offline_hardware_review']=args.verification_mode=='performance'
        report['elapsed_s']=time.monotonic()-start;save()
    except BaseException:
        report['status']='FAIL_OR_INCOMPLETE';report['error']=traceback.format_exc()
        if backend is not None:
            backend.leave_window()
            report['unfinished_retention']=backend.bank.metadata()
        if 'ledger' in locals():report['call_ledger']=ledger.calls
        report['elapsed_s']=time.monotonic()-start;save();raise


if __name__=='__main__':main()
