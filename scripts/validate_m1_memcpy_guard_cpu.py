"""Guard lives inside an allocated backing array; no physical test overrun."""
import ctypes,json,unittest,sys
from pathlib import Path
import m1_memcpy_interference as old
import m1_memcpy_interference_safe as safe

def witness():
    N=8;src=ctypes.create_string_buffer(b'Z'*N)
    owner=(ctypes.c_ubyte*(N+1))(*([0]*N+[0x7b]));dst=(ctypes.c_char*N).from_buffer(owner)
    old.copy_once(src,dst)
    return dict(intended=N,source_capacity=len(src),destination_capacity=len(dst),guard_before=0x7b,guard_after=owner[N],old_guard_preserved=owner[N]==0x7b,old_implementation_safety='FAIL')
class Guard(unittest.TestCase):
    def test_old_guard_witness(self):
        r=witness();self.assertEqual(r['guard_after'],0);self.assertFalse(r['old_guard_preserved'])
    def test_safe_exact_capacity(self):
        N=8;src=ctypes.create_string_buffer(b'Z'*N,N);owner=(ctypes.c_ubyte*(N+1))(*([0]*N+[0x7b]));dst=(ctypes.c_char*N).from_buffer(owner)
        safe.copy_once(src,dst);self.assertEqual(owner[N],0x7b);self.assertEqual(bytes(dst),b'Z'*N)
    def test_safe_rejects_mismatch(self):
        src=ctypes.create_string_buffer(b'Z'*8);dst=ctypes.create_string_buffer(8)
        with self.assertRaises(ValueError):safe.copy_once(src,dst)
if __name__=='__main__':
    print(json.dumps(witness()),flush=True);unittest.main()
