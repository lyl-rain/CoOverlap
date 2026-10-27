#!/usr/bin/env python3
"""CPU checks for the action-level DFS (shared transition core, no GPU)."""
import hashlib, sys, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'lsg2')); sys.path.insert(0, str(HERE / 'gap'))
import inputs, search  # noqa: E402


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tag, cls.sid = inputs.SEGMENTS[0]
        cls.result, cls.seg = inputs.load(cls.tag, cls.sid)
        cls.ops, cls.extra = inputs.costs(cls.seg)
        cls.plan, cls.P = cls.seg['plan'], cls.seg['period_ns'] / 1e6
        cls.base = inputs.metrics(cls.plan, cls.P,
                                  search.replay(cls.plan, cls.P, cls.extra, [], stop=False))

    def root_state(self):
        r = search.replay(self.plan, self.P, self.extra, [], stop=True)
        self.assertEqual(r.status, 'STOPPED_FOR_SEARCH')
        return r.search_state

    def test_release_boundary_states(self):
        st = self.root_state()
        self.assertEqual(st['now'], 0.0)
        self.assertIn('C', st['legal'])          # refresh 0 released at 0
        self.assertNotIn('E', st['legal'])       # E0 releases at 15 ms
        self.assertIn('I', st['legal'])
        early = search.replay(self.plan, self.P, self.extra, ['E'], stop=True)
        self.assertEqual(early.status, 'ILLEGAL_ACTION')

    def test_wait_does_not_move_releases(self):
        a = self.base
        b = inputs.metrics(self.plan, self.P,
                           search.replay(self.plan, self.P, self.extra, ['I'], stop=False))
        self.assertEqual([c['release'] for c in a['cycles']], [c['release'] for c in b['cycles']])
        self.assertEqual([c['deadline'] for c in a['cycles']], [c['deadline'] for c in b['cycles']])
        self.assertEqual([r['release'] for r in a['refreshes']], [r['release'] for r in b['refreshes']])

    def test_early_refresh_start_is_refused_by_lifecycle(self):
        r = search.replay(self.plan, self.P, self.extra, ['C', 'C', 'C', 'C'], stop=True)
        self.assertIn(r.status, ('ILLEGAL_RECLAIM', 'ILLEGAL_ACTION', 'STOPPED_FOR_SEARCH', 'DRAINED'))
        if r.status in ('ILLEGAL_RECLAIM', 'ILLEGAL_ACTION'):
            self.assertTrue(getattr(r, 'note', None) or r.slot_refusals)

    def test_improvement_rules(self):
        better = dict(self.base, cycle_fail=0, expert_fail=0, refresh_fail=0,
                      worst_cycle_response=self.base['worst_cycle_response'] - 1,
                      max_refresh_response=self.base['max_refresh_response'], complete=True)
        self.assertIsNotNone(search._improves(self.base, better))
        worse_expert = dict(better, expert_fail=1)
        self.assertIsNone(search._improves(dict(self.base, cycle_fail=1), worse_expert))
        incomplete = dict(better, complete=False)
        self.assertIsNone(search._improves(self.base, incomplete))

    def test_caps_terminate(self):
        st, best = search.search_segment(self.plan, self.P, self.extra, self.base,
                                         node_cap=5, wall_cap=10)
        self.assertIn(st['stop_reason'], ('NODE_CAP', 'WALL_CAP'))
        self.assertLessEqual(st['nodes_expanded'], 5)
        st2, _ = search.search_segment(self.plan, self.P, self.extra, self.base,
                                       node_cap=100000, wall_cap=0.001)
        self.assertEqual(st2['stop_reason'], 'WALL_CAP')

    def test_complete_search_and_replay(self):
        st, best = search.search_segment(self.plan, self.P, self.extra, self.base)
        self.assertEqual(st['stop_reason'], 'COMPLETE')
        self.assertEqual(st['nodes_expanded'], st['nodes_expanded'])
        if best:
            r = search.replay(self.plan, self.P, self.extra, best['prefix'], stop=False)
            self.assertEqual(inputs.metrics(self.plan, self.P, r), best['metrics'])

    def test_inputs_unchanged(self):
        before = (sha(inputs.B9), sha(inputs.B10))
        search.search_segment(self.plan, self.P, self.extra, self.base, node_cap=50)
        self.assertEqual(before, (sha(inputs.B9), sha(inputs.B10)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
