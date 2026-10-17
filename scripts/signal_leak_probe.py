"""Measure whether a real KeyboardInterrupt can leave a lock taken (R144). NOT run by CI: it is timing-dependent and it measures.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Usage: ``python scripts/signal_leak_probe.py {condition|raw|raw_notify|wait} [seconds]``

A SIGALRM handler raises KeyboardInterrupt at 0.3 ms intervals while the main thread loops ``with <lock>: <body>``; after each interrupt it
asks whether the lock is still owned (a leak) and releases it so the loop can go on. Variants:
  condition   ``with threading.Condition():``            the form R144 removed
  raw         ``with threading.RLock():``                 the form it uses
  raw_notify  ``with raw: condition.notify_all()``        a Condition built on the raw lock, notified inside
  wait        ``with raw: condition.wait(0.00002)``       the one Python-frame path left (reports RuntimeError masks, not leaks)

Measured on CPython 3.13: condition 15,174 of 43,142 left held; raw 0 of 40,151; raw_notify 0 of 46,483; wait 0 left held (174 of 65,632 became a
RuntimeError). On 3.14.0rc2 the ``with`` statement no longer compiles to BEFORE_WITH and raw left 6,516 of 8,157 held, condition 2,410 of 8,123:
re-run this on any new interpreter before accepting it, and see ``tests/test_condition_with_form.py``.
"""

from __future__ import annotations

import collections
import signal
import sys
import threading
import time

_INTERVAL_S = 0.0003


def main(argv: list[str]) -> int:
    variants = ("condition", "raw", "raw_notify", "wait")
    if not argv or argv[0] not in variants:
        print(__doc__)
        return 2
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
        while time.monotonic() < end:
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
