"""Generate immutable finite configurations; never starts a model."""
import argparse,json,hashlib
from pathlib import Path
from m1_completion_core import calibration_config,formal_configs,trace_config,select_budgets,validate_config

def write(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2)

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--calibration-result');a=p.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
    if not a.calibration_result:
        write(out/'calibration.json',calibration_config())
        for tight,loose in ((180,240),(180,320),(240,320)):
            b=out/('EXAMPLE_NOT_A_SELECTION_'+str(tight)+'_'+str(loose));b.mkdir()
            for c in formal_configs(dict(tight_ms=tight,loose_ms=loose))+[trace_config(dict(tight_ms=tight,loose_ms=loose))]:
                validate_config(c);write(b/(c['role']+'.json'),c)
    else:
        source=Path(a.calibration_result);r=json.loads(source.read_text())
        # A bare synthetic statistics object is insufficient to freeze a GPU run.
        if r.get('gate')!='PASS' or not r.get('inputs') or not r.get('extension_sha256') or not r.get('script_sha256'):raise ValueError('missing live evidence')
        selection=select_budgets(r);selection['result_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
        write(out/'selection.json',selection)
        for c in formal_configs(selection)+[trace_config(selection)]:validate_config(c);write(out/(c['role']+'.json'),c)
if __name__=='__main__':main()
