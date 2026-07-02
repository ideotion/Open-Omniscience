"""Library computed figures (field ask 2026-07-02): average article word count,
average keyword mentions per article, and the ingestion rate (lifetime articles/day +
current articles/hour over the last 24 h). All index-backed; counts only, no score."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.api.database import _compute_figures
from src.database.models import Article, Base, Keyword, KeywordMention, Source


def _corpus(session: Session, now: datetime) -> None:
    session.add(Source(id=1, name="Web", domain="w.test", source_type="news"))
    # 3 distinct keywords — keyword_mentions is unique per (keyword, article), so the
    # per-article mention-row count IS the article's distinct-keyword count.
    kws = []
    for term in ("election", "inflation", "drought"):
        k = Keyword(term=term, normalized_term=term, language="en")
        session.add(k)
        kws.append(k)
    session.flush()
    # 4 articles: 2 old (10 days), 2 within the last 24 h; word counts avg 250; 3 keywords each.
    for i, (wc, age_h) in enumerate([(100, 240), (300, 240), (200, 5), (400, 2)]):
        a = Article(
            title=f"a{i}",
            url=f"http://x/{i}",
            canonical_url=f"http://x/{i}",
            source_id=1,
            content="c",
            hash=f"h{i}",
            word_count=wc,
            created_at=now - timedelta(hours=age_h),
        )
        session.add(a)
        session.flush()
        for k in kws:
            session.add(KeywordMention(keyword_id=k.id, article_id=a.id))
    session.commit()


def test_compute_figures_reports_averages_and_rates():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    now = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    with Session(eng) as s:
        _corpus(s, now)
        out = _compute_figures(s, now)
    assert out["articles"] == 4
    assert out["avg_word_count"] == 250.0  # (100+300+200+400)/4
    assert out["avg_keywords_per_article"] == 3.0  # 12 mentions / 4 articles
    assert out["articles_last_24h"] == 2  # the two within 24 h
    assert out["articles_per_hour_recent"] == round(2 / 24, 2)  # current rate over the last day
    assert out["articles_per_day"] > 0  # lifetime average additions/day
    # no score/ranking field anywhere in the payload
    assert not any("score" in k or "rank" in k for k in out)


def test_compute_figures_empty_corpus_is_honest():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    now = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    with Session(eng) as s:
        out = _compute_figures(s, now)
    assert out == {"articles": 0}  # nothing invented on an empty corpus


def test_figures_endpoint_registered_and_wired_into_the_library_tab():
    import pathlib

    from src.api.database import router

    assert "/api/database/figures" in [r.path for r in router.routes]
    app_js = (
        pathlib.Path(__file__).resolve().parents[1] / "src" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    # the Library overview fetches the figures endpoint and renders the four tiles
    assert "/api/database/figures" in app_js
    for label in (
        "Avg words / article",
        "Avg keywords / article",
        "Articles / day (avg since first)",
        "Articles / hour (last 24h)",
    ):
        assert label in app_js, label
