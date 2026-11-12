"""Route-neutral, CPU-testable ownership and finite replay contracts.

Events must be fresh, recorded completion events supplied by the backend.
No CUDA import, allocation, scheduling policy, or model mathematics lives here.
"""
from dataclasses import dataclass, field
import math
from period_obligation_stats import classify, counts

ENCODER = tuple(range(18))
DECODER = tuple((s, i) for s in range(10) for i in range(18))
PREFIX = ('language', 'vision27', 'norm', 'project', 'bias')
BLOCKS = (PREFIX + tuple(range(9)), tuple(range(9, 18)))
# Marker names that emit an observed model call; internal fused ops emit none.
CALL_SEQUENCE = {'language': (('language',),), 'vision27': (('vision27',),),
                 'norm': (), 'project': (), 'bias': ()}
DECODER_CALLS = tuple(('decoder', s, i) for s, i in DECODER)


def expected_calls(work):
    """Ordered observed ledger calls produced by one block of declared work.

    ``work`` is the legal plan vocabulary: marker names that wrap a model call
    and integer encoder-layer indices. Fused internal ops (norm/project/bias)
    produce no separately observed call and must never become encoder ids.
    """
    calls = []
    for item in work:
        if isinstance(item, bool):
            raise ValueError('boolean work item')
        if isinstance(item, int):
            calls.append(('encoder', item))
        elif item in CALL_SEQUENCE:
            calls.extend(CALL_SEQUENCE[item])
        else:
            raise ValueError('unreviewed work item: %r' % (item,))
    return calls


class BlockPlan:
    """Ordered legal execution blocks with their published-state semantics.

    ``blocks`` is the immutable per-block work tuple; ``valid_layers`` is the
    number of effective NEW KV layers after that block (0 for a prefix-only
    block); ``shapes`` is the retained state shape of that block; ``kinds`` is
    the model-callback name; ``groups`` says which blocks form one pre-declared
    VLM obligation unit (kept at two per refresh for both plans so cycle
    obligations stay comparable).
    """
    __slots__ = ('id', 'blocks', 'valid_layers', 'shapes', 'kinds', 'groups')

    def __init__(self, id, blocks, valid_layers, shapes, kinds, groups):
        self.id = id
        self.blocks = tuple(tuple(b) for b in blocks)
        self.valid_layers = tuple(int(v) for v in valid_layers)
        self.shapes = tuple(shapes)
        self.kinds = tuple(kinds)
        self.groups = tuple(tuple(g) for g in groups)
        if not (len(self.blocks) == len(self.valid_layers) == len(self.shapes)
                == len(self.kinds) == len(self.blocks)):
            raise ValueError('block plan arrays differ')
        if any(i < 0 or i >= len(self.blocks) for g in self.groups for i in g):
            raise ValueError('block group outside plan')
        if sorted(i for g in self.groups for i in g) != list(range(len(self.blocks))):
            raise ValueError('block groups must partition the plan')
        if self.valid_layers[-1] != 18:
            raise ValueError('final block must publish all 18 effective KV layers')
        if any(b <= a for a, b in zip(self.valid_layers, self.valid_layers[1:])):
            raise ValueError('effective KV layers must increase monotonically')

    def __len__(self):
        return len(self.blocks)

    def summary(self):
        return dict(id=self.id, blocks=[list(b) for b in self.blocks],
                    valid_layers=list(self.valid_layers), shapes=list(self.shapes),
                    kinds=list(self.kinds), groups=[list(g) for g in self.groups])


DEFAULT_PLAN = BlockPlan('two_9_9', BLOCKS, (9, 18), ('mid', 'full'),
                         ('B1', 'B2'), ((0,), (1,)))


@dataclass(frozen=True)
class Snapshot:
    name: str
    image_sha: str
    wrist_sha: str
    state_sha: str
    language_sha: str
    noise_sha: str

    def __post_init__(self):
        for key in ('image_sha', 'wrist_sha', 'state_sha', 'language_sha', 'noise_sha'):
            value = getattr(self, key)
            if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('snapshot requires SHA256 for every fixed input')


