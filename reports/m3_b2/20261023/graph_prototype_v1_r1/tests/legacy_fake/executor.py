"""Thin executor adapter: identical math/scheduling core for eager and graph.

Uses the frozen ``m2_executor.VersionedKV`` for versions, readers, publication and
reclaim; only the unit execution differs (direct call vs graph replay).
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DAY = HERE.parent
PREV = DAY.parent
sys.path.insert(0, str(PREV / '20261022' / 'empirical_plan_selector_v1_r1' / 'selector'))
sys.path.insert(0, str(HERE / 'proto'))

import graph_backend as gb          # noqa: E402
import math_backend as mb           # noqa: E402
from plan_model import DECODER, Fence, SNAPSHOTS, VersionedKV, TWO, THREE  # noqa: E402

CONDITIONS = {
    'A': dict(engine='eager', policy='serial_context'),
    'B': dict(engine='eager', policy='b2_boundary'),
    'C': dict(engine='graph', policy='serial_context'),
    'D': dict(engine='graph', policy='b2_boundary'),
}
PHASE_MS = 15.0
LEAD_MS = 10.0


class SegmentRun:
    def __init__(self, condition, cycles=2, period_ms=180.0):
        self.condition = condition
        self.cfg = CONDITIONS[condition]
        self.cycles = cycles
        self.period_ms = period_ms
        self.engine = self.cfg['engine']
        self.policy = self.cfg['policy']
        self.device = gb.FakeDevice()
        self.kv = VersionedKV(plan=TWO)
        self.registry = gb.GraphRegistry()
        self.replay = gb.ReplayLedger()
        self.calls = []
        self.captured_before_t0 = False
        self.t0 = None
        self.window_d2h = 0
        self.workers = 0
        self.persisted = []
        self.failures = []
        self.buffers = {(s, k): bytearray(n) for s in (0, 1)
                        for k, n in (('B1', 9), ('B2', 9), ('E10', 180))}

    # ---------------------------------------------------------------- setup
    def capture(self):
        units = {}
        for slot in (0, 1):
            units[slot] = [
                ('B1', mb.context_b1, [self.buffers[(slot, 'B1')]]),
                ('B2', mb.context_b2, [self.buffers[(slot, 'B2')]]),
                ('E10', mb.expert10, [self.buffers[(slot, 'E10')]]),
            ]
        self.registry.capture_all(units, self.device)
        for u in self.registry.units.values():
            u.generation = 1
        self.captured_before_t0 = self.t0 is None
        return self

    # ------------------------------------------------------------- execution
    def _buffers(self, slot, kind):
        if self.engine == 'graph':
            u = self.registry.get('slot%d_%s' % (slot, kind))
            return u.buffers
        return (self.buffers[(slot, kind)],)

    def _run_unit(self, slot, kind, job_id, version, fn, *args):
        if self.engine == 'eager':
            self.calls.append(dict(job_id=job_id, kind=kind, slot=slot, version=version))
            return self.device.run(fn, *args)
        unit = self.registry.get('slot%d_%s' % (slot, kind))
        unit.version = version
        entry = unit.replay(self.device, fn, job_id, unit.generation, version,
                            self._buffers(slot, kind))
        self.replay.add(dict(graph_id=unit.graph_id, job_id=job_id, kind=kind, slot=slot,
                             generation=unit.generation, version=version,
                             event='COMPLETE'))
        return entry['out']

    def run(self):
        if self.engine == 'graph' and not self.registry.units:
            raise gb.GraphError('graph engine without captured units')
        self.t0 = self.window_d2h  # symbolic t0 marker
        kv = self.kv
        h0 = kv.begin(0, SNAPSHOTS[0])
        for b in range(2):
            self._run_unit(0, 'B%d' % (b + 1), 'R0/B%d' % (b + 1), h0.version,
                           mb.context_b1 if b == 0 else mb.context_b2, self._buffers(0, 'B%d' % (b + 1))[0])
        # publish only after both blocks completed (frozen lifecycle)
        for b in range(2):
            kv.submit_block(h0, b, SNAPSHOTS[0], TWO.blocks[b], self._fence())
            kv.poll_block(h0)
        kv.publish(h0)
        self.persisted.append('R0')
        for j in range(self.cycles):
            v = j // 2
            kv.bind('E%d' % j, SNAPSHOTS[0].noise_sha, version=v)
            h = kv.readers['E%d' % j].handle
            self._run_unit(j % 2, 'E10', 'E%d' % j, v, mb.expert10,
                           self._buffers(j % 2, 'E10')[0])
            kv.submit_expert('E%d' % j, h, DECODER, self._fence())
            kv.poll_expert('E%d' % j)
        return self.summary()

    def _fence(self):
        f = Fence()
        f.done = True
        return f

    # ---------------------------------------------------------------- checks
    def summary(self):
        return dict(condition=self.condition, engine=self.engine, policy=self.policy,
                    cycles=self.cycles, period_ms=self.period_ms,
                    graphs=sorted(self.registry.units), replay_entries=len(self.replay.entries),
                    eager_calls=len(self.calls), captured_before_t0=self.captured_before_t0,
                    workers=self.workers, window_d2h=self.window_d2h,
                    persisted=self.persisted, failures=self.failures)

    def check_replay_coverage(self, expected_jobs):
        return self.replay.check_complete(expected_jobs)


def expected_jobs(cycles=2):
    out = [('R0/B1', 'B1', 0), ('R0/B2', 'B2', 0)]
    out += [('E%d' % j, 'E10', j % 2) for j in range(cycles)]
    return out
