"""Measure whether a real KeyboardInterrupt can leave a lock taken (R144). NOT run by CI: it is timing-dependent and it measures.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Usage: ``python scripts/signal_leak_probe.py {condition|raw|raw_notify|wait} [seconds]``
       ``python scripts/signal_leak_probe.py {gate_writer|gate_writer_bounded|gate_pool|gate_governor|gate_hold|gate_library|gate_library_swap|gate_swap_window} [seconds] [--plain]``

A SIGALRM handler raises KeyboardInterrupt at 0.3 ms intervals while the main thread loops ``with <lock>: <body>``; after each interrupt it
asks whether the lock is still owned (a leak) and releases it so the loop can go on. Variants:
  condition   ``with threading.Condition():``            the form R144 removed
  raw         ``with threading.RLock():``                 the form it uses
  raw_notify  ``with raw: condition.notify_all()``        a Condition built on the raw lock, notified inside
  wait        ``with raw: condition.wait(0.00002)``       the one Python-frame path left (reports RuntimeError masks, not leaks)

The ``gate_*`` variants run the REAL gate (the write gate, the pool reservation, the collection governor, the settings write hold, the library
lock) instead of a bare Condition: a helper thread owns the resource and keeps waking the waiter, the main thread blocks in the gate's own wait,
and the SIGALRM interrupt is what ends that wait. After each interrupt the probe reports what came out (``KeyboardInterrupt`` is the right
answer; ``RuntimeError`` is the mask this change removes), whether the gate's lock is still owned by the main thread, and whether the gate's own
counters were left wrong. ``--plain`` replaces the gate module's ``_wait`` with a bare ``cond.wait`` (the code before ``src.utils.interrupts``), so one
script gives the before and the after on the same machine. The gates need the repository on ``sys.path``; run it from the repository root.

Measured on CPython 3.13: condition 15,174 of 43,142 left held; raw 0 of 40,151; raw_notify 0 of 46,483; wait 0 left held (174 of 65,632 became a
RuntimeError). On 3.14.0rc2 the ``with`` statement no longer compiles to BEFORE_WITH and raw left 6,516 of 8,157 held, condition 2,410 of 8,123:
re-run this on any new interpreter before accepting it, and see ``tests/test_condition_with_form.py``.
"""

from __future__ import annotations

import collections
import os
import signal
import sys
import threading
import time

_INTERVAL_S = 0.0003


GATES = ("gate_writer", "gate_writer_bounded", "gate_pool", "gate_governor", "gate_hold", "gate_library", "gate_library_swap", "gate_swap_window",
         "gate_corpus_lease", "gate_user_batch_hold", "gate_inflight", "gate_pass_in_flight")


def _plain_wait(cond, lock, timeout=None):  # noqa: ARG001 - the signature of src.utils.interrupts.wait
    return cond.wait(timeout)


