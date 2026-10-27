"""CUDA 13.2 installed-header ABI; sequential legal Green contexts with variable SM quota.

This module is a copy of the already-verified green_runtime_resource.py extended to
create and destroy one Green execution context at a time for a list of legal SM
quotas. It does not switch the driver current context, does not reset the device,
does not capture/replay a graph, and does not change any model math.
"""
import ctypes as C


class Sm(C.Structure):
    _fields_ = [('smCount', C.c_uint), ('minSmPartitionSize', C.c_uint),
                ('smCoscheduledAlignment', C.c_uint), ('flags', C.c_uint)]


class ResUnion(C.Union):
    _fields_ = [('sm', Sm), ('reserved', C.c_ubyte * 40)]


class Resource(C.Structure):
    _fields_ = [('type', C.c_int), ('pad', C.c_ubyte * 92),
                ('data', ResUnion), ('next', C.c_void_p)]


class Dim3(C.Structure):
    _fields_ = [('x', C.c_uint), ('y', C.c_uint), ('z', C.c_uint)]


assert C.sizeof(Resource) == 144 and Resource.data.offset == 96 and Resource.next.offset == 136


class QuotaRuntime:
    def __init__(self, lib, log):
        self.lib = lib
        self.log = log
        self.device = Resource()
        self.ordinary = C.c_void_p()
        self.library = C.c_void_p()
        self.green = C.c_void_p()
        self.green_stream = C.c_void_p()
        self.desc = C.c_void_p()
        P = C.c_void_p
        R = C.POINTER(Resource)
        U = C.POINTER(C.c_uint)
        sig = {
            'cudaDeviceGetDevResource': [C.c_int, R, C.c_int],
            'cudaDevSmResourceSplitByCount': [R, U, R, R, C.c_uint, C.c_uint],
            'cudaDevResourceGenerateDesc': [C.POINTER(P), R, C.c_uint],
            'cudaGreenCtxCreate': [C.POINTER(P), P, C.c_int, C.c_uint],
            'cudaExecutionCtxStreamCreate': [C.POINTER(P), P, C.c_uint, C.c_int],
            'cudaStreamCreateWithFlags': [C.POINTER(P), C.c_uint],
            'cudaStreamGetDevResource': [P, R, C.c_int],
            'cudaExecutionCtxDestroy': [P],
            'cudaStreamDestroy': [P],
            'cudaLibraryLoadFromFile': [C.POINTER(P), C.c_char_p, P, P, C.c_uint, P, P, C.c_uint],
            'cudaLibraryGetKernel': [C.POINTER(P), P, C.c_char_p],
            'cudaLibraryUnload': [P],
            'cudaLaunchKernel': [P, Dim3, Dim3, C.POINTER(P), C.c_size_t, P],
        }
        for name, args in sig.items():
            fn = getattr(lib, name)
            fn.argtypes = args
            fn.restype = C.c_int

    def call(self, name, *args):
        rc = getattr(self.lib, name)(*args)
        self.log.append(dict(api=name, return_code=rc))
        if rc:
            raise RuntimeError(f'{name} CUDA status {rc}')

    def init_device(self):
        self.call('cudaDeviceGetDevResource', 0, C.byref(self.device), 1)
        sm = self.device.data.sm
        if self.device.type != 1 or sm.smCount != 16:
            raise RuntimeError('unexpected device SM count')
        if sm.minSmPartitionSize < 2 or sm.smCoscheduledAlignment <= 0:
            raise RuntimeError('unexpected SM granularity')
        self.call('cudaStreamCreateWithFlags', C.byref(self.ordinary), 1)
        return dict(device_sm=sm.smCount, min_sm=sm.minSmPartitionSize,
                    alignment=sm.smCoscheduledAlignment,
                    ordinary_stream=self.ordinary.value)

    def create_green(self, q):
        sm = self.device.data.sm
        if q < sm.minSmPartitionSize or q > sm.smCount:
            raise ValueError(f'quota {q} outside legal range')
        if q % sm.smCoscheduledAlignment:
            raise ValueError(f'quota {q} not aligned')
        # Resource objects are per-call; the device resource itself is read-only.
        dev = Resource()
        self.call('cudaDeviceGetDevResource', 0, C.byref(dev), 1)
        n = C.c_uint()
        self.call('cudaDevSmResourceSplitByCount', None, C.byref(n), C.byref(dev), None, 0, q)
        if not 1 <= n.value <= 16:
            raise RuntimeError('unsafe partition count')
        groups = (Resource * n.value)()
        remain = Resource()
        self.call('cudaDevSmResourceSplitByCount', groups, C.byref(n), C.byref(dev), C.byref(remain), 0, q)
        if groups[0].data.sm.smCount != q:
            raise RuntimeError(f'not exact {q} SM group')
        desc = C.c_void_p()
        self.call('cudaDevResourceGenerateDesc', C.byref(desc), C.byref(groups[0]), 1)
        ctx = C.c_void_p()
        self.call('cudaGreenCtxCreate', C.byref(ctx), desc, 0, 0)
        stream = C.c_void_p()
        self.call('cudaExecutionCtxStreamCreate', C.byref(stream), ctx, 1, 0)
        self.desc, self.green, self.green_stream = desc, ctx, stream
        self.groups = groups
        self.remain = remain
        return dict(quota=q, green_execution_context=ctx.value, green_stream=stream.value,
                    group_sm_counts=[g.data.sm.smCount for g in groups],
                    remainder_sm=remain.data.sm.smCount)

    def destroy_green(self):
        if self.green_stream.value:
            self.call('cudaStreamDestroy', self.green_stream)
            self.green_stream = C.c_void_p()
        if self.green.value:
            self.call('cudaExecutionCtxDestroy', self.green)
            self.green = C.c_void_p()
        self.desc = C.c_void_p()

    def resource(self, stream):
        r = Resource()
        self.call('cudaStreamGetDevResource', C.c_void_p(stream), C.byref(r), 1)
        if r.type != 1:
            raise RuntimeError('not SM resource')
        return r.data.sm.smCount

    def load_probe(self, path):
        self.call('cudaLibraryLoadFromFile', C.byref(self.library), str(path).encode(),
                  None, None, 0, None, None, 0)
        self.kernel = C.c_void_p()
        self.call('cudaLibraryGetKernel', C.byref(self.kernel), self.library, b'_Z5probePiS_i')

    def probe(self, stream, ids, values):
        a = C.c_void_p(ids)
        b = C.c_void_p(values)
        n = C.c_int(4096)
        args = (C.c_void_p * 3)(C.cast(C.byref(a), C.c_void_p),
                                C.cast(C.byref(b), C.c_void_p),
                                C.cast(C.byref(n), C.c_void_p))
        self.call('cudaLaunchKernel', self.kernel, Dim3(64, 1, 1), Dim3(64, 1, 1),
                  args, 0, C.c_void_p(stream))

    def close(self):
        try:
            self.destroy_green()
        finally:
            if self.library.value:
                self.call('cudaLibraryUnload', self.library)
                self.library = C.c_void_p()
            if self.ordinary.value:
                self.call('cudaStreamDestroy', self.ordinary)
                self.ordinary = C.c_void_p()
