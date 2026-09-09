"""Audit §4.1 (P0), THIRD site: the corpus window's Links subtab.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The audit named ONE surface (`/api/insights/trend`). The fix routed
`queries.py`'s five display callers through `exact=True`, and a follow-up caught
`price_narrative`. This is the third, found by an adversarial re-verifier and
confirmed live on 2026-09-09 -- and it is the one that shows what an incomplete
fix of a defect CLASS actually costs.

Measured on the live corpus, after the first two fixes and before this one, for a
single corpus window opened on the commodity `Dy`:

    /api/insights/trend?term=Dy        -> resolved: null
    /api/insights/context?term=Dy      -> resolved: null
    /api/insights/associations?term=Dy -> resolved: null
    /api/links/shared?term=Dy          -> resolved: {"term": "already"}, members: 36

Three subtabs of the same window answered honestly and the fourth returned
thirty-six articles about an English adverb. The partial fix did not merely leave
a hole -- it made the hole MORE convincing, because everything around it had
started telling the truth. (Nd -> "indiqué" 28, Pr -> "proposed" 37.)

`term` here is never human-typed: it is `_corpusTerm` in app-corpus.js, a keyword
the app itself chose when the window opened. There is no forgiving-search-box
argument for keeping the fuzzy default on this path.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.database.models import Article, ArticleLink, Base, Keyword, KeywordMention, Source
from src.database.session import get_db


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'l.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    db = Sess()
    db.add(Source(id=1, name="Wire", domain="wire.test"))
    # "already" CONTAINS the substring "dy" (alrea|dy) -- all LIKE %dy% asks for --
    # and is a far more common word than any commodity, so it ranks first by
    # mention count. There is no keyword "dy" of its own.
    db.add(Keyword(id=1, term="already", normalized_term="already"))
    for i in range(1, 4):
        db.add(Article(
            id=i, url=f"https://wire.test/a{i}", canonical_url=f"https://wire.test/a{i}",
            source_id=1, title=f"T{i}", content="c", hash=f"h{i}",
        ))
        db.add(KeywordMention(keyword_id=1, article_id=i, count=1))
        db.add(ArticleLink(article_id=i, url="https://origin.test/x",
                           normalized_url="https://origin.test/x"))
    db.commit()
    db.close()

    def _db():
        s = Sess()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_a_substring_probe_never_borrows_another_keywords_links(client):
    """THE GUARD. `Dy` has no keyword of its own, so the Links view must answer
    with nothing -- never with the shared origins of articles about "already"."""
    r = client.get("/api/links/shared", params={"term": "Dy"})
    assert r.status_code == 200
    d = r.json()
    assert d["resolved"] is None, (
        f"Dy resolved to {d['resolved']!r} -- the fuzzy fallback is back on a display path"
    )
    assert d["members"] == 0
    assert d["shared"] == []


def test_the_fixture_really_would_have_answered_without_the_guard(client):
    """ANTI-VACUITY. The same corpus, queried by the keyword that DOES exist,
    must return the shared origin -- otherwise the refusal above proves only that
    the fixture is empty."""
    r = client.get("/api/links/shared", params={"term": "already"})
    d = r.json()
    assert d["resolved"] == {"term": "already"}
    assert d["members"] == 3
    assert d["shared"], "the fixture must be capable of returning a shared link"
    assert d["shared"][0]["cited_by_articles"] == 3


def test_every_subtab_of_one_corpus_window_agrees(client):
    """The property the partial fix broke: a window opened on one term must not
    have one subtab answering from a different keyword than its siblings. Checked
    across the four endpoints app-corpus.js drives from the same `_corpusTerm`.
    """
    answers = {
        "trend": client.get("/api/insights/trend", params={"term": "Dy"}).json().get("resolved"),
        "context": client.get("/api/insights/context", params={"term": "Dy"}).json().get("resolved"),
        "associations": client.get(
            "/api/insights/associations", params={"term": "Dy"}
        ).json().get("resolved"),
        "links": client.get("/api/links/shared", params={"term": "Dy"}).json().get("resolved"),
    }
    assert all(v is None for v in answers.values()), (
        "one subtab is answering from a different keyword than its siblings: " + repr(answers)
    )
