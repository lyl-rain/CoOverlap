#!/usr/bin/env python3
"""Write the B10 CONFIG, BUDGET, SELECTION record and FREEZE from the plan."""
import hashlib, json, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'deployment'))
import m3_b10_plan as p
def sha(x): return hashlib.sha256(Path(x).read_bytes()).hexdigest()
config=p.protocol()
(HERE/'deployment'/'CONFIG.json').write_text(json.dumps(config,indent=2,sort_keys=True)+'\n')
b=p.budget()
budget=dict(schema='m3_b10_budget_v1',protocol=p.PROTOCOL,work=config['work'],
  retention=dict(bank_bytes=b['bank_bytes'],gpu_and_pinned=b['gpu_and_pinned_bytes'],
                 batch_payload_bytes=b['batch_payload_bytes'],per_cell=b['per_cell_segment_bytes']),
  disk=b['disk'],timeline_s=b['timeline_s'],
  limits=config['limits'],
  source='computed from m3_b10_plan.budget()/protocol(); not copied from a report')
(HERE/'deployment'/'BUDGET.json').write_text(json.dumps(budget,indent=2,sort_keys=True)+'\n')
files={k:v for k,v in {
 'config':'deployment/CONFIG.json','budget':'deployment/BUDGET.json',
 'plan':'deployment/m3_b10_plan.py','entry':'deployment/pi05_m3_b10_validation.py',
 'controller':'deployment/m3_b10_control.py','prediction':'prediction/PREDICTION.json',
 'selection':'prediction/SELECTION_FREEZE.json','prediction_builder':'analysis/build_b10_prediction.py',
 'selector_core':'../credible_plan_selector_v2/cps2/core.py',
 'selector_rules':'../credible_plan_selector_v2/outputs/RULES.json',
 'selector_costs':'../credible_plan_selector_v2/outputs/COSTS.json',
 'selector_ablation':'../credible_plan_selector_v2/outputs/ABLATION.csv',
 'b9_result':'../expert_reserve_validation_b9_v1_r2/gpu_run_01/board_small/model/result.json'}.items()}
rec={k:dict(path=v,sha256=sha(v)) for k,v in files.items()}
freeze=dict(schema='m3_b10_freeze_v1',protocol=p.PROTOCOL,status='PREPARED',
            approval='NOT_APPROVED',run='NOT_RUN',files=rec)
(HERE/'FREEZE.json').write_text(json.dumps(freeze,indent=2,sort_keys=True)+'\n')
print(json.dumps(dict(config=sha(HERE/'deployment'/'CONFIG.json'),budget_sha=sha(HERE/'deployment'/'BUDGET.json'),
   work=config['work']['batch']['total_C'],work_e=config['work']['batch']['total_E'],
   bank=b['bank_bytes'],payload=b['batch_payload_bytes'],timeline=b['timeline_s'],
   disk_gib=b['disk']['estimate_gib']),indent=1))
