"""Dependency-closed CPU contracts selected for mainline integration.

Twenty existing tests retain their original assertions. Three model-adapter /
GPU-entry checks are not included; see docs/MAINLINE_INTEGRATION.md.
Fake events provide no GPU correctness evidence.
"""
import dataclasses
import hashlib
import unittest

from m2_executor import (VersionedKV, Snapshot, BLOCKS, DECODER, replay_manifest,
                         replay_stats, completion)


class Event:
    def __init__(self, done=False): self.done = done
    def query(self): return self.done


def snapshot(name='S0'):
    return Snapshot(name, *[hashlib.sha256((name+k).encode()).hexdigest() for k in ('image','wrist','state','language','noise')])


def ready(m, slot, s=None):
    s = s or snapshot()
    h = m.begin(slot, s)
    for i in (0, 1):
        m.submit_block(h, i, s, BLOCKS[i], Event(True))
        assert m.poll_block(h)
    return h


class Contracts(unittest.TestCase):
    def setUp(self):
        self.m = VersionedKV(); self.s = snapshot(); self.h = ready(self.m, 0, self.s); self.m.publish(self.h)

    def test_snapshot_immutable_and_complete(self):
        with self.assertRaises(dataclasses.FrozenInstanceError): self.s.name = 'changed'
        with self.assertRaises(ValueError): Snapshot('bad', *['missing']*5)

    def test_partial_publication_rejected(self):
        h=self.m.begin(1,self.s)
        with self.assertRaises(RuntimeError): self.m.publish(h)
        self.m.submit_block(h,0,self.s,BLOCKS[0],Event(True));self.m.poll_block(h)
        with self.assertRaises(RuntimeError): self.m.publish(h)

    def test_event_before_publish_and_restore(self):
        h=self.m.begin(1,self.s);e=Event()
        self.m.submit_block(h,0,self.s,BLOCKS[0],e)
        self.assertFalse(self.m.poll_block(h))
        with self.assertRaises(RuntimeError): self.m.submit_block(h,1,self.s,BLOCKS[1],Event(True))
        e.done=True;self.m.poll_block(h);end=Event()
        self.m.submit_block(h,1,self.s,BLOCKS[1],end)
        with self.assertRaises(RuntimeError): self.m.publish(h)
        end.done=True;self.m.poll_block(h);self.m.publish(h)

    def test_wrong_input_and_order_rejected(self):
        h=self.m.begin(1,self.s)
        with self.assertRaises(RuntimeError): self.m.submit_block(h,1,self.s,BLOCKS[1],Event(True))
        with self.assertRaises(ValueError): self.m.submit_block(h,0,snapshot('S1'),BLOCKS[0],Event(True))
        with self.assertRaises(ValueError): self.m.submit_block(h,0,self.s,BLOCKS[0][:-1],Event(True))

    def test_reader_spanning_publication_pins_old(self):
        self.m.bind('E',self.s.noise_sha);n=ready(self.m,1,snapshot('S1'));self.m.publish(n)
        self.assertEqual(self.m.readers['E'].handle,self.h)
        with self.assertRaises(RuntimeError): self.m.reclaim(self.h)
        done=Event();self.m.submit_expert('E',self.h,DECODER,done)
        self.assertFalse(self.m.poll_expert('E'))
        with self.assertRaises(RuntimeError): self.m.reclaim(self.h)
        done.done=True;self.m.poll_expert('E');self.m.reclaim(self.h)

    def test_latest_binding_and_old_reader_not_rebound(self):
        self.m.bind('old',self.s.noise_sha);n=ready(self.m,1,snapshot('S1'));self.m.publish(n)
        self.assertEqual(self.m.bind('new',snapshot('S1').noise_sha),n)
        with self.assertRaises(RuntimeError): self.m.bind('stale',self.s.noise_sha,0)
        with self.assertRaises(RuntimeError): self.m.submit_expert('old',n,DECODER,Event(True))

    def test_expert_complete_ten_steps_required(self):
        self.m.bind('E',self.s.noise_sha)
        for calls in (DECODER[:-1], DECODER+DECODER[:1], tuple(reversed(DECODER))):
            with self.assertRaises(RuntimeError):self.m.submit_expert('E',self.h,calls,Event(True))
        with self.assertRaises(RuntimeError): self.m.bind('badnoise',snapshot('S1').noise_sha)

    def test_scratch_readers_serialize(self):
        self.m.bind('A',self.s.noise_sha);self.m.bind('B',self.s.noise_sha);e=Event()
        self.m.submit_expert('A',self.h,DECODER,e)
        with self.assertRaises(RuntimeError): self.m.submit_expert('B',self.h,DECODER,Event(True))
        e.done=True;self.m.poll_expert('A');self.m.submit_expert('B',self.h,DECODER,Event(True));self.m.poll_expert('B')

    def test_duplicate_and_cancel_semantics(self):
        self.m.bind('A',self.s.noise_sha)
        with self.assertRaises(ValueError):self.m.bind('A',self.s.noise_sha)
        self.m.cancel_unsubmitted('A');self.assertFalse(self.m.get(self.h).readers)
        self.m.bind('B',self.s.noise_sha);self.m.submit_expert('B',self.h,DECODER,Event())
        with self.assertRaises(RuntimeError):self.m.cancel_unsubmitted('B')

    def test_timeout_quarantines_until_gpu_done(self):
        h=self.m.begin(1,self.s);e=Event();self.m.submit_block(h,0,self.s,BLOCKS[0],e);self.m.quarantine(h)
        with self.assertRaises(RuntimeError): self.m.publish(h)
        with self.assertRaises(RuntimeError): self.m.reclaim(h)
        e.done=True;self.m.reclaim(h)
        newer=self.m.begin(1,self.s);self.assertGreater(newer.generation,h.generation)
        with self.assertRaises(ValueError):self.m.get(h)

    def test_event_query_error_never_frees(self):
        class Broken:
            def query(self):raise RuntimeError('device error')
        h=self.m.begin(1,self.s);self.m.submit_block(h,0,self.s,BLOCKS[0],Broken());self.m.quarantine(h)
        with self.assertRaises(RuntimeError):self.m.reclaim(h)
        self.assertIsNotNone(self.m.slots[1])

    def test_long_reuse_1000_generations(self):
        for i in range(1000):
            old=self.m.current;n=ready(self.m,1-old.slot,snapshot('S1' if i%2==0 else 'S0'));self.m.publish(n);self.m.reclaim(old)
        self.assertEqual(self.m.current.version,1000)
        self.assertEqual(sum(self.m.generations),1001)

    def test_release_clock_and_incomplete_denominator(self):
        p=replay_manifest(100,4)
        out=replay_stats(p,{0:(120,130),1:(250,260)}, {(0,0):(70,80),(0,1):(240,250)}, {0:(240,260)})
        self.assertEqual([r['release_ns'] for r in out['cycles']],[0,100,200,300])
        self.assertEqual(out['cycle_counts']['denominator'],4)
        self.assertEqual(out['cycle_counts']['FAIL'],2)
        self.assertEqual(out['cycle_counts']['INCOMPLETE'],2)
        self.assertIsNone(out['response_upper_p99_ns']);self.assertEqual(out['backlog'],1)
        self.assertEqual(out['refreshes'][0]['k_upper'],3)

    def test_uncertain_deadline_equality_and_publication_cost(self):
        p=replay_manifest(100,2)
        out=replay_stats(p,{0:(90,100),1:(195,205)}, {(0,0):(90,100),(0,1):(190,200)}, {0:(199,205)})
        self.assertEqual([r['status'] for r in out['cycles']],['PASS','UNCERTAIN'])
        self.assertEqual(out['refreshes'][0]['status'],'UNCERTAIN')
        self.assertEqual(out['refreshes'][0]['ready_upper_ns'],205)
        self.assertEqual(out['cycle_counts']['miss_ratio_upper'],.5)

    def test_fair_manifest_and_complete_work(self):
        a=replay_manifest();b=replay_manifest();self.assertEqual(a,b)
        self.assertEqual([e['version'] for e in a['experts']],[0,0,1,1,2,2,3,3])
        self.assertEqual(len(a['refreshes']),4)
        for bad in (0,-1,1.2):
            with self.assertRaises(ValueError):replay_manifest(bad)
        with self.assertRaises(ValueError):replay_manifest(cycles=3)

    def test_completion_interval_includes_poll_uncertainty(self):
        class E:
            def __init__(self):self.q=0
            def query(self):self.q+=1;return self.q==2
        times=iter([11,12,20,21]);self.assertEqual(completion(E(),10,lambda:next(times)),(11,21))


    def test_both_replay_orders_share_real_driver(self):
        from m2_replay_driver import replay
        # Symbolic backend only: deliberately overruns deadlines and retains
        # state in physical slots while the same real replay driver runs.
        s0=snapshot();s1=dataclasses.replace(snapshot('S1'),noise_sha=s0.noise_sha)
        results=[]
        for mode in ('serial_adjacent','serial_resumed'):
            m=VersionedKV();now=[0];state={};outputs=[];work=[]
            def stage(slot):state[slot]=[]
            def block(mm,h,b,key):
                v=mm.get(h);mm.check_block(h,b,v.snapshot,BLOCKS[b]);before=now[0]
                state[h.slot].extend(BLOCKS[b]);now[0]+=160_000_000
                mm.submit_block(h,b,v.snapshot,BLOCKS[b],Event(True));mm.poll_block(h)
                self.assertEqual(tuple(state[h.slot]), BLOCKS[0] if b==0 else BLOCKS[0]+BLOCKS[1])
                work.append((h.version,b));return before,now[0]
            def boot(mm,key):
                h=mm.begin(0,s0);stage(0)
                block(mm,h,0,key);block(mm,h,1,key);mm.publish(h)
            def expert(mm,job,h):
                mm.check_expert(job,h);before=now[0];now[0]+=180_000_000
                outputs.append((h.version,mm.get(h).snapshot.name,s0.noise_sha,tuple(state[h.slot])))
                mm.submit_expert(job,h,DECODER,Event(True));mm.poll_expert(job);return before,now[0]
            def wait_release(t):now[0]=max(t,now[0])
            result=replay(m,[s0,s1],mode,boot,stage,block,expert,wait_release,lambda:now[0])
            self.assertEqual(result['statistics']['cycle_counts']['denominator'],8)
            self.assertEqual(result['statistics']['refresh_counts']['denominator'],4)
            self.assertEqual(len(work),10) # bootstrap plus 4 complete refreshes
            self.assertEqual(len(outputs),8)
            self.assertGreater(result['statistics']['cycle_counts']['FAIL'],0)
            self.assertFalse(any(v.readers for v in m.slots if v))
            results.append((outputs,work))
        self.assertEqual(results[0],results[1])

    def test_exact_boundary_k_and_bad_stats_ids(self):
        p=replay_manifest(100,2)
        result=replay_stats(p,{0:(90,100),1:(190,200)},{(0,0):(90,100),(0,1):(190,200)},{0:(200,200)})
        self.assertEqual(result['refreshes'][0]['k_upper'],2)
        self.assertEqual(result['refreshes'][0]['status'],'PASS')
        with self.assertRaises(ValueError): replay_stats(p,{9:(1,2)},{},{})
        with self.assertRaises(ValueError): replay_stats(p,{0:(5,4)},{},{})



    def test_never_done_event_wait_is_finite(self):
        times=iter([1,2,3,4,5])
        with self.assertRaises(TimeoutError):completion(Event(),0,lambda:next(times),deadline_ns=5)

    def test_replay_failure_retains_full_denominator(self):
        from m2_replay_driver import replay
        m=VersionedKV();rec={};s=snapshot()
        def boot(mm,key):mm.publish(ready(mm,0,s))
        def fail(*args):raise TimeoutError('injected backend timeout')
        with self.assertRaises(TimeoutError):replay(m,[s,s],'serial_adjacent',boot,fail,fail,fail,lambda t:None,lambda:0,record=rec)
        self.assertEqual(rec['status'],'INCOMPLETE')
        self.assertEqual(rec['statistics']['cycle_counts']['INCOMPLETE'],8)
        self.assertEqual(rec['statistics']['refresh_counts']['INCOMPLETE'],4)


if __name__=='__main__':
    unittest.main(verbosity=2)
