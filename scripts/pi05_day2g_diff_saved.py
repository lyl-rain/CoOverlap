"""Read-only BF16 comparison of two saved Day 2G post-graph runs."""
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

baseline, current = map(Path, sys.argv[1:3])
def decode(two): return struct.unpack('<f',b'\x00\x00'+two)[0]
for name in ('encoder_x_postgraph','enc_K_postgraph','enc_V_postgraph','raw_bf16'):
    a=(baseline/f'replay_0_{name}.bin').read_bytes()
    b=(current/f'replay_0_{name}.bin').read_bytes()
    assert len(a)==len(b) and len(a)%2==0
    mismatch=[i for i in range(0,len(a),2) if a[i:i+2]!=b[i:i+2]]
    result=dict(name=name,bytes=len(a),baseline_sha256=hashlib.sha256(a).hexdigest(),
                current_sha256=hashlib.sha256(b).hexdigest(),
                mismatched_bf16=len(mismatch),first_byte=mismatch[0] if mismatch else None)
    if mismatch:
        i=mismatch[0]
        result['first_values']=[decode(a[i:i+2]),decode(b[i:i+2])]
        if name=='raw_bf16':
            ranked=[]
            for offset in range(0,len(a),2):
                ref,actual=decode(a[offset:offset+2]),decode(b[offset:offset+2])
                if math.isfinite(ref) and math.isfinite(actual):
                    absolute=abs(actual-ref)
                    ranked.append((absolute,absolute/max(abs(ref),1e-6),offset//2,ref,actual))
            largest_abs=max(ranked,key=lambda item:item[0])
            largest_rel=max(ranked,key=lambda item:item[1])
            result['largest_absolute']=dict(value=largest_abs[0],position=[largest_abs[2]//32,largest_abs[2]%32],
                                            reference=largest_abs[3],current=largest_abs[4])
            result['largest_relative']=dict(value=largest_rel[1],position=[largest_rel[2]//32,largest_rel[2]%32],
                                            reference=largest_rel[3],current=largest_rel[4],
                                            denominator='max(abs(reference),1e-6)')
    if name.startswith('enc_') and name!='encoder_x_postgraph':
        stride=611*256*2
        prefix=561*256*2
        result['encoder_prefix_per_layer']=[sum(layer*stride<=i<layer*stride+prefix for i in mismatch)
                                            for layer in range(18)]
        result['decoder_suffix_per_layer']=[sum(layer*stride+prefix<=i<(layer+1)*stride for i in mismatch)
                                           for layer in range(18)]
        earliest=next((i for i in mismatch if i%stride<prefix),None)
        result['first_retained_encoder_prefix_position']=None if earliest is None else [
            earliest//stride,(earliest%stride)//512,(earliest%512)//2]
    print(json.dumps(result,sort_keys=True))
