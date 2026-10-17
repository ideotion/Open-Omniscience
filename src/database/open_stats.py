"""
How often an encrypted file was opened with its key, from which thread, and what each open cost.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Opening an encrypted file derives its key again (SQLCipher: PBKDF2-HMAC-SHA512 x 256,000: 163 ms of thread CPU, median
of 20 on one pinned core, range 158-208 ms), and nothing in the app keeps the result: it lives inside the connection that
was opened. So every new connection to an encrypted file costs that, whoever asked for it (the pool growing, the
custody log, a lane's store). Until this module nothing counted them, which is why "one collector thread spends 41 CPU
seconds a minute where the sampled frame is the key derivation" could be neither confirmed nor refuted from a bundle:
the sampled frame says where a thread stood at one instant, and the thread's CPU is its total.

``src/database/connect.py`` calls :func:`begin` / :func:`end` around each keyed open of an existing encrypted file;
the collection monitor opens a window with :func:`reset` when a pass starts and writes :func:`safe_snapshot` into the
pass's summary line in ``collect_perf.jsonl`` (``encrypted_opens``) and, through the scheduler, into the pass's run
report (``scheduler_runs.jsonl``, so ``scheduler.recent_runs`` in the debug bundle), the same two places as
``extraction_lock`` (``src/ingest/lock_stats.py``).

What is counted, and what is not:

* every ATTEMPT to open an existing encrypted file with the key: a failed attempt paid the derivation too, and a file
  opened at several candidate page sizes (the probe in ``connect``) is one attempt per size;
* NOT plaintext opens (no derivation), and NOT the creation of a new encrypted file (once per store);
* the window is process-wide between :func:`reset` and :func:`snapshot`, so the opens of every thread during a pass
  are in it, the collector's and everyone else's; an open that begins before the reset and ends after it is counted
  when it ENDS. Opens while no pass runs are in no pass's window, and neither are those of the step the scheduler runs
  after the monitor stops (the repayment of owed custody entries). A pass without a monitor (the sequential path, used
  only on a caller's own session) opens no window and writes no block;
* NUMBERS AND TWO CLOSED VOCABULARIES ONLY. ``file`` is one of the app's own database file names (:data:`KNOWN_FILES`),
  else ``(other)``: a path is never printed, and a restore or merge opens files whose names a person chose. ``thread`` is
  the FAMILY of the opening thread's name (``oo-collect`` for ``oo-collect_22``, ``oo-osm`` for ``oo-osm-fr``, or one of
  the fixed names in :data:`_NAMED_FAMILIES`), else ``(other)``: several threads are named from a request, and the part
  after the first word is that request's text. The key, the passphrase and every exception text never reach this module:
  it is handed a path, a flag and two clocks;
* ``cpu_s`` is the sum of the opening threads' own CPU time over the opens that could be measured; when none could, it is
  ABSENT and ``cpu_unmeasured`` says how many, never a zero.

Best-effort by construction: arithmetic under a private lock, no I/O, taken after the open is over. :func:`end` swallows
its own ``Exception``, so a fault in the statistic cannot replace an open's result.
"""

from __future__ import annotations

import re
import threading
import time

#: A leaf lock: nothing is called while it is held.
_STATS_LOCK = threading.Lock()

#: The database files the app opens by a name of its own (the names ``src`` writes in code). Any other name is reported as
#: :data:`OTHER`.
KNOWN_FILES = (
    "open_omniscience.db",
    "custody_log.db",
    "wiki.db",
    "law.db",
    "osm.db",
    "anchors.db",
    "working.db",
    "corpus.db",
)
OTHER = "(other)"
OTHERS = "(others)"

