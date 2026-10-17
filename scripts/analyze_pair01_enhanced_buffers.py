"""Offline enhanced probe: view/token sections, prestate hashes, transfer checks."""
from pathlib import Path
import csv,hashlib,json,numpy as np
base=Path('reports/m1_recovery/pair01_access_recovery');p=base/'raw/cooverlap_pair_enhanced_20261014_01'
h=json.loads((base/'raw/cooverlap_pair_enhanced_sha.json').read_text());assert all(hashlib.sha256((p/k).read_bytes()).hexdigest()==v for k,v in h.items())
def load(name,shape):
 raw=(p/(name+'.bin')).read_bytes();u=np.frombuffer(raw,dtype='<u2').reshape(shape);return u,(u.astype('<u4')<<16).view('<f4')
def compare(a,b):
 u,x=a;v,y=b;d=np.abs(x.astype(float)-y.astype(float));return dict(different=int((u!=v).sum()),elements=u.size,max_abs=float(d.max()),finite=bool(np.isfinite(x).all() and np.isfinite(y).all()),sha_current=hashlib.sha256(u.tobytes()).hexdigest(),sha_reference=hashlib.sha256(v.tobytes()).hexdigest())
res={'transfer_files_verified':len(h),'segments':[],'pre':[]}
for name,shape,segment in [('images',(2,224,224,3),True),('language',(49,2048),False),('rope',(561,256),False)]:
 a=load('Pair01_pre_v1_'+name,shape);b=load('reference_S1_pre_'+name,shape)
 for i in range(2) if segment else [None]:res['pre'].append(dict(buffer=name,view=i,**compare((a[0][i],a[1][i]) if i is not None else a,(b[0][i],b[1][i]) if i is not None else b)))
for name,shape in [('vision_x',(512,1152)),('vision_x_pooled',(512,1152))]:
 a=load('Pair01_post_'+name,shape);b=load('reference_S1_post_'+name,shape)
 for i in range(2):
  sl=slice(i*256,(i+1)*256);res['segments'].append(dict(buffer=name,layer=None,section='view'+str(i+1),**compare((a[0][sl],a[1][sl]),(b[0][sl],b[1][sl]))))
for name,shape in [('K',(9,561,256)),('V',(9,561,256)),('x',(1,561,2048))]:
 a=load('Pair01_boundary_'+name,shape);b=load('reference_S1_boundary_'+name,shape)
 for layer in range(shape[0]):
  for section,lo,hi in [('view1',0,256),('view2',256,512),('language',512,561)]:res['segments'].append(dict(buffer=name,layer=layer if name!='x' else 8,section=section,**compare((a[0][layer,lo:hi],a[1][layer,lo:hi]),(b[0][layer,lo:hi],b[1][layer,lo:hi]))))
(base/'buffer_analysis.json').write_text(json.dumps(res,indent=2)+'\n')
with (base/'buffer_segments.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(res['segments'][0]));w.writeheader();w.writerows(res['segments'])
for which in ['Pair01_pre_resources','Pair01_post_resources']:
 m=json.loads((p/(which+'.json')).read_text())
 with (base/(which+'.csv')).open('w') as f:
  w=csv.writer(f);w.writerow(['name','ptr','nbytes','owner','dtype','role'])
  for group in ['writable','shared_readonly']:
   for v in m[group]:w.writerow([v['name'],v['ptr'],v['nbytes'],v.get('owner'),v['dtype'],group])
print(json.dumps(dict(transfer_verified=len(h),pre=res['pre'],vision=res['segments'][:4]),indent=2))
