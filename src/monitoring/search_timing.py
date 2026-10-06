"""
Per-search intra-request timing breakdown (planning §4 — search instrumentation FIRST).

§4's doctrine is *measure before you optimize*: the app already has the S2.7 per-ROUTE p95
reservoir (``latency.py``) and the slow-query EXPLAIN instrument (``slowquery.py``), but not
the intra-request breakdown that says WHERE one search spends its wall-clock — FTS ``MATCH``
ms vs content-fetch ms vs serialization ms. Which phase DOMINATES decides the §4 lever, so it
must be measured on the operator's live encrypted corpus, never guessed.

This is the pure, testable core. It mirrors three shipped foundations:
  * ``src/api/unlock.py:_forensic_timer`` — the per-phase wall-clock timer (injectable clock).
  * ``src/monitoring/latency.py:_pct`` — the reservoir percentile (replicated, 4 lines, to keep
    this module import-light — importing latency pulls in the asyncio watchdog).
  * ``src/monitoring/collect_perf.py:_append_jsonl``/``_trim_jsonl`` — the bounded JSONL log.

Honesty by construction: measurements only, no composite score; the aggregate names the
dominant phase by MEASURED p95 (a fact about where wall-clock goes, not a quality judgement);
degrades to an honest empty report before anything is recorded. The networked call (running a
real search on the live corpus) is the OPERATOR/CI seam — ``instrument_search`` is the one-line
hook a handler calls; the core proves the mechanism on an injected clock.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from src.monitoring import unlock_marker

_LOG = logging.getLogger(__name__)

SCHEMA = "oo-search-timing-1"
SELFTEST_SCHEMA = "oo-search-timing-selftest-1"

KIND_TEXT = "text"
KIND_BROWSE = "browse"

# Recent search records kept in-process for the aggregate (bounded, recent-window — the same
# discipline as latency.py's per-route reservoir; a leak here must never grow unbounded). ONE
# window per kind: browses are far more frequent than searches, and in a shared window 512 of them
# push every text search out, so ``searches`` would read 0 on an instance that had searched.
_RES_CAP = 512
_CAP_LINES = 5000
_LOCK = threading.Lock()
# An append, a cut and a read of ONE log never overlap: a line appended between the cut's read and its
# write would be lost; an append that had opened the file just before the cut replaced it would write
# into the old file; and a read that has the file open while a cut swaps it makes the swap fail on
# Windows, where a file that is open cannot be replaced. Held only around the write itself, around a
# cut (a few milliseconds, tens while a log still holds lines written whole; every 250th append: see
# ``_trim_if_due``) and around the read of a log's bytes, never while taking ``_LOCK``. ONE lock per log:
# one log's cut never holds up the other kind's append.
_FILE_LOCKS = {KIND_TEXT: threading.Lock(), KIND_BROWSE: threading.Lock()}
_recent: dict[str, list[dict]] = {KIND_TEXT: [], KIND_BROWSE: []}

# ...and ONE durable log per kind, for the same reason. The text log keeps the name it always had.
_LOG_FILES = {KIND_TEXT: "search_timing.jsonl", KIND_BROWSE: "search_timing_browse.jsonl"}
# A log is cut back to ``_CAP_LINES`` once this many appends have passed since it last was (and on
# a process's first append), not on every one: cutting rewrites the whole file, and a browse can
# arrive many times a minute. The file may therefore hold up to this many lines beyond the cap, and
# this many more for each cut that failed (a full disk; on Windows a file another program holds open).
_TRIM_EVERY = 250
_appends_since_trim: dict[str, int] = {KIND_TEXT: _TRIM_EVERY, KIND_BROWSE: _TRIM_EVERY}
# The two texts every finished record carries (``SearchPhaseTimer.finish``). Both are in every report (the
# aggregate's own, and the durable summary's), so a log line repeating them said the same words on each of
# its 5,000 lines: 1,741 of a browse line's 1,937 bytes, 850 of a text line's 1,043. Nothing reads them
# back (``_read_log`` counts lines and reads ``at``; the aggregate reads ``phases``, ``total_ms`` and
# ``limit``), so a DURABLE line is the measurement only. The in-process window keeps the record whole.
_STATIC_TEXT_KEYS = ("method", "caveat")


class SearchPhaseTimer:
    """Times the phases of ONE search request. Mirrors unlock._forensic_timer: ``phase(name)``
    records the wall-clock since the previous mark; ``finish()`` returns the record + the total.

    ``kind`` says what was timed: a TEXT search, or a BROWSE of the article list (no text query;
    2026-10-01, diagnostics rank 9 -- the browse is the call a person waits on and was the one
    thing never timed). ``meta`` is a handful of small scalars (the page size and offset of a
    browse) copied into the record; never a query, never any article content.

    The clocks are injected (default ``time.monotonic`` and ``time.time``) so the timer is fully
    deterministic in tests — no real waiting. Every method is cheap and best-effort; a timing
    failure must never change what a search returns."""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] | None = None,
        kind: str = KIND_TEXT,
        meta: dict[str, Any] | None = None,
        wall: Callable[[], float] | None = None,
    ) -> None:
        self._mono = monotonic or time.monotonic
        self._wall = wall or time.time
        self._t0 = self._mono()
        self._last = self._t0
        self._phases: list[dict] = []
        self._kind = kind
        self._meta = dict(meta or {})

    def phase(self, name: str) -> dict:
        """Mark the end of a phase; return its ``{phase, ms}`` record."""
        now = self._mono()
        rec = {"phase": str(name), "ms": round((now - self._last) * 1000, 3)}
        self._phases.append(rec)
        self._last = now
        return rec

    def finish(self) -> dict:
        """Return ``{kind, phases, total_ms, at, started_after_unlock_s, method, caveat}`` — total
        is the FULL wall from start to finish (so unmarked time between phases is visible as
        total minus the phase sum).

        ``at`` is when it finished (UTC), and ``started_after_unlock_s`` how far from the latest
        unlock to have finished by then it BEGAN: signed, and ``None`` -- never 0 -- when this
        process had finished no unlock (see ``unlock_marker``). Neither existed before 2026-10-01,
        so no older record can be placed in time.

        ``method`` and ``caveat`` are the same words on every record: the in-process window keeps
        them, and the durable log does not write them (``append_search_timing``)."""
        total = round((self._mono() - self._t0) * 1000, 3)
        ended = self._wall()
        if self._kind == KIND_BROWSE:
            method = (
                "Wall-clock over one browse of the article list (no text query), split by "
                "phase: the count of the matching set (count_cached when the corpus-wide "
                "total was served from the data-version cache, count_recomputed when it was "
                "counted now because nothing was cached for this data version -- the first "
                "browse since the app started or unlocked, an entry that had expired or been "
                "evicted, a write by any connection since the last count, the cache off, or no "
                "data-version probe -- count_live when a filter or the quarantine view made it "
                "a live COUNT) and the page of "
                "rows; total is the wall from the start of the query to the page in hand, so "
                "unmarked time is total minus the phase sum. It begins after the request has "
                "waited for a worker, and ends before the response is built (building it is "
                "not in it). A database connection is taken by the first statement. A browse "
                "that looks nothing up first (a language, a date range and the advanced "
                "search's source ids are plain conditions) runs that statement inside the "
                "timed span, so any wait for a connection, and the cost of opening it, are "
                "INSIDE the first phase that runs a statement: the count phase, or the rows "
                "phase when the count was served from the cache (the data-version probe has "
                "a connection of its own). A browse that has a source, a source type, tags, a "
                "provenance, the advanced search's countries or regions, or a query of field "
                "filters only (source:x) looks something up first, BEFORE the clock starts, "
                "and on such a browse the wait for a connection and the lookup itself are in "
                "no phase and not in the total either."
            )
        else:
            method = (
                "Wall-clock over one text search, split by phase (fts: the FTS MATCH and its "
                "candidate ids · resolve: the candidates that survive the filters · load: their "
                "order and the page of rows); total is the wall from the start of the query to "
                "the page in hand, so unmarked time is total minus the phase sum. It begins after "
                "the request has waited for a worker, after the keyword the handler looks up for "
                "the per-article counts, and after the lookups a source, a source type, tags, a "
                "provenance, or the advanced search's countries or regions make; it ends before "
                "the response is built (the per-article counts, the translated titles, the "
                "did-you-mean and the JSON are not in it)."
            )
        return {
            # The caller's scalars go FIRST, so a key of the same name as one below can never
            # override what the timer itself says.
            **self._meta,
            "kind": self._kind,
            "phases": list(self._phases),
            "total_ms": total,
            "at": datetime.fromtimestamp(ended, tz=UTC).isoformat(timespec="seconds"),
            "started_after_unlock_s": unlock_marker.started_after_unlock_s(ended - total / 1000.0),
            "method": method,
            "caveat": (
                "One request — a single sample, not a distribution; feed many into the "
                "aggregate for percentiles. Deduced from wall-clock, never a quality score."
            ),
        }


def _pct(sorted_vals: list[float], p: float) -> float:
    """Replicates latency._pct — nearest-rank percentile over a pre-sorted list."""
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return round(sorted_vals[k], 3)


def aggregate_phases(records: list[dict]) -> dict:
    """PURE aggregate over a list of finished search records — per-phase percentiles + the
    MEASURED dominant phase (by p95 ms — where wall-clock actually goes, the §4 lever). Never
    touches module state, so the self-test and the live report share one implementation.

    Honest on an empty list: ``phases={}``, ``dominant_phase=None`` — no fabricated numbers."""
    per: dict[str, list[float]] = {}
    totals: list[float] = []
    for r in records:
        for p in r.get("phases", []) or []:
            try:
                ms = float(p.get("ms", 0.0))
            except (TypeError, ValueError):
                continue  # a malformed ms must not create an empty-list phase (max([]) → 500).
            per.setdefault(str(p.get("phase")), []).append(ms)
        t = r.get("total_ms")
        if t is not None:
            with contextlib.suppress(TypeError, ValueError):
                totals.append(float(t))

    phases: dict[str, dict] = {}
    for name, vals in per.items():
        s = sorted(vals)
        phases[name] = {
            "n": len(vals),
            "p50_ms": _pct(s, 50),
            "p95_ms": _pct(s, 95),
            "p99_ms": _pct(s, 99),
            "max_ms": round(max(vals), 3),
            "mean_ms": round(sum(vals) / len(vals), 3),
        }
    # The dominant phase is the one with the highest p95 wall-clock — a measurement, not a
    # ranking of quality. Ties resolve deterministically by phase name so the answer is stable.
    dominant = (
        max(phases, key=lambda k: (phases[k]["p95_ms"], k)) if phases else None
    )
    ts = sorted(totals)
    return {
        "schema": SCHEMA,
        "searches": len(records),
        "phases": phases,
        "total": {
            "n": len(totals),
            "p50_ms": _pct(ts, 50),
            "p95_ms": _pct(ts, 95),
            "p99_ms": _pct(ts, 99),
            "max_ms": round(max(totals), 3) if totals else 0.0,
        },
        "dominant_phase": dominant,
        "method": (
            "Per-phase percentiles over a bounded recent-window of in-process search records; "
            "the dominant phase is the highest measured p95 wall-clock — the §4 target chosen "
            "by evidence, not theory."
        ),
        "caveat": (
            f"In-process + recent-window only (last {_RES_CAP} searches); a cold cache or the "
            "live encrypted corpus at scale can shift the split, so the deciding run is the "
            "operator's. Measurements only — no composite score."
        ),
    }


def _kind_of(record: dict) -> str:
    """A record without a ``kind`` -- every one written before 2026-10-01 -- is a text search."""
    return KIND_BROWSE if record.get("kind") == KIND_BROWSE else KIND_TEXT


def _append_bounded(window: list[dict], record: dict) -> None:
    """The one place the window's bound is enforced. The live window and the self-test's check of
    the bound both go through it, so the check proves the real code and never touches live state."""
    window.append(record)
    if len(window) > _RES_CAP:
        del window[0 : len(window) - _RES_CAP]


def record_search_phases(record: dict) -> None:
    """Feed one finished record into the in-process aggregate (bounded per kind, thread-safe)."""
    with _LOCK:
        _append_bounded(_recent[_kind_of(record)], record)


def _snapshot() -> list[dict]:
    with _LOCK:
        return [*_recent[KIND_TEXT], *_recent[KIND_BROWSE]]


# Page sizes listed one by one in a report's ``page_sizes``; the rest are summed under ``other``.
# What this protects is the size of that map in the export: its keys are the ``limit`` a CLIENT chose,
# so without a bound a caller trying many different limits would make the map as long as the number
# it tried. Ten is far more than the handful of page sizes the app itself asks for.
_PAGE_SIZES_MAX = 10


def _page_sizes(browse: list[dict]) -> dict[str, int]:
    """How many of these browses asked for each page size (``limit``): the most frequent first,
    the rest summed under ``other``. Counts only -- the p95 beside it mixes them."""
    counts: dict[str, int] = {}
    for r in browse:
        lim = r.get("limit")
        key = "no limit" if lim is None else str(lim)
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    out = dict(ordered[:_PAGE_SIZES_MAX])
    rest = sum(n for _, n in ordered[_PAGE_SIZES_MAX:])
    if rest:
        out["other"] = rest
    return out


def build_report(records: list[dict], durable: dict | None = None) -> dict:
    """The published report, from a list of finished records. PURE (never touches module state), so
    the self-test and the live report share one implementation.

    The TOP LEVEL is the text-search aggregate, exactly the shape it always had, and
    ``searches`` counts text searches only: a browse is not a search, and counting it there would
    turn "nobody searched" into "somebody did". The browses are a sibling aggregate under
    ``browse`` (same shape, ``pages`` in place of ``searches``). A record written before
    2026-10-01 has no ``kind`` and is a text search, which is what every one of them was."""
    text = [r for r in records if _kind_of(r) == KIND_TEXT]
    browse = [r for r in records if _kind_of(r) == KIND_BROWSE]
    out = aggregate_phases(text)
    out["scope"] = (
        "text searches recorded by THIS process since it started (a bounded recent window); "
        "browses of the article list are under `browse`, and what the durable logs hold across "
        "restarts is under `durable_log`"
    )
    pages = aggregate_phases(browse)
    pages["pages"] = pages.pop("searches")
    pages["kind"] = KIND_BROWSE
    pages["page_sizes"] = _page_sizes(browse)
    pages["method"] = (
        "Per-phase percentiles over a bounded recent window of in-process article-list browses "
        "(no text query), counted from when the query starts to when the page is in hand; the "
        "dominant phase is the highest measured p95. It holds every call to GET /api/articles "
        "that has no text query and no explicit `ids` set, whoever makes it (the Search tab, "
        "the Home cards, a channel's list, the analysis), once it has returned a page: a call "
        "that failed is not in it (the route latency log counts those); a call for a fixed set "
        "of ids is not timed. So one p95 spans page sizes from a handful of rows to a thousand: "
        "`page_sizes` counts the browses by the page size they asked for. A browse that "
        "has a source, a source type, tags, a provenance, the advanced search's countries "
        "or regions, or a query of field filters only looks that up BEFORE its clock starts, "
        "so the wait for a database connection and the lookup itself are in no phase and not "
        "in the total; this report does not mark which of its browses did."
    )
    pages["caveat"] = (
        f"In-process + recent-window only (last {_RES_CAP} browses, kept apart from the "
        "searches); the figure is the wall of the query, not of the request: waiting for a "
        "worker before it, and building the response after it, are NOT in it, and the wait for "
        "a database connection is inside whichever phase first runs a statement, except on a "
        "browse that looks a filter up before the clock starts: there the wait and the lookup "
        "are in no phase (named in `method`; the report does not mark which browses did). "
        "Measurements only — no composite score."
    )
    out["browse"] = pages
    if durable is not None:
        out["durable_log"] = durable
    return out


def search_timing_report() -> dict:
    """The live aggregate over what this process has recorded so far, plus what the durable logs
    hold across restarts — read-only, degrades to an honest empty report before any search is
    instrumented."""
    return build_report(_snapshot(), durable_log_summary())


def _log_path(kind: str = KIND_TEXT):
    from src.paths import data_dir

    return data_dir() / _LOG_FILES[kind]


def _trim_jsonl(kind: str = KIND_TEXT) -> None:
    """Cut a log back to its newest ``_CAP_LINES`` lines. The cut is written beside the log and
    swapped in whole, under the lock the appends take, so a full disk, an error or a killed process
    mid-cut leaves the old log intact (never a truncated one) and no line appended meanwhile is lost.
    Nothing is synced to disk: a power loss is not covered by that. The swap itself can be refused (on
    Windows a file another program holds open cannot be replaced): that is logged at debug level and the
    cut is tried again ``_TRIM_EVERY`` appends later, the log growing by those appends meanwhile. A
    half-made copy is removed under the same lock, so it can never take out another cut's copy."""
    try:
        path = _log_path(kind)
        with _FILE_LOCKS[kind]:
            if not path.exists():
                return
            part = None
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                if len(lines) > _CAP_LINES:
                    part = path.with_name(path.name + ".part")
                    part.write_text("\n".join(lines[-_CAP_LINES:]) + "\n", encoding="utf-8")
                    os.replace(part, path)
                    part = None
            finally:
                if part is not None:
                    with contextlib.suppress(OSError):
                        part.unlink()
    except Exception:  # noqa: BLE001 - logging must never break a search
        _LOG.debug("search_timing trim failed", exc_info=True)


