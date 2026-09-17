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
    # A foreign keyword resolves to the UI-language term via its ring. `translate_term`
    # is the RAW lookup and keeps its old answer; the REFUSAL Q412 = a asked for lives on
    # `resolve_translation`, the ladder, so a caller that wants the unguarded answer can
    # still have it and a surface gets the guarded one.
    assert eq.translate_term("fr", "élection", "en") == "election"
    assert eq.translate_term("de", "wahl", "en") == "election"
    # The LADDER refuses both, because each sits in several rings (Q412 = a).
    for lang, term, n in (("fr", "élection", 2), ("de", "wahl", 3)):
        r = eq.resolve_translation(lang, term, "en")
        assert r.tier == eq.TIER_UNTRANSLATED and r.declined == eq.DECLINE_SEVERAL_SENSES_TR
        assert len(r.senses) == n and r.text is None
    # ...and translates a clean single-ring member, tagged with its source language.
    r = eq.resolve_translation("fr", "climat", "en")
    assert r.tier == eq.TIER_VERIFIED and r.text == "climate" and r.source_lang == "fr"
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
    # `élection` / `wahl` are COLLISION-PRONE (each sits in several rings), so since
    # Q412 = a the ladder REFUSES them and offers a sense picker. `climat` / `klima` are
    # clean single-ring members, kept here so the VERIFIED rung is still asserted by this
    # fixture rather than only its refusal -- a fixture that exercised one rung would
    # certify the ladder on a third of its behaviour.
    for term, norm, lang, m in [("élection", "élection", "fr", 50), ("Wahl", "wahl", "de", 40),
                                ("climat", "climat", "fr", 35), ("Klima", "klima", "de", 34),
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
    assert by["climat"]["translation"] == "climate" and by["climat"]["translation_source"] == "ring"
    assert by["climat"]["translation_tier"] == "verified"
    assert by["climat"]["translation_source_lang"] == "fr"
    assert by["klima"]["translation"] == "climate"
    # The colliding members carry no translation but DO carry the refusal + the picker,
    # so the row is honest about why rather than silently blank (Q412 = a).
    assert "translation" not in by["élection"]
    assert by["élection"]["translation_declined"] == "several-senses"
    assert len(by["élection"]["senses"]) == 2
    # An English keyword (same as target) carries NO translation (nothing to add), and
    # says so as `same_language` rather than as `untranslated` -- two different facts.
    assert "translation" not in by["budget"]
    assert by["budget"]["translation_tier"] == "same_language"
    # Without target_lang, no translation field is added (byte-compatible default).
    plain = _by_norm(q.top_terms(s, limit=10, group=False))
    assert all("translation" not in t for t in plain.values())


def _seed_solo(s):
    """Only ONE ring member present (climat), so it stays a SOLO row (not merged into
    the 'climate' ring) — the path that needs a per-row translation.

    `climat` replaced `élection` here on 2026-09-17: `élection` sits in TWO rings, so
    since Q412 = a the ladder refuses it, and a fixture whose only foreign term refuses
    could no longer exercise the per-row VERIFIED path these three tests exist for. The
    refusal has its own assertions in `test_top_terms_annotates_verified_translation`."""
    s.add(Source(name="S", domain="s.test"))
    s.flush()
    a = Article(url="u", canonical_url="u", source_id=1, title="t", content="c", hash="h")
    s.add(a)
    s.flush()
    for term, norm, lang, m in [("climat", "climat", "fr", 50), ("budget", "budget", "en", 30)]:
        k = Keyword(term=term, normalized_term=norm, language=lang, frequency=0,
                    mention_count=m, article_count=1)
        s.add(k)
        s.flush()
        s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=m, observed_on=date.today()))
    s.commit()
    return a


def test_trending_annotates_verified_translation():
    s = _sess()
    _seed_solo(s)
    by = _by_norm(q.trending(s, window_days=7, baseline_days=30, min_recent=1, limit=10, target_lang="en"))
    assert by.get("climat", {}).get("translation") == "climate"
    assert by.get("climat", {}).get("translation_tier") == "verified"


def test_trending_windows_threads_target_lang():
    s = _sess()
    _seed_solo(s)
    res = q.trending_windows(s, limit=10, target_lang="en")
    found = False
    for w in res["windows"]:
        for t in w["terms"]:
            if t["normalized"] == "climat":
                assert t.get("translation") == "climate"
                assert t.get("translation_source_lang") == "fr"
                found = True
    assert found


def test_corpus_keywords_annotates_verified_translation():
    """The analysis-window Keywords subtab is language-aware too (Phase 3)."""
    s = _sess()
    a = _seed_solo(s)
    by = _by_norm(q.corpus_keywords(s, article_ids=[a.id], limit=10, target_lang="en"))
    assert by["climat"]["translation"] == "climate" and by["climat"]["translation_source"] == "ring"
    assert "translation" not in by["budget"]
    # No target_lang -> byte-compatible default (no annotation).
    plain = _by_norm(q.corpus_keywords(s, article_ids=[a.id], limit=10))
    assert all("translation" not in t for t in plain.values())
