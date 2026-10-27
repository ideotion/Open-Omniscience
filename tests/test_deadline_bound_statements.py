"""A deadline built on a progress handler bounds only what loops: the two whole-table counts that sat inside one and were not stopped by it.

``statement_deadline`` (src/database/maintenance.py) installs a SQLite progress handler that is asked once per 20,000 virtual-machine
opcodes. A bare ``count(*)`` with no ``WHERE`` is nine opcodes in all and the whole b-tree walk happens inside one of them, so the handler is
never asked while it runs and the deadline around it bounds nothing; ``count(1)`` / ``count(id)`` loop (about three opcodes per row) and are
stopped. The deadline-bound sweep (wal-lane/deadline-bound-sweep-2026-10-27.md; S1, S2) found two such counts:

* the Library figures' ``keyword_mentions`` count (src/api/database.py), whose 300 s deadline is documented as protecting the pooled
  connection and the read snapshot the count holds; it ran whole under a millionth of a second over 1,240,657 mentions;
* ``content_share_estimate`` (src/monitoring/storage.py), the encrypted store's normal path (neither qualified sqlcipher3 build has dbstat),
  whose docstring said it was bounded by the statement deadline.

THE TEST OF A BOUND is the REAL deadline at a tiny value over enough rows, asserting the typed timeout. The handler is asked every 20,000
opcodes, so the rows must be enough for a three-opcode loop to reach that (here 30,000); a handler asked at EVERY opcode (``set_progress_handler(cb,
1)``) is consulted 9 times by a bare ``count(*)`` and passes against the very statement it should catch (the delta read of #1543). A test that
only checks the statement sits inside a ``statement_deadline`` block pins the nesting, not the bound. Each test below was checked red against
the statement respelled as a bare ``count(*)``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.api import database as dbmod
from src.database.maintenance import StatementTimeout, statement_deadline
from src.database.models import Article, Base, Keyword, KeywordMention, Source

#: Enough rows that a three-opcode loop reaches the handler's 20,000-opcode interval several times over.
_ROWS = 30_000
_KEYWORDS = 50
_TINY = 1e-6


def _store(*, articles: int, mentions: int):
    """An in-memory store on the app's own schema: ``articles`` article rows and ``mentions`` keyword_mentions rows (distinct pairs)."""
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    session.add(Source(name="S", domain="x.test"))
    session.commit()
    now = datetime.now(UTC)
    for off in range(0, articles, 10_000):
        session.execute(
            Article.__table__.insert(),
            [
                {
                    "url": f"u{i}",
                    "canonical_url": f"u{i}",
                    "source_id": 1,
                    "title": f"Story {i}",
                    "content": "x",
                    "hash": f"h{i}",
                    "language": "en",
                    "created_at": now,
                }
                for i in range(off, min(off + 10_000, articles))
            ],
        )
    if mentions:
        session.execute(
            Keyword.__table__.insert(),
            [
                {"term": f"k{i}", "normalized_term": f"k{i}", "language": "en", "frequency": 0}
                for i in range(_KEYWORDS)
            ],
        )
        session.execute(
            KeywordMention.__table__.insert(),
            [
                {
                    "keyword_id": 1 + i % _KEYWORDS,
                    "article_id": 1 + i // _KEYWORDS,
                    "count": 1,
                    "first_offset": 0,
                    "observed_on": date(2024, 1, 1),
                    "country": "FR",
                    "language": "en",
                }
                for i in range(mentions)
            ],
        )
    session.commit()
    return session


def test_the_figures_mentions_count_is_stopped_by_the_real_deadline_over_enough_rows():
    """The shipped statement, the real deadline, no fake: the count must come back as the typed timeout. Respelled as a bare ``count(*)`` it
    comes back whole (30,000) and this fails."""
    s = _store(articles=_ROWS // _KEYWORDS, mentions=_ROWS)
    with pytest.raises(StatementTimeout), statement_deadline(s, seconds=_TINY):
        dbmod._mentions_count(s)


def test_the_background_count_reports_a_named_failure_when_its_deadline_fires_for_real(monkeypatch):
    """The same bound through the code that owns it: ``_compute_figures_counted`` with the count deadline at a millionth of a second and
    NO fake count. The tile must say the count failed, name the time limit, and carry no number (an interrupted count is not a zero)."""
    monkeypatch.setenv("OO_FIGURES_COUNT_DEADLINE_S", str(_TINY))
    dbmod._forget_mentions()
    s = _store(articles=_ROWS // _KEYWORDS, mentions=_ROWS)
    try:
        out = dbmod._compute_figures_counted(s, datetime.now(UTC))
    finally:
        dbmod._forget_mentions()
    assert out["keyword_mentions_state"] == "failed", out
    assert out["keyword_mentions_failure"]["kind"] == "statement-deadline"
    assert out[dbmod._COUNT_KEY] is None


@pytest.mark.parametrize("mentions", [0, 1, 1_000, _ROWS])
def test_the_loop_form_counts_the_same_number_as_the_bare_count(mentions):
    """``count(id)`` replaces ``count(*)`` only because ``id`` is the primary key and never NULL: same number on an empty table, one row, and
    thousands. Asserted non-zero where it can be, so equality is not a tautology."""
    s = _store(articles=max(1, mentions // _KEYWORDS + 1), mentions=mentions)
    bare = s.execute(select(func.count()).select_from(KeywordMention)).scalar()
    assert dbmod._mentions_count(s) == bare == mentions


def test_the_content_share_count_is_stopped_by_the_real_deadline_over_enough_rows(monkeypatch):
    """``content_share_estimate`` takes the default deadline (``OO_STATEMENT_TIMEOUT_S``). With it at a millionth of a second and 30,000
    articles, its ``count(1)`` is asked after 20,000 opcodes and stops: the block comes back ``aborted``. Respelled as a bare ``count(*)`` the
    count runs whole and the 400 short probes that follow stay under the interval, so the estimate comes back COMPLETE and this fails."""
    from src.monitoring.storage import content_share_estimate

    monkeypatch.setenv("OO_STATEMENT_TIMEOUT_S", str(_TINY))
    s = _store(articles=_ROWS, mentions=0)
    out = content_share_estimate(s, 123_456)
    assert out is not None and out.get("aborted") is True, out
    assert "sampled" not in out


def test_the_content_share_estimate_still_answers_when_the_deadline_is_generous(monkeypatch):
    """The same store under the default minute: the estimate completes, with the count it takes from ``count(1)``."""
    from src.monitoring.storage import content_share_estimate

    monkeypatch.setenv("OO_STATEMENT_TIMEOUT_S", "60")
    s = _store(articles=_ROWS, mentions=0)
    out = content_share_estimate(s, 123_456)
    assert out is not None and not out.get("aborted"), out
    assert out["articles"] == _ROWS
    assert out["sampled"] > 0
