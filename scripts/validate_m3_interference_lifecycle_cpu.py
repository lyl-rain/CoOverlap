"""CPU-only tests for the window-gated worker lifecycle.

The controller/worker modules exercised here are the ones intended for the
future four-condition executor.  A fake clock and fake process backend replace
only the OS process boundary; the lifecycle state machine, final-evidence
validation, worker copy loop, guard checks and heartbeat code are the real
implementations.  No 32 MiB pressure loop, model, CUDA, SSH or hardware write is
started.

A PASS proves these lifecycle/logic properties only.  It is not board safety,
not an interference-effect result and not a GPU acceptance.
"""
import ctypes as C
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m3_interference_lifecycle as L
import m3_interference_worker as W


class FakeClock:
    def __init__(self, now_ns=1_000_000_000):
        self.now_ns = int(now_ns)
        self.sleeps = []

    def monotonic_ns(self):
        return self.now_ns

    def sleep_ns(self, ns):
        ns = max(0, int(ns))
        self.sleeps.append(ns)
        self.now_ns += ns

    def advance_ns(self, ns):
        self.now_ns += int(ns)

    def max_sleep(self):
        return max(self.sleeps) if self.sleeps else 0


def ready_evidence(handle, plan, config, override=None):
    obj = dict(
        ok=True, ready=True, phase="ready", worker_version=W.WORKER_VERSION,
        pid=handle.pid, parent_pid=os.getpid(),
        declared_start_ns=plan.start_ns, declared_end_ns=plan.end_ns,
        config_fingerprint=W.config_fingerprint(),
        cpu=config.cpu, copy_length_bytes=config.copy_length_bytes,
        guard_bytes=config.guard_bytes,
        source_pattern=config.source_pattern, dest_pattern=config.dest_pattern,
        source={"capacity": config.source_capacity_bytes},
        dest={"capacity": config.dest_capacity_bytes},
        affinity=[config.cpu], pre_window_copy_ops=0,
        ready_ns=handle.clock.monotonic_ns(),
        script_sha256="0" * 64, guard_module_sha256="0" * 64,
    )
    if override:
        obj.update(override)
    return obj


def final_evidence(handle, plan, config, override=None):
    copies = int(handle.behavior.get("final_copies_override", handle.copies))
    copy_bytes = copies * config.copy_length_bytes
    actual_start = handle.behavior.get(
        "actual_start_override",
        handle.pressure_start_ns if handle.pressure_started else None)
    actual_end = handle.behavior.get(
        "actual_end_override",
        handle.pressure_end_ns if handle.pressure_end_ns is not None
        else handle.clock.monotonic_ns())
    heartbeat = dict(seq=2, magic=W.HEARTBEAT_MAGIC, copies=copies,
                     copy_bytes=copy_bytes,
                     heartbeat_ns=handle.clock.monotonic_ns(),
                     state=W.STATE_STOPPED, state_name="STOPPED")
    delta = handle.behavior.get("heartbeat_copies_delta")
    if delta:
        heartbeat["copies"] += delta
        heartbeat["copy_bytes"] += delta * config.copy_length_bytes
    loop_enter = actual_start
    first_call = (actual_start if copies > 0 and actual_start is not None else None)
    last_return = None
    if copies > 0 and actual_start is not None:
        last_return = min(actual_end,
                          actual_start + copies * handle.copy_period_ns)
    loop_exit = actual_end
    work_valid = bool(copies > 0 and first_call is not None
                      and last_return is not None and last_return >= first_call)
    coverage_complete = bool(actual_start is not None and actual_end is not None
                             and actual_end >= plan.end_ns)
    obj = dict(
        ok=handle.behavior.get("final_ok", work_valid), ready=False, phase="final",
        worker_version=W.WORKER_VERSION, pid=handle.pid,
        parent_pid=os.getpid(),
        config_fingerprint=W.config_fingerprint(),
        declared_start_ns=plan.start_ns, declared_end_ns=plan.end_ns,
        copy_length_bytes=config.copy_length_bytes,
        guard_bytes=config.guard_bytes,
        guards=handle.behavior.get("guards", "PASS"),
        affinity=[config.cpu],
        copies=copies, copy_bytes=copy_bytes,
        actual_start_ns=actual_start, actual_end_ns=actual_end,
        copy_loop_enter_ns=loop_enter, copy_loop_exit_ns=loop_exit,
        first_copy_call_ns=first_call, last_copy_return_ns=last_return,
        work_valid=work_valid, window_coverage_complete=coverage_complete,
        work_evidence=dict(loop_enter_ns=loop_enter, loop_exit_ns=loop_exit,
                           first_copy_call_ns=first_call,
                           last_copy_return_ns=last_return,
                           successful_copies=copies,
                           successful_copy_bytes=copy_bytes),
        exit_reason=handle.behavior.get(
            "exit_reason", "sigterm" if handle.terminated_by else "window_elapsed"),
        error=handle.behavior.get("final_error"),
        start_lateness_ns=(actual_start - plan.start_ns
                           if actual_start is not None else None),
        end_overrun_ns=(actual_end - plan.end_ns
                        if actual_end is not None else None),
        heartbeat_final=heartbeat,
        script_sha256="0" * 64, guard_module_sha256="0" * 64,
    )
    if override:
        obj.update(override)
    return obj


def final_from_copy_window(raw, *, plan, config, pid=9999):
    """Map the actual copy_window result into the real final-evidence shape."""
    return dict(
        ok=bool(raw["work_valid"] and raw["window_coverage_complete"]
                and raw["guards"] == "PASS"),
        ready=False, phase="final", pid=pid, parent_pid=os.getpid(),
        config_fingerprint=W.config_fingerprint(),
        declared_start_ns=plan.start_ns, declared_end_ns=plan.end_ns,
        copy_length_bytes=config.copy_length_bytes,
        guard_bytes=config.guard_bytes,
        guards=raw["guards"], affinity=[config.cpu],
        copies=raw["copies"], copy_bytes=raw["copy_bytes"],
        actual_start_ns=raw["actual_start_ns"],
        actual_end_ns=raw["actual_end_ns"],
        copy_loop_enter_ns=raw["copy_loop_enter_ns"],
        copy_loop_exit_ns=raw["copy_loop_exit_ns"],
        first_copy_call_ns=raw["first_copy_call_ns"],
        last_copy_return_ns=raw["last_copy_return_ns"],
        work_valid=raw["work_valid"],
        window_coverage_complete=raw["window_coverage_complete"],
        work_evidence=raw["work_evidence"],
        exit_reason=raw["exit_reason"],
        error=raw["error"],
        heartbeat_final=dict(
            seq=2, magic=W.HEARTBEAT_MAGIC, copies=raw["copies"],
            copy_bytes=raw["copy_bytes"],
            heartbeat_ns=raw["actual_end_ns"],
            state=W.STATE_STOPPED, state_name="STOPPED"),
        script_sha256="0" * 64, guard_module_sha256="0" * 64,
    )


