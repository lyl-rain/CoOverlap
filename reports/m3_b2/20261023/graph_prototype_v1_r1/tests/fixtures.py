"""CPU boundary fixtures ONLY. Production math/scheduler/ownership are not copied."""
import sys
from pathlib import Path
from types import SimpleNamespace
D=Path(__file__).resolve().parents[1]/'deployment'
sys.path.insert(0,str(D))
from validate_m3_b3_cpu import PlanDevice
from m3_b3_plan import CONTROL
from graph_backend import GraphDevice,GraphRegistry
from m2_pi05_ops import CallLedger,block1,block2


class API:
    def __init__(self,device):self.device=device;self.capturing=None;self.replays=0;self.capture_calls=0
    def emit(self,fn):
        if self.capturing is not None:self.capturing.commands.append(fn)
        else:fn()
    def CUDAGraph(self):
        api=self
        class Graph:
            def __init__(self):self.commands=[]
            def replay(self):
                api.replays+=1
                for f in self.commands:f() # recorded native-op boundary, NOT model callable
        return Graph()
    def graph(self,g,stream,capture_error_mode):
        api=self
        class Capture:
            def __enter__(self):
                assert stream.cuda_stream==77;api.capturing=g;api.capture_calls+=1
            def __exit__(self,*args):api.capturing=None
        return Capture()
    def stream(self,s):
        class Context:
            def __enter__(self):assert s.cuda_stream==77
            def __exit__(self,*args):pass
        return Context()


class NativeOps:
    def layer_norm(self,*args,stream):assert stream==77
    def bf16_nn(self,*args,stream):assert stream==77
    def add_bias_bf16(self,*args,stream):assert stream==77


class Pipeline:
    def __init__(self,d,slot):
        self.d,self.slot=d,slot;self.vision_seq_enc=512
        self.bufs={k:SimpleNamespace(ptr=SimpleNamespace(value=i+1000+slot*100)) for i,k in enumerate(['vision_x_pooled','vision_x_norm','encoder_x'])}
        self.weights={k:500+i for i,k in enumerate(['vision_final_norm_w','vision_final_norm_b','encoder_multi_modal_projector_w','encoder_multi_modal_projector_b'])}
        self.fvk=self.gemm=NativeOps()
    def emit(self,action,stream):
        assert stream==77;self.d.api.emit(action)
    def _copy_lang_embeds_to_encoder_x(self,stream=0):
        def action():
            self.d.physical[self.slot].update(v=self.d.nextv,state='prefix');self.d.nextv+=1
        self.emit(action,stream)
    def vision_encoder(self,stream=0):self.emit(lambda:setattr(self.d,'now',self.d.now+30_000_000),stream)
    def _encoder_layer(self,i,seq,fuse,stream):
        def action():
            self.d.now+=5_500_000 if i<9 else 4_900_000
            if i==8:self.d.physical[self.slot]['state']='mid'
            if i==17:self.d.physical[self.slot]['state']='full'
        self.emit(action,stream)
    def _decoder_layer(self,i,step,seq,ds,skip,stream):
        def action():
            self.d.now+=420_000
            if (step,i)==(9,17):
                key=self.d.math_context[2]
                s=self.d.physical[self.slot];s.update(raw_job=key,raw_version=s['v'],noise='overwritten')
        self.emit(action,stream)
    def transformer_decoder(self,stream=0):
        for step in range(10):
            for i in range(18):self._decoder_layer(i,step,561,50,False,stream)


class Device(GraphDevice,PlanDevice):
    """Replace allocation/native CUDA boundary; use real GraphDevice.run_math,
    real math bodies, CallLedger, GraphBoundaryBackend, run_segment and KV."""
    def __init__(self):
        PlanDevice.__init__(self,plan=CONTROL)
        self.capacity=487320064;self.window=False;self.mode='performance';self.segment_id=None;self.segment_ids=set()
        self.api=API(self);self.stream=SimpleNamespace(cuda_stream=77,query=lambda:True)
        self.ps=[Pipeline(self,i) for i in (0,1)]
        self.ledger=CallLedger(self.ps);self.ledger.stream_id=77
        self.addresses=[10000,20000]
        self.block_math=dict(B1=lambda p:block1(p,2048,1152,stream=77),B2=lambda p:block2(p,stream=77))
        registry=GraphRegistry(self.api,self.stream,self.ledger,lambda s:((s,self.addresses[s]),),self.bound,clock=self.clock)
        self.configure_graph(registry)
        for s in (0,1):
            for kind in ('B1','B2','Expert'):
                fn,work,expected=self.math_operation(s,kind)
                if kind=='Expert':work=__import__('m2_executor').DECODER
                registry.capture_unit(s,kind,fn,work,expected)
    def bound(self):pass
    def run_math(self,*a,**k):return GraphDevice.run_math(self,*a,**k)
    def prepare_segment(self,epoch,conf,record):
        PlanDevice.prepare_segment(self,epoch,conf,record);self.record=record
        self.registry.begin_segment(self.label(),self.engine)
    def set_window(self,on,mode):
        PlanDevice.set_window(self,on,mode);self.window=on
        if on:self.call_start=len(self.ledger.calls)
        else:self.call_end=len(self.ledger.calls)
    def audit_and_persist(self,layout,metadata):
        ok,counts=GraphDevice.audit_calls(self,layout,self.ledger.calls[self.call_start:self.call_end])
        assert ok
        result=PlanDevice.audit_and_persist(self,layout,metadata)
        result['work_counts']=counts
        return result
    def restore(self,slot,images):return PlanDevice.restore(self,slot,images)
    def capture(self,e,slot):return PlanDevice.capture(self,e,slot)
    def mark(self,key,index):
        from validate_m2_clean_cpu import Event
        if index==0:self.operations[key]=dict(submitted=True,completed=False)
        self.now+=100
        self.events.setdefault(key,[Event() for _ in range(8)])
        return self.events[key][index]
    def wait_event(self,event):return PlanDevice.wait_event(self,event)
    def complete_op(self,*a):return PlanDevice.complete_op(self,*a)
    def ready(self,initial):return PlanDevice.ready(self,initial)
    def bootstrap(self,*a):return PlanDevice.bootstrap(self,*a)
    def wait_release(self,*a):return PlanDevice.wait_release(self,*a)
    def audit_ready(self,*a):return PlanDevice.audit_ready(self,*a)
    def release_bank(self):return PlanDevice.release_bank(self)
