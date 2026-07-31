"""A crash-surviving run journal for imports and exports.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS
---------------
Field night 2026-07-31. A 686,896-article import sat at ``15/19 ·
3000/686896`` for seven hours. Answering "is it stuck or is it slow?" took
manual ``ps`` sampling by hand, over several rounds, and the first verdict was
wrong. When the run was finally killed there was **no report at all** -- import
#14 does not exist -- because every number the import path produces is correct,
in memory, and written exactly once, at the end, on the success path.

So this is not an instrumentation project. The measurements already exist and
are already right (``StageTimings``, ``VolumeBackupManager._progress``,
``reindex_rates``, ``persist_import_report``). What was missing is a **sink**:
somewhere they land *while the run is in flight*, so a run that never reaches
its end still leaves evidence.

WHAT IT WRITES
--------------
Two files per run under ``data_dir()/run_logs/``:

``<run_id>.jsonl``       milestones -- append-only, fsync'd, **never trimmed**
``<run_id>.beat.jsonl``  heartbeat  -- newest-wins ring, flushed, not fsync'd

Two files, not one, for one reason: milestones must never be trimmed away and
heartbeats must be. Mixing them means either an unbounded file or a ring that
eventually eats the ``run_begin`` line.

THE FORENSIC CONTRACT
---------------------
A journal whose last line is not ``run_end`` describes a run that did not
finish. It is deliberately **not** claimed that such a run "crashed": a journal
disabled mid-run (ENOSPC on the sidecar's own volume) leaves the identical
signature, and asserting a crash we cannot distinguish from a muted sidecar
would be a fabricated diagnosis. :func:`promote_incomplete_runs` therefore
writes ``{"ev": "promoted", "outcome": "incomplete"}`` -- a DISTINCT event, never
a synthesised ``run_end``. Overloading the token whose absence carries the
signal would spend the evidence on the first boot after the crash.

HONESTY RULES ENFORCED HERE
---------------------------
* An unmeasurable field is **omitted** and its reason appended to
  ``unmeasured``. It is never zeroed, because a 0 in ``kids_n`` reads as "no
  worker processes" -- the exact inverse of the deadlock evidence it would be
  standing in for.
* ``moving`` is emitted **only** when the active phase owns a real progress
  counter and two consecutive samples both read it. ``prepare_staged`` (54% of
  a large import) publishes no counter at all, so a naive ``d_done == 0`` rule
  would report ``moving: false`` for ninety minutes of perfectly healthy work.
* Deltas are precomputed. A human reading 1,700 lines should not have to
  subtract two of them by hand -- that is a smaller version of the manual ``ps``
  sampling this replaces.
* ``bc_ms`` (the cost of taking the beat) is in every beat. The overhead is a
  measurement, not an assurance.

SAFETY
------
The journal must never break, block, or deadlock the operation it observes.

* Every write is wrapped; the FIRST failure disables that stream for the rest
  of the run (log once, no-op onward). A resilience sidecar that can itself
  abort a hard-won ten-hour import is worse than no sidecar.
* Milestones and beats have **separate locks and separate handles**, so a
  blocked write on one stream cannot stall the other.
* ``os.register_at_fork`` quiesces both locks across a fork and disables the
  journal in the child. The re-index runs a process pool; a fork while the
  sampler held a lock would hand the child a lock with no owner alive to
  release it -- which is precisely tonight's deadlock, reintroduced by the
  journal built to diagnose it.
* The sampler never touches the database: memory is psutil, WAL size is an
  ``os.stat``, the gate figures are in-memory counters. No connection, no
  session, no statement.
* :func:`progress` is on a ~700,000-call path. It is two attribute stores. No
  lock, no I/O, no clock read, no allocation.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

_DIR_NAME = "run_logs"

#: Heartbeat cadence. 15 s over a ten-hour import is ~2,400 lines: enough
#: resolution to see a stall begin, small enough to read.
_BEAT_INTERVAL_S = 15.0

#: Newest-wins cap on the beat ring. ~24 h at the default cadence.
_BEAT_CAP_LINES = 5760

#: Rewrite (trim) the ring every N appends rather than on every one.
_BEAT_TRIM_EVERY = 512

#: Above this measured per-beat cost the child-process walk is sampled at a
#: reduced cadence. `children(recursive=True)` enumerates /proc and builds a
#: Process object per pid; on a loaded box that is not free, and the beat must
#: never become a load source on the machine it is diagnosing.
_CHILD_WALK_BUDGET_MS = 25.0

#: The progress dicts published by VolumeBackupManager, by the EXACT key names
#: they actually use (src/backup/volume_job.py:304-335). There is no generic
#: `done`/`total` anywhere in the tree; assuming one would make every counter
#: read None on every path, forever.
_COUNTER_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("reindex", "reindex_done", "reindex_total"),
    ("merge", "merge_step", "merge_steps"),
)


def run_logs_dir() -> Path:
    from src.paths import data_dir

    return data_dir() / _DIR_NAME


def journal_enabled() -> bool:
    """On by default; ``OO_RUN_JOURNAL=0`` disables it.

    Default-on is the point: the run worth diagnosing is the one nobody
    expected to need diagnosing, and an opt-in journal is off precisely then.
    """
    return os.environ.get("OO_RUN_JOURNAL", "1") != "0"


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


#: run_id prefix per kind. A kind not listed here still journals -- it just gets a
#: generic prefix, because refusing to record an operation because its name is
#: unfamiliar is exactly the coverage gap this table exists to close.
_KIND_PREFIX: dict[str, str] = {
    "import": "imp",
    "export": "exp",
    "verify": "vfy",
    "folder-export": "fex",
    "folder-import": "fim",
    "newsletter-import": "nim",
}


def _new_run_id(kind: str) -> str:
    import secrets

    prefix = _KIND_PREFIX.get(kind, "run")
    return f"{prefix}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


# --------------------------------------------------------------------------- #
#  Per-field sampling helpers. Each returns a value or raises; the caller omits
#  a raising field and records WHY. A silent default here would be the
#  fabricated-zero the module docstring forbids.
# --------------------------------------------------------------------------- #
def _proc_cpu_s(proc: Any) -> float:
    t = proc.cpu_times()
    return round(t.user + t.system, 3)


def _sample_children(proc: Any, limit: int = 24) -> tuple[list[dict], float, float]:
    """``([{pid, cpu_s, rss_mb, age_s}, ...], total_cpu_s, total_rss_mb)``.

    The per-child CPU total is the field that actually answers "stuck or
    slow?" during the re-index: the work runs in a process pool, so a HEALTHY
    parent is also near-idle. Parent CPU alone cannot tell the two apart.

    ``total_rss_mb`` is a SUM of resident sets, which double-counts pages
    shared with the parent (a forked worker shares most of them). It is an
    upper bound, labelled as one where it is reported.
    """
    kids: list[dict] = []
    cpu_total = 0.0
    rss_total = 0.0
    now = time.time()
    for i, ch in enumerate(proc.children(recursive=True)):
        if i >= limit:
            break
        row: dict = {"pid": ch.pid}
        try:
            t = ch.cpu_times()
            c = round(t.user + t.system, 3)
            row["cpu_s"] = c
            cpu_total += c
        except Exception:  # noqa: BLE001 - a racing exit / AccessDenied omits the field
            pass
        try:
            r = round(ch.memory_info().rss / (1024 * 1024), 1)
            row["rss_mb"] = r
            rss_total += r
        except Exception:  # noqa: BLE001
            pass
        with suppress(Exception):
            row["age_s"] = round(now - ch.create_time(), 1)
        kids.append(row)
    return kids, round(cpu_total, 3), round(rss_total, 1)


def _wal_bytes() -> int:
    from src.paths import data_dir

    return (data_dir() / "open_omniscience.db-wal").stat().st_size


def _counter_of(prog: dict | None) -> tuple[str | None, int | None, int | None]:
    """``(source_name, done, total)`` from a progress dict, or ``(None, None,
    None)`` when the active phase publishes no counter at all.

    The third case is real and common -- ``prepare_staged``, ``verify`` and the
    reassembly all report a phase and nothing else -- and it must stay
    distinguishable from "a counter that read zero".
    """
    if not isinstance(prog, dict):
        return None, None, None
    for name, done_k, total_k in _COUNTER_SOURCES:
        d = prog.get(done_k)
        if isinstance(d, int):
            t = prog.get(total_k)
            return name, d, t if isinstance(t, int) else None
    return None, None, None


class RunLog:
    """One run's two streams. Construct via :func:`begin`, not directly."""

    def __init__(self, run_id: str, kind: str, *, dir_path: Path | None = None) -> None:
        self.run_id = run_id
        self.kind = kind  # "import" | "export"
        self._pid = os.getpid()
        self._t0 = time.monotonic()
        self._dir = dir_path if dir_path is not None else run_logs_dir()

        # Separate handles AND separate locks: a stalled write on one stream
        # must not block the other (the sampler and the worker thread are
        # different threads with different failure modes).
        self._m_lock = threading.Lock()
        self._b_lock = threading.Lock()
        self._m_fp: Any = None
        self._b_fp: Any = None
        self._m_off = False
        self._b_off = False
        self._disabled_reasons: list[str] = []

        # Hot path: two plain attribute stores, no lock (a reference assignment
        # and an int increment are atomic under the GIL). `_prog_seq` counts
        # PUBLICATIONS, which is a liveness signal that exists in every phase,
        # unlike a per-phase progress counter.
        self._prog: dict | None = None
        self._prog_seq = 0

        self._sampler: threading.Thread | None = None
        self._stop = threading.Event()
        self._ended = False
        self._child_walk_ok = True
        self._beats_written = 0

    # -- files ------------------------------------------------------------- #
    @property
    def milestone_path(self) -> Path:
        return self._dir / f"{self.run_id}.jsonl"

    @property
    def beat_path(self) -> Path:
        return self._dir / f"{self.run_id}.beat.jsonl"

    def _open(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._m_fp = open(self.milestone_path, "a", encoding="utf-8")  # noqa: SIM115
            self._b_fp = open(self.beat_path, "a", encoding="utf-8")  # noqa: SIM115
        except Exception as exc:  # noqa: BLE001 - never block the run on its own journal
            self._disable("milestones", exc)
            self._disable("beats", exc)

    def _disable(self, stream: str, exc: BaseException) -> None:
        reason = f"{stream}: {type(exc).__name__}: {exc}"
        if stream == "milestones":
            self._m_off = True
            fp, self._m_fp = self._m_fp, None
        else:
            self._b_off = True
            fp, self._b_fp = self._b_fp, None
        with suppress(Exception):
            if fp is not None:
                fp.close()
        self._disabled_reasons.append(reason)
        _LOG.warning("run journal %s disabled for run %s (%s)", stream, self.run_id, reason)

    def _write(self, rec: dict, *, beat: bool, durable: bool) -> None:
        # PID guard BEFORE the lock. A forked child inherits both, and if the
        # guard sat inside the critical section the child would block on a lock
        # whose owner does not exist in it.
        if self._pid != os.getpid():
            return
        lock = self._b_lock if beat else self._m_lock
        with lock:
            fp = self._b_fp if beat else self._m_fp
            if fp is None or (self._b_off if beat else self._m_off):
                return
            try:
                fp.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")
                fp.flush()
                if durable:
                    # fsync is asymmetric BY DESIGN: a milestone is the evidence
                    # a hard kill leaves behind, so it must be on the platter
                    # before the next line of work runs. A beat is one of
                    # thousands and the previous one is nearly as good, so it
                    # is not worth an fsync -- and several milestone sites fire
                    # while the process-wide write gate is held, where a
                    # multi-second fsync on a failing disk would be felt by
                    # every other writer. Those pass durable=False.
                    with suppress(OSError):
                        os.fsync(fp.fileno())
            except Exception as exc:  # noqa: BLE001
                self._disable("beats" if beat else "milestones", exc)

    # -- milestones -------------------------------------------------------- #
    def milestone(self, ev: str, *, durable: bool = True, **fields: Any) -> None:
        from src.safety.scrub import scrub

        rec = {"ev": ev, "t": _utc_iso(), "el_s": round(time.monotonic() - self._t0, 1)}
        rec.update(scrub(fields))
        self._write(rec, beat=False, durable=durable)

    # -- hot path ---------------------------------------------------------- #
    def progress(self, p: dict) -> None:
        """Publish the latest progress dict. Called once per merged article.

        Deliberately trivial: two stores. No lock (the sampler only ever reads
        the reference), no ``time`` call, no copy, no allocation beyond the
        reference already held by the caller.
        """
        self._prog = p
        self._prog_seq += 1

    # -- heartbeat --------------------------------------------------------- #
    def _beat(self, prev: dict) -> dict:
        t_beat0 = time.monotonic()
        unmeasured: list[str] = []
        rec: dict = {"t": _utc_iso(), "el_s": round(time.monotonic() - self._t0, 1)}

        prog = self._prog
        seq = self._prog_seq
        if isinstance(prog, dict):
            ph = prog.get("phase")
            if ph:
                rec["phase"] = ph
        rec["d_prog_seq"] = seq - int(prev.get("_seq", seq))

        src_name, done, total = _counter_of(prog)
        if src_name is None:
            # The active phase owns no counter. Say so, and say nothing about
            # whether it is moving -- there is no measurement to base that on.
            rec["counter"] = "none-in-this-phase"
        else:
            rec["counter"] = src_name
            rec["done"] = done
            if total is not None:
                rec["total"] = total
            if prev.get("_counter") == src_name and isinstance(prev.get("_done"), int):
                d_done = (done or 0) - prev["_done"]
                rec["d_done"] = d_done
                rec["moving"] = d_done > 0

        try:
            import psutil

            proc = psutil.Process()
        except Exception as exc:  # noqa: BLE001
            proc = None
            unmeasured.append(f"psutil: {type(exc).__name__}")

        if proc is not None:
            try:
                cpu = _proc_cpu_s(proc)
                rec["cpu_s"] = cpu
                if isinstance(prev.get("_cpu"), (int, float)):
                    rec["d_cpu_s"] = round(cpu - prev["_cpu"], 3)
            except Exception as exc:  # noqa: BLE001
                unmeasured.append(f"cpu_s: {type(exc).__name__}")
            try:
                rec["rss_mb"] = round(proc.memory_info().rss / (1024 * 1024), 1)
            except Exception as exc:  # noqa: BLE001
                unmeasured.append(f"rss_mb: {type(exc).__name__}")

            if self._child_walk_ok:
                try:
                    kids, kcpu, krss = _sample_children(proc)
                    rec["kids_n"] = len(kids)
                    rec["kids"] = kids
                    rec["kids_cpu_s"] = kcpu
                    # Sum of resident sets: an UPPER BOUND, since a forked
                    # worker shares most of its pages with the parent.
                    rec["kids_rss_mb_upper"] = krss
                    if isinstance(prev.get("_kcpu"), (int, float)):
                        rec["d_kids_cpu_s"] = round(kcpu - prev["_kcpu"], 3)
                except Exception as exc:  # noqa: BLE001
                    # NOT kids_n: 0 -- that reads as "no worker processes",
                    # which is the opposite of what an AccessDenied means.
                    unmeasured.append(f"kids: {type(exc).__name__}")

        try:
            import psutil as _ps

            vm = _ps.virtual_memory()
            rec["mem_avail_mb"] = round(vm.available / (1024 * 1024), 1)
            sm = _ps.swap_memory()
            rec["swap_used_mb"] = round(sm.used / (1024 * 1024), 1)
        except Exception as exc:  # noqa: BLE001
            unmeasured.append(f"memory: {type(exc).__name__}")

        try:
            from src.paths import data_dir

            st = os.statvfs(str(data_dir()))
            rec["disk_free_mb"] = round(st.f_bavail * st.f_frsize / (1024 * 1024), 1)
        except Exception as exc:  # noqa: BLE001
            unmeasured.append(f"disk_free: {type(exc).__name__}")

        try:
            rec["wal_mb"] = round(_wal_bytes() / (1024 * 1024), 1)
        except FileNotFoundError:
            pass  # no WAL right now is a real, unremarkable state
        except Exception as exc:  # noqa: BLE001
            unmeasured.append(f"wal_mb: {type(exc).__name__}")

        try:
            from src.database.writer import write_gate_stats

            g = write_gate_stats()
            rec["gate"] = {
                "held": g.get("held"),
                "waiters": g.get("waiters"),
                "max_wait_s": g.get("max_wait_s"),
            }
        except Exception as exc:  # noqa: BLE001
            unmeasured.append(f"gate: {type(exc).__name__}")

        if unmeasured:
            rec["unmeasured"] = unmeasured

        bc = (time.monotonic() - t_beat0) * 1000.0
        rec["bc_ms"] = round(bc, 1)
        if self._child_walk_ok and bc > _CHILD_WALK_BUDGET_MS:
            # Self-limiting: the beat measured itself as expensive on THIS
            # machine, so it stops doing the expensive part and says so. The
            # cost was never assumed -- bc_ms is why.
            self._child_walk_ok = False
            rec["child_walk"] = "disabled-cost"

        # Carry-forward state for the next beat's deltas (underscore keys are
        # stripped before the line is written).
        rec["_seq"] = seq
        rec["_counter"] = src_name
        rec["_done"] = done
        rec["_cpu"] = rec.get("cpu_s")
        rec["_kcpu"] = rec.get("kids_cpu_s")
        return rec

    def _sample_loop(self) -> None:
        prev: dict = {}
        while not self._stop.wait(_BEAT_INTERVAL_S):
            try:
                rec = self._beat(prev)
            except Exception:  # noqa: BLE001 - a sampler must never die on one bad beat
                _LOG.debug("run journal beat failed", exc_info=True)
                continue
            prev = rec
            self._write(
                {k: v for k, v in rec.items() if not k.startswith("_")},
                beat=True,
                durable=False,
            )
            self._beats_written += 1
            if self._beats_written % _BEAT_TRIM_EVERY == 0:
                self._trim_beats()

    def _trim_beats(self) -> None:
        if self._pid != os.getpid():
            return
        with self._b_lock:
            if self._b_off or self._b_fp is None:
                return
            try:
                lines = self.beat_path.read_text(encoding="utf-8").splitlines()
                if len(lines) <= _BEAT_CAP_LINES:
                    return
                self._b_fp.close()
                self.beat_path.write_text(
                    "\n".join(lines[-_BEAT_CAP_LINES:]) + "\n", encoding="utf-8"
                )
                self._b_fp = open(self.beat_path, "a", encoding="utf-8")  # noqa: SIM115
            except Exception:  # noqa: BLE001 - an untrimmed ring is fine; a broken run is not
                _LOG.debug("run journal beat trim failed", exc_info=True)

    # -- lifecycle --------------------------------------------------------- #
    def _start(self, header: dict) -> None:
        self._open()
        self.milestone("run_begin", **header)
        self._sampler = threading.Thread(
            target=self._sample_loop, daemon=True, name=f"runlog-{self.run_id}"
        )
        self._sampler.start()

    def end(self, outcome: str, **fields: Any) -> None:
        """Close the run. Idempotent -- a second call is a no-op, so a caller
        that ends in both a normal path and a ``finally`` cannot write two."""
        if self._ended:
            return
        self._ended = True
        self._stop.set()
        if self._sampler is not None:
            self._sampler.join(timeout=2.0)
        extra = dict(fields)
        if self._disabled_reasons:
            # A muted stream leaves the same signature as a hard kill, so the
            # run that DID finish says so explicitly rather than being
            # retroactively minted a crash by promote_incomplete_runs().
            extra["journal_truncated"] = True
            extra["journal_disabled"] = self._disabled_reasons
        # Built as a dict rather than passed as kwargs: a caller legitimately
        # reports its OWN wall_s (the export engine does), and a keyword
        # collision must not turn the closing line -- the one that makes the run
        # readable as finished -- into a TypeError.
        payload: dict[str, Any] = {
            "outcome": outcome,
            "wall_s": round(time.monotonic() - self._t0, 1),
            "beats": self._beats_written,
        }
        payload.update(extra)
        self.milestone("run_end", **payload)
        for lk, attr in ((self._m_lock, "_m_fp"), (self._b_lock, "_b_fp")):
            with lk:
                fp = getattr(self, attr)
                setattr(self, attr, None)
                with suppress(Exception):
                    if fp is not None:
                        fp.close()

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "journal": str(self.milestone_path),
            "beats": self._beats_written,
            "journal_truncated": bool(self._disabled_reasons) or None,
        }