class FakeHandle:
    _next_pid = 4200

    def __init__(self, clock, plan, config, behavior):
        FakeHandle._next_pid += 1
        self.pid = FakeHandle._next_pid
        self.clock = clock
        self.plan = plan
        self.config = config
        self.behavior = dict(behavior or {})
        self.ready = False
        self.ready_evidence = None
        self.pressure_started = False
        self.pressure_start_ns = None
        self.pressure_end_ns = None
        self.copies = 0
        self.last_sim_ns = None
        self.exit_code = None
        self.terminated_by = None
        self.actions = []
        self.cleaned = False
        self.release_calls = 0
        self.stdout_closed = False
        self.stderr_closed = False
        self.shm_closed = False
        self.shm_unlinked = False
        self.resources_released = False
        self.copy_period_ns = int(self.behavior.get("copy_period_ns", 10_000_000))

    def wait_ready(self, deadline_ns):
        deadline = int(deadline_ns)
        now = self.clock.monotonic_ns()
        if self.behavior.get("ready_timeout"):
            self.clock.sleep_ns(max(0, deadline - now))
            raise L.ReadinessTimeout("fake readiness timeout")
        delay = int(self.behavior.get("ready_delay_ns", 1_000_000))
        receive_at = now + delay
        if self.behavior.get("receive_after_deadline_ns") is not None:
            receive_at = max(receive_at, deadline
                             + int(self.behavior["receive_after_deadline_ns"]))
        return_after_deadline = bool(
            self.behavior.get("return_ready_after_deadline", False))
        if receive_at >= deadline and not return_after_deadline:
            self.clock.sleep_ns(max(0, deadline - self.clock.monotonic_ns()))
            raise L.ReadinessTimeout("fake readiness past absolute deadline")
        self.clock.sleep_ns(max(0, receive_at - self.clock.monotonic_ns()))
        if not self.behavior.get("ready_ok", True):
            raise L.ReadinessError("fake readiness failure")
        self.ready = True
        override = dict(self.behavior.get("ready_override") or {})
        if "ready_ns" not in override:
            override["ready_ns"] = receive_at
        self.ready_evidence = ready_evidence(self, self.plan, self.config, override)
        return self.ready_evidence

    def _simulate(self):
        if not self.ready or self.exit_code is not None:
            return
        now = self.clock.monotonic_ns()
        if now < self.plan.start_ns:
            return
        if not self.pressure_started:
            self.pressure_started = True
            self.pressure_start_ns = self.plan.start_ns
            self.last_sim_ns = self.plan.start_ns
        exit_at = self.behavior.get("self_exit_at_ns")
        active_end = min(now, exit_at) if exit_at is not None else now
        if active_end > self.last_sim_ns:
            n = (active_end - self.last_sim_ns) // self.copy_period_ns
            self.copies += int(n)
            self.last_sim_ns += int(n) * self.copy_period_ns
        if exit_at is not None and now >= exit_at:
            self.exit_code = int(self.behavior.get("self_exit_code", 0))
            self.pressure_end_ns = exit_at

    def poll(self):
        self._simulate()
        return self.exit_code

    def terminate(self):
        self.actions.append(("SIGTERM", self.clock.monotonic_ns()))
        self._simulate()
        if self.behavior.get("respond_to_term", True):
            self.terminated_by = "SIGTERM"
            self.exit_code = 0
            self.pressure_end_ns = self.clock.monotonic_ns()

    def kill(self):
        self.actions.append(("SIGKILL", self.clock.monotonic_ns()))
        self._simulate()
        if not self.behavior.get("ignore_kill", False):
            self.terminated_by = "SIGKILL"
            self.exit_code = -9
            self.pressure_end_ns = self.clock.monotonic_ns()

    def wait_exit(self, timeout_ns):
        deadline = self.clock.monotonic_ns() + int(timeout_ns)
        while True:
            if self.poll() is not None:
                return self.exit_code
            remaining = deadline - self.clock.monotonic_ns()
            if remaining <= 0:
                return self.poll()
            self.clock.sleep_ns(min(1_000_000, remaining))

    def read_heartbeat(self):
        if not self.ready:
            return None
        obj = dict(seq=2, magic=W.HEARTBEAT_MAGIC, copies=self.copies,
                   copy_bytes=self.copies * self.config.copy_length_bytes,
                   heartbeat_ns=self.clock.monotonic_ns(),
                   state=W.STATE_STOPPED, state_name="STOPPED")
        obj.update(self.behavior.get("heartbeat_override") or {})
        return obj

    def collect_final(self, timeout_ns=None):
        self._simulate()
        if self.exit_code is None:
            return dict(final=None, exit_code=None, stdout_tail=[], stderr="",
                        heartbeat=self.read_heartbeat())
        if self.exit_code == -9 and not self.behavior.get("final_after_kill", False):
            return dict(final=None, exit_code=self.exit_code, stdout_tail=[],
                        stderr="killed", heartbeat=self.read_heartbeat())
        override = self.behavior.get("final_object")
        final = (json.loads(json.dumps(override)) if override is not None
                 else final_evidence(self, self.plan, self.config))
        return dict(final=final, exit_code=self.exit_code, stdout_tail=[],
                    stderr="", heartbeat=self.read_heartbeat())

    def release(self):
        self.release_calls += 1
        process_exit_confirmed = self.poll() is not None
        if not process_exit_confirmed:
            self.resources_released = False
            return dict(no_owned_process=False, process_exit_confirmed=False,
                        stdout_closed=self.stdout_closed,
                        stderr_closed=self.stderr_closed, shm_present=True,
                        shm_closed=False, shm_unlinked=False,
                        resources_released=False,
                        release_attempts=self.release_calls,
                        skipped="fake process not exited")
        self.stdout_closed = True
        self.stderr_closed = True
        self.shm_closed = True
        self.shm_unlinked = True
        self.resources_released = True
        return dict(no_owned_process=False, process_exit_confirmed=True,
                    stdout_closed=True, stderr_closed=True, shm_present=True,
                    shm_closed=True, shm_unlinked=True,
                    resources_released=True,
                    release_attempts=self.release_calls)

    def cleanup(self):
        self.cleaned = True
        return self.release()


