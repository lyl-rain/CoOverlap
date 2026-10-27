"""CPU-only absolute cross-process policy. In-process checks remain byte exact."""
import math,struct
POLICY={'id':'absolute_cross_process_v1','bf16_max_abs':0.015625,'action_f32_max_abs':0.01,'relative_tolerance':None,'in_process':'raw bytes exact','statement':'cross-process absolute tolerance; not bitwise; cause UNKNOWN'}
def evaluate(actual,reference,kind,shape,reference_shape):
    if tuple(shape)!=tuple(reference_shape):raise ValueError('shape mismatch')
    count=math.prod(shape);width=2 if kind=='bf16' else 4 if kind=='f32' else 0
    if not width or len(actual)!=count*width or len(reference)!=count*width:raise ValueError('dtype/byte count mismatch')
    def decode(data):
        if kind=='f32':return struct.unpack('<'+str(count)+'f',data)
        return tuple(struct.unpack('<f',struct.pack('<I',v<<16))[0] for v in struct.unpack('<'+str(count)+'H',data))
    a,b=decode(actual),decode(reference);finite=all(math.isfinite(v) for v in a+b)
    delta=[abs(x-y) if math.isfinite(x) and math.isfinite(y) else float('inf') for x,y in zip(a,b)]
    worst=max(range(count),key=delta.__getitem__);max_abs=delta[worst]
    index=[];flat=worst
    for dim in reversed(shape):index.append(flat%dim);flat//=dim
    threshold=POLICY['bf16_max_abs'] if kind=='bf16' else POLICY['action_f32_max_abs']
    return dict(pass_=finite and max_abs<=threshold,byte_exact=actual==reference,finite=finite,max_abs=max_abs if finite else None,threshold=threshold,mismatch_elements=sum(x!=y for x,y in zip(a,b)),elements=count,max_abs_index=list(reversed(index)),actual_value=a[worst] if math.isfinite(a[worst]) else None,reference_value=b[worst] if math.isfinite(b[worst]) else None,actual_nonfinite=sum(not math.isfinite(x) for x in a),reference_nonfinite=sum(not math.isfinite(x) for x in b),shape=list(shape),criterion='absolute only; no rtol or epsilon')
