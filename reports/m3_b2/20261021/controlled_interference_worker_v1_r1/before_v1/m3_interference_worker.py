"""Window-gated CPU11 memmove worker for controlled-interference experiments.

This is a THIN adaptation of the already accepted guard/copy primitive in
`m1_memcpy_interference_v4.py`:

  * reuse: `GuardedBuffer`, `copy_once`, the 64-byte two-sided guards, the two
    32 MiB payloads, the exact capacity/length checks, CPU11 affinity,
    PR_SET_PDEATHSIG, the ordinary-user requirement and SIGTERM handling;
  * change: no output directory and no JSON/log/progress file is written at all;
    the worker reports readiness and final evidence on stdout (a pipe) and
    counters/heartbeat in shared memory, so the declared experiment window has
    no file I/O and no JSON serialization;
  * change: the worker no longer has a fixed 90 s lifetime.  It is gated by an
    absolute monotonic start/end pair pre-declared by the caller and never
    starts copying before `start_ns`;
  * change: there is no full 32 MiB preflight memmove before the window.  Only
    buffer allocation/pattern initialisation and guard checks happen before the
    window; the first 32 MiB copy is at or after `start_ns`.

The worker never adapts capacity or intensity at runtime.  `copy_bytes` counts
logical memmove bytes; it is NOT measured DRAM bandwidth.
"""
import argparse
import ctypes as C
import hashlib
import json
import os
import signal
import struct
import sys
import time
import traceback
from pathlib import Path

# Reuse the accepted guarded-copy primitive; the historical file is not modified.
from m1_memcpy_interference_v4 import GuardedBuffer, copy_once

WORKER_VERSION = "m3_ci_worker_v1"
FIXED_CPU = 11
FIXED_BYTES = 32 * 1024 * 1024
FIXED_GUARD = 64
SOURCE_PATTERN = 0x5A
DEST_PATTERN = 0x00

HEARTBEAT_MAGIC = 0x434F5648  # "COVH"
HEARTBEAT_STRUCT = struct.Struct("<QQQQQ")  # magic, copies, bytes, now_ns, state
HEARTBEAT_SIZE = 64
STATE_READY = 1
STATE_RUNNING = 2
STATE_STOPPED = 3
STATE_FAILED = 4
STATE_NAMES = {STATE_READY: "READY", STATE_RUNNING: "RUNNING",
               STATE_STOPPED: "STOPPED", STATE_FAILED: "FAILED"}


class WorkerConfigError(ValueError):
    pass


class GuardFailure(RuntimeError):
    pass


def config_fingerprint():
    """Canonical, JSON-free fingerprint of the fixed intensity configuration."""
    fields = (
        "schema=m3_ci_worker_v1",
        "version=" + WORKER_VERSION,
        "cpu=%d" % FIXED_CPU,
        "src=%d" % FIXED_BYTES,
        "dst=%d" % FIXED_BYTES,
        "len=%d" % FIXED_BYTES,
        "guard=%d" % FIXED_GUARD,
        "src_pattern=%d" % SOURCE_PATTERN,
        "dst_pattern=%d" % DEST_PATTERN,
    )
    return hashlib.sha256("|".join(fields).encode("ascii")).hexdigest()


def validate_config(cpu, source_capacity_bytes, dest_capacity_bytes,
                    copy_length_bytes, guard_bytes, source_pattern, dest_pattern):
    if cpu != FIXED_CPU:
        raise WorkerConfigError("cpu must be %d" % FIXED_CPU)
    if (source_capacity_bytes, dest_capacity_bytes, copy_length_bytes) != (
            FIXED_BYTES, FIXED_BYTES, FIXED_BYTES):
        raise WorkerConfigError("fixed source/destination capacity and copy length required")
    if guard_bytes != FIXED_GUARD:
        raise WorkerConfigError("guard must be %d bytes" % FIXED_GUARD)
    if source_pattern != SOURCE_PATTERN or dest_pattern != DEST_PATTERN:
        raise WorkerConfigError("fixed source/destination patterns required")
    if not (0 <= source_pattern <= 255 and 0 <= dest_pattern <= 255):
        raise WorkerConfigError("patterns must be bytes")