class FakeBackend:
    def __init__(self, clock, behavior=None):
        self.clock = clock
        self.behavior = dict(behavior or {})
        self.spawn_count = 0
        self.handles = []

    def spawn(self, plan, config):
        delay = int(self.behavior.get("spawn_delay_ns", 0))
        if delay:
            self.clock.sleep_ns(delay)
        if self.behavior.get("spawn_fail"):
            raise OSError("fake spawn failure")
        self.spawn_count += 1
        handle = FakeHandle(self.clock, plan, config, self.behavior)
        self.handles.append(handle)
        return handle


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.config = L.InterferenceConfig()
        self.plan = L.WindowPlan.from_replay_t0(
            self.clock.now_ns + 100_000_000, 200_000_000, 50_000_000)
        self.backend = FakeBackend(self.clock, {"self_exit_at_ns": self.plan.end_ns})

    def controller(self, backend=None):
        return L.InterferenceController(
            self.config, clock=self.clock, backend=backend or self.backend)

    def run_window(self, controller):
        controller.prepare(self.plan)
        controller.await_start()
        controller.finish()
        return controller

    # 1. quiet ---------------------------------------------------------------
    def test_quiet_mode_creates_no_worker_or_pressure(self):
        quiet = L.InterferenceConfig(mode="quiet")
        ctl = L.InterferenceController(quiet, clock=self.clock, backend=self.backend)
        writes = []
        ctl.persist = lambda path, obj: writes.append((self.clock.now_ns, obj)) or {"ok": True}
        ctl.prepare(self.plan)
        self.assertEqual(self.backend.spawn_count, 0)
        self.assertIsNone(ctl.handle)
        self.assertEqual(writes, [])
        ctl.await_start()
        self.assertEqual(self.backend.spawn_count, 0)
        ctl.finish()
        self.assertEqual(writes, [])
        ctl.finalize("unused.json")
        self.assertEqual(len(writes), 1)
        ev = writes[0][1]
        self.assertTrue(ev["quiet_no_worker"])
        self.assertEqual(ev["counts"]["workers_spawned"], 0)
        self.assertEqual(ev["counts"]["worker_spawn_attempts"], 0)
        self.assertEqual(ev["counts"]["copies"], 0)
        self.assertEqual(ev["status"], "QUIET_COMPLETE")

    # 2. readiness success / failure / timeout -------------------------------
    def test_readiness_success_still_has_no_pressure_before_start(self):
        ctl = self.controller()
        ctl.prepare(self.plan)
        self.assertEqual(ctl.state, L.State.READY)
        self.assertEqual(self.backend.spawn_count, 1)
        self.assertIsNone(self.backend.handles[0].pressure_start_ns)
        self.assertLess(self.clock.now_ns, self.plan.start_ns)
        ctl.await_start()
        self.assertEqual(self.backend.handles[0].pressure_start_ns, self.plan.start_ns)
        ctl.finish()
        self.assertEqual(ctl.state, L.State.STOPPED)

    def test_readiness_failure_blocks_window_and_has_no_retry(self):
        backend = FakeBackend(self.clock, {"ready_ok": False})
        ctl = L.InterferenceController(self.config, clock=self.clock, backend=backend)
        with self.assertRaises(L.ReadinessError):
            ctl.prepare(self.plan)
        self.assertEqual(ctl.state, L.State.FAILED)
        self.assertFalse(ctl._window_started)
        self.assertEqual(backend.spawn_count, 1)
        self.assertEqual(ctl.worker_spawn_attempts, 1)
        self.assertEqual(ctl.failure["stage"], "readiness")
        self.assertTrue(ctl.cleanup["cleanup_complete"])
        with self.assertRaises(L.LifecycleError):
            ctl.prepare(self.plan)  # single-use, no automatic retry
        self.assertEqual(backend.spawn_count, 1)

    def test_readiness_timeout_is_bounded_and_blocks_window(self):
        config = L.InterferenceConfig(ready_timeout_ns=100_000_000,
                                      ready_margin_ns=10_000_000)
        plan = L.WindowPlan.from_replay_t0(self.clock.now_ns + 150_000_000,
                                           200_000_000, 50_000_000)
        backend = FakeBackend(self.clock, {"ready_timeout": True})
        ctl = L.InterferenceController(config, clock=self.clock, backend=backend)
        start = self.clock.now_ns
        with self.assertRaises(L.ReadinessTimeout):
            ctl.prepare(plan)
        elapsed = self.clock.now_ns - start
        expected = config.ready_timeout_ns
        self.assertGreaterEqual(elapsed, expected)
        self.assertLessEqual(elapsed, expected + config.term_grace_ns
                             + config.kill_grace_ns + 10_000_000)
        self.assertFalse(ctl._window_started)
        self.assertEqual(ctl.failure["stage"], "readiness")

    def test_readiness_contract_mismatch_is_rejected(self):
        backend = FakeBackend(self.clock, {
            "ready_override": {"affinity": [0]},
            "self_exit_at_ns": self.plan.end_ns})
        ctl = L.InterferenceController(self.config, clock=self.clock, backend=backend)
        with self.assertRaises(L.ReadinessError):
            ctl.prepare(self.plan)
        self.assertFalse(ctl._window_started)
        self.assertTrue(ctl.cleanup["cleanup_complete"])

    # 3. duplicate start / no retry -----------------------------------------
    def test_duplicate_prepare_is_rejected_and_spawns_once(self):
        ctl = self.controller()
        ctl.prepare(self.plan)
        with self.assertRaises(L.LifecycleError):
            ctl.prepare(self.plan)
        self.assertEqual(self.backend.spawn_count, 1)
        ctl.await_start()
        ctl.finish()
        self.assertEqual(self.backend.spawn_count, 1)

    # 4. normal end / early exit / parent death ------------------------------
    def test_normal_end_confirms_exit_and_evidence(self):
        ctl = self.controller()
        self.run_window(ctl)
        self.assertEqual(ctl.state, L.State.STOPPED)
        self.assertTrue(ctl.cleanup["exit_confirmed"])
        self.assertTrue(ctl.cleanup["cleanup_complete"])
        self.assertEqual(ctl.cleanup["signals"], [])
        self.assertGreater(ctl.worker_final["copies"], 0)
        self.assertEqual(ctl.worker_final["actual_end_ns"], self.plan.end_ns)

    def test_early_worker_exit_is_detected_as_incomplete_window(self):
        backend = FakeBackend(self.clock, {
            "self_exit_at_ns": self.plan.start_ns + 50_000_000,
            "self_exit_code": 1})
        ctl = L.InterferenceController(self.config, clock=self.clock, backend=backend)
        ctl.prepare(self.plan)
        ctl.await_start()
        with self.assertRaises(L.WorkerExitedEarly):
            ctl.finish()
        self.assertEqual(ctl.state, L.State.FAILED)
        self.assertEqual(ctl.failure["stage"], "window")
        self.assertLess(ctl.worker_final["actual_end_ns"], self.plan.end_ns)

    # 5. bounded TERM/KILL cleanup ------------------------------------------
    def test_term_ignored_then_bounded_kill(self):
        backend = FakeBackend(self.clock, {"respond_to_term": False,
                                           "self_exit_at_ns": None})
        ctl = L.InterferenceController(self.config, clock=self.clock, backend=backend)
        ctl.prepare(self.plan)
        ctl.await_start()
        with self.assertRaises(L.LifecycleError):
            ctl.finish()
        stop_ns = [e["monotonic_ns"] for e in ctl.timeline
                   if e["event"] == "stop_requested"][0]
        elapsed = self.clock.now_ns - stop_ns
        self.assertEqual([a[0] for a in backend.handles[0].actions],
                         ["SIGTERM", "SIGKILL"])
        self.assertLessEqual(elapsed, self.config.term_grace_ns
                             + self.config.kill_grace_ns + 10_000_000)
        self.assertTrue(ctl.cleanup["cleanup_complete"])
        self.assertEqual(ctl.state, L.State.FAILED)

    def test_term_and_kill_ignored_has_bounded_failure(self):
        backend = FakeBackend(self.clock, {"respond_to_term": False,
                                           "ignore_kill": True,
                                           "self_exit_at_ns": None})
        ctl = L.InterferenceController(self.config, clock=self.clock, backend=backend)
        ctl.prepare(self.plan)
        ctl.await_start()
        with self.assertRaises(L.CleanupTimeout):
            ctl.finish()
        stop_ns = [e["monotonic_ns"] for e in ctl.timeline
                   if e["event"] == "stop_requested"][0]
        elapsed = self.clock.now_ns - stop_ns
        self.assertEqual([a[0] for a in backend.handles[0].actions],
                         ["SIGTERM", "SIGKILL"])
        self.assertLessEqual(elapsed, self.config.term_grace_ns
                             + self.config.kill_grace_ns + 10_000_000)
        self.assertFalse(ctl.cleanup["cleanup_complete"])
        self.assertEqual(ctl.failure["stage"], "cleanup")

    # 6. pre-declared trajectory independent of consumer completion ----------
    def trajectory(self, completion_offset_ns):
        clock = FakeClock()
        plan = L.WindowPlan.from_replay_t0(clock.now_ns + 100_000_000,
                                           200_000_000, 50_000_000)
        backend = FakeBackend(clock, {"self_exit_at_ns": plan.end_ns})
        ctl = L.InterferenceController(self.config, clock=clock, backend=backend)
        ctl.prepare(plan)
        ctl.await_start()
        clock.advance_ns(completion_offset_ns)
        ctl.finish()
        h = backend.handles[0]
        return dict(plan=plan, pressure_start=h.pressure_start_ns,
                    pressure_end=h.pressure_end_ns, copies=h.copies,
                    final_copies=ctl.worker_final["copies"],
                    actual_start=ctl.worker_final["actual_start_ns"],
                    actual_end=ctl.worker_final["actual_end_ns"])

    def test_consumer_completion_times_do_not_change_interference_trajectory(self):
        early = self.trajectory(10_000_000)       # consumer finishes early
        late = self.trajectory(500_000_000)       # consumer drains after end
        for key in ("pressure_start", "pressure_end", "copies",
                    "final_copies", "actual_start", "actual_end"):
            self.assertEqual(early[key], late[key], key)
        self.assertEqual(early["pressure_start"], early["plan"].start_ns)
        self.assertEqual(early["pressure_end"], early["plan"].end_ns)

    # 7. no serialization / persistence / unbounded wait inside window -------
    def test_window_has_no_serialization_or_persistence(self):
        writes = []
        ctl = self.controller()
        ctl.persist = lambda path, obj: writes.append((self.clock.now_ns, obj)) or {"ok": True}
        with mock.patch.object(L.json, "dumps",
                               side_effect=AssertionError("serialized inside window")):
            ctl.prepare(self.plan)
            ctl.await_start()
            ctl.finish()
            self.assertEqual(writes, [])
        ctl.finalize("unused.json")
        self.assertEqual(len(writes), 1)
        self.assertGreaterEqual(writes[0][0], self.plan.end_ns)

    def test_finalize_inside_window_is_refused(self):
        quiet = L.InterferenceConfig(mode="quiet")
        writes = []
        ctl = L.InterferenceController(quiet, clock=self.clock, backend=self.backend)
        ctl.persist = lambda path, obj: writes.append(self.clock.now_ns)
        ctl.prepare(self.plan)
        ctl.await_start()
        self.clock.advance_ns(10_000_000)
        with self.assertRaises(L.PersistenceError):
            ctl.finalize("unused.json")
        self.assertEqual(writes, [])
        ctl.finish()
        ctl.finalize("unused.json")
        self.assertEqual(len(writes), 1)

    def test_default_persistence_is_after_window(self):
        ctl = self.controller()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "evidence.json"
            ctl.prepare(self.plan)
            ctl.await_start()
            ctl.finish()
            self.assertFalse(path.exists())
            self.assertGreaterEqual(self.clock.now_ns, self.plan.end_ns)
            ctl.finalize(path)
            self.assertTrue(path.exists())
            doc = json.loads(path.read_text())
            self.assertFalse(doc["persisted_inside_window"])
            self.assertTrue(doc["persisted"])
            self.assertEqual(doc["status"], "WINDOW_COMPLETE")
            self.assertEqual(ctl.state, L.State.STOPPED)
            self.assertEqual(ctl._status_name(), "WINDOW_COMPLETE")
            self.assertTrue(ctl.persisted)
            self.assertEqual(doc["counts"]["copy_bytes"],
                             doc["worker_final"]["copies"] * self.config.copy_length_bytes)

    def test_all_waits_are_bounded_by_declared_sleep_or_grace(self):
        ctl = self.controller()
        self.run_window(ctl)
        self.assertTrue(self.clock.sleeps)
        self.assertLessEqual(max(self.clock.sleeps), self.config.max_sleep_ns)
        self.assertLess(len(self.clock.sleeps), 10000)

    # 8. capacity / copy length / guard --------------------------------------
    def test_window_plan_rejects_inconsistent_replay_alignment(self):
        good = L.WindowPlan.from_replay_t0(1000, 200, 50)
        good.validate(10_000)
        bad = L.WindowPlan(start_ns=1000, nominal_end_ns=1200, end_ns=1250,
                           replay_t0_ns=1001, nominal_window_ns=200,
                           drain_allowance_ns=50)
        with self.assertRaises(L.WindowError):
            bad.validate(10_000)
        bad2 = L.WindowPlan(start_ns=1000, nominal_end_ns=1200, end_ns=1250,
                            replay_t0_ns=1000, nominal_window_ns=201,
                            drain_allowance_ns=50)
        with self.assertRaises(L.WindowError):
            bad2.validate(10_000)

    def test_bad_capacity_or_copy_length_is_rejected(self):
        for kwargs in (
            {"source_capacity_bytes": 1024},
            {"dest_capacity_bytes": 1024},
            {"copy_length_bytes": 1024},
            {"guard_bytes": 32},
            {"source_pattern": 0x11},
            {"cpu": 0},
        ):
            with self.assertRaises(ValueError):
                L.InterferenceConfig(**kwargs).validate()
        with self.assertRaises(W.WorkerConfigError):
            W.validate_config(11, W.FIXED_BYTES, W.FIXED_BYTES,
                              W.FIXED_BYTES - 1, W.FIXED_GUARD,
                              W.SOURCE_PATTERN, W.DEST_PATTERN)

    def test_actual_guard_primitive_detects_corruption_and_length_mismatch(self):
        src = W.GuardedBuffer(1024, W.SOURCE_PATTERN)
        dst = W.GuardedBuffer(1024, W.DEST_PATTERN)
        W.checked_guards(src, dst)
        W.copy_once(src.payload, dst.payload, 1024)
        with self.assertRaises(ValueError):
            W.copy_once(src.payload, dst.payload, 1023)
        C.memset(C.addressof(src.owner), 0, 1)
        with self.assertRaises(W.GuardFailure):
            W.checked_guards(src, dst)

    # 9. evidence is tied to the active phase --------------------------------
    def test_failure_evidence_matches_active_phase(self):
        backend = FakeBackend(self.clock, {"ready_ok": False})
        ctl = L.InterferenceController(self.config, clock=self.clock, backend=backend)
        with self.assertRaises(L.ReadinessError):
            ctl.prepare(self.plan)
        self.assertFalse(ctl.failure["window_started"])
        self.assertEqual(ctl.failure["stage"], "readiness")
        failure_events = [e for e in ctl.timeline if e["event"] == "failure"]
        self.assertEqual(len(failure_events), 1)
        self.assertEqual(failure_events[0]["phase"], "before_start")
        self.assertEqual(failure_events[0]["stage"], "readiness")

    def test_guard_failure_is_attributed_to_the_window(self):
        backend = FakeBackend(self.clock, {"guards": "FAIL", "final_ok": False,
                                           "self_exit_at_ns": self.plan.end_ns})
        ctl = L.InterferenceController(self.config, clock=self.clock, backend=backend)
        ctl.prepare(self.plan)
        ctl.await_start()
        with self.assertRaises(L.LifecycleError):
            ctl.finish()
        self.assertEqual(ctl.state, L.State.FAILED)
        self.assertEqual(ctl.failure["stage"], "final_evidence")
        self.assertIsNotNone(ctl.worker_final["actual_start_ns"])

    def test_heartbeat_mismatch_is_rejected(self):
        backend = FakeBackend(self.clock, {"heartbeat_copies_delta": 1,
                                           "self_exit_at_ns": self.plan.end_ns})
        ctl = L.InterferenceController(self.config, clock=self.clock, backend=backend)
        ctl.prepare(self.plan)
        ctl.await_start()
        with self.assertRaises(L.LifecycleError):
            ctl.finish()
        self.assertEqual(ctl.state, L.State.FAILED)

    # 10. abort / owned cleanup ---------------------------------------------
    def test_abort_only_signals_the_owned_handle(self):
        backend = FakeBackend(self.clock, {"respond_to_term": True,
                                           "self_exit_at_ns": None})
        ctl = L.InterferenceController(self.config, clock=self.clock, backend=backend)
        ctl.prepare(self.plan)
        ctl.abort("unit-test")
        self.assertEqual(ctl.state, L.State.FAILED)
        self.assertEqual([a[0] for a in backend.handles[0].actions], ["SIGTERM"])
        self.assertTrue(backend.handles[0].cleaned or ctl.cleanup["cleanup_complete"])
        self.assertEqual(ctl.cleanup["owned_pid"], backend.handles[0].pid)
        with self.assertRaises(L.LifecycleError):
            ctl.prepare(self.plan)
        self.assertEqual(backend.spawn_count, 1)

    def test_spawn_failure_is_single_attempt(self):
        backend = FakeBackend(self.clock, {"spawn_fail": True})
        ctl = L.InterferenceController(self.config, clock=self.clock, backend=backend)
        with self.assertRaises(L.ReadinessError):
            ctl.prepare(self.plan)
        self.assertEqual(backend.spawn_count, 0)
        self.assertEqual(ctl.state, L.State.FAILED)
        with self.assertRaises(L.LifecycleError):
            ctl.prepare(self.plan)

    # 11. fixed configuration ------------------------------------------------
    def test_fixed_intensity_is_declared_and_not_adaptive(self):
        a = L.InterferenceConfig()
        b = L.InterferenceConfig()
        self.assertEqual(a.fingerprint(), b.fingerprint())
        intensity = a.fixed_intensity()
        self.assertFalse(intensity["runtime_adaptation"])
        self.assertEqual(intensity["copy_length_bytes"], W.FIXED_BYTES)
        self.assertEqual(intensity["guard_bytes_per_side"], W.FIXED_GUARD)
        self.assertEqual(intensity["cpu"], W.FIXED_CPU)
        self.assertIn("NOT measured DRAM bandwidth",
                      intensity["copy_bytes_interpretation"])


