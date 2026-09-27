"""The two language passes hold a few bytes per keyword, not a Python object per keyword.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FIELD CASE (crash bundle, 2026-09-26, a 3.9 GB machine with 2.98 M keywords): one
session died six minutes after a collect pass ended, with the 12-hourly keyword clean-up
due and never recorded as finished. Its language reconcile held every keyword's vote in a
``dict[int, dict[str, int]]`` (294 bytes a keyword, measured) and then read every keyword
through an ORM query that does not stream (313 bytes a keyword): about 1.8 GB at that
corpus size, on top of the running app. The per-article pass beside it read every
keyword's language into a dict on every batch.

The votes now live in two arrays indexed by keyword id, the keywords are read in keyset
chunks, the corrections are written in batches, and the per-article pass looks up only
the keywords its batch mentions. Memory is MEASURED with ``tracemalloc`` at N and 4N
keywords, and the decisions are checked against an independent statement of the rule.
"""

from __future__ import annotations

import gc
import random
import tracemalloc
from collections import Counter

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from src.analytics import store
from src.analytics.managed import normalize_lang
from src.analytics.store import (
    _LanguageVotes,
    reconcile_article_language,
    reconcile_keyword_language,
)
from src.database import query as query_mod
from src.database.models import Base

_SMALL = 4_000
_LARGE = 4 * _SMALL


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = sa.create_engine(
        f"sqlite:///{tmp_path / 'v.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.execute(sa.text("INSERT INTO sources (id, name, domain) VALUES (1, 'S', 's.test')"))
    s.commit()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _article(s, aid: int, *, language=None, detected=None, content="x") -> None:
    s.execute(
        sa.text(
            "INSERT INTO articles (id, url, canonical_url, source_id, content, hash, "
            "language, detected_language) VALUES (:i, :u, :u, 1, :c, :h, :l, :d)"
        ),
        {"i": aid, "u": f"https://s.test/{aid}", "c": content, "h": f"h{aid}",
         "l": language, "d": detected},
    )


def _peak_bytes(fn) -> int:
    gc.collect()
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


# ------------------------------ the tally itself ------------------------------ #


def test_a_keyword_that_meets_a_second_language_keeps_every_count():
    v = _LanguageVotes()
    for _ in range(3):
        v.add(5, "en")
    assert v.get(5) == {"en": 3}
    v.add(5, "fr")
    assert v.get(5) == {"en": 3, "fr": 1}
    v.add(5, "en")
    assert v.get(5) == {"en": 4, "fr": 1}
    assert v.get(4) is None and v.get(6) is None
    assert v.keywords == 1


def test_past_255_languages_the_tally_still_counts():
    """A slot is one byte; the 256th distinct code has none, and must still be counted."""
    v = _LanguageVotes()
    codes = [f"x{i}" for i in range(300)]
    for kid, code in enumerate(codes, start=1):
        v.add(kid, code)
        v.add(kid, code)
    for code in codes:  # every code on one keyword too
        v.add(1000, code)
    assert all(v.get(kid) == {code: 2} for kid, code in enumerate(codes, start=1))
    assert v.get(1000) == dict.fromkeys(codes, 1)
    assert v.keywords == 301


def test_an_id_outside_the_arrays_is_counted_in_the_dict(monkeypatch):
    """A sparse or huge id must never size an array; it is counted all the same."""
    monkeypatch.setattr(store, "_VOTE_DENSE_IDS", 16)
    v = _LanguageVotes()
    v.add(3, "en")
    v.add(100, "en")
    v.add(100, "en")
    v.add(-1, "fr")
    assert v.get(3) == {"en": 1}
    assert v.get(100) == {"en": 2}
    assert v.get(-1) == {"fr": 1}
    assert len(v._first) < 16, "an id past the limit grew the arrays"
    assert v.keywords == 3


# --------------------- the decisions, against the rule itself --------------------- #


def _random_corpus(s, seed: int) -> tuple[dict, list]:
    """Keywords, articles and mentions covering every branch of the rule: votes from the
    mention's own language (including an unnormalised ``en-US``), votes from the
    article's asserted or deduced language, mentions with no language anywhere, keywords
    in several languages, and stored languages that are missing, right, a respelling, or
    wrong."""
    rng = random.Random(seed)
    art_langs = [("en", None), ("fr", None), ("de", None), ("en-US", None),
                 (None, "es"), (None, "pt-BR"), (None, None)]
    arts = {}
    for aid in range(1, 121):
        lang, det = rng.choice(art_langs)
        _article(s, aid, language=lang, detected=det)
        arts[aid] = (lang, det)
    stored = {}
    for kid in range(1, 151):
        stored[kid] = rng.choice([None, "en", "fr", "en-US", "de", "es"])
        s.execute(
            sa.text("INSERT INTO keywords (id, term, normalized_term, language) "
                    "VALUES (:i, :t, :t, :l)"),
            {"i": kid, "t": f"k{kid}", "l": stored[kid]},
        )
    mentions = []
    for kid in range(1, 151):
        leaning = rng.choice(["en", "fr", "de", "es", "en-US"])
        for aid in rng.sample(range(1, 121), rng.randint(0, 6)):
            roll = rng.random()
            lang = leaning if roll < 0.45 else (
                rng.choice(["en", "fr", "de"]) if roll < 0.6 else None)
            s.execute(
                sa.text("INSERT INTO keyword_mentions (keyword_id, article_id, count, language) "
                        "VALUES (:k, :a, 1, :l)"),
                {"k": kid, "a": aid, "l": lang},
            )
            mentions.append((kid, aid, lang))
    s.commit()
    return {"arts": arts, "stored": stored}, mentions


def _oracle(corpus: dict, mentions: list, *, min_articles: int = 2) -> tuple[dict, dict]:
    """The rule as the docstring states it, written out without the code under test."""
    def article_vote(aid):
        lang, det = corpus["arts"][aid]
        known = (lang or "").strip() or (det or "").strip()
        return (normalize_lang(known) or None) if known else None

    votes: dict[int, Counter] = {}
    tally = Counter()
    for kid, aid, lang in mentions:
        if lang:
            tally["votes_from_mentions"] += 1
        else:
            lang = article_vote(aid)
            if lang is None:
                tally["mentions_unmeasured"] += 1
                continue
            tally["votes_from_articles"] += 1
        votes.setdefault(kid, Counter())[lang] += 1
    final = dict(corpus["stored"])
    for kid, counts in votes.items():
        total = sum(counts.values())
        sig_lang, sig_n = counts.most_common(1)[0]
        if sig_n < min_articles or sig_n * 2 <= total:
            continue
        stored = corpus["stored"][kid]
        if (stored or None) == sig_lang:
            continue
        final[kid] = sig_lang
        if stored and normalize_lang(stored) == sig_lang:
            tally["respelled"] += 1
        else:
            tally["relanguaged"] += 1
            tally["lang_to_lang" if stored else "null_to_lang"] += 1
    tally["keywords_with_signature"] = len(votes)
    return dict(tally), final


@pytest.mark.parametrize("dense_ids", [1 << 25, 40])
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_the_reconcile_decides_exactly_what_the_rule_says(db, monkeypatch, seed, dense_ids):
    """Across every chunk and batch edge (tiny chunks here), and with some keywords
    counted in the arrays and some in the dict."""
    monkeypatch.setattr(store, "_LANG_SCAN_CHUNK", 7)
    monkeypatch.setattr(query_mod, "KEYSET_CHUNK", 11)
    monkeypatch.setattr(store, "_LANG_UPDATE_BATCH", 5)
    monkeypatch.setattr(store, "_VOTE_DENSE_IDS", dense_ids)
    corpus, mentions = _random_corpus(db, seed)
    want_tally, want_final = _oracle(corpus, mentions)
    out = reconcile_keyword_language(db)
    assert out["complete"] is True
    for key in ("keywords_with_signature", "relanguaged", "null_to_lang", "lang_to_lang",
                "respelled", "votes_from_mentions", "votes_from_articles",
                "mentions_unmeasured"):
        assert out[key] == want_tally.get(key, 0), (key, out, want_tally)
    got_final = dict(db.execute(sa.text("SELECT id, language FROM keywords")).all())
    assert got_final == want_final
    # ANTI-VACUITY: the corpus exercised the branches the rule has.
    assert want_tally.get("relanguaged", 0) and want_tally.get("votes_from_articles", 0)


def test_corrections_are_written_in_batches(db, monkeypatch):
    monkeypatch.setattr(store, "_LANG_UPDATE_BATCH", 4)
    _article(db, 1, language="en")
    _article(db, 2, language="en")
    for kid in range(1, 11):
        db.execute(sa.text("INSERT INTO keywords (id, term, normalized_term) VALUES (:i, :t, :t)"),
                   {"i": kid, "t": f"k{kid}"})
        for aid in (1, 2):
            db.execute(sa.text("INSERT INTO keyword_mentions (keyword_id, article_id, count, "
                               "language) VALUES (:k, :a, 1, 'en')"), {"k": kid, "a": aid})
    db.commit()
    sizes: list[int] = []
    real = store._write_keyword_languages

    def spy(session, updates):
        sizes.append(len(updates))
        real(session, updates)

    monkeypatch.setattr(store, "_write_keyword_languages", spy)
    out = reconcile_keyword_language(db)
    assert sizes == [4, 4, 2]
    assert out["null_to_lang"] == 10
    assert db.execute(sa.text("SELECT count(*) FROM keywords WHERE language = 'en'")).scalar() == 10


# ------------------------------ memory, measured ------------------------------ #


def _grow_voted_keywords(s, upto: int, *, stored: str | None) -> None:
    """Keywords 1..upto, each mentioned once by article 1 in English (idempotent)."""
    if s.execute(sa.text("SELECT count(*) FROM articles")).scalar() == 0:
        _article(s, 1, language="en")
    s.execute(sa.text(
        "WITH RECURSIVE c(i) AS (SELECT (SELECT coalesce(max(id), 0) + 1 FROM keywords) "
        "UNION ALL SELECT i + 1 FROM c WHERE i < :upto) "
        "INSERT INTO keywords (id, term, normalized_term, language) "
        "SELECT i, 'k' || i, 'k' || i, :stored FROM c"
    ), {"upto": upto, "stored": stored})
    s.execute(sa.text(
        "INSERT INTO keyword_mentions (keyword_id, article_id, count, language) "
        "SELECT k.id, 1, 1, 'en' FROM keywords k "
        "WHERE NOT EXISTS (SELECT 1 FROM keyword_mentions m WHERE m.keyword_id = k.id)"
    ))
    s.commit()


@pytest.mark.parametrize("stored", ["en", None], ids=["steady-state", "every-keyword-corrected"])
def test_the_keyword_reconcile_does_not_hold_every_keyword(db, monkeypatch, stored):
    """Steady state (nothing to correct) and a first run (everything to correct: the
    stored language is reset to NULL before each read, so both reads write every row)."""
    monkeypatch.setattr(store, "_LANG_SCAN_CHUNK", 500)
    monkeypatch.setattr(query_mod, "KEYSET_CHUNK", 500)
    monkeypatch.setattr(store, "_LANG_UPDATE_BATCH", 500)

    def read():
        if stored is None:
            db.execute(sa.text("UPDATE keywords SET language = NULL"))
            db.commit()
        out = reconcile_keyword_language(db, min_articles=1)
        assert out["complete"] is True

    _grow_voted_keywords(db, _SMALL, stored=stored)
    read()
    small = _peak_bytes(read)
    _grow_voted_keywords(db, _LARGE, stored=stored)
    large = _peak_bytes(read)
    assert large / small < 2.0, (small, large)


def test_the_article_pass_reads_only_the_keywords_its_batch_mentions(db):
    """One unknown article whose own keywords say French, beside a keyword table that
    grows fourfold: the pass's memory must not grow with the table."""
    _article(db, 1, content="x")  # no language of either class; too short to detect
    for kid in (1, 2, 3):
        db.execute(sa.text("INSERT INTO keywords (id, term, normalized_term, language) "
                           "VALUES (:i, :t, :t, 'fr')"), {"i": kid, "t": f"fr{kid}"})
        db.execute(sa.text("INSERT INTO keyword_mentions (keyword_id, article_id, count) "
                           "VALUES (:k, 1, 1)"), {"k": kid})
    db.commit()

    def grow(upto):
        db.execute(sa.text(
            "WITH RECURSIVE c(i) AS (SELECT (SELECT max(id) + 1 FROM keywords) "
            "UNION ALL SELECT i + 1 FROM c WHERE i < :upto) "
            "INSERT INTO keywords (id, term, normalized_term, language) "
            "SELECT i, 'en' || i, 'en' || i, 'en' FROM c"
        ), {"upto": upto})
        db.commit()

    results: list[dict] = []

    def read():
        db.execute(sa.text("UPDATE articles SET detected_language = NULL"))
        db.commit()
        results.append(reconcile_article_language(db, limit=10))

    grow(_SMALL)
    read()
    small = _peak_bytes(read)
    grow(_LARGE)
    large = _peak_bytes(read)
    assert large / small < 2.0, (small, large)
    assert all(r["set_by_keywords"] == 1 for r in results), results
    assert db.execute(sa.text("SELECT detected_language FROM articles")).scalar() == "fr"


def test_the_article_pass_looks_up_every_chunk_of_its_keywords(db):
    """1,200 keywords span three 500-id lookups. The deduction needs ALL of them
    (``min_keywords=1200``), so a lookup that skipped a chunk would deduce nothing."""
    _article(db, 1, content="x")
    for kid in range(1, 1201):
        db.execute(sa.text("INSERT INTO keywords (id, term, normalized_term, language) "
                           "VALUES (:i, :t, :t, 'fr')"), {"i": kid, "t": f"fr{kid}"})
        db.execute(sa.text("INSERT INTO keyword_mentions (keyword_id, article_id, count) "
                           "VALUES (:k, 1, 1)"), {"k": kid})
    db.commit()
    out = reconcile_article_language(db, limit=10, min_keywords=1200)
    assert out["set_by_keywords"] == 1, out