def _trim_if_due(kind: str) -> None:
    """Cut a log back to the cap once every ``_TRIM_EVERY`` appends, and on a process's first one.

    Cutting reads and rewrites the whole file. Measured on the development container, warm page
    cache, over seven cuts of a log holding 5,250 records of one kind. A line is the measurement
    only (``_STATIC_TEXT_KEYS`` are not written): a browse line is 196 bytes (the log 0.98 MB at the
    cap) and a cut took 2.4-2.6 ms, 1.0-1.1 ms of it the read; a text line is 193 bytes (0.97 MB),
    2.3-2.8 ms, 0.9-1.1 ms of it the read. The same records written whole, as every line was until
    2026-10-06 (the sizes moved with that wording, and did when the browse and the unlock distance
    joined it), were 1,937 and 1,043 bytes (9.7 and 5.2 MB at the cap), and a cut took 38-94 ms (22-31 ms
    of it the read) and 22-51 ms (12-18 ms): a log still holds lines of that shape until the cuts drop
    them. A cold read costs more. Cutting after EVERY append would still put a rewrite of the whole file
    on each article-list call the moment a log reached its cap, so it is done once every
    ``_TRIM_EVERY`` (the number protects the rewrite, not the log's size, so the smaller line does not
    move it). The first append of a process cuts too, so a log never carries the growth of the process
    before it."""
    with _LOCK:
        _appends_since_trim[kind] += 1
        due = _appends_since_trim[kind] >= _TRIM_EVERY
        if due:
            _appends_since_trim[kind] = 0
    if due:
        _trim_jsonl(kind)


