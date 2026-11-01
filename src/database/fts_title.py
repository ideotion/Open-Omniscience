"""The instant title index: a small prefix-searchable FTS5 table over article TITLES only.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY IT EXISTS (docs: /mnt/project-files/perf-5tb/DECISION.md, measured 2026-11-01 on a synthetic
corpus). The omnibar's article search is ``MATCH 'inf*' ORDER BY bm25(...)`` on an index with no
prefix tables, so the engine must read and score EVERY matching document before it can return ten:
4.2 s p50 for one typed character at 1 M documents, growing with the corpus. A second, titles-only
index with ``prefix='1 2 3 4'`` read newest-first (``ORDER BY rowid DESC LIMIT n``) lets FTS5 stop
after ``n`` hits whatever the corpus size: 0.2-0.4 ms p50 from 200 k to 3 M documents. Titles are
short, so the prefix tables cost ~0.14 KB a document (a body prefix index costs 167 % of the text,
which is why bodies do not get one).

WHAT IT IS NOT. It is NOT relevance ranking: the answer is "the newest articles whose title starts
with what you typed", and every surface that shows it says so. "Newest" is highest ``articles.id``
(ingest order), not publication date: FTS5 walks rowids in order, which is what makes the early stop
possible. ``ORDER_SQL`` is the ONE place that decides the order, so the choice can be swapped.

SHAPE. ``article_fts_title`` is CONTENTLESS with ``contentless_delete=1`` (SQLite >= 3.43): a delete
is by rowid and needs none of the original values, so unlike ``article_fts`` it needs no record of
"exactly what was indexed". The name starts with ``article_fts`` on purpose: the backup, the stream
backup and the merge already skip every table so named (a derived, rebuildable index is never
shipped), and ``article_fts_title_state`` rides under the same rule.

TEXT IS INDEXED THE WAY THE MAIN INDEX INDEXES IT: the same ``oo_fts_*`` SQL functions the
``article_fts_*`` triggers call fold Arabic and segment Chinese/Japanese, and the query takes the
same ``fts_norm.query_variants`` forms, so a title the main index finds is a title this finds
(``tests/test_fts_title.py`` pins the parity). A prefix over Chinese or Japanese text matches the
index as typed, not re-segmented: the same limit the main index's prefix search states.

NEVER BUILT AT BOOT. ``ensure_title_index`` creates the table, the state row and the three sync
triggers and nothing else (the P0.4 lesson: an unlock that rebuilt an index took 981-1,645 s).
History is filled by ``backfill_step``, a bounded, resumable step the background job calls; until it
reaches the end, ``status()`` says how many articles the index covers and the surface says so.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import text

from src.database.fts import FTS_TOKENIZER, _quote, _string_forms, _tokenize_clause
from src.database.fts_norm import query_variants, search_fold

_LOG = logging.getLogger(__name__)

TABLE = "article_fts_title"
STATE_TABLE = "article_fts_title_state"

#: The ordering of an answer. FTS5 walks a doclist in rowid order, so ``rowid DESC`` is what lets
#: it stop after ``LIMIT`` hits. Any other order needs every match first (the measured 4 s).
ORDER_SQL = "ORDER BY rowid DESC"

#: A typed query longer than this many characters is cut; more words than this are ignored.
#: Both bound the work a keystroke can ask for (a pasted paragraph is not a keystroke).
MAX_QUERY_CHARS = 120
MAX_WORDS = 6

#: The longest prefix the index holds a table for (``prefix='1 2 3 4'``). A prefix LONGER than this is not
#: looked up: FTS5 merges the doclists of every word it could complete into, which is the whole doclist of a
#: frequent word (measured: ~20-30 ms at 1 M titles for the title's commonest word, growing with the corpus).
#: Such a prefix is first expanded to the whole words in the index that start with it, and those are searched
#: as exact words (0.15 ms, stopping after the first hits). More than this many completions and the prefix is
#: searched as a prefix after all: an honest slow answer, never a silently partial one.
INDEXED_PREFIX_MAX = 4
EXPAND_MAX_TERMS = 64

#: Titles per backfill batch, and the time one ``backfill_step`` may hold the writer.
BACKFILL_BATCH = 2000
BACKFILL_STEP_BUDGET_S = 0.75

#: The expression BOTH the triggers and the backfill index a title with, so the two cannot
#: disagree. ``oo_fts_used(title, NULL, caps)`` is the part of the connection's capabilities that
#: changes this title; ``oo_fts_norm`` applies it. ``{row}`` is ``new`` in a trigger and ``a`` in
#: the backfill's SELECT.
_TITLE_EXPR = "oo_fts_norm({row}.title, oo_fts_used({row}.title, NULL, oo_fts_caps()))"


def _ddl() -> list[str]:
    return [
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {TABLE} USING fts5(
            title,
            content='', contentless_delete=1,
            {_tokenize_clause(FTS_TOKENIZER)},
            prefix='1 2 3 4'
        )
        """,
        # The term dictionary of the index, read through a view with no storage of its own. It answers
        # "which words start with these five letters" so a long prefix can be searched as whole words.
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {TABLE}_vocab USING fts5vocab({TABLE}, 'row')",
        # One row (id 1): where the backfill stopped, and the highest article id it must reach.
        # Articles above ``frozen_max`` are indexed by the trigger, so the backfill is finite.
        f"""
        CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cursor INTEGER NOT NULL,
            frozen_max INTEGER NOT NULL,
            done INTEGER NOT NULL
        )
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS {TABLE}_ai AFTER INSERT ON articles
        WHEN new.title IS NOT NULL BEGIN
            INSERT OR REPLACE INTO {TABLE}(rowid, title) VALUES (new.id, {_TITLE_EXPR.format(row="new")});
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS {TABLE}_ad AFTER DELETE ON articles BEGIN
            DELETE FROM {TABLE} WHERE rowid = old.id;
        END
        """,
        # Column-scoped for the reason article_fts_au is (tests/test_fts_update_trigger_scope.py):
        # the re-index stamps other columns on every pass and must not re-index the title for it.
        f"""
        CREATE TRIGGER IF NOT EXISTS {TABLE}_au AFTER UPDATE OF title ON articles BEGIN
            DELETE FROM {TABLE} WHERE rowid = old.id;
            INSERT INTO {TABLE}(rowid, title)
            SELECT new.id, {_TITLE_EXPR.format(row="new")} WHERE new.title IS NOT NULL;
        END
        """,
    ]


