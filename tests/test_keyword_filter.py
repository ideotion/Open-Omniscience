"""
Tests for keyword filtering: stronger stoplist + user-editable exclusions.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.analytics.extract import BaselineExtractor, global_stopwords
from src.analytics.store import index_article
from src.database.models import Article, Base, Source


def _norms(text):
    return {t.normalized for t in BaselineExtractor().extract(text)}


def test_function_words_no_longer_leak():
    text = "I think you are right. The economy is not one thing. Not one bit, you know."
    norms = _norms(text)
    for dumb in ("i", "you", "the", "not", "one", "not one", "not one bit", "economy is not"):
        assert dumb not in norms, f"{dumb!r} should be filtered"
    assert "economy" in norms  # real content survives


def test_global_stopwords_is_multilingual():
    g = global_stopwords()
    for w in ("the", "not", "one", "le", "der", "die", "el", "il"):
        assert w in g


def test_single_letter_not_an_entity():
    # "I" appears mid-sentence capitalised but must never become an entity.
    text = "Yesterday I met them, and I told them so, because I believed it then."
    ents = {t.normalized for t in BaselineExtractor().extract(text) if t.kind != "term"}
    assert "i" not in ents


def test_filter_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.analytics.filters import add_excluded, excluded_set, load_settings, save_settings

    save_settings({"excluded": "Foo, BAR\nbaz", "min_length": 4})
    s = load_settings()
    assert s.excluded == ["bar", "baz", "foo"] and s.min_length == 4
    add_excluded("Qux")
    assert "qux" in excluded_set()


def test_excluded_terms_hidden_in_top(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="us"))
    s.commit()
    a = Article(
        url="https://x.test/p",
        canonical_url="https://x.test/p",
        source_id=1,
        title="T",
        content="Sanctions and sanctions on copper. Copper and copper exports and tariffs.",
        hash="h1",
        language="en",
        published_at=datetime(2024, 1, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    s.add(a)
    s.commit()
    index_article(s, a, extractor=BaselineExtractor(), country="us")

    assert any(t["normalized"] == "copper" for t in q.top_terms(s, limit=20)["terms"])
    from src.analytics.filters import add_excluded

    add_excluded("copper")
    assert not any(t["normalized"] == "copper" for t in q.top_terms(s, limit=20)["terms"])
    s.close()


def test_stoplist_covers_flagged_function_words_and_contractions():
    """User-flagged leaks (since/last/it's/don't) are filtered, incl. curly ’ spellings,
    while genuine subject keywords are never hidden."""
    sw = global_stopwords()
    for w in ("since", "last", "it's", "don't", "said", "reportedly", "today", "meanwhile"):
        assert w in sw, w
    assert "it’s" in sw and "don’t" in sw  # curly-apostrophe variants
    for keep in ("inflation", "russia", "sanctions", "election", "macron"):
        assert keep not in sw, keep
