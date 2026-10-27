"""One implementation for both observation modes; CUDA-free at import time."""
from m2_executor import DEFAULT_PLAN
from m2_clean_core import RetentionLedger, retention_layout, tag


class CleanBackend:
    def __init__(self,device,snapshots,verification_mode='performance',layout=None,plan=None,
                 stage_observer=None):
        if verification_mode not in ('performance','correctness'):
            raise ValueError('unknown observation mode')
        self.d=device;self.snapshots=snapshots;self.mode=verification_mode
        self.d.set_window(False,verification_mode)
        self.plan=DEFAULT_PLAN if plan is None else plan
        self.layout=layout or retention_layout(plan=self.plan)
        self.bank=RetentionLedger(self.layout,device.capacity)
        self.stage_observer=stage_observer
        self.window=False;self.epoch=-1;self.record=None

    def prepare(self,manager,conf,record):
        self.guard_outside('prepare')
        self.epoch+=1;self.record=record;self.bank.begin(self.epoch)
        self.d.prepare_segment(self.epoch,conf,record)

    def bootstrap(self,manager,key):
        self.guard_outside('bootstrap')
        self.d.bootstrap(manager,self.snapshots,key)

    def ready(self,manager):
        self.guard_outside('ready')
        current=manager.get(manager.current)
        initial=dict(current=vars(current.handle),snapshot=current.snapshot.name,
                     phase=current.phase,readers=len(current.readers),generations=list(manager.generations))
        if (vars(current.handle)!=dict(slot=0,generation=1,version=0) or current.snapshot.name!='S0'
                or current.phase!='PUBLISHED' or current.readers or manager.generations!=[1,0]):
            raise RuntimeError('unequal logical segment initial state')
        self.d.ready(initial)
        return initial

    def enter_window(self):
        self.window=True;self.d.set_window(True,self.mode)

    def leave_window(self):
        self.window=False;self.d.set_window(False,self.mode)

    def guard_outside(self,action):
        if self.window and self.mode=='performance':
            raise RuntimeError('forbidden performance-window action: '+action)

    def wait_release(self,release):
        self.d.wait_release(release)

    def capture(self,manager,key,handle):
        v=manager.get(handle)
        if v.snapshot!=self.snapshots[handle.slot]:raise RuntimeError('snapshot mutation')
        entry=self.bank.claim(key,handle,v.snapshot)
        self.d.capture(entry,handle.slot)
        return key

    def observe(self,keys):
        if self.mode=='correctness':
            # Same execution/retention implementation; this hook alone adds
            # intrusive immediate D2H/comparison. Such timings are diagnostic.
            self.d.audit_ready([self.bank.entries[k] for k in keys])

    def stage(self,manager,handle,job):
        obs=self.stage_observer
        key=job+'/stage';self.d.mark(key,0,observer=obs);self.d.mark(key,1,observer=obs)
        self.d.restore(handle.slot,True,observer=obs)
        if obs is not None:obs.capture_before('images')
        image_key=self.capture(manager,job+'/images',handle)
        if obs is not None:obs.capture_after('images')
        if obs is not None:obs.capture_before('noise')
        noise_key=self.capture(manager,job+'/noise',handle)
        if obs is not None:obs.capture_after('noise')
        keys=[image_key,noise_key]
        self.d.mark(key,2,observer=obs);event=self.d.mark(key,7,observer=obs)
        self.bank.seal(keys,event);self.observe(keys)

    def block(self,manager,handle,index,key):
        v=manager.get(handle);manager.check_block(handle,index,v.snapshot,self.plan.blocks[index])
        other=manager.current
        self.d.mark(key,0);self.d.mark(key,1)
        keys=[self.capture(manager,key+'/other_pre',other)]
        self.d.mark(key,2);self.d.mark(key,3)
        calls=self.d.run_math(key,handle.slot,self.plan.kinds[index])
        self.d.mark(key,4);self.d.mark(key,5)
        keys += [self.capture(manager,key+'/target',handle),self.capture(manager,key+'/other_post',other)]
        self.d.mark(key,6);event=self.d.mark(key,7);self.bank.seal(keys,event)
        manager.submit_block(handle,index,v.snapshot,calls,event)
        lower=self.d.wait_event(event)
        if not manager.poll_block(handle):raise RuntimeError('block event not complete')
        self.observe(keys)
        self.d.complete_op(key,lower,None,keys);upper=self.d.clock()
        self.d.operations[key]['upper_ns']=upper
        return lower,upper

    def expert(self,manager,job,handle):
        manager.check_expert(job,handle)
        self.d.mark(job,0);self.d.mark(job,1)
        self.d.restore(handle.slot,False)
        keys=[self.capture(manager,job+'/noise',handle),self.capture(manager,job+'/pre',handle)]
        self.d.mark(job,2);self.d.mark(job,3)
        calls=self.d.run_math(job,handle.slot,'Expert')
        self.d.mark(job,4);self.d.mark(job,5)
        keys += [self.capture(manager,job+'/raw',handle),self.capture(manager,job+'/post',handle)]
        self.d.mark(job,6);event=self.d.mark(job,7);self.bank.seal(keys,event)
        manager.submit_expert(job,handle,calls,event)
        lower=self.d.wait_event(event)
        if not manager.poll_expert(job):raise RuntimeError('reader event not complete')
        self.observe(keys)
        self.d.complete_op(job,lower,None,keys);upper=self.d.clock()
        self.d.operations[job]['upper_ns']=upper
        return lower,upper

    def drain(self):
        # No remaining model/retention work when this returns. Missing or
        # failed events keep this bank owned, never silently dropped.
        self.bank.complete()

    def validate_and_persist(self):
        self.guard_outside('D2H/compare/write')
        self.bank.complete()
        result=self.d.audit_and_persist(self.layout,self.bank.metadata())
        if not result['pass_']:raise AssertionError('retained job numerical/state mismatch')
        self.bank.mark_verified();self.bank.release(persisted=result['persisted']);self.d.release_bank()
        self.record['validation']=result
        self.record['status']='PASS'
        return result
