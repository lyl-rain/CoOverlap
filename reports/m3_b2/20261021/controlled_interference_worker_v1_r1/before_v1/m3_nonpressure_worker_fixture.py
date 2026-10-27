"""TEST FIXTURE ONLY: non-pressure stand-in for the real memmove worker.

This process speaks the real worker's readiness/final/heartbeat protocol but
performs no memmove and allocates no 32 MiB buffers.  It exists so CPU tests can
exercise the real `SubprocessBackend`/`SubprocessHandle` pipe and shared-memory
path without starting the real pressure worker.  It is never imported by, and
must never be deployed with, the production entry point.
"""
import argparse
import json
import os
import signal
import struct
import time
from multiprocessing import shared_memory

MAGIC = 0x434F5648
STATE_READY = 1
STATE_RUNNING = 2
STATE_STOPPED = 3


def main():
    ap = argparse.ArgumentParser()
    for name in ("--parent", "--start-ns", "--end-ns", "--config-fingerprint",
                 "--shm-name", "--cpu", "--source-capacity", "--dest-capacity",
                 "--copy-length", "--guard-bytes", "--source-pattern",
                 "--dest-pattern", "--heartbeat-interval-ns",
                 "--guard-interval-ns", "--max-sleep-ns"):
        ap.add_argument(name, required=False)
    args, _ = ap.parse_known_args()
    parent = int(args.parent)
    start_ns = int(args.start_ns)
    end_ns = int(args.end_ns)
    cpu = int(args.cpu)
    copy_length = int(args.copy_length)
    guard = int(args.guard_bytes)
    try:
        shm = shared_memory.SharedMemory(name=args.shm_name, track=False)
    except TypeError:  # Python < 3.13
        shm = shared_memory.SharedMemory(name=args.shm_name)
    stop = [False]
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__(0, True))
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__(0, True))
    seq = [0]

    def heartbeat(copies, state):
        struct.pack_into("<Q", shm.buf, 0, seq[0] + 1)
        struct.pack_into("<QQQQQ", shm.buf, 8, MAGIC, copies,
                         copies * copy_length, time.monotonic_ns(), state)
        struct.pack_into("<Q", shm.buf, 0, seq[0] + 2)
        seq[0] += 2

    print(json.dumps(dict(
        ok=True, ready=True, phase="ready", pid=os.getpid(), parent_pid=parent,
        declared_start_ns=start_ns, declared_end_ns=end_ns,
        config_fingerprint=args.config_fingerprint, cpu=cpu,
        copy_length_bytes=copy_length, guard_bytes=guard,
        source_pattern=int(args.source_pattern), dest_pattern=int(args.dest_pattern),
        source={"capacity": int(args.source_capacity)},
        dest={"capacity": int(args.dest_capacity)},
        affinity=[cpu], pre_window_copy_ops=0,
        ready_ns=time.monotonic_ns())), flush=True)
    heartbeat(0, STATE_READY)
    while time.monotonic_ns() < start_ns and not stop[0]:
        time.sleep(0.001)
    actual_start = time.monotonic_ns()
    heartbeat(0, STATE_RUNNING)
    while time.monotonic_ns() < end_ns and not stop[0]:
        time.sleep(0.001)
    actual_end = time.monotonic_ns()
    copies = 7  # protocol-only count; no data movement happened
    heartbeat(copies, STATE_STOPPED)
    print(json.dumps(dict(
        ok=True, ready=False, phase="final", pid=os.getpid(), parent_pid=parent,
        config_fingerprint=args.config_fingerprint,
        declared_start_ns=start_ns, declared_end_ns=end_ns,
        copy_length_bytes=copy_length, guard_bytes=guard, guards="PASS",
        affinity=[cpu], copies=copies, copy_bytes=copies * copy_length,
        actual_start_ns=actual_start, actual_end_ns=actual_end,
        exit_reason="window_elapsed",
        heartbeat_final=dict(seq=seq[0], magic=MAGIC, copies=copies,
                             copy_bytes=copies * copy_length,
                             heartbeat_ns=time.monotonic_ns(),
                             state=STATE_STOPPED, state_name="STOPPED")),
        sort_keys=True), flush=True)
    shm.close()


if __name__ == "__main__":
    main()