class _Scenario:
    """One gate, held by somebody else, plus what to call on it, how to wake its waiter, and how to tell whether an interrupt damaged it."""

    def __init__(self, name: str, plain: bool) -> None:
        sys.path.insert(0, ".")
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []
        self.name = name
        self.plain = plain
        getattr(self, "_" + name)()
        self.helper = all(hasattr(mod, "_wait") for mod in self.patch_modules)  # a tree from before src.utils.interrupts has none
        if plain:
            for mod in self.patch_modules:
                mod._wait = _plain_wait  # noqa: SLF001 - the before-the-fix behaviour, on purpose

    def _park(self, fn) -> None:
        ready = threading.Event()

        def run() -> None:
            fn()
            ready.set()
            self.stop.wait()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.threads.append(t)
        assert ready.wait(5), "the helper thread did not take the resource"

    def _kick_loop(self, wake) -> None:
        def run() -> None:
            while not self.stop.is_set():
                wake()
                time.sleep(0)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.threads.append(t)

    def _gate_writer_common(self, timeout) -> None:
        from src.database import writer

        gate = writer.WriterGate()
        self.patch_modules = [writer]
        self.lock, self.cond = gate._lock, None
        self._park(gate.acquire)  # the owner: another thread, for good

        def wake() -> None:
            with gate._lock:
                gate._wake_head()

        self._kick_loop(wake)
        self.call = lambda: gate.acquire(timeout=timeout)

        def damage() -> list[str]:
            bad = []
            if gate._waiters or gate._queue:  # noqa: SLF001
                bad.append("waiter left counted or queued")
                gate._waiters = 0  # noqa: SLF001
                gate._queue.clear()  # noqa: SLF001
            return bad

        self.damage = damage
        self.stale = lambda: 0

    def _gate_writer(self) -> None:
        self._gate_writer_common(None)

    def _gate_writer_bounded(self) -> None:
        self._gate_writer_common(30.0)

    def _gate_pool(self) -> None:
        from src.database import pool_reserve

        slots = pool_reserve._Slots(1)  # noqa: SLF001
        self.patch_modules = [pool_reserve]
        self.lock, self.cond = slots._lock, slots._cond  # noqa: SLF001
        self._park(lambda: slots.acquire(1, 1.0))

        def wake() -> None:
            with slots._lock:  # noqa: SLF001
                slots._cond.notify_all()  # noqa: SLF001

        self._kick_loop(wake)
        self.call = lambda: slots.acquire(2, 30.0)
        self.damage = lambda: [] if set(slots._held) == {1} else ["slot table changed"]  # noqa: SLF001
        self.stale = lambda: len(slots._cond._waiters)  # noqa: SLF001

    def _gate_governor(self) -> None:
        from src.scheduler import bandwidth

        sem = bandwidth._AdjustableSemaphore(1)  # noqa: SLF001
        self.patch_modules = [bandwidth]
        self.lock, self.cond = sem._lock, sem._cond  # noqa: SLF001
        sem.acquire()  # the one permit is taken, by this (main) thread: the next acquire waits
        self._kick_loop(lambda: sem.set_permits(1))
        self.call = sem.acquire
        self.damage = lambda: [] if sem.active == 1 else [f"active={sem.active}, expected 1"]
        self.stale = lambda: len(sem._cond._waiters)  # noqa: SLF001

    def _gate_hold(self) -> None:
        from src.config import kv_store

        self.patch_modules = [kv_store]
        self.lock, self.cond = kv_store._hold_lock, kv_store._hold  # noqa: SLF001
        token = object()
        with kv_store._hold_lock:  # noqa: SLF001
            kv_store._inflight.add(token)  # noqa: SLF001 - a write in flight: the hold has to wait for it

        def wake() -> None:
            with kv_store._hold_lock:  # noqa: SLF001
                kv_store._hold.notify_all()  # noqa: SLF001

        self._kick_loop(wake)

        def call() -> None:
            with kv_store.hold_writes(30.0):
                pass

        self.call = call
        def damage() -> list[str]:
            if kv_store._hold_by is None:  # noqa: SLF001
                return []
            kv_store._hold_by = None  # noqa: SLF001 - cleared so the next iteration measures its own interrupt, not the first one's damage
            return ["hold left set"]

        self.damage = damage
        self.stale = lambda: len(kv_store._hold._waiters)  # noqa: SLF001

    def _gate_library_common(self, mode: str) -> None:
        from src.database import library_generation as lg

        lock = lg._Lock()  # noqa: SLF001
        self.patch_modules = [lg]
        self.lock, self.cond = lock._lock, lock._cond  # noqa: SLF001
        if mode == "shared":  # the swap holds the library: an open waits
            lock._holder = -1  # noqa: SLF001
            self.call = lock.shared
        else:  # an open is in flight: the swap waits (bounded)
            lock._shared = 1  # noqa: SLF001
            self.call = lambda: lock.exclusive(30.0)

        def wake() -> None:
            with lock._lock:  # noqa: SLF001
                lock._cond.notify_all()  # noqa: SLF001

        self._kick_loop(wake)

        def damage() -> list[str]:
            bad = []
            here = getattr(lock, "shared_held_here", lambda: 0)()  # older trees have no per-thread record
            if mode == "shared" and (lock._shared or here):  # noqa: SLF001
                bad.append("shared level left raised")
                lock._shared = 0  # noqa: SLF001
                if hasattr(lock, "_mine"):
                    lock._mine.n = 0  # noqa: SLF001
            if mode != "shared" and lock._holder is not None:  # noqa: SLF001
                bad.append("swap holder left set")
                lock._holder = None  # noqa: SLF001
            return bad

        self.damage = damage
        self.stale = lambda: len(lock._cond._waiters)  # noqa: SLF001

    def _gate_library(self) -> None:
        self._gate_library_common("shared")

    def _gate_library_swap(self) -> None:
        self._gate_library_common("exclusive")

    def _gate_swap_window(self) -> None:
        """The whole ``swap_window`` context manager, free to be had: the interrupt lands anywhere from the acquire to the release, including the
        statements between the acquire and its ``try``."""
        import tempfile
        from pathlib import Path

        from src.database import library_generation as lg

        lock = lg._Lock()  # noqa: SLF001
        saved = lg._LOCK  # noqa: SLF001
        lg._LOCK = lock  # noqa: SLF001
        self._restore = lambda: setattr(lg, "_LOCK", saved)
        self.patch_modules = [lg]
        self.lock, self.cond = lock._lock, None  # noqa: SLF001
        source = Path(tempfile.mkdtemp(prefix="oo-swap-probe-")) / "library.db"
        source.write_bytes(b"x")  # it still exists when the window ends: the swap did not happen

        def call() -> None:
            with lg.swap_window(source, timeout=30.0):
                pass

        def damage() -> list[str]:
            bad = []
            if lock._holder is not None:  # noqa: SLF001
                bad.append("swap holder left set")
                lock._holder = None  # noqa: SLF001
            if lg._WINDOW_STAMP is not None:  # noqa: SLF001
                bad.append("window stamp left set")
                lg._WINDOW_STAMP = None  # noqa: SLF001
            # (library_generation has no lock of its own for the window's state any more: it is written only inside the window)
            return bad

        self.call = call
        self.damage = damage
        self.stale = lambda: 0

    def _cm(self, call, damage) -> None:
        """A context manager that is free to be had: the interrupt lands anywhere from its first statement to its last."""
        self.lock, self.cond = threading.RLock(), None
        self.patch_modules = []
        self.call = call
        self.damage = damage
        self.stale = lambda: 0

    def _gate_corpus_lease(self) -> None:
        from src.database import corpus_lease as cl

        def call() -> None:
            with cl.corpus_lease("probe"):
                pass

        def damage() -> list[str]:
            raised = any(n > 0 for n in cl._HELD.values())  # noqa: SLF001 - a name at zero is given back (active_leases does not list it)
            cl._HELD.clear()  # noqa: SLF001
            return ["lease left raised"] if raised else []

        self._cm(call, damage)

    def _gate_user_batch_hold(self) -> None:
        from src.ai_layer import coordinator as co

        def call() -> None:
            with co.user_batch_hold("probe"):
                pass

        def damage() -> list[str]:
            bad = []
            if co._hold_count:  # noqa: SLF001
                bad.append("hold count left raised")
                co._hold_count = 0  # noqa: SLF001
            if co._hold_reasons:  # noqa: SLF001
                bad.append("hold reason left listed")
                del co._hold_reasons[:]  # noqa: SLF001
            return bad

        self._cm(call, damage)

    def _gate_inflight(self) -> None:
        from src.llm import inflight as inf

        def call() -> None:
            with inf.generating("probe", backend="probe"):
                pass

        def damage() -> list[str]:
            if not inf._OPEN:  # noqa: SLF001
                return []
            inf._OPEN.clear()  # noqa: SLF001
            return ["in-flight call left open"]

        self._cm(call, damage)

    def _gate_pass_in_flight(self) -> None:
        from src.database import verify as vf

        def call() -> None:
            with vf._pass_in_flight("probe"):  # noqa: SLF001
                pass

        def damage() -> list[str]:
            if vf._PASS_FILE is None:  # noqa: SLF001
                return []
            vf._PASS_FILE = None  # noqa: SLF001
            return ["pass file left named"]

        self._cm(call, damage)

    def close(self) -> None:
        self.stop.set()
        getattr(self, "_restore", lambda: None)()