def _read_log(kind: str) -> dict:
    """Counts and dates for ONE durable log -- never the records themselves.

    A line with no ``at`` (written before 2026-10-01), or an ``at`` with no time zone, cannot be
    placed in time: it is COUNTED as undated, never dropped and never given a zone. ``records`` is
    ``None`` (with the reason) when the file cannot be read: an unreadable log is not an empty one."""
    name = _LOG_FILES[kind]
    try:
        path = _log_path(kind)
        # The bytes are read under the lock a cut and an append take; they are parsed after it.
        with _FILE_LOCKS[kind]:
            if not path.exists():
                return {
                    "file": name, "records": 0, "undated": 0, "malformed": 0,
                    "dated_from": None, "dated_to": None,
                    "reason": f"no {name} in this data folder: nothing of this kind has been logged here",
                }
            text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
    except Exception as exc:  # noqa: BLE001 - a report must never fail for want of its side log
        return {
            "file": name, "records": None, "undated": None, "malformed": None,
            "dated_from": None, "dated_to": None,
            "reason": f"the log could not be read ({type(exc).__name__}); unmeasured, not empty",
        }
    n = n_undated = n_bad = 0
    dated: list[datetime] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            n_bad += 1  # a line cut short by the very death being explained
            continue
        if not isinstance(rec, dict):
            n_bad += 1
            continue
        n += 1
        try:
            at = datetime.fromisoformat(str(rec["at"]))
        except (KeyError, ValueError):
            n_undated += 1
            continue
        if at.tzinfo is None:
            n_undated += 1
            continue
        dated.append(at)
    return {
        "file": name,
        "records": n,
        "undated": n_undated,
        "malformed": n_bad,
        "dated_from": min(dated).isoformat(timespec="seconds") if dated else None,
        "dated_to": max(dated).isoformat(timespec="seconds") if dated else None,
        "reason": None,
    }