class WorkerLoopTests(unittest.TestCase):
    """The actual worker loop with a fake clock/copy function; no 32 MiB copy."""

    def loop(self, *, start_offset=10_000_000, window=30_000_000,
             stop_after=None, parent_alive=None, parent_death_after_ns=None,
             guard_fail_after=None):
        clock = FakeClock()
        start = clock.now_ns + start_offset
        end = start + window
        calls = []
        heartbeats = []

        def copy_fn():
            calls.append(clock.monotonic_ns())
            clock.sleep_ns(1_000_000)

        def guard_check():
            if guard_fail_after is not None and clock.now_ns >= guard_fail_after:
                raise W.GuardFailure("MEMCPY_GUARD_CORRUPTION")

        def heartbeat(copies, copy_bytes, now_ns, state):
            heartbeats.append((copies, copy_bytes, now_ns, state))

        if parent_death_after_ns is not None:
            death_ns = start + parent_death_after_ns
            parent_alive = lambda: clock.monotonic_ns() < death_ns
        result = W.copy_window(
            clock=clock, start_ns=start, end_ns=end,
            copy_bytes_per_op=1024, copy_fn=copy_fn,
            guard_check=guard_check, heartbeat=heartbeat,
            stop_requested=(lambda: stop_after is not None and clock.now_ns >= stop_after),
            parent_alive=(parent_alive or (lambda: True)),
            heartbeat_interval_ns=5_000_000, guard_interval_ns=10_000_000,
            max_sleep_ns=2_000_000, sleep_fn=clock.sleep_ns)
        return clock, start, end, calls, heartbeats, result

    def test_no_copy_before_declared_start(self):
        clock, start, end, calls, heartbeats, result = self.loop()
        self.assertTrue(calls)
        self.assertGreaterEqual(min(calls), start)
        self.assertGreaterEqual(result["actual_start_ns"], start)
        self.assertEqual(result["exit_reason"], "window_elapsed")
        self.assertEqual(result["guards"], "PASS")
        self.assertGreater(result["copies"], 0)
        self.assertEqual(result["copy_bytes"], result["copies"] * 1024)
        self.assertTrue(result["work_valid"])
        self.assertTrue(result["window_coverage_complete"])
        self.assertIsNotNone(result["copy_loop_enter_ns"])
        self.assertIsNotNone(result["copy_loop_exit_ns"])
        self.assertIsNotNone(result["first_copy_call_ns"])
        self.assertIsNotNone(result["last_copy_return_ns"])
        self.assertLessEqual(result["copy_loop_enter_ns"],
                             result["first_copy_call_ns"])
        self.assertLessEqual(result["first_copy_call_ns"],
                             result["last_copy_return_ns"])
        self.assertLessEqual(result["last_copy_return_ns"],
                             result["copy_loop_exit_ns"])
        self.assertEqual(heartbeats[0][3], W.STATE_RUNNING)
        self.assertEqual(heartbeats[-1][3], W.STATE_STOPPED)

    def test_parent_death_terminates_loop(self):
        clock, start, end, calls, heartbeats, result = self.loop(
            start_offset=10_000_000, window=50_000_000,
            parent_death_after_ns=5_000_000)
        self.assertEqual(result["exit_reason"], "parent_exit")
        self.assertLessEqual(result["actual_end_ns"], start + 7_000_000)
        self.assertGreaterEqual(result["copies"], 0)

    def test_sigterm_and_guard_failure_paths(self):
        clock = FakeClock()
        start = clock.now_ns + 10_000_000
        clock, start, end, calls, heartbeats, result = self.loop(
            start_offset=10_000_000, window=50_000_000,
            stop_after=start + 5_000_000)
        self.assertEqual(result["exit_reason"], "sigterm")
        self.assertGreaterEqual(result["actual_start_ns"], start)
        guard = self.loop(start_offset=10_000_000, window=50_000_000,
                          guard_fail_after=None)
        clock2, start2, end2, calls2, hb2, result2 = guard
        # Explicit guard failure path with the real loop.
        clock3 = FakeClock()
        start3 = clock3.now_ns + 10_000_000
        fail_at = start3 + 3_000_000
        calls3 = []

        def copy3():
            calls3.append(clock3.monotonic_ns())
            clock3.sleep_ns(1_000_000)

        def guard3():
            if clock3.monotonic_ns() >= fail_at:
                raise W.GuardFailure("MEMCPY_GUARD_CORRUPTION")

        result3 = W.copy_window(
            clock=clock3, start_ns=start3, end_ns=start3 + 30_000_000,
            copy_bytes_per_op=1024, copy_fn=copy3, guard_check=guard3,
            heartbeat=lambda *a: None, stop_requested=lambda: False,
            parent_alive=lambda: True, heartbeat_interval_ns=5_000_000,
            guard_interval_ns=1_000_000, max_sleep_ns=2_000_000,
            sleep_fn=clock3.sleep_ns)
        self.assertEqual(result3["exit_reason"], "guard_failure")
        self.assertEqual(result3["guards"], "FAIL")

    def test_heartbeat_seqlock_and_torn_write(self):
        buf = bytearray(W.HEARTBEAT_SIZE)
        self.assertIsNone(W.heartbeat_decode(buf))
        seq = W.heartbeat_encode(buf, seq=0, copies=7, copy_bytes=7168,
                                now_ns=12345, state=W.STATE_RUNNING)
        decoded = W.heartbeat_decode(buf)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["copies"], 7)
        self.assertEqual(decoded["state"], W.STATE_RUNNING)
        self.assertEqual(seq, 2)
        # Simulate a reader observing the odd (in-progress) sequence.
        import struct
        struct.pack_into("<Q", buf, 0, seq + 1)
        self.assertIsNone(W.heartbeat_decode(buf))



