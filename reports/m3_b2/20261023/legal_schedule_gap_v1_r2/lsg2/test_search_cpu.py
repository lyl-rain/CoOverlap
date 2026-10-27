#!/usr/bin/env python3
"""CPU-only regressions of the actual shared transition and search core."""
from __future__ import annotations
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE / 'gap'), str(HERE / 'lsg2')]
import inputs
import search
import core as selector_core


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tag, cls.sid = inputs.SEGMENTS[0]
        _, cls.seg = inputs.load(cls.tag, cls.sid)
        _, cls.extra = inputs.costs(cls.seg)
        cls.plan, cls.P = cls.seg['plan'], cls.seg['period_ns'] / 1e6
        cls.base = inputs.metrics(cls.plan, cls.P, search.replay(cls.plan, cls.P, cls.extra, [], False))

    def replay(self, prefix, stop=True):
        return search.replay(self.plan, self.P, self.extra, prefix, stop)

    def test_real_collision_keeps_distinct_objective_histories(self):
        p1 = ['I'] * 11 + ['C', 'C', 'C']
        p2 = ['I'] * 11 + ['C', 'C', 'E', 'C']
        a, b = self.replay(p1), self.replay(p2)
        self.assertEqual(a.status, 'STOPPED_FOR_SEARCH')
        self.assertEqual(b.status, 'STOPPED_FOR_SEARCH')
        self.assertEqual(search.legacy_state_key(a.search_state), search.legacy_state_key(b.search_state))
        ma, mb = [inputs.metrics(self.plan, self.P, r) for r in (a, b)]
        self.assertLess(mb['worst_cycle_response'], ma['worst_cycle_response'])
        self.assertNotEqual(a.exact_times['experts'], b.exact_times['experts'])

    def test_search_never_calls_unsafe_key(self):
        with patch.object(search, 'legacy_state_key', side_effect=AssertionError('unsafe dedup')):
            stats, _ = search.search_segment(self.plan, self.P, self.extra, self.base, node_cap=25)
        self.assertEqual(stats['pruned_nodes'], 0)
        self.assertEqual(stats['memoization'], 'DISABLED')

    def test_no_hook_matches_frozen_events_stats_and_lifecycle(self):
        for plan in search.plan_model.PLANS.values():
            for period in (140, 160):
                a = selector_core.hooked.simulate(plan, period=period)
                b = search.core.simulate(plan, period=period)
                for field in ('events', 'cycles', 'refreshes', 'journal', 'status', 'deferred', 'slot_refusals'):
                    self.assertEqual(getattr(a, field), getattr(b, field), (plan.name, period, field))

    def test_instance_cost_matches_frozen_default(self):
        old = selector_core.hooked.simulate(search.plan_model.PLANS[self.plan], period=self.P,
                expert=1e-6, stage_first=1e-6, stage_later=1e-6,
                gap=0.041, publish_cost=0.012, extra_ms=lambda k:self.extra.get(k, 0))
        new = self.replay([], False)
        for field in ('events', 'cycles', 'refreshes', 'journal', 'status'):
            self.assertEqual(getattr(old, field), getattr(new, field), field)

    def test_release_before_equal_after(self):
        root = self.replay([])
        self.assertNotIn('E', root.search_state['legal'])
        self.assertEqual(self.replay(['E']).status, 'ILLEGAL_ACTION')
        for when, allowed in [(14.9999, False), (15.0, True), (15.0001, True)]:
            extra = dict(self.extra, **{})
            extra[('stage', 0)] = when - 1e-6
            r = search.replay(self.plan, self.P, extra, ['C'], True)
            self.assertEqual('E' in r.search_state['legal'], allowed)

    def test_wait_preserves_all_arrivals_and_deadlines(self):
        later = inputs.metrics(self.plan, self.P, self.replay(['I'], False))
        for kind in ('cycles', 'refreshes'):
            for a, b in zip(self.base[kind], later[kind]):
                self.assertEqual((a['release'], a['deadline']), (b['release'], b['deadline']))

    def test_mixed_actions_replay_and_context_progress(self):
        r = self.replay(['C', 'C', 'E', 'C'], False)
        self.assertEqual(r.status, 'DRAINED')
        self.assertEqual([e['kind'] for e in r.events[:4]], ['stage', 'block', 'Expert', 'block'])
        self.assertEqual([e['version'] for e in r.events if e['kind']=='Expert'], [j//2 for j in range(8)])
        self.assertEqual([e['refresh'] for e in r.events if e['kind']=='publish'], list(range(4)))

    def test_reader_protection_is_actually_rejected(self):
        r = search.core.simulate(search.plan_model.PLANS[self.plan], hold_expert=0)
        self.assertEqual(r.status, 'ILLEGAL_RECLAIM')
        self.assertTrue(r.slot_refusals)
        self.assertIn('E0', r.slot_refusals[0]['readers'])

    def test_small_tree_matches_independent_recursive_enumeration(self):
        # Small fixture: one refresh, two Experts. Independent tree traversal,
        # same legal transition core, no memoization on either side.
        cycles, P = 2, 160
        root = search.replay(self.plan, P, self.extra, [], False, cycles=cycles)
        base = inputs.metrics(self.plan, P, root)
        totals = dict(nodes=0, terminal=0, invalid=0, branches=0, improving=0)
        best = [None]
        def visit(prefix):
            r = search.replay(self.plan, P, self.extra, prefix, True, cycles=cycles)
            if r.status == 'STOPPED_FOR_SEARCH':
                totals['nodes'] += 1
                for a in r.search_state['legal']:
                    totals['branches'] += 1
                    visit(prefix + [a])
            elif r.status == 'DRAINED':
                totals['terminal'] += 1
                m = inputs.metrics(self.plan, P, r)
                v = search._improves(base, m)
                if v:
                    totals['improving'] += 1
                    c = dict(prefix=prefix, verdict=v, metrics=m)
                    if best[0] is None or search._better(c, best[0]):best[0]=c
            else:totals['invalid'] += 1
        visit([])
        st, found = search.search_segment(self.plan, P, self.extra, base, cycles=cycles)
        self.assertEqual(st['stop_reason'], 'COMPLETE')
        self.assertEqual((st['nodes_expanded'], st['terminal_schedules'], st['invalid_branches'], st['branches_generated'], st['improvement_schedules']),
                         (totals['nodes'], totals['terminal'], totals['invalid'], totals['branches'], totals['improving']))
        self.assertEqual(found, best[0])
        self.assertGreater(st['terminal_schedules'], 1)

    def test_rule_b_rejects_refresh_failures(self):
        base = dict(self.base, cycle_fail=0, expert_fail=0, refresh_fail=0)
        c = dict(base, complete=True, worst_cycle_response=base['worst_cycle_response']-1, refresh_fail=1)
        self.assertIsNone(search._improves(base,c))

    def test_improvement_a_and_tradeoffs(self):
        base = dict(self.base, cycle_fail=2, expert_fail=0, refresh_fail=0)
        c = dict(base, cycle_fail=1, complete=True)
        self.assertEqual(search._improves(base,c), 'A')
        for change in [dict(expert_fail=1), dict(refresh_fail=1), dict(complete=False)]:
            self.assertIsNone(search._improves(base,dict(c,**change)))

    def test_improvement_b_positive_and_no_strict_change(self):
        b = dict(self.base, cycle_fail=0, expert_fail=0, refresh_fail=0, complete=True)
        self.assertIsNone(search._improves(b,b))
        c = dict(b,worst_cycle_response=b['worst_cycle_response']-0.1)
        self.assertEqual(search._improves(b,c),'B')
        self.assertIsNone(search._improves(b,dict(c,max_refresh_response=b['max_refresh_response']+1)))

    def test_node_cap_and_pending_work(self):
        st,_ = search.search_segment(self.plan,self.P,self.extra,self.base,node_cap=5)
        self.assertEqual(st['stop_reason'],'NODE_CAP')
        self.assertEqual(st['nodes_expanded'],5)
        self.assertGreater(st['pending_prefixes'],0)

    def test_deadline_checked_inside_replay(self):
        calls = [0]
        def clock():
            calls[0]+=1
            return calls[0]*0.001
        st,_=search.search_segment(self.plan,self.P,self.extra,self.base,wall_cap=0.005,clock=clock)
        self.assertEqual(st['stop_reason'],'WALL_CAP')
        self.assertEqual(st['interrupted_replays'],1)
        self.assertGreater(st['pending_prefixes'],0)

    def test_all_terminal_replays_evaluated_without_default_tail(self):
        trace,status = search.default_action_trace(self.plan,self.P,self.extra)
        self.assertEqual(status,'DRAINED')
        r=search.replay(self.plan,self.P,self.extra,trace,True)
        self.assertEqual(r.status,'DRAINED')
        self.assertEqual(inputs.metrics(self.plan,self.P,r), self.base)

    def test_exact_times_not_display_rounding_control_classification(self):
        r=self.replay([],False)
        # A 0.0001 ms miss is rounded to exactly the deadline in display events.
        dl=self.P+15
        r.exact_times['experts'][0]=dl+0.0001
        event=next(e for e in r.events if e['kind']=='Expert' and e['id']==0)
        event['end']=round(dl+0.0001,3)
        m=inputs.metrics(self.plan,self.P,r)
        self.assertEqual(m['cycles'][0]['status'],'FAIL')
        self.assertLess(m['cycles'][0]['expert_margin'],0)

    def test_missing_tail_publication_does_not_fabricate_zero(self):
        r=self.replay([],False)
        del r.exact_times['publications'][0]
        m=inputs.metrics(self.plan,self.P,r)
        self.assertEqual(m['cycles'][1]['status'],'INCOMPLETE')
        self.assertIsNone(m['cycles'][1]['unit_margin'])
        self.assertFalse(m['complete'])

    def test_best_comparison_prefers_smaller_response(self):
        a=dict(metrics=dict(cycle_fail=0,expert_fail=0,refresh_fail=0,worst_cycle_response=100,max_refresh_response=200))
        b=dict(metrics=dict(a['metrics'],worst_cycle_response=110))
        self.assertTrue(search._better(a,b))
        self.assertFalse(search._better(b,a))

    def test_inputs_and_frozen_source_unchanged(self):
        paths=[inputs.B9,inputs.B10,Path(selector_core.__file__).parent/'model.py']
        before=[digest(p) for p in paths]
        search.search_segment(self.plan,self.P,self.extra,self.base,node_cap=25)
        self.assertEqual(before,[digest(p) for p in paths])


if __name__=='__main__':unittest.main(verbosity=2)