# --------------------------------------------------------------------------- #
#  Ambient current run
#
#  One import or export runs at a time by construction (VolumeBackupManager
#  refuses a second), so an ambient handle is what lets deep call sites
#  (stream_backup's freeze window, merge_corpus's step callback) record a
#  milestone without threading a parameter through six signatures. A genuinely
#  concurrent second begin() is REFUSED AND LOGGED -- never silently dropped,
#  and never allowed to steal the slot from the run already writing.
# --------------------------------------------------------------------------- #
_CURRENT: RunLog | None = None
_CURRENT_LOCK = threading.Lock()


def active() -> RunLog | None:
    return _CURRENT


def begin(kind: str, *, label: str = "", dest: str | None = None, **header: Any) -> RunLog | None:
    """Open a run journal, or return ``None`` when journalling is off/refused.

    Each queue item gets its OWN run: eight sequential imports at ~10 h each
    under one run_id would wrap the beat ring and lose the early hours of every
    item but the last.
    """
    global _CURRENT
    if not journal_enabled():
        return None
    # Nothing below may propagate. This is the first line of a ten-hour import;
    # a journal that can refuse to let the import START is the sidecar-breaks-
    # the-operation failure mode at its worst.
    try:
        with _CURRENT_LOCK:
            cur = _CURRENT
            if cur is not None and not cur._ended:
                _LOG.warning(
                    "run journal: refusing a concurrent %s run -- %s is still open",
                    kind, cur.run_id,
                )
                return None
            rl = RunLog(_new_run_id(kind), kind)
            _CURRENT = rl
        try:
            from src.api.diagnostics import _hardware_profile

            hw: Any = _hardware_profile()
        except Exception as exc:  # noqa: BLE001 - cross-machine comparison is a bonus
            hw = f"unavailable: {type(exc).__name__}"
        rl._start({"run_id": rl.run_id, "kind": kind, "label": label, "dest": dest,
                   "pid": os.getpid(), "hardware": hw, **header})
        return rl
    except Exception:  # noqa: BLE001
        _LOG.warning("run journal could not start; continuing unjournalled", exc_info=True)
        with _CURRENT_LOCK:
            _CURRENT = None
        return None


