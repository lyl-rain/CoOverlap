"""Host-only background polling of recorded B1 Events; no launches or scheduling."""
import threading,time
class B1Observer:
    def __init__(self,sleep_s):
        self.sleep_s=sleep_s;self.lock=threading.Lock();self.items={};self.stop=threading.Event()
        self.thread=threading.Thread(target=self._loop,name='B1_Event_observer',daemon=True);self.thread.start()
    def arm(self,key,event,record_begin,record_end):
        with self.lock:
            if key in self.items:raise ValueError('reused B1 event key')
            self.items[key]={'event':event,'done':threading.Event(),'record':dict(event_record_begin_ns=record_begin,event_record_end_ns=record_end,completion_lower_ns=record_begin,polls=0,query_cpu_ns=0)}
    def _loop(self):
        while not self.stop.is_set():
            with self.lock:pending=[item for item in self.items.values() if not item['done'].is_set()]
            for item in pending:
                rec=item['record'];a=time.monotonic_ns()
                try:
                    completed=item['event'].query();b=time.monotonic_ns()
                    rec['polls']+=1;rec['query_cpu_ns']+=b-a
                    if completed:
                        rec['completion_observed_ns']=b;rec['completion_uncertainty_ns']=b-rec['completion_lower_ns'];item['done'].set()
                    else:rec['completion_lower_ns']=a
                except BaseException as exc:rec['error']=repr(exc);item['done'].set()
            self.stop.wait(self.sleep_s)
    def result(self,key):
        with self.lock:item=self.items[key]
        if not item['done'].wait(1):raise RuntimeError('B1 observer missing completion after model completion')
        if 'error' in item['record']:raise RuntimeError(item['record']['error'])
        return dict(item['record'])
    def close(self):
        self.stop.set();self.thread.join(timeout=1)
        if self.thread.is_alive():raise RuntimeError('B1 observer failed to stop')
