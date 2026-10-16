"""The HOT tier's mention set is read from the frequency index, and a corpus's first 5,001 keywords cost an index read.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``corpus_mention_titles`` ran ``ORDER BY coalesce(frequency, 0) DESC, term LIMIT 5001`` every wiki drain. No
index serves an expression, so it scanned and sorted every keyword: 9.5 s on average over 224 calls on the
2.26 million keywords of the 16 Oct 2026 bundles (max 78 s), a read snapshot held the whole time. The
order is now ``frequency DESC, term``, which ``idx_keyword_frequency`` serves.

The ORDER of the answer is the contract this file holds (most frequent first, ties by term, the cap reported); the PLAN is the
property the change exists for, so it is read from SQLite itself, not from the source text.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Keyword
from src.wiki import hotset


@pytest.fixture
def corpus(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'hot-mentions.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as db:
        yield db, engine


def _seed(db, rows):
    for term, frequency in rows:
        db.add(Keyword(term=term, normalized_term=term.lower(), frequency=frequency))
    db.commit()


def test_the_most_frequent_terms_come_first_ties_by_term_and_a_null_frequency_last(corpus):
    db, _engine = corpus
    _seed(
        db,
        [("delta", 5), ("alpha", 5), ("bravo", 9), ("zulu", None), ("echo", 0), ("charlie", 2), ("yankee", None)],
    )
    titles, capped = hotset.corpus_mention_titles(db, limit=4)
    assert titles == {"bravo", "alpha", "delta", "charlie"}, "frequency 9, then the two 5s by term, then 2"
    assert capped is True, "seven keywords, four taken: the cap was hit and the caller is told"
    everything, capped_all = hotset.corpus_mention_titles(db, limit=7)
    assert everything == {"bravo", "alpha", "delta", "charlie", "echo", "zulu", "yankee"} and capped_all is False


def test_the_cap_is_reported_exactly_at_the_boundary(corpus):
    db, _engine = corpus
    _seed(db, [(f"t{i:02d}", 100 - i) for i in range(6)])
    titles, capped = hotset.corpus_mention_titles(db, limit=6)
    assert len(titles) == 6 and capped is False, "as many as the limit is not a truncation"
    titles, capped = hotset.corpus_mention_titles(db, limit=5)
    assert titles == {f"t{i:02d}" for i in range(5)} and capped is True


def _statement_of_the_read(db, engine):
    """The statement ``corpus_mention_titles`` sends, with its parameters, as SQLite received it."""
    seen: list[tuple[str, object]] = []

    def grab(_conn, _cursor, statement, parameters, _context, _many):
        if "FROM keywords" in statement:
            seen.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", grab)
    try:
        hotset.corpus_mention_titles(db, limit=10)
    finally:
        event.remove(engine, "before_cursor_execute", grab)
    assert len(seen) == 1, "the mention set is ONE statement"
    return seen[0]


def test_the_read_is_served_by_the_frequency_index_and_sorts_nothing_but_ties(corpus):
    """The property the change is for. The plan, asked of SQLite on the very statement the function sent: it walks
    ``idx_keyword_frequency`` and sorts only the right part of the ORDER BY (the ties). The old form's plan was a bare
    SCAN with USE TEMP B-TREE FOR ORDER BY, a sort of every keyword."""
    db, engine = corpus
    _seed(db, [(f"t{i}", i % 7) for i in range(50)])
    statement, parameters = _statement_of_the_read(db, engine)
    with engine.connect() as conn:
        plan = [str(r[-1]) for r in conn.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters).fetchall()]
    joined = " | ".join(plan)
    assert "idx_keyword_frequency" in joined, joined
    assert "USE TEMP B-TREE FOR ORDER BY" not in joined, "a full sort of every keyword is the cost this removed: " + joined
    assert not any(p.startswith("SCAN keywords") and "USING" not in p for p in plan), joined


def test_the_old_expression_form_is_the_one_the_plan_check_would_catch(corpus):
    """Non-vacuity: the plan check above reddens on the form it replaced, so a return to the expression cannot pass quietly."""
    db, engine = corpus
    _seed(db, [(f"t{i}", i % 7) for i in range(50)])
    old = (
        "SELECT keywords.term FROM keywords WHERE keywords.term IS NOT NULL "
        "ORDER BY coalesce(keywords.frequency, 0) DESC, keywords.term LIMIT 11 OFFSET 0"
    )
    with engine.connect() as conn:
        plan = " | ".join(str(r[-1]) for r in conn.execute(text("EXPLAIN QUERY PLAN " + old)).fetchall())
    assert "USE TEMP B-TREE FOR ORDER BY" in plan and "idx_keyword_frequency" not in plan, plan
