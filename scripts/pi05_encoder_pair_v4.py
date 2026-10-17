"""One predeclared post-Vision Encoder pair, no kernel or algorithm changes."""
import ctypes as C, time

def run_pair(env):
    import numpy as np
    import torch
    from flash_rt.models.pi05.pipeline_rtx import ENC_D,VIS_D
    from pi05_dual_slot_adapter import address_manifest
    from green_pair_resources_v4 import PairRuntime
    from pathlib import Path
    import os
    owner,p0,p1,attn1,runner1=(env[k] for k in ('owner','p0','p1','attn1','runner1'))
    report,store,compare,require,save=(env[k] for k in ('report','store','compare','require','save'))
    stage,snap,action,noise,pub0=(env[k] for k in ('stage','snap','action','noise','pub0'))
    ref0,ref1,mid,raw0,act0=(env[k] for k in ('ref0','ref1','mid','raw0','act0'))
    job,expected,started=(env[k] for k in ('job','expected_stream','_PROCESS_START'))
    r=report['pair']=dict(status='INCOMPLETE',samples=[],api=[],physical_kernel_overlap='UNKNOWN: no extra Nsight trace in this batch',closed_library_internal_scratch='UNKNOWN')
    rt=None;streams=[];original=[];routes={}
    class Proxy:
        def __init__(self,obj,label,slot):self.obj=obj;self.label=label;self.slot=slot;self.cache={}
        def __getattr__(self,name):
            fn=getattr(self.obj,name)
            if not callable(fn):return fn
            if name not in self.cache:
                def call(*a,**kw):
                    supplied=kw.get('stream')
                    if self.label=='FVK' and name in ('patch_im2col','avg_pool_vision_tokens') and 'stream' not in kw:supplied=a[-1]
                    if supplied!=expected[self.slot] or torch.cuda.current_stream().cuda_stream!=expected[self.slot]:raise RuntimeError('stream route mismatch '+self.slot+'.'+self.label+'.'+name)
                    key=self.slot+'.'+self.label+'.'+name;routes[key]=routes.get(key,0)+1
                    return fn(*a,**kw)
                self.cache[name]=call
            return self.cache[name]
    def deadline():
        if time.monotonic()-started>120:raise TimeoutError('pair reserve60s: no new sample')
    def prefix():
        expected['v1']=0;stage(p1);job[0]='pair_prefix_'+str(len(r['samples']))
        h=time.monotonic_ns();a,b=torch.cuda.Event(enable_timing=True),torch.cuda.Event(enable_timing=True);a.record()
        p1._copy_lang_embeds_to_encoder_x(0);p1.vision_encoder(0)
        B,W=p1.bufs,p1.weights;vs=p1.vision_seq_enc
        p1.fvk.layer_norm(B['vision_x_pooled'].ptr.value,W['vision_final_norm_w'],W['vision_final_norm_b'],B['vision_x_norm'].ptr.value,vs,VIS_D,1e-5,stream=0)
        p1.gemm.bf16_nn(B['vision_x_norm'].ptr.value,W['encoder_multi_modal_projector_w'],B['encoder_x'].ptr.value,vs,ENC_D,VIS_D,stream=0)
        p1.fvk.add_bias_bf16(B['encoder_x'].ptr.value,W['encoder_multi_modal_projector_b'],vs,ENC_D,stream=0)
        b.record();b.synchronize()
        return dict(host_begin_ns=h,complete_ack_ns=time.monotonic_ns(),event_ms=a.elapsed_time(b),vision_layers=27,encoder_layers=[])
    try:
        torch.cuda.synchronize();rt=PairRuntime(owner._cudart,r['api']);r['resources']=rt.setup()
        ordinaryA=torch.cuda.ExternalStream(rt.ordinary.value,device=0);ordinaryB=torch.cuda.Stream()
        greenA=torch.cuda.ExternalStream(rt.green.value,device=0);greenB=torch.cuda.ExternalStream(rt.green_b.value,device=0)
        streams=[ordinaryA,ordinaryB,greenA,greenB]
        require([rt.resource(s.cuda_stream) for s in streams]==[16,16,8,8],'pair_stream_resource_counts')
        probe=Path(os.environ['COOVERLAP_PROBE_CUBIN']);r['probe_sha256']=env['digest'](probe.read_bytes())
        require(r['probe_sha256']=='68374788021779b09326587e04099d1a71a1a585145aba02379bc0c8c410faad','existing_probe_binary_sha')
        rt.load_probe(probe)
        ids=torch.empty(4096,dtype=torch.int32,device='cuda');vals=torch.empty_like(ids);torch.cuda.synchronize();observed=[]
        for name,s in [('greenA',greenA),('greenB',greenB)]:
            rt.probe(s.cuda_stream,ids.data_ptr(),vals.data_ptr());s.synchronize()
            ii,vv=ids.cpu().numpy(),vals.cpu().numpy();observed.append(set(map(int,ii)))
            r.setdefault('probes',{})[name]=dict(stream=s.cuda_stream,SM_ids=sorted(observed[-1]),resource_SM=rt.resource(s.cuda_stream))
            require(np.array_equal(vv,np.arange(4096,dtype=np.int32)+7) and 0<=ii.min()<=ii.max()<16,name+'_probe_values')
        require(len(observed[0])==8 and len(observed[1])==8 and not observed[0]&observed[1],'two_8SM_probe_observed_sets_disjoint')
        r['addresses_before']=address_manifest(owner,p0,p1,attn1,runner1,validate=False)
        require(not r['addresses_before']['overlaps'],'pair_visible_intervals_disjoint')
        for slot,p in [('v0',p0),('v1',p1)]:
            original.append((p,p.gemm,p.fvk,p.attn._fa2_fwd))
            p.gemm=Proxy(p.gemm,'GEMM',slot);p.fvk=Proxy(p.fvk,'FVK',slot)
            fn=p.attn._fa2_fwd
            def fa(*a,_fn=fn,_slot=slot,**kw):
                if kw.get('stream')!=expected[_slot] or torch.cuda.current_stream().cuda_stream!=expected[_slot]:raise RuntimeError('FA2 route mismatch '+_slot)
                return _fn(*a,**kw)
            p.attn._fa2_fwd=fa
        retained=dict(x=torch.empty(561*ENC_D*2,dtype=torch.uint8,device='cuda'),K=torch.empty((9,561,1,256),dtype=torch.bfloat16,device='cuda'),V=torch.empty((9,561,1,256),dtype=torch.bfloat16,device='cuda'))
        torch.cuda.synchronize();save()
        def sample(mode,role,index):
            deadline();name=f'pair_{role}_{mode}_{index}';prefix_rec=prefix()
            expected['v0']=0;owner._copy_tensor_to_pipeline_buf_stream(noise,p0.input_noise_buf,0);torch.cuda.synchronize()
            require(env['read'](p0.input_noise_buf.ptr.value,3200).tobytes()==env['f']['noise0_bf16_bytes'].tobytes(),name+'_actual_noise')
            A,B=(greenA,greenB) if mode in ('fixed','return') else (ordinaryA,ordinaryB)
            if mode=='serial':B=A # single-stream ordering, no artificial Expert wait
            events=[torch.cuda.Event(enable_timing=True) for _ in range(7)];anchor,a1,b1,a2,b2,es,ee=events
            for e in events:e.record()
            torch.cuda.synchronize();anchor.record();anchor.synchronize()
            A.wait_event(anchor);B.wait_event(pub0);B.wait_event(anchor)
            rec=dict(name=name,mode=mode,role=role,prefix=prefix_rec,v0='published S0',v1='unpublished S1',B1_stream=A.cuda_stream,Expert_stream=B.cuda_stream,routes_before=dict(routes))
            r['samples'].append(rec);save();release=time.monotonic_ns()
            expected['v1']=A.cuda_stream;job[0]=name+'_enc0_8'
            with torch.cuda.stream(A):
                rec['B1_submit_begin_ns']=time.monotonic_ns();a1.record(A)
                for i in range(9):p1._encoder_layer(i,561,False,A.cuda_stream)
                b1.record(A);rec['B1_submit_return_ns']=time.monotonic_ns()
            expected['v0']=B.cuda_stream;job[0]=name+'_Expert'
            with torch.cuda.stream(B):
                rec['Expert_submit_begin_ns']=time.monotonic_ns();es.record(B);p0.transformer_decoder(B.cuda_stream);ee.record(B);rec['Expert_submit_return_ns']=time.monotonic_ns()
            # No artificial wait for Expert to manufacture a return window.
            ack0=time.monotonic_ns();b1.synchronize();ack1=time.monotonic_ns()
            rec.update(boundary_wait_begin_ns=ack0,boundary_confirmed_ns=ack1,Expert_done_at_boundary=ee.query())
            # Midpoint retention has identical cost and lies outside B1/B2 model Events.
            with torch.cuda.stream(A):
                retained['K'].copy_(p1.attn.enc_K[:9,:561]);retained['V'].copy_(p1.attn.enc_V[:9,:561])
                rc=owner._cudart.cudaMemcpyAsync(C.c_void_p(retained['x'].data_ptr()),C.c_void_p(p1.bufs['encoder_x'].ptr.value),retained['x'].numel(),3,A.cuda_stream)
                if rc:raise RuntimeError('pair midpoint D2D '+str(rc))
                retained_done=torch.cuda.Event();retained_done.record(A)
            returned=mode=='return' and ee.query();target=ordinaryA if returned else A
            expected['v1']=target.cuda_stream;job[0]=name+'_enc9_17'
            path_begin=time.monotonic_ns()
            with torch.cuda.stream(target):
                target.wait_event(retained_done);target.wait_event(b1)
                rec['B2_submit_begin_ns']=time.monotonic_ns();a2.record(target)
                for i in range(9,18):p1._encoder_layer(i,561,False,target.cuda_stream)
                b2.record(target);rec['B2_submit_return_ns']=time.monotonic_ns()
            rec.update(returned=returned,B2_stream=target.cuda_stream,path_setup_Host_ns=rec['B2_submit_begin_ns']-path_begin)
            lower=time.monotonic_ns()
            while not ee.query():lower=time.monotonic_ns();time.sleep(.0001)
            rec['Expert_complete_lower_ns']=lower;rec['Expert_complete_upper_ns']=time.monotonic_ns()
            rec['B2_done_at_Expert_observation']=b2.query();b2.synchronize();rec['Context_complete_ack_ns']=time.monotonic_ns()
            rec.update(Expert_event_ms=es.elapsed_time(ee),Encoder_B1_event_ms=a1.elapsed_time(b1),Encoder_B2_event_ms=a2.elapsed_time(b2),Expert_done_GPU_event_since_anchor_ms=anchor.elapsed_time(ee),Context_done_GPU_event_since_anchor_ms=anchor.elapsed_time(b2),window_Host_ms=(rec['Context_complete_ack_ns']-release)/1e6,full_refresh_prefix_to_ready_Host_ms=(rec['Context_complete_ack_ns']-prefix_rec['host_begin_ns'])/1e6,event_overlap_is_not_kernel_overlap=True,cuda_last_error=owner._cudart.cudaGetLastError())
            save()
            if rec['cuda_last_error']:raise RuntimeError('pair CUDA '+str(rec['cuda_last_error']))
            expected.update(v0=0,v1=0);torch.cuda.synchronize()
            # Save all live outputs before any failing assertion.
            boundary=tuple(store(name+'_boundary_'+k,retained[k].view(torch.uint8).cpu().numpy()) for k in ('x','K','V'))
            final=snap(p1,name+'_final');old=snap(p0,name+'_old');raw,act=action(p0,name+'_Expert')
            protect=all(a.tobytes()==b.tobytes() and a.shape==b.shape for a,b in zip(old,ref0))
            r['old_v0_protected']=protect;save()
            require(protect,name+'_old_v0_protected')
            passed=all(a.tobytes()==b.tobytes() and a.shape==b.shape for a,b in zip(boundary,mid[0])) and all(a.tobytes()==b.tobytes() and a.shape==b.shape for a,b in zip(final,ref1)) and raw.tobytes()==raw0.tobytes() and act.tobytes()==act0.tobytes()
            if not passed:r['failure_kind']='PAIR_NUMERICAL_ONLY';r['cuda_clean']=True;save()
            for k,a,b in zip(('x','K','V'),boundary,mid[0]):compare(name+'_boundary_'+k,a,b)
            for k,a,b in zip(('x','K','V'),final,ref1):compare(name+'_final_'+k,a,b)
            compare(name+'_Expert_raw',raw,raw0);compare(name+'_Expert_actions',act,act0,False)
            require(report['ledger'][name+'_enc0_8']['v1']['encoder']+report['ledger'][name+'_enc9_17']['v1']['encoder']==list(range(18)),name+'_18layers_once')
            require(report['ledger'][name+'_Expert']['v0']['decoder']==env['expected_dec'],name+'_10steps')
            rec['status']='PASS';save()
        sample('ordinary','gate',0)
        for j,mode in enumerate(env['cfg']['pair']['formal_order']):sample(mode,'formal',j//4)
        r['status']='PASS_COVERED_NUMERICS_ROUTE_AND_EVENTS_ONLY';report['status']='PASS';save()
    finally:
        # A fault during GPU synchronization/cleanup must propagate globally.
        torch.cuda.synchronize()
        for p,g,f,fa in original:p.gemm=g;p.fvk=f;p.attn._fa2_fwd=fa
        expected.update(v0=0,v1=0)
        r['addresses_after']=address_manifest(owner,p0,p1,attn1,runner1,validate=False)
        before=r.get('addresses_before',{})
        require(not r['addresses_after']['overlaps'],'pair_final_resource_intervals_disjoint')
        if before:require({v['name']:(v['ptr'],v['nbytes']) for v in before['writable']}=={v['name']:(v['ptr'],v['nbytes']) for v in r['addresses_after']['writable']},'pair_visible_addresses_stable')
        if rt is not None:rt.close()
        r['cleanup']='PASS_synchronized_resources_released';save()
