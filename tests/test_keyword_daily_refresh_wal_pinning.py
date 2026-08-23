"""Regression test for PR-D / W1's fix-forward: the mandatory 4-lens adversarial
skeptic matrix's transactional-semantics finding #3 (MEDIUM).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DIAGNOSED BUG: ``refresh_keyword_daily``'s INCREMENTAL branch (the tail-only
merge that runs once a full ``build_keyword_daily`` has already established a
baseline) still used the pre-fix "hold one open cursor across a raw fetchmany
loop, no ``.close()``, no intervening ``session.commit()``" shape that PR-D / W1
was built to eliminate in ``build_keyword_daily`` itself: a SINGLE
``session.execute(...)`` at the top of the incremental scan, followed by a raw
``while True: chunk = result.fetchmany(batch_size)`` loop with nothing releasing
the WAL read-mark between batches. On a live corpus with a large tail, this pins
the WAL for the ENTIRE incremental scan's duration, not just its final moment.

WHY THIS TEST CHECKS *MID-SCAN*, NOT "right after the call returns" (an important
empirical correction found while designing this test -- recorded so it is never
re-litigated): a standalone probe confirmed that fully DRAINING a
``session.execute(...)`` Result via repeated ``fetchmany()`` calls down to a
natural EMPTY final chunk releases SQLite's WAL read-mark on its own, even with
NO explicit ``.close()`` and NO ``session.commit()`` ever issued. Since
``refresh_keyword_daily``'s own incremental loop structurally CANNOT return until
its ``while True: ... if not chunk: break`` loop has fully drained (there is no
early-return path), a test that checks the WAL state only AFTER the whole
function call returns would pass on BOTH the pre-fix and the fixed code --
demonstrating nothing. The REAL, field-diagnosed harm (docs/design/
AUTONOMOUS_SESSION_BRIEF_2026-07-26_HARDWARE_DIAGNOSTICS_COMPARISON.md §1) is that
a checkpoint attempted WHILE the multi-batch scan is still IN PROGRESS -- between
any two of its batches, before the whole scan finishes -- finds the WAL pinned for
the pre-fix code's ENTIRE scan duration (one continuous open transaction spanning
every batch), while the fixed code (which closes + commits after EACH batch)
lets such a mid-scan checkpoint succeed between any two batches. This test fires
the checkpoint attempt from that exact mid-scan vantage point, deterministically
and without threads, mirroring ``tests/test_keyword_daily_scan_bound_race.py``'s
``_trigger_write_before_call`` technique (call-counted monkeypatch on
``session.execute``, not a real-time race).

WHY THE TRIGGER COUNTS *BATCH* QUERIES SPECIFICALLY, NOT "the Nth execute() call
overall": the fixed code issues an EXTRA ``session.execute(...)`` before its batch
loop even starts (the ``scan_bound = MAX(created_at)`` capture, itself a
short-lived scalar query that self-closes) -- a call the pre-fix code never makes
at all. Counting raw call numbers would put the two code shapes' Nth calls at
different logical positions and could fire the checkpoint attempt too early (before
any batch has genuinely happened) or never at all. Filtering on the batch query's
own distinctive column list is a shape-agnostic anchor: it matches BOTH the
pre-fix code's single monolithic tail query AND the fixed code's per-batch
queries, so "the 2nd matching call" reliably means "immediately before batch 2
begins" on the fixed code -- and, just as importantly, NEVER FIRES AT ALL on the
pre-fix code (which never issues a second such query for one incremental refresh,
since it makes exactly one, covering the whole tail). A hook that never fires is
itself the demonstration of the bug: this test asserts a mid-scan checkpoint was
BOTH attempted and successful, so pre-fix code fails on the "attempted" half
alone, without ever depending on it accidentally reaching busy=1.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar
from src.database import session as db_session
from src.database.models import Article, Base, Keyword, KeywordMention, Source
from src.scheduler import hygiene
from src.scheduler.hygiene import checkpoint_wal

_JOURNAL_SIZE_LIMIT_MB = 1
_BASE = datetime(2024, 1, 1, tzinfo=UTC)
_BATCH_QUERY_ANCHOR = "keyword_id, observed_on, count, article_id"  # in BOTH code shapes' SQL


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
        "there is no store to refresh -- see test_connect_degrades_honestly_when_the_"
        "engine_is_unavailable, which RUNS in that configuration"
    ),
)


def test_connect_degrades_honestly_when_the_engine_is_unavailable():
    """The NEGATIVE-SPACE twin of the skip guard above -- and it must RUN on a core
    install, which is the whole point: a `skipif` alone is a mute button, asserting
    nothing about the configuration it skips in.

    ``columnar.connect``'s own docstring states the contract -- "Returns a DuckDB
    connection, or ``None`` when the engine is unavailable (duckdb absent /
    ``OO_COLUMNAR=0``) so the caller falls back to the live query." This pins BOTH
    directions of that sentence, so whichever configuration the lane runs in, one of
    the two branches genuinely exercises `connect()` rather than leaving it untested.
    """
    con = columnar.connect(passphrase=None)
    if _columnar_engine_available():
        assert con is not None, (
            "duckdb is importable and OO_COLUMNAR is not '0', so connect() must hand "
            "back a real connection -- returning None here would silently disable "
            "every columnar path on an install that HAS the engine"
        )
        con.close()
    else:
        assert con is None, (
            "the engine is unavailable, so connect() must return None for the caller "
            "to fall back to the live query -- anything else (a half-built object, a "
            "raised ImportError) breaks the documented degrade contract"
        )


def _ts(n: int) -> datetime:
    """The n-th deterministic, well-separated timestamp (BASE + n seconds)."""
    return _BASE + timedelta(seconds=n)


def _wal_engine(tmp_path, name="wal_kd_refresh.db"):
    """A REAL file-backed WAL database with a small journal_size_limit -- the SAME
    pattern ``tests/test_wal_reader_starvation.py``/``test_wal_multi_producer_drain.py``
    use, so ``OO_WAL_SIZE_LIMIT_MB`` (set per-test via monkeypatch) is honoured.
    """
    db = tmp_path / name
    eng = create_engine(f"sqlite:///{db}", future=True)
    event.listen(eng, "connect", db_session._sqlite_pragmas)
    Base.metadata.create_all(eng)
    return eng, db


def _mention(keyword_id: int, article_id: int, ts: datetime, *, count: int = 1):
    return insert(KeywordMention).values(
        keyword_id=keyword_id, article_id=article_id, count=count,
        observed_on=date(2024, 1, 1), created_at=ts,
    )


def _fresh_cadence(monkeypatch):
    """Reset checkpoint_wal's min-interval memory so this test decides for itself
    (mirrors tests/test_wal_reader_starvation.py's own helper)."""
    monkeypatch.setattr(hygiene, "_LAST_CKPT_MONO", None)


@needs_columnar
def test_a_checkpoint_attempted_between_two_batches_of_an_incremental_refresh_succeeds(
    tmp_path, monkeypatch
):
    """MUST FAIL on the unpatched (single monolithic-query) incremental shape: the
    checkpoint hook, keyed on the 2nd batch-shaped ``session.execute`` call, never
    fires at all (the pre-fix code makes exactly ONE such call for the whole tail),
    so this test's "a checkpoint was both attempted and successful mid-scan"
    assertion fails on the "attempted" half alone.

    PASSES on the fixed (per-batch, close+commit-between-batches) shape: batch 1's
    read is closed and committed before batch 2's query is even issued, so a
    checkpoint fired right before that 2nd query reaches the real database finds
    nothing pinning the WAL.
    """
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", str(_JOURNAL_SIZE_LIMIT_MB))
    _fresh_cadence(monkeypatch)

    eng, db_path = _wal_engine(tmp_path)
    Session = sessionmaker(bind=eng, future=True)
    session = Session()
    try:
        # -- seed a small baseline the FULL build will cover ------------------------ #
        session.add(Source(name="S", domain="s.test"))
        session.add(Keyword(id=1, term="k1", normalized_term="k1"))
        session.commit()
        for i in range(1, 3):
            session.add(Article(
                url=f"https://s.test/{i}", canonical_url=f"https://s.test/{i}",
                source_id=1, title="T", content="c", hash=f"h{i}", language="en",
                created_at=datetime.now(UTC),
            ))
        session.commit()
        session.execute(_mention(1, 1, _ts(1)))
        session.execute(_mention(1, 2, _ts(2)))
        session.commit()

        con = columnar.connect(passphrase=None)
        baseline = columnar.refresh_keyword_daily(con=con, session=session, corpus_epoch=1)
        assert baseline["mode"] == "full"

        # -- grow the TAIL: enough rows that batch_size=3 needs SEVERAL batches ------ #
        for i in range(3, 13):  # 10 tail articles/mentions -> 4 batches at batch_size=3
            session.add(Article(
                url=f"https://s.test/{i}", canonical_url=f"https://s.test/{i}",
                source_id=1, title="T", content="c", hash=f"h{i}", language="en",
                created_at=datetime.now(UTC),
            ))
        session.commit()
        for i in range(3, 13):
            session.execute(_mention(1, i, _ts(i)))
        session.commit()

        checkpoint_outcome: dict = {}
        real_execute = session.execute
        calls = {"batch_n": 0}

        def patched(stmt, *a, **kw):
            if _BATCH_QUERY_ANCHOR in str(stmt):
                calls["batch_n"] += 1
                if calls["batch_n"] == 2:
                    # Grow the WAL from a SEPARATE connection so there's genuinely
                    # something for the checkpoint to reclaim -- a checkpoint on an
                    # unchanged WAL trivially "succeeds" (busy=0) regardless of any
                    # pin, which would make this assertion vacuous.
                    with eng.connect() as c:
                        c.exec_driver_sql("INSERT INTO sources (name, domain) VALUES "
                                           "('grow', 'grow.test')")
                        c.exec_driver_sql(
                            "UPDATE sources SET name = randomblob(262144) "
                            "WHERE domain = 'grow.test'"
                        )
                        c.commit()
                    rec = checkpoint_wal(engine=eng, force=True, busy_timeout_ms=200)
                    checkpoint_outcome["rec"] = rec
            return real_execute(stmt, *a, **kw)

        session.execute = patched  # type: ignore[method-assign]
        try:
            tally = columnar.refresh_keyword_daily(
                con=con, session=session, corpus_epoch=1, batch_size=3
            )
        finally:
            session.execute = real_execute  # type: ignore[method-assign]

        assert tally["mode"] == "incremental"
        assert calls["batch_n"] >= 2, (
            "the incremental scan never reached a 2nd batch query -- the fixture "
            "seeded too few tail rows to force multiple batches"
        )
        rec = checkpoint_outcome.get("rec")
        assert rec is not None, (
            "no checkpoint was even ATTEMPTED mid-scan -- on the pre-fix shape, "
            "the whole tail is read via ONE session.execute() call, so a 2nd "
            "batch-shaped call (this test's trigger point) never happens at all"
        )
        assert rec["busy"] == 0, (
            "a checkpoint attempted between two batches of the incremental refresh "
            "must succeed (busy=0) -- busy=1 here means the scan is still holding "
            "ONE continuous open read transaction across batch boundaries instead "
            "of closing + committing between them"
        )
        assert rec["wal_bytes_after"] == 0, (
            "the checkpoint reported busy=0 but did not fully truncate the WAL -- "
            "expected a clean full checkpoint once nothing pins it"
        )

        # Sanity: the incremental refresh still produced correct output (this test
        # is about transactional shape, not correctness -- but a shape fix must
        # never silently break the merge).
        roll = columnar.windowed_term_counts(con)
        assert roll[1][0] == 12, f"expected 12 total mentions (2 baseline + 10 tail): {roll}"
    finally:
        session.close()
        eng.dispose()