def durable_log_summary() -> dict:
    """What the two durable logs hold: counts and dates, never the records themselves.

    The in-process aggregate restarts at zero with every process, so ``searches: 0`` means "none
    recorded since this process started", which the figure alone cannot tell from "never". (The
    sixteen zeros of the 2026-09-30 round were not that: each export's own self-test emptied the
    window before the report read it, and the self-test no longer does -- see LESSONS.md.) The
    logs are durable, so they are the only place a restart does not erase.
    Text searches and browses have a log each: browses are far more frequent, and in one shared log
    they would push every text search out of its cap."""
    return {
        "cap_lines": _CAP_LINES,
        "method": (
            "Counted from the two durable logs, which survive a restart: search_timing.jsonl for "
            "text searches and search_timing_browse.jsonl for browses of the article list. Each is "
            f"cut back to its newest {_CAP_LINES} lines once every {_TRIM_EVERY} appends, so it can "
            f"hold up to {_TRIM_EVERY} more than that, and {_TRIM_EVERY} more for each cut that "
            "failed (a full disk; on Windows a file another program holds open), which is tried "
            "again at the next one. A line is the measurement only (kind, phases, total_ms, at, "
            "started_after_unlock_s and, for a browse, its page size and offset): the `method` and "
            "`caveat` that describe a measurement are the ones in this report, and a line written "
            "before 2026-10-06 still carries them, so both shapes can share a file until the cuts "
            "drop the older one. `undated` lines carry no usable `at` (none, "
            "or one with no time zone) and cannot be placed in time; dated_from and dated_to bound "
            "the dated ones."
        ),
        "caveat": (
            "The in-process figures above restart at zero with every process; these do not, so "
            "`searches` there can read 0 on an instance that has logged thousands. The cap means "
            "the oldest records are gone, not that there were none."
        ),
        "text": _read_log(KIND_TEXT),
        "browse": _read_log(KIND_BROWSE),
    }


