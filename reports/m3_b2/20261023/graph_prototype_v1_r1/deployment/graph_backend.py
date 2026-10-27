"""Real CUDA Graph adapter; no CUDA import or allocation at import time.

The injected cuda object is torch.cuda in production, a recording API fixture
in CPU tests. Both engines share math_operation and the real ownership manager.
"""
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from m2_executor import DECODER, DECODER_CALLS, expected_calls
from m3_b2_backend import BoundaryBackend
from m2_clean_cuda import CudaDevice


class GraphError(RuntimeError):
    pass


@dataclass(frozen=True)
class Unit:
    graph_id: str
    slot: int
    kind: str
    graph: object
    addresses: tuple
    observed_capture_calls: tuple
    work: tuple


class GraphRegistry:
    def __init__(self, cuda, stream, ledger, fingerprint, bound, clock=time.monotonic_ns):
        if not getattr(stream, 'cuda_stream', 0):
            raise GraphError('explicit non-default stream required for BOTH engines')
        self.cuda,self.stream,self.ledger=cuda,stream,ledger
        self.fingerprint,self.bound,self.clock=fingerprint,bound,clock
        self.units={};self.segment=None;self.rows={};self.engine='eager'

    def capture_unit(self,slot,kind,fn,work,expected):
        self.bound()
        key=(slot,kind)
        if key in self.units or len(self.units)>=6:
            raise GraphError('duplicate or excessive capture')
        addresses=tuple(self.fingerprint(slot))
        graph=self.cuda.CUDAGraph()
        start=len(self.ledger.calls)
        # No model warmup is hidden here. Capture host calls are accounted
        # separately from graph launches / complete GPU forwards.
        with self.cuda.graph(graph,stream=self.stream,capture_error_mode='global'):
            self.ledger.execute('capture/slot%d/%s'%(slot,kind),slot,kind,fn,
                                expected=expected,work=work)
        calls=tuple(tuple(r[2:]) for r in self.ledger.calls[start:])
        if calls!=tuple(expected) or any(r[1]!=slot for r in self.ledger.calls[start:]):
            raise GraphError('capture call sequence/slot mismatch')
        if tuple(self.fingerprint(slot))!=addresses:
            raise GraphError('capture changed visible model addresses')
        self.units[key]=Unit('slot%d_%s'%(slot,kind),slot,kind,graph,addresses,calls,tuple(work))
        self.bound()
        return self.units[key]

    def begin_segment(self,label,engine):
        if engine not in ('eager','graph'):raise GraphError('unknown engine')
        if len(self.units)!=6:raise GraphError('all six verified capture manifests required')
        self.segment,self.engine=label,engine
        self.rows={}

    def execute(self,manager,handle,key,kind,eager,completion_event):
        entered=self.clock()
        self.bound()
        if not callable(getattr(completion_event,'query',None)):raise GraphError('fresh completion Event required')
        if self.segment is None:raise GraphError('segment identity missing')
        version=manager.get(handle) # real slot+generation+version identity
        if kind=='Expert':
            manager.check_expert(key,handle)
            work=DECODER
        else:
            b=manager.plan.kinds.index(kind);work=manager.plan.blocks[b]
            manager.check_block(handle,b,version.snapshot,work)
        slot=handle.slot
        unit=self.units[(slot,kind)]
        if tuple(work)!=unit.work:raise GraphError('capture work differs from current plan')
        if tuple(self.fingerprint(slot))!=unit.addresses:raise GraphError('device address changed')
        if key in self.rows:raise GraphError('duplicate submitted job')
        row=dict(segment_id=self.segment,job_id=key,graph_id=unit.graph_id,kind=kind,
                 slot=slot,generation=handle.generation,version=handle.version,
                 engine=self.engine,status='SUBMITTED',event=None,event_confirmed=False,
                 submit_enter_host_ns=entered,native_launch_before_host_ns=self.clock(),expected_event=id(completion_event))
        self.rows[key]=row
        if self.engine=='graph':
            with self.cuda.stream(self.stream):unit.graph.replay()
        else:
            with self.cuda.stream(self.stream):eager()
        row['native_launch_after_host_ns']=self.clock()
        row['submit_exit_host_ns']=self.clock()
        return tuple(work)

    def confirm(self,key,event):
        if key not in self.rows:raise GraphError('completion without submission')
        row=self.rows[key]
        if row['status']!='SUBMITTED':raise GraphError('duplicate completion')
        if id(event)!=row.get('expected_event'):raise GraphError('wrong completion Event identity')
        if not event.query():raise GraphError('completion Event not ready')
        row.update(status='COMPLETE',event=id(event),event_confirmed=True,confirm_host_ns=self.clock())

    def audit(self,layout):
        expected={}
        for entry in layout['entries']:
            job=entry['job']
            if job.startswith('R') and not entry['key'].endswith('/target'):
                continue # other_pre/post describe the predecessor, not this job
            kinds=('Expert',) if job.startswith('E') else ('B1','B2')
            for kind in kinds:
                key=job if kind=='Expert' else job+'/'+kind
                expected[key]=(kind,entry['slot'],entry['generation'],entry['version'])
        if set(self.rows)!=set(expected):raise GraphError('missing/extra replay or direct job')
        counts=Counter()
        for key,want in expected.items():
            row=self.rows[key]
            got=tuple(row[k] for k in ('kind','slot','generation','version'))
            if got!=want or row['segment_id']!=self.segment:
                raise GraphError('wrong slot/generation/version/segment in job ledger')
            if row['status']!='COMPLETE' or not row['event_confirmed'] or row['event'] is None or row['event']!=row['expected_event']:
                raise GraphError('job has no confirmed completion')
            unit=self.units[(row['slot'],row['kind'])]
            counts.update(c[0] for c in unit.observed_capture_calls)
        return dict(counts)

    def manifests(self):
        return [dict(graph_id=u.graph_id,slot=u.slot,kind=u.kind,
                     addresses=u.addresses,observed_capture_calls=u.observed_capture_calls,
                     work=u.work) for u in self.units.values()]


