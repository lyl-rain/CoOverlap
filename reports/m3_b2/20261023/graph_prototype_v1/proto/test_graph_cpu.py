#!/usr/bin/env python3
"""CPU checks for the symmetric Graph prototype (fake device; no CUDA)."""
import hashlib, sys, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'proto'))
import executor as ex, graph_backend as gb, math_backend as mb  # noqa: E402


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Conditions(unittest.TestCase):
    def test_config_drives_engine_and_policy(self):
        self.assertEqual((ex.CONDITIONS['A']['engine'], ex.CONDITIONS['A']['policy']),
                         ('eager', 'serial_context'))
        self.assertEqual((ex.CONDITIONS['D']['engine'], ex.CONDITIONS['D']['policy']),
                         ('graph', 'b2_boundary'))
        for c in ('A', 'B'):
            self.assertEqual(ex.SegmentRun(c).engine, 'eager')
        for c in ('C', 'D'):
            self.assertEqual(ex.SegmentRun(c).engine, 'graph')

    def test_same_math_outputs(self):
        a = ex.SegmentRun('A'); a.run()
        c = ex.SegmentRun('C'); c.capture(); c.run()
        self.assertEqual(a.buffers[(0, 'E10')], c.buffers[(0, 'E10')])
        self.assertEqual(a.buffers[(0, 'B1')], c.buffers[(0, 'B1')])

    def test_graph_count_and_identity(self):
        c = ex.SegmentRun('C'); c.capture()
        self.assertEqual(len(c.registry.units), 6)
        self.assertEqual(sorted(c.registry.units),
                         ['slot0_B1', 'slot0_B2', 'slot0_E10', 'slot1_B1', 'slot1_B2', 'slot1_E10'])


class Contracts(unittest.TestCase):
    def test_address_change_rejected(self):
        c = ex.SegmentRun('C'); c.capture(); c.run()
        u = c.registry.get('slot0_E10')
        bad = (bytearray(180),)
        with self.assertRaises(gb.GraphError):
            u.replay(c.device, mb.expert10, 'E0', 1, 0, bad)

    def test_generation_mismatch_rejected(self):
        c = ex.SegmentRun('C'); c.capture(); c.run()
        u = c.registry.get('slot0_E10')
        with self.assertRaises(gb.GraphError):
            u.replay(c.device, mb.expert10, 'E0', 2, 0, u.buffers)

    def test_expert_version_must_match(self):
        c = ex.SegmentRun('C'); c.capture(); c.run()
        u = c.registry.get('slot0_E10')
        u.version = 0
        with self.assertRaises(gb.GraphError):
            u.replay(c.device, mb.expert10, 'E9', 1, 1, u.buffers)

    def test_unpublished_version_cannot_bind(self):
        c = ex.SegmentRun('C'); c.capture(); c.run()
        with self.assertRaises(RuntimeError):
            c.kv.bind('E99', ex.SNAPSHOTS[0].noise_sha, version=7)

    def test_replay_coverage_requires_every_job(self):
        c = ex.SegmentRun('C'); c.capture(); c.run()
        with self.assertRaises(gb.GraphError):
            c.replay.check_complete([('E0', 'E10', 0)] + [('E99', 'E10', 0)])

    def test_duplicate_completion_rejected(self):
        c = ex.SegmentRun('C'); c.capture(); c.run()
        with self.assertRaises(gb.GraphError):
            c.replay.add(dict(graph_id='slot0_E10', job_id='E0', kind='E10', slot=0,
                              generation=1, version=0, event='COMPLETE'))

    def test_capture_unavailable_is_an_error(self):
        c = ex.SegmentRun('C')
        with self.assertRaises(gb.GraphError):
            c.run()


class Hygiene(unittest.TestCase):
    def test_no_window_d2h_and_no_workers(self):
        for cond in ('A', 'B', 'C', 'D'):
            r = ex.SegmentRun(cond)
            if cond in ('C', 'D'):
                r.capture()
            s = r.run()
            self.assertEqual(s['window_d2h'], 0)
            self.assertEqual(s['workers'], 0)
            self.assertTrue(s['persisted'])

    def test_capture_before_t0(self):
        c = ex.SegmentRun('C'); c.capture()
        self.assertTrue(c.captured_before_t0)
        c.run()
        self.assertTrue(c.captured_before_t0)

    def test_frozen_model_untouched(self):
        frozen = (HERE.parents[1] / '20261022' / 'empirical_plan_selector_v1_r1' / 'selector' / 'plan_model.py')
        self.assertEqual(sha(frozen), '2ee21ef17d6cd03eb5dc21336ad7c2b2c370544f6091b1193ff7894669552237')


if __name__ == '__main__':
    unittest.main(verbosity=2)
