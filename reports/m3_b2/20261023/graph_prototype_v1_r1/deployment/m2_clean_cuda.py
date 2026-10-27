"""Preallocated CUDA adapter. No Torch/CUDA import occurs at module import.

All numerical math is delegated to the frozen v3 m2_pi05_ops functions.
Native copies use GPU->GPU in windows, and pinned GPU->Host only afterwards.
"""
import ctypes as C
import hashlib
import json
import time
from pathlib import Path
from m2_clean_core import FULL,MID,X,KV_LAYER,IMAGES,NOISE,SIZES,retention_layout
from m2_executor import DECODER, DECODER_CALLS, DEFAULT_PLAN, expected_calls


class CudaDevice:
    def __init__(self,torch,np,owner,pipelines,ledger,expected,actions,norm,math_callbacks,
                 bootstrap_callback,save_callback,out,deadline,capacity=None,plan=None,
                 block_math=None,max_blocks=None,execution_stream=None):
        self.torch=torch;self.np=np;self.owner=owner;self.ps=pipelines;self.ledger=ledger
        self.expected=expected;self.actions=actions;self.norm=norm
        self.context,self.b1,self.b2=math_callbacks
        self.plan=DEFAULT_PLAN if plan is None else plan
        # Model callback per block kind; the same frozen math bodies, only the
        # legal cut between them differs by plan.
        self.block_math=dict(block_math or dict(B1=self.b1,B2=self.b2))
        self.max_blocks=int(max_blocks or len(self.plan))
        self.bootstrap_callback=bootstrap_callback;self.save_callback=save_callback
        self.out=Path(out);self.deadline=deadline;self.stream=torch.cuda.default_stream() if execution_stream is None else execution_stream
        self.clock=time.monotonic_ns;self.capacity=capacity or retention_layout()['nbytes']
        self.window=False;self.mode='performance';self.epoch=-1;self.operations={}
        self.namespace='segment';self.leased=False
        self.segment_id=None;self.segment_ids=set();self.audited_segments=set()
        self.runtime=owner._cudart
        self.runtime.cudaMemcpyAsync.argtypes=[C.c_void_p,C.c_void_p,C.c_size_t,C.c_int,C.c_void_p]
        self.runtime.cudaMemcpyAsync.restype=C.c_int
        self.runtime.cudaMemcpy2DAsync.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.c_size_t,C.c_size_t,C.c_int,C.c_void_p]
        self.runtime.cudaMemcpy2DAsync.restype=C.c_int
        # Two fixed buffers; no per-job Torch allocations, slices, contiguous()
        # calls or numerical tensor operations in a performance window.
        self.gpu=torch.empty(self.capacity,dtype=torch.uint8,device='cuda')
        self.host=torch.empty(self.capacity,dtype=torch.uint8,pin_memory=True)
        self.gptr=self.gpu.data_ptr();self.hptr=self.host.data_ptr()
        self.host_view=memoryview(self.host.numpy())
        self.sources=[]
        for p in pipelines:
            kv=[]
            for t in (p.attn.enc_K,p.attn.enc_V):
                if (t.dtype!=torch.bfloat16 or t.element_size()!=2 or t.stride(1)*2!=512
                        or t.shape[0]!=18 or t.shape[1]<561 or tuple(t.shape[2:])!=(1,256) or t.stride(-1)!=1):
                    raise RuntimeError('unexpected effective KV geometry')
                kv.append((t.data_ptr(),t.stride(0)*2))
            if p.input_images_buf.nbytes!=IMAGES:raise RuntimeError('image buffer byte count')
            if p.bufs['encoder_x'].nbytes<X:raise RuntimeError('encoder x buffer too small')
            self.sources.append(dict(x=p.bufs['encoder_x'].ptr.value,kv=kv,
                                     images=p.input_images_buf.ptr.value,noise=p.input_noise_buf.ptr.value))
        keys=['E'+str(j) for j in range(16)]
        keys += ['R'+str(q)+'/B'+str(b+1) for q in range(8) for b in range(self.max_blocks)]
        keys += ['R'+str(q)+'/stage' for q in range(8)]
        self.events={key:[torch.cuda.Event(enable_timing=True) for _ in range(8)] for key in keys}
        self.last_false={};self.receipts=[];self.noise=None;self.images=None

    def set_segment_id(self,value):
        """Assign the segment identity used by ledger keys, retention index and output dir."""
        self.guard('segment identity assignment')
        if not isinstance(value,str) or not value:raise ValueError('segment id must be a non-empty string')
        if value in self.segment_ids:raise RuntimeError('duplicate segment id: '+value)
        self.segment_ids.add(value);self.segment_id=value

    def label(self):
        return self.segment_id or (self.namespace+str(self.epoch))

    def use_plan(self,plan,block_math):
        """Switch the declared block plan between segments, outside any window."""
        self.guard('block plan switch')
        if len(plan)>self.max_blocks:raise RuntimeError('block plan exceeds preallocated Event depth')
        self.plan=plan;self.block_math=dict(block_math)

    def guard(self,action):
        if self.window and self.mode=='performance':raise RuntimeError('forbidden performance-window action: '+action)

    def bound(self):
        if self.clock()>=self.deadline:raise TimeoutError('170s model admission/operation limit; retain INCOMPLETE')

    def set_window(self,active,mode):
        self.window=active;self.mode=mode
        if active:self.call_start=len(self.ledger.calls)
        else:self.call_end=len(self.ledger.calls)

    def prepare_segment(self,epoch,conf,record):
        self.guard('allocation/preparation')
        self.bound()
        if self.leased:raise RuntimeError('physical bank still leased to previous jobs')
        if self.label() in self.audited_segments:raise RuntimeError('segment identity already persisted: '+self.label())
        self.leased=True;self.epoch=epoch;self.record=record;self.last_false={}
        record['segment_id']=self.label()
        self.operations={key:dict(key=key,kind='stage' if key.endswith('/stage') else 'Expert' if key.startswith('E') else key[-2:],
                                  submitted=False,completed=False) for key in self.events}
        with self.torch.cuda.stream(self.stream):self.gpu.zero_()
        self.host.zero_()
        for es in self.events.values():
            for event in es:event.record(self.stream)
        self.stream.synchronize()
        # Restore both slots to identical external inputs before every segment.
        for slot in (0,1):self.restore(slot,True)
        self.stream.synchronize()
        self.receipts=[]
        record['retention_capacity_B']=self.capacity
        record['event_capacity']=len(self.events)*8
        record['observation_mode']=self.mode

    def ready(self,initial):
        self.guard('initial numerical/resource checks')
        self.stream.synchronize()
        # Input/language/visible resource checks are injected by the model
        # wrapper and run before t0, never by a timed callback.
        self.save_callback('ready',self,initial)
        self.stream.synchronize()
        self.bound()

    def bootstrap(self,manager,snapshots,key):
        self.guard('bootstrap')
        self.bootstrap_callback(manager,snapshots,key)

    def restore(self,slot,images):
        self.bound()
        if images:self.owner._copy_tensor_to_pipeline_buf_stream(self.images,self.ps[slot].input_images_buf,self.stream_id())
        self.owner._copy_tensor_to_pipeline_buf_stream(self.noise,self.ps[slot].input_noise_buf,self.stream_id())

    def copy(self,destination,source,nbytes,kind=3):
        if kind!=3:self.guard('D2H')
        rc=self.runtime.cudaMemcpyAsync(C.c_void_p(destination),C.c_void_p(source),nbytes,kind,self.stream_id())
        if rc:raise RuntimeError('cudaMemcpyAsync status '+str(rc))

    def capture(self,entry,slot):
        self.bound();src=self.sources[slot];dst=self.gptr+entry['offset'];shape=entry['shape']
        if entry['offset']+entry['nbytes']>self.capacity:raise RuntimeError('capture overflow')
        if shape in ('images','noise','raw'):
            self.copy(dst,src['images' if shape=='images' else 'noise'],entry['nbytes'])
        elif shape=='prefix':
            # Prefix-only state: activation only, 0 effective NEW KV layers.
            self.copy(dst,src['x'],X)
        else:
            layers=9 if shape=='mid' else 18
            self.copy(dst,src['x'],X);dst+=X
            for ptr,pitch in src['kv']:
                rc=self.runtime.cudaMemcpy2DAsync(C.c_void_p(dst),KV_LAYER,C.c_void_p(ptr),pitch,KV_LAYER,layers,3,self.stream_id())
                if rc:raise RuntimeError('effective KV cudaMemcpy2DAsync status '+str(rc))
                dst+=layers*KV_LAYER
        self.receipts.append((entry['key'],slot,entry['offset'],entry['nbytes']))

    def mark(self,key,index):
        self.bound();e=self.events[key][index]
        if index==0:self.operations[key]['submitted']=True
        # record_begin is a lower bound for completion of this newly recorded
        # event even if the model kernels finished before the host record call.
        before=self.clock();e.record(self.stream)
        if index==7:self.last_false[id(e)]=before
        return e

    def stream_id(self):
        return getattr(getattr(self,"stream",None),"cuda_stream",0)

    def math_operation(self,slot,kind):
        p=self.ps[slot]
        if kind=='Expert':
            fn=lambda:p.transformer_decoder(self.stream_id());work=None;expected=list(DECODER_CALLS)
        else:
            b=self.plan.kinds.index(kind)
            work=self.plan.blocks[b]
            fn=lambda:self.block_math[kind](p)
            # Observed-call vocabulary of THIS plan block (two-block B1 keeps
            # language+vision27+Encoder0-8; the three-block prefix has no encoder).
            expected=expected_calls(work)
        return fn,work,expected

    def run_math(self,key,slot,kind):
        self.bound()
        fn,work,expected=self.math_operation(slot,kind)
        return self.ledger.execute(self.label()+'/'+key,slot,kind,fn,
                                   expected=expected,work=work)

    def wait_release(self,release):
        while self.clock()<release:
            self.bound();time.sleep(.0001)
        self.bound()

    def wait_event(self,event):
        lower=self.last_false[id(event)]
        while True:
            self.bound();before=self.clock();done=event.query()
            if done:return lower
            lower=before;time.sleep(.0001)

    def complete_op(self,key,lower,upper,keys):
        self.operations[key].update(completed=True,lower_ns=lower,upper_ns=upper,
                                    retained_keys=tuple(keys))

    def download(self,offset=0,nbytes=None):
        self.guard('D2H');nbytes=self.capacity if nbytes is None else nbytes
        self.copy(self.hptr+offset,self.gptr+offset,nbytes,2);self.stream.synchronize()

    def compare_entry(self,entry):
        self.guard('CPU numerical comparison/SHA')
        view=self.host_view[entry['offset']:entry['offset']+entry['nbytes']]
        wanted=self.expected[entry['expected']]
        exact=view==wanted
        row=dict(key=entry['key'],nbytes=entry['nbytes'],exact=exact,
                 sha256=hashlib.sha256(view).hexdigest(),reference_sha256=hashlib.sha256(wanted).hexdigest())
        if entry['shape']=='raw':
            from flash_rt.core.utils.actions import unnormalize_actions
            vals=(self.np.frombuffer(view,dtype='<u2').astype('<u4')<<16).view('<f4').reshape(50,32)
            actions=self.np.ascontiguousarray(unnormalize_actions(vals,self.norm)[:,:7],dtype=self.np.float32).tobytes()
            row['finite']=bool(self.np.isfinite(vals).all())
            row['actions_exact']=actions==self.actions[entry['slot']]
            row['actions_sha256']=hashlib.sha256(actions).hexdigest()
            row['exact']=row['exact'] and row['finite'] and row['actions_exact']
        return row

    def audit_ready(self,entries):
        self.guard('correctness-mode D2H/comparison')
        for e in entries:
            self.download(e['offset'],e['nbytes'])
            if not self.compare_entry(e)['exact']:raise AssertionError('immediate retained numerical mismatch')

    def event_metrics(self):
        self.guard('event elapsed_time queries')
        result=[]
        for key,info in self.operations.items():
            if not info['submitted']:continue
            es=self.events[key]
            row=dict(info,GPU_total_envelope_ms=es[0].elapsed_time(es[7]),
                     GPU_pre_D2D_envelope_ms=es[1].elapsed_time(es[2]))
            if not key.endswith('/stage'):
                row.update(GPU_math_envelope_ms=es[3].elapsed_time(es[4]),
                           GPU_post_retention_envelope_ms=es[5].elapsed_time(es[6]))
            result.append(row)
        return result

    def audit_calls(self,layout,rows):
        from m2_executor import DECODER
        calls_ok=True
        experts=sorted({e['job'] for e in layout['entries'] if e['job'].startswith('E')})
        refreshes=sorted({e['job'] for e in layout['entries'] if e['job'].startswith('R')})
        for job in experts:
            key=self.label()+'/'+job
            got=[tuple(x[3:]) for x in rows if x[0]==key and x[2]=='decoder']
            calls_ok &= tuple(got)==DECODER
        for job in refreshes:
            for b in range(len(self.plan)):
                key=self.label()+'/'+job+'/B'+str(b+1)
                got=[x[3] for x in rows if x[0]==key and x[2]=='encoder']
                calls_ok &= got==[i for i in self.plan.blocks[b] if isinstance(i,int)]
                lang=[x for x in rows if x[0]==key and x[2]=='language']
                vis=[x for x in rows if x[0]==key and x[2]=='vision27']
                calls_ok &= bool(lang)==('language' in self.plan.blocks[b])
                calls_ok &= bool(vis)==('vision27' in self.plan.blocks[b])
        from collections import Counter
        counts=dict(Counter(row[2] for row in rows))
        calls_ok &= counts==dict(encoder=18*len(refreshes),decoder=180*len(experts),language=len(refreshes),vision27=len(refreshes))
        return bool(calls_ok),counts

    def audit_and_persist(self,layout,metadata):
        self.guard('full deferred validation/persistence')
        self.bound();self.download(0,layout['nbytes'])
        checks=[self.compare_entry(e) for e in layout['entries']]
        rows=self.ledger.calls[self.call_start:self.call_end]
        calls_ok,counts=self.audit_calls(layout,rows)
        experts=sorted({e['job'] for e in layout['entries'] if e['job'].startswith('E')})
        refreshes=sorted({e['job'] for e in layout['entries'] if e['job'].startswith('R')})
        segment=self.out/self.label();segment.mkdir(exist_ok=False)
        # memoryview avoids a second full-bank Host allocation.
        with (segment/'RETENTION.bin').open('xb') as f:
            f.write(self.host_view[:layout['nbytes']]);f.flush()
            import os
            os.fsync(f.fileno())
        index=dict(segment_id=self.label(),layout=layout,claims=metadata,capture_receipts=self.receipts,
                   comparisons=checks,call_counts=counts,call_sequence_pass=bool(calls_ok),
                   work_evidence=getattr(self,'work_evidence',{}),
                   operations=self.event_metrics(),payload_sha256=hashlib.sha256(self.host_view[:layout['nbytes']]).hexdigest())
        with (segment/'RETENTION_INDEX.json').open('x') as f:
            json.dump(index,f,indent=2);f.flush();os.fsync(f.fileno())
        fd=os.open(segment,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
        self.audited_segments.add(self.label())
        result=dict(pass_=bool(calls_ok and all(c['exact'] for c in checks)),persisted=True,
                    segment_id=self.label(),
                    records=len(checks),expert_outputs=len(experts),refreshes=len(refreshes),payload_B=layout['nbytes'],
                    all_job_actions_exact=all(c.get('actions_exact',True) for c in checks),
                    call_counts=counts,index=str(segment/'RETENTION_INDEX.json'))
        self.record['call_ledger_start']=self.call_start;self.record['call_ledger_end']=self.call_end
        self.record['operations']=index['operations']
        self.bound()
        return result

    def release_bank(self):
        self.guard('bank reuse')
        if not self.leased:raise RuntimeError('bank not owned')
        self.leased=False
