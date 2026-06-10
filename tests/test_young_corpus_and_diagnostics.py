"""
Young-corpus card thresholds + the keyword diagnostics log.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two maintainer rulings (CLAUDE.md, 2026-06-10):
- Cards must appear sooner on a young corpus, with an HONEST small-n caveat
  (lowered volume gates never fabricate -- every number stays a real count).
- The Settings diagnostics log: a shareable, on-demand export of keywords +
  families + overrides + super-groups, in the oo-export-1 envelope.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source


@pytest.fixture()
def young_corpus(monkeypatch, tmp_path):
    """6 articles across 2 sources -- a day-one corpus. 'drought' is mentioned in
    exactly 2 recent articles: below the mature min_recent=3, at the young gate."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(name="Beta", domain="beta.test", country="us"))
    s.commit()

    now = datetime.now(UTC)
    for i in range(6):
        a = Article(
            url=f"https://young.test/{i}",
            canonical_url=f"https://young.test/{i}",
            source_id=1 if i % 3 else 2,
            title=f"Young story {i}",
            hash=f"yh{i}",
            language="en",
            content=(
                # ONE 'drought' per article: 2 recent mentions total -- below the
                # mature min_recent=3, exactly at the young gate of 2.
                "A severe drought is hitting the region as dry conditions spread."
                if i < 2
                else "Quiet day with steady weather and calm local markets reported."
            ),
            published_at=now - timedelta(days=i % 3),
            created_at=now,
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=BaselineExtractor(), country="fr")
    return s


def test_rising_fires_on_young_corpus_with_two_mentions(young_corpus):
    from src.briefing.producers import rising_now

    cards = rising_now(young_corpus)
    assert cards, "a young corpus (2 recent mentions) must still produce a rising card"
    c = next((c for c in cards if "drought" in c.title), cards[0])
    assert "Early-corpus note" in c.caveat  # honesty: small sample is SAID, not hidden
    assert c.n >= 2  # the count shown is the real count


def test_mature_threshold_still_strict(young_corpus, monkeypatch):
    """With the young gate disabled the same 2-mention corpus stays quiet --
    the lowered minimum applies ONLY to young corpora."""
    from src.briefing import producers

    monkeypatch.setattr(producers, "_YOUNG_CORPUS_ARTICLES", 0)  # nothing is "young"
    cards = producers.rising_now(young_corpus)
    assert all("drought" not in c.title for c in cards)
    assert all("Early-corpus note" not in c.caveat for c in cards)


def test_diet_fires_with_six_articles(young_corpus):
    from src.briefing.producers import diet_self_audit

    cards = diet_self_audit(young_corpus)
    assert cards, "6 articles across 2 sources must produce a diet card (was gated at 10)"
    assert "Early-corpus note" in cards[0].caveat


# --------------------------------------------------------------------------- #
#  Diagnostics log endpoint (shared app DB -- membership assertions only)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_keyword_log_envelope_and_content(client):
    from src.database.models import (
        Keyword,
        KeywordMention,
        KeywordSuperGroup,
        KeywordSuperGroupMember,
        SessionLocal,
    )

    s = SessionLocal()
    try:
        src = Source(name="Diag source", domain="diag.test")
        s.add(src)
        s.flush()
        art = Article(
            url="https://diag.test/1",
            canonical_url="https://diag.test/1",
            source_id=src.id,
            title="Diagnostics seed",
            hash="diag-h1",
            language="en",
            content="Zanzibar-Diag appears here.",
            created_at=datetime.now(UTC),
        )
        s.add(art)
        kw = Keyword(term="Zanzibar-Diag", normalized_term="zanzibar-diag")
        s.add(kw)
        s.flush()
        s.add(
            KeywordMention(
                keyword_id=kw.id,
                article_id=art.id,
                count=3,
                observed_on=datetime.now(UTC).date(),
            )
        )
        sg = KeywordSuperGroup(name="Diag supergroup")
        s.add(sg)
        s.flush()
        s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="zanzibar-diag"))
        s.commit()
    finally:
        s.close()

    r = client.get("/api/diagnostics/keywords")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    body = r.json()
    # The versioned, provenance-carrying envelope.
    assert body["export_schema"] == "oo-export-1"
    assert body["kind"] == "keyword-diagnostics"
    data = body["data"]
    for key in ("corpus", "method", "keywords", "families", "overrides", "supergroups"):
        assert key in data
    # Real counts for the seeded keyword; the corpus header is honest.
    mine = [k for k in data["keywords"] if k["normalized"] == "zanzibar-diag"]
    assert mine and mine[0]["mentions"] == 3 and mine[0]["hidden"] is False
    assert data["corpus"]["keywords_exported"] >= 1
    # The curated super-group appears with its member key.
    sg_mine = [g for g in data["supergroups"] if g["name"] == "Diag supergroup"]
    assert sg_mine and "zanzibar-diag" in sg_mine[0]["members"]
    # No composite scores anywhere in a keyword row (honesty by construction).
    assert all("score" not in k for k in data["keywords"])


# --------------------------------------------------------------------------- #
#  Translated docs: ?lang= serving + honest fallback (ruled 2026-06-10)
# --------------------------------------------------------------------------- #
def test_doc_translation_served_and_fallback(client):
    # French Quickstart: a hand-seeded translation exists -> served, header says fr.
    r = client.get("/api/docs/quickstart?lang=fr")
    assert r.status_code == 200
    assert r.headers["x-oo-doc-lang"] == "fr"
    assert "Démarrage rapide" in r.text
    # No German manual yet -> English fallback, honestly labelled.
    r = client.get("/api/docs/quickstart?lang=de")
    assert r.status_code == 200
    assert r.headers["x-oo-doc-lang"] == "en"
    # A path-shaped lang can never traverse: falls back to English, no error.
    r = client.get("/api/docs/quickstart?lang=..%2F..")
    assert r.status_code == 200
    assert r.headers["x-oo-doc-lang"] == "en"
    # The list endpoint reports which docs have a translation.
    docs = client.get("/api/docs?lang=fr").json()["docs"]
    by_slug = {d["slug"]: d for d in docs}
    assert by_slug["quickstart"]["translated"] is True
    assert by_slug["security"]["translated"] is False


def test_keyword_log_carries_language_signatures(client):
    """Trans-language groundwork (maintainer 2026-06-10): each keyword's
    language signature = distinct articles per ARTICLE language — the
    disambiguation evidence for hand/main-style equivalence rings."""
    from src.database.models import Keyword, KeywordMention, SessionLocal

    s = SessionLocal()
    try:
        src = Source(name="Sig source", domain="sig.test")
        s.add(src)
        s.flush()
        arts = []
        for i, lang in enumerate(["fr", "fr", "en"]):
            a = Article(
                url=f"https://sig.test/{i}", canonical_url=f"https://sig.test/{i}",
                source_id=src.id, title=f"Sig {i}", hash=f"sig-h{i}",
                language=lang, content="La main / the hand.",
                created_at=datetime.now(UTC),
            )
            s.add(a)
            arts.append(a)
        kw = Keyword(term="main", normalized_term="main-sig-test")
        s.add(kw)
        s.flush()
        for a in arts:
            s.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1,
                                 observed_on=datetime.now(UTC).date()))
        s.commit()
    finally:
        s.close()

    data = client.get("/api/diagnostics/keywords").json()["data"]
    mine = next(k for k in data["keywords"] if k["normalized"] == "main-sig-test")
    # The evidence, verbatim: 2 French articles, 1 English — never a guess.
    assert mine["language_signature"] == {"fr": 2, "en": 1}
    assert "language_signature" in data["method"] or "language" in data["method"]
