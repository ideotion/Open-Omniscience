"""Bounded-memory reading for the keyword diagnostics log and its bundle digest member.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (keyword export crash, 2026-09-30). ``GET /api/diagnostics/keywords`` (and
the ``keyword-log-digest.json`` member of the all-diagnostics bundle, which is the same
function) kept one Python dict entry for EVERY keyword and EVERY article, then -- for the
"All keywords (.zip)" button, ``per_lang=1000000`` -- one entry dict per keyword of the
whole corpus, before it compressed the lot into a ``BytesIO`` (up to nine times) and threw
99 % of it away to meet a 9 MB attachment cap. Measured on a synthetic corpus of 2 M keywords
(83 % of them orphans, as in the field), 250 k articles and 5 M mentions: digest 776 MB,
default zip 776 MB, "All keywords" zip 4.4 GB and 162 s. The field corpora are 5-7x larger in
keywords, so the digest alone reaches 3-5 GB (the instance killed at 5,334 MB RSS) and the
"All keywords" zip 25-35 GB, which kills every 6-8 GB machine.

WHAT THIS MODULE DOES INSTEAD. Nothing here is proportional to the number of keywords:

* :class:`ArticleMaps` holds article -> language and article -> source in flat arrays
  (4 + 8 bytes per article id, where two dicts cost ~130) and falls back to dicts when the
  ids are too sparse for an array to be honest about its size.
* :func:`scan_keywords` makes the ONE ordered pass over the mention rows the export always
  made, reduces each keyword as the scan passes it, and hands the result to a
  :class:`Ranker`. "Has mentions" is one byte per keyword id, not a set.
* :class:`Ranker` answers the per-language quota ("rank r of language L") with a bounded heap
  per language, and when the window is larger than the machine can hold it SPILLS to an
  SQLite file next to the data (or in the OS temp folder when there is no data folder; after
  a free-space check) and reads each language back in
  rank order. A spill loses nothing the window could use: a row that a full heap discards is
  ranked beyond the window for good, because rank only ever worsens as rows arrive.
* :class:`StopwordAcc`, :class:`RingAcc` and :class:`SuspectBoard` are the streaming forms
  of the three digests the export computes over its survivors. They keep a bounded top list
  and exact counters, and they reproduce the ordering of the one-shot functions they
  replaced, tie-break included (``tests/test_keyword_export_bounded.py`` pins the ranking and the
  scan against a plain reference written from the documented rules, in both ranker modes).

WHAT IT DOES NOT DO. It does not change what is counted or how it is ranked: the same
mention rows (``MENTIONS_TABLE`` is the one place that names the table, so the keyword
thread's move of readers onto ``KeywordMentionRead`` (D22) is a one-line change), the
same per-article language (``articles.language``, not the per-mention column), the same
order: mention-bearing keywords by mentions descending then id ascending, then the orphans by
id ascending, within each language.
"""

from __future__ import annotations

import contextlib
import errno
import heapq
import logging
import os
import sqlite3
import sys
import tempfile
from array import array
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import text

_LOG = logging.getLogger(__name__)

#: The ONE place the scan names its mention table. D22 (quarantined articles leave the
#: counts) moves readers to the ``KeywordMentionRead`` view; this export is the keyword
#: thread's call to move, and it is a one-line change here when they do.
MENTIONS_TABLE = "keyword_mentions"

UNKNOWN = "?"

#: How often the scan loops look at the machine's memory, in rows. The reading itself is
#: cached for a quarter second (``maintenance._available_mb``), so this costs nothing; the
#: number only has to be small enough that the loop cannot outrun a 64 MB/s growth between
#: two looks (65,536 rows is a few tens of milliseconds).
_CHECK_EVERY = 1 << 16

#: A heap row is a 7-tuple plus three int objects. MEASURED, not estimated: see
#: ``test_row_budget_constant_matches_the_measured_row_size`` (it fails if this drifts by
#: more than 25 %). It is what turns "a share of available memory" into a row count.
ROW_BYTES = 200

#: The share of AVAILABLE memory (read when the export starts) the ranker's heaps may use
#: before they spill to disk. A tenth: the export also holds the article arrays, the
#: per-batch entries and the zip buffers, and the rest of the machine is the operator's.
HEAP_SHARE = 0.10

#: Bytes one keyword costs while the families are grouped over it: the entry's `fam` item, the
#: grouping's own record for it, and the family it lands in. MEASURED 2026-10-06 as the grouping's
#: peak resident rise per keyword, in its own process, over terms shaped like the field's: 2,069 /
#: 2,134 / 2,228 bytes at 200,000 / 100,000 / 50,000 keywords of Cyrillic phrases (three in five of
#: them two to four tokens), against 2,027 for Latin phrases of the same shape and 1,483 for short
#: single-token terms. The constant is the worst of those plus twelve per cent. The margin sits on
#: THIS constant because it is the one that scales with the length of a term (the entry constant,
#: ``EXPORT_ENTRY_BYTES``, holds ids, counts and dates, not a term), and a field corpus holds longer
#: terms than any synthetic one. Two tests hold it: one fails when it stops covering the Python
#: allocation of the grouping on both shapes (tracemalloc, a LOWER bound on what the process
#: takes), and one pins the value against the resident measurement above, so changing it means
#: measuring again, not editing a number.
FAMILY_ROW_BYTES = 2500

#: The share of AVAILABLE memory the family grouping may use, on top of the ranker's own tenth.
#: What it protects: the grouping runs after the scan, while the process still holds its own
#: baseline, the article arrays, the ranker's heaps (``HEAP_SHARE``) and the archive's buffers, and
#: the rest of the machine is the operator's other programs. A tenth, like ``HEAP_SHARE``, is a
#: DEFAULT chosen for that margin, not a measurement: the memory stop, not this number, is what
#: ends a run that still runs short, and a machine with more free memory groups more. Below about
#: 1.25 GB available the floor (``MIN_FAMILY_ROWS`` keywords) is larger than a tenth: at 640 MiB
#: available it is about a fifth, at 425 MiB more than a quarter.
FAMILY_SHARE = 0.10