def end(outcome: str, **fields: Any) -> dict | None:
    """End the ambient run and clear it. Returns its summary, or ``None``."""
    global _CURRENT
    with _CURRENT_LOCK:
        rl = _CURRENT
        _CURRENT = None
    if rl is None:
        return None
    try:
        rl.end(outcome, **fields)
        return rl.summary()
    except Exception:  # noqa: BLE001 - closing the journal must never fail the run
        _LOG.warning("run journal could not be closed cleanly", exc_info=True)
        return None


def milestone(ev: str, *, durable: bool = True, **fields: Any) -> None:
    """Record a milestone on the ambient run. A no-op when there is none."""
    rl = _CURRENT
    if rl is not None:
        rl.milestone(ev, durable=durable, **fields)


def progress(p: dict) -> None:
    """Publish progress to the ambient run. Hot path -- see :meth:`RunLog.progress`."""
    rl = _CURRENT
    if rl is not None:
        rl.progress(p)


@contextmanager
def run(kind: str, *, label: str = "", dest: str | None = None, **header: Any) -> Iterator[Any]:
    """Open a run for the duration of a block, closing it however the block ends.

    This is what makes coverage a PROPERTY rather than a checklist. Hand-wiring
    begin/end at every worker means every exit path -- the raise, the operator's
    cancel, the early return, the one nobody thought of -- is a separate chance
    to forget, and the paths that get forgotten are the unusual ones, which are
    precisely the ones worth having a journal for.

    A block that wants a more specific outcome than "ok" simply calls
    :func:`end` itself; the exits here are no-ops once a run has been closed, so
    an explicit outcome always wins over the generic one.
    """
    rl = begin(kind, label=label, dest=dest, **header)
    try:
        yield rl
    except BaseException as exc:
        import traceback

        milestone(
            "error",
            cls=type(exc).__name__,
            msg=str(exc)[:2000],
            traceback="".join(traceback.format_exception(exc))[-8000:],
        )
        end("error", cls=type(exc).__name__)
        raise
    else:
        end("ok")
    finally:
        # The net for a path that returned without an outcome. Names its own
        # ignorance rather than guessing success.
        end("ended-without-a-recorded-outcome")


