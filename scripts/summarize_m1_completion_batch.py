"""Offline independent-repeat table, no pooling into a stability claim."""
import json,sys
from pathlib import Path
def main():
    from m1_run_identity import require_analysis_user
    require_analysis_user()
    root=Path(sys.argv[1]);rows=[]
    for role in ['repeat1','repeat2','repeat3']:
        p=root/role/'offline_analysis/SUMMARY.json'
        if not p.exists():rows.append(dict(role=role,status='NOT_ANALYZED_OR_NOT_RUN'));continue
        r=json.loads(p.read_text())
        for c in r['combinations']:
            c['status']=c['status']+';FREQUENCY='+c.get('frequency_condition','UNKNOWN')
            qs=[q for q in r['refreshes'] if q['segment']==c['segment']]
            rows.append(dict(role=role,P_ms=c['P_ms'],plan=c['plan'],interference=c['interference'],status=c['status'],cycle=c['cycle'],Expert=c['Expert'],VLM=c['VLM'],Expert_response_max_ms=c['expert_response_max_ms'],refresh_responses_ms=[(q['response_lower_ms'],q['response_upper_ms']) for q in qs],k=[(q['k_observed_lower'],q['k_observed_upper']) for q in qs],target=[q['target_status'] for q in qs],backlog=[(q['definite_prior_refresh_backlog_at_Q'],q['uncertain_prior_refresh_backlog_at_Q']) for q in qs]))
    (root/'INDEPENDENT_RESULTS.json').open('x').write(json.dumps(rows,indent=2))
    lines=['# M1 三重复按组合并列（未插桩）','','每格保留独立分母；缺失/不确定不当通过。仅有限可行性，不宣称可靠p99、稳定收益或路线选择。','','|重复|P|计划|干扰|段状态|周期FAIL/分母|Expert FAIL/分母|VLM FAIL/分母|周期不确定/未完成|','|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        if 'cycle' not in r:lines.append(f"|{r['role']}||||{r['status']}|||||");continue
        c,e,v=r['cycle'],r['Expert'],r['VLM'];lines.append(f"|{r['role']}|{r['P_ms']}|{r['plan']}|{r['interference']}|{r['status']}|{c['FAIL']}/{c['denominator']}|{e['FAIL']}/{e['denominator']}|{v['FAIL']}/{v['denominator']}|{c['UNCERTAIN']}/{c['INCOMPLETE']}|")
    (root/'INDEPENDENT_RESULTS.md').open('x').write('\n'.join(lines)+'\n')
if __name__=='__main__':main()
