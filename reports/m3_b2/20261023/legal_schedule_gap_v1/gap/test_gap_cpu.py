#!/usr/bin/env python3
"""CPU checks for the legal-schedule gap analysis (no GPU)."""
import sys, unittest
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'gap'))
import importlib.util, inputs
spec=importlib.util.spec_from_file_location('gap_run', HERE/'gap'/'run.py')
run_mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(run_mod)

class Base(unittest.TestCase):
    def setUp(self):
        tag, sid = inputs.SEGMENTS[0]
        self.tag, self.sid = tag, sid
        self.result, self.seg = inputs.load(tag, sid)
        self.ops, self.extra = inputs.costs(self.seg)
        self.P = self.seg['period_ns'] / 1e6

    def test_cost_identity_per_operation(self):
        self.assertEqual(len(self.ops), 20)
        self.assertEqual(set(k[0] for k in self.ops), {'Expert', 'block', 'stage'})

    def test_baseline_drains_and_completes(self):
        m = inputs.metrics(self.seg['plan'], self.P, inputs.run(self.seg['plan'], self.P, self.extra))
        self.assertEqual(m['status'], 'DRAINED')
        self.assertTrue(m['complete'])
        self.assertEqual(len(m['cycles']), 8)
        self.assertEqual(len(m['refreshes']), 4)

    def test_release_never_earlier_than_declared(self):
        m = inputs.metrics(self.seg['plan'], self.P, inputs.run(self.seg['plan'], self.P, self.extra))
        for c in m['cycles']:
            self.assertAlmostEqual(c['release'], c['cycle'] * self.P + 15.0, places=6)
            self.assertAlmostEqual(c['deadline'], c['release'] + self.P, places=6)

    def test_wait_policy_does_not_move_releases(self):
        a = inputs.metrics(self.seg['plan'], self.P, inputs.run(self.seg['plan'], self.P, self.extra))
        b = inputs.metrics(self.seg['plan'], self.P, inputs.run(
            self.seg['plan'], self.P, self.extra, tail_rule='delay_to_next_release'))
        self.assertEqual([c['release'] for c in a['cycles']], [c['release'] for c in b['cycles']])
        self.assertEqual([c['deadline'] for c in a['cycles']], [c['deadline'] for c in b['cycles']])
        self.assertEqual([r['release'] for r in a['refreshes']], [r['release'] for r in b['refreshes']])

    def test_no_policy_improves_on_this_segment(self):
        base = inputs.metrics(self.seg['plan'], self.P, inputs.run(self.seg['plan'], self.P, self.extra))
        for pol in ('P1_context_first', 'P2_delay_tail', 'P3_context_first_delay'):
            m = inputs.metrics(self.seg['plan'], self.P, inputs.run(self.seg['plan'], self.P, self.extra,
                                                                   **run_mod.POLICIES[pol]))
            self.assertIsNone(run_mod.improves(base, m), pol)

    def test_coverage_is_explicit_about_missing_dfs(self):
        import json
        cov = json.loads((HERE / 'outputs' / 'SEARCH_COVERAGE.json').read_text())
        self.assertEqual(cov['action_level_dfs'], 'NOT_IMPLEMENTED')
        self.assertEqual(cov['node_cap'], 100000)
        self.assertEqual(cov['wall_cap_s'], 10)

if __name__ == '__main__':
    unittest.main(verbosity=2)
