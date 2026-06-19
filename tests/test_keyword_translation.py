"""Language-aware keyword views: verified cross-language TRANSLATIONS (maintainer
ruling 2026-06-19 — don't blind the reader to foreign keywords, translate them).

The verified translation source is the cross-language rings (Wikidata-QID-sourced):
a ring lists a concept's term in every language, so the translation of a keyword
into the UI language is its ring's member in that language. In-memory, no crypto.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import equivalence as eq
from src.analytics import queries as q
from src.database.models import Article, Base, Keyword, KeywordMention, Source


def test_ring_translation_and_translate_term_resolve_via_rings():
    rid = eq.ring_of("en", "election")
    assert rid, "the bundled 'election' ring must exist"
    # The verified translation of the concept into each language is its ring member.
    assert eq.ring_translation(rid, "fr") == "élection"
    # A foreign keyword resolves to the UI-language term via its ring.
    assert eq.translate_term("fr", "élection", "en") == "election"
    assert eq.translate_term("de", "wahl", "en") == "election"
    # Same-language is a no-op (nothing to translate), and an unknown term -> None.
    assert eq.translate_term("en", "election", "en") is None
    assert eq.translate_term("fr", "no-such-term-xyz", "en") is None


def _sess():
    e = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def _seed(s):
    s.add(Source(name="S", domain="s.test"))
    s.flush()
    a = Article(url="u", canonical_url="u", source_id=1, title="t", content="c", hash="h")
    s.add(a)
    s.flush()
    for term, norm, lang, m in [("élection", "élection", "fr", 50), ("Wahl", "wahl", "de", 40),
                                ("budget", "budget", "en", 30)]:
        k = Keyword(term=term, normalized_term=norm, language=lang, frequency=0,
                    mention_count=m, article_count=1)
        s.add(k)
        s.flush()
        s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=m, observed_on=date.today()))
    s.commit()


def _by_norm(res):
    return {t["normalized"]: t for t in res["terms"]}


def test_top_terms_annotates_verified_translation():
    s = _sess()
    _seed(s)
    by = _by_norm(q.top_terms(s, limit=10, group=False, target_lang="en"))
    assert by["élection"]["translation"] == "election" and by["élection"]["translation_source"] == "ring"
    assert by["wahl"]["translation"] == "election"
    # An English keyword (same as target) carries NO translation (nothing to add).
    assert "translation" not in by["budget"]
    # Without target_lang, no translation field is added (byte-compatible default).
    plain = _by_norm(q.top_terms(s, limit=10, group=False))
    assert all("translation" not in t for t in plain.values())


def _seed_solo(s):
    """Only ONE ring member present (élection), so it stays a SOLO row (not merged
    into the 'election' ring) — the path that needs a per-row translation."""
    s.add(Source(name="S", domain="s.test"))
    s.flush()
    a = Article(url="u", canonical_url="u", source_id=1, title="t", content="c", hash="h")
    s.add(a)
    s.flush()
    for term, norm, lang, m in [("élection", "élection", "fr", 50), ("budget", "budget", "en", 30)]:
        k = Keyword(term=term, normalized_term=norm, language=lang, frequency=0,
                    mention_count=m, article_count=1)
        s.add(k)
        s.flush()
        s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=m, observed_on=date.today()))
    s.commit()


def test_trending_annotates_verified_translation():
    s = _sess()
    _seed_solo(s)
    by = _by_norm(q.trending(s, window_days=7, baseline_days=30, min_recent=1, limit=10, target_lang="en"))
    assert by.get("élection", {}).get("translation") == "election"


def test_trending_windows_threads_target_lang():
    s = _sess()
    _seed_solo(s)
    res = q.trending_windows(s, limit=10, target_lang="en")
    found = False
    for w in res["windows"]:
        for t in w["terms"]:
            if t["normalized"] == "élection":
                assert t.get("translation") == "election"
                found = True
    assert found
