"""Minimal lifecycle for a window-gated, fixed-intensity CPU11 interference worker.

The component owns at most one worker process.  It supports:

  * quiet mode: no worker is created at all;
  * create -> ready -> wait for a pre-declared monotonic start -> run -> stop
    -> exit confirmation;
  * readiness failure/timeout blocks the experiment window from starting;
  * a bounded TERM/KILL cleanup for the process this component owns only;
  * a single start, no retry, and no automatic restart;
  * in-memory state/counters/timeline; persistence happens only after the
    window has ended (and never inside the window).

The worker starts/stops from pre-declared absolute monotonic instants.  The
controller never extends or shortens interference in response to serial or
boundary completion times.
"""
import copy
import json
import os
import select
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from m3_interference_worker import (
    FIXED_BYTES,
    FIXED_CPU,
    FIXED_GUARD,
    DEST_PATTERN,
    SOURCE_PATTERN,
    HEARTBEAT_SIZE,
    config_fingerprint as worker_config_fingerprint,
    heartbeat_decode,
    validate_config as validate_worker_config,
)

SCHEMA = "m3_interference_lifecycle_v1_r1"
MODES = ("quiet", "fixed")


class LifecycleError(RuntimeError):
    pass


class WindowError(LifecycleError):
    pass


class ReadinessError(LifecycleError):
    pass


class ReadinessTimeout(ReadinessError):
    pass


class WorkerExitedEarly(LifecycleError):
    pass


class CleanupTimeout(LifecycleError):
    pass


class PersistenceError(LifecycleError):
    pass


class State:
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class SystemClock:
    def monotonic_ns(self):
        return time.monotonic_ns()

    def sleep_ns(self, ns):
        time.sleep(max(0, ns) / 1e9)


@dataclass(frozen=True)
class WindowPlan:
    """Pre-declared absolute monotonic window, optionally aligned to replay t0.

    `nominal_end_ns` is the end of the normal experiment window.  `end_ns` is
    the fixed coverage end and includes a policy-independent late-drain
    allowance.  Interference runs from `start_ns` through `end_ns`; it is never
    extended because a particular serial/boundary trajectory drains late.
    """
    start_ns: int
    nominal_end_ns: int
    end_ns: int
    replay_t0_ns: int = None
    nominal_window_ns: int = None
    drain_allowance_ns: int = 0

    @classmethod
    def absolute(cls, start_ns, end_ns):
        return cls(int(start_ns), int(end_ns), int(end_ns))

    @classmethod
    def from_replay_t0(cls, replay_t0_ns, nominal_window_ns, drain_allowance_ns=0):
        t0 = int(replay_t0_ns)
        window = int(nominal_window_ns)
        drain = int(drain_allowance_ns)
        return cls(start_ns=t0, nominal_end_ns=t0 + window,
                   end_ns=t0 + window + drain, replay_t0_ns=t0,
                   nominal_window_ns=window, drain_allowance_ns=drain)

    def validate(self, max_window_ns):
        if self.start_ns < 0:
            raise WindowError("start_ns must be non-negative")
        if self.nominal_end_ns <= self.start_ns:
            raise WindowError("nominal_end_ns must be after start_ns")
        if self.end_ns < self.nominal_end_ns:
            raise WindowError("end_ns must not precede nominal_end_ns")
        if self.end_ns - self.start_ns > max_window_ns:
            raise WindowError("window exceeds max_window_ns")
        if self.drain_allowance_ns < 0:
            raise WindowError("drain_allowance_ns must be non-negative")
        if self.drain_allowance_ns != self.end_ns - self.nominal_end_ns:
            raise WindowError("drain_allowance_ns must equal end_ns - nominal_end_ns")
        if self.replay_t0_ns is not None and self.replay_t0_ns != self.start_ns:
            raise WindowError("replay_t0_ns must equal start_ns")
        if (self.nominal_window_ns is not None
                and self.nominal_end_ns - self.start_ns != self.nominal_window_ns):
            raise WindowError("nominal_window_ns must equal nominal_end_ns - start_ns")

    def as_dict(self):
        return dict(start_ns=self.start_ns, nominal_end_ns=self.nominal_end_ns,
                    end_ns=self.end_ns, replay_t0_ns=self.replay_t0_ns,
                    nominal_window_ns=self.nominal_window_ns,
                    drain_allowance_ns=self.drain_allowance_ns,
                    coverage_rule=(
                        "interference covers [start_ns, end_ns); the normal window "
                        "ends at nominal_end_ns and the fixed late-drain allowance "
                        "is [nominal_end_ns, end_ns); no policy-specific extension"))


