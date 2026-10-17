"""Indexed raw byte packs; segment commits retain every tensor and check."""
import contextlib, hashlib, json, os, time
from pathlib import Path

class EvidenceIO:
    def __init__(self,root):
        self.root=Path(root);self.metrics={k:dict(calls=0,ns=0) for k in ('comparison','serialization','write','persistence')}
        self.diag=(self.root/'diagnostics.jsonl').open('x')
        self.index=(self.root/'RAW_INDEX.jsonl').open('x')
        self.pack=(self.root/'RAW_TENSORS.bin').open('xb')
        self.pending=[];self.sequence=0;self.ns=0
    @contextlib.contextmanager
    def phase(self,key):
        t=time.monotonic_ns()
        try:yield
        finally:self.metrics[key]['calls']+=1;self.metrics[key]['ns']+=time.monotonic_ns()-t
    def encode(self,obj):
        with self.phase('serialization'):return json.dumps(obj,separators=(',',':'))
    def append(self,kind,value):
        self.sequence+=1;s=self.encode(dict(seq=self.sequence,kind=kind,value=value))+'\n'
        with self.phase('write'):self.diag.write(s);self.diag.flush()
    def json_file(self,path,obj):
        s=self.encode(obj)
        with self.phase('write'):
            with Path(path).open('w') as f:f.write(s)
        self.pending.append(Path(path))
    def tensor(self,name,array):
        with self.phase('serialization'):
            data=array.tobytes();meta=dict(shape=list(array.shape),storage_dtype=str(array.dtype),nbytes=array.nbytes,sha256=hashlib.sha256(data).hexdigest())
        if name.startswith('seg'):
            offset=self.pack.tell()
            with self.phase('write'):self.pack.write(data)
            record=self.encode(dict(name=name,file='RAW_TENSORS.bin',offset=offset,**meta))+'\n'
            with self.phase('write'):self.index.write(record);self.index.flush()
        else:
            p=self.root/(name+'.bin')
            with self.phase('write'):
                with p.open('xb') as f:f.write(data)
            self.pending.append(p);self.json_file(self.root/(name+'.json'),meta)
        return array
    def commit(self,report):
        # Commit after raw readback and all mandatory checks, before next segment.
        with self.phase('persistence'):
            for f in (self.pack,self.index,self.diag):f.flush();os.fsync(f.fileno())
            for p in self.pending:
                with p.open('rb') as f:os.fsync(f.fileno())
            self.pending.clear()
        report['off_window_costs']=self.metrics.copy()
        s=self.encode(report);tmp=self.root/'result.json.tmp'
        with self.phase('write'):
            with tmp.open('w') as f:f.write(s);f.flush()
        with self.phase('persistence'):
            with tmp.open('rb') as f:os.fsync(f.fileno())
            os.replace(tmp,self.root/'result.json')
            fd=os.open(self.root,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        self.ns=sum(v['ns'] for v in self.metrics.values())
