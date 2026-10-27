"""Reuse the EXACT passed preparation/D1 body, pinned by source SHA.

Only its preparation try-body through D1 is compiled as a callable; the M2
argument parser, one-shot authorization, gates and replay are never executed.
This avoids maintaining a second mathematical/reference setup implementation.
No CUDA imports/side effects until the newly authorized M3 caller invokes it.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import time
from m2_executor import Snapshot
from pi05_m2_correctness_v3 import sha

SOURCE_SHA = 'd91cdc465b87f1c76bc985cb0ea475176fe20cbf579dd2c8c824a92bef96ba18'


def preparation_audit():
    source=Path(__file__).with_name('pi05_m2_clean.py')
    data=source.read_bytes()
    if hashlib.sha256(data).hexdigest()!=SOURCE_SHA:
        raise ValueError('passed M2 preparation source changed; refuse before GPU import')
    tree=ast.parse(data,filename=str(source))
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    body=next(n for n in main.body if isinstance(n,ast.Try)).body
    end=next(i for i,n in enumerate(body) if isinstance(n,ast.ImportFrom) and n.module=='m2_clean_cuda')
    prefix=body[:end]
    if not any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Subscript) and isinstance(t.slice,ast.Constant)
        and t.slice.value=='in_process_equivalence' for t in n.targets) for n in prefix):
        raise ValueError('D1 inclusion boundary changed')
    return source,prefix,dict(source_sha256=SOURCE_SHA,statements=len(prefix),
        prefix_AST_sha256=hashlib.sha256(ast.dump(ast.Module(body=prefix,type_ignores=[]),include_attributes=False).encode()).hexdigest(),
        policy='original AST statements unchanged, through strict D1; no M2 entry/authorization/replay')


def prepare(args,report,save,require,bound):
    source,prefix,_=preparation_audit()
    # Parameters become closure variables of the original nested callbacks.
    fn=ast.parse('def reused(args,report,save,require,bound):\n return locals()').body[0]
    fn.body=prefix+fn.body
    module=ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))
    namespace=dict(globals())
    exec(compile(module,str(source),'exec'),namespace)
    return namespace['reused'](args,report,save,require,bound)