# A block inside which finished records are NOT kept: the benchmark runs the very queries it
# measures, and those runs must not turn up in the field record as searches nobody made (that
# would make `searches: 0` read 3 on an instance where no one ever typed a query).
_SUPPRESSED: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "oo_search_timing_suppressed", default=False
)


@contextlib.contextmanager
def suppressed() -> Iterator[None]:
    """Keep every record finished INSIDE the block out of the logs and the aggregate."""
    token = _SUPPRESSED.set(True)
    try:
        yield
    finally:
        _SUPPRESSED.reset(token)


def append_search_timing(record: dict) -> None:
    """Durably append one record to the bounded JSONL log of its kind AND feed the in-process
    aggregate. Best-effort — a logging failure never touches the search that produced it.

    The line is the measurement only: the record without ``_STATIC_TEXT_KEYS``. The in-process window
    gets the record whole and the caller's own dict is never changed. A log written before 2026-10-06
    has lines that still carry the two texts; every reader counts a line by its ``at`` whatever else it
    holds, and the cuts drop the older shape as they drop any old line, so the two can share a file."""
    if _SUPPRESSED.get():
        return
    record_search_phases(record)
    kind = _kind_of(record)
    try:
        line = {k: v for k, v in record.items() if k not in _STATIC_TEXT_KEYS}
        path = _log_path(kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _FILE_LOCKS[kind], open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, separators=(",", ":")) + "\n")
        _trim_if_due(kind)
    except Exception:  # noqa: BLE001
        _LOG.debug("search_timing append failed", exc_info=True)


