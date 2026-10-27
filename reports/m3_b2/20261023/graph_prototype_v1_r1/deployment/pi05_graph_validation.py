"""One symmetric Graph batch; all CUDA work requires NEW explicit approval."""
import argparse,hashlib,json,os,signal,time,traceback
from pathlib import Path
from graph_plan import RUN,PROTOCOL,budget,protocol
from m3_m2_preparation import prepare,preparation_audit


def jsonable(v):
    if isinstance(v,dict):return {str(k):jsonable(x) for k,x in v.items()}
    if isinstance(v,(tuple,list)):return [jsonable(x) for x in v]
    return v


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--verification-mode',choices=['performance'],default='performance')
    ap.add_argument('--approved-m3-symmetric-graph-v1-r1',action='store_true')
    for k in ('config','out','reference','source-preflight'):ap.add_argument('--'+k,type=Path)
    a=ap.parse_args(argv)
    if a.config and json.loads(a.config.read_text())!=protocol():raise ValueError('configuration changed')
    preparation_audit()
    if a.dry_run:print(json.dumps(protocol(),indent=2));return
    if not a.approved_m3_symmetric_graph_v1_r1 or os.environ.get('COOVERLAP_APPROVED_BATCH')!=PROTOCOL:
        ap.error('new Graph/model/hardware approval required before CUDA imports')
    if None in (a.config,a.out,a.reference,a.source_preflight):ap.error('all paths required')
    if os.geteuid()==0:raise PermissionError('ordinary nvidia model only')
    from graph_control import verify_credential,sha
    cred=verify_credential(a.config.parent,a.source_preflight.parent,sha(a.source_preflight))
    for k,v in os.environ.items():
        if v and (k.startswith(('NSYS_','KINETO_','TORCH_PROFILER_','CUPTI_INJECTION','CUDA_INJECTION')) or k=='LD_PRELOAD'):
            raise RuntimeError('unexpected injection '+k)
    a.out.mkdir(exist_ok=False)
    report=dict(status='INCOMPLETE',protocol=protocol(),config_sha256=sha(a.config),checks=[],
                segments=[dict(**c,status='NOT_STARTED',planned_Experts=8,planned_Context=4) for c in RUN],
                source_preflight_sha256=sha(a.source_preflight),source_package=cred['package'],
                gates={},graph_GPU_status='NOT_RUN',interpretation='one same-process sequential batch; no reliable tail/k_min/novelty claim')
    start=time.monotonic();deadline=time.monotonic_ns()+170_000_000_000
    def save():
        p=a.out/'result.tmp';p.write_text(json.dumps(jsonable(report),indent=2));p.replace(a.out/'result.json')
    def require(ok,name):
        report['checks'].append(dict(name=name,pass_=bool(ok)))
        if not ok:save();raise AssertionError(name)
    def bound():
        if time.monotonic_ns()>=deadline:raise TimeoutError('170 s deadline, no retry')
        if int(Path('/sys/devices/virtual/thermal/thermal_zone0/temp').read_text())>=80000:raise RuntimeError('thermal stop')
    def stopped(*_):raise TimeoutError('termination, preserve partial work')
    signal.signal(signal.SIGTERM,stopped)
    device=None;active={}
    try:
        e=prepare(a,report,save,require,bound) # exact passed AST through D1
        torch,np,ps,owner,ledger=e['torch'],e['np'],e['ps'],e['owner'],e['ledger']
        from m2_executor import DEFAULT_PLAN,VersionedKV
        from m2_pi05_ops import context,block1,block2
        from graph_backend import GraphDevice,GraphRegistry
        from graph_orchestrate import run_segments,version_gate
        # One explicit execution stream for both engines. Passed default-stream
        # preparation is fully drained before any new work is submitted.
        torch.cuda.default_stream().synchronize()
        stream=torch.cuda.Stream();si=stream.cuda_stream
        require(si!=0,'explicit_capture_and_execution_stream')
        ledger.stream_id=si
        expected=dict(images=e['images'].view(torch.uint8).cpu().numpy().tobytes(),noise=e['f']['noise0_bf16_bytes'].tobytes())
        for i in (0,1):
            expected['ref'+str(i)]=b''.join(e['refs'][i][0]);expected['mid'+str(i)]=b''.join(e['midrefs'][i]);expected['raw'+str(i)]=e['refs'][i][1]
        original=e['address_manifest'](owner,ps[0],ps[1],e['attn1'],e['runner1'])
        def addresses(slot):
            manifest=e['address_manifest'](owner,ps[0],ps[1],e['attn1'],e['runner1'])
            # Physical addresses/sizes, never Python object ids. Query cost is
            # symmetric and included in both timed engines.
            return tuple(sorted((x['name'],x['ptr'],x['nbytes'],tuple(x.get('shape',[])),tuple(x.get('stride',[])),x.get('dtype'))
                                for key in ('writable','shared_readonly','host_resources') for x in manifest[key]))
        math_for=dict(B1=lambda p:block1(p,e['ENC_D'],e['VIS_D'],stream=si),B2=lambda p:block2(p,stream=si))
        def bootstrap(m,snaps,key):
            h=m.begin(0,snaps[0]);device.restore(0,True)
            with torch.cuda.stream(stream):
                ledger.execute(device.label()+'/bootstrap',0,'Context',lambda:context(ps[0],stream=si))
            ev=torch.cuda.Event();ev.record(stream);ev.synchronize()
            for b in range(2):m.submit_block(h,b,snaps[0],m.plan.blocks[b],ev);require(m.poll_block(h),'bootstrap_block_done')
            require(e['snap'](ps[0],device.label()+'_bootstrap')==e['refs'][0][0],'bootstrap_exact')
            m.publish(h)
        def ready(phase,d,initial):
            require(e['address_manifest'](owner,ps[0],ps[1],e['attn1'],e['runner1'])==original,'visible_resources_stable')
            require(torch.cuda.mem_get_info()[0]>12*1024**3,'free_memory_floor')
            for i in (0,1):require(e['snap'](ps[i],'initial_'+d.label()+'_S'+str(i))==e['refs'][i][0],'same_physical_context')
            save()
            for path in a.out.rglob('*'):
                if path.is_file():
                    with path.open('rb') as saved:os.fsync(saved.fileno())
            stream.synchronize();bound()
        bb=budget()['bank_bytes']
        require(torch.cuda.mem_get_info()[0]>12*1024**3+2*bb,'bank_admission')
        device=GraphDevice(torch,np,owner,ps,ledger,expected,[r[2] for r in e['refs']],owner.norm_stats,
                           (lambda p:context(p,stream=si),math_for['B1'],math_for['B2']),bootstrap,ready,
                           a.out,deadline,capacity=bb,plan=DEFAULT_PLAN,block_math=math_for,max_blocks=2,
                           execution_stream=stream)
        device.images=e['images'];device.noise=e['noise']
        require(device.images.is_contiguous() and device.noise.is_contiguous(),'fixed_inputs_contiguous')
        require(not any(x['ptr'] and x['nbytes'] and max(device.gptr,x['ptr'])<min(device.gptr+bb,x['ptr']+x['nbytes']) for k in ('writable','shared_readonly') for x in original[k]),'bank_no_model_alias')
        registry=GraphRegistry(torch.cuda,stream,ledger,addresses,bound,clock=device.clock);device.configure_graph(registry)
        report['capture']={'status':'INCOMPLETE','units':[],'stream':si,'pool_bytes':'UNKNOWN'}
        capture_free_before=torch.cuda.mem_get_info()[0]
        # Per slot: capture B1, execute eager B1, capture B2, execute eager B2,
        # capture Expert10, execute eager Expert10. Exactly 2C/2E GPU forwards;
        # capture host call sequences are distinct ledger keys, no extra warmup.
        for slot,p in enumerate(ps):
            device.restore(slot,True);stream.synchronize()
            for kind in ('B1','B2','Expert'):
                fn,work,expected_calls=device.math_operation(slot,kind)
                work=__import__('m2_executor').DECODER if kind=='Expert' else work
                registry.capture_unit(slot,kind,fn,work,expected_calls)
                require(capture_free_before-torch.cuda.mem_get_info()[0]<=budget()['graph_extra_memory_cap_bytes'],'graph_extra_allocation_cap_2GiB')
                with torch.cuda.stream(stream):
                    ledger.execute('stream_gate/S%d/%s'%(slot,kind),slot,kind,fn,expected=expected_calls,work=work)
                stream.synchronize();bound()
                if kind=='B1':require(e['snap'](p,'stream_gate_S%d_mid'%slot,9)==e['midrefs'][slot],'stream_eager_mid_exact')
                elif kind=='B2':require(e['snap'](p,'stream_gate_S%d_full'%slot)==e['refs'][slot][0],'stream_eager_full_exact')
                else:
                    raw=e['read'](p.input_noise_buf.ptr.value,3200)
                    require(raw==e['refs'][slot][1],'stream_eager_raw_exact')
                require(torch.cuda.mem_get_info()[0]>12*1024**3,'capture_memory_floor')
        report['capture'].update(status='CAPTURED_NOT_YET_VALIDATED',units=registry.manifests(),
                                  reserved_bytes=torch.cuda.memory_reserved(),allocated_bytes=torch.cuda.memory_allocated())
        report['graph_numerical_gates']=[]
        # Replay each complete slot path with real ownership and fresh Events.
        for slot,p in enumerate(ps):
            m=VersionedKV(DEFAULT_PLAN);h=m.begin(slot,e['snaps'][slot]);device.restore(slot,True);stream.synchronize()
            registry.begin_segment('graph_numerical_gate_S%d'%slot,'graph')
            for b in (0,1):
                kind='B%d'%(b+1);key='R0/'+kind
                fn,_,_=device.math_operation(slot,kind)
                event=torch.cuda.Event()
                calls=registry.execute(m,h,key,kind,fn,event)
                event.record(stream);event.synchronize()
                m.submit_block(h,b,e['snaps'][slot],DEFAULT_PLAN.blocks[b],event);require(m.poll_block(h),'graph_gate_block_event')
                registry.confirm(key,event)
                require(e['snap'](p,'graph_gate_S%d_%s'%(slot,kind),9 if b==0 else 18)==(e['midrefs'][slot] if b==0 else e['refs'][slot][0]),'graph_boundary_byte_exact')
            m.publish(h);m.bind('E0',e['noise_sha'],version=h.version)
            device.restore(slot,False);fn,_,_=device.math_operation(slot,'Expert')
            event=torch.cuda.Event()
            calls=registry.execute(m,h,'E0','Expert',fn,event)
            event.record(stream);event.synchronize()
            m.submit_expert('E0',h,calls,event);require(m.poll_expert('E0'),'graph_gate_Expert_event');registry.confirm('E0',event)
            raw=e['read'](p.input_noise_buf.ptr.value,3200)
            require(raw==e['refs'][slot][1],'graph_raw_byte_exact')
            from flash_rt.core.utils.actions import unnormalize_actions
            vals=torch.from_numpy(np.frombuffer(raw,dtype=np.uint8).copy()).view(torch.bfloat16).float().reshape(50,32).numpy()
            actions=np.ascontiguousarray(unnormalize_actions(vals,owner.norm_stats)[:,:7],dtype=np.float32).tobytes()
            require(actions==e['refs'][slot][2],'graph_actions_byte_exact')
            report['graph_numerical_gates'].append(dict(slot=slot,status='PASS',
                raw_sha256=hashlib.sha256(raw).hexdigest(),actions_sha256=hashlib.sha256(actions).hexdigest(),
                journal=list(m.journal),replays=list(registry.rows.values())))
        report['capture']['status']='PASS_BYTE_EXACT_SAME_PROCESS'
        report['graph_GPU_status']='CORRECTNESS_GATES_PASSED'
        for interleave in (False,True):
            key='interrupt' if interleave else 'old_reader';record={};report['gates'][key]=record
            version_gate(device,e['snaps'],interleave,record,require,active);save()
        report['segment_summary']=run_segments(device,e['snaps'],report['segments'],a.out,time.monotonic_ns,require,active)
        from collections import Counter
        observed=dict(Counter(x[2] for x in ledger.calls))
        target=budget()['observed_python_calls']
        require(observed=={k:target[k] for k in ('language','vision27','encoder','decoder')},'complete_observed_Python_work')
        require(len(ledger.calls)==target['rows'],'complete_observed_Python_rows')
        report['call_ledger']=ledger.calls
        # Calls observed during capture != GPU forwards; Graph window work is
        # mapped from validated capture manifests, never forged CallLedger rows.
        report['work_accounting']=dict(budget=budget(),capture_host_calls=[r for r in ledger.calls if str(r[0]).startswith('capture/')],
                                       runtime_evidence=[r['work_evidence'] for r in report['segments']])
        report['status']='PASS_IN_PROCESS_SYMMETRIC_GRAPH';report['elapsed_s']=time.monotonic()-start;save()
    except BaseException:
        report.update(status='FAIL_OR_INCOMPLETE',error=traceback.format_exc(),elapsed_s=time.monotonic()-start)
        from m3_b3_orchestrate import describe_active,export_failed_retention
        report['failed_phase']=describe_active(active)
        if 'registry' in locals():report['partial_capture_manifests']=registry.manifests()
        report['partial_retention']=export_failed_retention(device,active,a.out,deadline,time.monotonic_ns)
        if device is not None:report['call_ledger']=device.ledger.calls
        save();raise


if __name__=='__main__':main()
