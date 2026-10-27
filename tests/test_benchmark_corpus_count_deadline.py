"""The scaling benchmark's corpus context counts ``keyword_mentions`` inside the bundle's per-member deadline, and the count must be one that deadline can stop.

``statement_deadline`` (src/database/maintenance.py) is a SQLite progress handler asked once per 20,000 virtual-machine opcodes. A bare
``SELECT COUNT(*)`` with no ``WHERE`` is nine opcodes in all and the whole b-tree walk happens inside one of them, so the handler is never asked
while it runs: it ran whole under a millionth of a second over 1,240,657 mentions. ``benchmark.json`` is a member of the all-diagnostics bundle
(``src/api/diagnostics/bundle.py``), which wraps every database-touching member in ``statement_deadline(db, <300 s>)``, and ``run_benchmark``
itself reads ``deadline_left_s``; the count in ``_store_and_corpus`` (S4 of the WAL lane's deadline-bound sweep, found by RC2 while building S3)
sat in that block unstoppable. ``count(1)`` loops (about three opcodes per row) and is stopped.

THE TEST OF A BOUND is the REAL deadline at a tiny value over enough rows, asserting the typed timeout: the handler is asked every 20,000
opcodes, so the rows must be enough for a three-opcode loop to reach that (30,000 here), and a handler asked at every opcode would pass against
the very statement it should catch (see tests/test_deadline_bound_statements.py). The article, source and keyword counts that come before it are
tiny here on purpose, so the deadline can only fire in the mentions count. Checked red against the statement respelled as a bare ``count(*)``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.maintenance import StatementTimeout, statement_deadline
from src.database.models import Article, Base, Keyword, KeywordMention, Source
from src.monitoring import benchmark

#: Enough rows that a three-opcode loop reaches the handler's 20,000-opcode interval, with few enough articles that the counts before it do not.
_MENTIONS = 30_000
_KEYWORDS = 50
_TINY = 1e-6


def _store(*, mentions: int):
    """An in-memory store on the app's own schema: one source, ``mentions // 50 + 1`` articles, 50 keywords and ``mentions`` mention rows."""
    articles = mentions // _KEYWORDS + 1
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    session.add(Source(name="S", domain="x.test"))
    session.commit()
    now = datetime.now(UTC)
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
            for i in range(articles)
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


def test_the_benchmark_mentions_count_is_stopped_by_the_real_deadline_over_enough_rows():
    """The shipped context read, the real deadline, no fake: it must come back as the typed timeout. Respelled as a bare ``count(*)`` it
    comes back whole with 30,000 and this fails."""
    s = _store(mentions=_MENTIONS)
    with pytest.raises(StatementTimeout), statement_deadline(s, seconds=_TINY):
        benchmark._store_and_corpus(s)


@pytest.mark.parametrize("mentions", [0, 1, 1_000, _MENTIONS])
def test_the_benchmark_corpus_counts_are_the_numbers_the_tables_hold(mentions):
    """``count(1)`` counts rows, as ``count(*)`` did: the same number on an empty table, one row, and thousands (non-zero where it can be)."""
    s = _store(mentions=mentions)
    _, corpus = benchmark._store_and_corpus(s)
    assert corpus["keyword_mentions"] == mentions
    assert corpus["articles"] == mentions // _KEYWORDS + 1
    assert corpus["sources"] == 1
    assert corpus["keywords"] == (_KEYWORDS if mentions else 0)
