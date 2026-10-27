"""B10 offline evaluator: frozen official statistics plus dual-reserve evaluation.

No CUDA imports. Real B10 results and explicit CPU fixtures are distinguished.
"""
import argparse,hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace
HERE=Path(__file__).resolve().parents[1]
DEPLOY=HERE/'deployment'
sys.path.insert(0,str(DEPLOY))
from m2_executor import replay_stats
from period_obligation_stats import classify
import m3_b10_plan as plan
from selection_contract import load_identity
pm=SimpleNamespace(BLOCKS={k:len(p) for k,p in plan.PLANS.items()},GROUPS={k:p.groups for k,p in plan.PLANS.items()},_group_of=lambda p,b:next(i for i,g in enumerate(plan.PLANS[p].groups) if b in g))
RESERVE_MS=10.0
STATUS_ORDER=('PASS','FAIL','UNCERTAIN','INCOMPLETE','INVALID')
def _ms(ns):return None if ns is None else round(ns/1e6,6)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def verify_freeze(path=None):
 p=Path(path or HERE/'FREEZE.json');d=load(p);bad=[]
 for row in d['files'].values():
  q=p.parent/row['path']
  if not q.is_file() or sha(q)!=row['sha256']:bad.append(row['path'])
 if bad:raise ValueError('INVALID_EVIDENCE frozen files: '+repr(bad))
 return d
def _parse_units(raw):
    out = {}
    for key, value in (raw or {}).items():
        if isinstance(key, tuple):
            out[key] = value
            continue
        text = str(key).strip().strip('()')
        m, b = text.split(',')
        out[(int(m), int(b))] = value
    return out


