"""PREPARED ONLY: one newly approved ordinary-user M3 profiling process."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback
from m2_executor import VersionedKV, BLOCKS
from m2_clean_core import retention_layout, gate_retention_layout
from m2_clean_stats import augment, write_tables
from m3_b2_core import PROTOCOL, ORDER, CYCLES, protocol, run_segment
from m3_m2_preparation import prepare, preparation_audit


def jsonable(v):
    if isinstance(v,dict):return {str(k):jsonable(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [jsonable(x) for x in v]
    return v


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--approved-m3-b2-profile-v1',action='store_true')
    ap.add_argument('--verification-mode',choices=['performance','correctness'],default='performance')
    for k in ('config','out','reference','source-preflight'):ap.add_argument('--'+k,type=Path)
    args=ap.parse_args()
    if args.config and json.loads(args.config.read_text())!=protocol():raise ValueError('frozen M3 configuration changed')
    _,_,audit=preparation_audit()
    if args.dry_run:
        print(json.dumps(dict(protocol=protocol(),preparation_reuse=audit),indent=2));return
    if not args.approved_m3_b2_profile_v1 or os.environ.get('COOVERLAP_APPROVED_BATCH')!=PROTOCOL:
        ap.error('NEW M3 approval required before GPU imports; old M2 authorization is invalid')
    if None in (args.config,args.out,args.reference,args.source_preflight):ap.error('all paths required')
    if os.geteuid()==0:raise PermissionError('model must be ordinary nvidia')
    from m3_b2_control import verify_credential, sha
    credential=verify_credential(args.config.parent,args.source_preflight.parent,sha(args.source_preflight))
    for k,v in os.environ.items():
        if v and (k.startswith(('NSYS_','KINETO_','TORCH_PROFILER_','CUPTI_INJECTION','CUDA_INJECTION')) or k=='LD_PRELOAD'):
            raise RuntimeError('unexpected injection '+k)
    args.out.mkdir(exist_ok=False)
    report=dict(status='INCOMPLETE',protocol=protocol(),
        segments=[dict(index=i,mode=p,status='NOT_STARTED',planned_Experts=CYCLES,planned_Context=CYCLES//2) for i,p in enumerate(ORDER)],checks=[],
        source_config_fingerprints={k:v['sha256'] for k,v in credential['package'].items()},
        config_sha256=sha(args.config),source_preflight_sha256=sha(args.source_preflight),
        preparation_reuse=audit,observation_mode=args.verification_mode,
        interpretation='sequential diagnostic profiling with symmetric fine Events and D2D; no net benefit/tail/k_min claim')
    start=time.monotonic();deadline=time.monotonic_ns()+170_000_000_000
    def save():
        tmp=args.out/'result.tmp';tmp.write_text(json.dumps(jsonable(report),indent=2));tmp.replace(args.out/'result.json')
    def require(ok,name):
        report['checks'].append(dict(name=name,pass_=bool(ok)))
        if not ok:save();raise AssertionError(name)
    def bound():
        if time.monotonic_ns()>=deadline:raise TimeoutError('170s internal cutoff; zero retry')
        if int(Path('/sys/devices/virtual/thermal/thermal_zone0/temp').read_text())>=80000:raise RuntimeError('thermal >=80C')
    def term(*_):raise TimeoutError('signal; preserve partial work without retry')
    signal.signal(signal.SIGTERM,term)
    device=backend=hooks=None
    try:
        e=prepare(args,report,save,require,bound)
        torch,np,owner,ps,ledger=e['torch'],e['np'],e['owner'],e['ps'],e['ledger']
        p0,p1=ps;refs,midrefs,snaps=e['refs'],e['midrefs'],e['snaps']
        context,block1,block2=e['context'],e['block1'],e['block2']
        stage,snap,read=e['stage'],e['snap'],e['read']
        address_manifest=e['address_manifest'];stream=e['stream'];noise_sha=e['noise_sha']
        original=address_manifest(owner,p0,p1,e['attn1'],e['runner1'])
        expected=dict(images=e['images'].view(torch.uint8).cpu().numpy().tobytes(),noise=e['f']['noise0_bf16_bytes'].tobytes())
        for i in (0,1):
            expected['ref'+str(i)]=b''.join(refs[i][0]);expected['mid'+str(i)]=b''.join(midrefs[i])
            expected['raw'+str(i)]=refs[i][1]
            for data in (*refs[i][0],*midrefs[i]):
                vals=(np.frombuffer(data,dtype='<u2').astype('<u4')<<16).view('<f4')
                require(np.isfinite(vals).all(),'finite_same_process_reference')
        bank_bytes=retention_layout(CYCLES)['nbytes']
        require(torch.cuda.mem_get_info()[0]>12*1024**3+2*bank_bytes,'GPU_and_pinned_retention_budget')
        embeddings=[read(p._lang_embeds_buf.ptr.value,p._lang_embeds_buf.nbytes) for p in ps]
        def bootstrap(m,snapshots,key):
            h=m.begin(0,snapshots[0]);stage(p0,True)
            ledger.execute(device.namespace+str(device.epoch)+'/bootstrap',0,'Context',lambda:context(p0))
            ev=torch.cuda.Event();ev.record(stream);ev.synchronize()
            for b in (0,1):m.submit_block(h,b,snapshots[0],BLOCKS[b],ev);require(m.poll_block(h),'bootstrap_complete')
            require(snap(p0,device.namespace+str(device.epoch)+'_bootstrap')==refs[0][0],'bootstrap_exact')
            m.publish(h)
        initial=[]
        def ready(phase,d,logical):
            require(address_manifest(owner,p0,p1,e['attn1'],e['runner1'])==original,'visible_resources_stable')
            require(torch.cuda.mem_get_info()[0]>12*1024**3,'memory_floor')
            for i,p in enumerate(ps):
                require(snap(p,'initial_'+d.namespace+str(d.epoch)+'_S'+str(i))==refs[i][0],'same_physical_initial_context')
                require(read(p._lang_embeds_buf.ptr.value,p._lang_embeds_buf.nbytes)==embeddings[i],'language_unchanged')
            if d.namespace=='segment':
                if initial:require(logical==initial[0],'identical_initial_logical_state')
                initial.append(logical)
            d.record['initial_state']=logical;save()
            for path in args.out.rglob('*'):
                if path.is_file():
                    with path.open('rb') as f:os.fsync(f.fileno())
            for directory in [args.out,*[p for p in args.out.rglob('*') if p.is_dir()]]:
                fd=os.open(directory,os.O_RDONLY)
                try:os.fsync(fd)
                finally:os.close(fd)
            sys.stdout.flush();sys.stderr.flush();os.fsync(1);os.fsync(2)
            stream.synchronize();bound()
        from m3_b2_profile import ProfileHooks,ProfileDevice
        from m3_b2_backend import BoundaryBackend
        # Only post-D1 calls are instrumented. Same hooks for both policies.
        hooks=ProfileHooks(torch,ps,ledger,time.monotonic_ns,capacity=10)
        device=ProfileDevice(torch,np,owner,ps,ledger,expected,[r[2] for r in refs],owner.norm_stats,
            (context,lambda p:block1(p,e['ENC_D'],e['VIS_D']),block2),bootstrap,ready,args.out,deadline,capacity=bank_bytes)
        device.hooks=hooks;device.images=e['images'];device.noise=e['noise']
        intervals=original['writable']+original['shared_readonly']
        require(not any(x['ptr'] and x['nbytes'] and max(device.gptr,x['ptr'])<min(device.gptr+bank_bytes,x['ptr']+x['nbytes']) for x in intervals),'bank_no_model_alias')
        require(device.images.is_contiguous() and device.noise.is_contiguous(),'contiguous_fixed_inputs')
        report['retention_memory']=dict(GPU_B=bank_bytes,Host_pinned_B=bank_bytes,profile_events=410,operation_events=320)
        for interleave in (False,True):
            device.namespace='interrupt_gate' if interleave else 'gate'
            gate=dict(status='INCOMPLETE',role='manual interleaving correctness only; not an arrival-policy performance sample' if interleave else 'old-reader gate')
            report[device.namespace]=gate
            backend=BoundaryBackend(device,snaps,'correctness',layout=gate_retention_layout())
            m=VersionedKV();backend.prepare(m,None,gate);backend.bootstrap(m,'bootstrap');backend.ready(m)
            m.bind('E0',noise_sha);old=m.current;new=m.begin(1,snaps[1])
            if interleave:m.bind('hold',noise_sha)
            backend.enter_window()
            try:
                backend.stage(m,new,'R0');backend.block(m,new,0,'R0/B1')
                if interleave:backend.expert(m,'E0',old)
                backend.block(m,new,1,'R0/B2');m.publish(new)
                require(m.bind('latest',noise_sha)==new,'latest_published_binding');m.cancel_unsubmitted('latest')
                try:m.reclaim(old)
                except RuntimeError:require(True,'old_reader_prevents_reuse')
                else:raise AssertionError('old slot reclaimed with reader')
                if interleave:m.cancel_unsubmitted('hold')
                else:backend.expert(m,'E0',old)
                m.reclaim(old);backend.drain()
            finally:backend.leave_window();gate['journal']=m.journal
            backend.validate_and_persist();require(len(m.journal)==(20 if interleave else 18),'gate_exact_journal')
            save()
        device.namespace='segment'
        backend=BoundaryBackend(device,snaps,args.verification_mode,layout=retention_layout(CYCLES))
        for index,policy in enumerate(ORDER):
            bound();record=report['segments'][index]
            m=VersionedKV()
            try:run_segment(m,snaps,policy,backend,record,time.monotonic_ns)
            finally:
                if record.get('t0_ns') is not None:record['metrics']=augment(record)
            backend.validate_and_persist()
            require(address_manifest(owner,p0,p1,e['attn1'],e['runner1'])==original,'resources_stable_after_segment')
            write_tables(record,args.out/('segment'+str(index)));save()
        from collections import Counter
        counts=dict(Counter(x[2] for x in ledger.calls));report['observed_call_counts']=counts
        # 15C/13E less two unwrapped warm Contexts and one unwrapped D1 C/E.
        require(counts==dict(encoder=216,decoder=2160,language=12,vision27=12),'complete_observed_work_2400')
        require(len(ledger.calls)==2400,'observed_ledger_2400')
        require(len(hooks.records)==10,'all_post_D1_context_profiles')
        require(owner._cudart.cudaGetLastError()==0,'cuda_last_error')
        report['profiles']=hooks.export();report['call_ledger']=ledger.calls
        report['cross_process_gate']=dict(admission=False,within_historical_envelope=all(x['pass_'] for x in report['cross_process']))
        report['status']='PASS_IN_PROCESS_PROFILE_ONLY'
        report['elapsed_s']=time.monotonic()-start;save()
    except BaseException:
        report['status']='FAIL_OR_INCOMPLETE';report['error']=traceback.format_exc()
        if backend is not None:
            backend.leave_window();report['unfinished_retention']=backend.bank.metadata()
            # Best effort only when safe and inside the SAME finite allowance.
            # Unverified evidence never enables reuse or counts as completion.
            report['partial_retention_status']='UNAVAILABLE_UNSAFE_OR_NO_TIME'
            try:
                if device is not None and device.leased and time.monotonic_ns()+5_000_000_000<deadline and device.stream.query():
                    device.download(0,backend.layout['nbytes'])
                    with (args.out/'PARTIAL_UNVERIFIED_RETENTION.bin').open('xb') as f:
                        f.write(device.host_view[:backend.layout['nbytes']]);f.flush();os.fsync(f.fileno())
                    report['partial_retention_status']='EXPORTED_UNVERIFIED_NOT_REUSABLE'
            except BaseException:report['partial_retention_error']=traceback.format_exc()
        if hooks is not None:
            try:report['profiles_partial']=hooks.export(require_complete=False)
            except BaseException:report['profile_export_error']=traceback.format_exc()
        if 'ledger' in locals():report['call_ledger']=ledger.calls
        report['elapsed_s']=time.monotonic()-start;save();raise


if __name__=='__main__':main()