#: The most page cache the spill file's connection may hold, in KiB (SQLite reads a negative
#: ``cache_size`` as KiB). What it protects: the ranking's prune and per-language reads are ordered
#: scans of the file, and SQLite's own default (2 MiB) makes each one re-read the pages from disk;
#: more than this would add to a working set the plan has already sized. The cache is allocated
#: as pages are touched, so a spill that stays small uses less. It is a ceiling chosen for that
#: margin, not a measured figure, and the gate's estimate (``estimate_export_need``) does not
#: count the ranking, so this cache is outside it. Once the heaps have been moved to disk it is
#: paid from the ranker's own share, which is never below ``MIN_HEAP_ROWS * ROW_BYTES`` (40 MB,
#: 38 MiB), more than these 32 MiB: in Python's own allocations, which is what that share is
#: made of. The resident size can stay above it when the allocator keeps freed blocks (seen in
#: a review's probe when each language's rows arrive in one run, less when they interleave; the
#: field feeds rows in keyword-id order, and whether that makes runs was not measured).
#: DURING the move the heap being written (and ``add()``'s own reference to it, until ``add()``
#: returns) and the cache fill together, so for that stretch the cache can sit up to 32 MiB
#: above the share.
SPILL_CACHE_KIB = 32 * 1024

#: Ids per ``IN (...)`` list in the export's queries. What it protects: a statement stays near
#: 8 KB of SQL (ids of up to nine digits), far under SQLite's statement-length limit
#: (``getlimit(SQLITE_LIMIT_SQL_LENGTH)`` reads it: 1,000,000,000 bytes on SQLite 3.45.1). It is
#: the length every reader of this file used before the export was sized, and ``in_batches``
#: always cuts to it
#: whatever the batch is: a larger batch changes how many entries are held between two checks,
#: never how long a statement is.
IN_LIST_IDS = 800

#: Floor on the family basis, in entries. What it protects: the default export (5,000 keywords
#: per language over a dozen or so languages) must still be grouped WHOLE on a machine so small
#: that a tenth of what is left is less than that; the live memory stop, not this number, is what
#: protects such a machine. There is no ceiling: a machine with memory to spare groups its whole
#: window.
MIN_FAMILY_ROWS = 50_000

#: Floor on the heap row budget. What it protects: the default export (5,000 keywords per
#: language over a few dozen languages, about 200,000 rows) must stay in memory on a
#: machine so small that 10 % of what is left would be less than that, instead of writing
#: a spill file to a disk that may itself be nearly full. There is no ceiling: a machine
#: with memory to spare simply never spills.
MIN_HEAP_ROWS = 200_000

#: Keyword ids above this get a set rather than a byte per id. 200 M ids would be 200 MB of
#: mostly zeros; a keyword table that sparse is better served by the set.
_MARK_LIMIT = 200_000_000

#: Article ids above ``max(_DENSE_FLOOR, _DENSE_FACTOR * articles)`` make the arrays dishonest
#: about their own size (12 bytes per id up to that bound), so the maps use dicts instead.
_DENSE_FLOOR = 2_000_000
_DENSE_FACTOR = 3

#: Spill rows are written this many at a time. What it protects: the commit count (a commit per
#: row is about a hundred times slower than one per batch) while the buffer stays a couple of
#: megabytes (20,000 rows x ~120 B of tuples), far below the heap budget it sits beside. It is
#: also how often the disk watch runs while the ranking spills.
_SPILL_FLUSH = 20_000

#: Bytes one spilled row costs on disk, table plus rank index, rounded up from a measured
#: ~85-100. Used only for the free-space check before a spill begins (and it protects the
#: operator's drive, nothing else); ``test_spill_row_constant_covers_the_measured_file_size``
#: fails if the file ever costs more per row than this.
SPILL_ROW_BYTES = 120

SPILL_PREFIX = "oo-keyword-scan-"


class ExportRefused(RuntimeError):
    """The export was refused before it could harm the machine, with the numbers that say why.

    ``status`` is the HTTP status the route answers with: 507 for disk, 503 otherwise."""

    def __init__(self, message: str, *, status: int = 503) -> None:
        super().__init__(message)
        self.status = status


def memory_plan(available_bytes: float | None) -> dict[str, int]:
    """Size the export's in-memory working set from the memory AVAILABLE right now.

    ``available_bytes=None`` (psutil absent, or the reading failed) gets the floor rather
    than a guess in either direction: an unmeasured machine is neither small nor large.
    """
    if available_bytes is None or available_bytes <= 0:
        rows = MIN_HEAP_ROWS
        batch = IN_LIST_IDS
        family_rows = MIN_FAMILY_ROWS
    else:
        rows = max(MIN_HEAP_ROWS, int(available_bytes * HEAP_SHARE / ROW_BYTES))
        # An entry is about 2 KB once it is a dict and a JSON string; a batch may use ~0.2 % of
        # what is available. A batch is the unit between two checks of the memory stop and the
        # disk watch, and the number of entries held at once. The floor is one full IN list. The
        # 8,000 ceiling holds a batch to about 16 MB of entries and keeps a check coming every
        # few thousand entries on any machine. It has nothing to do with the length of an IN list,
        # which ``in_batches`` cuts to ``IN_LIST_IDS`` whatever the batch is.
        batch = max(IN_LIST_IDS, min(8000, int(available_bytes * 0.002 / 2048)))
        family_rows = max(MIN_FAMILY_ROWS, int(available_bytes * FAMILY_SHARE / FAMILY_ROW_BYTES))
    return {"heap_rows": rows, "batch": batch, "family_rows": family_rows}


def available_bytes_now() -> float | None:
    """Available system memory in bytes, ``None`` when it cannot be read."""
    try:
        import psutil

        return float(psutil.virtual_memory().available)
    except Exception:  # noqa: BLE001 - a reading is best-effort
        return None


# --------------------------------------------------------------------------- articles


class _SparseArr:
    """A dict wearing an array's indexing, for article ids too sparse for a real array."""

    __slots__ = ("_d", "_default")

    def __init__(self, default: int) -> None:
        self._d: dict[int, int] = {}
        self._default = default

    def __getitem__(self, i: int) -> int:
        return self._d.get(i, self._default)

    def __setitem__(self, i: int, v: int) -> None:
        self._d[i] = v


