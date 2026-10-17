"""One bounded sequential B1/B2 boundary-switch experiment, shared controls."""
import time
START=time.monotonic()
import os,json,ctypes as C,hashlib,signal,traceback,collections
from pathlib import Path
OUT=Path(os.environ['COOVERLAP_RUN_DIR']);OUT.mkdir(exist_ok=False,parents=True)
r=dict(status='INCOMPLETE',samples=[],checks=[],api=[],ledger={},phases=[],cleanup='NOT_REACHED')
def save():
 with (OUT/'result.json').open('w') as f:json.dump(r,f,indent=2);f.flush();os.fsync(f.fileno())
def phase(s):r['phases'].append(dict(name=s,elapsed_s=time.monotonic()-START));save()
def stop(signum,frame):r['status']='INCOMPLETE_TIMEOUT';r['signal']=signum;save();raise SystemExit(124)
signal.signal(signal.SIGTERM,stop);save()
def sha(b):return hashlib.sha256(b).hexdigest()
def check(v,name):
 r['checks'].append(dict(name=name,pass_=bool(v)));save()
 if not v:raise AssertionError(name)
def budget():
 if time.monotonic()-START>108:raise TimeoutError('reserve final live checks and cleanup; no new work after soft 108s')
def store(name,b,shape):
 with (OUT/(name+'.bin')).open('xb') as f:f.write(b);f.flush();os.fsync(f.fileno())
 (OUT/(name+'.json')).write_text(json.dumps(dict(sha256=sha(b),nbytes=len(b),logical_dtype='bfloat16',shape=shape)))
