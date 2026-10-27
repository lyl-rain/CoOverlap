"""Minimal symmetric CUDA-Graph backend abstraction (CPU fake device only).

The Graph unit is a thin wrapper around the *same* math callable the eager path
calls.  Capture (on GPU) would be ``torch.cuda.CUDAGraph`` around that callable
with address-stable buffers; on CPU we only model the identity, buffer-address,
generation and version contracts, never a real capture.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

UNITS = ('B1', 'B2', 'E10')
MAX_GRAPHS = 6


class GraphError(RuntimeError):
    pass


class FakeDevice:
    """CPU stand-in for the CUDA boundary; records every math call."""

    def __init__(self):
        self.calls = []
        self.clock_ms = 0.0

    def run(self, fn, *args, cost_ms=0.0):
        self.calls.append(dict(fn=getattr(fn, '__name__', repr(fn)),
                               nargs=len(args)))
        self.clock_ms += cost_ms
        return fn(*args)


@dataclass
class GraphUnit:
    graph_id: str
    slot: int
    kind: str
    buffers: tuple
    calls: list = field(default_factory=list)
    generation: int = 0
    version: int | None = None
    captured: bool = False

    def address_key(self):
        return tuple(id(b) for b in self.buffers)

    def capture(self):
        if self.captured:
            raise GraphError('graph captured twice: %s' % self.graph_id)
        self.calls = []
        self.captured = True
        return self

    def record_capture(self, fn, *shapes):
        self.calls.append(dict(fn=getattr(fn, '__name__', repr(fn)), shapes=list(shapes)))

    def replay(self, device, fn, job_id, generation, version, buffers):
        if not self.captured:
            raise GraphError('graph not captured: %s' % self.graph_id)
        if tuple(id(b) for b in buffers) != self.address_key():
            raise GraphError('graph %s buffer address changed' % self.graph_id)
        if generation != self.generation:
            raise GraphError('graph %s generation mismatch %r != %r'
                             % (self.graph_id, generation, self.generation))
        if self.version is not None and version != self.version:
            raise GraphError('graph %s version %r != bound %r'
                             % (self.graph_id, version, self.version))
        out = device.run(fn, *buffers)
        return dict(graph_id=self.graph_id, job_id=job_id, slot=self.slot, kind=self.kind,
                    generation=generation, version=version, out=out)


class GraphRegistry:
    def __init__(self, max_graphs=MAX_GRAPHS):
        self.max_graphs = max_graphs
        self.units = {}
        self.device_calls = []

    def add(self, unit: GraphUnit):
        if len(self.units) >= self.max_graphs:
            raise GraphError('graph count exceeds %d' % self.max_graphs)
        if unit.graph_id in self.units:
            raise GraphError('duplicate graph id %s' % unit.graph_id)
        self.units[unit.graph_id] = unit
        return unit

    def get(self, graph_id):
        if graph_id not in self.units:
            raise GraphError('unknown graph %s' % graph_id)
        return self.units[graph_id]

    def capture_all(self, slot_units, device):
        for slot, units in slot_units.items():
            for kind, fn, buffers in units:
                u = GraphUnit('slot%d_%s' % (slot, kind), slot, kind, tuple(buffers))
                u.capture()
                u.record_capture(fn, len(buffers[0]))
                u.generation = 1
                self.add(u)
        return self


class ReplayLedger:
    """Runtime ledger for graph replays; never reuses the eager CallLedger."""

    def __init__(self):
        self.entries = []
        self.completed = set()

    def add(self, entry):
        job = (entry['graph_id'], entry['job_id'])
        if job in self.completed:
            raise GraphError('duplicate completion for %s/%s' % job)
        self.completed.add(job)
        self.entries.append(entry)

    def check_complete(self, expected_jobs):
        got = {(e['job_id'], e['kind'], e['slot'], e['generation'], e['version'])
               for e in self.entries}
        missing = [j for j in expected_jobs if j not in got]
        if missing:
            raise GraphError('missing replays: %r' % (missing,))
        return True

    def to_json(self):
        return json.dumps(self.entries, sort_keys=True, default=str)
