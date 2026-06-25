"""Copypasta / shared-talking-point detection (manipulation-pattern card, ruling #13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names the STRUCTURE: an identical verbatim span across many DISTINCT sources in articles
that are NOT whole duplicates. These tests pin the honest gates — the distinct-SOURCE
surfacing gate, the wire-republish exclusion (whole near-dups are echo_chamber's job, not
copypasta), and the absence of any score.

The pure ``shared_word_ngrams`` helper has no DB/extra dependency, so its tests run on every
lane; the card + endpoint tests use an in-memory SQLite corpus (sqlalchemy is a core dep).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.copypasta import find_copypasta
from src.database.models import Article, Base, Source
from src.signals.near_dup import shared_word_ngrams

# A verbatim "talking point" long enough to clear k=8 and to merge into one span.
PLANT = (
    "the proposed reform will protect working families and create thousands of new local "
    "jobs across the region"
)
# Otherwise-different bodies, so the sharing articles are NOT whole near-duplicates.
A_BODY = (
    "Officials in the northern district presented the annual budget on Tuesday morning to a "
    "packed council chamber, where reporters noted a tense exchange over school funding."
)
B_BODY = (
    "A long feature about coastal wildlife and seasonal migration patterns ran in the weekend "
    "edition, illustrated with photographs gathered over a decade of patient fieldwork."
)
C_BODY = (
    "The technology correspondent reviewed three competing messaging applications and their "
    "privacy trade-offs in a detailed comparison piece that was published online overnight."
)

NOW = datetime.now().replace(microsecond=0)


# --- the pure primitive (no DB / no extra; runs on every lane) --------------- #


def test_shared_word_ngrams_finds_a_phrase_across_distinct_docs():
    docs = {
        "a": A_BODY + " " + PLANT + ".",
        "b": B_BODY + " " + PLANT + ".",
        "c": C_BODY + " " + PLANT + ".",
        "d": "This document shares nothing with the others; entirely unique words throughout.",
    }
    res = shared_word_ngrams(docs, k=8, min_docs=2, max_phrases=50)
    assert len(res) == 1
    top = res[0]
    assert top["n_docs"] == 3
    assert sorted(top["doc_ids"]) == ["a", "b", "c"]
    # Overlapping windows are merged into the full planted span, not many 8-grams.
    assert "protect working families and create thousands" in top["phrase"]
    assert len(top["phrase"].split()) >= 13


def test_shared_word_ngrams_respects_min_docs_and_degenerate_inputs():
    docs = {"a": A_BODY + " " + PLANT, "b": B_BODY + " " + PLANT}
    assert shared_word_ngrams(docs, k=8, min_docs=3) == []  # only 2 docs share it
    assert shared_word_ngrams({}, k=8, min_docs=2) == []
    assert shared_word_ngrams({"x": "too short"}, k=8, min_docs=2) == []
    assert shared_word_ngrams(docs, k=8, min_docs=1) == []  # min_docs must be >= 2


# --- the card over an in-memory corpus --------------------------------------- #


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


def _src(db, sid, domain):
    db.add(Source(id=sid, name=f"Src{sid}", domain=domain))
    db.commit()


def _art(db, aid, source_id, text, days_ago=2):
    db.add(Article(
        id=aid, url=f"https://x/{aid}", canonical_url=f"https://x/{aid}", source_id=source_id,
        title=f"Story {aid}", content=text, hash=f"h{aid}", language="en",
        published_at=NOW - timedelta(days=days_ago),
    ))
    db.commit()


def test_fires_on_a_verbatim_phrase_across_three_distinct_sources(db):
    _src(db, 1, "a.test")
    _src(db, 2, "b.test")
    _src(db, 3, "c.test")
    _art(db, 1, 1, A_BODY + " " + PLANT + ".")
    _art(db, 2, 2, B_BODY + " " + PLANT + ".")
    _art(db, 3, 3, C_BODY + " " + PLANT + ".")
    out = find_copypasta(db, k=8, min_sources=3)
    assert out["count"] == 1
    it = out["items"][0]
    assert it["distinct_sources"] == 3 and it["n_articles"] == 3
    assert sorted(it["article_ids"]) == [1, 2, 3]
    assert "protect working families" in it["phrase"]
    assert "never a claim it was coordinated" in out["caveat"]
    # No score anywhere on the item.
    assert not any("score" in k for k in it)


def test_whole_article_wire_republish_is_excluded(db):
    """Three sources running the SAME article (a wire republish) is echo_chamber's job,
    not copypasta — the shared span is the whole article, so it must NOT fire here."""
    _src(db, 1, "a.test")
    _src(db, 2, "b.test")
    _src(db, 3, "c.test")
    wire = "Breaking news. " + PLANT + ". " + A_BODY + " " + B_BODY
    _art(db, 1, 1, wire)
    _art(db, 2, 2, wire)
    _art(db, 3, 3, wire)
    assert find_copypasta(db, k=8, min_sources=3)["count"] == 0


def test_below_min_sources_does_not_fire(db):
    _src(db, 1, "a.test")
    _src(db, 2, "b.test")
    _art(db, 1, 1, A_BODY + " " + PLANT + ".")
    _art(db, 2, 2, B_BODY + " " + PLANT + ".")
    assert find_copypasta(db, k=8, min_sources=3)["count"] == 0


def test_a_single_source_repeating_a_line_cannot_manufacture_it(db):
    """Independence is distinct SOURCES, never article count."""
    _src(db, 1, "a.test")
    _art(db, 1, 1, A_BODY + " " + PLANT + ".")
    _art(db, 2, 1, B_BODY + " " + PLANT + ".")
    _art(db, 3, 1, C_BODY + " " + PLANT + ".")
    assert find_copypasta(db, k=8, min_sources=3)["count"] == 0


def test_copypasta_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'c.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        for sid, dom in ((1, "a.test"), (2, "b.test"), (3, "c.test")):
            s.add(Source(id=sid, name=f"S{sid}", domain=dom))
        s.commit()
        for aid, body in ((1, A_BODY), (2, B_BODY), (3, C_BODY)):
            s.add(Article(
                id=aid, url=f"https://x/{aid}", canonical_url=f"https://x/{aid}", source_id=aid,
                title=f"Story {aid}", content=body + " " + PLANT + ".", hash=f"h{aid}",
                language="en", published_at=NOW - timedelta(days=2),
            ))
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            body = c.get("/api/insights/copypasta").json()
        assert body["count"] == 1
        assert body["items"][0]["distinct_sources"] == 3
        assert sorted(body["items"][0]["article_ids"]) == [1, 2, 3]
    finally:
        app.dependency_overrides.clear()