def heartbeat_encode(buf, *, seq, copies, copy_bytes, now_ns, state):
    """Seqlock write: odd sequence, fixed-width data, even sequence.

    Cost: three stores into one shared cache line.  There is no allocation,
    syscall or JSON/log serialization in this path.
    """
    if len(buf) < HEARTBEAT_SIZE:
        raise ValueError("heartbeat buffer too small")
    struct.pack_into("<Q", buf, 0, seq + 1)
    HEARTBEAT_STRUCT.pack_into(buf, 8, HEARTBEAT_MAGIC, int(copies),
                               int(copy_bytes), int(now_ns), int(state))
    struct.pack_into("<Q", buf, 0, seq + 2)
    return seq + 2


def heartbeat_decode(buf):
    """Return a consistent heartbeat or None if the seqlock is torn/unwritten."""
    if len(buf) < HEARTBEAT_SIZE:
        raise ValueError("heartbeat buffer too small")
    seq_one = struct.unpack_from("<Q", buf, 0)[0]
    if seq_one == 0 or (seq_one & 1):
        return None
    magic, copies, copy_bytes, now_ns, state = HEARTBEAT_STRUCT.unpack_from(buf, 8)
    seq_two = struct.unpack_from("<Q", buf, 0)[0]
    if seq_one != seq_two or magic != HEARTBEAT_MAGIC:
        return None
    return dict(seq=seq_one, magic=magic, copies=copies, copy_bytes=copy_bytes,
                heartbeat_ns=now_ns, state=state,
                state_name=STATE_NAMES.get(state, "UNKNOWN"))


def checked_guards(src, dst):
    try:
        src.check()
        dst.check()
    except RuntimeError as exc:
        if "MEMCPY_GUARD_CORRUPTION" in str(exc):
            raise GuardFailure("MEMCPY_GUARD_CORRUPTION") from exc
        raise


def copy_window(*, clock, start_ns, end_ns, copy_bytes_per_op, copy_fn,
                guard_check, heartbeat, stop_requested, parent_alive,
                heartbeat_interval_ns=250_000_000,
                guard_interval_ns=1_000_000_000,
                max_sleep_ns=1_000_000,
                sleep_fn=None):
    """Run the copy loop strictly between pre-declared monotonic instants.

    This function is the actual loop used by `main()`.  It never calls
    `copy_fn` before `start_ns`.  The end check happens before each copy, so a
    copy that starts before `end_ns` may finish slightly after it; no new copy
    is started after `end_ns`.  There is no adaptive duration or intensity.
    """
    sleep_fn = sleep_fn or (lambda ns: time.sleep(max(0, ns) / 1e9))
    if end_ns <= start_ns:
        raise WorkerConfigError("end_ns must be greater than start_ns")
    if copy_bytes_per_op <= 0:
        raise WorkerConfigError("positive copy_bytes_per_op required")
    if heartbeat_interval_ns <= 0 or guard_interval_ns <= 0 or max_sleep_ns <= 0:
        raise WorkerConfigError("positive heartbeat/guard/sleep bounds required")

    copies = 0
    copy_bytes = 0
    actual_start_ns = None
    actual_end_ns = None
    exit_reason = "window_elapsed"
    error = None
    guard_status = "PASS"

    # Wait for the pre-declared start without producing pressure.  Sleep is
    # bounded so a SIGTERM/parent death is observed promptly.
    while True:
        now = clock.monotonic_ns()
        if now >= start_ns:
            break
        if stop_requested():
            exit_reason = "stopped_before_start"
            actual_end_ns = now
            break
        if not parent_alive():
            exit_reason = "parent_exit_before_start"
            actual_end_ns = now
            break
        remaining = start_ns - now
        sleep_fn(min(remaining, max_sleep_ns))

    if exit_reason == "window_elapsed":
        actual_start_ns = clock.monotonic_ns()
        last_heartbeat_ns = actual_start_ns
        last_guard_ns = actual_start_ns
        try:
            heartbeat(copies, copy_bytes, actual_start_ns, STATE_RUNNING)
        except Exception as exc:  # heartbeat failure is an evidence failure
            exit_reason = "heartbeat_error"
            error = repr(exc)
            guard_status = "FAIL"

        while exit_reason == "window_elapsed":
            now = clock.monotonic_ns()
            if now >= end_ns:
                exit_reason = "window_elapsed"
                break
            if stop_requested():
                exit_reason = "sigterm"
                break
            if not parent_alive():
                exit_reason = "parent_exit"
                break
            try:
                copy_fn()
            except Exception as exc:
                exit_reason = "copy_error"
                error = repr(exc)
                guard_status = "FAIL"
                break
            copies += 1
            copy_bytes += copy_bytes_per_op
            now = clock.monotonic_ns()
            try:
                if now - last_guard_ns >= guard_interval_ns:
                    guard_check()
                    last_guard_ns = now
            except GuardFailure as exc:
                exit_reason = "guard_failure"
                error = str(exc)
                guard_status = "FAIL"
                break
            if now - last_heartbeat_ns >= heartbeat_interval_ns:
                try:
                    heartbeat(copies, copy_bytes, now, STATE_RUNNING)
                    last_heartbeat_ns = now
                except Exception as exc:
                    exit_reason = "heartbeat_error"
                    error = repr(exc)
                    guard_status = "FAIL"
                    break

    if actual_end_ns is None:
        actual_end_ns = clock.monotonic_ns()

    # Guard checks are always performed at the end, including the paths that
    # never started (no copy call happened).
    try:
        guard_check()
    except GuardFailure as exc:
        exit_reason = "guard_failure"
        error = str(exc)
        guard_status = "FAIL"

    state = STATE_STOPPED if guard_status == "PASS" and exit_reason not in (
        "copy_error", "heartbeat_error") else STATE_FAILED
    try:
        heartbeat(copies, copy_bytes, actual_end_ns, state)
    except Exception as exc:
        if error is None:
            error = repr(exc)
        guard_status = "FAIL"

    return dict(
        worker_version=WORKER_VERSION,
        declared_start_ns=start_ns,
        declared_end_ns=end_ns,
        actual_start_ns=actual_start_ns,
        actual_end_ns=actual_end_ns,
        copies=copies,
        copy_bytes=copy_bytes,
        copy_bytes_per_op=copy_bytes_per_op,
        guards=guard_status,
        exit_reason=exit_reason,
        error=error,
        start_lateness_ns=(actual_start_ns - start_ns
                           if actual_start_ns is not None else None),
        end_overrun_ns=actual_end_ns - end_ns,
        active_ns=(actual_end_ns - actual_start_ns
                   if actual_start_ns is not None else 0),
    )


