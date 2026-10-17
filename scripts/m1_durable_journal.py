"""Append-only off-window diagnostics; atomic report commits remain explicit."""
import json, os, time
from pathlib import Path
class DurableJournal:
    def __init__(self, root):
        self.root=Path(root);self.file=(self.root/'diagnostics.jsonl').open('x',buffering=1)
        self.sequence=0;self.ns=0
    def append(self, kind, value):
        begin=time.monotonic_ns();self.sequence+=1
        self.file.write(json.dumps(dict(seq=self.sequence,kind=kind,value=value),separators=(',',':'))+'\n')
        self.file.flush();os.fsync(self.file.fileno());self.ns+=time.monotonic_ns()-begin
    def commit(self, report):
        begin=time.monotonic_ns();p=self.root/'result.json';tmp=self.root/'result.json.tmp'
        with tmp.open('w') as f:
            json.dump(report,f,separators=(',',':'));f.flush();os.fsync(f.fileno())
        os.replace(tmp,p)
        self.ns+=time.monotonic_ns()-begin
