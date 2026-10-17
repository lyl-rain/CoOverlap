"""Second independent 8SM group from the existing installed Runtime API."""
import ctypes as C
from green_runtime_resource import Runtime
class PairRuntime(Runtime):
    def __init__(self,lib,log):
        super().__init__(lib,log);self.ctx_b=C.c_void_p();self.green_b=C.c_void_p()
    def setup(self):
        info=super().setup()
        if len(self.groups)!=2 or self.groups[1].data.sm.smCount!=8:raise RuntimeError('requires two legal 8SM groups from single split')
        self.desc_b=C.c_void_p()
        self.call('cudaDevResourceGenerateDesc',C.byref(self.desc_b),C.byref(self.groups[1]),1)
        self.call('cudaGreenCtxCreate',C.byref(self.ctx_b),self.desc_b,0,0)
        self.call('cudaExecutionCtxStreamCreate',C.byref(self.green_b),self.ctx_b,1,0)
        return dict(**info,green_b_context=self.ctx_b.value,green_b_stream=self.green_b.value,group_indices=[0,1])
    def close(self):
        if self.green_b.value:self.call('cudaStreamDestroy',self.green_b);self.green_b.value=None
        if self.ctx_b.value:self.call('cudaExecutionCtxDestroy',self.ctx_b);self.ctx_b.value=None
        super().close()