def instrument_search(fn: Callable[[SearchPhaseTimer], Any]) -> Any:
    """The OPERATOR/CI seam. A handler runs its search inside ``fn`` (calling ``timer.phase(...)``
    at each stage); this records the finished breakdown and returns the search result unchanged.

    Wiring this into the real (async) search endpoint is the CI/operator step (§4's live per-phase
    ms on the 100-130 GB encrypted corpus decides the lever); the core here is fully proven on an
    injected clock without a browser, Ollama, network, or the live corpus."""
    timer = SearchPhaseTimer()
    try:
        result = fn(timer)
    finally:
        try:
            append_search_timing(timer.finish())
        except Exception:  # noqa: BLE001
            _LOG.debug("instrument_search record failed", exc_info=True)
    return result


def _reset_for_tests() -> None:
    """Drop the in-process record windows and the trim counters (test hook)."""
    with _LOCK:
        for window in _recent.values():
            window.clear()
        for kind in _appends_since_trim:
            _appends_since_trim[kind] = _TRIM_EVERY


def _walk_no_score(obj: Any) -> None:
    """Raises explicitly (never a bare ``assert``, which ``python -O``/
    ``PYTHONOPTIMIZE`` strips silently and would let this self-test's own
    no-fabricated-score check false-pass under that flag — transversal
    audit 09, 2026-07-25, §10.4)."""
    banned = ("score", "ranking", "rating", "grade")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(b in str(k).lower() for b in banned):
                raise AssertionError(f"score-like key: {k}")
            _walk_no_score(v)
    elif isinstance(obj, list):
        for v in obj:
            _walk_no_score(v)


