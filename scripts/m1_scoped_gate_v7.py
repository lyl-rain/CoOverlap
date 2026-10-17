"""Reference validity and scheduling equivalence are separate contracts.

No tolerance increase: final outputs use the existing absolute_cross_process_v1.
Intermediate cross-process values are saved diagnostics, never a new baseline.
"""
import hashlib,math,struct
from m1_dual_gate import evaluate,POLICY

def intermediate(actual,reference_meta,logical_shape):
    count=math.prod(logical_shape)
    if len(actual)!=count*2 or reference_meta['nbytes']!=len(actual) or reference_meta['storage_dtype']!='uint8':raise ValueError('intermediate BF16 byte count/shape mismatch')
    # BF16 exponent255 flags NaN/Inf without allocating giant Python floats.
    nonfinite=sum((v & 0x7f80)==0x7f80 for (v,) in struct.iter_unpack('<H',actual))
    h=hashlib.sha256(actual).hexdigest()
    return dict(finite=nonfinite==0,nonfinite_elements=nonfinite,sha256=h,nbytes=len(actual),logical_shape=list(logical_shape),old_reference_sha256=reference_meta['sha256'],old_reference_byte_exact=h==reference_meta['sha256'],role='cross-process intermediate diagnostic; not an output tolerance PASS')

def final_gate(actual,reference,kind,shape):
    return evaluate(actual,reference,kind,shape,shape)

def byte_equal(actual,reference):
    return actual==reference