def ensure_title_index(conn) -> None:
    """Create the table, the state table and the three sync triggers. Idempotent, O(1), and it
    never reads an article: the caller owns the transaction (``ensure_fts`` runs it inside its
    own). The connection needs the ``oo_fts_*`` functions, as it does for the main index."""
    for ddl in _ddl():
        conn.execute(text(ddl))


def _present(conn) -> bool:
    return conn.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": TABLE}).fetchone() is not None


def _state(conn) -> tuple[int, int, bool] | None:
    row = conn.execute(text(f"SELECT cursor, frozen_max, done FROM {STATE_TABLE} WHERE id = 1")).fetchone()  # nosec B608 - module constant
    return None if row is None else (int(row[0]), int(row[1]), bool(row[2]))


def backfill_step(conn, *, budget_s: float = BACKFILL_STEP_BUDGET_S, batch: int = BACKFILL_BATCH) -> dict[str, Any]:
    """Index one bounded slice of history; the caller owns the transaction and the writer gate.

    The first call freezes ``frozen_max`` (the highest article id now); later calls resume from
    ``cursor``. Re-indexing a title the trigger already indexed is harmless (INSERT OR REPLACE).
    Returns ``{"done", "cursor", "frozen_max", "indexed"}``; ``done`` is True once the cursor has
    reached ``frozen_max`` (or there was nothing to index)."""
    st = _state(conn)
    if st is None:
        top = conn.execute(text("SELECT COALESCE(max(id), 0) FROM articles")).scalar() or 0
        conn.execute(
            text(f"INSERT INTO {STATE_TABLE}(id, cursor, frozen_max, done) VALUES (1, 0, :m, :d)"),  # nosec B608 - module constant
            {"m": int(top), "d": 1 if int(top) == 0 else 0},
        )
        st = (0, int(top), int(top) == 0)
    cursor, frozen_max, done = st
    indexed = 0
    deadline = time.monotonic() + budget_s
    while not done:
        # The last id of this batch: one index-only probe (articles.id is the rowid), so the batch is an
        # exact id range and the INSERT ... SELECT below reads each title once.
        upper = conn.execute(
            text("SELECT id FROM articles WHERE id > :c AND id <= :m ORDER BY id LIMIT 1 OFFSET :o"),
            {"c": cursor, "m": frozen_max, "o": max(0, batch - 1)},
        ).scalar()
        upper = frozen_max if upper is None else int(upper)
        res = conn.execute(
            text(
                f"INSERT OR REPLACE INTO {TABLE}(rowid, title) "  # nosec B608 - module constants only; the range is bound
                f"SELECT a.id, {_TITLE_EXPR.format(row='a')} FROM articles a "
                "WHERE a.id > :c AND a.id <= :u AND a.title IS NOT NULL"
            ),
            {"c": cursor, "u": upper},
        )
        indexed += int(res.rowcount or 0)
        cursor = upper
        done = cursor >= frozen_max
        conn.execute(
            text(f"UPDATE {STATE_TABLE} SET cursor = :c, done = :d WHERE id = 1"),  # nosec B608 - module constant
            {"c": cursor, "d": 1 if done else 0},
        )
        if time.monotonic() >= deadline:
            break
    return {"done": done, "cursor": cursor, "frozen_max": frozen_max, "indexed": indexed}


