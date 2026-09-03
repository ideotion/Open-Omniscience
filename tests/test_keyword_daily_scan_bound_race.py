"""PR-D / W2: the ``scan_bound`` composite-(created_at, id)-keyset fix for
``build_keyword_daily`` -- deterministic, EXPLICIT-timestamp reproductions of the two HIGH
parity findings a mandatory 4-lens adversarial skeptic matrix raised against the W1 fix.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY EXPLICIT TIMESTAMPS, NOT ``datetime.now(UTC)`` FOR THE CONCURRENT WRITE: an earlier
standalone probe of this exact fix used ``datetime.now(UTC)`` for the "concurrent" writer's
``created_at``, relying on real wall-clock separation from the scan's own ``scan_bound``
capture. On a fast local run (a tempfile SQLite DB, no real network/disk latency) the whole
scenario -- 10+ inserts, several SELECTs, one DELETE+INSERT -- can execute inside a single
clock tick, so the "concurrent" row's timestamp can TIE (or, on a coarser-resolution clock,
even precede) the scan_bound it is supposed to postdate. A tie silently degenerates the
composite-(created_at, id) ordering back into a PURE id ordering (since every row shares the
same ``created_at``) -- exactly the bug shape the fix exists to prevent -- so a
real-time-dependent test can pass or fail by luck of the scheduler, not by testing the fix.
These tests instead construct every ``created_at`` explicitly (``_BASE + N seconds``), so the
scan_bound / cursor / concurrent-write ordering is fully deterministic and reproduces the
EXACT interleaving the skeptic matrix described, every run.

REAL SQLITE ROWID SEMANTICS RELIED ON (empirically confirmed earlier in this project; see
CLAUDE.md's SQLCipher/ROWID-reuse lessons): for a plain ``INTEGER PRIMARY KEY`` (no
``AUTOINCREMENT``), a row inserted WITHOUT an explicit id gets ``(SELECT MAX(rowid))+1`` from
the table's CURRENT state. So deleting a MIDDLE row (not holding the table's current max id)
and reinserting produces a NEW, HIGHER id (the double-count shape: the mention was already
read once at its old id, then reappears at a fresh higher id in a later batch). Deleting the
row that IS the current max and reinserting REUSES that exact freed id (the drop shape: the
new row lands BEHIND the scan's already-advanced cursor).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, insert, text
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar
from src.database import session as db_session
from src.database.models import Article, Base, Keyword, KeywordMention, Source


def _columnar_engine_available() -> bool:
    """The SOURCE OF TRUTH for "can ``columnar.connect()`` hand back a connection".

    Deliberately mirrors ``columnar.connect``'s OWN guard (columnar.py) rather than
    probing ``duckdb_available()`` alone: that function answers "is the optional
    ``duckdb`` extra importable", while ``connect()`` returns ``None`` for a SECOND
    reason too -- the ``OO_COLUMNAR=0`` operator kill switch. A guard that reads only
    half the condition skips honestly on a core install and then fails on an operator
    who turned the engine off, which is the same defect wearing a different hat.
    """
    return columnar.duckdb_available() and os.getenv("OO_COLUMNAR") != "0"


needs_columnar = pytest.mark.skipif(
    not _columnar_engine_available(),
    reason=(
        "the derived columnar engine is unavailable (the optional `duckdb` extra is "
        "absent, or OO_COLUMNAR=0), so `columnar.connect()` honestly returns None and "
        "there is no store to build -- see test_connect_degrades_honestly_when_the_"
        "engine_is_unavailable, which RUNS in that configuration"
    ),
)


def test_connect_degrades_honestly_when_the_engine_is_unavailable():
    """The NEGATIVE-SPACE twin of the skip guard above -- and it must RUN on a core
    install, which is the whole point: a `skipif` alone is a mute button, asserting
    nothing about the configuration it skips in.

    ``columnar.connect``'s own docstring promises it returns ``None`` when the engine
    is unavailable "so the caller falls back to the live query". That promise is the
    reason the scan-bound tests below may skip rather than fail, so it is asserted
    here rather than assumed.
    """
    con = columnar.connect(passphrase=None)
    if _columnar_engine_available():
        assert con is not None, (
            "duckdb is importable and OO_COLUMNAR is not 0, so connect() must hand "
            "back a real connection -- a None here would mean the engine failed for "
            "some THIRD reason the skip guard cannot see, and the tests below would "
            "then skip while silently hiding it"
        )
        con.close()
    else:
        assert con is None, (
            "the engine is unavailable, so connect() must degrade to None rather than "
            "raise or hand back a half-built connection -- this is the contract its "
            "own docstring states, and the tests below rely on it to skip honestly"
        )


_BASE = datetime(2024, 1, 1, tzinfo=UTC)


def _ts(n: int) -> datetime:
    """The n-th deterministic, well-separated timestamp (BASE + n seconds)."""
    return _BASE + timedelta(seconds=n)


def _fresh_engine(db_path: Path):
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    event.listen(eng, "connect", db_session._sqlite_pragmas)
    Base.metadata.create_all(eng)
    return eng


def _seed_articles_and_source(session, n: int) -> None:
    session.add(Source(name="S", domain="s.test"))
    session.commit()
    for i in range(1, n + 1):
        session.add(Article(
            url=f"https://s.test/{i}", canonical_url=f"https://s.test/{i}", source_id=1,
            title="T", content="c", hash=f"h{i}", language="en",
            created_at=datetime.now(UTC),
        ))
    session.commit()


def _mention(keyword_id: int, article_id: int, ts: datetime, *, count: int = 1):
    return insert(KeywordMention).values(
        keyword_id=keyword_id, article_id=article_id, count=count,
        observed_on=date(2024, 1, 1), created_at=ts,
    )


def _trigger_write_before_batch(scanner, writer, *, batch_n: int, write_fn):
    """Monkeypatch ``scanner.execute`` so ``write_fn(writer)`` runs -- and commits --
    exactly once, immediately BEFORE the ``batch_n``-th DATED BATCH query of
    ``build_keyword_daily``'s scan reaches the real database. Deterministic, no
    threads, no real-time race.

    ANCHORED ON THE QUERY SHAPE, not on a call ordinal. This used to count EVERY
    ``scanner.execute`` call and take the ``call_n``-th, which coincided with the
    intended batch only for one particular sequence of statements: S3.5 split the
    scan into a NULL-created_at phase and a dated phase, so the dated scan's first
    batch moved from call 2 to call 3 and a ``call_n=3`` trigger began firing
    BEFORE any row had been read. The tests then measured the accepted
    deleted-before-the-cursor-reached-it residual instead of the double-count they
    are named for -- a stale landmark, not a behaviour change. Matching the dated
    batch's own SQL cannot drift that way.
    """
    real_execute = scanner.execute
    seen = {"n": 0}

    def _is_dated_batch(stmt) -> bool:
        # NEVER `or ""` here: a SQLAlchemy clause raises TypeError from __bool__.
        raw = getattr(stmt, "text", None)
        sql = raw if isinstance(raw, str) else str(stmt)
        return "keyword_mentions" in sql and "LIMIT" in sql and "created_at IS NOT NULL" in sql

    def patched(stmt, *a, **kw):
        if _is_dated_batch(stmt):
            seen["n"] += 1
            if seen["n"] == batch_n:
                write_fn(writer)
        return real_execute(stmt, *a, **kw)

    scanner.execute = patched  # type: ignore[method-assign]
    return lambda: setattr(scanner, "execute", real_execute)  # restore hook


@needs_columnar
def test_a_row_already_read_that_is_deleted_and_reinserted_to_a_higher_id_is_never_double_counted(
    tmp_path,
):
    """PARITY FINDING #1 (HIGH): a mention already streamed in an EARLY batch, then
    deleted-and-reinserted (a genuine SQLite re-index idiom -- see index_article) to a fresh,
    HIGHER id DURING the same scan, must be counted EXACTLY ONCE by this build -- never once
    at its old id AND again at its new id.

    Setup: 6 mentions (keyword_id=1, article_id=1..6), created_at = BASE+1s..+6s, so
    scan_bound (captured once, before the loop) = BASE+6s. batch_size=3 -> batch1 reads
    ids {1,2,3} (article 2 already streamed here). Immediately before batch2 fires, article
    2's mention is deleted (freeing a MIDDLE id, so the reinsert gets a fresh id=7, NOT a
    reused low id) and reinserted with created_at=BASE+7s -- strictly AFTER scan_bound, the
    real invariant a genuinely concurrent write satisfies (it commits only after the scan
    already captured its boundary). The fix must exclude id=7 from THIS build regardless of
    it being numerically greater than every cursor the scan will ever reach.

    THE DISCRIMINATING ASSERTION: keyword_daily's ``mentions`` is SUM(count) over the STAGED
    rows (never deduplicated by article_id -- see columnar.py's GROUP BY), while
    ``articles_on_day`` is COUNT(DISTINCT article_id) (deduplicated). A double-count bug
    stages TWO rows for article_id=2 (old id=2 in batch1, reinserted id=7 in a later batch)
    -> mentions=7 while articles stays 6 (the duplicate dedupes on article_id in the DISTINCT
    count, but not in the SUM). The old, pre-W2 pure id>cursor keyset would have shown exactly
    this: batch2 (id>3) reads {4,5,6}; batch3 (id>6) would then ALSO read the reinserted {7}
    -- an id-only scan cannot see that id=7 postdates the scan's own start.
    """
    db_path = tmp_path / "double_count.db"
    eng = _fresh_engine(db_path)
    Session = sessionmaker(bind=eng, future=True)
    scanner = Session()
    writer = Session()

    scanner.add(Keyword(id=1, term="k1", normalized_term="k1"))
    scanner.commit()
    _seed_articles_and_source(scanner, 6)
    for i in range(1, 7):
        scanner.execute(_mention(1, i, _ts(i)))
    scanner.commit()

    # Sanity: KeywordMention ids landed 1..6 in insertion order (the test's own assumption,
    # verified rather than trusted blindly).
    ids_before = [
        r[0] for r in writer.execute(text("SELECT id FROM keyword_mentions ORDER BY id")).fetchall()
    ]
    assert ids_before == [1, 2, 3, 4, 5, 6]

    def _concurrent_reindex(w):
        # article_id=2's mention is deleted (a MIDDLE id -> the reinsert gets a fresh,
        # HIGHER id, never id=2 back) then reinserted with a created_at strictly after
        # scan_bound (BASE+6s) -- the real property a scan-started-before-this-commit write
        # always has.
        w.execute(text("DELETE FROM keyword_mentions WHERE article_id=2"))
        w.execute(_mention(1, 2, _ts(7)))
        w.commit()

    restore = _trigger_write_before_batch(scanner, writer, batch_n=2, write_fn=_concurrent_reindex)
    try:
        con = columnar.connect(passphrase=None)
        tally = columnar.build_keyword_daily(session=scanner, con=con, batch_size=3)
    finally:
        restore()

    new_id = writer.execute(
        text("SELECT id FROM keyword_mentions WHERE article_id=2")
    ).scalar()
    assert new_id == 7, f"the reinsert must land on a fresh higher id, not a reused one: {new_id}"

    roll = columnar.windowed_term_counts(con)
    assert roll == {1: (6, 6)}, (
        f"DOUBLE-COUNT: expected exactly 6 mentions / 6 distinct articles (article 2 counted "
        f"once, via its ORIGINAL id, read before the concurrent write); got {roll}"
    )
    assert tally["streamed_mentions"] == 6
    live_rows = writer.execute(text("SELECT COUNT(*) FROM keyword_mentions")).scalar()
    assert live_rows == 6, "the live table still holds 6 rows (1 deleted, 1 reinserted)"

    scanner.close()
    writer.close()
    eng.dispose()


@needs_columnar
def test_a_reinsert_that_reuses_a_freed_max_id_is_excluded_this_build_but_self_corrects_on_the_next(
    tmp_path,
):
    """PARITY FINDING #2 (HIGH, the sibling DROP direction): deleting the row that IS the
    table's CURRENT max id, then reinserting (SQLite reuses that exact freed id for a fresh
    row with no explicit id given), must NEVER let the reinsert be silently read at the wrong
    position by a scan already in flight -- and the excluded mention must NOT be lost forever:
    a later, fresh rebuild (its OWN fresh scan_bound) must pick it up.

    Setup: 6 mentions (keyword_id=1, article_id=1..6), created_at = BASE+1s..+6s, so
    scan_bound = BASE+6s. Immediately before batch2 fires (after batch1 has already read
    ids {1,2,3}), article 6's mention (id=6, the table's CURRENT max) is deleted and a
    DIFFERENT keyword's mention (keyword_id=2, article_id=6, count=9 -- a distinguishing
    payload) is inserted with created_at=BASE+7s (after scan_bound). Because id=6 was just
    freed AND was the max, the new row is assigned id=6 -- REUSING an id the scan's cursor has
    not yet reached (cursor is still at id=3 when the write lands).

    An id-only keyset (id > cursor) would read this reused id=6 as if it were the ORIGINAL
    row -- silently substituting a keyword_id=2/count=9 mention, written AFTER the scan
    started, for the keyword_id=1 mention that legitimately existed when the scan began and
    was deleted before the cursor reached it. The composite-key fix excludes it from THIS
    build (its created_at postdates scan_bound) -- and a FRESH build afterwards (a new
    scan_bound capturing the post-write state) proves it was deferred, not dropped.
    """
    db_path = tmp_path / "reused_id_drop.db"
    eng = _fresh_engine(db_path)
    Session = sessionmaker(bind=eng, future=True)
    scanner = Session()
    writer = Session()

    scanner.add(Keyword(id=1, term="k1", normalized_term="k1"))
    scanner.add(Keyword(id=2, term="k2", normalized_term="k2"))
    scanner.commit()
    _seed_articles_and_source(scanner, 6)
    for i in range(1, 7):
        scanner.execute(_mention(1, i, _ts(i)))
    scanner.commit()

    def _concurrent_write(w):
        # article 6's mention IS the table's current max id -> deleting it frees id=6 for
        # reuse by the very next no-explicit-id insert (real SQLite rowid semantics).
        w.execute(text("DELETE FROM keyword_mentions WHERE article_id=6"))
        w.execute(_mention(2, 6, _ts(7), count=9))
        w.commit()

    restore = _trigger_write_before_batch(scanner, writer, batch_n=2, write_fn=_concurrent_write)
    try:
        con = columnar.connect(passphrase=None)
        columnar.build_keyword_daily(session=scanner, con=con, batch_size=3)
    finally:
        restore()

    reused_id = writer.execute(
        text("SELECT id FROM keyword_mentions WHERE article_id=6 AND keyword_id=2")
    ).scalar()
    assert reused_id == 6, f"the reinsert must REUSE the freed max id: got {reused_id}"

    roll = columnar.windowed_term_counts(con)
    # keyword_id=1: only the 5 SURVIVING original mentions (article 6's original mention was
    # legitimately deleted mid-scan -- excluded from this build, the documented, accepted
    # residual; NEVER re-read via the reused id).
    assert roll.get(1) == (5, 5), f"keyword_id=1 should show exactly its 5 surviving mentions: {roll}"
    # keyword_id=2 must be ABSENT ENTIRELY from this build -- not present with a wrong count,
    # not silently substituted in place of keyword_id=1's deleted mention.
    assert 2 not in roll, f"the reused-id reinsert must be excluded from THIS build entirely: {roll}"

    # SELF-CORRECTION: a later, independent rebuild (its own fresh scan_bound, capturing the
    # now-settled post-write state) must pick up the deferred mention -- proving exclusion,
    # not permanent loss.
    con2 = columnar.connect(passphrase=None)
    columnar.build_keyword_daily(session=scanner, con=con2, batch_size=3)
    roll2 = columnar.windowed_term_counts(con2)
    assert roll2.get(1) == (5, 5), "keyword_id=1 is unchanged by the later rebuild"
    assert roll2.get(2) == (9, 1), (
        f"a later rebuild must surface the deferred mention (count=9, 1 article): {roll2}"
    )

    scanner.close()
    writer.close()
    eng.dispose()


@needs_columnar
def test_watermark_reflects_the_true_max_id_even_when_the_tail_rows_are_all_undated(tmp_path):
    """TRANSACTIONAL-SEMANTICS FINDING #2 (MEDIUM): ``last_mention_id`` must track the TRUE
    max mention id seen this build, including UNDATED rows (``observed_on IS NULL``) that sit
    at the id tail -- an undated row is excluded from ``keyword_daily`` staging (it carries no
    day to bucket into) but must still advance the watermark, or a future incremental refresh
    would permanently re-scan the id range it silently skipped.
    """
    db_path = tmp_path / "watermark_undated_tail.db"
    eng = _fresh_engine(db_path)
    Session = sessionmaker(bind=eng, future=True)
    s = Session()

    s.add(Keyword(id=1, term="k1", normalized_term="k1"))
    s.commit()
    _seed_articles_and_source(s, 5)
    # ids 1-3: dated (staged). ids 4-5: UNDATED (observed_on=None) -- inserted LAST, so they
    # hold the highest ids, exactly the tail-under-report scenario.
    for i in range(1, 4):
        s.execute(_mention(1, i, _ts(i)))
    s.commit()
    for i in range(4, 6):
        s.execute(insert(KeywordMention).values(
            keyword_id=1, article_id=i, count=1, observed_on=None, created_at=_ts(i),
        ))
    s.commit()

    true_max_id = s.execute(text("SELECT MAX(id) FROM keyword_mentions")).scalar()
    assert true_max_id == 5

    con = columnar.connect(passphrase=None)
    tally = columnar.build_keyword_daily(session=s, con=con, batch_size=2)

    assert tally["last_mention_id"] == true_max_id, (
        f"watermark under-reports: {tally['last_mention_id']} != {true_max_id}"
    )
    assert tally["streamed_mentions"] == 3, "only the 3 DATED rows are staged into keyword_daily"

    s.close()
    eng.dispose()