class _FakeClock:
    """Deterministic monotonic clock: returns each tick in order, holds the last forever."""

    def __init__(self, ticks: list[float]) -> None:
        self._ticks = list(ticks)
        self._i = 0

    def __call__(self) -> float:
        v = self._ticks[min(self._i, len(self._ticks) - 1)]
        self._i += 1
        return v


def run_search_timing_selftest() -> dict:
    """Prove the §4 mechanism on a deterministic injected clock — no browser, no network, no DB,
    no live corpus. Hand-computed asserts pin the per-phase ms, the total wall, and — the point
    of the instrument — that the DOMINANT phase is chosen by MEASURED p95, not by insertion order.

    Mirrors run_perception_eval_selftest / run_triage_selftest so a regression reddens both the
    in-app diagnostics endpoint AND CI. Returns a log with a top-level ``passed`` bool."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    # Ticks in SECONDS: init, phase1, phase2, phase3, finish. Chosen so the middle phase
    # (content_fetch) dominates — proving "dominant" is not just the first-recorded phase.
    ticks_a = [0.0, 0.010, 0.055, 0.058, 0.060]
    timer_a = SearchPhaseTimer(monotonic=_FakeClock(ticks_a))
    timer_a.phase("fts_match")
    timer_a.phase("content_fetch")
    timer_a.phase("serialize")
    rec_a = timer_a.finish()

    ms_by_phase = {p["phase"]: p["ms"] for p in rec_a["phases"]}
    check(
        "phase_ms_exact",
        ms_by_phase == {"fts_match": 10.0, "content_fetch": 45.0, "serialize": 3.0},
        str(ms_by_phase),
    )
    check("total_ms_exact", rec_a["total_ms"] == 60.0, str(rec_a["total_ms"]))
    # Unmarked time is visible: total (60) > phase sum (58).
    check(
        "unmarked_time_visible",
        rec_a["total_ms"] > sum(p["ms"] for p in rec_a["phases"]),
        f"total={rec_a['total_ms']} sum={sum(p['ms'] for p in rec_a['phases'])}",
    )

    # A second search where content_fetch stays the wall-clock hog.
    ticks_b = [0.0, 0.012, 0.052, 0.056, 0.058]
    timer_b = SearchPhaseTimer(monotonic=_FakeClock(ticks_b))
    timer_b.phase("fts_match")
    timer_b.phase("content_fetch")
    timer_b.phase("serialize")
    rec_b = timer_b.finish()

    agg = aggregate_phases([rec_a, rec_b])
    check(
        "dominant_is_measured_not_first",
        agg["dominant_phase"] == "content_fetch",
        f"dominant={agg['dominant_phase']} (fts_match was recorded first)",
    )
    check(
        "percentiles_and_n_present",
        agg["phases"]["content_fetch"]["n"] == 2
        and set(agg["phases"]["content_fetch"]) >= {"p50_ms", "p95_ms", "p99_ms", "max_ms"},
        str(agg["phases"].get("content_fetch")),
    )
    # Non-vacuous: a DIFFERENT input shifts the dominant phase — the answer tracks the data.
    ticks_c = [0.0, 0.002, 0.006, 0.106, 0.107]  # serialize is now the hog
    timer_c = SearchPhaseTimer(monotonic=_FakeClock(ticks_c))
    timer_c.phase("fts_match")
    timer_c.phase("content_fetch")
    timer_c.phase("serialize")
    agg_c = aggregate_phases([timer_c.finish()])
    check(
        "dominant_tracks_the_data",
        agg_c["dominant_phase"] == "serialize",
        f"dominant={agg_c['dominant_phase']}",
    )

    # Honest empty aggregate.
    empty = aggregate_phases([])
    check(
        "empty_is_honest",
        empty["phases"] == {} and empty["dominant_phase"] is None and empty["searches"] == 0,
        str(empty["dominant_phase"]),
    )

    # The kind split (2026-10-01): a browse never enters the text aggregate, and a record with no
    # kind -- every record written before then -- is a text search.
    old_style = {"phases": [{"phase": "x", "ms": 1.0}], "total_ms": 1.0}
    browse_rec = {
        "kind": KIND_BROWSE,
        "phases": [{"phase": "count_cached", "ms": 2.0}, {"phase": "rows", "ms": 90.0}],
        "total_ms": 92.0,
    }
    rep = build_report([rec_a, old_style, browse_rec])
    check(
        "browse_never_enters_the_text_aggregate",
        rep["searches"] == 2 and rep["browse"]["pages"] == 1 and "searches" not in rep["browse"],
        f"searches={rep['searches']} pages={rep['browse']['pages']}",
    )
    check(
        "browse_dominant_phase_is_measured",
        rep["browse"]["dominant_phase"] == "rows",
        f"dominant={rep['browse']['dominant_phase']}",
    )
    check(
        "records_are_kinded_and_dated",
        rec_a["kind"] == KIND_TEXT
        and isinstance(rec_a["at"], str)
        and "started_after_unlock_s" in rec_a,
        str({k: rec_a.get(k) for k in ("kind", "at", "started_after_unlock_s")}),
    )

    # The bounded record window never grows past the cap. Run on a LOCAL list through the helper the
    # live windows use, so it proves the real bound without touching what this process has recorded:
    # this self-test runs inside every diagnostics export, BEFORE the export reads the live windows,
    # and clearing them here made `searches` read 0 on all sixteen instances of the 2026-09-30 round.
    window: list[dict] = []
    for i in range(_RES_CAP + 50):
        _append_bounded(window, {"i": i, "phases": [{"phase": "x", "ms": 1.0}], "total_ms": 1.0})
    # Exactly the cap, the OLDEST fifty gone and the newest kept: a window that dropped everything
    # would also be "at most the cap".
    check(
        "record_window_bounded",
        len(window) == _RES_CAP and window[0]["i"] == 50 and window[-1]["i"] == _RES_CAP + 49,
        f"cap={_RES_CAP} len={len(window)} first={window[0]['i'] if window else None}",
    )

    # No composite score anywhere in the surfaced structures.
    no_score = True
    try:
        _walk_no_score(rec_a)
        _walk_no_score(agg)
        _walk_no_score(rep)
    except AssertionError as exc:
        no_score = False
        check("no_score_field", False, str(exc))
    if no_score:
        check("no_score_field", True)

    passed = all(c["passed"] for c in checks)
    return {
        "schema": SELFTEST_SCHEMA,
        "passed": passed,
        "checks": checks,
        "total": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "failed_count": sum(1 for c in checks if not c["passed"]),
        "method": (
            "Runs the SearchPhaseTimer + aggregate on a deterministic injected clock with "
            "hand-computed expected ms; proves the dominant phase is chosen by measured p95, "
            "not insertion order, and that the aggregate is honest on empty input."
        ),
        "caveat": (
            "Verifies the MECHANISM, not the live corpus. Real per-phase ms come from wiring "
            "instrument_search into the search endpoint on the operator's rig (§4 CI/operator "
            "seam). No score."
        ),
    }