@dataclass(frozen=True)
class Handle:
    slot: int
    generation: int
    version: int


@dataclass
class Version:
    handle: Handle
    snapshot: Snapshot
    phase: str = 'BUILDING'
    completed: int = 0
    pending: object = None
    fence: object = None
    readers: set = field(default_factory=set)
    valid_layers: int = 0
    block_events: dict = field(default_factory=dict)


@dataclass
class Reader:
    job: str
    handle: Handle
    noise_sha: str
    phase: str = 'BOUND'
    fence: object = None


class VersionedKV:
    """Two physical slots, monotonic logical versions, event-protected reuse.

    Decoder suffix, noise and scratch are writable: readers of one slot must
    execute serially even when the encoder prefix itself is read-only.
    A timed-out build is quarantined until its last submitted event completes.
    A bound reader already pins storage, including before any GPU submission.
    """
    def __init__(self, plan=None):
        self.plan = DEFAULT_PLAN if plan is None else plan
        self.slots = [None, None]
        self.generations = [0, 0]
        self.versions = {}
        self.readers = {}
        self.current = None
        self.next_version = 0
        self.journal = []

    def get(self, h):
        if not isinstance(h, Handle) or h.slot not in (0, 1):
            raise ValueError('invalid handle')
        v = self.slots[h.slot]
        if v is None or v.handle != h:
            raise ValueError('stale generation or reclaimed version')
        return v

    def begin(self, slot, snapshot):
        if slot not in (0, 1) or not isinstance(snapshot, Snapshot):
            raise ValueError('invalid slot/snapshot')
        if self.slots[slot] is not None:
            raise RuntimeError('slot still owned')
        h = Handle(slot, self.generations[slot] + 1, self.next_version)
        self.generations[slot] += 1
        self.next_version += 1
        v = Version(h, snapshot)
        self.slots[slot] = v
        self.versions[h.version] = h
        self.journal.append(('begin', h.version, slot, h.generation, snapshot.name))
        return h

    def check_block(self, h, index, snapshot, work):
        v = self.get(h)
        if (v.phase != 'BUILDING' or v.pending is not None or index != v.completed
                or index not in range(len(self.plan))):
            raise RuntimeError('illegal block order or unfinished boundary')
        if snapshot != v.snapshot or tuple(work) != self.plan.blocks[index]:
            raise ValueError('input mutation, repeated or omitted work')

    def submit_block(self, h, index, snapshot, work, event):
        self.check_block(h, index, snapshot, work)
        v = self.get(h)
        if not callable(getattr(event, 'query', None)):
            raise ValueError('completion event required')
        v.pending, v.fence = index, event
        v.block_events[index] = event
        self.journal.append(('block_submit', h.version, index, self.plan.valid_layers[index]))

    def poll_block(self, h):
        v = self.get(h)
        if v.phase != 'BUILDING' or v.pending is None:
            raise RuntimeError('no pending block')
        if not v.fence.query():
            return False
        v.completed += 1
        v.valid_layers = self.plan.valid_layers[v.completed - 1]
        v.pending = None
        if v.completed == len(self.plan):
            v.phase = 'READY'
        self.journal.append(('block_done', h.version, v.completed - 1, v.valid_layers, v.phase))
        return True

    def publish(self, h):
        v = self.get(h)
        if (v.phase != 'READY' or v.completed != len(self.plan) or v.pending is not None
                or not v.fence.query()):
            raise RuntimeError('partial KV or incomplete completion event')
        # A prefix-only block has 0 effective NEW KV layers; it can never publish.
        if v.valid_layers != self.plan.valid_layers[-1]:
            raise RuntimeError('effective KV layer count is not publishable: %d' % v.valid_layers)
        if set(v.block_events) != set(range(len(self.plan))):
            raise RuntimeError('missing completed block evidence')
        if self.current is not None:
            old = self.get(self.current)
            if h.version <= old.handle.version:
                raise RuntimeError('publication must be monotonic')
            old.phase = 'RETIRED'
        v.phase, self.current = 'PUBLISHED', h
        self.journal.append(('publish', h.version))

    def bind(self, job, noise_sha, version=None):
        if job in self.readers:
            raise ValueError('duplicate Expert job')
        h = self.current if version is None else self.versions.get(version)
        if h is None:
            raise RuntimeError('no published version')
        v = self.get(h)
        # Retired versions cannot acquire NEW readers. Existing tokens survive.
        if v.phase != 'PUBLISHED' or noise_sha != v.snapshot.noise_sha:
            raise RuntimeError('binding requires published KV and fixed noise')
        r = Reader(job, h, noise_sha)
        self.readers[job] = r
        v.readers.add(job)
        self.journal.append(('bind', job, h.version, v.snapshot.name))
        return h

    def check_expert(self, job, h):
        r = self.readers[job]
        v = self.get(h)
        if r.phase != 'BOUND' or r.handle != h:
            raise RuntimeError('Expert must keep one version for all 10 x 18 calls')
        for other in v.readers:
            q = self.readers[other]
            if other != job and q.phase == 'SUBMITTED' and not q.fence.query():
                raise RuntimeError('same-slot decoder scratch still in use')

    def submit_expert(self, job, h, calls, event):
        self.check_expert(job, h)
        if tuple(map(tuple, calls)) != DECODER:
            raise RuntimeError('Expert must complete exactly 10 x 18 calls')
        r = self.readers[job]
        if not callable(getattr(event, 'query', None)):
            raise ValueError('completion event required')
        r.phase, r.fence = 'SUBMITTED', event
        self.journal.append(('expert_submit', job, h.version, len(calls)))

    def poll_expert(self, job):
        r = self.readers[job]
        if r.phase != 'SUBMITTED':
            raise RuntimeError('no submitted Expert')
        if not r.fence.query():
            return False
        r.phase = 'DONE'
        self.get(r.handle).readers.remove(job)
        self.journal.append(('expert_done', job, r.handle.version))
        return True

    def cancel_unsubmitted(self, job):
        r = self.readers[job]
        if r.phase != 'BOUND':
            raise RuntimeError('submitted GPU work requires completion event')
        r.phase = 'CANCELLED'
        self.get(r.handle).readers.remove(job)
        self.journal.append(('cancel_unsubmitted', job))

    def quarantine(self, h):
        v = self.get(h)
        if v.phase not in ('BUILDING', 'READY'):
            raise RuntimeError('only unpublished builds can be abandoned')
        v.phase = 'QUARANTINED'
        self.journal.append(('quarantine', h.version))

    def reclaim(self, h):
        v = self.get(h)
        if v.phase not in ('RETIRED', 'QUARANTINED') or v.readers:
            raise RuntimeError('published/building/bound slot cannot be reused')
        # query errors propagate; an unknown/error device state never frees it.
        if v.fence is not None and not v.fence.query():
            raise RuntimeError('GPU work still owns slot')
        self.slots[h.slot] = None
        self.journal.append(('reclaim', h.version, h.slot, h.generation))