@dataclass(frozen=True)
class InterferenceConfig:
    mode: str = "fixed"
    cpu: int = FIXED_CPU
    source_capacity_bytes: int = FIXED_BYTES
    dest_capacity_bytes: int = FIXED_BYTES
    copy_length_bytes: int = FIXED_BYTES
    guard_bytes: int = FIXED_GUARD
    source_pattern: int = SOURCE_PATTERN
    dest_pattern: int = DEST_PATTERN
    ready_timeout_ns: int = 3_000_000_000
    ready_margin_ns: int = 10_000_000
    term_grace_ns: int = 2_000_000_000
    kill_grace_ns: int = 1_000_000_000
    heartbeat_interval_ns: int = 250_000_000
    guard_interval_ns: int = 1_000_000_000
    max_sleep_ns: int = 1_000_000
    start_tolerance_ns: int = 10_000_000
    max_window_ns: int = 600_000_000_000

    def validate(self):
        if self.mode not in MODES:
            raise WindowError("mode must be quiet or fixed")
        validate_worker_config(self.cpu, self.source_capacity_bytes,
                               self.dest_capacity_bytes, self.copy_length_bytes,
                               self.guard_bytes, self.source_pattern,
                               self.dest_pattern)
        for name in ("ready_timeout_ns", "ready_margin_ns", "term_grace_ns",
                     "kill_grace_ns", "heartbeat_interval_ns",
                     "guard_interval_ns", "max_sleep_ns", "max_window_ns"):
            if getattr(self, name) <= 0:
                raise WindowError("%s must be positive" % name)
        if self.ready_timeout_ns <= self.ready_margin_ns:
            raise WindowError("ready_timeout_ns must exceed ready_margin_ns")
        if self.start_tolerance_ns < 0:
            raise WindowError("start_tolerance_ns must be non-negative")

    @property
    def preallocated_buffer_bytes(self):
        return 2 * (FIXED_BYTES + 2 * FIXED_GUARD)

    def fixed_intensity(self):
        return dict(
            kind="CPU11 fixed contiguous libc memmove",
            cpu=FIXED_CPU,
            source_capacity_bytes=FIXED_BYTES,
            dest_capacity_bytes=FIXED_BYTES,
            copy_length_bytes=FIXED_BYTES,
            guard_bytes_per_side=FIXED_GUARD,
            source_pattern=SOURCE_PATTERN,
            dest_pattern=DEST_PATTERN,
            workers=1,
            runtime_adaptation=False,
            source_owner_bytes=FIXED_BYTES + 2 * FIXED_GUARD,
            dest_owner_bytes=FIXED_BYTES + 2 * FIXED_GUARD,
            preallocated_buffer_bytes=self.preallocated_buffer_bytes,
            heartbeat_bytes=HEARTBEAT_SIZE,
            data_buffers_preallocated=True,
            shared_memory_preallocated=True,
            normal_timed_path_file_writes=False,
            python_temporaries_possible=True,
            counter_guard_heartbeat_cost=(
                "present in the normal loop; actual overhead not measured"),
            rss_sampling="not sampled in-window",
            copy_bytes_interpretation=(
                "logical memmove bytes, NOT measured DRAM bandwidth"),
        )

    def fingerprint(self):
        fields = (
            "schema=" + SCHEMA, "mode=" + self.mode, "cpu=%d" % self.cpu,
            "src=%d" % self.source_capacity_bytes,
            "dst=%d" % self.dest_capacity_bytes,
            "len=%d" % self.copy_length_bytes, "guard=%d" % self.guard_bytes,
            "srcp=%d" % self.source_pattern, "dstp=%d" % self.dest_pattern,
            "ready_to=%d" % self.ready_timeout_ns,
            "ready_margin=%d" % self.ready_margin_ns,
            "term=%d" % self.term_grace_ns, "kill=%d" % self.kill_grace_ns,
            "hb=%d" % self.heartbeat_interval_ns,
            "guard_int=%d" % self.guard_interval_ns,
            "sleep=%d" % self.max_sleep_ns,
            "start_tol=%d" % self.start_tolerance_ns,
            "max_window=%d" % self.max_window_ns,
        )
        import hashlib
        return hashlib.sha256("|".join(fields).encode("ascii")).hexdigest()



