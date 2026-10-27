# -*- coding: utf-8 -*-
from pathlib import Path
import json,os,hashlib,difflib,shutil,csv
P=Path('/Users/moblumen/Desktop/CoOverlap');O=Path(__file__).resolve().parent;final=P/'reports/m3_b2/20261023/m3_stage_acceptance_review_v1'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
idx=json.loads((O/'EVIDENCE_INDEX.json').read_text())
lines=['# M3 审阅来源索引','','以下SHA仅证明本地选定输入的一致性；不代替远端或全部payload重算。','','|来源|文件|SHA256|','|---|---|---|']
for key,row in idx['inputs'].items():
 p=P/row['path'];assert sha(p)==row['sha256'],row['path']
 lines.append('|'+key+'|['+p.name+']('+os.path.relpath(p,final)+')|`'+row['sha256']+'`|')
(O/'SOURCES.md').write_text('\n'.join(lines)+'\n')
# Consistency of figures and decision status, not a scheduler/GPU revalidation.
rows=list(csv.DictReader((O/'METRICS_BY_CELL.csv').open()));by={(r['batch'],float(r['period_ms']),r['plan'],r['policy']):r for r in rows if r['batch']!='B6'}
assert by['B5',180.0,'two_9_9','serial_context']['Cycle_FAIL']=='8'
assert by['B5',180.0,'two_9_9','b2_boundary']['Cycle_FAIL']=='0'
assert by['B9',140.0,'two_9_9','b2_boundary']['Cycle_UNCERTAIN']=='1'
assert by['B9',140.0,'three_prefix_9_9','b2_boundary']['Cycle_FAIL']=='7'
assert all(r['Cycle_FAIL']=='0' and r['Cycle_UNCERTAIN']=='0' for r in rows if r['batch']=='B10')
d=json.loads((O/'DECISION_RECORD.json').read_text());assert all(x['status']=='PENDING_USER_CONFIRMATION' for x in d['decisions']);assert d['M4_authorized'] is False
# Save complete before copies and additive status/map patches.
(O/'before_docs').mkdir(exist_ok=True);(O/'docs_new').mkdir(exist_ok=True)
changes=[]
status='''更新时间：2026-10-23（M3阶段成果审阅与分项验收建议：待用户确认）\n当前阶段：M2保持已验收；M3未全面验收；B2仍候选，不自动进入M4。\n\n## 当前：M3阶段审阅与待确认决策\n\n- 已整理任务书要求、B3–B10实测、开销与消融、计划预测反例、恢复/归档边界。\n- 本地重建B4–B10共7批52段的416周期/208刷新，核心统计0差异；这些是核验覆盖量，不合并成总体性能率。\n- **建议（未获用户确认）：** 分项接收已实现的合法切分/边界执行、已覆盖正确性与有限机制对照；暂不宣布M3整体通过。\n- 尚未成立：可靠准入与相对标准boundary基线的独立方法收益；干扰条件化选计划；全部开销独立归因。任务书预捕获子图与当前非Graph范围差异须显式确认。\n- B9给出错误接受反例，B10接受获样本支持但150 ms出现过度拒绝；选择器暂建议定位离线评价/诊断，不调阈值补点。\n- B10官方64/64/32通过、双预留满足、恢复首次FAIL→后续PASS与root-only归档缺口全部保留；当前恢复确认不等于自动恢复链已证明可靠。\n- 四项建议均PENDING_USER_CONFIRMATION；不自动定线B2、不生成B11、不授权M4。详见[一页结论](../reports/m3_b2/20261023/m3_stage_acceptance_review_v1/ONE_PAGE.md)、[阶段审阅](../reports/m3_b2/20261023/m3_stage_acceptance_review_v1/M3_STAGE_REVIEW.md)、[决策记录](../reports/m3_b2/20261023/m3_stage_acceptance_review_v1/DECISION_RECORD.json)。\n- 本轮仅本地读取、重建与文档整理，新增模型/worker/SSH/部署/硬件写入/scope均0；原始数据、执行器和冻结包不改。\n\n## 历史：B10收口状态快照（原文保留）\n\n'''
code='''## 当前：M3成果与验收审阅（2026-10-23，决策待确认）\n\n- `reports/m3_b2/20261023/m3_stage_acceptance_review_v1/`：M3_STAGE_REVIEW.md（任务书对照/成果/缺口/四项建议）、ONE_PAGE.md、DECISION_RECORD.json（全部待用户确认）。\n- `build_review.py`只读原始记录并复用冻结replay_stats/classify；METRICS_BY_CELL.csv、METRICS_BY_SEGMENT.json、VERIFY_RESULT.json记录7批52段核心统计重建0差异，不构成新GPU证据。\n- TASK_REQUIREMENTS.json、EVIDENCE_INDEX.json、SOURCES.md为任务书原文与来源SHA/链接；原包、原数据、执行器均未改。\n- 建议分项验收而非M3整体PASS；B2仍候选，不自动进入M4。\n\n'''
for name,prefix in [('PROJECT_STATUS.md',status),('CODE_MAP.md',code)]:
 p=P/'docs'/name;old=p.read_text();backup=O/'before_docs'/name
 if backup.exists():assert backup.read_bytes()==p.read_bytes(),'refuse replacing original docs backup after publication'
 backup.write_bytes(p.read_bytes());head,tail=old.split('\n',1)
 if name=='PROJECT_STATUS.md':tail=tail.replace('## 当前：','## 历史：',1)
 else:tail=tail.replace('## 当前：','## 历史：',1)
 new=head+'\n\n'+prefix+tail;(O/'docs_new'/name).write_text(new)
 changes.append(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/docs/'+name,tofile='b/docs/'+name)))
(O/'DOC_DIFF.patch').write_text(''.join(changes))
(O/'REVIEW_VALIDATION.json').write_text(json.dumps(dict(status='PASS',checked_input_fingerprints=len(idx['inputs']),official_core_statistics='7 batches / 52 segments / 0 differences',figure_checks='B5/B9/B10 counts verified against regenerated CSV',decisions='all pending user confirmation',no_new_GPU_evidence=True,remote_access_this_round=0),indent=2)+'\n')
# Include the report-producing commands and all report artifacts; omit replacement docs payload from final copy.
files={str(p.relative_to(O)):dict(path=str(p.relative_to(O)),sha256=sha(p)) for p in O.rglob('*') if p.is_file() and 'docs_new' not in p.parts and p.name!='REPORT_SHA256.json'}
(O/'REPORT_SHA256.json').write_text(json.dumps(dict(files=files,self_hash=False),indent=2,ensure_ascii=False,sort_keys=True)+'\n')
print(json.dumps(dict(status='REVIEW_READY',sources=len(idx['inputs']),artifacts=len(files),decisions='PENDING_USER_CONFIRMATION'),ensure_ascii=False))