#: Slots of headroom when a flat array is extended. What it protects: a collection pass runs beside
#: the export and inserts articles in bursts, and extending by exactly one slot per article would
#: build and extend a one-slot array each time. It does not save a copy of the array: CPython's own
#: ``array`` over-allocates (measured: one address change in 200,000 one-slot extends of a 2 M-slot
#: array). The headroom costs 4 KB in the language array and 8 KB in the source array, nothing at
#: the scale of the arrays.
_GROW_HEADROOM = 1024


def _grow(arr: Any, aid: int, fill: int) -> None:
    """Extend a flat array so index ``aid`` exists (an article inserted after the id bounds
    were read, on a connection that holds no snapshot)."""
    # The headroom and what it protects are stated at ``_GROW_HEADROOM``.
    arr.extend(array(arr.typecode, [fill]) * (aid + 1 - len(arr) + _GROW_HEADROOM))


class ArticleMaps:
    """article id -> language and -> source id, in a few bytes per article.

    An id the table does not hold reads as language ``"?"`` (index 0) and source ``-1``,
    exactly what ``dict.get(aid, "?")`` and ``dict.get(aid)`` gave before.
    """

    def __init__(self, db, check: Callable[[], None]) -> None:
        stats = db.execute(
            text("SELECT COUNT(*), COALESCE(MIN(id), 0), COALESCE(MAX(id), 0) FROM articles")
        ).one()
        self.n_articles = int(stats[0])
        min_id, max_id = int(stats[1]), int(stats[2])
        self.langs: list[str] = [UNKNOWN]
        ids: dict[str, int] = {UNKNOWN: 0}
        self.dense = min_id >= 0 and max_id <= max(_DENSE_FLOOR, _DENSE_FACTOR * self.n_articles)
        lang_arr: Any
        src_arr: Any
        if self.dense:
            lang_arr = array("I", bytes(4 * (max_id + 1)))
            src_arr = array("q", [-1]) * (max_id + 1)
        else:
            lang_arr, src_arr = _SparseArr(0), _SparseArr(-1)
        for i, (aid, lg) in enumerate(db.execute(text("SELECT id, language FROM articles"))):
            key = lg or UNKNOWN
            lid = ids.get(key)
            if lid is None:
                key = sys.intern(key)
                lid = len(self.langs)
                ids[key] = lid
                self.langs.append(key)
            try:
                lang_arr[aid] = lid
            except IndexError:  # an article newer than the bounds read (no snapshot held)
                _grow(lang_arr, aid, 0)
                lang_arr[aid] = lid
            if not i & (_CHECK_EVERY - 1):
                check()
        for i, (aid, sid) in enumerate(db.execute(text("SELECT id, source_id FROM articles"))):
            if sid is not None:
                try:
                    src_arr[aid] = sid
                except IndexError:
                    _grow(src_arr, aid, -1)
                    src_arr[aid] = sid
            if not i & (_CHECK_EVERY - 1):
                check()
        self.lang_arr = lang_arr
        self.src_arr = src_arr

    def lang_of(self, aid: int) -> str:
        """The article's language code (``"?"`` when unknown) -- for callers off the hot path."""
        try:
            return self.langs[self.lang_arr[aid]] if aid >= 0 else UNKNOWN
        except IndexError:
            return UNKNOWN


# --------------------------------------------------------------------------- digests


class _Rev:
    """Wraps a key so that a SMALLER key compares as LARGER.

    The digests keep the ``k`` best items by "more articles, then more mentions, then the one
    that came first in survivor order". A heap wants one total order, and the last component
    runs the opposite way to the first two, so it is wrapped rather than negated (survivor
    order is a tuple, which has no negation).
    """

    __slots__ = ("k",)

    def __init__(self, k: Any) -> None:
        self.k = k

    def __lt__(self, other: _Rev) -> bool:
        return self.k > other.k

    def __gt__(self, other: _Rev) -> bool:
        return self.k < other.k

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Rev) and self.k == other.k

    def __hash__(self) -> int:
        return hash(self.k)


def order_key(kid: int, m: int, has_mentions: bool) -> tuple[int, int, int]:
    """Position in the export's global survivor order: mention-bearing keywords by mentions
    descending then id ascending, then the orphans by id ascending. Smaller = earlier."""
    return (0 if has_mentions else 1, -m, kid)


class _TopList:
    """The ``limit`` best items of a stream, ordered "a desc, m desc, survivor order asc"."""

    __slots__ = ("limit", "heap")

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.heap: list[tuple] = []

    def push(self, a: int, m: int, okey: Any, payload: dict) -> None:
        item = (a, m, _Rev(okey), payload)
        if len(self.heap) < self.limit:
            heapq.heappush(self.heap, item)
        elif item[:3] > self.heap[0][:3]:
            heapq.heapreplace(self.heap, item)

    def ordered(self) -> list[dict]:
        return [t[3] for t in sorted(self.heap, key=lambda t: t[:3], reverse=True)]