@contextmanager
def stage(name: str, *, durable: bool = True) -> Iterator[None]:
    """``stage_begin`` / ``stage_end`` around a block, on the ambient run.

    The ``begin`` is the load-bearing half: a run killed 4,000 s into
    ``prepare_staged:validate`` leaves the begin and nothing else, which NAMES
    the stage that was running. An end-only sink would have left the journal
    exactly as coarse as it was before the stage split shipped.
    """
    t0 = time.monotonic()
    milestone("stage_begin", name=name, durable=durable)
    try:
        yield
    finally:
        milestone(
            "stage_end", name=name, seconds=round(time.monotonic() - t0, 3), durable=durable
        )


# --------------------------------------------------------------------------- #
#  Fork safety
# --------------------------------------------------------------------------- #
def _before_fork() -> None:
    rl = _CURRENT
    if rl is None:
        return
    rl._m_lock.acquire()
    rl._b_lock.acquire()


def _after_fork_parent() -> None:
    rl = _CURRENT
    if rl is None:
        return
    with suppress(RuntimeError):
        rl._b_lock.release()
    with suppress(RuntimeError):
        rl._m_lock.release()


def _after_fork_child() -> None:
    # The child must never write to the parent's journal, and the PID guard in
    # _write already refuses it. Release the inherited locks anyway so nothing
    # in the child can block on them, and drop the handles.
    rl = _CURRENT
    if rl is None:
        return
    rl._m_off = rl._b_off = True
    rl._m_fp = rl._b_fp = None
    with suppress(RuntimeError):
        rl._b_lock.release()
    with suppress(RuntimeError):
        rl._m_lock.release()


