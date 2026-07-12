"""S4.6: the in-app generic_terms detector block (engine_report) — DF-ubiquity open-class
stoplist candidates folded into the routine diagnostics export. Propose, human judges, NEVER
auto-apply; no score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.engine_report import _generic_terms
from src.analytics.extract import global_stopwords
from src.database.models import Base, Keyword, KeywordTag


def _session():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def _kw(norm, arts, ments, *, entity=False, ngram=False, lang="en", term=None):
    return Keyword(normalized_term=norm, term=term or norm, language=lang,
                   is_entity=entity, is_ngram=ngram, article_count=arts, mention_count=ments)


def _assert_no_score_keys(obj) -> None:
    # No-score is enforced on field NAMES, not a repr() substring (a legitimate 'No score'
    # disclaimer trips the naive check — the ledger lesson).
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert "score" not in k.lower() and "ranking" not in k.lower(), k
            _assert_no_score_keys(v)
    elif isinstance(obj, list):
        for it in obj:
            _assert_no_score_keys(it)


def test_generic_terms_surfaces_high_df_and_excludes_the_right_things():
    from src.analytics.equivalence import is_ring_term

    stop = global_stopwords()
    # preconditions: 'global' is a genuine non-ring open-class candidate; 'health' is a ring
    # CONCEPT (so it must be excluded — a known concept is not open-class garbage); 'monday' is
    # already stoplisted.
    assert "global" not in stop and is_ring_term("global") is False
    assert is_ring_term("health") is True
    assert "monday" in stop
    s = _session()
    s.add_all([
        _kw("global", 90, 200),                     # high-df generic, non-ring -> a candidate
        _kw("widgetx", 80, 150),                    # high-df non-ring -> a candidate (tagged below)
        _kw("health", 75, 140),                     # a RING concept -> excluded
        _kw("monday", 70, 100),                     # weekday (in the stoplist) -> excluded
        _kw("WHO", 60, 90, term="WHO"),             # acronym -> excluded
        _kw("climate policy", 50, 80, ngram=True),  # n-gram -> excluded
        _kw("macron", 40, 60, entity=True),         # entity -> excluded
        _kw("obscure", 1, 1),                       # below the df floor (article_count<=1)
    ])
    s.commit()
    wid = s.query(Keyword.id).filter(Keyword.normalized_term == "widgetx").scalar()
    s.add(KeywordTag(keyword_id=wid, axis="topic", tag="tech", source="baseline"))
    s.commit()

    r = _generic_terms(s, top_per_lang=10)
    en = {i["normalized"]: i for i in r["by_language"].get("en", [])}
    assert "global" in en and en["global"]["tagged"] is False   # high-df generic surfaces
    assert "widgetx" in en and en["widgetx"]["tagged"] is True   # tagged known topic flagged
    for excluded in ("health", "monday", "who", "climate policy", "macron", "obscure"):
        assert excluded not in en, excluded                     # ring/stop/acronym/ngram/entity/floor
    assert en["global"]["df_ratio"] == 1.0                       # self-normalises to the commonest
    assert 0 < en["widgetx"]["df_ratio"] <= 1.0
    assert r["candidate_terms"] == len(en)
    # NO score field anywhere (the non-negotiable) + no internal id leaks
    _assert_no_score_keys(r)
    assert all("id" not in row for row in en.values())


def test_generic_terms_empty_corpus_is_safe():
    r = _generic_terms(_session())
    assert r["candidate_terms"] == 0 and r["by_language"] == {}
