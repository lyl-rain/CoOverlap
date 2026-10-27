"""Read-only timing hooks around existing calls, never additional math/cuts."""
import time
from m2_clean_cuda import CudaDevice
from m2_clean_core import retention_layout
from m3_b2_backend import confirm_completion


class ProfileHooks:
    """Ten post-D1 Contexts; all 410 timing Events allocated/materialized first.

    Internal event locations are diagnostic landmarks, NOT new scheduling or
    safe-retention boundaries. Only M2's layer-8/full boundaries are runnable.
    """
    LABELS = ('lang_begin','lang_end','vision_begin','vision_end') + tuple(
        'enc%d_%s'%(i,edge) for i in range(18) for edge in ('begin','end')) + ('tail_end',)

    def __init__(self,torch,pipelines,ledger,clock,capacity=10):
        self.stream=torch.cuda.default_stream();self.clock=clock;self.ledger=ledger
        self.pool=[{name:torch.cuda.Event(enable_timing=True) for name in self.LABELS} for _ in range(capacity)]
        for events in self.pool:
            for e in events.values():e.record(self.stream)
        self.stream.synchronize()
        self.records=[];self.active={};self.installed=[]
        for slot,p in enumerate(pipelines):
            lang,vis,enc,full=p._copy_lang_embeds_to_encoder_x,p.vision_encoder,p._encoder_layer,p.transformer_encoder
            self.installed.append((p,lang,vis,enc,full))
            def l(*a,_fn=lang,_slot=slot,**kw):
                if len(self.records)>=len(self.pool):raise RuntimeError('profiling Event capacity exhausted')
                row=dict(index=len(self.records),slot=_slot,key=self.ledger.active,host={},marks=set())
                self.records.append(row);self.active[_slot]=row
                self.mark(_slot,'lang_begin');value=_fn(*a,**kw);self.mark(_slot,'lang_end');return value
            def v(*a,_fn=vis,_slot=slot,**kw):
                self.mark(_slot,'vision_begin');value=_fn(*a,**kw);self.mark(_slot,'vision_end');return value
            def e(i,*a,_fn=enc,_slot=slot,**kw):
                self.mark(_slot,'enc%d_begin'%i);value=_fn(i,*a,**kw);self.mark(_slot,'enc%d_end'%i);return value
            def f(*a,_fn=full,_slot=slot,**kw):
                value=_fn(*a,**kw);self.tail(_slot);return value
            p._copy_lang_embeds_to_encoder_x,p.vision_encoder,p._encoder_layer,p.transformer_encoder=l,v,e,f

    def mark(self,slot,label):
        row=self.active[slot]
        if label in row['marks']:raise RuntimeError('repeated profiling/model landmark')
        row['host'][label]=self.clock()
        self.pool[row['index']][label].record(self.stream);row['marks'].add(label)

    def tail(self,slot):self.mark(slot,'tail_end')

    def export(self,require_complete=True):
        out=[]
        for row in self.records:
            complete=row['marks']==set(self.LABELS)
            events=self.pool[row['index']]
            done=complete and all(events[k].query() for k in self.LABELS)
            if require_complete and not done:raise RuntimeError('profiling Context incomplete/pending')
            result=dict(index=row['index'],slot=row['slot'],key=row['key'],host=row['host'],
                        complete=bool(done),marks=sorted(row['marks']))
            if done:
                pairs=dict(language=('lang_begin','lang_end'),vision27=('vision_begin','vision_end'),
                    projection_group=('vision_end','enc0_begin'),encoder_0_8=('enc0_begin','enc8_end'),
                    encoder_9_17=('enc9_begin','enc17_end'),tail=('enc17_end','tail_end'),
                    context_envelope=('lang_begin','tail_end'))
                result['event_envelopes_ms']={k:events[a].elapsed_time(events[b]) for k,(a,b) in pairs.items()}
                result['encoder_layers_event_ms']=[events['enc%d_begin'%i].elapsed_time(events['enc%d_end'%i]) for i in range(18)]
            out.append(result)
        return out


class ProfileDevice(CudaDevice):
    def __init__(self,*args,**kw):
        kw.setdefault('capacity',retention_layout(4)['nbytes'])
        super().__init__(*args,**kw)
        self.hooks=None

    def mark(self,key,index):
        if index==0:self.operations[key]['operation_submit_begin_host_ns']=self.clock()
        return super().mark(key,index)

    def wait_event(self,event):
        key=next(k for k,es in self.events.items() if es[7] is event)
        row=self.operations[key];lower=self.last_false[id(event)]
        row['event_wait_begin_host_ns']=self.clock();polls=0
        while True:
            self.bound();before=self.clock();done=event.query();after=self.clock();polls+=1
            if done:
                row.update(first_true_query_before_host_ns=before,first_true_query_after_host_ns=after,
                           last_false_or_record_begin_host_ns=lower,event_poll_count=polls)
                return lower
            lower=before;time.sleep(.0001)

    def complete_op(self,key,lower,upper,keys):
        # Every future operation, including stage, requires a fresh actual query.
        row=self.operations[key]
        confirm_completion(self.events[key][7],row,lower,self.clock)
        row.update(lower_ns=lower,upper_ns=upper,retained_keys=tuple(keys))

    def run_math(self,key,slot,kind):
        self.operations[key]['math_submit_begin_host_ns']=self.clock()
        calls=super().run_math(key,slot,kind)
        if kind=='B2':self.hooks.tail(slot)
        self.operations[key]['math_submit_return_host_ns']=self.clock()
        return calls
