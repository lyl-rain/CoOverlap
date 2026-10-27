"""One math implementation shared by eager and graph paths (CPU stand-in).

The real backend calls the frozen FlashRT ops; here the same callables write
deterministic bytes so the contract (same function, same buffers, same outputs)
is testable on CPU.  Signatures must stay stable under capture.
"""


def context_b1(buf, layers=9, salt=1):
    for i in range(layers):
        buf[i % len(buf)] = (buf[i % len(buf)] + salt + i) & 0xFF
    return dict(kind='B1', layers=layers)


def context_b2(buf, layers=9, salt=2):
    for i in range(layers):
        buf[i % len(buf)] = (buf[i % len(buf)] + salt + i) & 0xFF
    return dict(kind='B2', layers=layers)


def expert10(buf, steps=10, layers=18, version=0):
    for s in range(steps):
        for l in range(layers):
            buf[(s * layers + l) % len(buf)] = (version + s + l) & 0xFF
    return dict(kind='E10', steps=steps, layers=layers, version=version)