class StopwordAcc:
    """Streaming form of ``_stopword_candidates``: per dominant language, the highest
    article-SPREAD short single-token terms that are not yet stoplisted.

    Feed it every survivor; it keeps the top ``per_lang`` per language and the exact
    qualifying count, and orders languages exactly as the one-shot function did (status
    priority, then size, ties by first appearance in survivor order)."""

    def __init__(self, is_hidden: Callable[[str], bool], *, per_lang: int, max_len: int,
                 min_articles: int) -> None:
        self._hidden = is_hidden
        self._per_lang = per_lang
        self._max_len = max_len
        self._min_articles = min_articles
        self._by_lang: dict[str, list] = {}  # lang -> [total, _TopList, first_okey]

    def feed(self, okey: Any, m: int, a: int, dom: str | None, meta: tuple) -> None:
        term, norm, lang, is_ent, _ent = meta
        if is_ent or not norm or " " in norm:
            return
        if len(norm) > self._max_len or int(a) < self._min_articles:
            return
        if self._hidden(norm):
            return
        d = dom or lang or UNKNOWN
        slot = self._by_lang.get(d)
        if slot is None:
            slot = self._by_lang[d] = [0, _TopList(self._per_lang), okey]
        slot[0] += 1
        if okey < slot[2]:
            slot[2] = okey
        top = slot[1]
        if len(top.heap) < top.limit or (int(a), int(m)) >= top.heap[0][:2]:
            top.push(int(a), int(m), okey,
                     {"term": term, "normalized": norm, "mentions": int(m),
                      "articles": int(a), "len": len(norm)})

    def result(self) -> dict:
        from src.analytics.managed import language_status

        out: dict[str, dict] = {}
        for dom, (total, top, _first) in sorted(self._by_lang.items(), key=lambda kv: kv[1][2]):
            out[dom] = {"status": language_status(dom), "total": total,
                        "candidates": top.ordered()}
        priority = sorted(
            (d for d, v in out.items() if v["status"] in ("no_stoplist", "unsegmented")),
            key=lambda d: -out[d]["total"],
        )
        ordered = dict(sorted(
            out.items(),
            key=lambda kv: (kv[1]["status"] not in ("no_stoplist", "unsegmented"),
                            -kv[1]["total"]),
        ))
        return {"priority": priority, "ordered": ordered}


class RingAcc:
    """Streaming form of ``_ring_candidates``: per dominant language, the highest
    article-spread TERMS not in any cross-language ring, plus the coverage counters.

    ``ring_of(lang, normalized)`` is ``equivalence.ring_of``; it is passed in so the
    accumulator stays free of the equivalence tables (and testable without them)."""

    def __init__(self, is_hidden: Callable[[str], bool], ring_of: Callable[[str, str], Any], *,
                 per_lang: int, min_articles: int) -> None:
        self._hidden = is_hidden
        self._ring_of = ring_of
        self._per_lang = per_lang
        self._min_articles = min_articles
        self._gap: dict[str, list] = {}  # lang -> [gap_total, _TopList, first_okey]
        self._gated: dict[str, int] = {}
        self._covered: dict[str, int] = {}

    def feed(self, okey: Any, m: int, a: int, dom: str | None, meta: tuple) -> None:
        term, norm, lang, is_ent, _ent = meta
        if is_ent or not norm:
            return
        if int(a) < self._min_articles or self._hidden(norm):
            return
        eff = dom or lang or UNKNOWN
        self._gated[eff] = self._gated.get(eff, 0) + 1
        if self._ring_of(eff, norm) is not None:
            self._covered[eff] = self._covered.get(eff, 0) + 1
            return
        slot = self._gap.get(eff)
        if slot is None:
            slot = self._gap[eff] = [0, _TopList(self._per_lang), okey]
        slot[0] += 1
        if okey < slot[2]:
            slot[2] = okey
        top = slot[1]
        if len(top.heap) < top.limit or (int(a), int(m)) >= top.heap[0][:2]:
            top.push(int(a), int(m), okey,
                     {"term": term, "normalized": norm, "mentions": int(m), "articles": int(a)})

    def result(self) -> dict:
        out: dict[str, dict] = {}
        for lang, (gap_total, top, _first) in sorted(self._gap.items(), key=lambda kv: kv[1][2]):
            g = self._gated.get(lang, 0)
            c = self._covered.get(lang, 0)
            out[lang] = {
                "gap_total": gap_total,
                "ring_covered": c,
                "coverage": round(c / g, 4) if g else 0.0,
                "candidates": top.ordered(),
            }
        ordered = dict(sorted(out.items(), key=lambda kv: (kv[1]["coverage"], -kv[1]["gap_total"])))
        tot_g = sum(self._gated.values())
        tot_c = sum(self._covered.values())
        return {
            "translation_coverage": round(tot_c / tot_g, 4) if tot_g else 0.0,
            "gated_terms": tot_g,
            "by_language": ordered,
        }


class SuspectBoard:
    """The boilerplate-suspect list: every qualifying (keyword, source) pair is COUNTED, only
    the strongest ``limit`` are kept (the anti-capping rule: a cap may bound a REPORT, never
    the crunching; 200 is a list a person reads). Order: share of source desc, count in source
    desc, keyword id asc."""

    def __init__(self, limit: int = 200) -> None:
        self.limit = limit
        self.total = 0
        self._heap: list[tuple] = []

    def add(self, kid: int, rec: dict) -> None:
        self.total += 1
        key = (rec["share_of_source"], rec["in_this_source"], -kid)
        item = (key, kid, rec)
        if len(self._heap) < self.limit:
            heapq.heappush(self._heap, item)
        elif key > self._heap[0][0]:
            heapq.heapreplace(self._heap, item)

    def top(self) -> list[dict]:
        return [t[2] for t in sorted(self._heap, key=lambda t: t[0], reverse=True)]


# --------------------------------------------------------------------------- ranking


#: SQLite's extended result code for a write that failed with an errno it has no word for
#: (``SQLITE_IOERR_WRITE``: its unix layer says ``disk I/O error`` for a quota or a drive that
#: turned read-only, and ``database or disk is full`` only for ENOSPC). The constant exists from
#: Python 3.11, and this project needs 3.13.
_SQLITE_IOERR_WRITE = sqlite3.SQLITE_IOERR_WRITE


def _drive_is_read_only(directory: Path | str) -> bool:
    """True when the file system holding ``directory`` is mounted read-only (``statvfs``; a
    platform without it, or a folder it cannot read, says False: nothing is guessed)."""
    statvfs = getattr(os, "statvfs", None)
    flag = getattr(os, "ST_RDONLY", None)
    if statvfs is None or flag is None:
        return False
    try:
        return bool(statvfs(str(directory)).f_flag & flag)
    except OSError:
        return False