def declared_rows(period_ns, plan, cycles, phase_ns, nblocks):
    """The declared obligations of one segment, with no completion evidence.

    Used when a pre-created segment was never executed: identity comes from the
    frozen CONFIG, not from an absent manifest, and every declared job stays
    INCOMPLETE with completion/response/margin = None (never zero, never PASS).
    """
    experts, cycles_out, refreshes, blocks = [], [], [], []
    for j in range(cycles):
        rel = j * period_ns + phase_ns
        dl = (j + 1) * period_ns + phase_ns
        experts.append(dict(job_id='E%d' % j, release_ms=_ms(rel), deadline_ms=_ms(dl),
                            dispatch_ms=None, completion_ms=None, response_ms=None,
                            margin_ms=None, completion_status='INCOMPLETE',
                            deadline_status='INCOMPLETE'))
        cycles_out.append(dict(job_id='cycle%d' % j, release_ms=_ms(rel),
                               deadline_ms=_ms(dl), completion_ms=None, response_ms=None,
                               response_interval_ms=[None, None], margin_ms=None,
                               status='INCOMPLETE', expert_status='INCOMPLETE',
                               unit_status='INCOMPLETE'))
    for q in range(cycles // 2):
        rel = 2 * q * period_ns
        refreshes.append(dict(job_id='refresh%d' % q, release_ms=_ms(rel),
                              deadline_ms=_ms(rel + 2 * period_ns), completion_ms=None,
                              response_ms=None, response_interval_ms=[None, None],
                              margin_ms=None, status='INCOMPLETE', k_lower=None, k_upper=None))
        for b in range(nblocks):
            gi = pm._group_of(plan, b) if plan in pm.GROUPS else 0
            blocks.append(dict(job_id='R%d/B%d' % (q, b + 1), refresh=q, block=b,
                               obligation_group=gi, release_ms=_ms(rel), dispatch_ms=None,
                               completion_ms=None, response_ms=None, margin_ms=None,
                               status='INCOMPLETE'))
    return experts, cycles_out, refreshes, blocks


def segment_official(segment, declared, reserve_ms=RESERVE_MS):
    """Official job rows of one segment; identity comes from the frozen CONFIG.

    A pre-created ``NOT_STARTED`` record has no manifest/t0 by design, so it is a
    declared-but-unexecuted segment (all obligations INCOMPLETE), not structural
    damage.  An identity conflict with the CONFIG is still INVALID_EVIDENCE.
    """
    issues = []
    seg_id = declared['segment_id']
    cell = declared['cell']
    plan = declared['plan']
    period_ns = declared['period_ns']
    cycles = declared['cycles']
    phase_ns = declared['phase_ns']
    nblocks = pm.BLOCKS[plan]
    manifest = segment.get('manifest')
    t0 = segment.get('t0_ns')
    record_has_jobs = any(segment.get(k) for k in
                          ('experts', 'units', 'published', 'blocks', 'decisions'))
    for field, want, got in (('segment_id', seg_id, segment.get('segment_id')),
                             ('cell', cell, segment.get('cell')),
                             ('plan', plan, segment.get('plan')),
                             ('period_ns', period_ns, segment.get('period_ns'))):
        if got is not None and got != want:
            issues.append('identity conflict: %s expected %r got %r' % (field, want, got))
    policy = segment.get('policy', segment.get('mode'))
    if policy is not None and policy != declared['policy']:
        issues.append('identity conflict: policy expected %r got %r'
                      % (declared['policy'], policy))
    if issues:
        e, c, r, b = declared_rows(period_ns, plan, cycles, phase_ns, nblocks)
        return dict(segment_id=seg_id, cell=cell, plan=plan, period_ns=period_ns,
                    period_ms=_ms(period_ns), issues=issues, status='INVALID_EVIDENCE',
                    experts=e, cycles=c, refreshes=r, blocks=b,
                    declared=dict(experts=cycles, cycles=cycles,
                                  refreshes=cycles // 2, blocks=cycles // 2 * nblocks))
    if manifest is None or t0 is None:
        if record_has_jobs:
            e, c, r, b = declared_rows(period_ns, plan, cycles, phase_ns, nblocks)
            return dict(segment_id=seg_id, cell=cell, plan=plan, period_ns=period_ns,
                        period_ms=_ms(period_ns),
                        issues=['job records without manifest/t0'], status='INVALID_EVIDENCE',
                        experts=e, cycles=c, refreshes=r, blocks=b,
                        declared=dict(experts=cycles, cycles=cycles,
                                      refreshes=cycles // 2,
                                      blocks=cycles // 2 * nblocks))
        # declared-but-unexecuted: pre-created NOT_STARTED record
        e, c, r, b = declared_rows(period_ns, plan, cycles, phase_ns, nblocks)
        seen = segment.get('status')
        return dict(segment_id=seg_id, cell=cell, plan=plan, period_ns=period_ns,
                    period_ms=_ms(period_ns), issues=[],
                    status='NOT_STARTED' if seen in (None, 'NOT_STARTED') else seen,
                    experts=e, cycles=c, refreshes=r, blocks=b,
                    declared=dict(experts=cycles, cycles=cycles,
                                  refreshes=cycles // 2,
                                  blocks=cycles // 2 * nblocks),
                    note='pre-created segment without execution; all declared obligations INCOMPLETE')
    m = manifest
    if m != plan_manifest(period_ns):
        raise ValueError('INVALID_EVIDENCE manifest differs from frozen trajectory')
    exp_ids = [e['id'] for e in m['experts']]
    ref_ids = [r['id'] for r in m['refreshes']]
    raw_experts = segment.get('experts') or {}
    raw_pub = segment.get('published') or {}
    raw_blocks = segment.get('blocks') or {}
    raw_units = _parse_units(segment.get('units'))
    extra = (set(raw_experts) - {str(j) for j in exp_ids}
             | set(raw_pub) - {str(q) for q in ref_ids})
    if extra:
        issues.append('unexpected job ids: %s' % sorted(extra))
    for key, value in list(raw_experts.items()) + list(raw_pub.items()) + \
            [(str(k), v) for k, v in raw_units.items()] + list(raw_blocks.items()):
        if not (isinstance(value, (list, tuple)) and len(value) == 2):
            issues.append('job %s is not a (lower, upper) pair' % (key,))
            continue
        lo, hi = value
        if not (isinstance(lo, int) and isinstance(hi, int) and lo <= hi):
            issues.append('job %s has an illegal interval %r' % (key, value))
    experts, cycles_out, refreshes, blocks = [], [], [], []
    if issues:
        stats = None
    else:
        try:
            stats = replay_stats(m, {int(k): tuple(v) for k, v in raw_experts.items()},
                                 raw_units, {int(k): tuple(v) for k, v in raw_pub.items()},
                                 t0=t0)
        except ValueError as exc:
            issues.append('replay_stats refused the record: %s' % exc)
            stats = None
    cycle_by = {}
    if stats is not None:
        for row in stats['cycles']:
            j = row['cycle']
            margin = (None if row['response_upper_ns'] is None else
                      round((row['deadline_ns'] - row['release_ns']
                             - row['response_upper_ns']) / 1e6, 6))
            cycle_by[j] = dict(
                job_id='cycle%d' % j, release_ms=_ms(row['release_ns'] - t0),
                deadline_ms=_ms(row['deadline_ns'] - t0),
                completion_ms=(None if row['response_upper_ns'] is None else
                               _ms(row['release_ns'] + row['response_upper_ns'] - t0)),
                response_ms=(None if row['response_upper_ns'] is None else
                             _ms(row['response_upper_ns'])),
                response_interval_ms=[None if row['response_lower_ns'] is None else
                                      _ms(row['response_lower_ns']),
                                      None if row['response_upper_ns'] is None else
                                      _ms(row['response_upper_ns'])],
                margin_ms=margin, status=row['status'],
                expert_status=row['expert_status'], unit_status=row['unit_status'])
            cycles_out.append(cycle_by[j])
        for row in stats['refreshes']:
            q = row['id']
            margin = (None if row['ready_upper_ns'] is None else
                      round(2 * m['period_ns'] / 1e6 - row['ready_upper_ns'] / 1e6, 6))
            refreshes.append(dict(
                job_id='refresh%d' % q, release_ms=_ms(q * 2 * m['period_ns']),
                deadline_ms=_ms(q * 2 * m['period_ns'] + 2 * m['period_ns']),
                completion_ms=(None if row['ready_upper_ns'] is None else
                               _ms(q * 2 * m['period_ns'] + row['ready_upper_ns'])),
                response_ms=(None if row['ready_upper_ns'] is None else
                             _ms(row['ready_upper_ns'])),
                response_interval_ms=[None if row['ready_lower_ns'] is None else
                                      _ms(row['ready_lower_ns']),
                                      None if row['ready_upper_ns'] is None else
                                      _ms(row['ready_upper_ns'])],
                margin_ms=margin, status=row['status'], k_lower=row['k_lower'],
                k_upper=row['k_upper']))
    if issues:
        e,c,r,b=declared_rows(period_ns,plan,cycles,phase_ns,nblocks)
        return dict(segment_id=seg_id,cell=cell,plan=plan,period_ns=period_ns,period_ms=_ms(period_ns),issues=issues,status='INVALID_EVIDENCE',experts=e,cycles=c,refreshes=r,blocks=b)
    for e in m['experts']:
        j = e['id']
        rel = t0 + e['release_ns']
        dl = t0 + e['deadline_ns']
        rec = raw_experts.get(str(j))
        if rec is None:
            experts.append(dict(job_id='E%d' % j, release_ms=_ms(e['release_ns']),
                                deadline_ms=_ms(e['deadline_ns']), dispatch_ms=None,
                                completion_ms=None, response_ms=None, margin_ms=None,
                                completion_status='INCOMPLETE', deadline_status='INCOMPLETE'))
            continue
        lo, hi = rec
        if not (isinstance(lo, int) and isinstance(hi, int) and lo <= hi and lo >= rel):
            experts.append(dict(job_id='E%d' % j, release_ms=_ms(e['release_ns']),
                                deadline_ms=_ms(e['deadline_ns']), dispatch_ms=None,
                                completion_ms=None, response_ms=None, margin_ms=None,
                                completion_status='INVALID', deadline_status='INVALID'))
            continue
        completion_status = 'COMPLETE'
        deadline_status = classify(lo, hi, dl)
        experts.append(dict(
            job_id='E%d' % j, release_ms=_ms(e['release_ns']),
            deadline_ms=_ms(e['deadline_ns']), dispatch_ms=None,
            completion_ms=_ms(hi - t0), response_ms=_ms(hi - rel),
            response_interval_ms=[_ms(lo - rel), _ms(hi - rel)],
            margin_ms=_ms(dl - hi), completion_status=completion_status,
            deadline_status=deadline_status))
    for key, (lo, hi) in sorted(raw_blocks.items()):
        q, b = key.strip('()').split(',')
        q, b = int(q), int(b)
        gi = pm._group_of(plan, b) if plan in pm.GROUPS else 0
        cyc = cycle_by.get(2 * q + gi)
        blocks.append(dict(job_id='R%d/B%d' % (q, b + 1), refresh=q, block=b,
                           obligation_group=gi, release_ms=_ms(q * 2 * m['period_ns']),
                           dispatch_ms=None, completion_ms=_ms(hi - t0),
                           response_ms=_ms(hi - t0 - q * 2 * m['period_ns']),
                           margin_ms=(None if cyc is None or cyc['margin_ms'] is None
                                      else round(cyc['deadline_ms'] - _ms(hi - t0), 6)),
                           status=(None if cyc is None else cyc['status'])))
    status = 'INVALID_EVIDENCE' if issues else 'OK'
    return dict(segment_id=seg_id, cell=cell, plan=plan, period_ns=period_ns,
                period_ms=_ms(period_ns), issues=issues, status=status,
                experts=experts, cycles=cycles_out, refreshes=refreshes, blocks=blocks,
                declared=dict(experts=len(exp_ids), cycles=len(exp_ids),
                              refreshes=len(ref_ids),
                              blocks=len(raw_blocks) if raw_blocks else None))


def official_summary(result, config):
    """Per-segment official statistics with declared denominators preserved.

    The denominator comes from the frozen CONFIG (8 segments x 8 Expert / 8 Cycle /
    4 Refresh).  A pre-created ``NOT_STARTED`` record contributes its declared
    obligations as INCOMPLETE; it never contributes PASS and never loses the
    denominator.
    """
    by_id = {s.get('segment_id'): s for s in (result.get('segments') or [])}
    cycles = config['cycles']
    phase_ns = config['phase_ns']
    rows = []
    totals = {jt: {k: 0 for k in STATUS_ORDER} for jt in ('Expert', 'Cycle', 'Refresh')}
    declared = {jt: 0 for jt in ('Expert', 'Cycle', 'Refresh')}
    for index, (sid, cell) in enumerate(zip(config['segment_ids'], config['run'])):
        n_exp, n_cyc, n_ref = cycles, cycles, cycles // 2
        declared['Expert'] += n_exp
        declared['Cycle'] += n_cyc
        declared['Refresh'] += n_ref
        declared_cell = dict(segment_id=sid, cell=cell['cell'], plan=cell['plan'],
                             policy=cell['policy'], period_ns=cell['period_ns'],
                             cycles=cycles, phase_ns=phase_ns, index=index)
        segment = by_id.get(sid)
        if segment is None:
            e, c, r, b = declared_rows(cell['period_ns'], cell['plan'], cycles,
                                       phase_ns, pm.BLOCKS[cell['plan']])
            row = dict(segment_id=sid, cell=cell['cell'], plan=cell['plan'],
                       period_ns=cell['period_ns'], period_ms=cell['period_ns'] / 1e6,
                       status='MISSING', issues=['segment record absent'],
                       experts=e, cycles=c, refreshes=r, blocks=b,
                       declared=dict(experts=n_exp, cycles=n_cyc, refreshes=n_ref,
                                     blocks=cycles // 2 * pm.BLOCKS[cell['plan']]))
            rows.append(row)
            for jt, n in (('Expert', n_exp), ('Cycle', n_cyc), ('Refresh', n_ref)):
                totals[jt]['INCOMPLETE'] += n
            continue
        row = segment_official(segment, declared_cell)
        rows.append(row)
        if row['status'] == 'INVALID_EVIDENCE':
            for jt, n in (('Expert', n_exp), ('Cycle', n_cyc), ('Refresh', n_ref)):
                totals[jt]['INVALID'] += n
            continue
        for e in row['experts']:
            totals['Expert'][e['deadline_status']
                             if e['completion_status'] == 'COMPLETE' else 'INCOMPLETE'] += 1
        for c in row['cycles']:
            totals['Cycle'][c['status']] += 1
        for r in row['refreshes']:
            totals['Refresh'][r['status']] += 1
    per_cell = {}
    for row in rows:
        key = '%s@p%d' % (row['cell'], int(round(row['period_ms'])))
        bucket = per_cell.setdefault(key, dict(plan=row['plan'], period_ms=row['period_ms'],
                                               declared=dict(experts=0, cycles=0, refreshes=0),
                                               cycles={k: 0 for k in STATUS_ORDER},
                                               refreshes={k: 0 for k in STATUS_ORDER},
                                               experts={k: 0 for k in STATUS_ORDER},
                                               segments=[]))
        bucket['segments'].append(row['segment_id'])
        bucket['declared']['experts'] += len(row['experts'])
        bucket['declared']['cycles'] += len(row['cycles'])
        bucket['declared']['refreshes'] += len(row['refreshes'])
        for jt, key2 in (('Cycle', 'cycles'), ('Refresh', 'refreshes'), ('Expert', 'experts')):
            for x in row[key2]:
                st = x.get('status') if jt != 'Expert' else (
                    x['deadline_status'] if x['completion_status'] == 'COMPLETE' else 'INCOMPLETE')
                bucket[keys(jt)][st] = bucket[keys(jt)].get(st, 0) + 1
    return dict(segments=rows, totals=totals, declared=declared, per_cell=per_cell,
                note='official deadlines only; denominators are the declared obligations; '
                     'NOT_STARTED/INCOMPLETE/INVALID are never counted as PASS')


def keys(jt):
    return {'Cycle': 'cycles', 'Refresh': 'refreshes', 'Expert': 'experts'}[jt]



def plan_manifest(period):return plan.manifest(period)
def reserve_state(lo,hi,deadline,reserve=10.0):
 if lo is None or hi is None:return 'UNKNOWN'
 boundary=deadline-reserve
 return 'SATISFIED' if hi<=boundary else ('SHORT' if lo>boundary else 'UNCERTAIN')
def conditions(result,config):
 fields=[]
 def add(name,expected,actual):fields.append(dict(field=name,expected=expected,actual=actual,verdict='UNKNOWN' if actual is None else ('MATCH' if expected==actual else 'MISMATCH')))
 proto=result.get('protocol') or {}
 add('protocol',config,proto)
 add('config_sha256',sha(DEPLOY/'CONFIG.json'),result.get('config_sha256'))
 add('observation_mode','performance',result.get('observation_mode'))
 source=load(HERE.parent/'credible_plan_selector_v2_r1/SOURCE_CONDITIONS.json')['B9']['condition']
 for name in ('configuration','snapshots'):
  add(name,source[name],result.get(name))
 clocks=result.get('initial_clock_limits')
 def limits(rows):return [{k:x.get(k) for k in ('name','path','min','max','cur','target')} for x in rows] if rows else None
 add('clock_limits',limits(source['clock_limits']),limits(clocks))
 dep={}
 for line in (DEPLOY/'DEPLOY_SHA256.txt').read_text().splitlines():
  h,k=line.split(None,1);dep[k]=h
 add('source_config_fingerprints',dep,result.get('source_config_fingerprints'))
 add('prediction_identity.sha256',config['prediction']['sha256'],(result.get('prediction_identity') or {}).get('sha256'))
 add('selection_fingerprint',config['selection']['fingerprint'],(result.get('selection_freeze') or {}).get('fingerprint'))
 raw=result.get('segments') or []
 for sid,c in zip(config['segment_ids'],config['run']):
  seg=next((x for x in raw if x.get('segment_id')==sid),{})
  add(sid+'.manifest',plan_manifest(c['period_ns']),seg.get('manifest'))
  add(sid+'.block_plan',config['plans'][c['plan']],seg.get('block_plan'))
  add(sid+'.payload_B',config['retention']['layouts'][c['plan']]['nbytes'],(seg.get('validation') or {}).get('payload_B'))
  add(sid+'.selection',config['selection']['by_budget_ns'][str(c['period_ns'])],seg.get('selection'))
  add(sid+'.selection_fingerprint',config['selection']['fingerprint'],seg.get('selection_fingerprint'))
 mismatches=[x['field'] for x in fields if x['verdict']=='MISMATCH'];unknown=[x['field'] for x in fields if x['verdict']=='UNKNOWN']
 return dict(status='CONDITION_MISMATCH' if mismatches else ('INSUFFICIENT_EVIDENCE' if unknown else 'MATCH'),fields=fields,mismatches=mismatches,unknown=unknown,target_evidence='new target-budget measurement; source match alone was not target validation')
def reserve_rows(segment,declared):
 t0=segment.get('t0_ns');m=plan_manifest(declared['period_ns']);units=_parse_units(segment.get('units'));out=[]
 for e in m['experts']:
  j=e['id'];dl=e['deadline_ns']/1e6
  for kind,key,rec in [('Expert','E%d'%j,(segment.get('experts') or {}).get(str(j))),('VLMUnit','R%d/U%d'%(j//2,j%2),units.get((j//2,j%2)))]:
   lo=hi=None
   if rec is not None and t0 is not None:lo,hi=[(v-t0)/1e6 for v in rec]
   out.append(dict(job_type=kind,job_id=key,deadline_ms=dl,completion_lower_ms=lo,completion_upper_ms=hi,margin_ms=None if hi is None else dl-hi,reserve_ms=10.0,state=reserve_state(lo,hi,dl)))
 return out

def comparisons(segment,official,prediction_cases):
 actual={}
 for kind,key in [('Expert','experts'),('Cycle','cycles'),('Refresh','refreshes'),('ContextBlock','blocks')]:
  for row in official[key]:actual[kind,row['job_id']]=row
 decisions={};order=[]
 for d in segment.get('decisions') or []:
  if d['kind'] in ('Expert','Context'):
   key='E%d'%d['id'] if d['kind']=='Expert' else 'R%d/B%d'%(d['id'],d['block']+1)
   order.append(key);decisions[key]=(d['host_ns']-segment['t0_ns'])/1e6
 binds={}
 for row in segment.get('journal') or []:
  if row and row[0]=='bind':binds.setdefault(row[1],row[2])
 results=[]
 for label,case in prediction_cases.items():
  by={(x['job_type'],x['job_id']):x for x in case['rows']}
  jobs=[]
  for key in sorted(set(by)|set(actual)):
   p=by.get(key);a=actual.get(key)
   if p is None or a is None:jobs.append(dict(job_type=key[0],job_id=key[1],status='MISSING_PREDICTION' if p is None else 'MISSING_ACTUAL'));continue
   comp=None if p.get('completion_ms') is None or a.get('completion_ms') is None else a['completion_ms']-p['completion_ms']
   resp=None if p.get('response_ms') is None or a.get('response_ms') is None else a['response_ms']-p['response_ms']
   actual_status=a.get('deadline_status',a.get('status'))
   if a.get('completion_status')=='INCOMPLETE':actual_status='INCOMPLETE'
   jobs.append(dict(job_type=key[0],job_id=key[1],predicted_status=p.get('status'),actual_status=actual_status,completion_exceedance_ms=comp,completion_error_ms=None if comp is None else -comp,response_exceedance_ms=resp,response_error_ms=None if resp is None else -resp,stress_completion_exceeded=None if comp is None else comp>0,stress_response_exceeded=None if resp is None else resp>0,dispatch_actual_ms=decisions.get(key[1]),dispatch_predicted_ms=p.get('dispatch_ms'),version_actual=binds.get(key[1]) if key[0]=='Expert' else None,version_predicted=p.get('version')))
  first=next((dict(index=i,predicted=p,actual=a) for i,(p,a) in enumerate(zip(case['order'],order)) if p!=a),None)
  if first is None and len(case['order'])!=len(order):
   i=min(len(case['order']),len(order));first=dict(index=i,predicted=case['order'][i] if i<len(case['order']) else None,actual=order[i] if i<len(order) else None)
  pv={r['job_id']:r['version'] for r in case['rows'] if r['job_type']=='Expert'}
  results.append(dict(source_scenario=label,scenario=case['scenario'],jobs=jobs,order_match=case['order']==order,first_divergence=first,predicted_order=case['order'],actual_order=order,predicted_versions=pv,actual_versions=binds,version_match=all(binds.get(j)==v for j,v in pv.items()),missing_prediction=[list(k) for k in actual if k not in by],missing_actual=[list(k) for k in by if k not in actual]))
 return results

def evaluate(result,freeze_path=None):
 verify_freeze(freeze_path);selection,pred=load_identity(DEPLOY);config=load(DEPLOY/'CONFIG.json')
 raw=result.get('segments') or [];ids=[x.get('segment_id') for x in raw]
 if len(set(ids))!=len(ids) or set(ids)-set(config['segment_ids']):raise ValueError('INVALID_EVIDENCE duplicate/unexpected segment ID')
 official=official_summary(result,config)
 if any(s['status']=='INVALID_EVIDENCE' for s in official['segments']):raise ValueError('INVALID_EVIDENCE segment identity/interval')
 cond=conditions(result,config);reserves=[];comp=[];choices=[]
 for row,c in zip(official['segments'],config['run']):
  seg=next((x for x in raw if x.get('segment_id')==row['segment_id']),{})
  rr=reserve_rows(seg,c);reserves.append(dict(segment_id=row['segment_id'],rows=rr))
  cc=comparisons(seg,row,pred['segments'][c['cell']]);comp.append(dict(segment_id=row['segment_id'],comparisons=cc))
  psel=selection['by_period_ns'][str(c['period_ns'])];candidate=psel['candidates'][c['plan']]
  accepted=candidate['accepted']; official_status=[x.get('deadline_status',x.get('status')) for x in row['experts']+row['cycles']+row['refreshes']]
  fail='FAIL' in official_status;uncertain=any(x in ('UNCERTAIN','INCOMPLETE',None) for x in official_status)
  short=any(x['state']=='SHORT' for x in rr);unknown=any(x['state'] in ('UNKNOWN','UNCERTAIN') for x in rr)
  rejected_dimensions=[]
  if not candidate['G2']['pass_']:
   for dimension,metric in [('Expert','ME'),('VLMUnit','MU')]:
    if candidate[metric]<10:rejected_dimensions.append(dimension)
  rejected_short=any(x['state']=='SHORT' and x['job_type'] in rejected_dimensions for x in rr)
  if accepted:verdict='OFFICIAL_COUNTEREXAMPLE' if fail else ('RESERVE_COUNTEREXAMPLE' if short else ('UNCONFIRMED' if uncertain or unknown else 'SUPPORTED_ON_THIS_SEGMENT'))
  else:verdict='REJECTION_SUPPORTED_ON_SAMPLE' if fail or rejected_short else ('UNCONFIRMED' if uncertain or unknown else 'OVER_REJECTION_ON_NOMINAL_SAMPLE_PERTURBATIONS_UNTESTED')
  choices.append(dict(segment_id=row['segment_id'],candidate=c['plan'],model_accepted=accepted,model_selected=psel.get('selected'),condition=cond['status'],nominal_verdict=verdict,domain_verdict=verdict if cond['status']=='MATCH' else cond['status'],rejected_reserve_dimensions=rejected_dimensions))
 checks_ok=bool(result.get('checks')) and all(x.get('pass_') for x in result['checks'])
 complete_segments=len(raw)==8 and all(x.get('status')!='NOT_STARTED' and x.get('manifest') is not None and x.get('t0_ns') is not None and (x.get('validation') or {}).get('pass_') and (x.get('validation') or {}).get('persisted') for x in raw)
 correctness_ok=(result.get('status')==plan.RESULT_STATUS and checks_ok and complete_segments and (result.get('in_process_equivalence') or {}).get('byte_exact') is True and bool(result.get('gates')) and all(g.get('status')=='PASS' for g in result['gates'].values()) and len(result.get('call_ledger') or [])==13400)
 A=dict(status='PASS_ON_RECORDED_MODEL_EVIDENCE' if correctness_ok else 'INCOMPLETE_OR_FAILED_EVIDENCE',recorded_model_status=result.get('status'),checks=result.get('checks',[]),checks_ok=bool(result.get('checks')) and all(x.get('pass_') for x in result['checks']),D1=result.get('in_process_equivalence'),gates=result.get('gates'),segment_validations=[dict(segment_id=s.get('segment_id'),validation=s.get('validation')) for s in raw],scope_and_restore='NOT_IN_MODEL_RESULT; attach independent scope/readback evidence separately')
 return dict(schema='m3_b10_evaluation_v1',protocol=plan.PROTOCOL,fixture=bool(result.get('fixture')),verdict='EVALUATED' if cond['status']=='MATCH' else cond['status'],A_correctness=A,B_official=official,C_reserves=reserves,D_selection=choices,E_prediction=comp,F_conditions=cond,prediction_status='NOT_EVALUABLE' if any(s['status'] in ('NOT_STARTED','MISSING') for s in official['segments']) else ('EVALUATED_EXTRAPOLATION' if cond['status']=='MATCH' else cond['status']),denominator_note='64 Expert / 64 Cycle / 32 Refresh; source/scenario comparisons are not independent GPU runs')

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--result',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--freeze',type=Path,default=HERE/'FREEZE.json');args=ap.parse_args(argv)
 try:
  doc=evaluate(load(args.result),args.freeze);code=0
 except (ValueError,KeyError,TypeError,OSError) as exc:
  doc=dict(verdict='INVALID_EVIDENCE',error=str(exc));code=2
 args.out.mkdir(parents=True,exist_ok=True)
 (args.out/'EVALUATION.json').write_text(json.dumps(doc,indent=2,sort_keys=True)+'\n')
 print(json.dumps(dict(verdict=doc['verdict'],fixture=doc.get('fixture'),exit=code)))
 return code
if __name__=='__main__':raise SystemExit(main())