def _run_gate(name: str, seconds: float, plain: bool) -> int:
    sc = _Scenario(name, plain)
    armed = [False]

    def handler(*_args: object) -> None:
        if armed[0]:
            # ONE interrupt per iteration, like one Ctrl-C: a second one arriving while the first is still unwinding the caller's ``with`` lands in
            # the exit handler, where nothing in Python can protect it (measured: it alone left the lock owned in about 1 % of iterations)
            armed[0] = False
            raise KeyboardInterrupt

    signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, _INTERVAL_S, _INTERVAL_S)
    outcomes = collections.Counter()
    iterations = lock_left = damaged = stale = 0
    damage_kinds = collections.Counter()
    damage_where = collections.Counter()  # (damage kinds, where the interrupt landed): says WHICH statement lost the state
    end = time.monotonic() + seconds
    try:
        # ``while True: if not <cond>: break``, not ``while <cond>:``: the back-edge of the second sits outside the exception table of the
        # ``try`` on CPython 3.13, so a real Ctrl-C landing there would skip the ``finally`` that stops the timer (src/utils/interrupts.py; R163)
        while True:
            if time.monotonic() >= end:
                break
            iterations += 1
            landed = ""
            try:
                armed[0] = True
                try:
                    sc.call()
                    outcomes["returned (no interrupt)"] += 1
                finally:
                    armed[0] = False
            except BaseException as exc:  # noqa: BLE001 - counting what the interrupt turned into
                outcomes[type(exc).__name__] += 1
                landed = _landing(exc)
            # the exception is gone by here: a traceback still holding a suspended ``@contextmanager`` generator would read as "left held" until
            # the generator is collected, which is the exception's lifetime and not the code's
            if sc.lock._is_owned():  # noqa: SLF001 - the question is exactly whether this thread still holds it
                lock_left += 1
                while True:
                    if not sc.lock._is_owned():  # noqa: SLF001
                        break
                    sc.lock.release()
            bad = sc.damage()
            if bad:
                damaged += 1
                damage_kinds.update(bad)
                damage_where[(", ".join(bad), landed)] += 1
            if sc.cond is not None and len(sc.cond._waiters) > 0:  # noqa: SLF001
                stale += 1
                sc.cond._waiters.clear()  # noqa: SLF001 - stale entries an interrupted wait leaves
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0, 0)
        sc.close()
    total = sum(v for k, v in outcomes.items() if k != "returned (no interrupt)")
    print(
        f"{sys.version.split()[0]} {name} [{'plain Condition.wait' if plain or not sc.helper else 'src.utils.interrupts.wait'}]: iterations={iterations} interrupts={total} "
        f"{dict(outcomes)} lock_left_owned={lock_left} counters_left_wrong={damaged} {dict(damage_kinds)} stale_waiter_entries={stale}"
    )
    for (kinds, landed), n in damage_where.most_common(8):
        print(f"    {n:6d}  {kinds}  <- interrupt landed in {landed}")
    return 0