@contextlib.contextmanager
def _refuse_when_the_disk_is_full(directory: Path | str | None = None):
    """SQLite's own "database or disk is full" (and "attempt to write a readonly database") is the
    drive answering, not a fault of ours: say so, as the same refusal (HTTP 507) the free-space
    checks give. A bare "disk I/O error" on a write (``SQLITE_IOERR_WRITE``) is the same answer
    only when the drive says so itself: ``directory``'s file system is read-only. Without that it
    could as well be a failing drive or a quota SQLite cannot name, so it is raised as itself.
    Any other SQLite error is raised as itself."""
    try:
        yield
    except sqlite3.OperationalError as exc:
        said = str(exc).lower()
        if "full" in said:
            code = errno.ENOSPC
        elif (
            "readonly" in said
            or "read-only" in said
            or (
                getattr(exc, "sqlite_errorcode", None) == _SQLITE_IOERR_WRITE
                and directory is not None
                and _drive_is_read_only(directory)
            )
        ):
            code = errno.EROFS
        else:
            raise
        refusal = no_room_refusal(OSError(code, str(exc)), "ranking keywords")
        if refusal is None:
            raise
        raise refusal from exc


#: The OS errors that all say "the drive will not take what the export is writing": a full disk
#: (ENOSPC), a user's quota (EDQUOT, which Windows does not define), and a read-only file system
#: (EROFS, for instance a data folder on a drive the system remounted read-only after errors).
#: What they protect: each is a fact about the operator's machine to be told with the way out, and
#: not a 500 that reads as a bug in the app.
_NO_ROOM_ERRNOS = frozenset(
    code for code in (errno.ENOSPC, getattr(errno, "EDQUOT", None), errno.EROFS) if code is not None
)


def no_room_refusal(exc: OSError, doing: str) -> ExportRefused | None:
    """The 507 for an OS error that means the drive will not take the write, or ``None`` for any
    other error (which the caller raises as itself: it may be a bug, and a bug must stay visible).

    ``doing`` finishes "while the export was ...". The text says "the drive the export writes to"
    because that is the data folder, or the system's temp folder when there is none."""
    code = getattr(exc, "errno", None)
    if code not in _NO_ROOM_ERRNOS:
        return None
    if code == errno.EROFS:
        return ExportRefused(
            f"the drive the export writes to turned out to be read-only while the export was "
            f"{doing}, so it stopped. The data folder (or the system's temp folder, when there is "
            "none) has to be writable for an export. A partial file that could not be deleted from "
            "a read-only drive is removed by a later export once the drive is writable "
            "(scratch files older than twelve hours are swept at the start of each export).",
            status=507,
        )
    why = "has no room left in your disk quota" if code != errno.ENOSPC else "ran out of room"
    return ExportRefused(
        f"the drive the export writes to {why} while the export was {doing}, so it stopped and "
        "removed any partial file (one it could not delete is swept by a later export that writes "
        "to the same folder once it is twelve hours old). Free some space, or ask for a smaller "
        "window (per_lang=...).",
        status=507,
    )


def scratch_file(prefix: str, suffix: str, directory: Path | str) -> Path:
    """Create an empty scratch file with a name no other export can share (``mkstemp``).

    A full drive answers here too: creating the file is the first write the export makes, and on
    a drive with no room it raises ``ENOSPC`` from the OS, not from SQLite. A quota and a
    read-only drive answer the same way. All are the same refusal (HTTP 507) the free-space
    checks give (see :func:`no_room_refusal`), never a 500 that reads as a bug in the app.
    """
    try:
        fd, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=str(directory))
    except OSError as exc:
        refusal = no_room_refusal(exc, "creating its scratch file")
        if refusal is None:
            raise
        raise refusal from exc
    os.close(fd)
    return Path(name)


