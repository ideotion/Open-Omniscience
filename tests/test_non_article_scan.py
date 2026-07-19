"""
Slice 4a (review half) — the retroactive non-article SCAN. Count-only (url + word_count, no content
decrypt), the #659 URL-shape rules only, high-precision by design.

NEGATIVE SPACE: a real article (substantial word_count) is NEVER flagged whatever its URL; a SHORT
real brief at an article path is NOT flagged (only clear URL-shaped nav/section/tag/homepage pages
with a thin body are).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.analytics.non_article_scan import scan_non_article_candidates, suspected_non_article_ids
from src.database.models import Article, Base, Source

_BANNED = ("score", "ranking", "rating", "grade")


def _walk_no_score(o) -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            assert not any(b in str(k).lower() for b in _BANNED), k
            _walk_no_score(v)
    elif isinstance(o, list):
        for v in o:
            _walk_no_score(v)


def _corpus() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    src = Source(name="News", domain="news.example", language="en", enabled=True)
    s.add(src)
    s.flush()
    aid = [0]

    def add(url, wc):
        aid[0] += 1
        s.add(Article(url=url, canonical_url=url, source_id=src.id, content="x", hash=f"h{aid[0]}",
                      word_count=wc, language="en", title=f"t{aid[0]}"))

    add("https://news.example/2026/07/election-results", 500)  # real article — kept (wc>=100)
    add("https://news.example/2026/07/short-brief", 20)        # SHORT real brief at an article path — kept
    add("https://news.example/", 10)                            # homepage
    add("https://news.example/tag/gaza", 5)                     # taxonomy listing
    add("https://news.example/business", 8)                     # section landing
    add("https://news.example/tag/economy", 4)                  # taxonomy again
    s.commit()
    return s


def test_scan_flags_url_shaped_non_articles_but_never_a_real_one():
    s = _corpus()
    out = scan_non_article_candidates(s)
    assert out["scanned"] == 6
    signals = {r["signal"]: r["count"] for r in out["by_reason"]}
    assert signals.get("url_homepage") == 1
    assert signals.get("url_taxonomy") == 2   # both /tag/ pages
    assert signals.get("url_section") == 1
    assert out["flagged"] == 4                 # the two REAL articles (500 words, and the 20-word
    #                                            brief at an article path) are NOT flagged
    assert out["reversible"] is True
    _walk_no_score(out)


def test_a_substantial_body_is_kept_regardless_of_a_nav_shaped_url():
    # NEGATIVE SPACE: even a section/tag-shaped URL is kept if the stored body is substantial
    # (a real article that happens to live at /business) — the classifier's load-bearing guarantee.
    s = _corpus()
    s.add(Article(url="https://news.example/business", canonical_url="https://news.example/business/x",
                  source_id=s.query(Source).one().id, content="x", hash="hBIG", word_count=900,
                  language="en", title="big"))
    s.commit()
    out = scan_non_article_candidates(s)
    # still only 1 url_section (the 8-word one); the 900-word /business article is kept
    assert {r["signal"]: r["count"] for r in out["by_reason"]}.get("url_section") == 1


def test_bounded_id_sample_per_reason():
    s = _corpus()
    out = scan_non_article_candidates(s, sample_per_reason=1)
    tax = next(r for r in out["by_reason"] if r["signal"] == "url_taxonomy")
    assert tax["count"] == 2 and len(tax["sample_ids"]) == 1  # count is full, the sample is bounded


def test_suspected_non_article_ids_scoped_to_a_member_set():
    """S1.4 (row 10): a cluster-building producer's member-exclusion seam — scoped to a
    SPECIFIC id set (never the whole corpus), never flags a real article, and returns []
    for an empty input rather than scanning everything."""
    s = _corpus()
    ids = [a.id for a in s.query(Article).order_by(Article.id).all()]
    real_id, brief_id, home_id, tag1_id, section_id, tag2_id = ids

    out = suspected_non_article_ids(s, ids)
    assert out == {home_id, tag1_id, section_id, tag2_id}
    assert real_id not in out and brief_id not in out  # real content is never flagged

    # Scoped to just the real article + the homepage capture:
    assert suspected_non_article_ids(s, [real_id, home_id]) == {home_id}
    assert suspected_non_article_ids(s, []) == set()
