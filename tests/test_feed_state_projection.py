"""The per-feed fetch state is read as the columns each call site uses, never as the entity (entity-load sweep part 2, bundle B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``FeedFetchState`` carries two wide opaque strings (``etag`` up to 512, ``last_modified`` up to 128) that no reader of the whole table needs. Loading
86,000 states as entities (the Coverage subtab, and the collector's due-feed filter on every pass over every feed) cost 0.8-1.1 s and 141 MB of Python
allocation against 0.2 s and 34 MB as the four columns the loop reads (``keyword-lane/entity-load-sweep-part2-2026-10-27.md``). The answers are
pinned equal to what the entity path gave, and the statements are pinned to leave the validators out: a revert to ``query(FeedFetchState)`` fails here
on the statement and not on a stopwatch.

WHAT ELSE THE ENTITY LOAD DID, and why nothing is lost: it put the rows in the pass-level session's identity map. The workers fetch through their own
sessions (``session_scope()`` per worker in the runner), ``FeedFetchState`` has no relationship and no mapper-level load listener (the mapper
listeners of ``models.py`` are on ``Source`` and ``Article`` inserts and updates), and the session-level listeners (``do_orm_execute``,
``before_flush``, ``after_begin``) fire for a column query the same as for an entity query.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, FeedFetchState, Source
from src.ingest.pipeline import feed_is_due
from src.scheduler.coverage import tag_coverage
from src.scheduler.runner import _filter_due_feeds

_NOW = datetime.now(UTC)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(_conn, _cursor, statement, _params, _context, _many):  # noqa: ANN001
        statements.append(statement)

    s.statements = statements  # type: ignore[attr-defined]
    try:
        yield s
    finally:
        s.close()


def _seed(s) -> list[Source]:
    out = []
    for i in range(6):
        src = Source(name=f"s{i}", domain=f"s{i}.example", rss_url=f"https://s{i}.example/rss", tags="news" if i % 2 else "tech", enabled=True)
        s.add(src)
        s.flush()
        out.append(src)
    # 0: backed off for an hour; 1: backoff already over; 2: checked, no backoff; 3: error status; 4: never fetched; 5: checked long ago
    def ago(**kw):  # a naive UTC datetime, as the column stores it
        return (_NOW - timedelta(**kw)).replace(tzinfo=None)

    states = {
        0: {"skip_until": ago(hours=-1), "last_status": 200, "last_checked_at": ago(hours=1)},
        1: {"skip_until": ago(hours=1), "last_status": 304, "last_checked_at": ago(hours=2)},
        2: {"skip_until": None, "last_status": 200, "last_checked_at": ago(minutes=5)},
        3: {"skip_until": None, "last_status": 500, "last_checked_at": ago(minutes=9)},
        5: {"skip_until": None, "last_status": 200, "last_checked_at": ago(days=9)},
    }
    for i, cols in states.items():
        s.add(FeedFetchState(source_id=out[i].id, etag='W/"a-long-opaque-validator"', last_modified="Tue, 27 Oct 2026 07:00:00 GMT", **cols))
    s.commit()
    return out


def _feed_state_selects(s) -> list[str]:
    return [q for q in s.statements if "feed_fetch_state" in q.lower() and q.lstrip().upper().startswith("SELECT")]


def test_the_due_feed_filter_answers_what_the_entity_path_answered_and_selects_no_validators(db):
    sources = _seed(db)
    db.statements.clear()
    due, backed_off = _filter_due_feeds(db, list(sources))

    reference = {st.source_id: st for st in db.query(FeedFetchState)}  # the entity path, run after the statements are captured
    expected_due = [s for s in sources if not feed_is_due(reference.get(s.id))]
    assert backed_off == len(expected_due) == 1
    assert [s.id for s in due] == [s.id for s in sources if s not in expected_due]

    mine = _feed_state_selects(db)[0]
    assert "skip_until" in mine
    for wide in ("etag", "last_modified"):
        assert wide not in mine, f"the due-feed filter reads {wide}, which feed_is_due does not"


def test_the_coverage_loop_reads_four_columns_and_gives_the_same_buckets(db):
    _seed(db)
    db.statements.clear()
    out = tag_coverage(db)

    states = [q for q in _feed_state_selects(db) if "FROM feed_fetch_state" in q]
    assert states, "tag_coverage no longer reads the feed states"
    for wide in ("etag", "last_modified", "consecutive_unchanged"):
        assert wide not in states[0], f"tag_coverage reads {wide}, which the loop never uses"

    totals = out["totals"]
    assert totals["total"] == 6
    assert totals["reached"] == 5 and totals["never_reached"] == 1
    assert totals["backed_off"] == 1
    assert totals["status"]["error"] == 1
