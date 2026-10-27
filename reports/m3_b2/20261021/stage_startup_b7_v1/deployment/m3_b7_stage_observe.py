"""Fixed-capacity Host-only observation for the B7 stage call.

The observer only stamps the stage entry/exit and the named calls around the
existing stage sequence.  It performs no CUDA call, no synchronization, no
D2H, no comparison and no file/JSON write.  Event/poll evidence is kept as
aggregate counts; polling iterations are never logged individually.
"""
import time

TIMESTAMP_NAMES = (
    'stage_enter',
    'event0_before', 'event0_after',
    'event1_before', 'event1_after',
    'restore_images_before', 'restore_images_after',
    'restore_noise_before', 'restore_noise_after',
    'capture_images_before', 'capture_images_after',
    'capture_noise_before', 'capture_noise_after',
    'event2_before', 'event2_after',
    'event7_before', 'event7_after',
    'event7_wait_before', 'event7_wait_after',
    'confirmation_before', 'confirmation_after',
    'stage_exit',
)


class StageObservation:
    """Preallocated 22-slot Host observation for exactly one stage."""

    def __init__(self, clock=None, segment_id=None, stage_index=None):
        self.clock = clock or time.monotonic_ns
        self.segment_id = segment_id
        self.stage_index = stage_index
        self.slots = [None] * len(TIMESTAMP_NAMES)
        self.index = {name: i for i, name in enumerate(TIMESTAMP_NAMES)}
        self.seen = set()
        self.counts = {'event7_polls': 0, 'event_records': 0,
                       'restore_calls': 0, 'capture_calls': 0,
                       'confirmation_calls': 0}

    def _stamp(self, name):
        if name not in self.index:
            raise ValueError('unreviewed stage timestamp: ' + name)
        if name in self.seen:
            raise RuntimeError('duplicate stage timestamp: ' + name)
        self.seen.add(name)
        self.slots[self.index[name]] = int(self.clock())

    def stage_enter(self):
        self._stamp('stage_enter')

    def stage_exit(self):
        self._stamp('stage_exit')

    def event_before(self, key, index):
        if int(index) not in (0, 1, 2, 7):
            raise ValueError('unreviewed Event index: %r' % (index,))
        self.counts['event_records'] += 1
        self._stamp('event%d_before' % int(index))

    def event_after(self, key, index):
        self._stamp('event%d_after' % int(index))

    def restore_before(self, kind):
        if kind not in ('images', 'noise'):
            raise ValueError('unreviewed restore input: ' + kind)
        self.counts['restore_calls'] += 1
        self._stamp('restore_%s_before' % kind)

    def restore_after(self, kind):
        self._stamp('restore_%s_after' % kind)

    def capture_before(self, kind):
        if kind not in ('images', 'noise'):
            raise ValueError('unreviewed capture input: ' + kind)
        self.counts['capture_calls'] += 1
        self._stamp('capture_%s_before' % kind)

    def capture_after(self, kind):
        self._stamp('capture_%s_after' % kind)

    def event7_wait_before(self):
        self._stamp('event7_wait_before')

    def event7_wait_after(self, polls):
        self.counts['event7_polls'] = int(polls)
        self._stamp('event7_wait_after')

    def confirmation_before(self):
        self.counts['confirmation_calls'] += 1
        self._stamp('confirmation_before')

    def confirmation_after(self):
        self._stamp('confirmation_after')

    def snapshot(self):
        timestamps = {name: self.slots[i] for i, name in enumerate(TIMESTAMP_NAMES)}
        missing = [name for name, value in timestamps.items() if value is None]
        return dict(schema='m3_b7_stage_observation_v1', segment_id=self.segment_id,
                    stage_index=self.stage_index, timestamps=timestamps, counts=dict(self.counts),
                    complete=not missing, missing=missing,
                    note='Host stamps only; no GPU operation or synchronization was added')


class SegmentStageObservation:
    """Preallocate four stage records (one per refresh) for one segment.

    The stage path is called four times per segment (R0..R3).  This collector
    creates and preallocates the four StageObservation records at construction,
    selects the next one on stage_enter, and finalizes it on stage_exit.  It adds
    no CUDA operation, synchronization, D2H, serialization or per-poll log.
    """

    def __init__(self, clock=None, segment_id=None, stages=4):
        self.clock = clock or time.monotonic_ns
        self.segment_id = segment_id
        self.capacity = int(stages)
        self.records = [StageObservation(clock=self.clock, segment_id=segment_id,
                                         stage_index=i)
                        for i in range(self.capacity)]
        self.next_index = 0
        self.current = None

    def _obs(self):
        if self.current is None:
            raise RuntimeError('stage observer method called outside a stage')
        return self.current

    def stage_enter(self):
        if self.current is not None:
            raise RuntimeError('previous stage has no exit')
        if self.next_index >= self.capacity:
            raise RuntimeError('stage observation capacity exceeded')
        self.current = self.records[self.next_index]
        self.current.stage_enter()

    def stage_exit(self):
        obs = self._obs()
        obs.stage_exit()
        self.current = None
        self.next_index += 1

    def event_before(self, key, index):
        self._obs().event_before(key, index)

    def event_after(self, key, index):
        self._obs().event_after(key, index)

    def restore_before(self, kind):
        self._obs().restore_before(kind)

    def restore_after(self, kind):
        self._obs().restore_after(kind)

    def capture_before(self, kind):
        self._obs().capture_before(kind)

    def capture_after(self, kind):
        self._obs().capture_after(kind)

    def event7_wait_before(self):
        self._obs().event7_wait_before()

    def event7_wait_after(self, polls):
        self._obs().event7_wait_after(polls)

    def confirmation_before(self):
        self._obs().confirmation_before()

    def confirmation_after(self):
        self._obs().confirmation_after()

    def snapshot(self):
        stages = [obs.snapshot() for obs in self.records]
        counts = {k: sum(int(obs.counts.get(k, 0)) for obs in self.records)
                  for k in ('event7_polls', 'event_records', 'restore_calls',
                            'capture_calls', 'confirmation_calls')}
        return dict(schema='m3_b7_segment_stage_observation_v1',
                    segment_id=self.segment_id, stages=stages,
                    stage_count=len(stages), counts=counts,
                    complete=all(s['complete'] for s in stages),
                    missing=[s['stage_index'] for s in stages if not s['complete']],
                    note='Host stamps only; four preallocated stage records per segment')
