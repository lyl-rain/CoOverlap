"""CUDA 13.2 installed-header ABI; no compilation, Graph or context switching."""
import ctypes as C
class Sm(C.Structure):_fields_=[('smCount',C.c_uint),('minSmPartitionSize',C.c_uint),('smCoscheduledAlignment',C.c_uint),('flags',C.c_uint)]
class ResUnion(C.Union):_fields_=[('sm',Sm),('reserved',C.c_ubyte*40)]
class Resource(C.Structure):_fields_=[('type',C.c_int),('pad',C.c_ubyte*92),('data',ResUnion),('next',C.c_void_p)]
class Dim3(C.Structure):_fields_=[('x',C.c_uint),('y',C.c_uint),('z',C.c_uint)]
assert C.sizeof(Resource)==144 and Resource.data.offset==96 and Resource.next.offset==136
class Runtime:
 def __init__(self,lib,log):
  self.lib=lib;self.log=log;self.ctx=C.c_void_p();self.ordinary=C.c_void_p();self.green=C.c_void_p();self.library=C.c_void_p()
  P=C.c_void_p;R=C.POINTER(Resource);U=C.POINTER(C.c_uint)
  sig={'cudaDeviceGetDevResource':[C.c_int,R,C.c_int],'cudaDevSmResourceSplitByCount':[R,U,R,R,C.c_uint,C.c_uint],'cudaDevResourceGenerateDesc':[C.POINTER(P),R,C.c_uint],'cudaGreenCtxCreate':[C.POINTER(P),P,C.c_int,C.c_uint],'cudaExecutionCtxStreamCreate':[C.POINTER(P),P,C.c_uint,C.c_int],'cudaStreamCreateWithFlags':[C.POINTER(P),C.c_uint],'cudaStreamGetDevResource':[P,R,C.c_int],'cudaExecutionCtxDestroy':[P],'cudaStreamDestroy':[P],'cudaLibraryLoadFromFile':[C.POINTER(P),C.c_char_p,P,P,C.c_uint,P,P,C.c_uint],'cudaLibraryGetKernel':[C.POINTER(P),P,C.c_char_p],'cudaLibraryUnload':[P],'cudaLaunchKernel':[P,Dim3,Dim3,C.POINTER(P),C.c_size_t,P]}
  for name,args in sig.items():
   fn=getattr(lib,name);fn.argtypes=args;fn.restype=C.c_int
 def call(self,name,*args):
  rc=getattr(self.lib,name)(*args);self.log.append(dict(api=name,return_code=rc))
  if rc:raise RuntimeError(f'{name} CUDA status {rc}')
 def setup(self):
  r=Resource();self.call('cudaDeviceGetDevResource',0,C.byref(r),1)
  if r.type!=1 or r.data.sm.smCount!=16 or r.data.sm.minSmPartitionSize>8 or 8%r.data.sm.smCoscheduledAlignment:raise RuntimeError('unexpected device SM granularity')
  n=C.c_uint();self.call('cudaDevSmResourceSplitByCount',None,C.byref(n),C.byref(r),None,0,8)
  if not 1<=n.value<=16:raise RuntimeError('unsafe partition count')
  groups=(Resource*n.value)();remain=Resource();self.call('cudaDevSmResourceSplitByCount',groups,C.byref(n),C.byref(r),C.byref(remain),0,8)
  if groups[0].data.sm.smCount!=8:raise RuntimeError('not exact 8 SM')
  self.desc=C.c_void_p();self.call('cudaDevResourceGenerateDesc',C.byref(self.desc),C.byref(groups[0]),1)
  self.call('cudaGreenCtxCreate',C.byref(self.ctx),self.desc,0,0)
  self.call('cudaStreamCreateWithFlags',C.byref(self.ordinary),1)
  self.call('cudaExecutionCtxStreamCreate',C.byref(self.green),self.ctx,1,0)
  self.groups=groups;self.all=r
  return dict(device_sm=r.data.sm.smCount,min_sm=r.data.sm.minSmPartitionSize,alignment=r.data.sm.smCoscheduledAlignment,green_execution_context=self.ctx.value,ordinary_stream=self.ordinary.value,green_stream=self.green.value)
 def resource(self,stream):
  r=Resource();self.call('cudaStreamGetDevResource',C.c_void_p(stream),C.byref(r),1)
  if r.type!=1:raise RuntimeError('not SM resource')
  return r.data.sm.smCount
 def load_probe(self,path):
  self.call('cudaLibraryLoadFromFile',C.byref(self.library),str(path).encode(),None,None,0,None,None,0)
  self.kernel=C.c_void_p();self.call('cudaLibraryGetKernel',C.byref(self.kernel),self.library,b'_Z5probePiS_i')
 def probe(self,stream,ids,values):
  a=C.c_void_p(ids);b=C.c_void_p(values);n=C.c_int(4096);args=(C.c_void_p*3)(C.cast(C.byref(a),C.c_void_p),C.cast(C.byref(b),C.c_void_p),C.cast(C.byref(n),C.c_void_p))
  self.call('cudaLaunchKernel',self.kernel,Dim3(64,1,1),Dim3(64,1,1),args,0,C.c_void_p(stream))
 def close(self):
  if self.library.value:self.call('cudaLibraryUnload',self.library);self.library=C.c_void_p()
  for obj in [self.ordinary,self.green]:
   if obj.value:self.call('cudaStreamDestroy',obj);obj.value=None
  if self.ctx.value:self.call('cudaExecutionCtxDestroy',self.ctx);self.ctx=C.c_void_p()
