"""The baseline-tag backfill reads three columns of the keyword table one id-ordered chunk at a time (entity-load sweep part 2, bundle A).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

It used to iterate ``session.query(Keyword)``: every keyword of the table as an entity at once (on 1,500,000 seeded keywords, same store, shipped statements:
33.8 s and 2,951 MB of Python allocation against 3.7 s and 12.5 MB for the columns in chunks; ``keyword-lane/entity-load-sweep-part2-2026-10-27.md``). This file pins what
the chunking must not change (the tags written, the ``limit``, a second run adding nothing, a match on either side of a chunk edge) and the statements
that bound the read (three columns, ordered by id, a LIMIT on every read of the table), so a revert fails on the statement and not on a stopwatch.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.analytics import store
from src.analytics.baseline import baseline_tags
from src.analytics.store import backfill_baseline_tags
from src.database.models import Base, Keyword, KeywordTag

# "election" matches the shipped English baseline (a type and a topic tag), "inflation" one tag, "widget" none
_TERMS = ["widget", "election", "widget", "inflation", "election", "widget", "widget", "election", "inflation", "widget"]


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
    for term in _TERMS:
        s.add(Keyword(term=term, normalized_term=term, language="en", frequency=0, is_entity=False))
    s.commit()
    yield s
    s.close()


def _reference(s, limit=None) -> dict:
    """What the loop over the entities gave: the tags a baseline match adds, per keyword, for the first ``limit`` keywords by id."""
    q = s.query(Keyword).order_by(Keyword.id)
    if limit:
        q = q.limit(limit)
    tagged = added = scanned = 0
    for kw in q:
        scanned += 1
        pairs = baseline_tags(kw.language, kw.normalized_term)
        if pairs:
            tagged += 1
            added += len(pairs)
    return {"scanned": scanned, "tagged_keywords": tagged, "tags_added": added}


def _tags(s) -> list[tuple[int, str, str]]:
    return sorted((t.keyword_id, t.axis, t.tag) for t in s.query(KeywordTag).filter_by(source="baseline"))


@pytest.mark.parametrize("chunk", [1, 2, 3, 4, 10, 11, 20_000])
def test_the_tags_written_do_not_depend_on_where_the_chunks_end(db, monkeypatch, chunk):
    want = _reference(db)
    assert want["tagged_keywords"] == 5 and want["tags_added"] == 8, "the shipped baseline moved: pick other terms"
    monkeypatch.setattr(store, "_BASELINE_BACKFILL_CHUNK", chunk, raising=False)  # raising=False: the same file runs on the code before the constant existed

    got = backfill_baseline_tags(db)

    assert got == want
    assert len(_tags(db)) == want["tags_added"]
    assert backfill_baseline_tags(db)["tags_added"] == 0, "a second run is idempotent"


@pytest.mark.parametrize("limit", [1, 3, 4, 7, 10, 50])
def test_limit_means_the_first_n_keywords_by_id(db, monkeypatch, limit):
    monkeypatch.setattr(store, "_BASELINE_BACKFILL_CHUNK", 3, raising=False)
    assert backfill_baseline_tags(db, limit=limit) == _reference(db, limit)


def test_the_table_is_read_as_three_columns_ordered_by_id_with_a_limit(db, monkeypatch):
    monkeypatch.setattr(store, "_BASELINE_BACKFILL_CHUNK", 4, raising=False)
    db.statements.clear()
    backfill_baseline_tags(db)

    reads = [q for q in db.statements if "FROM keywords" in q]
    assert len(reads) == 3, "ten keywords in chunks of four: three reads, the last one short"
    for q in reads:
        head = q.split("FROM keywords")[0]
        assert "keywords.normalized_term" in head and "keywords.language" in head and "keywords.id" in head
        for wide in ("keywords.term,", "frequency", "relevance_score", "created_at", "mention_count"):
            assert wide not in head, f"the backfill reads {wide}, which the match does not use"
        assert "ORDER BY keywords.id" in q and "LIMIT" in q