class GraphDevice(CudaDevice):
    """All restore/copy/Event/retention paths remain the shared CudaDevice ones."""
    def configure_graph(self,registry):
        self.registry=registry;self.engine='eager';self.math_context=None

    def select_engine(self,engine):
        self.guard('engine switch')
        if self.leased:raise GraphError('cannot switch engine with a leased bank')
        if engine not in ('eager','graph'):raise GraphError('unknown engine')
        self.engine=engine

    def prepare_segment(self,*args,**kwargs):
        super().prepare_segment(*args,**kwargs)
        self.registry.begin_segment(self.label(),self.engine)
        self.record['engine']=self.engine

    def run_math(self,key,slot,kind):
        self.bound()
        if self.math_context is None:raise GraphError('math requires real manager/handle')
        manager,handle,wanted_key,wanted_kind=self.math_context
        if (key,kind,slot)!=(wanted_key,wanted_kind,handle.slot):
            raise GraphError('request conflicts with bound handle')
        fn,work,expected=self.math_operation(slot,kind)
        def eager():
            return self.ledger.execute(self.label()+'/'+key,slot,kind,fn,expected=expected,work=work)
        return self.registry.execute(manager,handle,key,kind,eager,self.events[key][7])

    def audit_calls(self,layout,rows):
        logical=self.registry.audit(layout)
        if self.engine=='eager':
            ok,actual=super().audit_calls(layout,rows)
            if actual!=logical:raise GraphError('direct calls disagree with captured work definition')
            evidence='actual eager CallLedger + confirmed per-job ledger'
        else:
            if rows:raise GraphError('Graph replay unexpectedly executed Python model calls')
            ok=True
            evidence='capture-observed call manifest x confirmed replay instances; NOT replay Python observations'
        self.work_evidence=dict(source=evidence,logical_model_calls=logical,
                               runtime_python_call_rows=len(rows),jobs=list(self.registry.rows.values()))
        self.record['work_evidence']=self.work_evidence
        return ok,logical


class GraphBoundaryBackend(BoundaryBackend):
    @contextmanager
    def context(self,manager,handle,key,kind):
        if self.d.math_context is not None:raise GraphError('nested math context')
        self.d.math_context=(manager,handle,key,kind)
        try:yield
        finally:self.d.math_context=None

    def block(self,manager,handle,index,key):
        with self.context(manager,handle,key,self.plan.kinds[index]):
            return super().block(manager,handle,index,key)

    def expert(self,manager,job,handle):
        with self.context(manager,handle,job,'Expert'):
            return super().expert(manager,job,handle)

    def finish(self,key,lower):
        interval=super().finish(key,lower)
        if key in self.d.registry.rows:self.d.registry.confirm(key,self.d.events[key][7])
        # Include graph/direct job accounting in the Host completion upper bound.
        upper=self.d.clock();self.d.operations[key].update(upper_ns=upper,host_finalization_upper_ns=upper,job_accounting_upper_host_ns=upper)
        return interval[0],upper