def mark_behind(con, prev_max_id: int) -> None:
    """Record that rows above ``prev_max_id`` were bulk-inserted with the title trigger suspended (a merge),
    so the backfill must cover them. Raw DB-API connection (the merge's own), the caller's transaction.
    Does nothing when no backfill state exists: a never-built index is built from scratch anyway."""
    row = con.execute(f"SELECT cursor, done FROM {STATE_TABLE} WHERE id = 1").fetchone()  # nosec B608 - module constant
    if row is None:
        return
    top = int(con.execute("SELECT COALESCE(max(id), 0) FROM articles").fetchone()[0])
    cursor = int(prev_max_id) if row[1] else min(int(row[0]), int(prev_max_id))
    con.execute(
        f"UPDATE {STATE_TABLE} SET cursor = ?, frozen_max = ?, done = 0 WHERE id = 1",  # nosec B608 - module constant
        (cursor, top),
    )


def reset(conn) -> None:
    """Forget the whole title index and start its backfill over (the repair path: a damaged or doubtful index is
    rebuilt from the articles, which are never touched). The caller owns the transaction."""
    conn.execute(text(f"INSERT INTO {TABLE}({TABLE}) VALUES('delete-all')"))  # nosec B608 - module constant
    conn.execute(text(f"DELETE FROM {STATE_TABLE}"))  # nosec B608 - module constant


def status(conn) -> dict[str, Any]:
    """How much of the corpus the title index covers. Reads two counts, so it is for a status
    surface, never a keystroke. ``complete`` is only ever True when the backfill reached the end;
    a store whose index was never built reports ``covered`` of ``articles`` and ``complete`` False."""
    exists = conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": TABLE}
    ).fetchone()
    if not exists:
        return {"present": False, "complete": False, "covered": 0, "articles": 0}
    articles = int(conn.execute(text("SELECT count(*) FROM articles")).scalar() or 0)
    covered = int(conn.execute(text(f"SELECT count(*) FROM {TABLE}_docsize")).scalar() or 0)  # nosec B608 - module constant
    st = _state(conn)
    return {
        "present": True,
        "complete": bool(st and st[2]) and covered >= articles,
        "covered": covered,
        "articles": articles,
        "cursor": None if st is None else st[0],
        "frozen_max": None if st is None else st[1],
    }


