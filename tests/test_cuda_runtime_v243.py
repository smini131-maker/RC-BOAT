"""Exercise native buffer ownership/copies without loading CUDA or hardware."""
import ctypes as ct
from pathlib import Path
import sys,types,unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'catkin_ws/src/rcboat_ros/src'))
try:
    import numpy as np
    from rcboat_ros import cuda_runtime as module
    from rcboat_ros.balloon_detector import TensorRTBackend
except ImportError:np=None


@unittest.skipIf(np is None,'NumPy unavailable')
class CudaTransferTests(unittest.TestCase):
    def setUp(self):
        self.memory={};self.lib=types.SimpleNamespace()
        def allocate(pointer,size,*args):
            data=ct.create_string_buffer(size);address=ct.addressof(data);self.memory[address]=data
            ct.cast(pointer,ct.POINTER(ct.c_void_p))[0]=address;return 0
        def release(pointer):self.memory.pop(pointer.value);return 0
        def stream(pointer):ct.cast(pointer,ct.POINTER(ct.c_void_p))[0]=123;return 0
        callbacks=dict(cudaSetDevice=lambda *args:0,cudaMalloc=allocate,cudaHostAlloc=allocate,
            cudaFree=release,cudaFreeHost=release,cudaStreamCreate=stream,
            cudaStreamSynchronize=lambda *a:0,cudaStreamDestroy=lambda *a:0,
            cudaMemcpyAsync=lambda dest,src,size,*args:(ct.memmove(dest,src,size) and 0),
            cudaGetErrorString=lambda code:b'simulated CUDA allocation failure')
        for name,callback in callbacks.items():setattr(self.lib,name,Mock(side_effect=callback))
        with patch.object(module.ct,'CDLL',return_value=self.lib),patch.object(module.ctypes.util,'find_library',return_value='fake-cudart'):
            self.cuda=module.CudaRuntime()

    def test_asynchronous_input_output_and_repeated_result_ownership(self):
        backend=TensorRTBackend.__new__(TensorRTBackend);backend.cuda=self.cuda;backend.stream=self.cuda.stream();backend.buffers=[];backend.bindings=[]
        for is_input in (True,False):
            host,device,pinned=self.cuda.allocate((1,2),np.float32)
            backend.buffers.append((host,device,(1,2),is_input,pinned));backend.bindings.append(device.value)
        def execute(bindings,stream):
            src=(ct.c_float*2).from_address(bindings[0]);dest=(ct.c_float*2).from_address(bindings[1])
            for i in range(2):dest[i]=src[i]*2
            return True
        backend.context=types.SimpleNamespace(execute_async_v2=execute)
        try:
            first=backend.run(np.array([[2.,4.]],np.float32));second=backend.run(np.array([[3.,5.]],np.float32))
            np.testing.assert_array_equal(first,[[4.,8.]]);np.testing.assert_array_equal(second,[[6.,10.]])
            with self.assertRaises(ValueError):backend.run(np.ones((2,),np.float32))
        finally:backend.close()
        self.assertEqual(self.memory,{})

    def test_failed_device_allocation_releases_pinned_memory(self):
        self.lib.cudaMalloc.side_effect=lambda *args:2
        with self.assertRaisesRegex(RuntimeError,'CUDA allocation failure'):self.cuda.allocate((4,),np.float32)
        self.assertEqual(self.memory,{})

    def test_oversized_or_empty_buffers_are_rejected_before_allocation(self):
        for shape in [(0,),(100000000,)]:
            with self.assertRaises(ValueError):self.cuda.allocate(shape,np.float32)
        self.lib.cudaHostAlloc.assert_not_called()


if __name__=='__main__':unittest.main()
