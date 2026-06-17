"""B1 disclosure: keyword analytics honestly flag unsegmented languages (zh/ja).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The app ships zh/ja UI locales, but keyword extraction is whitespace-based and does
NOT segment Chinese/Japanese, so keyword analytics over those corpora are sparse/empty.
The audit-07 B1 ruling: surface that WHERE THE USER READS KEYWORDS, not only in a
diagnostics export. These tests pin the disclosure: present for zh/ja sets, absent for
English sets, never a fabricated keyword.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database.models import Article, Base


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _mk(db, h, language):
    a = Article(
        url=f"https://x.test/{h}", canonical_url=f"https://x.test/{h}", source_id=1,
        title="T", content="some text", hash=h, language=language,
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    return a


def test_unsegmented_note_present_for_zh_ja(db):
    a1 = _mk(db, "z1", "zh")
    a2 = _mk(db, "j1", "ja")
    a3 = _mk(db, "e1", "en")
    note = q.unsegmented_note(db, [a1.id, a2.id, a3.id])
    assert note is not None
    assert set(note["languages"]) == {"zh", "ja"}
    assert note["n_articles"] == 2  # the 2 unsegmented, not the English one
    assert "segment" in note["note"].lower()


def test_unsegmented_note_absent_for_english_only(db):
    a1 = _mk(db, "e1", "en")
    a2 = _mk(db, "f1", "fr")
    assert q.unsegmented_note(db, [a1.id, a2.id]) is None
    assert q.unsegmented_note(db, []) is None


def test_corpus_keywords_carries_the_disclosure(db):
    a1 = _mk(db, "z1", "zh")
    out = q.corpus_keywords(db, article_ids=[a1.id])
    # A zh article yields no segmented keywords, but now WHY is disclosed (not a bare 0).
    assert out["count"] == 0
    assert "unsegmented" in out and out["unsegmented"]["languages"] == ["zh"]
    # An English-only call carries no such note.
    a2 = _mk(db, "e1", "en")
    assert "unsegmented" not in q.corpus_keywords(db, article_ids=[a2.id])


def test_article_graph_empty_map_explains_unsegmented(db):
    a1 = _mk(db, "j1", "ja")
    g = q.article_graph(db, article_ids=[a1.id])
    assert g["nodes"] == []
    assert "unsegmented" in g
    # The caveat is the honest "why", not a bare "too few keywords".
    assert "segment" in g["caveat"].lower()