def _require_linux_worker_identity(parent_pid):
    if not sys.platform.startswith("linux"):
        raise WorkerConfigError("the real pressure worker requires Linux")
    from m1_run_identity import require_nvidia
    identity = require_nvidia()
    libc = C.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [C.c_int, C.c_ulong, C.c_ulong, C.c_ulong, C.c_ulong]
    libc.prctl.restype = C.c_int
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0):
        raise OSError(C.get_errno(), "PR_SET_PDEATHSIG")
    if os.getppid() != parent_pid:
        raise RuntimeError("parent changed before readiness")
    os.sched_setaffinity(0, {FIXED_CPU})
    if os.sched_getaffinity(0) != {FIXED_CPU}:
        raise RuntimeError("affinity mismatch")
    return identity


def _emit(obj):
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")
    sys.stdout.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parent", required=True, type=int)
    ap.add_argument("--start-ns", required=True, type=int)
    ap.add_argument("--end-ns", required=True, type=int)
    ap.add_argument("--config-fingerprint", required=True)
    ap.add_argument("--shm-name", required=True)
    ap.add_argument("--cpu", type=int, default=FIXED_CPU)
    ap.add_argument("--source-capacity", type=int, default=FIXED_BYTES)
    ap.add_argument("--dest-capacity", type=int, default=FIXED_BYTES)
    ap.add_argument("--copy-length", type=int, default=FIXED_BYTES)
    ap.add_argument("--guard-bytes", type=int, default=FIXED_GUARD)
    ap.add_argument("--source-pattern", type=int, default=SOURCE_PATTERN)
    ap.add_argument("--dest-pattern", type=int, default=DEST_PATTERN)
    ap.add_argument("--heartbeat-interval-ns", type=int, default=250_000_000)
    ap.add_argument("--guard-interval-ns", type=int, default=1_000_000_000)
    ap.add_argument("--max-sleep-ns", type=int, default=1_000_000)
    args = ap.parse_args(argv)

    shm = None
    try:
        validate_config(args.cpu, args.source_capacity, args.dest_capacity,
                        args.copy_length, args.guard_bytes,
                        args.source_pattern, args.dest_pattern)
        if args.end_ns <= args.start_ns:
            raise WorkerConfigError("end_ns must be greater than start_ns")
        if args.config_fingerprint != config_fingerprint():
            raise WorkerConfigError("config fingerprint mismatch")
        identity = _require_linux_worker_identity(args.parent)

        src = GuardedBuffer(args.source_capacity, args.source_pattern)
        dst = GuardedBuffer(args.dest_capacity, args.dest_pattern)
        checked_guards(src, dst)

        from multiprocessing import shared_memory
        try:
            shm = shared_memory.SharedMemory(name=args.shm_name, track=False)
        except TypeError:  # Python < 3.13
            shm = shared_memory.SharedMemory(name=args.shm_name)

        stopped = [False]

        def _stop(signum, frame):
            stopped[0] = True

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

        seq = [0]

        def heartbeat(copies, copy_bytes, now_ns, state):
            seq[0] = heartbeat_encode(shm.buf, seq=seq[0], copies=copies,
                                      copy_bytes=copy_bytes, now_ns=now_ns,
                                      state=state)

        def guard_check():
            checked_guards(src, dst)

        def copy_fn():
            copy_once(src.payload, dst.payload, args.copy_length)

        def parent_alive():
            return os.getppid() == args.parent

        ready_ns = time.monotonic_ns()
        heartbeat(0, 0, ready_ns, STATE_READY)
        script_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        guard_module_sha = hashlib.sha256(
            Path(sys.modules[GuardedBuffer.__module__].__file__).read_bytes()).hexdigest()
        _emit(dict(
            ok=True, ready=True, phase="ready", worker_version=WORKER_VERSION,
            pid=os.getpid(), parent_pid=args.parent, identity=identity,
            declared_start_ns=args.start_ns, declared_end_ns=args.end_ns,
            config_fingerprint=args.config_fingerprint,
            cpu=args.cpu, copy_length_bytes=args.copy_length,
            guard_bytes=args.guard_bytes, source_pattern=args.source_pattern,
            dest_pattern=args.dest_pattern, source=src.info(), dest=dst.info(),
            affinity=sorted(os.sched_getaffinity(0)),
            script_sha256=script_sha, guard_module_sha256=guard_module_sha,
            ready_ns=ready_ns, heartbeat="shared_memory_seqlock",
            pre_window_copy_ops=0,
        ))

        result = copy_window(
            clock=time, start_ns=args.start_ns, end_ns=args.end_ns,
            copy_bytes_per_op=args.copy_length, copy_fn=copy_fn,
            guard_check=guard_check, heartbeat=heartbeat,
            stop_requested=lambda: stopped[0], parent_alive=parent_alive,
            heartbeat_interval_ns=args.heartbeat_interval_ns,
            guard_interval_ns=args.guard_interval_ns,
            max_sleep_ns=args.max_sleep_ns,
            sleep_fn=lambda ns: time.sleep(max(0, ns) / 1e9),
        )
        ok = (result["guards"] == "PASS" and result["exit_reason"] in (
            "window_elapsed", "sigterm", "parent_exit", "stopped_before_start"))
        emitted_ns = time.monotonic_ns()
        _emit(dict(ok=ok, ready=False, phase="final", pid=os.getpid(),
                   parent_pid=args.parent, identity=identity,
                   config_fingerprint=args.config_fingerprint,
                   script_sha256=script_sha,
                   guard_module_sha256=guard_module_sha,
                   affinity=sorted(os.sched_getaffinity(0)),
                   heartbeat_final=heartbeat_decode(shm.buf),
                   parent_exit=(os.getppid() != args.parent),
                   emitted_ns=emitted_ns,
                   emitted_inside_declared_window=(emitted_ns < args.end_ns),
                   source=src.info(), dest=dst.info(),
                   copy_length_bytes=args.copy_length,
                   guard_bytes=args.guard_bytes, **result))
        return 0 if ok else 2
    except BaseException as exc:
        _emit(dict(ok=False, ready=False, phase="error", error=repr(exc),
                   error_type=type(exc).__name__,
                   pid=os.getpid(), parent_pid=args.parent,
                   worker_version=WORKER_VERSION))
        traceback.print_exc(file=sys.stderr)
        return 2
    finally:
        if shm is not None:
            try:
                shm.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