def _landing(exc: BaseException) -> str:
    """The innermost frame of the interrupt's traceback outside the signal handler: ``function (file:line)``. An interrupt inside a cleanup call's
    own entry or body is the class a Python call cannot protect; one in the statements between an acquire and its ``try`` is the class to fix."""
    frames = []
    tb = exc.__traceback__
    while tb is not None:
        frames.append((tb.tb_frame.f_code.co_name, os.path.basename(tb.tb_frame.f_code.co_filename), tb.tb_lineno))
        tb = tb.tb_next
    if frames and frames[-1][0] == "handler":
        frames.pop()
    return "{} ({}:{})".format(*frames[-1]) if frames else "?"


def main(argv: list[str]) -> int:
    variants = ("condition", "raw", "raw_notify", "wait") + GATES
    plain = "--plain" in argv
    argv = [a for a in argv if a != "--plain"]
    if not argv or argv[0] not in variants:
        print(__doc__)
        return 2
    if argv[0] in GATES:
        return _run_gate(argv[0], float(argv[1]) if len(argv) > 1 else 10.0, plain)
    variant = argv[0]
    seconds = float(argv[1]) if len(argv) > 1 else 10.0
    raw = threading.RLock()
    cond = threading.Condition() if variant == "condition" else threading.Condition(raw)
    armed = [False]

    def handler(*_args: object) -> None:
        if armed[0]:
            raise KeyboardInterrupt

    signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, _INTERVAL_S, _INTERVAL_S)
    interrupts = collections.Counter()
    left_held = iterations = 0
    end = time.monotonic() + seconds
    try:
        # ``while True: if not <cond>: break``, not ``while <cond>:``: the back-edge of the second sits outside the exception table of the
        # ``try`` on CPython 3.13, so a real Ctrl-C landing there would skip the ``finally`` that stops the timer (src/utils/interrupts.py; R163)
        while True:
            if time.monotonic() >= end:
                break
            iterations += 1
            try:
                armed[0] = True
                try:
                    if variant == "condition":
                        with cond:
                            pass
                    elif variant == "raw":
                        with raw:
                            pass
                    elif variant == "raw_notify":
                        with raw:
                            cond.notify_all()
                    else:
                        with raw:
                            cond.wait(0.00002)
                finally:
                    armed[0] = False
            except BaseException as exc:  # noqa: BLE001 - counting what the interrupt turned into
                interrupts[type(exc).__name__] += 1
            lock = cond if variant == "condition" else raw
            if lock._is_owned():  # noqa: SLF001 - the question is exactly whether it is still taken
                left_held += 1
                while lock._is_owned():  # noqa: SLF001
                    (lock._lock if variant == "condition" else lock).release()  # noqa: SLF001
            if variant == "wait" and len(cond._waiters) > 50:  # noqa: SLF001 - stale entries an interrupted wait leaves
                cond._waiters.clear()  # noqa: SLF001
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0, 0)
    total = sum(interrupts.values())
    print(f"{sys.version.split()[0]} {variant}: iterations={iterations} interrupts={total} {dict(interrupts)} left_held={left_held} ({100 * left_held / max(total, 1):.2f}% of interrupts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
