import unittest
from analyze_cpu_gaps import classify,union_scan
from analyze_trace import length,intersect,sweep


class Accounting(unittest.TestCase):
    def test_union_does_not_sum_overlapping_kernels(self):
        intervals=[(0,10),(5,15)]
        self.assertEqual(length(intervals),15);self.assertEqual(union_scan(intervals),15)

    def test_overlap_does_not_use_branch_envelopes(self):
        e=[(0,10),(20,30)];v=[(5,25)]
        self.assertEqual(length(intersect(e,v)),10);self.assertEqual(sweep(e,v),10)

    def test_gap_has_three_distinct_API_states(self):
        result=classify(10,30,[dict(API_start_ns=20,API_end_ns=24)])
        self.assertEqual(result,dict(no_API_started_ns=10,API_inflight_ns=4,API_returned_pending_ns=6,unclassified_ns=0))

    def test_graph_nodes_share_returned_parent_API(self):
        result=classify(50,60,[dict(API_start_ns=0,API_end_ns=2)]*2410)
        self.assertEqual(result['API_returned_pending_ns'],10)
        self.assertEqual(result['no_API_started_ns'],0)

    def test_missing_mapping_stays_unclassified(self):
        self.assertEqual(classify(10,30,[])['unclassified_ns'],20)

    def test_API_can_remain_inflight_until_after_future_kernel_start(self):
        result=classify(10,30,[dict(API_start_ns=0,API_end_ns=40)])
        self.assertEqual(result['API_inflight_ns'],20)


if __name__=='__main__':unittest.main()
