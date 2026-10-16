"""What the CALLING THREAD did over an interval: its CPU time and the kernel's per-thread switch, fault and block counts.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY IT EXISTS. A wall-clock duration cannot say why an operation was slow, and the 16 Oct 2026 bundles show it: a
``SAVEPOINT`` (no table, index, FTS or WAL work) averaged 36.5 s against 35.0 s for an ``INSERT INTO articles``, so most of
that time was not the statement's own work and the record could not say what it was. The same thread's CPU time over the
same interval can: CPU close to the wall time is work, CPU far below it is a wait, and the counters below say what kind.

* ``cpu_ms``: the thread's CPU time (user and system), in milliseconds.
* ``nvcsw``: voluntary context switches, the thread giving the CPU up to wait (a lock, a sleep, a read, the GIL). A large
  count with ``cpu_ms`` far below the wall time is a wait. It CANNOT tell a SQLite busy-handler sleep from a wait for the GIL:
  both are voluntary, so a wait is named a wait and its owner is not guessed.
* ``nivcsw``: involuntary switches, the scheduler taking the CPU away: CPU starvation (50 workers on 2 cores).
* ``majflt`` and ``inblock``: major page faults and blocks read from disk: memory pushed out to swap, or cold pages, as against
  a lock.

A figure the OS cannot give is ABSENT from the answer, never 0: ``RUSAGE_THREAD`` is Linux only and ``time.thread_time`` may
be unavailable, and a 0 would read as "the thread did not wait". Counts and seconds only: no statement, no value, no name.

COST, measured on the development machine (a 2-core Intel under a Linux 6.18 kernel): 0.32 microseconds for ``thread_time``
and 0.57 for the four counters, so a :func:`sample` is under a microsecond. Never raises: it runs before every statement the
engine sends, on every thread, so an unsupported clock is "no figure", not an error.
"""

from __future__ import annotations

import time

try:  # POSIX only: Windows has no resource module, and the figures it gives are then absent, not 0
    import resource as _resource
except ImportError:  # pragma: no cover - platform
    _resource = None  # type: ignore[assignment]

#: The kernel's per-thread counters a figure set carries, in the order :func:`sample` returns them.
COUNTS = ("nvcsw", "nivcsw", "majflt", "inblock")

#: ``RUSAGE_THREAD`` where the OS has it (Linux), else ``None`` and the counters are absent.
RUSAGE_THREAD = getattr(_resource, "RUSAGE_THREAD", None)

#: A sample: the thread's CPU seconds and its four counters, each ``None`` where the OS cannot say.
Sample = tuple[float | None, tuple[int, int, int, int] | None]


def sample() -> Sample:
    """The calling thread's CPU seconds and (nvcsw, nivcsw, majflt, inblock) now, each ``None`` where the OS cannot say."""
    cpu: float | None
    try:
        cpu = time.thread_time()
    except (OSError, ValueError, AttributeError):
        cpu = None
    counts: tuple[int, int, int, int] | None = None
    if _resource is not None and RUSAGE_THREAD is not None:
        try:
            r = _resource.getrusage(RUSAGE_THREAD)
            counts = (int(r.ru_nvcsw), int(r.ru_nivcsw), int(r.ru_majflt), int(r.ru_inblock))
        except (OSError, ValueError):
            counts = None
    return cpu, counts


def since(before: Sample) -> dict[str, float | int]:
    """What the calling thread did since ``before`` (an earlier :func:`sample` OF THIS THREAD), as record fields.

    ``cpu_ms`` (one decimal) and the four counters; a field either sample could not give is left out. A thread's counters
    never go down, so a negative difference (a sample from another thread) is clamped to 0 rather than shown as a nonsense."""
    cpu0, counts0 = before
    cpu1, counts1 = sample()
    out: dict[str, float | int] = {}
    if cpu0 is not None and cpu1 is not None:
        out["cpu_ms"] = round(max(0.0, cpu1 - cpu0) * 1000.0, 1)
    if counts0 is not None and counts1 is not None:
        for name, a, b in zip(COUNTS, counts0, counts1, strict=True):
            out[name] = max(0, b - a)
    return out
