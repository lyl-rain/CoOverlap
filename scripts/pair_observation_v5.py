"""CPU-testable completion brackets. Event instances belong to one job/generation."""
import time
class Completion:
    def __init__(self,job,generation,lower_ns,clock=time.monotonic_ns):
        if generation!=1:raise ValueError('fresh measured event must use generation1')
        self.job,self.generation,self.lower,self.upper=job,generation,lower_ns,None
        self.clock=clock;self.queries=[]
    def query(self,event,job,generation):
        if (job,generation)!=(self.job,self.generation):raise ValueError('event/job generation mismatch')
        a=self.clock()
        try:done=bool(event.query())
        except BaseException as e:
            self.queries.append(dict(begin_ns=a,end_ns=self.clock(),error=repr(e)));raise
        b=self.clock();self.queries.append(dict(begin_ns=a,end_ns=b,done=done))
        if done:self.upper=b if self.upper is None else min(self.upper,b)
        elif self.upper is not None:raise RuntimeError('completed generation became incomplete')
        else:self.lower=max(self.lower,a) # begin of FALSE query, never its end
        return done
    def state(self):
        return dict(job=self.job,generation=self.generation,lower_ns=self.lower,
            upper_ns=self.upper,status='OBSERVED' if self.upper is not None else 'INCOMPLETE',queries=self.queries)
