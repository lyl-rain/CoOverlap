"""Meaningful CPU tests of new obligation mapping and uncertain deadline handling."""
import json
from period_obligation_stats import jobs,classify,cycle_rows,counts
P=100;t0=1000;e,r=jobs(t0,P)
assert [v['release_ns'] for v in r]==[1000,1200,1400,1600]
assert [v['deadline_ns'] for v in r]==[1200,1400,1600,1800]
assert classify(1090,1100,1100)=='PASS'
assert classify(1101,1110,1100)=='FAIL'
assert classify(1099,1101,1100)=='UNCERTAIN'
assert classify(None,None,1100)=='INCOMPLETE'
for v in e:v.update(completion_lower_ns=v['release_ns']+20,completion_observed_ns=v['release_ns']+21)
units=[]
for m in range(4):
 for u,delta in [('B1',40),('B2',60)]:units.append(dict(id=m,unit=u,completion_lower_ns=r[m]['release_ns']+delta,completion_observed_ns=r[m]['release_ns']+delta+1))
s=dict(P_ms=P/1e6,t0_ns=t0,experts=e,unit_completions=units)
a=cycle_rows(s);assert all(v['cycle_status']=='PASS' for v in a)
# Early B2 belongs to the next cycle, never a different refresh.
assert a[1]['required_unit_id']=='R0/B2' and a[1]['response_lower_ms']>=0
units[2].update(completion_lower_ns=1340,completion_observed_ns=1341)
a=cycle_rows(s);assert a[2]['cycle_status']=='FAIL' and a[0]['cycle_status']=='PASS'
units[2].update(completion_lower_ns=1299,completion_observed_ns=1301)
a=cycle_rows(s);assert a[2]['cycle_status']=='UNCERTAIN'
units.pop();a=cycle_rows(s);assert a[7]['cycle_status']=='INCOMPLETE'
assert counts(['FAIL','FAIL','UNCERTAIN','FAIL'])['longest_consecutive_definite_miss']==2
print(json.dumps({'status':'PASS','checks':['fixed arrivals/deadlines','exact same-refresh obligation IDs','early B2','definite miss','uncertain deadline not PASS','unfinished unit not PASS','consecutive misses']}))