if hasattr(os, "register_at_fork"):  # pragma: no branch - POSIX only
    os.register_at_fork(
        before=_before_fork,
        after_in_parent=_after_fork_parent,
        after_in_child=_after_fork_child,
    )


# --------------------------------------------------------------------------- #
#  Reading the journals back
# --------------------------------------------------------------------------- #
def _read_jsonl(p: Path) -> list[dict]:
    out: list[dict] = []
    try:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    # A torn final line is exactly what a hard kill leaves.
                    # Skipping it is right; treating the file as corrupt is not.
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        return out
    return out


def list_runs() -> list[dict]:
    """Every journalled run, newest first, with its outcome."""
    d = run_logs_dir()
    if not d.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(d.glob("*.jsonl")):
        if p.name.endswith(".beat.jsonl"):
            continue
        recs = _read_jsonl(p)
        if not recs:
            continue
        begin_rec = next((r for r in recs if r.get("ev") == "run_begin"), {})
        end_rec = next((r for r in reversed(recs) if r.get("ev") == "run_end"), None)
        promoted = next((r for r in reversed(recs) if r.get("ev") == "promoted"), None)
        outcome = (
            (end_rec or {}).get("outcome")
            if end_rec is not None
            else (promoted or {}).get("outcome", "incomplete")
        )
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append({
            "run_id": p.stem,
            "kind": begin_rec.get("kind"),
            "label": begin_rec.get("label"),
            "started_at": begin_rec.get("t"),
            "outcome": outcome,
            "complete": end_rec is not None,
            "size_bytes": size,
        })
    out.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return out