phase('imports')
import numpy as np
import torch
import flash_rt_gemm_diag as diag
from flash_rt.core.cuda_buffer import _cudart,CudaBuffer
from flash_rt.frontends.torch.pi05_rtx import Pi05TorchFrontendRtx
from flash_rt.models.pi05.pipeline_rtx import VIS_D,VIS_H,ENC_D,BF16
from pi05_dual_slot_adapter import CHECKPOINT,PROMPT,_collect
from green_runtime_resource import Runtime
rt=None
try:
 cfgpath=Path(os.environ['COOVERLAP_PROTOCOL']);cfg=json.loads(cfgpath.read_text());r['protocol']=cfg;r['script_sha256']=sha(Path(__file__).read_bytes());r['protocol_sha256']=sha(cfgpath.read_bytes());save()
 check(r['protocol_sha256']==os.environ['COOVERLAP_PROTOCOL_SHA'],'protocol_sha')
 check(cfg['warmup_order']==['A','B','C'] and cfg['formal_rounds']==[['A','B','C'],['B','C','A'],['C','A','B']],'fixed_approved_order')
 check(sha(Path(diag.__file__).read_bytes())=='bee648c5b5a9821084a39bb88ed9cba9681503c1043f90a7c95ace0bb1048d78','existing_isolated_extension_sha')
 r['extension']=diag.__file__;r['runtime_maps']=[l for l in Path('/proc/self/maps').read_text().splitlines() if 'libcudart' in l];save()
 torch.cuda.init();torch.cuda.synchronize();rt=Runtime(_cudart,r['api']);r['resources']=rt.setup();save()
 normal=torch.cuda.ExternalStream(rt.ordinary.value,device=0);green=torch.cuda.ExternalStream(rt.green.value,device=0)
 check(rt.resource(normal.cuda_stream)==16 and rt.resource(green.cuda_stream)==8,'existing_16_8_resource_points');phase('resources_done')
 fpath=Path('/tmp/cooverlap_pi05_fixed_reference.npz');f=np.load(fpath,allow_pickle=False);r['inputs']={k:sha(f[k].tobytes()) for k in ['image','wrist_image','state','noise0_bf16_bytes']};r['fixture_sha256']=sha(fpath.read_bytes());save()
 check(r['fixture_sha256']=='92f1a92b64352cc34010c81c1accd1cb00fcb227d0004f545b87549d5d6c544d','fixed_fixture')
 check(sha((CHECKPOINT/'config.json').read_bytes())=='0458a362b574c2cb088ebf3767c9eacb1f040b9cb680a89b594379a4fe36e5f7','checkpoint_config')
 budget();phase('load_checkpoint')
 owner=Pi05TorchFrontendRtx(CHECKPOINT,num_views=2,chunk_size=50,num_steps=10,hardware='rtx_sm87',state_prompt_mode='exact');owner.gemm=diag.GemmRunner();owner.set_prompt(PROMPT,state=f['state']);p=owner.pipeline
 p._bias_zero_buf=CudaBuffer.device_zeros(max(p.vision_seq*3*VIS_D,p.vision_seq*VIS_H),BF16)
 check(p.encoder_seq_len==561 and p._current_prompt_len==49 and p.num_steps==10 and p.chunk_size==50 and p.vision_num_layers==27 and not p._state_active,'fixed_dimensions')
 check(not any(getattr(p,k) for k in ['use_fp8','use_fp8_decoder','use_int8_encoder','use_int8_decoder','use_int8_vision']),'fixed_BF16')
 check(p._graph is None and p._decoder_only_graph is None and all(p.attn._fa2_sites.values()) and not p.attn._fixed_shape,'existing_eager_vendor_FA2_route')
 r['backend']=dict(routes=p.attn._fa2_sites,num_sms_heuristic=p.attn._num_sms);save();phase('autotune')
 p.autotune_gemms();torch.cuda.synchronize();check(p._gemms_autotuned,'original_autotune_once');phase('autotune_done')
 images=owner._stack_images({k:f[k] for k in ['image','wrist_image','state']});noise=torch.from_numpy(f['noise0_bf16_bytes'].copy()).cuda().view(torch.bfloat16).reshape(50,32)
 check(images.shape==(2,224,224,3) and images.dtype==torch.bfloat16,'fixed_preprocess');r['preprocessed_sha256']=sha(images.view(torch.uint8).cpu().numpy().tobytes())
 def mem():
  free,total=torch.cuda.mem_get_info();return dict(cuda_free=free,cuda_total=total,torch_allocated=torch.cuda.memory_allocated(),torch_reserved=torch.cuda.memory_reserved(),torch_peak=torch.cuda.max_memory_allocated(),proc={l.split(':')[0]:l.split(':',1)[1].strip() for l in Path('/proc/self/status').read_text().splitlines() if l.startswith(('VmRSS:','VmHWM:'))})
 r['memory_before']=mem();check(r['memory_before']['cuda_free']>12*1024**3,'memory_floor_before')
 r['owner']='single frontend._ckpt_bf16; one pipeline/backend/runner, sequentially reused';r['gemm_resources_before']=dict(owner.gemm.resource_info());r['buffers_before']=list(_collect(p,'v0.pipeline'))+list(_collect(p.attn,'v0.attn'));save()
 def read(ptr,n):
  buf=C.create_string_buffer(n);rc=_cudart.cudaMemcpy(buf,C.c_void_p(ptr),n,2)
  if rc:raise RuntimeError('D2H CUDA '+str(rc))
  return buf.raw
 def prefix():return tuple(b''.join(read(t.data_ptr()+i*t.stride(0)*t.element_size(),561*256*2) for i in range(18)) for t in [p.attn.enc_K,p.attn.enc_V])
 def context_state():return (read(p.bufs['encoder_x'].ptr.value,561*ENC_D*2),)+prefix()
 r['initial_language_sha256']=sha(read(p._lang_embeds_buf.ptr.value,p._lang_embeds_buf.nbytes));save()
 expected=[0];job=['none'];routing=collections.Counter()
 class Proxy:
  def __init__(self,obj,label):self.obj=obj;self.label=label;self.cache={}
  def __getattr__(self,name):
   fn=getattr(self.obj,name)
   if not callable(fn):return fn
   if name not in self.cache:
    def call(*a,**kw):
     supplied=kw.get('stream')
     if self.label=='FVK' and name in ('patch_im2col','avg_pool_vision_tokens') and 'stream' not in kw:supplied=a[-1] # installed source passes stream as final positional arg
     if supplied!=expected[0]:raise RuntimeError('explicit stream missing/mismatch '+self.label+'.'+name)
     routing[self.label+'.'+name]+=1
     return fn(*a,**kw)
    self.cache[name]=call
   return self.cache[name]
 p.gemm=Proxy(owner.gemm,'GEMM');p.fvk=Proxy(owner.fvk,'FVK')
 oldfa=p.attn._fa2_fwd
 def fa(*a,**kw):
  if kw.get('stream')!=expected[0]:raise RuntimeError('FA2 stream mismatch')
  routing['FA2.fwd']+=1;return oldfa(*a,**kw)
 p.attn._fa2_fwd=fa
 orig_enc=p._encoder_layer
 bank=dict(x=torch.empty(561*ENC_D*2,dtype=torch.uint8,device='cuda'),K=torch.empty((9,561,1,256),dtype=torch.bfloat16,device='cuda'),V=torch.empty((9,561,1,256),dtype=torch.bfloat16,device='cuda'))
 r['boundary_bank']=list(_collect(bank,'boundary_bank'))
 check(not any(max(a['ptr'],b['ptr'])<min(a['ptr']+a['nbytes'],b['ptr']+b['nbytes']) for a in r['boundary_bank'] for b in r['buffers_before']),'boundary_bank_no_model_alias')
 def retain_mid(s):
  rc=_cudart.cudaMemcpyAsync(C.c_void_p(bank['x'].data_ptr()),C.c_void_p(p.bufs['encoder_x'].ptr.value),bank['x'].numel(),3,s.cuda_stream)
  if rc:raise RuntimeError('boundary D2D error '+str(rc))
  bank['K'].copy_(p.attn.enc_K[:9,:561]);bank['V'].copy_(p.attn.enc_V[:9,:561])
 def mid_state():return tuple(read(bank[k].data_ptr(),bank[k].numel()*bank[k].element_size()) for k in ['x','K','V'])
 def enc(i,seq,fuse_b1,stream):
  if stream!=expected[0]:raise RuntimeError('Encoder stream mismatch')
  r['ledger'].setdefault(job[0],{}).setdefault('encoder',[]).append(i);orig_enc(i,seq,fuse_b1,stream)
  if job[0]=='full_reference' and i==8:retain_mid(normal)
 p._encoder_layer=enc
 def block1(s):
  p._copy_lang_embeds_to_encoder_x(s.cuda_stream);p.vision_encoder(s.cuda_stream)
  B,W,fvk,gemm=p.bufs,p.weights,p.fvk,p.gemm;vs=p.vision_seq_enc
  fvk.layer_norm(B['vision_x_pooled'].ptr.value,W['vision_final_norm_w'],W['vision_final_norm_b'],B['vision_x_norm'].ptr.value,vs,VIS_D,1e-5,stream=s.cuda_stream)
  gemm.bf16_nn(B['vision_x_norm'].ptr.value,W['encoder_multi_modal_projector_w'],B['encoder_x'].ptr.value,vs,ENC_D,VIS_D,stream=s.cuda_stream)
  fvk.add_bias_bf16(B['encoder_x'].ptr.value,W['encoder_multi_modal_projector_b'],vs,ENC_D,stream=s.cuda_stream)
  for i in range(9):p._encoder_layer(i,561,False,s.cuda_stream)
 def block2(s):
  for i in range(9,18):p._encoder_layer(i,561,False,s.cuda_stream)
 def upload(s):
  torch.cuda.synchronize()
  t=time.monotonic_ns()
  with torch.cuda.stream(s):
   owner._copy_tensor_to_pipeline_buf_stream(images,p.input_images_buf,s.cuda_stream)
   owner._copy_tensor_to_pipeline_buf_stream(noise,p.input_noise_buf,s.cuda_stream)
  s.synchronize();return (time.monotonic_ns()-t)/1e6
 def saved_state(name):
  state=context_state();mid=mid_state()
  for tag,data,shapes in [('final',state,[[561,2048],[18,561,1,256],[18,561,1,256]]),('mid',mid,[[561,2048],[9,561,1,256],[9,561,1,256]])]:
   for k,v,shape in zip(['x','K','V'],data,shapes):store(name+'_'+tag+'_'+k,v,shape)
  return state,mid
 # Independent original full Context reference; midpoint D2D is stream-ordered,
 # no model layer changes or internal Host scheduling.
 budget();phase('full_reference');job[0]='full_reference';expected[0]=normal.cuda_stream
 upload(normal)
 with torch.cuda.stream(normal):
  p._copy_lang_embeds_to_encoder_x(normal.cuda_stream);p.vision_encoder(normal.cuda_stream);p.transformer_encoder(normal.cuda_stream)
 normal.synchronize();reference_final,reference_mid=saved_state('full_reference')
 check(r['ledger']['full_reference']['encoder']==list(range(18)),'reference_18_layers')
 for data in reference_final+reference_mid:
  bits=np.frombuffer(data,dtype='<u2').astype(np.uint32)<<16
  check(np.isfinite(bits.view(np.float32)).all(),'reference_finite')
 # Prebuild/materialize events, identical data-retention policy in A/B/C.
 event_sets=[]
 for _ in range(13):
  es=[torch.cuda.Event(enable_timing=True) for _ in range(6)]
  for e in es:e.record(normal)
  normal.synchronize();event_sets.append(es)
 event_iter=iter(event_sets)
 mode_streams={'A':(normal,normal),'B':(green,green),'C':(green,normal)}
 def measure(mode,role,index):
  budget();name=f'{mode}_{role}_{index}';job[0]=name;s1=mode_streams[mode][0];expected[0]=s1.cuda_stream
  prep_ms=upload(s1);check(read(p.input_noise_buf.ptr.value,3200)==f['noise0_bf16_bytes'].tobytes(),name+'_fixed_noise')
  a1,e1,a2,e2,ca,cb=next(event_iter);before_route=dict(routing)
  r['active_job']=dict(name=name,mode=mode,role=role,round=index,status='RUNNING');save()
  with torch.cuda.stream(s1):
   check(torch.cuda.current_stream().cuda_stream==s1.cuda_stream,name+'_B1_Torch_stream')
   h0=time.monotonic_ns();a1.record(s1);block1(s1);b1_submit_return=time.monotonic_ns();e1.record(s1);e1.synchronize();h1=time.monotonic_ns();r['active_job'].update(B1_submit_before_ns=h0,B1_complete_ack_ns=h1)
   # Diagnostic boundary state is retained in every mode; its time stays in
   # both the Host gap and tail, outside B1/B2 model Event intervals.
   cp=time.monotonic_ns();ca.record(s1);retain_mid(s1);cb.record(s1);cb.synchronize();cq=time.monotonic_ns()
  s2=mode_streams[mode][1];expected[0]=s2.cuda_stream
  with torch.cuda.stream(s2):
   s2.wait_event(e1) # explicit producer dependency, same call in A/B/C
   if torch.cuda.current_stream().cuda_stream!=s2.cuda_stream:raise RuntimeError('B2 Torch stream mismatch')
   h2=time.monotonic_ns();a2.record(s2);block2(s2);submit2_return=time.monotonic_ns();e2.record(s2);e2.synchronize();h3=time.monotonic_ns()
  rc=_cudart.cudaGetLastError()
  rec=dict(name=name,mode=mode,role=role,round=index,B1_stream=s1.cuda_stream,B2_stream=s2.cuda_stream,B1_submit_before_ns=h0,B1_submit_return_ns=b1_submit_return,B1_complete_ack_ns=h1,B2_submit_before_ns=h2,B2_submit_return_ns=submit2_return,B2_complete_ack_ns=h3,Host_response_ms=(h3-h0)/1e6,Host_gap_ms=(h2-h1)/1e6,Host_tail_ms=(h3-h1)/1e6,B1_event_ms=a1.elapsed_time(e1),B2_event_ms=a2.elapsed_time(e2),B1_cpu_submit_ms=(b1_submit_return-h0)/1e6,B2_cpu_submit_ms=(submit2_return-h2)/1e6,boundary_retention_Host_ms=(cq-cp)/1e6,boundary_retention_event_ms=ca.elapsed_time(cb),input_prepare_ms=prep_ms,cuda_last_error=rc,routing={k:v-before_route.get(k,0) for k,v in routing.items() if v!=before_route.get(k,0)})
  r['samples'].append(rec);r['active_job'].update(status='MODEL_DRAINED',**rec);save()
  if rc:raise RuntimeError('CUDA error '+str(rc))
  final,mid=saved_state(name)
  check(all(a==b for a,b in zip(final,reference_final)),name+'_final_byte_exact')
  check(all(a==b for a,b in zip(mid,reference_mid)),name+'_mid_byte_exact')
  check(r['ledger'][name]['encoder']==list(range(18)),name+'_18_layers_once')
  check(rt.resource(s1.cuda_stream)==(16 if mode=='A' else 8) and rt.resource(s2.cuda_stream)==(8 if mode=='B' else 16),name+'_stream_resources')
  memory=mem();rec['live_memory']=memory;check(memory['cuda_free']>12*1024**3,name+'_memory_floor');save()
 phase('mixed_gate');measure('C','gate',0)
 for mode in cfg['warmup_order']:measure(mode,'warmup',0)
 for j,order in enumerate(cfg['formal_rounds']):
  for mode in order:measure(mode,'formal',j)
 phase('live_final_checks');torch.cuda.synchronize();r['buffers_after']=list(_collect(p,'v0.pipeline'))+list(_collect(p.attn,'v0.attn'));r['gemm_resources_after']=dict(owner.gemm.resource_info());r['memory_after']=mem()
 check({x['name']:(x['ptr'],x['nbytes']) for x in r['buffers_before']}=={x['name']:(x['ptr'],x['nbytes']) for x in r['buffers_after']},'visible_addresses_stable')
 check(r['gemm_resources_before']==r['gemm_resources_after'],'GEMM_resources_stable');check(r['memory_after']['cuda_free']>12*1024**3,'memory_floor_after')
 r['final_language_sha256']=sha(read(p._lang_embeds_buf.ptr.value,p._lang_embeds_buf.nbytes));check(r['final_language_sha256']==r['initial_language_sha256'],'language_immutable');save();rt.close();r['cleanup']='PASS_streams_context_released';r['status']='PASS';save();print(json.dumps({'status':'PASS','out':str(OUT)}),flush=True)
except BaseException:
 if r['status']!='INCOMPLETE_TIMEOUT':r['status']='INCOMPLETE_RESERVED_TAIL' if isinstance(__import__('sys').exc_info()[1],TimeoutError) else 'FAIL'
 r['error']=traceback.format_exc();save()
 if r['status']=='INCOMPLETE_RESERVED_TAIL':
  try:
   torch.cuda.synchronize()
   if 'mem' in globals():r['memory_reserved_tail']=mem()
   if rt is not None:rt.close()
   r['cleanup']='PASS_reserved_tail_cleanup';save()
  except BaseException:r['cleanup_error']=traceback.format_exc();save()
 raise
