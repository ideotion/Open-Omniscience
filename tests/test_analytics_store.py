"""
Tests for keyword-mention persistence + backfill + ingest wiring.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import backfill_corpus, index_article
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _article(db, hash_, text, *, country="fr", title="T", when="2024-03-01"):
    a = Article(
        url=f"https://x.test/{hash_}",
        canonical_url=f"https://x.test/{hash_}",
        source_id=1,
        title=title,
        content=text,
        hash=hash_,
        country=country,
        language="en",
        published_at=datetime.fromisoformat(when).replace(tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    return a


def test_index_article_writes_mentions_with_facets(db):
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    art = _article(
        db,
        "h1",
        "The WHO warned about climate policy. Climate policy and trade dominated talks.",
    )
    res = index_article(db, art, extractor=BaselineExtractor(), country="fr", city="Paris")
    assert res["mentions"] > 0 and res["entities"] >= 1

    # Entities are now ALL-CAPS acronyms only, kept UPPERCASE so they stay distinct
    # from a lowercase homograph (WHO != who) — Title-Case ("Climate Policy") is a
    # topical term, not an entity (PR #283 dropped Title-Case as an entity signal).
    # The entity is one keyword, flagged as entity, with denormalised facets.
    kw = db.query(Keyword).filter_by(normalized_term="WHO").one()
    assert kw.is_entity is True
    m = db.query(KeywordMention).filter_by(keyword_id=kw.id, article_id=art.id).one()
    assert m.country == "fr" and m.city == "Paris"
    assert m.observed_on.isoformat() == "2024-03-01"
    assert m.count >= 1 and m.first_offset is not None


def test_www_pass_flush_failure_does_not_poison_the_session(db, monkeypatch):
    """Field bug (2026-07-15): a UNIQUE-constraint flush failure deep in the
    dates/places/entities pass (there: an unrelated law-tracking revision racing
    a large corpus import; here: reproduced faithfully with a genuine duplicate
    Article.hash flush) used to leave the session's transaction "needs
    rollback" even though index_article's except caught the Python exception --
    every later use of the SAME session then raised a cascading
    PendingRollbackError / "Can't operate on closed transaction", burying the
    real cause. The WWW pass must be isolated in its own savepoint so a failure
    there rolls back on its own, and the keyword mentions already added in this
    same call must survive."""
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    art = _article(db, "h-poison", "Trade policy dominated the summit and trade policy talks continued.")

    from src.timemap import whostore

    def _boom(session, article):
        # A genuine flush-triggered IntegrityError (not a mocked exception) --
        # the same class of failure a real UNIQUE collision produces.
        dup = Article(
            url="https://x.test/dup", canonical_url="https://x.test/dup", source_id=1,
            title="dup", content="dup", hash=art.hash,  # duplicate of art's own hash
            country="fr", language="en",
            published_at=art.published_at, created_at=art.created_at,
        )
        session.add(dup)
        session.flush()
        return 0

    monkeypatch.setattr(whostore, "store_places_for_article", _boom)

    res = index_article(db, art, extractor=BaselineExtractor(), country="fr")
    assert res["places"] == 0  # the WWW pass failed and rolled back, honestly zero

    # The keyword mentions from THIS SAME call must have survived the WWW-pass
    # failure -- the whole point of isolating it in its own savepoint.
    assert db.query(KeywordMention).filter_by(article_id=art.id).count() > 0

    # The session must still be USABLE afterward -- the actual regression: a
    # plain query on the same session must not raise PendingRollbackError.
    assert db.query(Article).filter_by(id=art.id).one().id == art.id
    db.commit()  # and a subsequent commit must succeed cleanly


def test_reindex_is_idempotent(db):
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    art = _article(db, "h2", "Trade policy and trade policy and trade policy again here now.")
    index_article(db, art, extractor=BaselineExtractor())
    n1 = db.query(KeywordMention).filter_by(article_id=art.id).count()
    index_article(db, art, extractor=BaselineExtractor())
    n2 = db.query(KeywordMention).filter_by(article_id=art.id).count()
    assert n1 == n2 and n2 > 0  # replaced, not duplicated


def test_backfill_only_indexes_missing(db):
    db.add(Source(name="S", domain="x.test", country="de"))
    db.commit()
    _article(db, "h3", "Energy prices and energy policy shaped the debate across the region today.")
    _article(
        db, "h4", "Election results surprised analysts and shifted the political landscape sharply."
    )
    r1 = backfill_corpus(db, extractor=BaselineExtractor(), limit=10)
    assert r1["indexed"] == 2 and r1["remaining"] == 0
    # Running again indexes nothing new (all already have mentions).
    r2 = backfill_corpus(db, extractor=BaselineExtractor(), limit=10)
    assert r2["indexed"] == 0


def _kw_set(db, article_id):
    """The set of (normalized_term, count) keyword mentions for one article."""
    rows = (
        db.query(KeywordMention.count, Keyword.normalized_term)
        .join(Keyword, Keyword.id == KeywordMention.keyword_id)
        .filter(KeywordMention.article_id == article_id)
        .all()
    )
    return {(term, cnt) for cnt, term in rows}


def test_keyword_only_scope_skips_when_where_who_and_sentiment(db):
    """Phase 1.2: scope="keywords" runs the keyword pass ONLY — it leaves the
    dates/places/entities + sentiment untouched (a fast keyword cleanup)."""
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    art = _article(db, "h1", "The WHO warned about climate policy and trade in Paris on 5 March 2024.")
    ex = BaselineExtractor()
    full = index_article(db, art, extractor=ex, scope="full")
    assert full["mentions"] > 0
    # Mark sentiment with a sentinel, then a KEYWORD-ONLY re-index.
    art.sentiment_score, art.sentiment_label = 0.999, "sentinel"
    db.commit()
    kwonly = index_article(db, art, extractor=ex, scope="keywords")
    # when/where/who passes were skipped (tally zeros) but keywords still extracted.
    assert kwonly["dates"] == 0 and kwonly["places"] == 0 and kwonly["entities_stored"] == 0
    assert kwonly["mentions"] > 0
    a = db.get(Article, art.id)
    assert a.sentiment_score == 0.999 and a.sentiment_label == "sentinel"  # untouched
    # Contrast: a FULL re-index DOES recompute sentiment (away from the sentinel).
    index_article(db, art, extractor=ex, scope="full")
    assert db.get(Article, art.id).sentiment_label != "sentinel"


def test_keyword_only_scope_produces_identical_keyword_rows_to_full(db):
    """The keyword rows from a keyword-only pass match a full pass exactly."""
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    text = "The election results show major inflation across the global economy."
    a1 = _article(db, "h1", text)
    a2 = _article(db, "h2", text)
    ex = BaselineExtractor()
    index_article(db, a1, extractor=ex, scope="full")
    index_article(db, a2, extractor=ex, scope="keywords")
    assert _kw_set(db, a1.id) == _kw_set(db, a2.id)
    assert _kw_set(db, a1.id)  # non-empty (the comparison isn't vacuous)


# --- Phase 1.3: batched re-index commits (COLLECTOR_WRITER_BATCHING.md) ------- #


def _mentions_snapshot(db):
    """All (article_id, keyword_id, count) mention rows — compared across runs."""
    return sorted(
        (m.article_id, m.keyword_id, m.count) for m in db.query(KeywordMention).all()
    )


def _live_counters(db):
    """The authoritative per-keyword counts from the live GROUP BY over mentions."""
    from sqlalchemy import distinct, func

    rows = (
        db.query(
            KeywordMention.keyword_id,
            func.sum(KeywordMention.count),
            func.count(distinct(KeywordMention.article_id)),
        )
        .group_by(KeywordMention.keyword_id)
        .all()
    )
    return {kid: (int(s), int(a)) for kid, s, a in rows}


def _stored_counters(db):
    """The denormalised counters on the Keyword rows (for keywords with mentions)."""
    return {
        kw.id: (kw.mention_count, kw.article_count)
        for kw in db.query(Keyword).filter(Keyword.mention_count > 0).all()
    }


def test_batched_reindex_matches_per_article_and_keeps_counters_exact(db):
    """The killer no-loss assert (Phase 1.3): a batched re-index (commit_batch>1)
    produces IDENTICAL keyword rows + IDENTICAL counters to the per-article path, and
    the counters equal the live GROUP BY (no drift from batching)."""
    from src.analytics.store import reindex_all_batch

    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    ex = BaselineExtractor()
    # Several articles SHARING keywords, so counter deltas accumulate within a batch.
    for i in range(7):
        _article(db, f"h{i}", "Election results show inflation across the global economy and trade.", title=f"T{i}")

    r1 = reindex_all_batch(db, extractor=ex, limit=100, commit_batch=1)  # per-article
    assert r1["reindexed"] == 7 and r1["failed"] == 0
    snap1, ctr1 = _mentions_snapshot(db), _stored_counters(db)

    r2 = reindex_all_batch(db, extractor=ex, limit=100, commit_batch=3)  # batched (idempotent re-run)
    assert r2["reindexed"] == 7 and r2["failed"] == 0
    snap2, ctr2 = _mentions_snapshot(db), _stored_counters(db)

    assert snap1 == snap2  # identical mention rows
    assert ctr1 == ctr2  # identical denormalised counters
    assert ctr2 == _live_counters(db)  # counters == the live GROUP BY (zero drift)


def test_batched_reindex_failure_fallback_loses_nothing(db):
    """A failure building ONE article mid-batch rolls the batch back and redoes it
    per-article — every other article is fully indexed and the counters stay exact
    (no half-batch, no data loss). Mirrors the proven ingest_emails fallback."""
    from src.analytics.store import reindex_all_batch

    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    ex = BaselineExtractor()
    for i in range(6):
        _article(db, f"h{i}", "Energy prices and the drought pushed agriculture costs higher today.", title=f"T{i}")
    arts = db.query(Article).order_by(Article.id).all()
    bad_id = arts[2].id  # "T2" raises during extraction, mid-batch

    class _FlakyExtractor:
        name = ex.name

        def extract(self, content, *, title="", language="en"):
            if title == "T2":
                raise RuntimeError("boom")
            return ex.extract(content, title=title, language=language)

    r = reindex_all_batch(db, extractor=_FlakyExtractor(), limit=100, commit_batch=4)
    assert r["failed"] == 1 and r["reindexed"] == 5
    for a in arts:
        n = db.query(KeywordMention).filter_by(article_id=a.id).count()
        assert n == 0 if a.id == bad_id else n > 0  # only the bad one lost its mentions
    assert _stored_counters(db) == _live_counters(db)  # counters exact despite the failure


# --- Phase 4.2: reconcile_keyword_language ----------------------------------- #


def _lang_article(db, hash_, lang):
    a = Article(
        url=f"https://x.test/{hash_}",
        canonical_url=f"https://x.test/{hash_}",
        source_id=1,
        title="t",
        content="body",
        hash=hash_,
        language=lang,
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.flush()
    return a


def _kw_row(db, term, lang):
    k = Keyword(term=term, normalized_term=term, language=lang)
    db.add(k)
    db.flush()
    return k


def _mention_row(db, kw, art):
    db.add(KeywordMention(keyword_id=kw.id, article_id=art.id, count=1))


def test_reconcile_keyword_language_sets_signature_majority(db):
    """A keyword first-written in a mis-detected language is re-languaged to its
    signature-majority article language; NULL gets a language; low-confidence and
    already-correct keywords are left alone."""
    from src.analytics.store import reconcile_keyword_language

    db.add(Source(name="S", domain="x.test"))
    db.commit()
    # K1 stored "en" but mentioned in 2 fr + 1 en article -> signature fr -> flip.
    k1 = _kw_row(db, "inflation", "en")
    for h, lg in [("a1", "fr"), ("a2", "fr"), ("a3", "en")]:
        _mention_row(db, k1, _lang_article(db, h, lg))
    # K2 stored NULL, mentioned in 2 en articles -> signature en -> set en.
    k2 = _kw_row(db, "election", None)
    for h in ("b1", "b2"):
        _mention_row(db, k2, _lang_article(db, h, "en"))
    # K3 stored "en", only 1 fr article (below min_articles) -> unchanged.
    k3 = _kw_row(db, "drought", "en")
    _mention_row(db, k3, _lang_article(db, "c1", "fr"))
    # K4 stored "en", 3 en articles (already matches its signature) -> unchanged.
    k4 = _kw_row(db, "economy", "en")
    for h in ("d1", "d2", "d3"):
        _mention_row(db, k4, _lang_article(db, h, "en"))
    db.commit()

    out = reconcile_keyword_language(db)
    assert out["relanguaged"] == 2
    assert out["lang_to_lang"] == 1 and out["null_to_lang"] == 1
    db.expire_all()
    assert db.get(Keyword, k1.id).language == "fr"  # en -> fr (2 fr majority)
    assert db.get(Keyword, k2.id).language == "en"  # NULL -> en
    assert db.get(Keyword, k3.id).language == "en"  # single article -> unchanged
    assert db.get(Keyword, k4.id).language == "en"  # already matches -> unchanged


def test_reconcile_keyword_language_no_majority_is_left_alone(db):
    """A 1-fr / 1-en split has no clear majority (not > half) -> not flipped."""
    from src.analytics.store import reconcile_keyword_language

    db.add(Source(name="S", domain="x.test"))
    db.commit()
    k = _kw_row(db, "trade", "en")
    _mention_row(db, k, _lang_article(db, "e1", "fr"))
    _mention_row(db, k, _lang_article(db, "e2", "en"))
    db.commit()
    out = reconcile_keyword_language(db)
    assert out["relanguaged"] == 0
    db.expire_all()
    assert db.get(Keyword, k.id).language == "en"  # tie -> conservative, unchanged


def test_reconcile_keyword_language_untagged_bucket_is_noop(db):
    """Keywords whose mentions are ALL in untagged (NULL-language) articles -> the
    "?" bucket, left as-is (query-time global_stopwords handles those)."""
    from src.analytics.store import reconcile_keyword_language

    db.add(Source(name="S", domain="x.test"))
    db.commit()
    k = _kw_row(db, "inflation", "en")
    _mention_row(db, k, _lang_article(db, "n1", None))
    db.commit()
    out = reconcile_keyword_language(db)
    assert out["relanguaged"] == 0
    db.expire_all()
    assert db.get(Keyword, k.id).language == "en"


# --- 2026-07-02: reconcile_article_language (deduce UNKNOWN articles' language) ---- #


def _unknown_article(db, hash_, text):
    """An article with NEITHER an asserted language NOR a detected one."""
    a = Article(
        url=f"https://x.test/{hash_}",
        canonical_url=f"https://x.test/{hash_}",
        source_id=1,
        title="t",
        content=text,
        hash=hash_,
        language=None,
        detected_language=None,
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.flush()
    return a


_FR_PARAGRAPH = (
    "Le gouvernement a annoncé aujourd'hui une nouvelle réforme économique visant à "
    "réduire l'inflation et à soutenir les entreprises locales du pays. Les syndicats "
    "ont exprimé leurs inquiétudes tandis que les experts saluent une décision "
    "courageuse pour l'avenir de la nation et de tous ses citoyens réunis."
)


def test_reconcile_article_language_text_detect_sets_deduced(db):
    """The offline text detector deduces the language of a long unknown article and
    stores it in detected_language WITHOUT ever writing the asserted language."""
    pytest.importorskip("py3langid")  # the [analysis] lib; a core install -> graceful None
    from src.analytics.store import reconcile_article_language

    art = _unknown_article(db, "u1", _FR_PARAGRAPH)
    db.commit()
    out = reconcile_article_language(db)
    assert out["scanned"] == 1 and out["set_by_text"] == 1
    assert out["set_by_keywords"] == 0 and out["still_unknown"] == 0
    assert out["done"] is True
    db.expire_all()
    a = db.get(Article, art.id)
    assert a.detected_language == "fr"  # deduced channel set
    assert not a.language  # asserted language NEVER written


def test_reconcile_article_language_keyword_majority_fallback(db):
    """When the text detector fails (too-short content), the dominant language among the
    article's own indexed keywords deduces it — evidence, stored in detected_language."""
    from src.analytics.store import reconcile_article_language

    art = _unknown_article(db, "u2", "short")  # < min_chars -> text detect returns None
    # 3 fr keywords + 1 en keyword -> clear fr majority (>= 3, > half).
    for term in ("gouvernement", "reforme", "inflation"):
        _mention_row(db, _kw_row(db, term, "fr"), art)
    _mention_row(db, _kw_row(db, "policy", "en"), art)
    db.commit()
    out = reconcile_article_language(db)
    assert out["scanned"] == 1 and out["set_by_keywords"] == 1
    assert out["set_by_text"] == 0 and out["still_unknown"] == 0
    db.expire_all()
    a = db.get(Article, art.id)
    assert a.detected_language == "fr" and not a.language


