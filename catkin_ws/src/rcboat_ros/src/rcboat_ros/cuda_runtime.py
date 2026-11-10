"""Small CUDA runtime binding for static TensorRT I/O; no PyCUDA/context stack."""
import ctypes as ct
import ctypes.util
import numpy as np


class CudaRuntime:
    def __init__(self):
        self.lib=ct.CDLL(ctypes.util.find_library('cudart') or 'libcudart.so.10.2')
        signatures={
            'cudaSetDevice':[ct.c_int],
            'cudaMalloc':[ct.POINTER(ct.c_void_p),ct.c_size_t],
            'cudaFree':[ct.c_void_p],
            'cudaHostAlloc':[ct.POINTER(ct.c_void_p),ct.c_size_t,ct.c_uint],
            'cudaFreeHost':[ct.c_void_p],
            'cudaStreamCreate':[ct.POINTER(ct.c_void_p)],
            'cudaStreamSynchronize':[ct.c_void_p],
            'cudaStreamDestroy':[ct.c_void_p],
            'cudaMemcpyAsync':[ct.c_void_p,ct.c_void_p,ct.c_size_t,ct.c_int,ct.c_void_p],
        }
        for name,args in signatures.items():
            fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=ct.c_int
        self.lib.cudaGetErrorString.argtypes=[ct.c_int];self.lib.cudaGetErrorString.restype=ct.c_char_p
        self.call('cudaSetDevice',0)

    def call(self,name,*args):
        code=getattr(self.lib,name)(*args)
        if code:
            reason=self.lib.cudaGetErrorString(code)
            raise RuntimeError('%s: %s'%(name,reason.decode(errors='replace') if reason else code))

    def allocate(self,shape,dtype):
        dtype=np.dtype(dtype);count=int(np.prod(shape));size=count*dtype.itemsize
        if not 0<size<=32*1024*1024:raise ValueError('static TensorRT buffer exceeds limit')
        host=ct.c_void_p();device=ct.c_void_p()
        self.call('cudaHostAlloc',ct.byref(host),size,0)
        try:
            self.call('cudaMalloc',ct.byref(device),size)
            raw=(ct.c_ubyte*size).from_address(host.value)
            view=np.frombuffer(raw,dtype=dtype,count=count)
            return view,device,host
        except Exception:
            if device.value:self.call('cudaFree',device)
            self.call('cudaFreeHost',host)
            raise

    def stream(self):
        result=ct.c_void_p();self.call('cudaStreamCreate',ct.byref(result));return result

    def copy(self,destination,source,size,direction,stream):
        self.call('cudaMemcpyAsync',destination,source,size,direction,stream)