#: Thread names written by this app begin ``oo-<word>``; what follows the word may be a request's text (``oo-osm-{key}``),
#: which is why only the word is kept (letters up to the first ``-``, ``_`` or digit).
_APP_FAMILY = re.compile(r"oo-[a-z]{1,16}(?![a-z])")
#: The other families that open the store, by the start of their names: the framework's threads, and the app's own threads
#: whose names are fixed words (a tail after the family, where there is one, is a cache key or a code, and is not kept).
_NAMED_FAMILIES = (
    "MainThread",
    "AnyIO worker thread",  # what anyio and starlette's run_in_threadpool name their workers (a sync FastAPI endpoint)
    "ThreadPoolExecutor",
    "asyncio",  # the event loop's default executor: asyncio_0, asyncio_1, ...
    "bgjob",  # src/jobs/background.py: bgjob-<kind>
    "rollup-build",
    "map-rollup-build",
    "search-reindex-job",
    "reindex-job",
    "quarantine-job",
    "keyword-fold-job",
    "import-queue",
    "model-pull",
    "vllm-install-pump",
    "rss-sampler",
    "gpu-sampler",
    "alerts-poll-refresh",
    "all-diag-member",
    "served-cache",
    "osm-admin1",
    "ref-run-sampler",
)

#: Rows the window keeps, one per (file, thread family) pair, THE FIRST ones seen in the window (not the heaviest: which
#: pair is heaviest is not known until the pass ends). WHAT IT PROTECTS: the memory of a window that a long pass leaves
#: open and the size of the record it is printed from. The number is a bound, not a measurement: a pass has a handful of
#: app files opened by a handful of thread families, and 32 leaves room; a later pair is added to the ``(others)`` row, and
#: an open of a pair already kept always goes to its own row. It shrinks what is KEPT per pair, never what is COUNTED:
#: the totals are exact.
_STATE_ROWS = 32
#: Rows printed in the block, the most CPU first among those kept; the rest are summed into one ``(others)`` row. WHAT IT
#: PROTECTS: the size of one run report. A printed row is 128 bytes in a typical block and at most 209 (the longest file
#: and family strings, 10-digit counts, 7-digit seconds: computed, ``tests/test_open_stats.py``), and the method text is
#: 551, so a block is about 2 KB typically and at most 3.2 KB (computed), and the 30 reports of a debug bundle add at most
#: 97 KB (computed). It shrinks what is PRINTED, never what is COUNTED.
_PRINT_ROWS = 11


def _fresh_total() -> dict:
    return {"opens": 0, "failed": 0, "cpu_s": 0.0, "wall_s": 0.0, "wall_max_s": 0.0, "cpu_unmeasured": 0}


_totals: dict = _fresh_total()
_rows: dict[tuple[str, str], dict] = {}

#: What the numbers mean, carried in every snapshot that has any (the repo's rule: a signal says its method with it).
METHOD = (
    "attempts to open an existing encrypted file with its key, each paying one key derivation (a failed attempt counts, "
    "and so does each page size tried for one open); plaintext opens and new files are not counted; cpu_s = the opening "
    "thread's own CPU time, wall_s = elapsed time; file = one of the app's own database files or (other); thread = the "
    "family of the opening thread's name (oo-collect for oo-collect_22, or a fixed name such as rollup-build) or (other); "
    "cpu_s is absent when no open's CPU could be measured; the window is this pass, all threads"
)


def now() -> float:
    """The wall clock the statistics read (a name of its own so a test can drive it)."""
    return time.monotonic()


def cpu_now() -> float:
    """The calling thread's own CPU time, in seconds (a name of its own so a test can drive it)."""
    return time.thread_time()


def reset() -> None:
    """Start a new window: forget every open recorded so far."""
    with _STATS_LOCK:
        _totals.clear()
        _totals.update(_fresh_total())
        _rows.clear()


def file_label(path: object) -> str:
    """The closed-vocabulary name of the file at ``path``: one of :data:`KNOWN_FILES`, else :data:`OTHER`."""
    try:
        name = re.split(r"[\\/]", str(path))[-1]
    except Exception:  # noqa: BLE001 - a path that cannot be read is "other"
        return OTHER
    return name if name in KNOWN_FILES else OTHER


def thread_family(name: object) -> str:
    """The family of a thread's name: ``oo-<word>`` for this app's own threads, a name from :data:`_NAMED_FAMILIES`, else
    :data:`OTHER`."""
    try:
        text = str(name)
        match = _APP_FAMILY.match(text)
        if match:
            return match.group(0)
        for family in _NAMED_FAMILIES:
            if text.startswith(family):
                return family
    except Exception:  # noqa: BLE001 - a name that cannot be read is "other"
        pass
    return OTHER


