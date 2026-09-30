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
  SQLite file next to the data (after a free-space check) and reads each language back in
  rank order. A spill loses nothing the window could use: a row that a full heap discards is
  ranked beyond the window for good, because rank only ever worsens as rows arrive.
* :class:`StopwordAcc`, :class:`RingAcc` and :class:`SuspectBoard` are the streaming forms
  of the three digests the export computes over its survivors. They keep a bounded top list
  and exact counters, and they reproduce the ordering of the one-shot functions they
  replaced, tie-break included (``tests/test_keyword_log_scan.py`` is the differential).

WHAT IT DOES NOT DO. It does not change what is counted or how it is ranked: the same
mention rows (``MENTIONS_TABLE`` is the one place that names the table, so the keyword
thread's move of readers onto ``KeywordMentionRead`` (D22) is a one-line change), the
same per-article language (``articles.language``, not the per-mention column), the same
order: mention-bearing keywords by mentions descending then id ascending, then the orphans by
id ascending, within each language.
"""

from __future__ import annotations

import contextlib
import heapq
import logging
import os
import sqlite3
import sys
import time
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
#: grouping's own record for it, and the family it lands in. MEASURED (a 60,000-entry basis
#: peaked at 1.47-1.85 KB per entry depending on how many were multi-token phrases), rounded up;
#: ``test_family_row_budget_constant_matches_the_measured_size`` fails if it drifts.
FAMILY_ROW_BYTES = 2000

#: The share of AVAILABLE memory the family grouping may use, on top of the ranker's own tenth.
FAMILY_SHARE = 0.10

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

#: Spill rows are written this many at a time.
_SPILL_FLUSH = 20_000

#: Bytes one spilled row costs on disk, table plus rank index, rounded up from a measured
#: ~85. Used only for the free-space check before a spill begins.
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
        batch = 800
        family_rows = MIN_FAMILY_ROWS
    else:
        rows = max(MIN_HEAP_ROWS, int(available_bytes * HEAP_SHARE / ROW_BYTES))
        # An entry is about 2 KB once it is a dict and a JSON string; a batch may use ~0.2 % of
        # what is available. 800 is what every reader of this file used before it was sized.
        batch = max(800, min(8000, int(available_bytes * 0.002 / 2048)))
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


def _grow(arr: Any, aid: int, fill: int) -> None:
    """Extend a flat array so index ``aid`` exists (an article inserted after the id bounds
    were read, on a connection that holds no snapshot)."""
    arr.extend(array(arr.typecode, [fill]) * (aid + 1 - len(arr) + 1024))


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
    the crunching). Order: share of source desc, count in source desc, keyword id asc."""

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
    """

    def __init__(self, lo: int, hi: int, *, heap_rows: int, spill_dir: Path | None,
                 disk_check: Callable[[int], None] | None, expected_rows: int = 0) -> None:
        self._lo, self._hi = lo, hi
        self._heap_rows = heap_rows
        self._spill_dir = spill_dir
        self._disk_check = disk_check
        self._expected = expected_rows
        self._heaps: dict[str, list] = {}
        self._held = 0
        self._seen: dict[str, int] = {}
        self._con: sqlite3.Connection | None = None
        self._path: Path | None = None
        self._buf: list[tuple] = []

    # -- feeding

    def add(self, lang: str, kid: int, m: int, a: int, first: str | None, last: str | None,
            dom: str | None) -> None:
        seen = self._seen
        seen[lang] = seen.get(lang, 0) + 1
        if self._con is not None:
            self._buf.append((kid, lang, 0 if dom is None else 1, m, a, first, last, dom))
            if len(self._buf) >= _SPILL_FLUSH:
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
        if self._spill_dir is None:
            # Nowhere to put a file: keep going in memory rather than fail, but say so. The
            # caller only omits the directory when it has nothing better (a test, a stub).
            return
        need = max(self._expected, self._held) * SPILL_ROW_BYTES
        if self._disk_check is not None:
            self._disk_check(need)
        self._path = self._spill_dir / f"{SPILL_PREFIX}{os.getpid()}-{int(time.time() * 1000)}.sqlite"
        con = sqlite3.connect(str(self._path), isolation_level=None, check_same_thread=False)
        for pragma in ("journal_mode=OFF", "synchronous=OFF", "locking_mode=EXCLUSIVE",
                       "cache_size=-32768"):
            con.execute(f"PRAGMA {pragma}")
        con.execute(
            "CREATE TABLE kw (kid INTEGER PRIMARY KEY, lang TEXT NOT NULL, has_m INTEGER NOT NULL,"
            " m INTEGER NOT NULL, a INTEGER NOT NULL, first TEXT, last TEXT, dom TEXT)"
        )
        # Created BEFORE the rows go in: SQLite builds an index after the fact with a sorter
        # that spills to its temp directory, which on some machines is a RAM disk.
        con.execute("CREATE INDEX kw_rank ON kw (lang, has_m DESC, m DESC, kid)")
        self._con = con
        _LOG.info("keyword export: %d rows held, spilling the ranking to %s", self._held, self._path)
        # One language at a time, in flush-sized slices, popping each heap as it is written, so
        # moving the rows to disk never holds a second copy of them.
        for lang in list(self._heaps):
            h = self._heaps.pop(lang)
            for i in range(0, len(h), _SPILL_FLUSH):
                self._buf = [
                    (-it[2], lang, it[0], it[1], it[3], it[4], it[5], it[6])
                    for it in h[i:i + _SPILL_FLUSH]
                ]
                self._flush()
        self._held = 0

    def _flush(self) -> None:
        if self._buf and self._con is not None:
            self._con.execute("BEGIN")
            self._con.executemany("INSERT INTO kw VALUES (?,?,?,?,?,?,?,?)", self._buf)
            self._con.execute("COMMIT")
            self._buf = []

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
            (lang, self._hi - self._lo, self._lo),
        )

    def close(self) -> None:
        con, self._con = self._con, None
        if con is not None:
            try:
                con.close()
            finally:
                if self._path is not None:
                    for suffix in ("", "-journal", "-wal", "-shm"):
                        with contextlib.suppress(OSError):
                            os.unlink(str(self._path) + suffix)

    def __enter__(self) -> Ranker:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# --------------------------------------------------------------------------- the scan


#: What the single-file / digest form of the export holds per keyword it exports, at its peak:
#: the survivor row, its metadata and language signature, the digests' items and the families'
#: grouping (MEASURED on the digest path at 15,000-30,000 exported keywords: 2.2-2.5 KB each;
#: ``test_export_entry_constant_matches_the_measured_size`` fails if it drifts).
EXPORT_ENTRY_BYTES = 2500

#: The rest of the export's rise in resident memory that does not scale with the corpus: the
#: SQLite page cache, the accumulators, the interpreter's own growth. MEASURED: a digest over
#: 13 languages x 5,000 keywords rose the process by 190 MB at 2 M keywords and 195 MB at 6 M,
#: of which the per-keyword part above is ~160 MB.
EXPORT_FIXED_BYTES = 60 * 2**20

#: Bytes per article while the language/source arrays are dense (an ``I`` and a ``q``), and
#: per article when the ids are too sparse for that and two dicts stand in (measured ~100 each).
_ARRAY_BYTES_PER_ID = 12
_SPARSE_BYTES_PER_ARTICLE = 200


def estimate_export_need(db, *, per_language: int) -> dict[str, Any]:
    """What one export over THIS database is expected to add to the process, from its own counts.

    ``per_language`` is the window the export is asked for per language (the digest and the
    JSON stream use the classic 5,000). The estimate is the fixed part, plus one keyword's cost
    times the keywords that can be exported (at most ``per_language`` for each language and never
    more than the keyword table holds), plus the article arrays (12 bytes per article id) and
    the keyword mark (a byte per id). The ranker is NOT in it: its heaps are bounded by a share
    of the memory available at the start and spill to disk past that, so it cannot be what
    makes the export too big for the machine.

    Four cheap reads (two index scans and two aggregates); ``None`` for a count that cannot be
    read is treated as zero by the caller's fallback, never guessed.
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
    need = EXPORT_FIXED_BYTES + entries * EXPORT_ENTRY_BYTES + article_bytes + (max_kid + 1)
    return {
        "need_mb": need / 2**20,
        "articles": n_art,
        "keyword_id_bound": max_kid,
        "languages": languages,
        "exportable_keywords": entries,
        "per_language": per_language,
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