class Ranker:
    """Per-language quota ranking that never holds more than ``heap_rows`` rows in memory.

    ``add`` every keyword once; afterwards :meth:`rows` yields a language's window
    ``[lo, hi)`` in rank order as ``(kid, m, a, first, last, dom)`` (``dom`` is ``None`` for
    a keyword with no mention row). Rank order within a language is the export's own:
    mention-bearing keywords by mentions descending then id ascending, then the orphans by
    id ascending.

    Two modes, one behaviour. In heap mode each language keeps its best ``hi`` rows. When
    the rows held across all languages would pass ``heap_rows`` the contents move to an
    SQLite file under ``spill_dir`` and every later row goes there too. ``disk_check(bytes)``
    is called first and raises :class:`ExportRefused` when the volume cannot take the file.

    The spill is bounded the way the heaps are: a language never holds more than ``2 * hi``
    rows on disk. When it reaches that, the rows ranked beyond ``hi`` are deleted and the
    ``hi``-th row's key becomes that language's floor, so a later row that cannot rank inside
    the window is never written at all. What this protects is the drive: without it a window
    of 5,000 over 14.65 M keywords wrote the whole keyword table (1.2-1.7 GB) to disk after the
    up-front check had sized the file for the rows held at the moment of the switch.
    ``disk_watch()`` runs after every flush, and a full-disk error from SQLite itself is
    reported as the same :class:`ExportRefused` (507), never as a server error.
    """

    def __init__(self, lo: int, hi: int, *, heap_rows: int, spill_dir: Path | None,
                 disk_check: Callable[[int], None] | None, expected_rows: int = 0,
                 disk_watch: Callable[[], None] | None = None) -> None:
        self._lo, self._hi = lo, hi
        self._heap_rows = heap_rows
        # No folder named: the OS temp folder, never "nowhere" (a ranker with nowhere to spill
        # grows to the whole window in memory, which is the defect this class exists to end).
        self._spill_dir = spill_dir if spill_dir is not None else Path(tempfile.gettempdir())
        self._disk_check = disk_check
        self._disk_watch = disk_watch
        self._expected = expected_rows
        self._heaps: dict[str, list] = {}
        self._held = 0
        self._seen: dict[str, int] = {}
        self._con: sqlite3.Connection | None = None
        self._path: Path | None = None
        self._buf: list[tuple] = []
        # Spill mode only: rows per language on disk (or buffered), and the rank key of the
        # ``hi``-th row after a language's last prune (a row that does not beat it is outside
        # the window for good, because rank only ever worsens as rows arrive).
        self._on_disk: dict[str, int] = {}
        self._floor: dict[str, tuple[int, int, int]] = {}

    # -- feeding

    def add(self, lang: str, kid: int, m: int, a: int, first: str | None, last: str | None,
            dom: str | None) -> None:
        seen = self._seen
        seen[lang] = seen.get(lang, 0) + 1
        if self._con is not None:
            has_m = 0 if dom is None else 1
            floor = self._floor.get(lang)
            if floor is not None and (has_m, m, -kid) <= floor:
                return
            self._buf.append((kid, lang, has_m, m, a, first, last, dom))
            n = self._on_disk[lang] = self._on_disk.get(lang, 0) + 1
            if self._hi > 0 and n >= 2 * self._hi:
                self._prune(lang)
            elif len(self._buf) >= _SPILL_FLUSH:
                self._flush()
            return
        item = (0 if dom is None else 1, m, -kid, a, first, last, dom)
        h = self._heaps.get(lang)
        if h is None:
            self._heaps[lang] = [item]
            self._held += 1
        elif len(h) < self._hi:
            heapq.heappush(h, item)
            self._held += 1
        elif item > h[0]:
            heapq.heapreplace(h, item)
        else:
            return
        if self._held > self._heap_rows:
            self._to_spill()

    def _to_spill(self) -> None:
        # The spill cannot hold more than every keyword, nor more than ``2 * hi`` rows for
        # each language (see the class docstring). Languages still to appear are not known
        # yet, so the disk watch (after every flush) is the backstop for what this cannot see.
        bound = max(self._held, self._expected)
        if self._hi > 0 and len(self._heaps) * 2 * self._hi < bound:
            bound = max(self._held, len(self._heaps) * 2 * self._hi)
        if self._disk_check is not None:
            self._disk_check(bound * SPILL_ROW_BYTES)
        # mkstemp: a name no other export can share (two in one millisecond used to), created
        # before anything else so a failure below has a file to remove.
        self._path = scratch_file(SPILL_PREFIX, ".sqlite", self._spill_dir)
        name = str(self._path)
        con: sqlite3.Connection | None = None
        try:
            with _refuse_when_the_disk_is_full(self._spill_dir):
                con = sqlite3.connect(name, isolation_level=None, check_same_thread=False)
                for pragma in ("journal_mode=OFF", "synchronous=OFF", "locking_mode=EXCLUSIVE",
                               f"cache_size=-{SPILL_CACHE_KIB}"):
                    con.execute(f"PRAGMA {pragma}")
                con.execute(
                    "CREATE TABLE kw (kid INTEGER PRIMARY KEY, lang TEXT NOT NULL, has_m INTEGER NOT NULL,"
                    " m INTEGER NOT NULL, a INTEGER NOT NULL, first TEXT, last TEXT, dom TEXT)"
                )
                # Created BEFORE the rows go in: SQLite builds an index after the fact with a
                # sorter that spills to its temp directory, which on some machines is a RAM disk.
                con.execute("CREATE INDEX kw_rank ON kw (lang, has_m DESC, m DESC, kid)")
        except BaseException:
            if con is not None:
                with contextlib.suppress(sqlite3.Error):
                    con.close()
            self._remove_spill_files()
            raise
        self._con = con
        _LOG.info("keyword export: %d rows held, spilling the ranking to %s", self._held, self._path)
        # One language at a time, in flush-sized slices, popping each heap as it is written, so
        # moving the rows to disk never holds a second copy of them.
        for lang in list(self._heaps):
            h = self._heaps.pop(lang)
            self._on_disk[lang] = len(h)
            for i in range(0, len(h), _SPILL_FLUSH):
                self._buf = [
                    (-it[2], lang, it[0], it[1], it[3], it[4], it[5], it[6])
                    for it in h[i:i + _SPILL_FLUSH]
                ]
                self._flush()
        self._held = 0

    def _flush(self) -> None:
        if self._buf and self._con is not None:
            with _refuse_when_the_disk_is_full(self._spill_dir):
                self._con.execute("BEGIN")
                self._con.executemany("INSERT INTO kw VALUES (?,?,?,?,?,?,?,?)", self._buf)
                self._con.execute("COMMIT")
            self._buf = []
            if self._disk_watch is not None:
                self._disk_watch()

    def _prune(self, lang: str) -> None:
        """Drop this language's rows ranked beyond ``hi`` and remember where the cut was."""
        self._flush()
        con = self._con
        assert con is not None
        with _refuse_when_the_disk_is_full(self._spill_dir):
            cut = con.execute(
                "SELECT has_m, m, kid FROM kw WHERE lang=? "
                "ORDER BY has_m DESC, m DESC, kid ASC LIMIT 1 OFFSET ?",
                (lang, self._hi - 1),
            ).fetchone()
            if cut is None:
                return
            has_m, m, kid = cut
            con.execute(
                "DELETE FROM kw WHERE lang=? AND (has_m < ? OR (has_m = ? AND (m < ? OR (m = ? AND kid > ?))))",
                (lang, has_m, has_m, m, m, kid),
            )
        self._floor[lang] = (has_m, m, -kid)
        self._on_disk[lang] = self._hi

    # -- reading

    def clamp(self, hi: int) -> None:
        """Narrow the window's upper end after the scan (never widens it: rows the heaps
        discarded for ranking beyond the old ``hi`` are gone)."""
        self._hi = min(self._hi, hi)

    @property
    def spilled(self) -> bool:
        return self._con is not None

    def totals(self) -> dict[str, int]:
        """Keywords seen per language (window or not): pages_total and has_more read this."""
        return dict(self._seen)

    def taken(self, lang: str) -> int:
        """Rows of this language inside the window."""
        return max(0, min(self._seen.get(lang, 0), self._hi) - self._lo)

    @property
    def window_start(self) -> int:
        """The rank (from 0) of the first row of the window: what a later page starts at."""
        return self._lo

    def rows(self, lang: str) -> Iterator[tuple]:
        if self._con is None:
            h = sorted(self._heaps.get(lang, ()), reverse=True)
            for it in h[self._lo:self._hi]:
                yield (-it[2], it[1], it[3], it[4], it[5], it[6])
            return
        self._flush()
        yield from self._con.execute(
            "SELECT kid, m, a, first, last, dom FROM kw WHERE lang=? "
            "ORDER BY has_m DESC, m DESC, kid ASC LIMIT ? OFFSET ?",
            # max(0, ...): SQLite reads a NEGATIVE limit as "no limit", where the heap form's
            # slice [lo:hi] is empty when hi < lo. The route cannot reach it (fit_window never
            # returns less than one), but the two modes are one behaviour, so they agree here too.
            (lang, max(0, self._hi - self._lo), self._lo),
        )

    def close(self) -> None:
        con, self._con = self._con, None
        # The heap form holds a copy of every row of the window until it is read out; nothing
        # reads a closed ranker, and the grouping that follows is the peak, so the copy goes now.
        self._heaps = {}
        try:
            if con is not None:
                con.close()
        finally:
            self._remove_spill_files()

    def _remove_spill_files(self) -> None:
        if self._path is not None:
            for suffix in ("", "-journal", "-wal", "-shm"):
                with contextlib.suppress(OSError):
                    os.unlink(str(self._path) + suffix)

    def __enter__(self) -> Ranker:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# --------------------------------------------------------------------------- the scan