def summarise(run_id: str) -> dict:
    """A compact answer to "what was this run doing, and was it moving?".

    Every derived figure states its denominator or is omitted. A rate over
    fewer than two samples, or over a zero-length window, is not reported as
    0.0 -- it is reported as absent, with the reason.
    """
    d = run_logs_dir()
    m = _read_jsonl(d / f"{run_id}.jsonl")
    beats = _read_jsonl(d / f"{run_id}.beat.jsonl")
    if not m and not beats:
        raise FileNotFoundError(run_id)

    begin_rec = next((r for r in m if r.get("ev") == "run_begin"), {})
    end_rec = next((r for r in reversed(m) if r.get("ev") == "run_end"), None)
    errors = [r for r in m if r.get("ev") == "error"]

    # Unmatched stage_begin == the stage that was running when the run died.
    open_stages: list[str] = []
    for r in m:
        if r.get("ev") == "stage_begin":
            open_stages.append(r.get("name", "?"))
        elif r.get("ev") == "stage_end":
            nm = r.get("name")
            if nm in open_stages:
                open_stages.remove(nm)
            # A lone stage_end is normal, not corruption: StageTimings.record()
            # is called directly by sites that measured elsewhere.

    stages = {
        r.get("name"): r.get("seconds")
        for r in m
        if r.get("ev") == "stage_end" and r.get("seconds") is not None
    }

    out: dict = {
        "run_id": run_id,
        "kind": begin_rec.get("kind"),
        "label": begin_rec.get("label"),
        "started_at": begin_rec.get("t"),
        "hardware": begin_rec.get("hardware"),
        "complete": end_rec is not None,
        "outcome": (end_rec or {}).get("outcome") or "incomplete",
        "stages": stages,
        "beats": len(beats),
        "errors": [{"t": e.get("t"), "cls": e.get("cls"), "msg": e.get("msg")} for e in errors],
    }
    if end_rec is not None:
        out["wall_s"] = end_rec.get("wall_s")
        if end_rec.get("journal_truncated"):
            out["journal_truncated"] = True
    else:
        out["died_in_stage"] = open_stages[-1] if open_stages else None
        if not open_stages:
            # It died BETWEEN stages, or in work no stage wraps. The last stage
            # that finished is still a real, measured bound on where it got to --
            # and it is the honest thing to report rather than a null and nothing.
            last_end = next(
                (r.get("name") for r in reversed(m) if r.get("ev") == "stage_end"), None
            )
            out["died_after_stage"] = last_end
        out["note"] = (
            "no run_end: this run was killed, OR its journal was disabled mid-run "
            "(e.g. the sidecar's disk filled). The two are indistinguishable from "
            "the file alone."
        )

    if beats:
        last = beats[-1]
        out["last_beat"] = last
        # ANCHOR the span on the last OBSERVED beat, never on "now" and never on
        # a promotion line written at the next boot: a 40-minute stall must not
        # read as three days because the machine was off in between.
        out["last_seen_at"] = last.get("t")
        out["last_phase"] = last.get("phase")

    window = beats[-10:]
    if len(window) >= 2:
        first, last = window[0], window[-1]
        d_wall = (last.get("el_s") or 0) - (first.get("el_s") or 0)
        if d_wall > 0:
            rate: dict = {"window_s": round(d_wall, 1), "samples": len(window)}
            if isinstance(first.get("done"), int) and isinstance(last.get("done"), int) \
                    and first.get("counter") == last.get("counter"):
                rate["counter"] = last.get("counter")
                rate["items_per_s"] = round((last["done"] - first["done"]) / d_wall, 3)
            cpu = sum(b.get("d_cpu_s", 0) or 0 for b in window[1:])
            kcpu = sum(b.get("d_kids_cpu_s", 0) or 0 for b in window[1:])
            rate["cpu_s_per_wall_s"] = round(cpu / d_wall, 3)
            rate["kids_cpu_s_per_wall_s"] = round(kcpu / d_wall, 3)
            out["recent"] = rate
        else:
            out["recent_unavailable"] = "the last samples span no wall time"
    else:
        out["recent_unavailable"] = f"only {len(beats)} beat(s): a rate needs two"
    return out