class R1SpecTests(unittest.TestCase):
    """Targeted counterexamples for the Codex r1 repair specification."""

    def make(self, *, mode="fixed", behavior=None, ready_timeout=3_000_000_000,
             ready_margin=10_000_000):
        clock = FakeClock()
        config = L.InterferenceConfig(mode=mode, ready_timeout_ns=ready_timeout,
                                      ready_margin_ns=ready_margin)
        plan = L.WindowPlan.from_replay_t0(clock.now_ns + 100_000_000,
                                           200_000_000, 50_000_000)
        if callable(behavior):
            behavior = behavior(plan)
        behavior = dict(behavior or {"self_exit_at_ns": plan.end_ns})
        backend = FakeBackend(clock, behavior)
        ctl = L.InterferenceController(config, clock=clock, backend=backend)
        return clock, config, plan, backend, ctl

    # 1. execution result vs persistence -------------------------------------
    def test_failed_execution_remains_failed_after_successful_finalize(self):
        clock, config, plan, backend, ctl = self.make(behavior={
            "self_exit_at_ns": None, "guards": "FAIL", "final_ok": False})
        ctl.prepare(plan)
        ctl.await_start()
        with self.assertRaises(L.LifecycleError):
            ctl.finish()
        self.assertEqual(ctl.state, L.State.FAILED)
        self.assertEqual(ctl._status_name(), "FAILED")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "failed.json"
            ctl.finalize(path)
            doc = json.loads(path.read_text())
            self.assertEqual(doc["status"], "FAILED")
            self.assertEqual(doc["state"], "FAILED")
            self.assertTrue(doc["persisted"])
            self.assertEqual(ctl.state, L.State.FAILED)
            self.assertEqual(ctl.evidence["status"], "FAILED")
            with self.assertRaises(L.PersistenceError):
                ctl.finalize(Path(td) / "again.json")

    def test_persist_failure_keeps_execution_result_and_not_persisted(self):
        clock, config, plan, backend, ctl = self.make()
        ctl.prepare(plan)
        ctl.await_start()
        ctl.finish()
        self.assertEqual(ctl._status_name(), "WINDOW_COMPLETE")

        def boom(path, obj):
            raise OSError("fake disk failure")

        ctl.persist = boom
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(OSError):
                ctl.finalize(Path(td) / "evidence.json")
        self.assertEqual(ctl.state, L.State.STOPPED)
        self.assertEqual(ctl._status_name(), "WINDOW_COMPLETE")
        self.assertFalse(ctl.persisted)
        self.assertEqual(ctl.persistence_status, "FAILED")
        self.assertTrue(ctl.resource_release["resources_released"])
        with self.assertRaises(L.PersistenceError):
            ctl.finalize("never.json")

    def test_repeated_finalize_is_rejected_after_success(self):
        clock, config, plan, backend, ctl = self.make()
        ctl.prepare(plan)
        ctl.await_start()
        ctl.finish()
        with tempfile.TemporaryDirectory() as td:
            ctl.finalize(Path(td) / "one.json")
            with self.assertRaises(L.PersistenceError):
                ctl.finalize(Path(td) / "two.json")

    # 2. actual-work evidence -------------------------------------------------
    def test_zero_copies_is_not_window_complete(self):
        clock, config, plan, backend, ctl = self.make(behavior=lambda p: {
            "self_exit_at_ns": p.end_ns,
            "copy_period_ns": 10_000_000_000})
        ctl.prepare(plan)
        ctl.await_start()
        with self.assertRaises(L.LifecycleError):
            ctl.finish()
        self.assertEqual(ctl.state, L.State.FAILED)
        self.assertEqual(ctl._status_name(), "FAILED")
        self.assertEqual(ctl.worker_final["copies"], 0)

    def test_copy_window_pause_before_first_copy_rejected_by_controller(self):
        base = 1_000_000_000
        cclock = FakeClock(base)
        cplan = L.WindowPlan.from_replay_t0(base + 100_000_000,
                                            100_000_000, 0)
        copy_calls = []

        def copy_fn():
            copy_calls.append(cclock.monotonic_ns())

        def heartbeat(copies, copy_bytes, now_ns, state):
            if state == W.STATE_RUNNING:
                cclock.now_ns = cplan.end_ns

        raw = W.copy_window(
            clock=cclock, start_ns=cplan.start_ns, end_ns=cplan.end_ns,
            copy_bytes_per_op=1024, copy_fn=copy_fn,
            guard_check=lambda: None, heartbeat=heartbeat,
            stop_requested=lambda: False, parent_alive=lambda: True,
            heartbeat_interval_ns=5_000_000, guard_interval_ns=10_000_000,
            max_sleep_ns=2_000_000, sleep_fn=cclock.sleep_ns)
        self.assertEqual(raw["copies"], 0)
        self.assertEqual(copy_calls, [])
        self.assertIsNone(raw["first_copy_call_ns"])
        self.assertFalse(raw["work_valid"])

        clock = FakeClock(base)
        config = L.InterferenceConfig()
        backend = FakeBackend(clock, {
            "self_exit_at_ns": cplan.end_ns,
            "copy_period_ns": 10_000_000_000,
            "final_object": final_from_copy_window(raw, plan=cplan, config=config),
            "final_ok": False})
        ctl = L.InterferenceController(config, clock=clock, backend=backend)
        ctl.prepare(cplan)
        ctl.await_start()
        with self.assertRaises(L.LifecycleError):
            ctl.finish()
        self.assertEqual(ctl.state, L.State.FAILED)
        self.assertEqual(ctl._status_name(), "FAILED")
        self.assertEqual(ctl.worker_final["copies"], 0)

    def test_work_boundary_order_is_rejected(self):
        clock, config, plan, backend, ctl = self.make()
        start = plan.start_ns + 1_000_000
        bad = dict(
            ok=True, ready=False, phase="final", pid=0,
            parent_pid=os.getpid(), config_fingerprint=W.config_fingerprint(),
            declared_start_ns=plan.start_ns, declared_end_ns=plan.end_ns,
            copy_length_bytes=config.copy_length_bytes,
            guard_bytes=config.guard_bytes, guards="PASS",
            affinity=[config.cpu], copies=3,
            copy_bytes=3 * config.copy_length_bytes,
            actual_start_ns=start, actual_end_ns=plan.end_ns,
            copy_loop_enter_ns=start, copy_loop_exit_ns=plan.end_ns,
            first_copy_call_ns=start + 2_000_000,
            last_copy_return_ns=start + 1_000_000,
            work_valid=True, window_coverage_complete=True,
            exit_reason="window_elapsed",
            heartbeat_final=dict(copies=3, copy_bytes=3 * config.copy_length_bytes))
        backend.behavior.update({
            "final_object": bad, "heartbeat_override": {
                "copies": 3, "copy_bytes": 3 * config.copy_length_bytes},
            "self_exit_at_ns": plan.end_ns})
        ctl.prepare(plan)
        ctl.await_start()
        with self.assertRaises(L.LifecycleError):
            ctl.finish()
        self.assertEqual(ctl.state, L.State.FAILED)

    # 3. one absolute readiness deadline -------------------------------------
    def test_slow_spawn_consumes_readiness_budget(self):
        clock, config, plan, backend, ctl = self.make(
            ready_timeout=20_000_000, ready_margin=5_000_000,
            behavior=lambda p: {"spawn_delay_ns": 25_000_000,
                                "self_exit_at_ns": p.end_ns})
        with self.assertRaises(L.ReadinessTimeout):
            ctl.prepare(plan)
        self.assertFalse(ctl._window_started)
        self.assertEqual(ctl.failure["stage"], "readiness")
        self.assertGreaterEqual(ctl.spawn_return_ns, ctl.readiness_deadline_ns)
        self.assertTrue(backend.handles[0].resources_released)
        self.assertFalse(backend.handles[0].ready)
        self.assertEqual(backend.spawn_count, 1)
        self.assertEqual(ctl.plan.start_ns, plan.start_ns)
        self.assertEqual(ctl.plan.end_ns, plan.end_ns)

    def test_ready_received_after_deadline_is_rejected_even_with_old_ready_ns(self):
        clock, config, plan, backend, ctl = self.make(
            ready_timeout=20_000_000, ready_margin=5_000_000,
            behavior=lambda p: {"return_ready_after_deadline": True,
                                "receive_after_deadline_ns": 1_000_000,
                                "ready_override": {"ready_ns": 1},
                                "self_exit_at_ns": p.end_ns})
        with self.assertRaises(L.ReadinessTimeout):
            ctl.prepare(plan)
        self.assertFalse(ctl._window_started)
        self.assertEqual(ctl.failure["stage"], "readiness")
        self.assertGreaterEqual(ctl.ready_received_ns, ctl.readiness_deadline_ns)
        self.assertTrue(backend.handles[0].resources_released)

    def test_ready_validation_crossing_deadline_is_rejected(self):
        clock, config, plan, backend, ctl = self.make(
            ready_timeout=20_000_000, ready_margin=5_000_000)
        original = ctl._validate_ready

        def slow_validate(ready):
            original(ready)
            ctl.clock.advance_ns(
                max(0, ctl.readiness_deadline_ns - ctl.clock.now_ns + 1))

        ctl._validate_ready = slow_validate
        with self.assertRaises(L.ReadinessTimeout):
            ctl.prepare(plan)
        self.assertFalse(ctl._window_started)
        self.assertGreaterEqual(ctl.ready_validated_ns,
                                ctl.readiness_deadline_ns)
        self.assertTrue(backend.handles[0].resources_released)

    def test_worker_ready_ns_after_start_is_rejected(self):
        clock, config, plan, backend, ctl = self.make(
            behavior=lambda p: {"ready_override": {"ready_ns": p.start_ns},
                                "self_exit_at_ns": p.end_ns})
        with self.assertRaises(L.ReadinessError):
            ctl.prepare(plan)
        self.assertFalse(ctl._window_started)

    # 4. quiet full-window completion ----------------------------------------
    def test_quiet_stop_before_start_is_not_complete(self):
        clock, config, plan, backend, ctl = self.make(mode="quiet")
        ctl.prepare(plan)
        ctl.stop()
        self.assertEqual(ctl.state, L.State.FAILED)
        self.assertEqual(ctl._status_name(), "FAILED")
        self.assertFalse(ctl._window_complete)
        self.assertEqual(ctl.cancelled["reason"], "before_start")
        self.assertEqual(ctl.failure["stage"], "cancelled")

    def test_quiet_stop_before_declared_end_is_not_complete(self):
        clock, config, plan, backend, ctl = self.make(mode="quiet")
        ctl.prepare(plan)
        ctl.await_start()
        clock.advance_ns(10_000_000)
        ctl.stop()
        self.assertEqual(ctl.state, L.State.FAILED)
        self.assertEqual(ctl._status_name(), "FAILED")
        self.assertFalse(ctl._window_complete)
        self.assertEqual(ctl.cancelled["reason"], "before_declared_end")
        self.assertEqual(ctl.failure["stage"], "cancelled")

    def test_quiet_cancelled_remains_failed_after_finalize(self):
        clock, config, plan, backend, ctl = self.make(mode="quiet")
        ctl.prepare(plan)
        ctl.stop()
        self.assertEqual(ctl._status_name(), "FAILED")
        with tempfile.TemporaryDirectory() as td:
            ctl.finalize(Path(td) / "quiet_failed.json")
            self.assertEqual(ctl.state, L.State.FAILED)
            self.assertEqual(ctl._status_name(), "FAILED")
            self.assertTrue(ctl.persisted)
            doc = json.loads((Path(td) / "quiet_failed.json").read_text())
            self.assertEqual(doc["status"], "FAILED")
            self.assertEqual(doc["cancelled"]["reason"], "before_start")

    def test_quiet_complete_only_after_full_window(self):
        clock, config, plan, backend, ctl = self.make(mode="quiet")
        ctl.prepare(plan)
        ctl.await_start()
        ctl.finish()
        self.assertEqual(ctl.state, L.State.STOPPED)
        self.assertEqual(ctl._status_name(), "QUIET_COMPLETE")
        self.assertTrue(ctl._window_complete)
        self.assertTrue(ctl.resource_release["resources_released"])

    def test_fixed_cleanup_success_does_not_imply_window_success(self):
        clock, config, plan, backend, ctl = self.make(behavior=lambda p: {
            "copy_period_ns": 10_000_000_000,
            "self_exit_at_ns": p.end_ns})
        ctl.prepare(plan)
        ctl.await_start()
        with self.assertRaises(L.LifecycleError):
            ctl.finish()
        self.assertTrue(ctl.cleanup["cleanup_complete"])
        self.assertEqual(ctl._status_name(), "FAILED")

    # 5. resources independent of persistence --------------------------------
    def test_resources_released_after_finish_without_finalize(self):
        clock, config, plan, backend, ctl = self.make()
        ctl.prepare(plan)
        ctl.await_start()
        ctl.finish()
        handle = backend.handles[0]
        self.assertGreaterEqual(handle.release_calls, 1)
        self.assertTrue(handle.stdout_closed)
        self.assertTrue(handle.stderr_closed)
        self.assertTrue(handle.shm_closed)
        self.assertTrue(handle.shm_unlinked)
        self.assertTrue(ctl.resource_release["resources_released"])
        self.assertTrue(ctl.resource_release["process_exit_confirmed"])
        self.assertTrue(ctl.memory_evidence)
        self.assertIn("worker_final", ctl.memory_evidence)
        self.assertTrue(ctl.evidence["evidence_snapshot"]["present"])
        self.assertFalse(ctl.persisted)

    def test_close_after_readiness_failure_releases_and_is_idempotent(self):
        clock, config, plan, backend, ctl = self.make(behavior=lambda p: {
            "ready_ok": False, "self_exit_at_ns": p.end_ns})
        with self.assertRaises(L.ReadinessError):
            ctl.prepare(plan)
        handle = backend.handles[0]
        self.assertTrue(handle.stdout_closed)
        self.assertTrue(handle.stderr_closed)
        self.assertTrue(handle.shm_closed)
        self.assertTrue(handle.shm_unlinked)
        before = handle.release_calls
        ctl.close()
        ctl.close()
        self.assertGreaterEqual(handle.release_calls, before)
        self.assertTrue(ctl.resource_release["resources_released"])

    def test_close_after_window_failure_releases(self):
        clock, config, plan, backend, ctl = self.make(behavior=lambda p: {
            "guards": "FAIL", "final_ok": False,
            "self_exit_at_ns": p.end_ns})
        ctl.prepare(plan)
        ctl.await_start()
        with self.assertRaises(L.LifecycleError):
            ctl.finish()
        ctl.close()
        self.assertTrue(ctl.resource_release["resources_released"])
        self.assertTrue(backend.handles[0].stdout_closed)
        self.assertTrue(backend.handles[0].shm_unlinked)

    def test_no_false_resource_release_while_process_alive(self):
        clock, config, plan, backend, ctl = self.make(behavior={
            "respond_to_term": False, "ignore_kill": True,
            "self_exit_at_ns": None})
        ctl.prepare(plan)
        ctl.await_start()
        with self.assertRaises(L.CleanupTimeout):
            ctl.finish()
        ctl.close()
        self.assertFalse(ctl.resource_release["resources_released"])
        self.assertFalse(ctl.resource_release["process_exit_confirmed"])
        self.assertFalse(backend.handles[0].resources_released)
        self.assertFalse(backend.handles[0].stdout_closed)
        self.assertFalse(ctl.cleanup["cleanup_complete"])

    def test_finalize_after_cleanup_timeout_persists_failure_without_cleanup_claim(self):
        clock, config, plan, backend, ctl = self.make(behavior={
            "respond_to_term": False, "ignore_kill": True,
            "self_exit_at_ns": None})
        ctl.prepare(plan)
        ctl.await_start()
        with self.assertRaises(L.CleanupTimeout):
            ctl.finish()
        self.assertEqual(ctl.state, L.State.FAILED)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cleanup_failed.json"
            ctl.finalize(path)
            doc = json.loads(path.read_text())
            self.assertEqual(doc["status"], "FAILED")
            self.assertTrue(doc["persisted"])
            self.assertFalse(doc["resource_release"]["resources_released"])
            self.assertFalse(doc["cleanup"]["cleanup_complete"])
            self.assertFalse(ctl.resource_release["resources_released"])
            self.assertTrue(ctl.persisted)

    def test_repeated_close_is_idempotent(self):
        clock, config, plan, backend, ctl = self.make()
        ctl.prepare(plan)
        ctl.await_start()
        ctl.finish()
        ctl.close()
        first = dict(ctl.resource_release)
        ctl.close()
        self.assertTrue(first["resources_released"])
        self.assertTrue(ctl.resource_release["resources_released"])
        self.assertTrue(backend.handles[0].stdout_closed)

    def test_context_exception_releases_without_finalize(self):
        clock, config, plan, backend, ctl = self.make()
        with self.assertRaises(RuntimeError):
            with ctl:
                ctl.prepare(plan)
                ctl.await_start()
                raise RuntimeError("test exception")
        self.assertEqual(ctl.state, L.State.FAILED)
        self.assertTrue(ctl.resource_release["resources_released"])
        self.assertTrue(backend.handles[0].stdout_closed)
        self.assertFalse(ctl.persisted)

    # 6. cost wording is not a behavior test; the component test is the
    # config/intensity assertion below.
    def test_fixed_intensity_has_no_runtime_adaptation(self):
        cfg = L.InterferenceConfig()
        intensity = cfg.fixed_intensity()
        self.assertFalse(intensity["runtime_adaptation"])
        self.assertEqual(intensity["copy_length_bytes"], 32 * 1024 * 1024)