def begin() -> tuple[float, float | None] | None:
    """Take the clocks at the start of an open; ``None`` when they cannot be read (the open then goes uncounted)."""
    try:
        wall = now()
        try:
            cpu: float | None = cpu_now()
        except Exception:  # noqa: BLE001 - no per-thread CPU clock: the open is counted, its CPU is not
            cpu = None
        return wall, cpu
    except Exception:  # noqa: BLE001 - a statistic never fails an open
        return None


def end(started: tuple[float, float | None] | None, path: object, ok: bool) -> None:
    """Add one finished open. ``started`` is what :func:`begin` returned; ``ok`` is whether the file opened."""
    if started is None:
        return
    try:
        wall = max(0.0, now() - started[0])
        cpu: float | None
        try:
            cpu = None if started[1] is None else max(0.0, cpu_now() - started[1])
        except Exception:  # noqa: BLE001 - see begin()
            cpu = None
        key = (file_label(path), thread_family(threading.current_thread().name))
        with _STATS_LOCK:
            _add(_totals, ok, cpu, wall)
            row = _rows.get(key)
            if row is None:
                if len(_rows) >= _STATE_ROWS:
                    key = (OTHERS, OTHERS)
                    row = _rows.get(key)
                if row is None:
                    row = _rows[key] = _fresh_total()
            _add(row, ok, cpu, wall)
    except Exception:  # noqa: BLE001 - a statistic never replaces an open's result
        return


def _add(into: dict, ok: bool, cpu: float | None, wall: float) -> None:
    into["opens"] += 1
    if not ok:
        into["failed"] += 1
    if cpu is None:
        into["cpu_unmeasured"] += 1
    else:
        into["cpu_s"] += cpu
    into["wall_s"] += wall
    if wall > into["wall_max_s"]:
        into["wall_max_s"] = wall


def _printed(source: dict) -> dict:
    out = {"opens": source["opens"], "failed": source["failed"]}
    if source["cpu_unmeasured"] < source["opens"]:  # no CPU figure at all is absent, never a zero
        out["cpu_s"] = round(source["cpu_s"], 3)
    out["wall_s"] = round(source["wall_s"], 3)
    out["wall_max_s"] = round(source["wall_max_s"], 3)
    if source["cpu_unmeasured"]:
        out["cpu_unmeasured"] = source["cpu_unmeasured"]  # of the opens, how many have no CPU time in cpu_s
    return out


def snapshot() -> dict:
    """The window so far, as plain numbers. A window with no open says only ``opens: 0``."""
    with _STATS_LOCK:
        if not _totals["opens"]:
            return {"opens": 0}
        named = sorted(
            ((k, r) for k, r in _rows.items() if k != (OTHERS, OTHERS)),
            key=lambda kv: (-kv[1]["cpu_s"], -kv[1]["opens"], kv[0]),
        )
        by = [{"file": f, "thread": t, **_printed(r)} for (f, t), r in named[:_PRINT_ROWS]]
        rest = [r for _key, r in named[_PRINT_ROWS:]]
        if (OTHERS, OTHERS) in _rows:  # the pairs that did not fit in the window's rows
            rest.append(_rows[(OTHERS, OTHERS)])
        if rest:
            merged = _fresh_total()
            for r in rest:
                merged["opens"] += r["opens"]
                merged["failed"] += r["failed"]
                merged["cpu_s"] += r["cpu_s"]
                merged["wall_s"] += r["wall_s"]
                merged["cpu_unmeasured"] += r["cpu_unmeasured"]
                merged["wall_max_s"] = max(merged["wall_max_s"], r["wall_max_s"])
            by.append({"file": OTHERS, "thread": OTHERS, **_printed(merged)})
        out = _printed(_totals)
        out["by"] = by
        out["method"] = METHOD
        return out


def safe_snapshot() -> dict:
    """:func:`snapshot`, or the class of the failure that kept it from being read (never its words, never a zero)."""
    try:
        return snapshot()
    except Exception as exc:  # noqa: BLE001 - the pass is written without the figures, saying so
        return {"unavailable": type(exc).__name__}
