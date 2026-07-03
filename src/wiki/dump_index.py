"""
Full-text search over downloaded Wikipedia dumps — a disposable, rebuildable index.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The gap this closes (standing REMAINING item): a downloaded ``pages-articles-multistream``
dump could be read one title at a time (:mod:`src.wiki.dumpread`), but its BODIES were not
full-text-searchable — the omnibar's Wikipedia group searched only watched-page titles +
the corpus articles synced from watched pages.

Design decision — a SEPARATE side-file index, NOT the corpus DB:
  A dump is public, local, re-downloadable data. Ingesting a whole edition into the
  encrypted corpus (as Article rows) would balloon the corpus by tens of GB, blow the
  encrypted-backup size, and entangle the watched-page corpus path. Instead we build a
  DISPOSABLE FTS5 index in its OWN plaintext SQLite file next to the dumps
  (``data_dir()/wiki_dumps/dump_index.sqlite``) — which is already EXCLUDED from every
  backup (``wiki_dumps/`` is re-downloadable) and rebuildable from the local dump at any
  time. The watched-page corpus path is therefore literally untouched: this adds a new
  file, a new endpoint group, and reuses only the pure ``build_match`` query parser from
  :mod:`src.database.fts` (same Boolean syntax + BM25F ranking as article search).

  Plaintext is honest here: the index holds only public Wikipedia page text that already
  sits as plaintext ``.bz2`` files right beside it — no corpus content, no secrets.

Honesty: a hit points at the dump title (openable via the local dump reader) — the body
is a snapshot as of the dump date, not the live article; results carry that note, and the
index reports which editions it covers + when it was built (never a stale silent index).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

_LOG = logging.getLogger(__name__)

_INDEX_NAME = "dump_index.sqlite"
# BM25F weights: a title hit is a stronger relevance signal than a body hit (mirrors the
# article-search default in src.database.fts._bm25_weights).
_TITLE_WEIGHT, _BODY_WEIGHT = 4.0, 1.0
_MIN_BODY_CHARS = 8  # skip redirect stubs / empty pages (their title is still not lost)

# One writer at a time for the whole index file (a build holds it); reads are lock-free
# (SQLite WAL). A build also checks a per-run stop flag so it can be cancelled.
_write_lock = threading.Lock()


def index_path(base_dir: Path | None = None) -> Path:
    """Where the disposable dump index lives (beside the dumps, excluded from backups)."""
    if base_dir is None:
        from src.paths import data_dir

        base_dir = data_dir() / "wiki_dumps"
    return Path(base_dir) / _INDEX_NAME


def _open(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS dump_pages USING fts5("
        "title, body, wiki UNINDEXED, pageid UNINDEXED, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dump_index_meta ("
        "wiki TEXT PRIMARY KEY, pages INTEGER NOT NULL, chars INTEGER NOT NULL, "
        "indexed_at TEXT NOT NULL)"
    )
    return conn


def _is_redirect(wikitext: str) -> bool:
    head = wikitext.lstrip()[:64].lower()
    # #REDIRECT is the English magic word; localized ones also start with '#'.
    return head.startswith("#redirect") or head.startswith("#") and "redirect" in head


def build_index(
    wiki: str,
    *,
    base_dir: Path | None = None,
    index_file: Path | None = None,
    batch: int = 500,
    limit: int | None = None,
    replace: bool = True,
    progress=None,
    should_stop=None,
) -> dict:
    """(Re)build the search index for one downloaded edition by streaming its dump.

    Streams every article-namespace page once (:func:`src.wiki.dumpread.iter_pages`),
    strips wikitext to plain text, and inserts ``(title, body, wiki, pageid)`` into the
    FTS5 index in ``batch``-sized commits. ``replace`` clears the edition's existing rows
    first (idempotent re-index). ``progress(pages_done)`` and ``should_stop() -> bool``
    (cancellation) are optional hooks. Returns ``{wiki, pages, chars, cancelled}``.
    """
    from src.wiki.corpus import plain_from_wikitext
    from src.wiki.dumpread import iter_pages
    from src.wiki.dumps import validate_wiki_code

    wiki = validate_wiki_code(wiki)
    path = index_file or index_path(base_dir)
    pages = 0
    chars = 0
    cancelled = False
    with _write_lock:
        conn = _open(path)
        try:
            if replace:
                conn.execute("DELETE FROM dump_pages WHERE wiki = ?", (wiki,))
                conn.commit()
            pending = 0
            for page in iter_pages(wiki, base_dir=base_dir, namespaces=(0,), limit=limit):
                if should_stop is not None and should_stop():
                    cancelled = True
                    break
                wikitext = page.get("wikitext") or ""
                if _is_redirect(wikitext):
                    continue
                body = plain_from_wikitext(wikitext)
                title = page.get("title") or ""
                if len(body) < _MIN_BODY_CHARS and not title:
                    continue
                conn.execute(
                    "INSERT INTO dump_pages (title, body, wiki, pageid) VALUES (?, ?, ?, ?)",
                    (title, body, wiki, page.get("pageid")),
                )
                pages += 1
                chars += len(body)
                pending += 1
                if pending >= batch:
                    conn.commit()
                    pending = 0
                    if progress is not None:
                        progress(pages)
            conn.commit()
            # Record coverage honestly (only when a full run completed, so a cancelled
            # partial build never masquerades as a complete edition index).
            if not cancelled:
                conn.execute(
                    "INSERT INTO dump_index_meta (wiki, pages, chars, indexed_at) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(wiki) DO UPDATE SET "
                    "pages=excluded.pages, chars=excluded.chars, indexed_at=excluded.indexed_at",
                    (wiki, pages, chars, datetime.now(UTC).isoformat()),
                )
                conn.commit()
            if progress is not None:
                progress(pages)
        finally:
            conn.close()
    return {"wiki": wiki, "pages": pages, "chars": chars, "cancelled": cancelled}


def clear_index(wiki: str | None = None, *, base_dir: Path | None = None,
                index_file: Path | None = None) -> dict:
    """Drop the index for one edition (or all editions if ``wiki`` is None)."""
    path = index_file or index_path(base_dir)
    if not path.exists():
        return {"cleared": 0, "wiki": wiki}
    with _write_lock:
        conn = _open(path)
        try:
            if wiki is None:
                conn.execute("DELETE FROM dump_pages")
                conn.execute("DELETE FROM dump_index_meta")
            else:
                from src.wiki.dumps import validate_wiki_code

                wiki = validate_wiki_code(wiki)
                conn.execute("DELETE FROM dump_pages WHERE wiki = ?", (wiki,))
                conn.execute("DELETE FROM dump_index_meta WHERE wiki = ?", (wiki,))
            conn.commit()
        finally:
            conn.close()
    return {"cleared": 1 if wiki else -1, "wiki": wiki}


def index_status(*, base_dir: Path | None = None, index_file: Path | None = None) -> dict:
    """Which editions are indexed, their page counts, and when they were built."""
    path = index_file or index_path(base_dir)
    if not path.exists():
        return {"editions": [], "total_pages": 0}
    conn = _open(path)
    try:
        rows = conn.execute(
            "SELECT wiki, pages, chars, indexed_at FROM dump_index_meta ORDER BY wiki"
        ).fetchall()
    finally:
        conn.close()
    editions = [
        {"wiki": w, "pages": p, "chars": c, "indexed_at": ts} for (w, p, c, ts) in rows
    ]
    return {"editions": editions, "total_pages": sum(e["pages"] for e in editions)}


def search(
    query: str,
    *,
    wiki: str | None = None,
    limit: int = 20,
    base_dir: Path | None = None,
    index_file: Path | None = None,
) -> dict:
    """Full-text search over indexed dump BODIES (same Boolean syntax as article search).

    Returns ranked hits ``{wiki, title, pageid, snippet}`` — each openable via the local
    dump reader. ``None`` FTS query (empty/positive-less) yields no items, honestly.
    """
    from src.database.fts import build_match

    path = index_file or index_path(base_dir)
    out: dict = {
        "query": query,
        "items": [],
        "wiki": wiki,
        "note": (
            "matches in your downloaded dump BODIES (a snapshot as of the dump date, "
            "not the live article) — open a result to read its wikitext"
        ),
    }
    if not path.exists():
        out["reason"] = "no-index"
        return out
    match = build_match(query)
    if match is None:
        return out
    lim = max(1, min(int(limit), 100))
    params: dict = {"q": match, "lim": lim}
    sql = (
        "SELECT wiki, title, pageid, "
        "snippet(dump_pages, 1, '[', ']', '…', 12) AS snip "
        "FROM dump_pages WHERE dump_pages MATCH :q "
    )
    if wiki:
        from src.wiki.dumps import validate_wiki_code

        params["w"] = validate_wiki_code(wiki)
        sql += "AND wiki = :w "
    sql += f"ORDER BY bm25(dump_pages, {_TITLE_WEIGHT}, {_BODY_WEIGHT}) LIMIT :lim"
    conn = _open(path)
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        _LOG.warning("dump FTS search failed for %r", query, exc_info=True)
        out["reason"] = "search-error"
        return out
    finally:
        conn.close()
    out["items"] = [
        {"wiki": w, "title": t, "pageid": pid, "snippet": snip}
        for (w, t, pid, snip) in rows
    ]
    return out


# --------------------------------------------------------------------------- #
# Background build manager — one edition indexed at a time, cancellable, pollable.
# --------------------------------------------------------------------------- #
class DumpIndexManager:
    """Runs a dump-index build on a worker thread so a request never blocks on the
    (potentially long) sweep. One build at a time; cancellable; status pollable —
    the same shape as the other job managers so the task manager can surface it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"  # idle | running | done | error | cancelled
        self._wiki: str | None = None
        self._pages = 0
        self._error: str | None = None

    def start(self, wiki: str, *, base_dir: Path | None = None) -> dict:
        from src.wiki.dumps import validate_wiki_code

        wiki = validate_wiki_code(wiki)
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("a dump index build is already running")
            self._stop.clear()
            self._state = "running"
            self._wiki = wiki
            self._pages = 0
            self._error = None
            t = threading.Thread(
                target=self._run, args=(wiki, base_dir), name="dump-index", daemon=True
            )
            self._thread = t
            t.start()
        return self.status()

    def _run(self, wiki: str, base_dir: Path | None) -> None:
        try:
            def _progress(n: int) -> None:
                self._pages = n

            result = build_index(
                wiki, base_dir=base_dir, progress=_progress, should_stop=self._stop.is_set
            )
            with self._lock:
                self._pages = result["pages"]
                self._state = "cancelled" if result["cancelled"] else "done"
        except Exception as exc:  # noqa: BLE001 - a build failure is reported, never crashes
            _LOG.warning("dump index build failed for %s", wiki, exc_info=True)
            with self._lock:
                self._state = "error"
                self._error = str(exc)

    def cancel(self) -> dict:
        self._stop.set()
        return self.status()

    def status(self, *, base_dir: Path | None = None) -> dict:
        with self._lock:
            active = {
                "state": self._state,
                "wiki": self._wiki,
                "pages": self._pages,
                "error": self._error,
                "running": self._thread is not None and self._thread.is_alive(),
            }
        return {"build": active, **index_status(base_dir=base_dir)}


_manager: DumpIndexManager | None = None


def get_manager() -> DumpIndexManager:
    global _manager
    if _manager is None:
        _manager = DumpIndexManager()
    return _manager
