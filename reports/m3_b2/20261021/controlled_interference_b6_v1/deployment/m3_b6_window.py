"""b6 per-segment window coordinator built on the accepted r1 lifecycle.

This is a thin adapter: it owns no second state machine and no file writer.  It
takes the single t0 from the shared driver, prepares the r1 worker before that
instant, waits for the pre-declared start, and after replay finishes waits for
the fixed worker_end / confirms exit / releases resources.  The caller performs
D2H, comparisons, writes and bank reuse only after `finish()` returns.
"""
from m3_interference_lifecycle import (
    InterferenceConfig,
    InterferenceController,
    SystemClock,
    WindowPlan,
)
from m3_b6_plan import (
    CYCLES,
    DRAIN_NS,
    LEAD_NS,
    NOMINAL_NS,
    PERIOD_NS,
    PHASE_NS,
    WORKER_END_NS,
)

READY_TIMEOUT_NS = 3_000_000_000
READY_MARGIN_NS = 10_000_000
MODES = {'quiet': 'quiet', 'fixed_cpu_mem': 'fixed'}


class SegmentWindow:
    def __init__(self, mode, *, clock=None, controller_factory=None, config=None):
        if mode not in MODES:
            raise ValueError('unreviewed interference mode: %r' % (mode,))
        self.mode = mode
        self.worker_mode = MODES[mode]
        self.clock = clock or SystemClock()
        self.controller_factory = controller_factory or self._default_controller
        self.config = config or InterferenceConfig(
            mode=self.worker_mode,
            ready_timeout_ns=READY_TIMEOUT_NS,
            ready_margin_ns=READY_MARGIN_NS,
        )
        if self.config.mode != self.worker_mode:
            raise ValueError('controller config mode mismatch')
        self.plan = None
        self.controller = None
        self.opened = False
        self.started = False
        self.finished = False
        self.aborted = False
        self.prepare_error = None
        self.start_observed_ns = None
        self.start_lateness_ns = None
        self.result = None

    def _default_controller(self, plan, config):
        return InterferenceController(config, clock=self.clock)

    def open(self, now_ns, conf):
        """Determine the ONE t0 and make the worker ready before it."""
        if self.opened:
            raise RuntimeError('window may be opened exactly once')
        if int(conf['period_ns']) != PERIOD_NS or int(conf['cycles']) != CYCLES:
            raise ValueError('b6 window requires 8 cycles at 180 ms')
        if int(conf.get('phase_ns', PHASE_NS)) != PHASE_NS:
            raise ValueError('b6 Expert phase changed')
        if int(conf['period_ns']) * int(conf['cycles']) != NOMINAL_NS:
            raise ValueError('manifest nominal window differs from the declared b6 window')
        self.t0_ns = int(now_ns) + LEAD_NS
        self.plan = WindowPlan.from_replay_t0(self.t0_ns, NOMINAL_NS, DRAIN_NS)
        self.opened = True
        self.controller = self.controller_factory(self.plan, self.config)
        try:
            self.controller.prepare(self.plan)
        except BaseException as exc:
            self.prepare_error = repr(exc)
            try:
                self.controller.close()
            finally:
                self.aborted = True
            raise
        self.prepared_ns = self.clock.monotonic_ns()
        self.worker_count = 0 if self.worker_mode == 'quiet' else 1
        return self.t0_ns

    def await_start(self):
        if not self.opened or self.prepare_error is not None or self.aborted:
            raise RuntimeError('window is not prepared')
        self.controller.await_start()
        self.started = True
        self.start_observed_ns = self.clock.monotonic_ns()
        self.start_lateness_ns = max(0, self.start_observed_ns - self.plan.start_ns)
        return self.start_observed_ns

    def _window_ok(self, evidence):
        if self.worker_mode == 'quiet':
            return bool(evidence.get('status') == 'QUIET_COMPLETE'
                        and evidence.get('window_complete') is True
                        and (evidence.get('resource_release') or {}).get(
                            'resources_released') is True)
        final = evidence.get('worker_final') or {}
        release = evidence.get('resource_release') or {}
        return bool(
            evidence.get('status') == 'WINDOW_COMPLETE'
            and final.get('copies', 0) > 0
            and final.get('work_valid') is True
            and final.get('window_coverage_complete') is True
            and final.get('guards') == 'PASS'
            and release.get('process_exit_confirmed') is True
            and release.get('resources_released') is True)

    def finish(self, replay_end_ns, replay_status=None, replay_error=None):
        """Wait to the fixed worker_end, release resources, and evaluate coverage."""
        if self.finished:
            return self.result
        if self.aborted:
            return self._aborted_result('already_aborted')
        if not self.opened or self.controller is None:
            return self._aborted_result('window_not_opened')
        finish_call_ns = self.clock.monotonic_ns()
        finish_error = None
        try:
            self.controller.finish()
        except BaseException as exc:
            finish_error = repr(exc)
        try:
            self.controller.close()
        except BaseException as exc:
            if finish_error is None:
                finish_error = repr(exc)
            else:
                finish_error += '; close: ' + repr(exc)
        forced_wait_ns = 0
        if finish_error is not None and self.plan is not None:
            # The controller failed before it could wait/confirm the fixed end.
            # Do not let post-window D2H/writes start before worker_end; this
            # waits but never extends pressure or moves the declared window.
            while self.clock.monotonic_ns() < self.plan.end_ns:
                remaining = self.plan.end_ns - self.clock.monotonic_ns()
                step = min(remaining, 1_000_000)
                self.clock.sleep_ns(step)
                forced_wait_ns += step
        worker_end_observed_ns = self.clock.monotonic_ns()
        evidence = self.controller.evidence
        release = evidence.get('resource_release') or {}
        replay_overrun = (replay_end_ns is not None
                          and int(replay_end_ns) > self.plan.end_ns)
        reasons = []
        if replay_error is not None:
            reasons.append('replay_error')
        if replay_status != 'DRAINED_PENDING_VALIDATION':
            reasons.append('replay_status_not_drained')
        if replay_end_ns is None:
            reasons.append('replay_end_missing')
        if replay_overrun:
            reasons.append('replay_overran_worker_end')
        if finish_error is not None:
            reasons.append('worker_finish_error')
        if not self._window_ok(evidence):
            reasons.append('worker_window_not_valid')
        if self.worker_mode == 'quiet' and evidence.get('quiet_no_worker') is not True:
            reasons.append('quiet_created_worker')
        condition_valid = not reasons
        self.result = dict(
            mode=self.mode,
            worker_mode=self.worker_mode,
            plan=self.plan.as_dict(),
            t0_ns=self.plan.start_ns,
            nominal_end_ns=self.plan.nominal_end_ns,
            worker_end_ns=self.plan.end_ns,
            nominal_ns=NOMINAL_NS,
            drain_ns=DRAIN_NS,
            lead_ns=LEAD_NS,
            worker_count=getattr(self, 'worker_count', 0),
            prepared_ns=getattr(self, 'prepared_ns', None),
            start_observed_ns=self.start_observed_ns,
            start_lateness_ns=self.start_lateness_ns,
            replay_end_ns=replay_end_ns,
            replay_status=replay_status,
            replay_error=replay_error,
            replay_overran_worker_end=bool(replay_overrun),
            finish_call_ns=finish_call_ns,
            worker_end_observed_ns=worker_end_observed_ns,
            finish_error=finish_error,
            forced_wait_to_worker_end_ns=forced_wait_ns,
            condition_valid=condition_valid,
            condition_failure_reasons=reasons,
            worker_evidence=evidence,
            resource_release=release,
            coverage=dict(
                replay_starts_at_t0=True,
                replay_end_le_worker_end=not replay_overrun,
                worker_window_complete=bool(self._window_ok(evidence)),
                positive_copies=(evidence.get('worker_final') or {}).get('copies', 0) > 0,
                interpretation='positive copies prove work occurred, not continuous bandwidth; '
                               'copy_bytes is logical memmove traffic, not DRAM bandwidth',
            ),
            no_window_extension=True,
        )
        self.finished = True
        return self.result

    def _aborted_result(self, reason):
        if self.result is not None:
            return self.result
        evidence = None
        if self.controller is not None:
            try:
                evidence = self.controller.evidence
            except BaseException:
                evidence = None
        self.result = dict(
            mode=self.mode, worker_mode=self.worker_mode,
            plan=None if self.plan is None else self.plan.as_dict(),
            t0_ns=None if self.plan is None else self.plan.start_ns,
            nominal_end_ns=None if self.plan is None else self.plan.nominal_end_ns,
            worker_end_ns=None if self.plan is None else self.plan.end_ns,
            worker_count=int(((evidence or {}).get('counts') or {}).get('workers_spawned', 0)),
            condition_valid=False,
            condition_failure_reasons=[reason],
            aborted=True,
            abort_reason=reason,
            worker_evidence=evidence,
            resource_release=(evidence or {}).get('resource_release'),
            coverage=dict(replay_starts_at_t0=False, replay_end_le_worker_end=None,
                          worker_window_complete=False, positive_copies=False,
                          interpretation='worker open/start failed; no valid replay window'),
            no_window_extension=True,
        )
        self.finished = True
        return self.result

    def annotate_record(self, record):
        """Mark operations/cycles/refreshes outside the fixed worker window.

        Called after finish() and before D2H/write.  It only reads in-memory
        replay maps; it does not alter release, deadline or response values.
        """
        if self.plan is None or self.result is None:
            return None
        end = self.plan.end_ns
        t0 = self.plan.start_ns
        def pair(v):
            return (int(v[0]), int(v[1])) if isinstance(v, (list, tuple)) else None
        late_experts, late_blocks, late_units, late_published = [], [], [], []
        for key, value in (record.get('experts') or {}).items():
            p = pair(value)
            if p and p[1] > end:
                late_experts.append('E%s' % key)
        for key, value in (record.get('blocks') or {}).items():
            p = pair(value)
            if p and p[1] > end:
                if isinstance(key, (list, tuple)) and len(key) == 2:
                    late_blocks.append('R%d/B%d' % (int(key[0]), int(key[1]) + 1))
                else:
                    late_blocks.append('block:%s' % (key,))
        for key, value in (record.get('units') or {}).items():
            p = pair(value)
            if p and p[1] > end:
                late_units.append('unit:%s' % (key,))
        for key, value in (record.get('published') or {}).items():
            p = pair(value)
            if p and p[1] > end:
                late_published.append('R%s' % key)
        late_cycles = []
        for row in ((record.get('statistics') or {}).get('cycles') or []):
            response = row.get('response_upper_ns')
            if response is not None and row.get('release_ns') is not None:
                if row['release_ns'] + response > end:
                    late_cycles.append(row.get('cycle'))
        late_releases = []
        for e in ((record.get('manifest') or {}).get('experts') or []):
            if t0 + int(e['release_ns']) > end:
                late_releases.append('E%s@%d' % (e['id'], t0 + int(e['release_ns'])))
        for r in ((record.get('manifest') or {}).get('refreshes') or []):
            if t0 + int(r['release_ns']) > end:
                late_releases.append('R%s@%d' % (r['id'], t0 + int(r['release_ns'])))
        detail = dict(
            worker_end_ns=end,
            late_experts=late_experts, late_blocks=late_blocks,
            late_units=late_units, late_published=late_published,
            late_cycles=late_cycles, releases_after_worker_end=late_releases,
            any_late=bool(late_experts or late_blocks or late_units
                          or late_published or late_cycles),
        )
        self.result.setdefault('coverage', {})['late'] = detail
        self.result['coverage']['replay_end_le_worker_end'] = (
            (self.result.get('replay_end_ns') is not None)
            and int(self.result['replay_end_ns']) <= end)
        if detail['any_late']:
            self.result['condition_valid'] = False
            reasons = self.result.setdefault('condition_failure_reasons', [])
            if 'operations_after_worker_end' not in reasons:
                reasons.append('operations_after_worker_end')
        return detail

    def abort(self, reason):
        if self.finished:
            return self.result
        self.aborted = True
        if self.controller is not None:
            try:
                self.controller.abort(reason)
            except BaseException:
                pass
            try:
                self.controller.close()
            except BaseException:
                pass
        return self._aborted_result(reason)