FIXTURE_WORKER = Path(__file__).resolve().parent / "fixtures" / "m3_nonpressure_worker_fixture.py"


class RealProcessBoundaryTests(unittest.TestCase):
    """Real pipe/shared-memory path with a non-pressure fixture (no memmove)."""

    def test_real_subprocess_boundary_and_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            clock = L.SystemClock()
            start = clock.monotonic_ns() + 300_000_000
            plan = L.WindowPlan.absolute(start, start + 200_000_000)
            config = L.InterferenceConfig()
            backend = L.SubprocessBackend(worker_path=FIXTURE_WORKER)
            ctl = L.InterferenceController(config, backend=backend)
            ctl.prepare(plan)
            self.assertEqual(ctl.state, L.State.READY)
            self.assertEqual(ctl.ready_evidence["pre_window_copy_ops"], 0)
            ctl.await_start()
            ctl.finish()
            self.assertEqual(ctl.state, L.State.STOPPED)
            self.assertTrue(ctl.cleanup["exit_confirmed"])
            self.assertTrue(ctl.cleanup["cleanup_complete"])
            self.assertEqual(ctl.worker_final["copies"], 7)
            self.assertIn(ctl.worker_final["exit_reason"], ("window_elapsed", "sigterm"))
            self.assertIsNotNone(ctl.heartbeat_final)
            out = Path(td) / "evidence.json"
            ctl.finalize(out)
            doc = json.loads(out.read_text())
            self.assertEqual(doc["state"], "STOPPED")
            self.assertEqual(doc["status"], "WINDOW_COMPLETE")
            self.assertTrue(doc["persisted"])
            self.assertFalse(doc["persisted_inside_window"])
            release = ctl.resource_release
            self.assertTrue(release["process_exit_confirmed"])
            self.assertTrue(release["stdout_closed"])
            self.assertTrue(release["stderr_closed"])
            self.assertTrue(release["shm_closed"])
            self.assertTrue(release["shm_unlinked"])
            self.assertTrue(release["resources_released"])
            self.assertTrue(ctl.persisted)
            self.assertTrue(ctl.memory_evidence)
            self.assertIn("worker_final", ctl.memory_evidence)