def _atomic_write_json(path, obj):
    """Create a new evidence file after the window; never overwrite."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        try:
            os.unlink(str(p))
        except OSError:
            pass
        raise
    try:
        dfd = os.open(str(p.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass
    return dict(path=str(p), bytes=len(text.encode("utf-8")),
                sha256=_sha256_text(text), written_ns=time.monotonic_ns())


def _sha256_text(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SubprocessHandle:
    """Handle for one worker process; signals only this process, never a pkill."""

    def __init__(self, proc, shm, clock, plan, config, worker_path):
        self.proc = proc
        self.shm = shm
        self.clock = clock
        self.plan = plan
        self.config = config
        self.worker_path = worker_path
        self.pid = proc.pid
        self.ready_evidence = None
        self.final_evidence = None
        self._stdout_fd = proc.stdout.fileno()
        self._stderr_fd = proc.stderr.fileno()
        self._stdout_buffer = b""
        self._stderr_buffer = b""
        self._readiness_line = None
        self._final_lines = []
        self._cleaned = False

    def _check_owned(self):
        if self.proc.pid != self.pid:
            raise LifecycleError("worker pid identity changed")

    def _read_fd(self, fd, max_bytes=65536):
        ready, _, _ = select.select([fd], [], [], 0)
        if not ready:
            return b""
        return os.read(fd, max_bytes)

    def _take_line(self):
        while b"\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split(b"\n", 1)
            if line.strip():
                return line
        return None

    def wait_ready(self, deadline_ns):
        """Wait for readiness against one absolute monotonic deadline.

        The deadline is supplied by the controller and is not recomputed here;
        spawn time and pipe/parse time therefore consume the same budget.
        """
        deadline = int(deadline_ns)
        while True:
            line = self._take_line()
            if line is not None:
                try:
                    obj = json.loads(line.decode("utf-8"))
                except Exception as exc:
                    raise ReadinessError("invalid readiness line: %r" % (line[:200],)) from exc
                received_ns = self.clock.monotonic_ns()
                if received_ns >= deadline:
                    raise ReadinessTimeout(
                        "readiness line received at/after absolute deadline")
                if obj.get("ready") is True and obj.get("phase") == "ready":
                    self.ready_received_ns = received_ns
                    self.ready_evidence = obj
                    return obj
                raise ReadinessError("worker reported non-ready line: %r" % (obj,))
            if self.proc.poll() is not None:
                self._drain_available()
                raise ReadinessError("worker exited before readiness (code %r, stderr=%r)"
                                     % (self.proc.returncode,
                                        self._stderr_text()[-1000:]))
            remaining = deadline - self.clock.monotonic_ns()
            if remaining <= 0:
                self._drain_available()
                raise ReadinessTimeout("worker readiness timeout")
            wait_s = min(remaining / 1e9, 0.05)
            ready, _, _ = select.select([self._stdout_fd], [], [], wait_s)
            if ready:
                chunk = os.read(self._stdout_fd, 65536)
                if chunk:
                    self._stdout_buffer += chunk
                else:
                    raise ReadinessError("worker stdout closed before readiness")

    def _drain_available(self):
        while True:
            chunk = self._read_fd(self._stdout_fd)
            if not chunk:
                break
            self._stdout_buffer += chunk
        while True:
            chunk = self._read_fd(self._stderr_fd)
            if not chunk:
                break
            self._stderr_buffer += chunk

    def _stderr_text(self):
        return self._stderr_buffer.decode("utf-8", "replace")

    def poll(self):
        return self.proc.poll()

    def terminate(self):
        self._check_owned()
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)

    def kill(self):
        self._check_owned()
        if self.proc.poll() is None:
            self.proc.kill()

    def wait_exit(self, timeout_ns):
        try:
            return self.proc.wait(timeout=max(0, timeout_ns) / 1e9)
        except subprocess.TimeoutExpired:
            return None

    def read_heartbeat(self):
        if self.shm is None:
            return None
        try:
            return heartbeat_decode(self.shm.buf)
        except Exception:
            return None

    def collect_final(self, timeout_ns=None):
        self._drain_available()
        # After the process is reaped, the pipe reaches EOF; read any tail.
        end = self.clock.monotonic_ns() + int(timeout_ns or 0)
        while True:
            chunk = self._read_fd(self._stdout_fd)
            if chunk:
                self._stdout_buffer += chunk
                continue
            if self.proc.poll() is not None:
                break
            if timeout_ns is None or self.clock.monotonic_ns() >= end:
                break
            self.clock.sleep_ns(1_000_000)
        while True:
            chunk = self._read_fd(self._stderr_fd)
            if not chunk:
                break
            self._stderr_buffer += chunk
        lines = [ln for ln in self._stdout_buffer.split(b"\n") if ln.strip()]
        final = None
        for line in reversed(lines):
            try:
                obj = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            if obj.get("phase") in ("final", "error"):
                final = obj
                break
        return dict(final=final, exit_code=self.proc.returncode,
                    stdout_tail=[ln.decode("utf-8", "replace") for ln in lines[-3:]],
                    stderr=self._stderr_text()[-4000:],
                    heartbeat=self.read_heartbeat())

    @staticmethod
    def _close_stream(stream):
        if stream is None:
            return True
        try:
            stream.close()
        except Exception:
            pass
        return bool(getattr(stream, "closed", False))

    def release(self):
        """Idempotently close the resources owned by this handle.

        Resources are only closed after the owned process is confirmed exited.
        If the process is still alive, the call reports resources_released=false
        instead of pretending to have cleaned up.  It does not signal the
        process and never touches another process or shared-memory object.
        """
        self._release_attempts = getattr(self, "_release_attempts", 0) + 1
        process_exit_confirmed = self.proc.poll() is not None
        if not process_exit_confirmed:
            receipt = dict(
                no_owned_process=False, process_exit_confirmed=False,
                stdout_closed=bool(getattr(self.proc.stdout, "closed", False)),
                stderr_closed=bool(getattr(self.proc.stderr, "closed", False)),
                shm_present=self.shm is not None,
                shm_closed=False, shm_unlinked=False,
                resources_released=False,
                release_attempts=self._release_attempts,
                skipped="owned process not confirmed exited")
            self._release_receipt = receipt
            return receipt

        stdout_closed = self._close_stream(self.proc.stdout)
        stderr_closed = self._close_stream(self.proc.stderr)
        shm_present = self.shm is not None
        shm_closed = None
        shm_unlinked = None
        if shm_present:
            try:
                self.shm.close()
            except Exception:
                pass
            shm_closed = getattr(self.shm, "_mmap", None) is None
            try:
                self.shm.unlink()
                shm_unlinked = True
            except FileNotFoundError:
                shm_unlinked = True
            except Exception:
                shm_unlinked = False
        resources_released = bool(
            process_exit_confirmed and stdout_closed and stderr_closed
            and (not shm_present or (shm_closed and shm_unlinked)))
        receipt = dict(
            no_owned_process=False, process_exit_confirmed=True,
            stdout_closed=stdout_closed, stderr_closed=stderr_closed,
            shm_present=shm_present, shm_closed=shm_closed,
            shm_unlinked=shm_unlinked, resources_released=resources_released,
            release_attempts=self._release_attempts)
        self._release_receipt = receipt
        return receipt

    def cleanup(self):
        """Compatibility wrapper; actual per-resource state is in release()."""
        self._cleaned = True
        return self.release()


class SubprocessBackend:
    def __init__(self, worker_path=None, python=None, env=None, clock=None):
        self.worker_path = Path(worker_path or Path(__file__).with_name("m3_interference_worker.py"))
        self.python = python or sys.executable
        self.env = dict(os.environ if env is None else env)
        self.clock = clock or SystemClock()
        self.spawn_count = 0

    def spawn(self, plan, config):
        from multiprocessing import shared_memory
        shm = None
        try:
            try:
                shm = shared_memory.SharedMemory(create=True, size=HEARTBEAT_SIZE,
                                                 track=False)
            except TypeError:  # Python < 3.13
                shm = shared_memory.SharedMemory(create=True, size=HEARTBEAT_SIZE)
            command = [
                self.python, "-B", str(self.worker_path),
                "--parent", str(os.getpid()),
                "--start-ns", str(plan.start_ns),
                "--end-ns", str(plan.end_ns),
                "--config-fingerprint", worker_config_fingerprint(),
                "--shm-name", shm.name,
                "--cpu", str(config.cpu),
                "--source-capacity", str(config.source_capacity_bytes),
                "--dest-capacity", str(config.dest_capacity_bytes),
                "--copy-length", str(config.copy_length_bytes),
                "--guard-bytes", str(config.guard_bytes),
                "--source-pattern", str(config.source_pattern),
                "--dest-pattern", str(config.dest_pattern),
                "--heartbeat-interval-ns", str(config.heartbeat_interval_ns),
                "--guard-interval-ns", str(config.guard_interval_ns),
                "--max-sleep-ns", str(config.max_sleep_ns),
            ]
            proc = subprocess.Popen(
                command, cwd=str(self.worker_path.parent), env=self.env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, bufsize=0, close_fds=True)
            self.spawn_count += 1
            return SubprocessHandle(proc, shm, self.clock, plan, config,
                                    self.worker_path)
        except BaseException:
            if shm is not None:
                try:
                    shm.close()
                    shm.unlink()
                except Exception:
                    pass
            raise


class InterferenceController:
    """Single-use lifecycle for one quiet/fixed interference window."""

    def __init__(self, config=None, *, clock=None, backend=None, persist=None,
                 worker_path=None):
        self.config = config or InterferenceConfig()
        self.config.validate()
        self.clock = clock or SystemClock()
        self.persist = persist or _atomic_write_json
        self.backend = backend or SubprocessBackend(worker_path=worker_path,
                                                    clock=self.clock)
        self.state = State.CREATED
        self.plan = None
        self.handle = None
        self.timeline = []
        self._prepare_called = False
        self._finalize_attempted = False
        self.persisted = False
        self.persistence_status = "NOT_ATTEMPTED"
        self.persistence_error = None
        self.worker_spawn_attempts = 0
        self._stop_requested = False
        self._window_started = False
        self._window_armed = False
        self._window_complete = False
        self._window_start_observed_ns = None
        self._window_end_observed_ns = None
        self.prepare_call_ns = None
        self.readiness_deadline_ns = None
        self.spawn_return_ns = None
        self.ready_received_ns = None
        self.ready_validated_ns = None
        self.failure = None
        self.cancelled = None
        self.ready_evidence = None
        self.worker_final = None
        self.worker_final_heartbeat = None
        self.worker_final_raw = None
        self.heartbeat_final = None
        self.memory_evidence = {}
        self.resource_release = None
        self._resource_release_calls = 0
        self.cleanup = dict(signals=[], term_attempted=False,
                            kill_attempted=False, exit_confirmed=False,
                            process_exit_confirmed=None,
                            stdout_closed=None, stderr_closed=None,
                            shm_present=None, shm_closed=None,
                            shm_unlinked=None, resources_released=False,
                            cleanup_attempted=False, cleanup_complete=False,
                            owned_pid=None)
        self.persistence = None

    # ------------------------------------------------------------------ state
    def _event(self, event, phase, **fields):
        rec = dict(event=event, phase=phase,
                   monotonic_ns=self.clock.monotonic_ns())
        rec.update(fields)
        self.timeline.append(rec)
        return rec

    def _phase(self):
        if not self._window_started:
            return "before_start"
        now = self.clock.monotonic_ns()
        if self.plan is not None and now < self.plan.end_ns:
            return "window"
        return "after_window"

    def _set_failure(self, stage, exc):
        self.failure = dict(stage=stage, error=repr(exc),
                            error_type=type(exc).__name__,
                            detected_ns=self.clock.monotonic_ns(),
                            window_started=self._window_started)
        self._window_armed = self._window_started
        self._event("failure", self._phase(), stage=stage,
                    error=self.failure["error"],
                    error_type=self.failure["error_type"])
        self.state = State.FAILED
        if self.handle is None:
            # No owned process exists (e.g. window validation or spawn failure).
            self.cleanup["cleanup_complete"] = True

    def _cleanup_owned(self, reason, collect=False):
        """Bounded TERM then KILL for the single process this controller owns."""
        if self.cleanup.get("cleanup_complete"):
            return True
        if self.handle is None:
            self.cleanup["cleanup_complete"] = True
            return True
        if self.cleanup.get("cleanup_attempted"):
            return False
        self.cleanup["cleanup_attempted"] = True
        self.cleanup["owned_pid"] = self.handle.pid
        exit_code = self.handle.poll()
        if exit_code is None:
            self.cleanup["term_attempted"] = True
            self.cleanup["signals"].append("SIGTERM")
            self._event("cleanup_signal", self._phase(), signal="SIGTERM",
                        pid=self.handle.pid, reason=reason)
            try:
                self.handle.terminate()
            except Exception as exc:
                self._event("cleanup_signal_error", self._phase(),
                            signal="SIGTERM", error=repr(exc))
            exit_code = self.handle.wait_exit(self.config.term_grace_ns)
            self._event("cleanup_wait", self._phase(), signal="SIGTERM",
                        exit_code=exit_code,
                        bounded_grace_ns=self.config.term_grace_ns)
        if exit_code is None:
            self.cleanup["kill_attempted"] = True
            self.cleanup["signals"].append("SIGKILL")
            self._event("cleanup_signal", self._phase(), signal="SIGKILL",
                        pid=self.handle.pid, reason=reason)
            try:
                self.handle.kill()
            except Exception as exc:
                self._event("cleanup_signal_error", self._phase(),
                            signal="SIGKILL", error=repr(exc))
            exit_code = self.handle.wait_exit(self.config.kill_grace_ns)
            self._event("cleanup_wait", self._phase(), signal="SIGKILL",
                        exit_code=exit_code,
                        bounded_grace_ns=self.config.kill_grace_ns)
        if exit_code is None:
            self.cleanup["exit_confirmed"] = False
            self.cleanup["cleanup_complete"] = False
            self._event("cleanup_incomplete", self._phase(), pid=self.handle.pid)
            return False
        self.cleanup["exit_confirmed"] = True
        self.cleanup["exit_code"] = exit_code
        self.cleanup["exit_confirmed_ns"] = self.clock.monotonic_ns()
        if collect and self.worker_final is None:
            try:
                collected = self.handle.collect_final(self.config.kill_grace_ns)
                self.worker_final = collected.get("final")
                self.worker_final_raw = collected
                self.worker_final_heartbeat = (self.worker_final or {}).get("heartbeat_final")
                self.heartbeat_final = collected.get("heartbeat")
            except Exception as exc:
                self._event("collect_error", self._phase(), error=repr(exc))
        self._snapshot_evidence()
        self.cleanup["cleanup_complete"] = True
        self._event("cleanup_complete", self._phase(), exit_code=exit_code,
                    pid=self.handle.pid)
        return True

    def _snapshot_evidence(self):
        """Copy the evidence needed after shared resources are released."""
        self.memory_evidence = copy.deepcopy(dict(
            ready_evidence=self.ready_evidence,
            worker_final=self.worker_final,
            worker_final_heartbeat=self.worker_final_heartbeat,
            heartbeat_final=self.heartbeat_final,
            worker_final_raw=self.worker_final_raw,
        ))
        return self.memory_evidence

    def _collect_final_if_available(self):
        """Read final stdout/heartbeat before pipes/shared memory are released."""
        if (self.handle is None or self.worker_final is not None
                or self.handle.poll() is None):
            return
        try:
            collected = self.handle.collect_final(self.config.kill_grace_ns)
            self.worker_final = collected.get("final")
            self.worker_final_raw = collected
            self.worker_final_heartbeat = (self.worker_final or {}).get("heartbeat_final")
            self.heartbeat_final = collected.get("heartbeat")
            self._event("collect_final_before_release", self._phase(),
                        has_final=self.worker_final is not None)
        except Exception as exc:
            self._event("collect_error", self._phase(), error=repr(exc))

    def release_resources(self):
        """Release owned process pipes/shared memory, independently of persistence.

        The process must already be confirmed exited; if it is not, the receipt
        reports resources_released=false and leaves the failure state explicit.
        Repeated calls are idempotent.  The evidence snapshot is taken before any
        shared resource is released.
        """
        self._collect_final_if_available()
        self._snapshot_evidence()
        self._resource_release_calls += 1
        if self.handle is None:
            receipt = dict(
                no_owned_process=True, process_exit_confirmed=None,
                stdout_closed=None, stderr_closed=None,
                shm_present=False, shm_closed=None, shm_unlinked=None,
                resources_released=True,
                release_attempts=self._resource_release_calls,
                skipped="no owned process")
        else:
            receipt = self.handle.release()
        self.resource_release = receipt
        self.cleanup.update(dict(
            process_exit_confirmed=receipt.get("process_exit_confirmed"),
            stdout_closed=receipt.get("stdout_closed"),
            stderr_closed=receipt.get("stderr_closed"),
            shm_present=receipt.get("shm_present"),
            shm_closed=receipt.get("shm_closed"),
            shm_unlinked=receipt.get("shm_unlinked"),
            resources_released=bool(receipt.get("resources_released")),
            resource_release_calls=self._resource_release_calls))
        self._event("resources_release", self._phase(),
                    **{k: receipt.get(k) for k in
                       ("process_exit_confirmed", "stdout_closed", "stderr_closed",
                        "shm_present", "shm_closed", "shm_unlinked",
                        "resources_released")})
        return receipt

    # --------------------------------------------------------------- lifecycle
    def prepare(self, plan):
        if self._prepare_called:
            raise LifecycleError("prepare may be called exactly once (no retry)")
        self._prepare_called = True
        if self.state != State.CREATED:
            raise LifecycleError("prepare requires CREATED state")
        try:
            plan = plan if isinstance(plan, WindowPlan) else WindowPlan.absolute(*plan)
            plan.validate(self.config.max_window_ns)
        except Exception as exc:
            self._set_failure("prepare_window", exc)
            raise
        now = self.clock.monotonic_ns()
        if plan.start_ns <= now:
            exc = WindowError("start_ns is not in the future")
            self._set_failure("prepare_window", exc)
            raise exc
        lead = plan.start_ns - now
        if self.config.mode == "fixed" and lead < self.config.ready_margin_ns:
            exc = WindowError("insufficient lead time for worker readiness")
            self._set_failure("prepare_window", exc)
            raise exc
        self.plan = plan
        self.prepare_call_ns = now
        self._event("prepare_begin", "prepare", mode=self.config.mode,
                    start_ns=plan.start_ns, nominal_end_ns=plan.nominal_end_ns,
                    end_ns=plan.end_ns)
        if self.config.mode == "quiet":
            self._event("quiet_no_worker", "prepare",
                        spawned=False, note="quiet mode creates no process")
            self.state = State.READY
            self._window_armed = True
            self._event("prepared", "prepare", ready=True)
            return self

        # One absolute readiness deadline, fixed by config + window start.
        # Spawn, pipe, parse and validation time all consume this same budget.
        self.readiness_deadline_ns = min(
            plan.start_ns - self.config.ready_margin_ns,
            now + self.config.ready_timeout_ns)
        if self.readiness_deadline_ns <= now:
            exc = ReadinessTimeout("no readiness budget before start")
            self._set_failure("readiness", exc)
            raise exc
        self._event("readiness_deadline", "prepare",
                    prepare_call_ns=now,
                    readiness_deadline_ns=self.readiness_deadline_ns)
        self.worker_spawn_attempts += 1
        try:
            self.handle = self.backend.spawn(plan, self.config)
        except Exception as exc:
            self._set_failure("spawn", exc)
            self.release_resources()
            raise ReadinessError("worker spawn failed: %r" % (exc,)) from exc
        self.spawn_return_ns = self.clock.monotonic_ns()
        self.cleanup["owned_pid"] = self.handle.pid
        self._event("spawned", "prepare", pid=self.handle.pid, owned=True,
                    spawn_return_ns=self.spawn_return_ns,
                    readiness_remaining_ns=(
                        self.readiness_deadline_ns - self.spawn_return_ns))
        if self.spawn_return_ns >= self.readiness_deadline_ns:
            exc = ReadinessTimeout(
                "readiness budget exhausted by spawn; no wait attempted")
            self._set_failure("readiness", exc)
            self._cleanup_owned("readiness_deadline_after_spawn", collect=False)
            self.release_resources()
            raise exc
        try:
            ready = self.handle.wait_ready(self.readiness_deadline_ns)
            self.ready_received_ns = self.clock.monotonic_ns()
            self._event("ready_received", "prepare",
                        ready_received_ns=self.ready_received_ns,
                        readiness_deadline_ns=self.readiness_deadline_ns,
                        remaining_ns=(self.readiness_deadline_ns
                                      - self.ready_received_ns))
            if self.ready_received_ns >= self.readiness_deadline_ns:
                raise ReadinessTimeout(
                    "readiness line received at/after absolute deadline")
            self._validate_ready(ready)
            self.ready_validated_ns = self.clock.monotonic_ns()
            self._event("ready_validated", "prepare",
                        ready_validated_ns=self.ready_validated_ns,
                        readiness_deadline_ns=self.readiness_deadline_ns)
            if self.ready_validated_ns >= self.readiness_deadline_ns:
                raise ReadinessTimeout(
                    "readiness validation crossed absolute deadline")
        except Exception as exc:
            self._set_failure("readiness", exc)
            self._cleanup_owned("readiness_failure", collect=False)
            self.release_resources()
            raise
        self.ready_evidence = ready
        self.state = State.READY
        self._window_armed = True
        self._event("worker_ready", "prepare", pid=self.handle.pid,
                    ready_ns=ready.get("ready_ns"),
                    pre_window_copy_ops=ready.get("pre_window_copy_ops"))
        self._event("prepared", "prepare", ready=True)
        return self

    def _validate_ready(self, ready):
        expected = dict(
            ok=True, ready=True, phase="ready",
            parent_pid=os.getpid(), cpu=self.config.cpu,
            copy_length_bytes=self.config.copy_length_bytes,
            guard_bytes=self.config.guard_bytes,
            source_pattern=self.config.source_pattern,
            dest_pattern=self.config.dest_pattern,
            declared_start_ns=self.plan.start_ns,
            declared_end_ns=self.plan.end_ns,
            config_fingerprint=worker_config_fingerprint(),
            pre_window_copy_ops=0,
        )
        bad = {k: (ready.get(k), v) for k, v in expected.items()
               if ready.get(k) != v}
        if self.handle is not None and ready.get("pid") != self.handle.pid:
            bad["pid"] = (ready.get("pid"), self.handle.pid)
        ready_ns = ready.get("ready_ns")
        if not isinstance(ready_ns, int) or ready_ns >= self.plan.start_ns:
            bad["ready_ns"] = (ready_ns, "int before declared start")
        if ready.get("affinity") != [self.config.cpu]:
            bad["affinity"] = (ready.get("affinity"), [self.config.cpu])
        src = ready.get("source") or {}
        dst = ready.get("dest") or {}
        if src.get("capacity") != self.config.source_capacity_bytes:
            bad["source_capacity"] = (src.get("capacity"),
                                      self.config.source_capacity_bytes)
        if dst.get("capacity") != self.config.dest_capacity_bytes:
            bad["dest_capacity"] = (dst.get("capacity"),
                                    self.config.dest_capacity_bytes)
        if bad:
            raise ReadinessError("worker readiness contract mismatch: %r" % (bad,))

    def await_start(self):
        if self.state != State.READY:
            raise LifecycleError("await_start requires READY state")
        if self._window_started:
            return self
        while True:
            now = self.clock.monotonic_ns()
            if now >= self.plan.start_ns:
                break
            if self.handle is not None and self.handle.poll() is not None:
                exc = WorkerExitedEarly("worker exited before start (code %r)"
                                        % (self.handle.poll(),))
                self._set_failure("before_start", exc)
                self._cleanup_owned("before_start_exit", collect=True)
                self.release_resources()
                raise exc
            remaining = self.plan.start_ns - now
            self.clock.sleep_ns(min(remaining, self.config.max_sleep_ns))
        if self.clock.monotonic_ns() >= self.plan.end_ns:
            exc = WindowError("start was observed after the declared end")
            self._set_failure("before_start", exc)
            self._cleanup_owned("start_missed", collect=True)
            self.release_resources()
            raise exc
        if self.handle is not None and self.handle.poll() is not None:
            exc = WorkerExitedEarly("worker exited at start (code %r)"
                                    % (self.handle.poll(),))
            self._set_failure("before_start", exc)
            self._cleanup_owned("start_exit", collect=True)
            self.release_resources()
            raise exc
        self._window_started = True
        self._window_start_observed_ns = self.clock.monotonic_ns()
        self.state = State.RUNNING
        self._event("window_start", "window",
                    observed_ns=self._window_start_observed_ns,
                    declared_start_ns=self.plan.start_ns,
                    parent_observation_lateness_ns=(
                        self._window_start_observed_ns - self.plan.start_ns))
        return self

    def finish(self):
        """Wait to the pre-declared end, then stop/confirm the worker.

        The wait does not poll the worker continuously: detection of an early
        worker exit is deferred to the end of the window so the parent does not
        add in-window polling cost.  A missing worker therefore invalidates the
        window, but does not alter its duration.
        """
        if self.state == State.READY:
            self.await_start()
        if self.state != State.RUNNING:
            raise LifecycleError("finish requires RUNNING state")
        while True:
            now = self.clock.monotonic_ns()
            if now >= self.plan.end_ns:
                break
            self.clock.sleep_ns(min(self.plan.end_ns - now,
                                    self.config.max_sleep_ns))
        self._window_end_observed_ns = self.clock.monotonic_ns()
        self._event("window_end", "after_window",
                    observed_ns=self._window_end_observed_ns,
                    declared_end_ns=self.plan.end_ns)
        # Do not treat a worker that self-stopped at the declared end as an
        # early exit.  The final evidence carries actual_start/actual_end and is
        # validated by stop(); an exit before the declared end is rejected
        # there because actual_end_ns < end_ns.
        return self.stop()

    def _stop_quiet(self, now):
        """A quiet window is complete only after its declared end."""
        if self._window_started and now >= self.plan.end_ns:
            self.state = State.STOPPED
            self._window_complete = True
            self.cleanup["exit_confirmed"] = None
            self.cleanup["process_exit_confirmed"] = None
            self.cleanup["cleanup_complete"] = True
            self._event("quiet_window_complete", "after_window",
                        observed_ns=now, declared_end_ns=self.plan.end_ns,
                        spawned=False)
            return
        reason = ("before_start" if not self._window_started
                  else "before_declared_end")
        exc = LifecycleError(
            "quiet window cancelled or incomplete: %s (now=%d, end=%d)"
            % (reason, now, self.plan.end_ns))
        self.cancelled = dict(reason=reason, observed_ns=now,
                              window_started=self._window_started,
                              declared_start_ns=self.plan.start_ns,
                              declared_end_ns=self.plan.end_ns,
                              no_worker=True)
        self._set_failure("cancelled", exc)
        self.cleanup["exit_confirmed"] = None
        self.cleanup["process_exit_confirmed"] = None
        self.cleanup["cleanup_complete"] = True
        self._event("quiet_cancelled", self._phase(), **self.cancelled)

    def stop(self, *, early=False):
        """Bounded TERM/KILL and exit confirmation for the owned process."""
        if self.state == State.STOPPED:
            return self._summary()
        if self.state == State.FAILED and self.handle is None:
            self.release_resources()
            return self._summary()
        if self.state not in (State.READY, State.RUNNING, State.FAILED):
            raise LifecycleError("stop requires READY/RUNNING/FAILED state")
        now = self.clock.monotonic_ns()
        self._stop_requested = True
        expected_end = self.plan.end_ns if self.plan is not None else None
        self._event("stop_requested", self._phase(), early=bool(early),
                    declared_end_ns=expected_end,
                    before_declared_end=(expected_end is not None and now < expected_end))
        if self.config.mode == "quiet":
            self._stop_quiet(now)
            self.release_resources()
            return self._summary()
        if self.handle is None:
            exc = LifecycleError("no owned worker handle to stop")
            self._set_failure("stop", exc)
            self.release_resources()
            raise exc
        try:
            ok = self._cleanup_owned("early_stop" if early else "window_end",
                                     collect=True)
            if not ok:
                exc = CleanupTimeout("worker did not exit within bounded TERM/KILL")
                self._set_failure("cleanup", exc)
                raise exc
            if self.worker_final is None:
                exc = LifecycleError("worker exited without final evidence")
                self._set_failure("final_evidence_missing", exc)
                raise exc
            self._validate_final()
            if self.state != State.FAILED:
                self.state = State.STOPPED
                self._window_complete = True
            self._event("stopped", "after_window",
                        exit_code=self.cleanup.get("exit_code"))
        finally:
            self.release_resources()
        return self._summary()

    def _validate_final(self):
        final = self.worker_final
        bad = {}
        expected = dict(
            ok=True, phase="final", parent_pid=os.getpid(),
            config_fingerprint=worker_config_fingerprint(),
            declared_start_ns=self.plan.start_ns,
            declared_end_ns=self.plan.end_ns,
            copy_length_bytes=self.config.copy_length_bytes,
            guard_bytes=self.config.guard_bytes,
            guards="PASS",
        )
        for k, v in expected.items():
            if final.get(k) != v:
                bad[k] = (final.get(k), v)
        if final.get("pid") != self.handle.pid:
            bad["pid"] = (final.get("pid"), self.handle.pid)
        if final.get("affinity") != [self.config.cpu]:
            bad["affinity"] = (final.get("affinity"), [self.config.cpu])
        if self.cleanup.get("exit_code") != 0:
            bad["exit_code"] = (self.cleanup.get("exit_code"), 0)
        if final.get("emitted_inside_declared_window") is True:
            bad["emitted_inside_declared_window"] = (True, False)
        fsrc = final.get("source") or {}
        fdst = final.get("dest") or {}
        if fsrc.get("capacity") not in (None, self.config.source_capacity_bytes):
            bad["final_source_capacity"] = (fsrc.get("capacity"),
                                            self.config.source_capacity_bytes)
        if fdst.get("capacity") not in (None, self.config.dest_capacity_bytes):
            bad["final_dest_capacity"] = (fdst.get("capacity"),
                                           self.config.dest_capacity_bytes)
        copies = final.get("copies")
        copy_bytes = final.get("copy_bytes")
        if not isinstance(copies, int) or copies <= 0:
            bad["copies"] = (copies, "positive int for valid fixed work")
        if copy_bytes != (copies or 0) * self.config.copy_length_bytes:
            bad["copy_bytes"] = (copy_bytes,
                                 (copies or 0) * self.config.copy_length_bytes)
        if final.get("work_valid") is not True:
            bad["work_valid"] = (final.get("work_valid"), True)
        if final.get("window_coverage_complete") is not True:
            bad["window_coverage_complete"] = (
                final.get("window_coverage_complete"), True)
        boundary_names = ("copy_loop_enter_ns", "copy_loop_exit_ns",
                          "first_copy_call_ns", "last_copy_return_ns")
        boundary = {}
        for name in boundary_names:
            value = final.get(name)
            if not isinstance(value, int):
                bad[name] = (value, "host monotonic int")
            else:
                boundary[name] = value
        if len(boundary) == len(boundary_names):
            if not (boundary["copy_loop_enter_ns"] <= boundary["first_copy_call_ns"]
                    <= boundary["last_copy_return_ns"] <= boundary["copy_loop_exit_ns"]):
                bad["copy_boundaries"] = (boundary,
                    "loop_enter <= first_call <= last_return <= loop_exit")
        start = final.get("actual_start_ns")
        end = final.get("actual_end_ns")
        if start is None:
            bad["actual_start_ns"] = (start, "present")
        elif start < self.plan.start_ns:
            bad["actual_start_ns"] = (start, ">= declared start")
        elif start > self.plan.start_ns + self.config.start_tolerance_ns:
            bad["actual_start_ns"] = (start, "within start tolerance")
        if end is None:
            bad["actual_end_ns"] = (end, "present")
        elif end < self.plan.end_ns and start is not None:
            # A live worker is stopped at/after the declared end.  Activity
            # that ended before it means the pressure coverage was incomplete.
            exc = WorkerExitedEarly(
                "worker activity ended at %r, before declared end %r"
                % (end, self.plan.end_ns))
            self._set_failure("window", exc)
            raise exc
        elif end < self.plan.end_ns:
            bad["actual_end_ns"] = (end, ">= declared end")
        if isinstance(start, int) and isinstance(end, int) and boundary:
            if start > boundary["copy_loop_enter_ns"]:
                bad["actual_start_vs_loop"] = (start, "<= copy_loop_enter_ns")
            if end < boundary["copy_loop_exit_ns"]:
                bad["actual_end_vs_loop"] = (end, ">= copy_loop_exit_ns")
        if final.get("exit_reason") not in ("window_elapsed", "sigterm"):
            bad["exit_reason"] = (final.get("exit_reason"),
                                  "window_elapsed or sigterm for valid work")
        hb = self.heartbeat_final
        if hb is None:
            bad["heartbeat_final"] = (hb, "valid seqlock record")
        else:
            if hb.get("copies") != copies:
                bad["heartbeat_copies"] = (hb.get("copies"), copies)
            if hb.get("copy_bytes") != copy_bytes:
                bad["heartbeat_bytes"] = (hb.get("copy_bytes"), copy_bytes)
        final_hb = self.worker_final_heartbeat
        if final_hb is None:
            bad["worker_final_heartbeat"] = (final_hb, "final stdout heartbeat present")
        else:
            if final_hb.get("copies") != copies:
                bad["worker_final_heartbeat_copies"] = (final_hb.get("copies"), copies)
            if final_hb.get("copy_bytes") != copy_bytes:
                bad["worker_final_heartbeat_bytes"] = (final_hb.get("copy_bytes"),
                                                       copy_bytes)
        if bad:
            exc = LifecycleError("worker final evidence contract mismatch: %r" % (bad,))
            self._set_failure("final_evidence", exc)
            raise exc

    def abort(self, reason="aborted"):
        if self.state == State.STOPPED:
            self.release_resources()
            return self
        if self.state == State.FAILED:
            if (self.handle is not None and self.handle.poll() is None
                    and not self.cleanup.get("cleanup_attempted")):
                self._cleanup_owned("abort", collect=False)
            self.release_resources()
            return self
        self._event("abort", self._phase(), reason=reason)
        try:
            if self.config.mode == "quiet" and self.state in (State.READY, State.RUNNING):
                self.stop(early=True)
            elif self.handle is not None and self.handle.poll() is None:
                self.stop(early=True)
        except Exception as exc:
            self._event("abort_cleanup_error", self._phase(), error=repr(exc))
            if not self.cleanup.get("cleanup_attempted"):
                self._cleanup_owned("abort", collect=False)
        finally:
            self.release_resources()
        if self.state != State.FAILED:
            self._set_failure("abort", LifecycleError(reason))
        return self

    # -------------------------------------------------------------- persistence
    def _fixed_work_valid(self):
        final = self.worker_final or {}
        return bool(final.get("copies", 0) > 0
                    and final.get("work_valid") is True
                    and final.get("window_coverage_complete") is True
                    and final.get("guards") == "PASS")

    def _summary(self):
        if self.plan is None:
            window = None
        else:
            window = self.plan.as_dict()
        counts = dict(
            worker_spawn_attempts=self.worker_spawn_attempts,
            workers_spawned=1 if self.handle is not None else 0,
            copies=(self.worker_final or {}).get("copies", 0),
            copy_bytes=(self.worker_final or {}).get("copy_bytes", 0),
            signals=len(self.cleanup.get("signals", [])),
        )
        readiness = None
        if self.config.mode == "fixed":
            readiness = dict(
                prepare_call_ns=self.prepare_call_ns,
                readiness_deadline_ns=self.readiness_deadline_ns,
                spawn_return_ns=self.spawn_return_ns,
                ready_received_ns=self.ready_received_ns,
                ready_validated_ns=self.ready_validated_ns,
                worker_ready_ns=(self.ready_evidence or {}).get("ready_ns"),
                rule=("one absolute deadline; spawn, receive, parse and validation "
                      "all consume the same budget"))
        return dict(
            schema=SCHEMA,
            status=self._status_name(),
            state=self.state,
            mode=self.config.mode,
            quiet_no_worker=(self.config.mode == "quiet" and self.handle is None),
            window_complete=self._window_complete,
            cancelled=self.cancelled,
            config=self.config.fixed_intensity(),
            config_fingerprint=self.config.fingerprint(),
            worker_config_fingerprint=worker_config_fingerprint(),
            window=window,
            readiness=readiness,
            counts=counts,
            ready_evidence=self.ready_evidence,
            worker_final=self.worker_final,
            heartbeat_final=self.heartbeat_final,
            work_evidence=(self.worker_final or {}).get("work_evidence"),
            cleanup=dict(self.cleanup),
            resource_release=self.resource_release,
            evidence_snapshot=dict(
                present=bool(self.memory_evidence),
                fields=sorted(self.memory_evidence.keys()),
                snapshot_before_release=True),
            failure=self.failure,
            timeline=self.timeline,
            persistence_status=self.persistence_status,
            persisted=self.persisted,
            persistence_error=self.persistence_error,
            persistence=self.persistence,
            interpretation=(
                "lifecycle/work-evidence only; copy_bytes is logical memmove "
                "traffic, not DRAM bandwidth; positive copies prove work occurred, "
                "not continuous coverage; no board safety or GPU effect claim"),
        )

    def _status_name(self):
        if self.state == State.FAILED:
            return "FAILED"
        if self.state == State.CREATED:
            return "CREATED"
        if self.state == State.READY:
            return "QUIET_READY" if self.config.mode == "quiet" else "READY"
        if self.state == State.RUNNING:
            return "QUIET_RUNNING" if self.config.mode == "quiet" else "RUNNING"
        if self.state == State.STOPPED:
            if not self._window_complete:
                return "FAILED"
            return ("QUIET_COMPLETE" if self.config.mode == "quiet"
                    else ("WINDOW_COMPLETE" if self._fixed_work_valid()
                          else "FAILED"))
        return self.state

    @property
    def evidence(self):
        return self._summary()

    def finalize(self, path):
        if self._finalize_attempted:
            raise PersistenceError("finalize may be attempted exactly once")
        if self.state == State.CREATED:
            raise PersistenceError("nothing to persist before prepare")
        if self.state == State.RUNNING:
            raise PersistenceError("cannot persist while the window is running")
        if self.state == State.READY:
            raise PersistenceError("window was prepared but not run/stopped")
        now = self.clock.monotonic_ns()
        if (self._window_armed and self.plan is not None
                and now < self.plan.end_ns):
            raise PersistenceError("refusing to persist inside the declared window")
        self._finalize_attempted = True
        self._snapshot_evidence()
        self.release_resources()
        evidence = self._summary()
        evidence["persisted_at_ns"] = now
        evidence["persisted_inside_window"] = False
        evidence["persisted"] = True
        evidence["persistence_status"] = "PERSISTED"
        evidence["persistence"] = dict(
            requested_path=str(path), inside_window=False,
            after_declared_end=(self.plan is None or now >= self.plan.end_ns),
            status="PERSISTED", persisted=True, written=None,
            resources_released=bool(
                (self.resource_release or {}).get("resources_released")),
            process_exit_confirmed=(self.resource_release or {}).get(
                "process_exit_confirmed"),
            note=("execution status is independent of persistence; this file "
                  "records the attempted evidence write"))
        try:
            written = self.persist(path, evidence)
        except BaseException as exc:
            self.persistence_status = "FAILED"
            self.persistence_error = repr(exc)
            self.persistence = dict(
                requested_path=str(path), status="FAILED", persisted=False,
                written=None, error=repr(exc),
                resources_released=bool(
                    (self.resource_release or {}).get("resources_released")))
            raise
        self.persistence_status = "PERSISTED"
        self.persisted = True
        self.persistence_error = None
        self.persistence = dict(
            requested_path=str(path), status="PERSISTED", persisted=True,
            written=written, inside_window=False,
            after_declared_end=(self.plan is None or now >= self.plan.end_ns),
            resources_released=bool(
                (self.resource_release or {}).get("resources_released")))
        return self.persistence

    def close(self):
        if self.state in (State.RUNNING, State.READY):
            self.abort("close")
        if self.handle is not None and self.handle.poll() is None:
            self._cleanup_owned("close", collect=False)
        self.release_resources()
        return self.resource_release

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is not None and self.state not in (State.STOPPED, State.FAILED):
                self.abort("exception: %s" % exc_type.__name__)
        finally:
            self.close()
        return False