#: What the DIGEST holds per keyword it exports, once the window is ranked: the survivor row, and
#: the copy of it the ranking's heaps hold until the ranker is closed (which drops them, before the
#: grouping). It is NOT the cost of a keyword's metadata, its language signature or its entry: the
#: digest builds those a batch at a time and lets them go (``_DigestPass`` in the route). Kept for
#: every keyword of the window together, as the digest used to, they were part of a 1,057 MiB peak
#: at 82 languages x 5,000 (measured 2026-10-06 on the code this replaces: 226 MiB for the
#: entries, 199 MiB for the metadata and signatures behind them, +535 MiB inside ``build_families``
#: and 200 MiB for a dict of every family). The families' grouping is sized separately
#: (``FAMILY_ROW_BYTES`` per grouped keyword, a budget taken from the memory available). The
#: single-file JSON form is NOT priced by this constant: it still holds every survivor's metadata
#: and signature at once (about 2.5 KB each, as measured), and the bundle gate prices only the
#: digest (``_MEMBER_NEED_ESTIMATORS``), the one form the bundle runs.
#: MEASURED 2026-10-06 (synthetic databases of 21, 41 and 82 languages x 5,000 exported
#: keywords, 105,000 / 205,000 / 410,000 entries, the process's peak resident rise in its own
#: process with the grouping held at 50,000 keywords): +145.7 / +192.0 / +272.8 MiB, a slope of
#: 413-485 bytes per entry. The constant is the largest slope rounded up to 500 (3 % over). The
#: margin for the length of real terms is NOT here, since a survivor row holds ids, counts and
#: dates and no term: it sits on ``FAMILY_ROW_BYTES``, the constant that scales with a term, and
#: the fixed part below covers the rest (priced at 60 MiB, measured at 38). Two tests hold it: one
#: fails if it stops covering the Python-allocation cost (tracemalloc, a LOWER bound on what the
#: process takes), and one pins the value itself, so changing it means re-measuring the resident
#: size on purpose. The measuring scripts (a synthetic database of N languages x 5,000 keywords
#: and a peak-RSS probe of the digest) are kept with the project's shared files, not in this
#: repository; the method is the one in the sentences above.
EXPORT_ENTRY_BYTES = 500

#: The rest of the export's rise in resident memory that does not scale with the corpus: the
#: reading connection's SQLite page cache (not the spill's, which ``SPILL_CACHE_KIB`` names and
#: the gate does not count), the accumulators, the interpreter's own growth. MEASURED: the
#: intercept of the fit above, once the 50,000-keyword grouping and the entries' own cost are
#: taken out, is 29-38 MiB (29 MiB at 21 languages; 38 MiB in the earlier fit on the old code).
#: 60 MiB is 1.6x the larger; ``test_export_fixed_constant_covers_the_measured_intercept`` fails
#: if it drops below the 38 MiB that was measured, and the value itself is pinned, so a change is
#: a re-measurement and not a drift.
EXPORT_FIXED_BYTES = 60 * 2**20

#: Bytes per article while the language/source arrays are dense (an ``I`` and a ``q``), and
#: per article when the ids are too sparse for that and two dicts stand in (measured ~100 each).
_ARRAY_BYTES_PER_ID = 12
_SPARSE_BYTES_PER_ARTICLE = 200


def estimate_export_need(
    db, *, per_language: int, available_bytes: float | None = None
) -> dict[str, Any]:
    """What one export over THIS database is expected to add to the process, from its own counts.

    ``per_language`` is the window the export is asked for per language (the digest uses the
    classic 5,000). It prices the DIGEST: the single-file JSON stream holds more per keyword (see
    ``EXPORT_ENTRY_BYTES``) and is not priced here. The estimate is the fixed part, plus one
    keyword's cost times the keywords that can be exported (at most ``per_language`` for each language and never
    more than the keyword table holds), plus the families' grouping (``FAMILY_ROW_BYTES`` for each
    keyword it is given: the window, or the budget ``memory_plan`` takes from ``available_bytes``
    when the window is larger), plus the article arrays (12 bytes per article id) and the keyword
    mark (a byte per id). ``available_bytes`` is the memory the machine has now (``None``: the
    plan's floor, which is what an unmeasured machine gets). The ranker is NOT in it: its heaps
    are bounded by a share of the memory available at the start and spill to disk past that, so it
    cannot be what makes the export too big for the machine.

    Three statements: one aggregate over the articles' ids (COUNT, MIN and MAX in one pass), the
    keyword table's highest id (a primary-key read), and the number of distinct languages the
    articles carry (one pass over their language column; its cost on a 1.8 M-article instance is
    not measured here, and it is a single pass beside an export that reads every mention).
    ``None`` for a count that cannot be read is treated as zero by the caller's fallback, never
    guessed.

    What it does not see, and which way it errs: the languages are the ARTICLES' (plus one for
    "?"), because counting the keyword table's own languages would scan the whole table, which has
    no index on it. A mention-bearing keyword always lands in one of its articles' languages, so
    only ORPHANS in a language no article carries are missed (at most one window for each such
    language: 5,000 entries at 500 B and as many family rows at 2,500 B, at most 14.3 MiB at the
    default, and how many such languages there are is not measured); an instance with many thin languages is over-counted, since each is priced at
    a full window. The error is on the side of declining a machine slightly early.
    """
    n_art, min_art, max_art = (int(v or 0) for v in db.execute(
        text("SELECT COUNT(*), COALESCE(MIN(id), 0), COALESCE(MAX(id), 0) FROM articles")
    ).one())
    max_kid = int(db.execute(text("SELECT COALESCE(MAX(id), 0) FROM keywords")).scalar() or 0)
    # +1 for the "?" language an article without one (or a keyword no mention names) falls in.
    languages = int(db.execute(text("SELECT COUNT(DISTINCT language) FROM articles")).scalar() or 0) + 1
    dense = min_art >= 0 and max_art <= max(_DENSE_FLOOR, _DENSE_FACTOR * n_art)
    article_bytes = (
        _ARRAY_BYTES_PER_ID * (max_art + 1) if dense else _SPARSE_BYTES_PER_ARTICLE * n_art
    )
    entries = min(max_kid, languages * per_language)
    budget = memory_plan(available_bytes)["family_rows"]
    grouped = min(entries, budget)
    need = (
        EXPORT_FIXED_BYTES + entries * EXPORT_ENTRY_BYTES + grouped * FAMILY_ROW_BYTES
        + article_bytes + (max_kid + 1)
    )
    return {
        "need_mb": need / 2**20,
        "articles": n_art,
        "keyword_id_bound": max_kid,
        "languages": languages,
        "exportable_keywords": entries,
        "per_language": per_language,
        "grouped_keywords": grouped,
        "grouping_budget_keywords": budget,
    }


