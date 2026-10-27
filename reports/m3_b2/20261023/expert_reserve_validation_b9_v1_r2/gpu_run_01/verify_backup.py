#!/usr/bin/env python3
"""Verify the B9-r2 run_01 backup against the board-side manifest.

Reads BOARD_FILES.txt (mode, uid, size, mtime, path) and BOARD_SHA256.txt from the
board, compares the local copy file by file, writes LOCAL_SHA256.txt and
BACKUP_VERIFICATION.md.  Read-only: it never contacts the board and never touches
the original data.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCAL = HERE / 'board' / 'run_01'


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_manifest():
    rows = {}
    for line in (HERE / 'BOARD_FILES.txt').read_text().splitlines():
        if not line.strip():
            continue
        mode, uid, size, mtime, path = line.split(None, 4)
        rows[path.strip()] = dict(mode=int(mode, 8), uid=int(uid), size=int(size),
                                  mtime=float(mtime), path=path.strip())
    return rows


def load_hashes():
    out = {}
    for line in (HERE / 'BOARD_SHA256.txt').read_text().splitlines():
        if not line.strip():
            continue
        digest, path = line.split(None, 1)
        out[path.strip().lstrip('./')] = digest
    return out


def main():
    board = load_manifest()
    hashes = load_hashes()
    local = {p.relative_to(LOCAL).as_posix(): p for p in LOCAL.rglob('*') if p.is_file()}
    total_board = sum(r['size'] for r in board.values())
    rows, missing, size_mismatch, sha_mismatch = [], [], [], []
    copied_bytes = 0
    for rel, meta in sorted(board.items()):
        name = rel.lstrip('./')
        path = local.get(name)
        digest = hashes.get(name)
        if path is None:
            missing.append(dict(path=name, size=meta['size'], mode=meta['mode'],
                                uid=meta['uid'], sha256=digest,
                                reason='root-only unreadable' if digest is None else 'absent'))
            rows.append(dict(path=name, state='UNARCHIVED', board_size=meta['size'],
                             local_size=None, sha256=digest))
            continue
        size = path.stat().st_size
        copied_bytes += size
        local_digest = sha256(path)
        state = 'OK'
        if size != meta['size']:
            size_mismatch.append(dict(path=name, board=meta['size'], local=size))
            state = 'SIZE_MISMATCH'
        if digest is not None and local_digest != digest:
            sha_mismatch.append(dict(path=name, board=digest, local=local_digest))
            state = 'SHA_MISMATCH'
        rows.append(dict(path=name, state=state, board_size=meta['size'], local_size=size,
                         sha256=digest, local_sha256=local_digest))
    extra = sorted(set(local) - {k.lstrip('./') for k in board})
    unreadable = [r for r in missing if r['sha256'] is None]
    hard_missing = [r for r in missing if r['sha256'] is not None]
    ok = not hard_missing and not size_mismatch and not sha_mismatch and not extra
    (HERE / 'LOCAL_SHA256.txt').write_text(''.join(
        '%s  %s\n' % (sha256(local[k]), k) for k in sorted(local)))
    # duplicate check: board_small vs board
    dup = {}
    for name in ('model/result.json', 'model/cycles.csv', 'model/operations.csv',
                 'model/refreshes.csv'):
        a = HERE / 'board_small' / name
        b = LOCAL / name
        if a.exists() and b.exists():
            dup[name] = dict(equal=sha256(a) == sha256(b), sha256=sha256(b))
    root_only = [dict(path=k.lstrip('./'), size=v['size'], mode=oct(v['mode']), uid=v['uid'])
                 for k, v in board.items() if hashes.get(k.lstrip('./')) is None]
    status = ('PASS_WITH_ROOT_ONLY_UNARCHIVED' if ok and unreadable
              else ('PASS' if ok else 'INCOMPLETE'))
    doc = dict(schema='m3_b9_backup_verification_v1', status=status,
               source=dict(files=len(board), bytes=total_board),
               local=dict(files=len(local), bytes=copied_bytes),
               matched=dict(files=sum(1 for r in rows if r['state'] == 'OK'),
                            bytes=sum(r['local_size'] for r in rows if r['state'] == 'OK')),
               missing=missing, hard_missing=hard_missing,
               unarchived_root_only=unreadable,
               size_mismatch=size_mismatch, sha_mismatch=sha_mismatch,
               extra_local=extra, root_only=root_only, duplicates=dup,
               note='counts are physical files and bytes; no archive/stream size used')
    (HERE / 'BACKUP_VERIFICATION.json').write_text(json.dumps(doc, indent=2, sort_keys=True) + '\n')
    lines = ['# BACKUP_VERIFICATION — B9-r2 run 01', '',
             'status: **%s**' % doc['status'], '',
             '|项|值|', '|---|---|',
             '|源（板端 `run_01/`）|%d 文件，%d 字节（%.2f GiB）|' % (
                 len(board), total_board, total_board / 1073741824),
             '|本地 `board/run_01`|%d 文件，%d 字节|' % (len(local), copied_bytes),
             '|逐文件 OK|%d 文件|' % doc['matched']['files'],
             '|缺失|%d（其中 root-only 不可读 %d，硬缺失 %d）|' % (
                 len(missing), len(unreadable), len(hard_missing)),
             '|大小不符|%d|' % len(size_mismatch),
             '|SHA 不符|%d|' % len(sha_mismatch), '|本地多出|%d|' % len(extra), '',
             '|分类|内容|', '|---|---|',
             '|源原始数据|板端 `run_01/` 的 %d 个文件（含 8 段留存、model/result.json、CSV、log、scope 记录）|' % len(board),
             '|传输清单|`BOARD_FILES.txt`、`BOARD_SHA256.txt`、`LOCAL_SHA256.txt`|',
             '|本地派生|`analysis/`、`corrections/`、`RUN_REPORT.md`、本文件|', '',
             'root-only（无内容 SHA，只记元数据）：', '']
    for r in root_only:
        lines.append('- `%s`：size %d, mode %s, uid %d — **UNARCHIVED（不可读）**' % (
            r['path'], r['size'], r['mode'], r['uid']))
    if not root_only:
        lines.append('- 无')
    if missing:
        lines += ['', '缺失文件：'] + ['- `%s`（%s）' % (m['path'], m['reason']) for m in missing]
    lines += ['', '重复文件核对（board_small vs board）：', '']
    for k, v in dup.items():
        lines.append('- `%s`：%s' % (k, '一致' if v['equal'] else '不一致'))
    lines.append('')
    (HERE / 'BACKUP_VERIFICATION.md').write_text('\n'.join(lines))
    print(json.dumps(dict(status=doc['status'], source=doc['source'], local=doc['local'],
                          matched=doc['matched'], missing=len(missing),
                          size_mismatch=len(size_mismatch), sha_mismatch=len(sha_mismatch),
                          extra=len(extra), root_only=len(root_only), duplicates=dup), indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