def replay_manifest(period_ns=240_000_000, cycles=8):
    if type(period_ns) is not int or period_ns <= 0 or type(cycles) is not int or cycles < 2 or cycles % 2:
        raise ValueError('positive integer P=D and finite even cycles required')
    # Deterministic consumption contract: one refresh per 2P; E2m/E2m+1
    # both use vm. No method gets a different version by finishing earlier.
    return dict(schema='m2_common_v1', period_ns=period_ns, cycles=cycles,
                experts=[dict(id=j, release_ns=j*period_ns, deadline_ns=(j+1)*period_ns,
                              version=j//2, snapshot='S0' if (j//2)%2 == 0 else 'S1',
                              steps=10, layers=18) for j in range(cycles)],
                refreshes=[dict(id=m, version=m+1, snapshot='S1' if m%2 == 0 else 'S0',
                                release_ns=2*m*period_ns, deadline_ns=(2*m+2)*period_ns,
                                units=['B1', 'B2']) for m in range(cycles//2)],
                work=dict(views=2, vision_layers=27, prompt_tokens=49, encoder_seq=561,
                          encoder_layers=18, chunk=50, steps=10, precision='BF16'),
                binding='fixed version trajectory; latest-published API tested separately')


def completion(event, record_begin_ns, clock, deadline_ns=None):
    """Conservative Host interval; query-return time alone is not GPU time."""
    lower = record_begin_ns
    while True:
        before = clock()
        if deadline_ns is not None and before >= deadline_ns:
            raise TimeoutError('completion not observed within finite wait')
        done = event.query()
        after = clock()
        if done:
            return (lower, after)
        lower = before


def replay_stats(manifest, experts, units, published, t0=0):
    """Absolute release clock, assigned obligations, including unfinished jobs.

    Inputs map job IDs to (Host lower, Host upper). Missing work is INCOMPLETE.
    No fabricated quantile for an incomplete sample and no automatic k_min.
    """
    P = manifest['period_ns']
    n = manifest['cycles']
    if set(experts)-set(range(n)) or set(units)-{(m,b) for m in range(n//2) for b in (0,1)} or set(published)-set(range(n//2)):
        raise ValueError('unexpected work IDs')
    def bounds(value, release):
        if value is None:
            return (None, None)
        lo, hi = value
        if not (isinstance(lo, int) and isinstance(hi, int) and release <= lo <= hi):
            raise ValueError('invalid completion interval')
        return lo, hi
    rows, refreshes = [], []
    for e in manifest['experts']:
        j = e['id']; rel = t0 + e['release_ns']; dl = t0 + e['deadline_ns']
        a = bounds(experts.get(j), rel)
        # A whole Context may finish the next period's B2 early.
        urel = t0 + manifest['refreshes'][j//2]['release_ns']
        b = bounds(units.get((j//2, j%2)), urel)
        pair = (max(a[0], b[0]), max(a[1], b[1])) if None not in a+b else (None, None)
        rows.append(dict(cycle=j, release_ns=rel, deadline_ns=dl,
                         expert_status=classify(*a, dl), unit_status=classify(*b, dl),
                         status=classify(*pair, dl),
                         response_lower_ns=pair[0]-rel if pair[0] is not None else None,
                         response_upper_ns=pair[1]-rel if pair[1] is not None else None,
                         W_completed_in_window=sum(1 for (m, bidx), value in units.items()
                                       if value is not None and rel < value[1] <= dl),
                         W_assigned_on_time=int(b[1] is not None and b[1]<=dl),
                         W_unit='one fixed B1 or B2; late completions retained separately'))
    for r in manifest['refreshes']:
        rel = t0+r['release_ns']; dl = t0+r['deadline_ns']
        lo, hi = bounds(published.get(r['id']), rel)
        refreshes.append(dict(id=r['id'], status=classify(lo, hi, dl),
                              ready_lower_ns=lo-rel if lo is not None else None,
                              ready_upper_ns=hi-rel if hi is not None else None,
                              k_lower=max(1,(lo-rel+P-1)//P) if lo is not None else None,
                              k_upper=max(1,(hi-rel+P-1)//P) if hi is not None else None))
    cc = counts([r['status'] for r in rows])
    cc['miss_ratio_lower'] = cc['FAIL']/cc['denominator']
    cc['miss_ratio_upper'] = (cc['denominator']-cc['PASS'])/cc['denominator']
    complete = [r['response_upper_ns'] for r in rows if r['response_upper_ns'] is not None]
    def quantile(q):
        return sorted(complete)[max(0, math.ceil(q*len(complete))-1)] if len(complete)==len(rows) else None
    return dict(cycles=rows, cycle_counts=cc, refreshes=refreshes,
                refresh_counts=counts([r['status'] for r in refreshes]),
                response_upper_p99_ns=quantile(.99), response_upper_p999_ns=quantile(.999),
                quantile_method='nearest-rank Host upper bounds; n=8 is not reliable tail evidence',
                backlog=sum(r['status']=='INCOMPLETE' for r in refreshes), k_min=None)
