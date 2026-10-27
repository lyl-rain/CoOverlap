"""Minimum M3 adapter: reuse every frozen M2 math/copy/lifecycle operation."""
from m2_clean_backend import CleanBackend


def confirm_completion(event, row, lower, clock):
    """Actual fresh tail query; Host timestamps do not pretend to be GPU clocks."""
    row['completed'] = False
    before = clock()
    if not event.query():
        raise RuntimeError('tail Event not ready; completion cannot be fabricated')
    after = clock()
    row.update(completed=True, gpu_event_confirmed=True,
               gpu_done_observed_host_ns=after,
               gpu_completion_lower_host_ns=lower,
               gpu_completion_upper_host_ns=after,
               confirmation_query_before_host_ns=before,
               host_finalization_lower_ns=after)
    return after


class BoundaryBackend(CleanBackend):
    def finish(self, key, lower):
        row = self.d.operations[key]
        confirm_completion(self.d.events[key][7], row, lower, self.d.clock)
        # Includes completion observation, book-keeping and policy adapter cost.
        upper = self.d.clock()
        row.update(upper_ns=upper, host_finalization_upper_ns=upper)
        return lower, upper

    def stage(self, manager, handle, job):
        super().stage(manager, handle, job)
        key = job+'/stage'
        lower = self.d.wait_event(self.d.events[key][7])
        keys = [job+'/images', job+'/noise']
        self.d.complete_op(key, lower, None, keys)
        return self.finish(key, lower)

    def block(self, manager, handle, index, key):
        lower, _ = super().block(manager, handle, index, key)
        return self.finish(key, lower)

    def expert(self, manager, job, handle):
        lower, _ = super().expert(manager, job, handle)
        return self.finish(job, lower)
