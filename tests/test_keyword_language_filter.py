"""The 'languages I read' filter on the keyword views.

Field ask 2026-06-19: an English-reading user saw top keywords in Arabic (a fully
managed language whose high-volume sources legitimately top the all-languages
ranking). The keyword aggregations gained a ``languages`` filter so a reader can
restrict to languages they read; '?' is the unknown-language bucket. In-memory,
no crypto/network.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database.models import Article, Base, Keyword, KeywordMention, Source


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
    spec = [("election", "en", 100), ("انتخابات", "ar", 90),
            ("élection", "fr", 80), ("mystery", None, 70)]
    for term, lang, m in spec:
        k = Keyword(term=term, normalized_term=term, language=lang, frequency=0,
                    mention_count=m, article_count=1)
        s.add(k)
        s.flush()
        s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=m, observed_on=date.today()))
    s.commit()
    return a


def _norms(res):
    return [t["normalized"] for t in res["terms"]]


def test_norm_langs_and_lang_matches():
    assert q._norm_langs(None) is None and q._norm_langs([]) is None
    assert q._norm_langs([" EN ", "Fr", ""]) == ["en", "fr"]
    assert q._lang_matches("en", ["en", "fr"]) and not q._lang_matches("ar", ["en", "fr"])
    assert q._lang_matches("ar", None)  # no filter -> everything matches
    assert q._lang_matches(None, ["?"]) and not q._lang_matches(None, ["en"])  # unknown bucket


def test_top_terms_filters_by_language():
    s = _sess()
    _seed(s)
    assert set(_norms(q.top_terms(s, limit=10))) == {"election", "انتخابات", "élection", "mystery"}
    # English-only reader never sees the Arabic keyword.
    assert _norms(q.top_terms(s, limit=10, languages=["en"])) == ["election"]
    assert "انتخابات" not in _norms(q.top_terms(s, limit=10, languages=["en", "fr"]))
    # The '?' bucket selects the no-stored-language keyword.
    assert _norms(q.top_terms(s, limit=10, languages=["?"])) == ["mystery"]
    # An empty/None filter is 'all languages' (unchanged behaviour).
    assert len(_norms(q.top_terms(s, limit=10, languages=[]))) == 4


def test_trending_filters_by_language():
    s = _sess()
    _seed(s)
    all_terms = _norms(q.trending(s, window_days=7, baseline_days=30, min_recent=1, limit=10))
    en = _norms(q.trending(s, window_days=7, baseline_days=30, min_recent=1, limit=10, languages=["en"]))
    assert "انتخابات" in all_terms  # Arabic present without a filter
    assert "انتخابات" not in en and "election" in en


def test_trending_windows_threads_language():
    s = _sess()
    _seed(s)
    res = q.trending_windows(s, limit=10, languages=["en"])
    for w in res["windows"]:
        assert all(t["normalized"] != "انتخابات" for t in w["terms"])
