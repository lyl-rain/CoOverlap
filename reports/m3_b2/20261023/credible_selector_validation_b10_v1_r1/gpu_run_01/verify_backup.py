#!/usr/bin/env python3
"""Verify the B10 r1 run_01 backup against the board manifest (read-only)."""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
LOCAL = HERE / 'board' / 'run_01'

def sha256(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    board = {}
    for line in (HERE / 'BOARD_FILES.txt').read_text().splitlines():
        if not line.strip(): continue
        mode, uid, size, mtime, path = line.split(None, 4)
        board[path.strip()] = dict(mode=int(mode, 8), uid=int(uid), size=int(size), path=path.strip())
    hashes = {}
    for line in (HERE / 'BOARD_SHA256.txt').read_text().splitlines():
        if not line.strip(): continue
        d, p = line.split(None, 1)
        hashes[p.strip().lstrip('./')] = d
    local = {p.relative_to(LOCAL).as_posix(): p for p in LOCAL.rglob('*') if p.is_file()}
    total_board = sum(r['size'] for r in board.values())
    rows, missing, size_bad, sha_bad = [], [], [], []
    copied = 0
    for rel, meta in sorted(board.items()):
        name = rel.lstrip('./'); p = local.get(name); d = hashes.get(name)
        if p is None:
            missing.append(dict(path=name, size=meta['size'], sha256=d,
                                reason='root-only unreadable' if d is None else 'absent'))
            continue
        size = p.stat().st_size; copied += size; ld = sha256(p)
        state = 'OK'
        if size != meta['size']: size_bad.append(dict(path=name, board=meta['size'], local=size)); state='SIZE'
        if d is not None and ld != d: sha_bad.append(dict(path=name, board=d, local=ld)); state='SHA'
        rows.append(dict(path=name, state=state, size=size, sha256=d))
    extra = sorted(set(local) - {k.lstrip('./') for k in board})
    unreadable = [m for m in missing if m['sha256'] is None]
    hard = [m for m in missing if m['sha256'] is not None]
    status = 'PASS_WITH_ROOT_ONLY_UNARCHIVED' if (not hard and not size_bad and not sha_bad and not extra and unreadable) else ('PASS' if (not missing and not size_bad and not sha_bad and not extra) else 'INCOMPLETE')
    (HERE / 'LOCAL_SHA256.txt').write_text(''.join('%s  %s\n' % (sha256(local[k]), k) for k in sorted(local)))
    doc = dict(schema='m3_b10_backup_verification_v1', status=status,
               source=dict(files=len(board), bytes=total_board),
               local=dict(files=len(local), bytes=copied),
               matched=dict(files=sum(1 for r in rows if r['state']=='OK'),
                            bytes=sum(r['size'] for r in rows if r['state']=='OK')),
               missing=missing, hard_missing=hard, size_mismatch=size_bad,
               sha_mismatch=sha_bad, extra_local=extra,
               root_only=[dict(path=m['path'], size=m['size'], sha256=None, state='UNARCHIVED') for m in unreadable],
               recovery_handoff=dict(dir='recovery_readback_codex_20261023', files=5,
                                     note='handoff copies are local evidence, not board source files; excluded from source counts'),
               note='counts are physical files/bytes; the manifest files themselves are transfer metadata, not source data')
    (HERE / 'BACKUP_VERIFICATION.json').write_text(json.dumps(doc, indent=2, sort_keys=True) + '\n')
    md = ['# BACKUP_VERIFICATION — B10 r1 run 01', '', 'status: **%s**' % status, '',
          '|项|值|', '|---|---|',
          '|源 `run_01/`|%d 文件，%d 字节（%.2f GiB）|' % (len(board), total_board, total_board/2**30),
          '|本地 `board/run_01`|%d 文件，%d 字节|' % (len(local), copied),
          '|逐文件 OK|%d|' % doc['matched']['files'],
          '|缺失|%d（root-only 不可读 %d，硬缺失 %d）|' % (len(missing), len(unreadable), len(hard)),
          '|大小不符|%d|' % len(size_bad), '|SHA 不符|%d|' % len(sha_bad), '|本地多余|%d|' % len(extra), '',
          '|分类|内容|', '|---|---|',
          '|源原始数据|板端 `run_01/` 的 %d 个文件（模型输出、留存、scope 记录）|' % len(board),
          '|传输清单|`BOARD_FILES.txt`、`BOARD_SHA256.txt`、`LOCAL_SHA256.txt`（元数据，不计入源字节）|',
          '|恢复交接证据|`recovery_readback_codex_20261023/`（5 文件，本地证据，不算板端源文件）|',
          '|本地派生|`analysis/`、`closeout_eval/`、`RUN_REPORT*`、本文件|', '',
          'root-only（仅元数据，无内容 SHA）：']
    for m in unreadable:
        md.append('- `%s`：%d 字节 — **UNARCHIVED**' % (m['path'], m['size']))
    if extra: md += ['', '本地多余：'] + ['- `%s`' % e for e in extra]
    md += ['', 'source/scenario 比较不是独立 GPU 运行；backup 计数不包含 tar 流大小。', '']
    (HERE / 'BACKUP_VERIFICATION.md').write_text('\n'.join(md))
    print(json.dumps(dict(status=status, source=doc['source'], local=doc['local'],
                          matched=doc['matched'], missing=len(missing), root_only=len(unreadable),
                          size_bad=len(size_bad), sha_bad=len(sha_bad), extra=len(extra)), indent=2))
    return 0 if status.startswith('PASS') else 1

if __name__ == '__main__':
    sys.exit(main())