def _completions(conn, word: str) -> list[str] | None:
    """The whole words in the index that start with ``word``, or None when this word is not expanded
    (short, not plain letters/digits, a form the main index also rewrites, or too many completions)."""
    if conn is None or len(word) <= INDEXED_PREFIX_MAX or not word.isalnum():
        return None
    folded = search_fold(word)
    if folded is None or folded != word.casefold() or any(not isinstance(v, str) or v != word for v in query_variants(word)):
        return None  # accents, Arabic or CJK: the index text was rewritten, leave it to the prefix path
    lo, hi = folded, folded[:-1] + chr(ord(folded[-1]) + 1)
    try:
        rows = conn.execute(
            text(f"SELECT term FROM {TABLE}_vocab WHERE term >= :lo AND term < :hi LIMIT :k"),  # nosec B608 - module constant
            {"lo": lo, "hi": hi, "k": EXPAND_MAX_TERMS + 1},
        ).fetchall()
    except Exception:  # noqa: BLE001 - no vocab view (an old store mid-upgrade): the prefix path still works
        return None
    terms = [str(r[0]) for r in rows]
    return terms if 0 < len(terms) <= EXPAND_MAX_TERMS else None


def build_match(query: str, conn=None) -> str | None:
    """The FTS5 MATCH for what the user has typed so far, or None when there is nothing to search.

    Every word but the last must occur as a whole word; the last is the one being typed, so it is
    a PREFIX. Every word leaves through ``_quote`` (punctuation reaches the tokenizer verbatim, so
    FTS5 syntax typed into the box is just text), and takes the same forms the main index's query
    takes (Arabic folded, a Chinese/Japanese string re-segmented for a whole word)."""
    q = " ".join((query or "")[:MAX_QUERY_CHARS].split())
    words = q.split(" ")[:MAX_WORDS] if q else []
    if not words:
        return None
    parts: list[str] = []
    for w in words[:-1]:
        forms = [_quote(f) if isinstance(f, str) else "NEAR(" + " ".join(_quote(x) for x in f) + ")" for f in query_variants(w)]
        parts.append(forms[0] if len(forms) == 1 else "(" + " OR ".join(forms) + ")")
    done = _completions(conn, words[-1])
    if done is not None:
        parts.append("(" + " OR ".join(_quote(t) for t in done) + ")")
    else:
        last = [_quote(f) + "*" for f in _string_forms(words[-1], query_variants)]
        parts.append(last[0] if len(last) == 1 else "(" + " OR ".join(last) + ")")
    return " AND ".join(parts)


def title_prefix_ids(conn, query: str, *, limit: int = 10, exclude_quarantined: bool = True) -> list[int]:
    """The ids of the newest articles whose title matches ``query`` (last word as a prefix).

    ``limit`` hits, or fewer when fewer exist; a caller that wants "more exist" asks for one extra.
    Quarantined articles are left out in SQL, as the main search leaves them (a NULL, never-judged
    row stays in). Returns [] for an empty query or an index that does not exist yet."""
    match = build_match(query, conn)
    if match is None or limit < 1:
        return []
    params: dict[str, Any] = {"q": match, "n": int(limit)}
    gate = (
        f" AND EXISTS (SELECT 1 FROM articles a WHERE a.id = {TABLE}.rowid AND a.quarantined IS NOT 1)"
        if exclude_quarantined
        else ""
    )
    sql = f"SELECT rowid FROM {TABLE} WHERE {TABLE} MATCH :q{gate} {ORDER_SQL} LIMIT :n"  # nosec B608 - TABLE/ORDER_SQL/gate are module constants; the query and limit are bound parameters
    try:
        rows = conn.execute(text(sql), params).fetchall()
    except Exception:  # noqa: BLE001 - a store whose index was never created answers nothing; any other failure is re-raised
        if not _present(conn):
            return []
        raise
    return [int(r[0]) for r in rows]