class ScanStats:
    """What the scan learned beyond the ranking."""

    __slots__ = ("keywords_total", "board")

    def __init__(self, keywords_total: int, board: SuspectBoard) -> None:
        self.keywords_total = keywords_total
        self.board = board


def scan_keywords(db, maps: ArticleMaps, src_articles: dict[int, int], ranker: Ranker, *,
                  check: Callable[[], None]) -> ScanStats:
    """The one ordered pass over the mention rows, then one pass over the keyword table.

    Per keyword (as the ordered scan leaves it): mentions = SUM(count), articles = its row
    count (a row is unique per (keyword, article) under ``ix_mention_covering``, so a row
    count IS the distinct-article count), first/last = MIN/MAX(observed_on) ignoring NULL,
    the dominant article language (ties: language code ascending), and the boilerplate
    suspect test (>= 10 articles, >= 90 % in one source, >= 25 % of that source's articles).
    Orphans -- keywords no mention row names -- are ranked after every mention-bearing one,
    in their stored language (``"?"`` when it is NULL or empty).
    """
    board = SuspectBoard()
    max_kid = int(db.execute(text("SELECT COALESCE(MAX(id), 0) FROM keywords")).scalar() or 0)
    # Which keyword ids a mention row named: a byte per id, or a set for a table too sparse
    # for that (see _MARK_LIMIT).
    mark_arr: bytearray | None = bytearray(max_kid + 1) if max_kid <= _MARK_LIMIT else None
    mark_set: set[int] = set()
    langs = maps.langs
    lang_arr, src_arr = maps.lang_arr, maps.src_arr
    dates: dict[str, str] = {}

    cur_kid: int | None = None
    counts: dict[int, int] = {}
    srcs: dict[int, int] = {}
    m = a = n_src = 0
    first: str | None = None
    last: str | None = None

    def finalize() -> None:
        if cur_kid is None or not counts:
            return
        if len(counts) == 1:
            lid = next(iter(counts))
        else:
            lid = min(counts, key=lambda lg: (-counts[lg], langs[lg]))
        dom = langs[lid]
        ranker.add(dom, cur_kid, m, a, first, last, dom)
        if mark_arr is not None:
            if 0 <= cur_kid <= max_kid:
                mark_arr[cur_kid] = 1
        else:
            mark_set.add(cur_kid)
        if n_src >= 10:
            top_src, top_n = max(srcs.items(), key=lambda kv: kv[1])
            src_total = src_articles.get(top_src, 0)
            if src_total >= 10 and top_n / n_src >= 0.9 and top_n / src_total >= 0.25:
                board.add(cur_kid, {
                    "keyword_id": cur_kid,
                    "source_id": top_src,
                    "articles_with_keyword": n_src,
                    "in_this_source": top_n,
                    "source_article_total": src_total,
                    "share_of_keyword": round(top_n / n_src, 3),
                    "share_of_source": round(top_n / src_total, 3),
                })

    for n, (kid, aid, cnt, obs) in enumerate(
        db.execute(
            text(
                f"SELECT keyword_id, article_id, count, observed_on FROM {MENTIONS_TABLE}"  # nosec B608 - constant table name
                " ORDER BY keyword_id"
            )
        ),
        1,
    ):
        if kid != cur_kid:
            finalize()
            cur_kid, counts, srcs = kid, {}, {}
            m = a = n_src = 0
            first = last = None
        try:
            lid = lang_arr[aid] if aid >= 0 else 0
        except IndexError:
            lid = 0
        counts[lid] = counts.get(lid, 0) + 1
        try:
            sid = src_arr[aid] if aid >= 0 else -1
        except IndexError:
            sid = -1
        if sid != -1:
            srcs[sid] = srcs.get(sid, 0) + 1
            n_src += 1
        m += cnt or 0
        a += 1
        if obs is not None:
            if first is None or obs < first:
                first = dates.setdefault(obs, obs)
            if last is None or obs > last:
                last = dates.setdefault(obs, obs)
        if not n & (_CHECK_EVERY - 1):
            check()
    finalize()

    keywords_total = 0
    lang_cache: dict[str, str] = {}
    for kid, lg in db.execute(text("SELECT id, language FROM keywords")):
        keywords_total += 1
        marked = (0 <= kid <= max_kid and mark_arr[kid] != 0) if mark_arr is not None else kid in mark_set
        if marked:
            continue
        key = lg or UNKNOWN
        interned = lang_cache.get(key)
        if interned is None:
            interned = lang_cache[key] = sys.intern(key)
        ranker.add(interned, kid, 0, 0, None, None, None)
        if not keywords_total & (_CHECK_EVERY - 1):
            check()
    return ScanStats(keywords_total, board)