def raw_runs(*, max_runs: int = 4, max_beats: int = 4000) -> dict:
    """The newest runs' journals VERBATIM, bounded, for the diagnostics bundle.

    :func:`summarise` is the answer; this is the evidence. A stall is a shape
    across hundreds of beats -- swap climbing while CPU flatlines, the gate held
    with waiters piling up -- and no summary substitutes for reading it. Bounded
    because the bundle must stay openable: what was dropped is stated, never
    silently truncated.
    """
    out: dict = {}
    for r in list_runs()[:max_runs]:
        rid = r["run_id"]
        beats = _read_jsonl(run_logs_dir() / f"{rid}.beat.jsonl")
        entry: dict = {
            "milestones": _read_jsonl(run_logs_dir() / f"{rid}.jsonl"),
            "beats": beats[-max_beats:],
        }
        if len(beats) > max_beats:
            entry["beats_omitted"] = len(beats) - max_beats
            entry["beats_note"] = (
                f"the oldest {len(beats) - max_beats} beat(s) of this run are not "
                "included here; the full file is in data_dir()/run_logs/"
            )
        out[rid] = entry
    return out


def promote_incomplete_runs(*, max_runs: int = 50) -> list[dict]:
    """Mark every journal that never reached ``run_end``, once, at boot.

    Writes a DISTINCT ``promoted`` event -- never a synthesised ``run_end``.
    Overloading the token whose absence IS the evidence would make every
    crashed run read as finished from the first boot after the crash onward.

    Reads only files under ``data_dir()``; needs no database, so it can run
    before unlock, which is when an operator asking "what happened last night?"
    actually looks.
    """
    d = run_logs_dir()
    if not d.is_dir():
        return []
    promoted: list[dict] = []
    for p in sorted(d.glob("*.jsonl"), reverse=True)[:max_runs]:
        if p.name.endswith(".beat.jsonl"):
            continue
        recs = _read_jsonl(p)
        if not recs:
            continue
        if any(r.get("ev") in ("run_end", "promoted") for r in recs):
            continue
        run_id = p.stem
        try:
            info = summarise(run_id)
        except Exception:  # noqa: BLE001
            info = {"run_id": run_id}
        line = {
            "ev": "promoted",
            "t": _utc_iso(),
            "outcome": "incomplete",
            "died_in_stage": info.get("died_in_stage"),
            "last_seen_at": info.get("last_seen_at"),
            "reason": (
                "no run_end line: killed mid-run, or the journal was disabled "
                "(e.g. disk full). Not distinguishable from the file alone."
            ),
        }
        try:
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, separators=(",", ":")) + "\n")
                fh.flush()
                with suppress(OSError):
                    os.fsync(fh.fileno())
        except OSError:
            _LOG.debug("could not mark %s as incomplete", run_id, exc_info=True)
            continue
        _LOG.warning(
            "run %s has no run_end -- it was killed or its journal was muted "
            "(last seen %s, in stage %s)",
            run_id, info.get("last_seen_at"), info.get("died_in_stage"),
        )
        promoted.append(info)
        # The journal summary is what a killed run CAN leave. It carries no plan
        # counts, no corpus delta and no reindex rates, because those are
        # computed at the end and that end never came -- so the persisted report
        # says which stage died, not what was imported.
        with suppress(Exception):
            from src.backup.import_reports import persist_import_report

            persist_import_report(
                "incomplete", {"outcome": "incomplete", "source": "run-journal", **info},
                run_id=run_id,
            )
    return promoted