def test_reconcile_article_language_never_overwrites_asserted(db):
    """An article that already carries an asserted language is not a candidate — its
    language is untouched and no deduced language is written."""
    from src.analytics.store import reconcile_article_language

    a = _lang_article(db, "u3", "en")  # asserted en
    a.content = _FR_PARAGRAPH  # French text, but the asserted en must win
    db.commit()
    out = reconcile_article_language(db)
    assert out["scanned"] == 0 and out["done"] is True
    db.expire_all()
    a2 = db.get(Article, a.id)
    assert a2.language == "en" and not a2.detected_language


def test_reconcile_article_language_tie_or_too_few_left_unknown(db):
    """A keyword-language tie and a too-few-keywords case both stay honestly unknown."""
    from src.analytics.store import reconcile_article_language

    tie = _unknown_article(db, "u4", "short")  # 1 fr + 1 en -> no majority
    _mention_row(db, _kw_row(db, "gouvernement", "fr"), tie)
    _mention_row(db, _kw_row(db, "policy", "en"), tie)
    few = _unknown_article(db, "u5", "short")  # 2 fr only -> below min_keywords=3
    for term in ("reforme", "inflation"):
        _mention_row(db, _kw_row(db, term, "fr"), few)
    db.commit()
    out = reconcile_article_language(db)
    assert out["scanned"] == 2 and out["still_unknown"] == 2
    assert out["set_by_text"] == 0 and out["set_by_keywords"] == 0
    db.expire_all()
    assert not db.get(Article, tie.id).detected_language
    assert not db.get(Article, few.id).detected_language


def test_reconcile_article_language_is_idempotent(db):
    """A second pass re-scans nothing (a resolved article is excluded by the filter)."""
    pytest.importorskip("py3langid")  # the [analysis] lib; a core install -> graceful None
    from src.analytics.store import reconcile_article_language

    _unknown_article(db, "u6", _FR_PARAGRAPH)
    db.commit()
    first = reconcile_article_language(db)
    assert first["set_by_text"] == 1
    second = reconcile_article_language(db)
    assert second["scanned"] == 0 and second["done"] is True