class Recorder(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self._start = 0.0

    def startTest(self, test):
        self._start = time.monotonic()
        super().startTest(test)

    def _record(self, test, status):
        self.records.append(dict(name=test.id(), status=status,
                                 duration_s=time.monotonic() - self._start))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "PASS")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "FAIL")

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "ERROR")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "SKIP")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    loader = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2, resultclass=Recorder,
                                     stream=sys.stdout)
    started = time.monotonic()
    result = runner.run(loader)
    duration = time.monotonic() - started
    status = "PASS" if result.wasSuccessful() else "FAIL"
    records = result.records
    fake_count = len([r for r in records
                      if "RealProcessBoundaryTests" not in r["name"]])
    real_count = len([r for r in records
                      if "RealProcessBoundaryTests" in r["name"]])
    doc = dict(
        status=status,
        component_version=dict(worker=W.WORKER_VERSION, lifecycle=L.SCHEMA),
        scope=("CPU logic only: fake clock/process and 1 KiB buffers; one non-pressure "
               "real pipe/shared-memory fixture. No real 32 MiB pressure loop, no model/"
               "CUDA/SSH/hardware write. Not board safety or interference-effect evidence."),
        started_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        duration_s=duration,
        tests_run=result.testsRun,
        failures=len(result.failures),
        errors=len(result.errors),
        skipped=len(result.skipped),
        groups=dict(
            pure_fake_clock_small_buffer=dict(
                tests=fake_count,
                includes=["LifecycleTests", "R1SpecTests", "WorkerLoopTests"]),
            real_pipe_shared_memory_nonpressure_fixture=dict(
                tests=real_count, includes=["RealProcessBoundaryTests"]),
            environment_limited_not_run=dict(
                tests=0,
                not_run=[
                    "real 32 MiB memmove worker (Linux/nvidia/CPU11; not started)",
                    "board CPU11 affinity/RSS/thermal/residual evidence",
                    "window-time strace/file-I/O audit",
                    "GPU/replay t0 integration and board acceptance",
                ],
                rule="not run is not PASS and is not an implementation-logic failure"),
        ),
        tests=records,
        components={
            "m3_interference_worker.py": dict(
                path=str(Path(W.__file__).resolve()),
                sha256=hashlib.sha256(Path(W.__file__).read_bytes()).hexdigest()),
            "m3_interference_lifecycle.py": dict(
                path=str(Path(L.__file__).resolve()),
                sha256=hashlib.sha256(Path(L.__file__).read_bytes()).hexdigest()),
            "m3_nonpressure_worker_fixture.py": dict(
                path=str(FIXTURE_WORKER),
                sha256=hashlib.sha256(FIXTURE_WORKER.read_bytes()).hexdigest()),
            "validate_m3_interference_lifecycle_cpu.py": dict(
                path=str(Path(__file__).resolve()),
                sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
            "worker_config_fingerprint": W.config_fingerprint(),
        },
        environment=dict(python=sys.version, platform=sys.platform, cwd=os.getcwd()),
    )
    if args.json:
        Path(args.json).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: doc[k] for k in
                      ("status", "tests_run", "failures", "errors", "skipped")},
                     sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
