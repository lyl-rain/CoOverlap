"""Synthetic trace proves cross-NVTX GPU attribution and distinct copy timing."""
import sqlite3,tempfile,unittest
from pathlib import Path
from analyze_m1_trace_offline_v4 import analyze,union_ns
class Trace(unittest.TestCase):
    def test_union_overlap(self):self.assertEqual(union_ns([(30,40),(35,45)]),15)
    def test_correlation_not_cpu_clipping(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fake.sqlite';c=sqlite3.connect(p);pid=9<<24;tid=pid+1
            c.executescript('CREATE TABLE StringIds(id INTEGER,value TEXT);CREATE TABLE NVTX_EVENTS(start INTEGER,end INTEGER,text TEXT,textId INTEGER,globalTid INTEGER);CREATE TABLE CUPTI_ACTIVITY_KIND_RUNTIME(start INTEGER,end INTEGER,globalTid INTEGER,correlationId INTEGER,nameId INTEGER);CREATE TABLE CUPTI_ACTIVITY_KIND_KERNEL(start INTEGER,end INTEGER,globalPid INTEGER,correlationId INTEGER,streamId INTEGER);CREATE TABLE CUPTI_ACTIVITY_KIND_MEMCPY(start INTEGER,end INTEGER,globalPid INTEGER,correlationId INTEGER,streamId INTEGER);')
            c.executemany('INSERT INTO StringIds VALUES(?,?)',[(1,'cudaLaunchKernel'),(2,'cudaMemcpyAsync')])
            c.executemany('INSERT INTO NVTX_EVENTS VALUES(?,?,?,?,?)',[(10,20,'M1_SEG_0_Expert_0',None,tid),(50,150,'M1_NOISE_RECOVERY_seg0_E0',None,tid)])
            c.executemany('INSERT INTO CUPTI_ACTIVITY_KIND_RUNTIME VALUES(?,?,?,?,?)',[(15,16,tid,1,1),(52,149,tid,2,2)])
            c.executemany('INSERT INTO CUPTI_ACTIVITY_KIND_KERNEL VALUES(?,?,?,?,?)',[(30,40,pid,1,7),(35,45,pid,1,7)])
            c.execute('INSERT INTO CUPTI_ACTIVITY_KIND_MEMCPY VALUES(149,150,?,?,7)',(pid,2));c.commit();c.close()
            r=analyze(p);phase=r['phase_ranges'][0];noise=r['noise_wrappers'][0]
            self.assertEqual(phase['kernels'],2);self.assertEqual(phase['kernel_sum_ns'],20);self.assertEqual(phase['kernel_union_ns'],15)
            self.assertEqual(noise['cpu_NVTX_ns'],100);self.assertEqual(noise['runtime_sum_ns'],97);self.assertEqual(noise['copy_GPU_sum_ns'],1)
if __name__=='__main__':unittest.main(verbosity=2)
