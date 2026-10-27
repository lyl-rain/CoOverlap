"""PREPARED M2 v2 single-stream Eager validation; never imports torch on dry-run.

v2 differs from v1 in exactly two, math-neutral ways, both forced by gpu_run_03:
 S1  a bounded DVFS ramp (discarded complete Contextes on slot1, results never used)
     runs BEFORE any autotune, and the GPU frequency must read at maximum; the
     2026-10-20 probe showed a 306 MHz autotune flips the Vision patch-embedding
     candidate and changes every downstream byte.
 S2  the S0/S1 Context x/K/V must equal the frozen historical SHA256 byte for byte
     BEFORE the Expert10 work is spent (v4/v7 required the same). Tolerances are
     unchanged and still apply to the output only.

Only a new, explicit authorization permits --approved-m2-common-v2.
No clock/power write, root, quota, graph, profiler, dependency install or concurrency.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import time
import traceback
from m2_executor import VersionedKV, Snapshot, BLOCKS, DECODER, replay_manifest, replay_stats


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(8*1024*1024),b''):h.update(data)
    return h.hexdigest()


def protocol():
    return dict(id='m2_common_v2', status='PREPARED', manifest=replay_manifest(),
                changes_from_v1=['bounded DVFS ramp before autotune; GPU max frequency required',
                                 'S0/S1 Context x/K/V must equal frozen historical SHA256'],
                warmup_work=dict(Contexts_max=8, note='complete Contextes on slot1, discarded, never references'),
                numeric_precondition='S0 and S1 Context x/K/V byte exact vs frozen historical SHA256',
                modes=['serial_adjacent', 'serial_resumed'], model_process_limit=1,
                model_timeout_s=180, kill_grace_s=10, retry_limit=0,
                measured_work=dict(Contexts=8,Experts=16),
                preparation_work=dict(Contexts=6,Experts=3,autotune='two original runners, internal work separate'),
                total_explicit_work=dict(Contexts=14,Experts=19,encoder_layers=252,decoder_layers=3420),
                resources='one shared checkpoint; two private slots; stream0; free CUDA >12GiB',
                route=None, performance_claim=False)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--preflight',action='store_true')
    ap.add_argument('--approved-m2-common-v2',action='store_true')
    ap.add_argument('--out',type=Path)
    ap.add_argument('--reference',type=Path)
    ap.add_argument('--source-preflight',type=Path)
    args=ap.parse_args()
    if args.dry_run:
        print(json.dumps(protocol(),indent=2));return
    if args.reference is None:ap.error('--reference required')
    if args.preflight:
        # CPU/IO only, on-board and separately bounded by the invoking timeout.
        source=json.loads((args.reference/'SOURCE_CHECKPOINT_SHA256.json').read_text())
        if len(source)!=967:raise RuntimeError('frozen source/checkpoint lock changed')
        if args.source_preflight is None:ap.error('--source-preflight output required')
        records=[]
        for path,wanted in source.items():
            before=Path(path).stat()
            if sha(path)!=wanted:raise RuntimeError('source/checkpoint changed: '+path)
            after=Path(path).stat()
            keys=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
            if any(getattr(before,k)!=getattr(after,k) for k in keys):raise RuntimeError('file changed while hashing')
            records.append(dict(path=path,sha256=wanted,stat={k:getattr(after,k) for k in keys}))
        credential=dict(status='CPU_PREFLIGHT_PASS',files=records,host=socket.gethostname(),uid=os.geteuid(),created_ns=time.time_ns())
        with args.source_preflight.open('x') as out:json.dump(credential,out,indent=2)
        print(json.dumps(dict(status='CPU_PREFLIGHT_PASS',files=len(source),gpu_processes=0)));return
    if not args.approved_m2_common_v2:ap.error('new explicit M2 v2 authorization required before GPU imports')
    if args.out is None:ap.error('--out required')
    if args.source_preflight is None:ap.error('--source-preflight required')
    credential=json.loads(args.source_preflight.read_text())
    if credential['host']!=socket.gethostname() or credential['uid']!=os.geteuid() or not 0<=time.time_ns()-credential['created_ns']<=3600*10**9:
        raise RuntimeError('preflight host/user/age changed')
    if len(credential['files'])!=967:raise RuntimeError('source/checkpoint preflight incomplete')
    for row in credential['files']:
        current=Path(row['path']).stat()
        if any(getattr(current,k)!=v for k,v in row['stat'].items()):raise RuntimeError('preflight invalidated: '+row['path'])
    if os.geteuid()==0:raise RuntimeError('ordinary user only')
    # No inherited profiler/injection or M1 launch service.
    for key,value in os.environ.items():
        if value and (key.startswith(('NSYS_','KINETO_','TORCH_PROFILER_','CUPTI_INJECTION','CUDA_INJECTION')) or key=='LD_PRELOAD'):
            raise RuntimeError('unexpected instrumentation: '+key)
    args.out.mkdir(parents=True,exist_ok=False)
    report=dict(status='INCOMPLETE',protocol=protocol(),source_preflight_sha256=sha(args.source_preflight),checks=[],operations=[],modes=[])
    def save():
        tmp=args.out/'result.tmp';tmp.write_text(json.dumps(report,indent=2));tmp.replace(args.out/'result.json')
    def require(ok,name):
        report['checks'].append(dict(name=name,pass_=bool(ok)))
        if not ok:save();raise AssertionError(name)
    start=time.monotonic();last_telemetry=[-1.0]
    def telemetry():
        row=dict(host_ns=time.monotonic_ns(),nodes={})
        paths=[Path('/sys/devices/virtual/thermal/thermal_zone0/temp')]
        paths += [Path('/sys/devices/system/cpu/cpufreq')/('policy'+str(i))/key for i in (0,4,8) for key in ('scaling_cur_freq','scaling_min_freq','scaling_max_freq')]
        paths += [Path('/sys/class/devfreq')/dev/key for dev in ('17000000.gpu','bwmgr') for key in ('cur_freq','min_freq','max_freq')]
        for path in paths:
            try:row['nodes'][str(path)]=path.read_text().strip()
            except OSError:row['nodes'][str(path)]='UNKNOWN'
        report.setdefault('read_only_telemetry',[]).append(row)
    def bound():
        if time.monotonic()-start>170:raise TimeoutError('170s internal stop; no new work')
        if time.monotonic()-last_telemetry[0]>=1.0:telemetry();last_telemetry[0]=time.monotonic()
        if int(Path('/sys/devices/virtual/thermal/thermal_zone0/temp').read_text())>=80000:raise RuntimeError('thermal stop >=80C')
    def term(signum,frame):raise TimeoutError('termination requested; no new work')
    signal.signal(signal.SIGTERM,term)
    try:
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
        require(next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))>=32*1024**2,'available_system_memory_32GiB')
        disk=os.statvfs(args.out);require(disk.f_bavail*disk.f_frsize>=2*1024**3,'disk_space_2GiB')
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
        for _ in range(8):
            bound();stage(ps[1],True);context(ps[1]);stream.synchronize()
            warm.append(int(Path('/sys/class/devfreq/17000000.gpu/cur_freq').read_text()))
            if len(warm)>=2 and warm[-1]==warm[-2]==gpu_max:break
        report['autotune_warmup']=dict(iterations=len(warm),gpu_cur_freq=warm,gpu_max_freq=gpu_max,
            note='complete Contextes on slot1; results discarded and never compared or timed')
        require(warm[-1]>=gpu_max*9//10,'gpu_frequency_at_max_before_autotune')
        for p in ps:
            require(getattr(p,'_gemms_autotuned',False) is False,'autotune_not_already_done')
            p.autotune_gemms();stream.synchronize();bound()
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
            # S2: prove the numerical path before spending Expert10 work.
            frozen=json.loads((args.reference/'MANIFEST.json').read_text())['tensor_metadata']
            for key,data in zip(('x','K','V'),ctx):
                want=frozen['reference_S'+str(i)+'_'+key]['sha256']
                report.setdefault('context_precondition',[]).append(
                    dict(snapshot='S'+str(i),tensor=key,sha256=digest(data),frozen=want,exact=digest(data)==want))
                require(digest(data)==want,'S'+str(i)+'_context_'+key+'_byte_exact')
            ledger.execute('reference_expert'+str(i),i,'Expert',lambda:p.transformer_decoder(0));stream.synchronize()
            raw,act=outputs(p,'ref'+str(i));refs.append((ctx,raw,act));midrefs.append(mid[0])
            for suffix,data,kind,shape in [('raw_bf16',raw,'bf16',[50,32]),('actions',act,'f32',[50,7])]:
                fn='reference_S'+str(i)+'_'+suffix+'.bin';olddata=(args.reference/fn).read_bytes()
                require(digest(olddata)==meta['files'][fn]['sha256'],'historical_reference_sha')
                metrics=evaluate(data,olddata,kind,shape,shape);report.setdefault('cross_process',[]).append(dict(name=fn,**metrics));require(metrics['pass_'],'independent_output_gate')
        def run_model(key,slot,kind,fn):
            bound();begin=time.monotonic_ns();ev0=torch.cuda.Event(enable_timing=True);ev=torch.cuda.Event(enable_timing=True);ev0.record(stream)
            work=ledger.execute(key,slot,kind,fn)
            record_begin=time.monotonic_ns();ev.record(stream);lo=record_begin
            while True:
                bound();a=time.monotonic_ns();done=ev.query();b=time.monotonic_ns()
                if done:break
                lo=a;time.sleep(.0001)
            row=dict(key=key,slot=slot,kind=kind,cpu_begin_ns=begin,event_record_begin_ns=record_begin,lower_ns=lo,upper_ns=b,event_ms=ev0.elapsed_time(ev),event_complete=True)
            report['operations'].append(row);return work,ev,(lo,b)
        def blocks(m,h,which,key):
            v=m.get(h);p=ps[h.slot]
            m.check_block(h,which,v.snapshot,BLOCKS[which])
            oldctx=snap(ps[1-h.slot],key+'_other_before',persist=False)
            work,ev,times=run_model(key,h.slot,'B1' if which==0 else 'B2',lambda:block1(p,ENC_D,VIS_D) if which==0 else block2(p))
            m.submit_block(h,which,v.snapshot,work,ev);require(m.poll_block(h),'block_event_done')
            got=snap(p,key,9 if which==0 else 18)
            equal_snap(key+'_same_process_context',got,midrefs[h.slot] if which==0 else refs[h.slot][0])
            equal_snap(key+'_other_slot',snap(ps[1-h.slot],key+'_other_after',persist=False),oldctx)
            return times
        def bootstrap(m,key):
            h=m.begin(0,snaps[0]);stage(ps[0],True)
            # Original complete Context counts as one Context; split event registration is bookkeeping only.
            _,ev,_=run_model(key,0,'Context',lambda:context(ps[0]))
            for b in (0,1):m.submit_block(h,b,snaps[0],BLOCKS[b],ev);m.poll_block(h)
            require(snap(ps[0],key+'_final')==refs[0][0],key+'_exact');m.publish(h);return h
        def expert(m,job,h):
            m.check_expert(job,h)
            p=ps[h.slot];stage(p);before=snap(p,job+'_prefix_before',persist=False)
            calls,ev,times=run_model(job,h.slot,'Expert',lambda:p.transformer_decoder(0))
            m.submit_expert(job,h,calls,ev);require(m.poll_expert(job),'reader_event_done')
            require(outputs(p,job)==refs[h.slot][1:],job+'_same_version_output_exact')
            equal_snap(job+'_KV_read_only',snap(p,job+'_prefix_after',persist=False),before);return times
        # One prebound old reader crosses actual new publication; no GPU overlap.
        m=VersionedKV();old=bootstrap(m,'gate_bootstrap');m.bind('gate_old_reader',noise_sha)
        new=m.begin(1,snaps[1]);stage(ps[1],True);blocks(m,new,0,'gate_B1');blocks(m,new,1,'gate_B2');m.publish(new)
        require(m.bind('gate_latest_binding',noise_sha)==new,'latest_published_binding');m.cancel_unsubmitted('gate_latest_binding')
        try:m.reclaim(old)
        except RuntimeError:report['checks'].append(dict(name='old_bound_reader_blocks_reuse',pass_=True))
        else:raise AssertionError('old slot freed too soon')
        expert(m,'gate_old_reader',old);m.reclaim(old);report['gate_journal']=m.journal
        # Same finite workload, snapshots, version trajectory, budget and callbacks.
        from m2_replay_driver import replay
        def wait_release(rel):
            while time.monotonic_ns()<rel:bound();time.sleep(.0001)
        for mode in protocol()['modes']:
            m=VersionedKV()
            rec=dict(mode=mode,status='INCOMPLETE');report['modes'].append(rec)
            rec.update(replay(m,snaps,mode,bootstrap,lambda slot:stage(ps[slot],True),blocks,expert,wait_release,time.monotonic_ns,record=rec))
            save()
        final=address_manifest(owner,p0,p1,attn1,runner1)
        (args.out/'address_after.json').write_text(json.dumps(final,indent=2));require(final==manifest,'visible_addresses_stable')
        require(owner._cudart.cudaGetLastError()==0,'cuda_last_error')
        # 14 explicit Contexts/19 Experts; Autotune was performed before ledger attachment.
        require(sum(r[2]=='encoder' for r in ledger.calls)==252,'all_252_encoder_calls')
        require(sum(r[2]=='decoder' for r in ledger.calls)==3420,'all_3420_decoder_calls')
        require(sum(r[2]=='vision27' for r in ledger.calls)==14,'all_14_vision_prefixes')
        report['call_ledger']=ledger.calls;report['status']='PASS';report['elapsed_s']=time.monotonic()-start;save()
    except BaseException:
        report['status']='FAIL_OR_INCOMPLETE';report['error']=traceback.format_exc()
        if 'ledger' in locals():report['call_ledger']=ledger.calls
        if 'm' in locals():report['last_version_journal']=m.journal
        save();raise


if __name__=='__main__':main()
